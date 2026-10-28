import os
import shutil
import hashlib
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import time

# Re-export the theme helper so tools match the app theme
from ui_components import th, Toast

# monster_core: SpillSet — дедуп на диске (M-05), content_hash
try:
    from monster_core import SpillSet, content_hash
except ImportError:
    SpillSet = None
    content_hash = None

# ──────────────────────────────────────────────
#  File Splitter
# ──────────────────────────────────────────────
class FileSplitter(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master, fg_color=th("bg"))
        self.title("Разбить файл")
        self.geometry("520x340")
        self.resizable(False, False)
        self.after(100, self.lift)

        self._path = ctk.StringVar()
        self._lines_per_file = ctk.IntVar(value=500000)
        self._out_dir = ctk.StringVar()
        self._running = False

        ctk.CTkLabel(self, text="Splitter", font=("Segoe UI", 18, "bold"), text_color=th("text")).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(self, text="Разделить большой файл на части", font=("Segoe UI", 11), text_color=th("text_sec")).pack(anchor="w", padx=20)

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="x", padx=20, pady=16)

        # Source
        ctk.CTkLabel(frm, text="Исходный файл:", font=("Segoe UI", 11), text_color=th("text")).pack(anchor="w")
        row1 = ctk.CTkFrame(frm, fg_color="transparent")
        row1.pack(fill="x", pady=(4, 8))
        ctk.CTkEntry(row1, textvariable=self._path, font=("Segoe UI", 11), height=32).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row1, text="Обзор", width=80, height=32, command=self._browse_src, font=("Segoe UI", 11)).pack(side="right")

        # Lines per file
        ctk.CTkLabel(frm, text="Строк в каждом файле:", font=("Segoe UI", 11), text_color=th("text")).pack(anchor="w")
        ctk.CTkEntry(frm, textvariable=self._lines_per_file, font=("Segoe UI", 11), height=32).pack(fill="x", pady=(4, 8))

        # Output
        ctk.CTkLabel(frm, text="Папка для результатов:", font=("Segoe UI", 11), text_color=th("text")).pack(anchor="w")
        row2 = ctk.CTkFrame(frm, fg_color="transparent")
        row2.pack(fill="x", pady=(4, 8))
        ctk.CTkEntry(row2, textvariable=self._out_dir, font=("Segoe UI", 11), height=32).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row2, text="Обзор", width=80, height=32, command=self._browse_out, font=("Segoe UI", 11)).pack(side="right")

        # Go
        self._go_btn = ctk.CTkButton(self, text="▶ Разделить", height=40, font=("Segoe UI", 13, "bold"), command=self._run, fg_color=th("accent"))
        self._go_btn.pack(pady=12, padx=20, fill="x")

        self._status = ctk.CTkLabel(self, text="", font=("Segoe UI", 11), text_color=th("text_sec"))
        self._status.pack(padx=20, anchor="w")

    def _browse_src(self):
        p = filedialog.askopenfilename(title="Выберите файл")
        if p:
            self._path.set(p)
            if not self._out_dir.get():
                self._out_dir.set(os.path.dirname(p) + "_parts")

    def _browse_out(self):
        p = filedialog.askdirectory(title="Папка для частей")
        if p:
            self._out_dir.set(p)

    def _run(self):
        if self._running:
            return
        src = self._path.get()
        if not src or not os.path.isfile(src):
            messagebox.showerror("Ошибка", "Укажите существующий файл")
            return
        out = self._out_dir.get()
        if not out:
            messagebox.showerror("Ошибка", "Укажите папку для результатов")
            return
        os.makedirs(out, exist_ok=True)
        self._running = True
        self._go_btn.configure(state="disabled", text="⏳ Разделение...")
        # M-13: tk-переменные читаются ТОЛЬКО в main thread — значение передаётся аргументом
        max_lines = self._lines_per_file.get()
        threading.Thread(target=self._split, args=(src, out, max_lines), daemon=True).start()

    def _split(self, src, out, max_lines):
        try:
            start = time.time()
            total_lines = 0
            part = 1
            fout = None
            base = os.path.splitext(os.path.basename(src))[0]
            with open(src, "rb", buffering=8 * 1024 * 1024) as f:
                for i, line in enumerate(f, 1):
                    if fout is None:
                        fout = open(os.path.join(out, f"{base}_part{part}.txt"), "wb", buffering=4 * 1024 * 1024)
                    fout.write(line)
                    total_lines += 1
                    if i % max_lines == 0:
                        fout.close()
                        fout = None
                        part += 1
                    if i % 500000 == 0:
                        # M-13: все tk-обновления — через self.after (main thread)
                        self.after(0, lambda tl=total_lines, p=part: self._status.configure(text=f"Обработано: {tl:,} строк | Частей: {p}"))
                if fout:
                    fout.close()
            elapsed = time.time() - start
            self.after(0, lambda: self._done(total_lines, part, elapsed))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
            self.after(0, self._reset)

    def _done(self, total, parts, elapsed):
        Toast.show(self.master, f"Файл разделён: {parts} частей, {total:,} строк за {elapsed:.1f}s", "success")
        self._status.configure(text=f"✓ {parts} файлов, {total:,} строк, {elapsed:.1f}s")
        self._reset()

    def _reset(self):
        self._running = False
        self._go_btn.configure(state="normal", text="▶ Разделить")

# ──────────────────────────────────────────────
#  Merge Tool
# ──────────────────────────────────────────────
class MergeTool(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master, fg_color=th("bg"))
        self.title("Слияние результатов")
        self.geometry("600x420")
        self.resizable(False, False)
        self.after(100, self.lift)

        self._folders = []
        self._running = False

        ctk.CTkLabel(self, text="Merge Tool", font=("Segoe UI", 18, "bold"), text_color=th("text")).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(self, text="Объединить результаты нескольких сканов", font=("Segoe UI", 11), text_color=th("text_sec")).pack(anchor="w", padx=20)

        frm = ctk.CTkFrame(self, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=20, pady=12)

        ctk.CTkLabel(frm, text="Папки с результатами:", font=("Segoe UI", 11), text_color=th("text")).pack(anchor="w")
        row = ctk.CTkFrame(frm, fg_color="transparent")
        row.pack(fill="x", pady=(4, 8))
        ctk.CTkButton(row, text="+ Добавить папку", command=self._add_folder, font=("Segoe UI", 11), height=32).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="✕ Очистить", command=self._clear, fg_color=th("danger"), font=("Segoe UI", 11), height=32).pack(side="left")

        # Listbox for folders
        self._listbox = tk.Listbox(frm, bg=th("card"), fg=th("text"), selectbackground=th("border"),
                                   font=("Segoe UI", 11), borderwidth=0, highlightthickness=0, height=6)
        self._listbox.pack(fill="both", expand=True)
        ctk.CTkFrame(frm, height=1, fg_color=th("border")).pack(fill="x", pady=8)

        # Output
        self._out_var = ctk.StringVar()
        ctk.CTkLabel(frm, text="Папка для результата:", font=("Segoe UI", 11), text_color=th("text")).pack(anchor="w")
        row2 = ctk.CTkFrame(frm, fg_color="transparent")
        row2.pack(fill="x", pady=(4, 0))
        ctk.CTkEntry(row2, textvariable=self._out_var, font=("Segoe UI", 11), height=32).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row2, text="Обзор", width=80, height=32, command=self._browse_out, font=("Segoe UI", 11)).pack(side="right")

        self._merge_btn = ctk.CTkButton(self, text="▶ Слить", height=40, font=("Segoe UI", 13, "bold"), command=self._run, fg_color=th("accent"))
        self._merge_btn.pack(pady=12, padx=20, fill="x")

        self._status = ctk.CTkLabel(self, text="", font=("Segoe UI", 11), text_color=th("text_sec"))
        self._status.pack(padx=20, anchor="w")

    def _add_folder(self):
        p = filedialog.askdirectory(title="Папка с результатами скана")
        if p and p not in self._folders:
            self._folders.append(p)
            self._listbox.insert("end", os.path.basename(p) + "  —  " + p)
            if not self._out_var.get():
                self._out_var.set(os.path.join(os.path.dirname(p), "merged_results"))

    def _clear(self):
        self._folders.clear()
        self._listbox.delete(0, "end")

    def _browse_out(self):
        p = filedialog.askdirectory(title="Папка для объединённых результатов")
        if p:
            self._out_var.set(p)

    def _run(self):
        if self._running or len(self._folders) < 1:
            if len(self._folders) < 1:
                messagebox.showerror("Ошибка", "Добавьте хотя бы одну папку")
            return
        out = self._out_var.get()
        if not out:
            messagebox.showerror("Ошибка", "Укажите папку для результата")
            return
        os.makedirs(out, exist_ok=True)
        self._running = True
        self._merge_btn.configure(state="disabled", text="⏳ Слияние...")
        folders = list(self._folders)
        threading.Thread(target=self._merge, args=(out, folders), daemon=True).start()

    def _merge(self, out, folders):
        """M-05: потоковое слияние без RAM-сетов — дедуп через SpillSet (диск,
        blake2b-16). Порядок строк не сортируется, уникальность сохраняется."""
        seen_all = None
        try:
            start = time.time()
            total_input = 0
            total_unique = 0
            seen_all = SpillSet() if SpillSet is not None else None
            if seen_all is None:
                raise RuntimeError("monster_core недоступен — SpillSet (дедуп на диске) не найден")

            # Группируем файлы по qname (query)
            qfiles = {}
            for folder in folders:
                self.after(0, lambda f=folder: self._status.configure(text=f"Читаю: {os.path.basename(f)}..."))
                for fname in os.listdir(folder):
                    if not fname.endswith(".txt") or fname in ("report.txt", "report.html", "report.json", "index.sqlite"):
                        continue
                    fpath = os.path.join(folder, fname)
                    if not os.path.isfile(fpath):
                        continue
                    qname = os.path.splitext(fname)[0]
                    qfiles.setdefault(qname, []).append(fpath)

            self.after(0, lambda: self._status.configure(text="Пишу результат (потоковый дедуп)..."))
            batch = []
            for qname, fpaths in qfiles.items():
                target = os.path.join(out, f"{qname}.txt")
                fout = open(target, "wb", buffering=4 * 1024 * 1024)
                try:
                    for fpath in fpaths:
                        with open(fpath, "rb", buffering=4 * 1024 * 1024) as f:
                            for line in f:
                                line = line.rstrip(b"\r\n")
                                if not line:
                                    continue
                                total_input += 1
                                h = content_hash(line)
                                if seen_all.contains(h):
                                    continue
                                seen_all.add(h)
                                fout.write(line + b"\n")
                                total_unique += 1
                                batch.append(h)
                                if len(batch) >= 100000:
                                    batch = []
                finally:
                    fout.close()
                self.after(0, lambda ti=total_input, tu=total_unique: self._status.configure(text=f"✓ {tu:,} из {ti:,} строк..."))

            elapsed = time.time() - start
            self.after(0, lambda: self._done(total_input, total_unique, elapsed))
        except Exception as e:
            self.after(0, lambda _e=e: messagebox.showerror("Ошибка", str(_e)))
            self.after(0, self._reset)
        finally:
            # PRIME FIX: гарантия очистки spill-базы даже при исключении/прерывании
            if seen_all is not None:
                try:
                    seen_all.cleanup()
                except Exception:
                    pass

    def _done(self, total_input, total_unique, elapsed):
        Toast.show(self.master, f"Слияние готово: {total_unique:,} уникальных из {total_input:,} строк", "success")
        self._status.configure(text=f"✓ {total_unique:,} строк из {total_input:,}, {elapsed:.1f}s")
        self._reset()

    def _reset(self):
        self._running = False
        self._merge_btn.configure(state="normal", text="▶ Слить")
