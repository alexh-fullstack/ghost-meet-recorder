import os
import wave
import logging
import threading
import subprocess
import queue
import numpy as np
from datetime import datetime
import pyaudiowpatch as pyaudio
import imageio_ffmpeg
from recorder.devices import find_loopback_device, find_mic_device

log = logging.getLogger(__name__)

CHUNK = 2048
FORMAT = pyaudio.paInt16
QUEUE_MAX = 200

MAX_FILENAME = 180


class Recorder:
    def __init__(self, settings: dict):
        self._settings = settings
        self._thread = None
        self._stop_event = threading.Event()
        self._file_closed = threading.Event()
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

        prefix = self._settings.get("filename_prefix", "").strip()
        parts_cfg = self._settings.get("filename_parts", {"date": True, "time": True})
        s0 = session_info[0] if session_info else {}
        title = s0.get("tab", "")
        values = {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H-%M-%S"),
            "browser": s0.get("process", "unknown").replace(".exe", ""),
            "tab": title.replace(" ", "-") if title else "",
        }
        parts = []
        if prefix:
            parts.append(prefix)
        for k in ("date", "time", "browser", "tab"):
            if parts_cfg.get(k) and values.get(k):
                parts.append(values[k])
        if not parts:
            parts = [now.strftime("recording_%Y-%m-%d_%H-%M-%S")]
        tag = "_".join(parts)
        if len(tag) > MAX_FILENAME:
            tag = tag[:MAX_FILENAME]
        tag = tag.rstrip(". ")
        self._output_path = os.path.join(day_dir, f"{tag}.wav")

        self._stop_event.clear()
        self._file_closed.clear()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        log.info(f"Recording started -> {self._output_path}")

    def stop(self):
        if not self.is_recording:
            return
        self._stop_event.set()
        self._file_closed.wait(timeout=10)
        self._thread.join(timeout=5)
        self._thread = None
        log.info(f"Recording stopped -> {self._output_path}")

        fmt = self._settings.get("audio_format", "wav")
        if fmt != "wav":
            self._convert(fmt)

    _FFMPEG_ARGS = {
        "mp3":  ["-b:a", "192k"],
        "flac": ["-c:a", "flac"],
        "ogg":  ["-c:a", "libvorbis", "-q:a", "5"],
        "m4a":  ["-c:a", "aac", "-b:a", "192k"],
        "opus": ["-c:a", "libopus", "-b:a", "128k"],
        "aac":  ["-c:a", "aac", "-b:a", "192k"],
        "wma":  ["-c:a", "wmav2", "-b:a", "192k"],
    }

    def _convert(self, fmt):
        wav_path = self._output_path
        out_path = wav_path.rsplit(".", 1)[0] + f".{fmt}"
        args = self._FFMPEG_ARGS.get(fmt, [])
        try:
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", wav_path] + args + [out_path],
                capture_output=True, check=True,
            )
            os.remove(wav_path)
            self._output_path = out_path
            log.info(f"Converted to {fmt.upper()} -> {out_path}")
        except FileNotFoundError:
            log.warning("ffmpeg not found, keeping WAV")
        except subprocess.CalledProcessError as e:
            log.error(f"ffmpeg error: {e.stderr.decode()}")
            if os.path.exists(out_path):
                os.remove(out_path)

    def _record_loop(self):
        p = pyaudio.PyAudio()
        wf = None
        lb_stream = None
        mic_stream = None
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

            lb_queue = queue.Queue(maxsize=QUEUE_MAX)
            mic_queue = queue.Queue(maxsize=QUEUE_MAX)

            def _lb_callback(in_data, frame_count, time_info, status):
                try:
                    lb_queue.put_nowait(in_data)
                except queue.Full:
                    pass
                return (None, pyaudio.paContinue)

            def _mic_callback(in_data, frame_count, time_info, status):
                try:
                    mic_queue.put_nowait(in_data)
                except queue.Full:
                    pass
                return (None, pyaudio.paContinue)

            wf = wave.open(self._output_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(out_rate)

            # mic chunk size adjusted for sample rate difference
            mic_chunk = max(1, int(CHUNK * mic_rate / lb_rate))

            lb_stream = p.open(
                format=FORMAT, channels=lb_ch, rate=lb_rate,
                input=True, input_device_index=loopback["index"],
                frames_per_buffer=CHUNK,
                stream_callback=_lb_callback,
            )
            mic_stream = p.open(
                format=FORMAT, channels=mic_ch, rate=mic_rate,
                input=True, input_device_index=mic["index"],
                frames_per_buffer=mic_chunk,
                stream_callback=_mic_callback,
            )

            lb_stream.start_stream()
            mic_stream.start_stream()

            while not self._stop_event.is_set():
                try:
                    lb_data = lb_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                try:
                    mic_data = mic_queue.get(timeout=0.05)
                except queue.Empty:
                    mic_data = None

                lb_arr = np.frombuffer(lb_data, dtype=np.int16)
                if lb_ch > 1:
                    lb_arr = lb_arr.reshape(-1, lb_ch).mean(axis=1).astype(np.int16)

                target_len = len(lb_arr)

                if mic_data is not None:
                    mic_arr = np.frombuffer(mic_data, dtype=np.int16)
                    if mic_ch > 1:
                        mic_arr = mic_arr.reshape(-1, mic_ch).mean(axis=1).astype(np.int16)
                    if len(mic_arr) != target_len:
                        mic_arr = np.interp(
                            np.linspace(0, len(mic_arr) - 1, target_len),
                            np.arange(len(mic_arr)),
                            mic_arr.astype(np.float64),
                        ).astype(np.int16)
                else:
                    mic_arr = np.zeros(target_len, dtype=np.int16)

                mixed = np.clip(
                    lb_arr.astype(np.int32) + mic_arr.astype(np.int32),
                    -32768, 32767,
                ).astype(np.int16)

                wf.writeframes(mixed.tobytes())
        except Exception as e:
            log.error(f"Recording error: {e}")
        finally:
            for stream in (lb_stream, mic_stream):
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
            if wf is not None:
                try:
                    wf.close()
                except Exception:
                    pass
            self._file_closed.set()
            p.terminate()
