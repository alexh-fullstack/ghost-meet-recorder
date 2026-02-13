import pyaudiowpatch as pyaudio


def find_loopback_device(p: pyaudio.PyAudio):
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get("isLoopbackDevice") and default_speakers["name"] in dev["name"]:
            return dev
    raise RuntimeError("No WASAPI loopback device found")


def find_mic_device(p: pyaudio.PyAudio):
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    return p.get_device_info_by_index(wasapi_info["defaultInputDevice"])