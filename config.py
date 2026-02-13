import os
import json
import logging

APP_NAME = "Ghost Meet Recorder"
BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
POLL_INTERVAL = 2
AUDIO_FORMATS = ["wav", "mp3", "flac", "ogg", "m4a", "opus", "aac", "wma"]
FILENAME_PARTS = ["date", "time", "browser", "tab"]

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
DEFAULT_RECORDINGS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Ghost Meet Recordings")
os.makedirs(CONFIG_DIR, exist_ok=True)

DEFAULTS = {
    "recordings_dir": DEFAULT_RECORDINGS_DIR,
    "audio_format": "wav",
    "filename_prefix": "meet",
    "filename_parts": {"date": True, "time": True, "browser": False, "tab": False},
    "notifications": True,
}


def load_settings():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        merged = {**DEFAULTS, **saved}
        merged["filename_parts"] = {**DEFAULTS["filename_parts"], **saved.get("filename_parts", {})}
        return merged
    return dict(DEFAULTS)


def save_settings(settings: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=2)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)