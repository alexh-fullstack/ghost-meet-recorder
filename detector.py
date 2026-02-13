import re
import ctypes
import logging
from ctypes import wintypes
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

_user32 = ctypes.windll.user32
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _get_window_title(pid):
    titles = []

    def _cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            proc_id = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value == pid:
                length = _user32.GetWindowTextLengthW(hwnd)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    _user32.GetWindowTextW(hwnd, buf, length + 1)
                    titles.append(buf.value)
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return max(titles, key=len) if titles else ""


def _prettify_title(raw_title):
    if not raw_title:
        return ""
    title = _UNSAFE_CHARS.sub("", raw_title).strip()
    title = title.replace("  ", " ")
    if len(title) > 60:
        title = title[:60]
    title = title.rstrip(". ")
    return title or ""


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
            raw_title = _get_window_title(pid)
            if not raw_title:
                try:
                    parent = psutil.Process(pid).parent()
                    if parent and parent.name().lower() in BROWSER_PROCESSES:
                        raw_title = _get_window_title(parent.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            title = _prettify_title(raw_title)
            active.append({"process": name, "pid": pid, "tab": title})
    return active
