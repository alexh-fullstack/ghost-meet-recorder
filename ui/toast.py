import customtkinter as ctk
from ui.theme import BG_CARD_ELEVATED, TEXT_PRIMARY, TEXT_SECONDARY, TOAST_DURATION


class Toast(ctk.CTkToplevel):
    def __init__(self, parent, title, msg, accent="#2ecc71"):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=BG_CARD_ELEVATED)

        w, h = 280, 64
        sx = self.winfo_screenwidth() - w - 20
        sy = self.winfo_screenheight() - h - 60
        self.geometry(f"{w}x{h}+{sx}+{sy}")

        ctk.CTkFrame(self, width=3, height=h, fg_color=accent, corner_radius=0).place(x=0, y=0)

        ctk.CTkLabel(
            self, text=title, font=("Segoe UI Semibold", 11),
            text_color=TEXT_PRIMARY, anchor="w"
        ).place(x=14, y=12)

        ctk.CTkLabel(
            self, text=msg, font=("Segoe UI", 10),
            text_color=TEXT_SECONDARY, anchor="w"
        ).place(x=14, y=34)

        self.attributes("-alpha", 0.0)
        self._fade_in()

    def _fade_in(self, alpha=0.0):
        if alpha <= 0.95:
            self.attributes("-alpha", alpha)
            self.after(15, self._fade_in, alpha + 0.12)
        else:
            self.attributes("-alpha", 0.95)
            self.after(TOAST_DURATION, self._fade_out)

    def _fade_out(self, alpha=0.95):
        if alpha > 0.05:
            self.attributes("-alpha", alpha)
            self.after(15, self._fade_out, alpha - 0.12)
        else:
            self.destroy()