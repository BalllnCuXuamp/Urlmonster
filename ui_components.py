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
    "cyber": {
        "bg": "#0A0014", "card": "#15002A", "border": "#300060",
        "text": "#FFEEFF", "text_sec": "#AA66AA", "accent": "#FF2D95",
        "accent2": "#00FF41", "danger": "#FF4444", "warn": "#FFD700",
    },
    "matrix": {
        "bg": "#000A00", "card": "#001500", "border": "#003300",
        "text": "#D0FFD0", "text_sec": "#4FA84F", "accent": "#00FF41",
        "accent2": "#39FF5C", "danger": "#FF4444", "warn": "#FFD700",
    },
    "nebula": {
        "bg": "#0D0815", "card": "#1A1028", "border": "#3A2060",
        "text": "#F8E0FF", "text_sec": "#B088C0", "accent": "#E040FB",
        "accent2": "#F06FFF", "danger": "#FF4444", "warn": "#FFD700",
    },
    "arctic": {
        "bg": "#0A1220", "card": "#132038", "border": "#1A3060",
        "text": "#E8F4FD", "text_sec": "#6699BB", "accent": "#4FC3F7",
        "accent2": "#81D4FA", "danger": "#FF5555", "warn": "#FFD700",
    },
    "flame": {
        "bg": "#140800", "card": "#2A1200", "border": "#502800",
        "text": "#FFF0E0", "text_sec": "#CC7744", "accent": "#FF6D00",
        "accent2": "#FF9100", "danger": "#FF4444", "warn": "#FFD700",
    },
    "acid": {
        "bg": "#0A0F00", "card": "#141A00", "border": "#2A3800",
        "text": "#F8FFE0", "text_sec": "#88AA33", "accent": "#C6FF00",
        "accent2": "#EEFF41", "danger": "#FF4444", "warn": "#FFD700",
    },
    "void": {
        "bg": "#08000E", "card": "#12001A", "border": "#2A0040",
        "text": "#F0E8FF", "text_sec": "#A58CC8", "accent": "#7C4DFF",
        "accent2": "#B388FF", "danger": "#FF4444", "warn": "#FFD700",
    },
    "synth": {
        "bg": "#0E0018", "card": "#1A0030", "border": "#380060",
        "text": "#FFE8F0", "text_sec": "#C888AA", "accent": "#FF4081",
        "accent2": "#FF80AB", "danger": "#FF4444", "warn": "#FFD700",
    },
    "quantum": {
        "bg": "#000D14", "card": "#001A28", "border": "#003050",
        "text": "#E0FFFF", "text_sec": "#4499AA", "accent": "#00E5FF",
        "accent2": "#18FFFF", "danger": "#FF5555", "warn": "#FFD700",
    },
    # Концепт C «Криогенная лаборатория»: почти чёрный фон с глубиной,
    # ледяные тонкие линии, свечение только на активном элементе
    "cryo": {
        "bg": "#02060C", "card": "#04101C", "border": "#0A2A44",
        "text": "#E4F2FF", "text_sec": "#8CB8D8", "accent": "#66D9FF",
        "accent2": "#B4E8FF", "danger": "#FF5566", "warn": "#FFE066",
    },
    # Концепт B «Картография данных»: цвет несёт данные,
    # изотермы плотности холодный синий -> янтарный
    "geo": {
        "bg": "#061014", "card": "#0A1A20", "border": "#14343C",
        "text": "#E8F4F0", "text_sec": "#98C0B4", "accent": "#FFB300",
        "accent2": "#66D9CC", "danger": "#FF5566", "warn": "#FFD700",
    },
    # PRIME Living Interface — 5 уникальных тем, которых нет ни у кого
    "prime_abyss": {
        "bg": "#030B14", "card": "#071626", "border": "#0E2E4A",
        "text": "#DFF3FF", "text_sec": "#6FA8C9", "accent": "#00E5A0",
        "accent2": "#4DC3FF", "danger": "#FF5D73", "warn": "#FFC94D",
    },
    "prime_dune": {
        "bg": "#140E08", "card": "#221610", "border": "#4A2E1A",
        "text": "#FFF1DE", "text_sec": "#C9A06F", "accent": "#FF9E3D",
        "accent2": "#FFD23D", "danger": "#FF5D5D", "warn": "#FFE066",
    },
    "prime_moss": {
        "bg": "#0A0F0A", "card": "#131A12", "border": "#24301F",
        "text": "#EAF5E4", "text_sec": "#8AA37E", "accent": "#9DFF57",
        "accent2": "#E4FF57", "danger": "#FF6B6B", "warn": "#FFD93D",
    },
    "prime_ion": {
        "bg": "#0B0B1E", "card": "#151538", "border": "#2C2C6E",
        "text": "#ECECFF", "text_sec": "#8E8ED1", "accent": "#7C7CFF",
        "accent2": "#FF7C9E", "danger": "#FF5D5D", "warn": "#FFD23D",
    },
    "prime_velvet": {
        "bg": "#120A12", "card": "#1E121E", "border": "#3E243E",
        "text": "#F8EAF8", "text_sec": "#B98AB9", "accent": "#E09A4D",
        "accent2": "#F5D08A", "danger": "#FF6B6B", "warn": "#FFE066",
    },
}
_current_theme = "dark"

# Фазы конвейера (концепт A «Верстак»)
PIPELINE_PHASES = ["Detect", "Scan", "Dedup", "Merge", "Report"]


class PhasePipeline(ctk.CTkFrame):
    """Концепт A: конвейер фаз как первый класс UI — не прогресс-бар.
    Фазы зажигаются последовательно: Detect -> Scan -> Dedup -> Merge -> Report."""

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._dots = {}
        self._seps = []
        for i, phase in enumerate(PIPELINE_PHASES):
            c = tk.Canvas(self, width=22, height=22, highlightthickness=0, bd=0)
            c.pack(side="left", padx=2)
            self._dots[phase] = c
            self._draw_dot(phase, "#444444")
            if i < len(PIPELINE_PHASES) - 1:
                sep = ctk.CTkLabel(self, text="—", text_color="#444444", font=("Segoe UI", 10))
                sep.pack(side="left", padx=1)
                self._seps.append(sep)
        self._phase = None

    def _draw_dot(self, phase, color):
        c = self._dots[phase]
        c.delete("all")
        try:
            c.create_oval(4, 4, 18, 18, outline=color, width=2)
            if color != "#444444":
                c.create_oval(8, 8, 14, 14, fill=color, outline="")
        except Exception:
            pass

    def set_phase(self, phase):
        """Подсвечивает текущую фазу и все пройденные; гасит будущие."""
        self._phase = phase
        if phase not in PIPELINE_PHASES:
            return
        idx = PIPELINE_PHASES.index(phase)
        accent = th("accent")
        muted = "#444444"
        for i, p in enumerate(PIPELINE_PHASES):
            self._draw_dot(p, accent if i <= idx else muted)
        for i, sep in enumerate(self._seps):
            try:
                sep.configure(text_color=accent if i < idx else muted)
            except Exception:
                pass

    def reset(self):
        self._phase = None
        for p in PIPELINE_PHASES:
            self._draw_dot(p, "#444444")
        for sep in self._seps:
            try:
                sep.configure(text_color="#444444")
            except Exception:
                pass

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
        ctk.CTkButton(frame, text="─", command=on_min or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("border"), **btn_kw).pack(side="left")
        max_btn = ctk.CTkButton(frame, text="□", command=on_max or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("border"), **btn_kw)
        max_btn.pack(side="left")
        ctk.CTkButton(frame, text="✕", command=on_close or self._noop, fg_color="transparent", text_color=th("text_sec"), hover_color=th("danger"), **btn_kw).pack(side="left")

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
        self._auto_scroll = True
        self._max_lines = 2000   # M-14: растёт неограниченно -> кап

    def copy_text(self):
        self.clipboard_clear()
        self.clipboard_append(self.get("1.0", "end").strip())

    def write(self, msg, tag="info"):
        self.insert("end", msg + "\n", tag)
        # M-14: держим не более _max_lines строк
        try:
            line_count = int(self.index("end-1c").split(".")[0])
            if line_count > self._max_lines:
                self.delete("1.0", f"{line_count - self._max_lines}.0")
        except Exception:
            pass
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
            self._div.bind("<ButtonRelease-1>", self.stop_drag)
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
            self._div.bind("<ButtonRelease-1>", self.stop_drag)

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
