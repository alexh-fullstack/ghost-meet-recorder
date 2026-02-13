import time
import logging
import ctypes
import threading
import comtypes
from tkinter import filedialog
import pystray
import customtkinter as ctk
from config import load_settings, save_settings, AUDIO_FORMATS, FILENAME_PARTS, POLL_INTERVAL, APP_NAME
from detector import get_browser_mic_sessions
from recorder import Recorder
from ui.theme import *  # noqa: F403
from ui.icons import make_icon, make_ico
from ui.toast import Toast

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
        self.geometry("380x290")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.iconbitmap(make_ico(STATE_COLORS["idle"]))

        self._settings = load_settings()
        self._recorder = Recorder(self._settings)
        self._enabled = True
        self._monitoring = False
        self._tray_icon = None
        self._state = "idle"

        self._build_ui()
        self._set_state("idle")
        self._start_monitoring()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # --- status card ---
        self._card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10, height=48)
        self._card.grid(row=0, column=0, padx=PAD, pady=(PAD, 6), sticky="ew")
        self._card.grid_propagate(False)
        self._card.grid_columnconfigure(1, weight=1)
        self._card.grid_rowconfigure(0, weight=1)

        self._accent_bar = ctk.CTkFrame(
            self._card, width=3, fg_color=STATE_COLORS["idle"], corner_radius=2
        )
        self._accent_bar.grid(row=0, column=0, padx=(8, 8), pady=10, sticky="ns")

        self._status_label = ctk.CTkLabel(
            self._card, text="", font=("Segoe UI Semibold", 12),
            text_color=TEXT_PRIMARY, anchor="w"
        )
        self._status_label.grid(row=0, column=1, sticky="w")

        self._status_detail = ctk.CTkLabel(
            self._card, text="", font=("Segoe UI", 10),
            text_color=TEXT_SECONDARY, anchor="w"
        )
        self._status_detail.grid(row=0, column=2, padx=(6, 0), sticky="w")

        self._timer_label = ctk.CTkLabel(
            self._card, text="", font=("Consolas", 11), text_color=TEXT_SECONDARY
        )
        self._timer_label.grid(row=0, column=3, padx=(8, 0))

        self._toggle_btn = ctk.CTkButton(
            self._card, text="\u23f8", width=30, height=30,
            font=("Segoe UI", 13),
            fg_color=BG_CONTROL, hover_color=BG_CONTROL_HOVER,
            text_color=TEXT_SECONDARY,
            corner_radius=15, command=self._toggle_enabled
        )
        self._toggle_btn.grid(row=0, column=4, padx=(6, 8))

        # --- settings card ---
        scard = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12)
        scard.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="ew")
        scard.grid_columnconfigure(1, weight=1)

        labels = [("Save to", 0), ("Format", 1), ("Prefix", 2), ("Filename", 3), ("Notifications", 4)]
        for label, r in labels:
            ctk.CTkLabel(
                scard, text=label, font=("Segoe UI", 11), text_color=TEXT_SECONDARY
            ).grid(row=r, column=0, padx=14, pady=6, sticky="w")

        self._path_var = ctk.StringVar(value=self._settings["recordings_dir"])
        pf = ctk.CTkFrame(scard, fg_color="transparent")
        pf.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="ew")
        pf.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            pf, textvariable=self._path_var, state="readonly",
            height=28, font=("Segoe UI", 10), fg_color=BG_INPUT, border_width=0
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            pf, text="\u2026", width=28, height=28, font=("", 13),
            fg_color=BG_CONTROL, hover_color=BG_CONTROL_HOVER,
            corner_radius=6, command=self._pick_folder
        ).grid(row=0, column=1, padx=(4, 0))

        self._format_var = ctk.StringVar(value=self._settings["audio_format"])
        ctk.CTkOptionMenu(
            scard, values=AUDIO_FORMATS, variable=self._format_var,
            width=76, height=28, font=("Segoe UI", 10),
            fg_color=BG_CONTROL, button_color=BG_CONTROL_HOVER,
            corner_radius=6, command=lambda _: self._save()
        ).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")

        self._prefix_var = ctk.StringVar(value=self._settings.get("filename_prefix", "meet"))
        self._prefix_var.trace_add("write", lambda *_: self._save())
        ctk.CTkEntry(
            scard, textvariable=self._prefix_var,
            height=28, width=100, font=("Segoe UI", 10),
            fg_color=BG_INPUT, border_width=0, placeholder_text="prefix"
        ).grid(row=2, column=1, padx=(0, 12), pady=6, sticky="w")

        parts_cfg = self._settings.get("filename_parts", {})
        ff = ctk.CTkFrame(scard, fg_color="transparent")
        ff.grid(row=3, column=1, padx=(0, 12), pady=6, sticky="w")
        self._fname_vars = {}
        for i, part in enumerate(FILENAME_PARTS):
            var = ctk.BooleanVar(value=parts_cfg.get(part, part in ("date", "time")))
            self._fname_vars[part] = var
            ctk.CTkCheckBox(
                ff, text=part, variable=var, width=1,
                font=("Segoe UI", 10), text_color=TEXT_SECONDARY,
                checkbox_width=18, checkbox_height=18, corner_radius=4,
                border_width=2, command=self._save,
            ).grid(row=0, column=i, padx=(0, 8))

        self._notif_var = ctk.BooleanVar(value=self._settings.get("notifications", True))
        ctk.CTkSwitch(
            scard, text="", variable=self._notif_var, width=40, command=self._save
        ).grid(row=4, column=1, padx=(0, 12), pady=6, sticky="w")

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    # --- state ---

    def _set_state(self, state, detail=""):
        self._state = state
        color = STATE_COLORS[state]
        self._accent_bar.configure(fg_color=color)

        self._status_label.configure(text={
            "idle": "Disabled", "monitoring": "Monitoring", "recording": "Recording",
        }[state])
        self._status_detail.configure(text=detail or {
            "idle": "", "monitoring": "waiting for mic\u2026", "recording": "",
        }[state])

        if state != "recording":
            self._timer_label.configure(text="")

        if state == "idle":
            self._toggle_btn.configure(
                text="\u25b6", fg_color=STATE_COLORS["monitoring"],
                hover_color="#27ae60", text_color="#ffffff"
            )
        else:
            self._toggle_btn.configure(
                text="\u23f8", fg_color=BG_CONTROL,
                hover_color=BG_CONTROL_HOVER, text_color=TEXT_SECONDARY
            )

        self._update_window_icon(color)
        self._update_tray_icon(color)

    def _update_window_icon(self, color):
        try:
            self.iconbitmap(make_ico(color))
        except Exception:
            pass

    def _update_tray_icon(self, color):
        if self._tray_icon:
            self._tray_icon.icon = make_icon(color)

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
        self._settings["filename_prefix"] = self._prefix_var.get().strip()
        self._settings["filename_parts"] = {k: v.get() for k, v in self._fname_vars.items()}
        self._settings["notifications"] = self._notif_var.get()
        save_settings(self._settings)
        self._recorder.update_settings(self._settings)

    def _notify(self, title, msg, accent="#27ae60"):
        if not self._settings.get("notifications", True):
            return
        Toast(self, title, msg, accent)

    # --- tray ---

    def _start_monitoring(self):
        self._monitoring = True
        self._set_state("monitoring")
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _hide_to_tray(self):
        self.withdraw()
        if not self._tray_icon:
            self._create_tray()

    def _create_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._show_from_tray, default=True),
            pystray.MenuItem(
                lambda _: "Disable" if self._enabled else "Enable",
                self._tray_toggle
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._tray_icon = pystray.Icon(
            APP_NAME, make_icon(STATE_COLORS[self._state]), APP_NAME, menu
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_from_tray(self, icon=None, item=None):
        self.after(0, self.deiconify)

    def _tray_toggle(self, icon=None, item=None):
        self.after(0, self._toggle_enabled)

    def _quit(self, icon=None, item=None):
        self._monitoring = False
        if self._recorder.is_recording:
            self._recorder.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    # --- monitor ---

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
                    self.after(0, self._notify, "Recording started", names, STATE_COLORS["recording"])

                elif not sessions and self._recorder.is_recording:
                    log.info("MIC RELEASED -- session ended")
                    elapsed = int(time.time() - rec_start) if rec_start else 0
                    m, s = divmod(elapsed, 60)
                    duration = f"{m}m {s}s"
                    self._recorder.stop()
                    rec_start = None
                    self.after(0, self._set_state, "monitoring")
                    self.after(0, self._notify, "Recording saved", f"Duration: {duration}", STATE_COLORS["monitoring"])

                if self._recorder.is_recording and rec_start:
                    elapsed = int(time.time() - rec_start)
                    m, s = divmod(elapsed, 60)
                    h, m = divmod(m, 60)
                    ts = f"{h:02d}:{m:02d}:{s:02d}"
                    self.after(0, self._timer_label.configure, {"text": ts})

            except Exception as e:
                log.error(f"Monitor error: {e}")

            time.sleep(POLL_INTERVAL)