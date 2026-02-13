import time
import logging
import ctypes
import threading
import comtypes
from tkinter import filedialog
import customtkinter as ctk
from config import load_settings, save_settings, AUDIO_FORMATS, POLL_INTERVAL, APP_NAME
from detector import get_browser_mic_sessions
from recorder import Recorder
from ui.theme import *  # noqa: F403
from ui.icons import make_ico

log = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ghost.meet.recorder")


def _pretty(name):
    return name.replace(".exe", "").capitalize()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("360x220")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.iconbitmap(make_ico(STATE_COLORS["idle"]))

        self._settings = load_settings()
        self._recorder = Recorder(self._settings)
        self._enabled = True
        self._monitoring = False
        self._state = "idle"

        self._build_ui()
        self._set_state("idle")
        self._start_monitoring()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # --- status card ---
        self._card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        self._card.grid(row=0, column=0, padx=PAD, pady=(PAD, 10), sticky="ew")
        self._card.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(self._card, fg_color="transparent")
        left.grid(row=0, column=0, padx=(14, 0), pady=12, sticky="ew")
        left.grid_columnconfigure(1, weight=1)

        self._status_dot = ctk.CTkLabel(left, text="\u25cf", font=("", 18))
        self._status_dot.grid(row=0, column=0, rowspan=2, padx=(0, 10))

        self._status_label = ctk.CTkLabel(
            left, text="", font=("Segoe UI Semibold", 13),
            text_color=TEXT_PRIMARY, anchor="w"
        )
        self._status_label.grid(row=0, column=1, sticky="sw")

        self._status_detail = ctk.CTkLabel(
            left, text="", font=("Segoe UI", 11),
            text_color=TEXT_SECONDARY, anchor="w"
        )
        self._status_detail.grid(row=1, column=1, sticky="nw")

        self._timer_label = ctk.CTkLabel(
            left, text="", font=("Consolas", 13), text_color=TEXT_PRIMARY
        )
        self._timer_label.grid(row=0, column=2, rowspan=2, padx=(8, 0))

        self._toggle_btn = ctk.CTkButton(
            self._card, text="\u23f8", width=44,
            font=("Segoe UI", 16),
            fg_color="transparent", hover_color=BG_CONTROL_HOVER,
            text_color=TEXT_SECONDARY,
            corner_radius=8, command=self._toggle_enabled
        )
        self._toggle_btn.grid(row=0, column=1, padx=(0, 6), pady=6, sticky="ns")

        # --- settings card ---
        scard = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        scard.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="ew")
        scard.grid_columnconfigure(1, weight=1)

        for label, r in [("Save to", 0), ("Format", 1)]:
            ctk.CTkLabel(
                scard, text=label, font=("Segoe UI", 12), text_color=TEXT_SECONDARY
            ).grid(row=r, column=0, padx=14, pady=7, sticky="w")

        self._path_var = ctk.StringVar(value=self._settings["recordings_dir"])
        pf = ctk.CTkFrame(scard, fg_color="transparent")
        pf.grid(row=0, column=1, padx=(0, 14), pady=7, sticky="ew")
        pf.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            pf, textvariable=self._path_var, state="readonly",
            height=30, font=("Segoe UI", 11), fg_color=BG_INPUT, border_width=0
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            pf, text="\u2026", width=30, height=30, font=("", 14),
            fg_color=BG_CONTROL, hover_color=BG_CONTROL_HOVER,
            corner_radius=6, command=self._pick_folder
        ).grid(row=0, column=1, padx=(6, 0))

        self._format_var = ctk.StringVar(value=self._settings["audio_format"])
        ctk.CTkOptionMenu(
            scard, values=AUDIO_FORMATS, variable=self._format_var,
            width=80, height=30, font=("Segoe UI", 11),
            fg_color=BG_CONTROL, button_color=BG_CONTROL_HOVER,
            corner_radius=6, command=lambda _: self._save()
        ).grid(row=1, column=1, padx=(0, 14), pady=7, sticky="w")

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # --- state ---

    def _set_state(self, state, detail=""):
        self._state = state
        color = STATE_COLORS[state]
        self._status_dot.configure(text_color=color)

        self._status_label.configure(text={
            "idle": "Disabled", "monitoring": "Monitoring", "recording": "Recording",
        }[state])
        self._status_detail.configure(text=detail or {
            "idle": "Recording is paused",
            "monitoring": "Waiting for mic activity...",
            "recording": "",
        }[state])

        if state != "recording":
            self._timer_label.configure(text="")

        if state == "idle":
            self._toggle_btn.configure(text="\u25b6", text_color=STATE_COLORS["monitoring"])
        else:
            self._toggle_btn.configure(text="\u23f8", text_color=TEXT_SECONDARY)

        try:
            self.iconbitmap(make_ico(color))
        except Exception:
            pass

    # --- controls ---

    def _toggle_enabled(self):
        self._enabled = not self._enabled
        if self._enabled:
            self._set_state("monitoring")
        else:
            if self._recorder.is_recording:
                self._recorder.stop()
            self._set_state("idle")

    def _pick_folder(self):
        path = filedialog.askdirectory(initialdir=self._path_var.get())
        if path:
            self._path_var.set(path)
            self._save()

    def _save(self):
        self._settings["recordings_dir"] = self._path_var.get()
        self._settings["audio_format"] = self._format_var.get()
        save_settings(self._settings)
        self._recorder.update_settings(self._settings)

    # --- monitor ---

    def _start_monitoring(self):
        self._monitoring = True
        self._set_state("monitoring")
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _monitor_loop(self):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        rec_start = None
        while self._monitoring:
            try:
                if not self._enabled:
                    time.sleep(POLL_INTERVAL)
                    continue

                sessions = get_browser_mic_sessions()

                if sessions and not self._recorder.is_recording:
                    names = ", ".join(_pretty(s["process"]) for s in sessions)
                    log.info(f"MIC ACQUIRED -- {names}")
                    self._recorder.start(sessions)
                    rec_start = time.time()
                    self.after(0, self._set_state, "recording", names)

                elif not sessions and self._recorder.is_recording:
                    log.info("MIC RELEASED -- session ended")
                    self._recorder.stop()
                    rec_start = None
                    self.after(0, self._set_state, "monitoring")

                if self._recorder.is_recording and rec_start:
                    elapsed = int(time.time() - rec_start)
                    m, s = divmod(elapsed, 60)
                    h, m = divmod(m, 60)
                    ts = f"{h:02d}:{m:02d}:{s:02d}"
                    self.after(0, self._timer_label.configure, {"text": ts})

            except Exception as e:
                log.error(f"Monitor error: {e}")

            time.sleep(POLL_INTERVAL)