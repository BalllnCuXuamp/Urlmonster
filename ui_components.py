import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import time
import threading

# ──────────────────────────────────────────────
#  Colour palette
# ──────────────────────────────────────────────
THEMES = {
    "dark": {
        "bg": "#0d1117", "card": "#161b22", "border": "#30363d",
        "text": "#e6edf3", "text_sec": "#8b949e", "accent": "#58a6ff",
        "accent2": "#3fb950", "danger": "#f85149", "warn": "#d29922",
    },
    "light": {
        "bg": "#f6f8fa", "card": "#ffffff", "border": "#d0d7de",
        "text": "#1f2328", "text_sec": "#656d76", "accent": "#0969da",
        "accent2": "#1a7f37", "danger": "#cf222e", "warn": "#9a6700",
    },
}
_current_theme = "dark"

def th(key):
    return THEMES[_current_theme][key]

def set_theme(t):
    global _current_theme
    _current_theme = t
    ctk.set_appearance_mode("dark" if t == "dark" else "light")

# ──────────────────────────────────────────────
#  Custom Title Bar
# ──────────────────────────────────────────────
class TitleBar(ctk.CTkFrame):
    def __init__(self, master, title="URLmonster", on_close=None, on_min=None, on_max=None):
        super().__init__(master, height=40, corner_radius=0, fg_color=th("card"))
        self.pack(fill="x", side="top")
        self._start_x = self._start_y = 0

        # App icon + title
        ctk.CTkLabel(self, text="⚡", font=("Segoe UI", 14), text_color=th("accent")).pack(side="left", padx=(12, 4))
        ctk.CTkLabel(self, text=title, font=("Segoe UI", 11, "bold"), text_color=th("text")).pack(side="left")

        # Spacer
        frame = ctk.CTkFrame(self, fg_color="transparent", height=40)
        frame.pack(side="right")

        btn_kw = dict(width=46, height=40, corner_radius=0, border_width=0)
        ctk.CTkButton(frame, text="─", command=on_min or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("border"), **btn_kw).pack(side="right")
        max_btn = ctk.CTkButton(frame, text="□", command=on_max or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("border"), **btn_kw)
        max_btn.pack(side="right")
        ctk.CTkButton(frame, text="✕", command=on_close or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("danger"), **btn_kw).pack(side="right")

        # drag
        self.bind("<Button-1>", self._drag_start)
        self.bind("<B1-Motion>", self._drag_move)
        for child in self.winfo_children():
            child.bind("<Button-1>", self._drag_start)
            child.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._start_x = e.x_root - self.master.winfo_x()
        self._start_y = e.y_root - self.master.winfo_y()

    def _drag_move(self, e):
        self.master.geometry(f"+{e.x_root - self._start_x}+{e.y_root - self._start_y}")

    @staticmethod
    def _noop():
        pass

# ──────────────────────────────────────────────
#  Tab Bar
# ──────────────────────────────────────────────
class TabBar(ctk.CTkFrame):
    def __init__(self, master, tabs, on_switch=None):
        super().__init__(master, height=36, corner_radius=0, fg_color=th("bg"))
        self.pack(fill="x")
        self._on_switch = on_switch
        self._buttons = []
        self._active = None
        self._tabs = tabs
        for tab in tabs:
            if len(tab) == 3:
                name, icon, label = tab
            else:
                name, icon = tab
                label = name
            btn = ctk.CTkButton(
                self, text=f"{icon}  {label}", font=("Segoe UI", 11),
                fg_color="transparent", text_color=th("text_sec"),
                hover_color=th("card"), anchor="w",
                height=32, corner_radius=6, border_width=0,
                command=lambda n=name: self._activate(n),
            )
            btn.pack(side="left", padx=(0, 2), pady=2)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(fg_color=th("card")))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(fg_color="transparent" if b != self._active else th("border")))
            self._buttons.append(btn)
        if self._buttons:
            self._activate(tabs[0][0])

    def _activate(self, name):
        for btn, tab in zip(self._buttons, self._tabs):
            if tab[0] == name:
                btn.configure(fg_color=th("card"), text_color=th("accent"))
                self._active = btn
            else:
                btn.configure(fg_color="transparent", text_color=th("text_sec"))
        if self._on_switch:
            self._on_switch(name)

# ──────────────────────────────────────────────
#  Toast Notification
# ──────────────────────────────────────────────
class Toast:
    _instance = None

    @classmethod
    def show(cls, master, message, type="info", duration=3):
        colours = {"info": th("accent"), "success": th("accent2"), "error": th("danger"), "warn": th("warn")}
        bg = colours.get(type, th("accent"))
        tw = ctk.CTkToplevel(master, fg_color=th("card"))
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.geometry(f"400x50+{master.winfo_x() + master.winfo_width() - 420}+{master.winfo_y() + 10}")
        ctk.CTkLabel(tw, text=message, font=("Segoe UI", 12), text_color=th("text"), fg_color=th("card")).pack(fill="both", expand=True, padx=16, pady=8)
        ctk.CTkFrame(tw, height=3, fg_color=bg).pack(fill="x", side="bottom")
        master.after(duration * 1000, tw.destroy)
        cls._fade_in(tw, master)

    @staticmethod
    def _fade_in(w, master, alpha=0.0):
        if alpha < 1:
            w.attributes("-alpha", alpha)
            master.after(20, lambda: Toast._fade_in(w, master, min(1, alpha + 0.1)))

# ──────────────────────────────────────────────
#  Live Log
# ──────────────────────────────────────────────
class LiveLog(ctk.CTkTextbox):
    def __init__(self, master, **kw):
        super().__init__(master, wrap="none", **kw)
        self.tag_config("info", foreground=th("text_sec"))
        self.tag_config("ok", foreground=th("accent2"))
        self.tag_config("err", foreground=th("danger"))
        self.tag_config("warn", foreground=th("warn"))
        self.tag_config("acc", foreground=th("accent"))
        self._auto_scroll = True

    def write(self, msg, tag="info"):
        self.insert("end", msg + "\n", tag)
        if self._auto_scroll:
            self.see("end")

    def toggle_scroll(self):
        self._auto_scroll = not self._auto_scroll

# ──────────────────────────────────────────────
#  Metric Card
# ──────────────────────────────────────────────
class MetricCard(ctk.CTkFrame):
    def __init__(self, master, label, value="—", unit="", icon="📊", **kw):
        super().__init__(master, fg_color=th("card"), corner_radius=12, border_width=1, border_color=th("border"), **kw)
        self._value_label = None
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(row, text=icon, font=("Segoe UI", 18), text_color=th("text_sec")).pack(side="left")
        ctk.CTkLabel(row, text=label, font=("Segoe UI", 11), text_color=th("text_sec")).pack(side="right")
        self._value_label = ctk.CTkLabel(self, text=f"{value}{unit}", font=("Segoe UI", 22, "bold"), text_color=th("text"), anchor="w")
        self._value_label.pack(fill="x", padx=14, pady=(0, 12))

    def set(self, value, unit=""):
        self._value_label.configure(text=f"{value}{unit}")

# ──────────────────────────────────────────────
#  Split Pane (resizable)
# ──────────────────────────────────────────────
class SplitPane(ctk.CTkFrame):
    def __init__(self, master, left_widget, right_widget, ratio=0.35, min_left=200, min_right=200, orient="horizontal", **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._orient = orient
        self._ratio = ratio
        self._min_left = min_left
        self._min_right = min_right
        self._drag = False

        if orient == "horizontal":
            self.columnconfigure(0, weight=1)
            self.columnconfigure(2, weight=1)
            self.rowconfigure(0, weight=1)
            left_widget.grid(row=0, column=0, sticky="nsew")
            self._div = ctk.CTkFrame(self, width=4, cursor="sb_h_double_arrow", fg_color=th("border"))
            self._div.grid(row=0, column=1, sticky="ns")
            right_widget.grid(row=0, column=2, sticky="nsew")
            self._div.bind("<Button-1>", self._drag_start)
            self._div.bind("<B1-Motion>", self._drag_horiz)
        else:
            self.rowconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)
            self.columnconfigure(0, weight=1)
            left_widget.grid(row=0, column=0, sticky="nsew")
            self._div = ctk.CTkFrame(self, height=4, cursor="sb_v_double_arrow", fg_color=th("border"))
            self._div.grid(row=1, column=0, sticky="ew")
            right_widget.grid(row=2, column=0, sticky="nsew")
            self._div.bind("<Button-1>", self._drag_start)
            self._div.bind("<B1-Motion>", self._drag_vert)

    def _drag_start(self, e):
        self._drag = True

    def _drag_horiz(self, e):
        if not self._drag:
            return
        w = self.winfo_width()
        x = e.x_root - self.winfo_rootx()
        new_ratio = max(self._min_left / w, min(1 - self._min_right / w, x / w))
        self._ratio = new_ratio
        self.columnconfigure(0, weight=int(new_ratio * 100))
        self.columnconfigure(2, weight=int((1 - new_ratio) * 100))

    def _drag_vert(self, e):
        if not self._drag:
            return
        h = self.winfo_height()
        y = e.y_root - self.winfo_rooty()
        new_ratio = max(self._min_left / h, min(1 - self._min_right / h, y / h))
        self._ratio = new_ratio
        self.rowconfigure(0, weight=int(new_ratio * 100))
        self.rowconfigure(2, weight=int((1 - new_ratio) * 100))

    def stop_drag(self, e):
        self._drag = False
