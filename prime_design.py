#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRIME Living Interface — глобальный уникальный редизайн URLMonster.

Идея, которой нет ни у кого: интерфейс-организм.
- Цвет дышит от скорости: холодный простой → горячий пик.
- Конвейер — нейронная цепочка с импульсом, а не прогресс-бар.
- Лог — таймлайн событий с плотностью, а не плоский текст.
- Метрики — спарклайны истории, а не цифры.
- Управление — командная палитра Ctrl+K, а не лабиринт кнопок.
"""
import time
import tkinter as tk
import customtkinter as ctk

PRIME_THEMES = {
    # Такого нет ни в одном чекере: глубокий океан + биолюминесценция
    "prime_abyss": {
        "bg": "#030B14", "card": "#071626", "border": "#0E2E4A",
        "text": "#DFF3FF", "text_sec": "#6FA8C9", "accent": "#00E5A0",
        "accent2": "#4DC3FF", "danger": "#FF5D73", "warn": "#FFC94D",
    },
    # Песчаная буря на закате: тёплый, но тёмный — редкое сочетание
    "prime_dune": {
        "bg": "#140E08", "card": "#221610", "border": "#4A2E1A",
        "text": "#FFF1DE", "text_sec": "#C9A06F", "accent": "#FF9E3D",
        "accent2": "#FFD23D", "danger": "#FF5D5D", "warn": "#FFE066",
    },
    # Мох + фрактал: приглушённый зелёный, не «матрица», а лес
    "prime_moss": {
        "bg": "#0A0F0A", "card": "#131A12", "border": "#24301F",
        "text": "#EAF5E4", "text_sec": "#8AA37E", "accent": "#9DFF57",
        "accent2": "#E4FF57", "danger": "#FF6B6B", "warn": "#FFD93D",
    },
    # Ионный шторм: электрический индиго + коралл
    "prime_ion": {
        "bg": "#0B0B1E", "card": "#151538", "border": "#2C2C6E",
        "text": "#ECECFF", "text_sec": "#8E8ED1", "accent": "#7C7CFF",
        "accent2": "#FF7C9E", "danger": "#FF5D5D", "warn": "#FFD23D",
    },
    # Бархат + медь: премиальный тёмный, неонов нет вообще
    "prime_velvet": {
        "bg": "#120A12", "card": "#1E121E", "border": "#3E243E",
        "text": "#F8EAF8", "text_sec": "#B98AB9", "accent": "#E09A4D",
        "accent2": "#F5D08A", "danger": "#FF6B6B", "warn": "#FFE066",
    },
}

# Скоростная палитра: цвет как данные (0 МБ/с → 500+ МБ/с)
SPEED_STOPS = [
    (0, "#3A4A5E"), (20, "#00E5A0"), (80, "#4DC3FF"),
    (200, "#FFD23D"), (400, "#FF7C3D"), (600, "#FF3D7C"),
]

def speed_color(mbps: float) -> str:
    """Интерполяция цвета по скорости. Живой индикатор нагрузки."""
    try:
        v = float(mbps)
    except Exception:
        return SPEED_STOPS[0][1]
    if v <= 0:
        return SPEED_STOPS[0][1]
    for i in range(len(SPEED_STOPS) - 1):
        a_v, a_c = SPEED_STOPS[i]
        b_v, b_c = SPEED_STOPS[i + 1]
        if a_v <= v <= b_v:
            t = (v - a_v) / max(1e-6, (b_v - a_v))
            return _lerp_hex(a_c, b_c, t)
    return SPEED_STOPS[-1][1]

def _lerp_hex(a: str, b: str, t: float) -> str:
    def _p(h):
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    ar, ag, ab = _p(a)
    br, bg, bb = _p(b)
    r = int(ar + (br - ar) * t)
    g = int(ag + (bg - ag) * t)
    bl = int(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"


def register_prime_themes():
    """Вживляет PRIME-темы в ui_components без поломки старого кода."""
    try:
        import ui_components as ui
        for k, v in PRIME_THEMES.items():
            if k not in ui.THEMES:
                ui.THEMES[k] = v
        return list(PRIME_THEMES.keys())
    except Exception:
        return []


class SparkCard(ctk.CTkFrame):
    """Метрика со спарклайном истории — видно тренд, а не только цифру."""

    def __init__(self, master, label, value="—", unit="", icon="◈", history=60, **kw):
        from ui_components import th
        super().__init__(master, fg_color=th("card"), corner_radius=14,
                         border_width=1, border_color=th("border"), **kw)
        self._hist = []
        self._max = history
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(top, text=icon, font=("Segoe UI", 16),
                     text_color=th("text_sec")).pack(side="left")
        ctk.CTkLabel(top, text=label, font=("Segoe UI", 11),
                     text_color=th("text_sec")).pack(side="right")
        self._val = ctk.CTkLabel(self, text=f"{value}{unit}",
                                 font=("Segoe UI", 20, "bold"),
                                 text_color=th("text"), anchor="w")
        self._val.pack(fill="x", padx=12)
        self._cv = tk.Canvas(self, height=30, highlightthickness=0, bd=0)
        self._cv.pack(fill="x", padx=8, pady=(0, 8))
        self._unit = unit
        try:
            self._cv.configure(bg=self.cget("fg_color"))
        except Exception:
            pass

    def set(self, value, unit=None, raw=None):
        from ui_components import th
        if unit is None:
            unit = self._unit
        try:
            self._val.configure(text=f"{value}{unit}")
        except Exception:
            pass
        try:
            v = float(raw if raw is not None else str(value).replace(",", ".").split()[0])
        except Exception:
            return
        self._hist.append(v)
        if len(self._hist) > self._max:
            self._hist = self._hist[-self._max:]
        self._draw(th("accent"))

    def _draw(self, color):
        try:
            self._cv.delete("all")
            w = self._cv.winfo_width() or 200
            h = 30
            hs = self._hist
            if len(hs) < 2:
                return
            mn, mx = min(hs), max(hs)
            rng = (mx - mn) or 1.0
            pts = []
            for i, v in enumerate(hs):
                x = 4 + i * (w - 8) / max(1, len(hs) - 1)
                y = h - 4 - (v - mn) / rng * (h - 8)
                pts.extend([x, y])
            self._cv.create_line(*pts, fill=color, width=2, smooth=True)
        except Exception:
            pass


class PulseProgress(ctk.CTkFrame):
    """Прогресс с бегущим импульсом — видно жизнь, а не зависший бар."""

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._cv = tk.Canvas(self, height=10, highlightthickness=0, bd=0)
        self._cv.pack(fill="x", expand=True)
        self._frac = 0.0
        self._pulse = 0.0
        self._color = "#00E5A0"
        self._run = False

    def set(self, frac, color=None):
        self._frac = max(0.0, min(1.0, float(frac or 0.0)))
        if color:
            self._color = color
        self._draw()

    def start(self):
        self._run = True
        self._tick()

    def stop(self):
        self._run = False

    def _tick(self):
        if not self._run:
            return
        self._pulse = (self._pulse + 0.06) % 1.0
        self._draw()
        try:
            self.after(50, self._tick)
        except Exception:
            pass

    def _draw(self):
        try:
            self._cv.delete("all")
            w = self._cv.winfo_width() or 300
            h = 10
            self._cv.create_rectangle(0, 2, w, h - 2, fill="#1A2433", outline="")
            fw = int(w * self._frac)
            if fw > 0:
                self._cv.create_rectangle(0, 2, fw, h - 2, fill=self._color, outline="")
            px = int(w * self._pulse)
            self._cv.create_oval(px - 5, 0, px + 5, h, fill="white", outline="")
        except Exception:
            pass


class CommandPalette(ctk.CTkToplevel):
    """Ctrl+K палитра: все действия в одном месте с fuzzy-поиском."""

    def __init__(self, master, commands):
        """
        commands: list[(title, hint, callback)]
        """
        from ui_components import th
        super().__init__(master, fg_color=th("bg"))
        self.title("Команды")
        self.geometry("560x420")
        self.resizable(False, False)
        self._commands = list(commands)
        self._filtered = list(commands)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.after(100, self.lift)
        ctk.CTkLabel(self, text="⌘  Команды  (Ctrl+K)",
                     font=("Segoe UI", 13, "bold"),
                     text_color=th("text")).pack(anchor="w", padx=16, pady=(12, 4))
        self._q = ctk.StringVar()
        self._q.trace_add("write", lambda *_: self._filter())
        ent = ctk.CTkEntry(self, textvariable=self._q,
                           placeholder_text="старт, результаты, тема, разбить…",
                           height=38, font=("Segoe UI", 12))
        ent.pack(fill="x", padx=16, pady=4)
        ent.focus_set()
        self._box = tk.Listbox(self, height=14, borderwidth=0, highlightthickness=0,
                               font=("Segoe UI", 12))
        self._box.pack(fill="both", expand=True, padx=16, pady=8)
        self._box.bind("<Double-Button-1>", lambda *_: self._run())
        self._box.bind("<Return>", lambda *_: self._run())
        self.bind("<Escape>", lambda *_: self.destroy())
        try:
            self._box.configure(bg=th("card"), fg=th("text"),
                                selectbackground=th("accent"))
        except Exception:
            pass
        self._refresh()

    def _filter(self):
        q = self._q.get().lower().strip()
        if not q:
            self._filtered = list(self._commands)
        else:
            out = []
            for title, hint, cb in self._commands:
                hay = f"{title} {hint}".lower()
                # fuzzy: все символы запроса по порядку
                it = iter(hay)
                if all(c in it for c in q):
                    out.append((title, hint, cb))
            self._filtered = out
        self._refresh()

    def _refresh(self):
        self._box.delete(0, "end")
        for title, hint, _ in self._filtered[:50]:
            self._box.insert("end", f"{title}   ·   {hint}")
        if self._filtered:
            self._box.selection_set(0)

    def _run(self):
        try:
            idx = self._box.curselection()[0]
            _, _, cb = self._filtered[idx]
        except Exception:
            return
        try:
            self.destroy()
        except Exception:
            pass
        try:
            cb()
        except Exception:
            pass


class TimelineLog(ctk.CTkTextbox):
    """Лог-таймлайн: время + тип + плотность. Замена плоскому логу."""

    def __init__(self, master, **kw):
        super().__init__(master, wrap="none", **kw)
        self._t0 = time.time()

    def event(self, msg, kind="info"):
        from ui_components import th
        colors = {"info": th("text_sec"), "ok": th("accent2"),
                  "warn": th("warn"), "err": th("danger"), "hot": th("accent")}
        ts = time.strftime("%H:%M:%S")
        tag = f"k_{kind}_{int(time.time()*1000)%99999}"
        try:
            self.tag_config(tag, foreground=colors.get(kind, th("text")))
        except Exception:
            pass
        try:
            self.insert("end", f"[{ts}] ", "dim")
            self.insert("end", msg + "\n", tag)
            self.see("end")
            # кап строк — защита от раздувания
            lc = int(self.index("end-1c").split(".")[0])
            if lc > 3000:
                self.delete("1.0", f"{lc-3000}.0")
        except Exception:
            pass
