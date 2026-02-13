import logging
import psutil
from comtypes import CLSCTX_ALL, CoCreateInstance
from pycaw.pycaw import (
    IAudioSessionManager2,
    IAudioSessionControl2,
    IMMDeviceEnumerator,
)
from pycaw.constants import CLSID_MMDeviceEnumerator
from config import BROWSER_PROCESSES

log = logging.getLogger(__name__)


def get_browser_mic_sessions():
    enumerator = CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL
    )
    mic_device = enumerator.GetDefaultAudioEndpoint(1, 0)  # eCapture=1, eConsole=0
    raw = mic_device.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None)
    mgr = raw.QueryInterface(IAudioSessionManager2)
    session_enum = mgr.GetSessionEnumerator()

    active = []
    for i in range(session_enum.GetCount()):
        ctl = session_enum.GetSession(i)
        ctl2 = ctl.QueryInterface(IAudioSessionControl2)
        pid = ctl2.GetProcessId()
        if pid == 0:
            continue
        try:
            proc = psutil.Process(pid)
            name = proc.name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name not in BROWSER_PROCESSES:
            continue
        state = ctl.GetState()
        if state == 1:  # AudioSessionStateActive
            active.append({"process": name, "pid": pid})
    return active