import os
import wave
import logging
import threading
import subprocess
import numpy as np
from datetime import datetime
import pyaudiowpatch as pyaudio
from recorder.devices import find_loopback_device, find_mic_device

log = logging.getLogger(__name__)

CHUNK = 512
FORMAT = pyaudio.paInt16


class Recorder:
    def __init__(self, settings: dict):
        self._settings = settings
        self._thread = None
        self._stop_event = threading.Event()
        self._output_path = None

    def update_settings(self, settings: dict):
        self._settings = settings

    @property
    def is_recording(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_file(self):
        return self._output_path

    def start(self, session_info: list[dict]):
        if self.is_recording:
            return

        now = datetime.now()
        day_dir = os.path.join(
            self._settings["recordings_dir"], now.strftime("%Y-%m-%d")
        )
        os.makedirs(day_dir, exist_ok=True)

        tag = now.strftime("meet_%Y-%m-%d_%H-%M-%S")
        self._output_path = os.path.join(day_dir, f"{tag}.wav")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        log.info(f"Recording started -> {self._output_path}")

    def stop(self):
        if not self.is_recording:
            return
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None
        log.info(f"Recording stopped -> {self._output_path}")

        if self._settings.get("audio_format") == "mp3":
            self._convert_to_mp3()

    def _convert_to_mp3(self):
        wav_path = self._output_path
        mp3_path = wav_path.replace(".wav", ".mp3")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", mp3_path],
                capture_output=True, check=True,
            )
            os.remove(wav_path)
            self._output_path = mp3_path
            log.info(f"Converted to MP3 -> {mp3_path}")
        except FileNotFoundError:
            log.warning("ffmpeg not found, keeping WAV")
        except subprocess.CalledProcessError as e:
            log.error(f"ffmpeg error: {e.stderr.decode()}")

    def _record_loop(self):
        p = pyaudio.PyAudio()
        try:
            loopback = find_loopback_device(p)
            mic = find_mic_device(p)

            lb_rate = int(loopback["defaultSampleRate"])
            lb_ch = loopback["maxInputChannels"]
            mic_rate = int(mic["defaultSampleRate"])
            mic_ch = mic["maxInputChannels"]

            out_rate = lb_rate
            log.info(f"Loopback: {loopback['name']} ch={lb_ch} rate={lb_rate}")
            log.info(f"Mic: {mic['name']} ch={mic_ch} rate={mic_rate}")

            lb_stream = p.open(
                format=FORMAT, channels=lb_ch, rate=lb_rate,
                input=True, input_device_index=loopback["index"],
                frames_per_buffer=CHUNK,
            )
            mic_stream = p.open(
                format=FORMAT, channels=mic_ch, rate=mic_rate,
                input=True, input_device_index=mic["index"],
                frames_per_buffer=CHUNK,
            )

            wf = wave.open(self._output_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(out_rate)

            mic_ratio = mic_rate / lb_rate

            while not self._stop_event.is_set():
                lb_data = lb_stream.read(CHUNK, exception_on_overflow=False)
                mic_frames = max(1, int(CHUNK * mic_ratio))
                mic_data = mic_stream.read(mic_frames, exception_on_overflow=False)

                lb_arr = np.frombuffer(lb_data, dtype=np.int16)
                mic_arr = np.frombuffer(mic_data, dtype=np.int16)

                if lb_ch > 1:
                    lb_arr = lb_arr.reshape(-1, lb_ch).mean(axis=1).astype(np.int16)
                if mic_ch > 1:
                    mic_arr = mic_arr.reshape(-1, mic_ch).mean(axis=1).astype(np.int16)

                target_len = len(lb_arr)
                if len(mic_arr) != target_len:
                    mic_arr = np.interp(
                        np.linspace(0, len(mic_arr) - 1, target_len),
                        np.arange(len(mic_arr)),
                        mic_arr.astype(np.float64),
                    ).astype(np.int16)

                mixed = np.clip(
                    lb_arr.astype(np.int32) + mic_arr.astype(np.int32),
                    -32768, 32767,
                ).astype(np.int16)

                wf.writeframes(mixed.tobytes())

            lb_stream.stop_stream()
            lb_stream.close()
            mic_stream.stop_stream()
            mic_stream.close()
            wf.close()
        except Exception as e:
            log.error(f"Recording error: {e}")
        finally:
            p.terminate()