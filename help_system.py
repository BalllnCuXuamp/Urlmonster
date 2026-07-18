import customtkinter as ctk
from ui_components import th

HELP_PAGES = {
    "welcome": {
        "title": "👋 Добро пожаловать!",
        "text": (
            "URLmonster — инструмент для поиска и извлечения данных\n"
            "из больших текстовых файлов по множеству масок.\n\n"
            "Возможности:\n"
            "• Поиск по 196+ запросам одновременно\n"
            "• Обработка файлов до 100+ GB\n"
            "• Rust-ядро для максимальной скорости\n"
            "• Дедупликация между запусками\n"
            "• Докачка прерванных сканов\n"
            "• Встроенный Web UI и системный трей"
        ),
    },
    "queries": {
        "title": "📋 Запросы",
        "text": (
            "Файл queries.txt содержит список запросов.\n\n"
            "Формат:\n"
            "  [GroupName]\n"
            "  login:example\n"
            "  full:example.com\n"
            "  site.com\n\n"
            "Префиксы:\n"
            "  full: — сохранить полную строку с https://\n"
            "  login: — сохранить только логин\n"
            "  без префикса — по настройке умолчания\n\n"
            "Группы:[Credentials], [URLs] и т.д.\n"
            "Можно выбирать группу в редакторе запросов."
        ),
    },
    "modes": {
        "title": "⚙️ Режимы",
        "text": (
            "Режимы парсинга строк:\n\n"
            "Auto — автоопределение формата\n"
            "  • Если в строке есть :// → URL режим\n"
            "  • Иначе → Default\n\n"
            "Default — последние 2 поля после разделителя\n"
            "  login:password  или  url;login;password\n\n"
            "URL — добавляет https:// если нет протокола\n"
            "  site.com:user:pass → https://site.com:user:pass\n\n"
            "Exact — строго 2 части через разделитель\n"
            "  user:pass — OK,  user:pass:extra — NO\n\n"
            "Domain — нормализует запрос до домена\n"
            "  https://www.site.com/path → site.com"
        ),
    },
    "filter": {
        "title": "🔍 Фильтры",
        "text": (
            "Исключать пустые — строки без логина/пароля\n\n"
            "Учитывать регистр — точное совпадение\n\n"
            "Blacklist — исключающие фразы\n"
            "  Строки, содержащие любую из них, пропускаются\n\n"
            "Регулярные выражения — вместо подстроки\n"
            "  Используется как паттерн regex\n\n"
            "Сохранять целиком (Full) — вся строка с https://\n"
            "  По умолчанию для всех запросов\n"
            "  Можно переопределить префиксом в queries.txt"
        ),
    },
    "output": {
        "title": "📤 Результаты",
        "text": (
            "После скана создаётся папка:\n"
            "  results/YYYY-MM-DD_HH-MM-SS/\n\n"
            "В ней:\n"
            "  {запрос}.txt — найденные пары\n"
            "  report.txt — текстовый отчёт\n"
            "  report.html — HTML с графиком\n"
            "  report.json — структурированные данные\n"
            "  logs/ — лог работы\n\n"
            "Разделитель вывода:\n"
            "  :  ;  |  Tab  Login  Password\n\n"
            "Разбить файлы — делить результат по N строк"
        ),
    },
    "resume": {
        "title": "🔄 Докачка (Resume)",
        "text": (
            "Докачка позволяет продолжить прерванный скан.\n\n"
            "Как работает:\n"
            "  • processed_files.json — какие файлы обработаны\n"
            "  • _progress.json — сколько байт обработано\n"
            "  • _checkpoint.json — точная позиция в файле\n\n"
            "При включённой докачке:\n"
            "  • Уже обработанные файлы пропускаются\n"
            "  • Прерванный файл продолжается с чекпоинта\n\n"
            "Важно: если файлы не изменились, повторный\n"
            "запуск с докачкой пропустит их.\n"
            "Для полного перескана выключите Resume."
        ),
    },
    "perf": {
        "title": "⚡ Производительность",
        "text": (
            "Тип диска — определяет число воркеров:\n"
            "  HDD = 2 | SSD = 4 | NVMe = 4\n\n"
            "Auto — определение через PowerShell Get-Disk\n\n"
            "Буферизация:\n"
            "  Чтение: 16 MB блоками\n"
            "  Запись: 4 MB буфер\n\n"
            "Rust-ядро:\n"
            "  Aho-Corasick automaton\n"
            "  До 4 GB/мин на SSD\n\n"
            "Hang detection:\n"
            "  120 сек без прогресса → terminate"
        ),
    },
}


class HelpWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master, fg_color=th("bg"))
        self.title("Справка")
        self.geometry("700x520")
        self.minsize(600, 400)
        self.after(100, self.lift)

        self._pages = list(HELP_PAGES.keys())
        self._current = 0

        ctk.CTkLabel(self, text="Справка", font=("Segoe UI", 18, "bold"), text_color=th("text")).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(self, text="Выберите тему слева или листайте", font=("Segoe UI", 11), text_color=th("text_sec")).pack(anchor="w", padx=20)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=12)

        # Sidebar
        side = ctk.CTkFrame(main, width=180, fg_color=th("card"), corner_radius=10)
        side.pack(side="left", fill="y", padx=(0, 12))
        side.pack_propagate(False)

        self._nav_btns = {}
        for i, key in enumerate(self._pages):
            page = HELP_PAGES[key]
            btn = ctk.CTkButton(
                side, text=page["title"], font=("Segoe UI", 11),
                fg_color="transparent", text_color=th("text_sec"),
                hover_color=th("border"), anchor="w", height=34,
                corner_radius=6, border_width=0,
                command=lambda k=key: self._show(k),
            )
            btn.pack(fill="x", padx=6, pady=1)
            self._nav_btns[key] = btn

        # Content
        self._content = ctk.CTkTextbox(main, font=("Segoe UI", 12), wrap="word", fg_color=th("card"), corner_radius=10, border_width=0)
        self._content.pack(side="left", fill="both", expand=True)
        self._content.configure(state="disabled")

        # Nav buttons
        nav = ctk.CTkFrame(self, fg_color="transparent", height=40)
        nav.pack(fill="x", padx=20, pady=(0, 12))
        self._prev_btn = ctk.CTkButton(nav, text="◀ Назад", width=100, command=self._prev, font=("Segoe UI", 11))
        self._prev_btn.pack(side="left")
        self._next_btn = ctk.CTkButton(nav, text="Вперёд ▶", width=100, command=self._next, font=("Segoe UI", 11))
        self._next_btn.pack(side="right")
        self._pos_label = ctk.CTkLabel(nav, text="1 / " + str(len(self._pages)), font=("Segoe UI", 11), text_color=th("text_sec"))
        self._pos_label.pack(side="bottom")

        self._show(self._pages[0])

    def _show(self, key):
        if key in HELP_PAGES:
            page = HELP_PAGES[key]
            self._current = self._pages.index(key)
            self._content.configure(state="normal")
            self._content.delete("1.0", "end")
            self._content.insert("1.0", page["text"])
            self._content.configure(state="disabled")
            self._pos_label.configure(text=f"{self._current + 1} / {len(self._pages)}")
            # Highlight active nav
            for k, btn in self._nav_btns.items():
                btn.configure(fg_color=th("accent") if k == key else "transparent",
                              text_color=th("text") if k == key else th("text_sec"))
            self._prev_btn.configure(state="normal" if self._current > 0 else "disabled")
            self._next_btn.configure(state="normal" if self._current < len(self._pages) - 1 else "disabled")

    def _prev(self):
        if self._current > 0:
            self._show(self._pages[self._current - 1])

    def _next(self):
        if self._current < len(self._pages) - 1:
            self._show(self._pages[self._current + 1])


class TutorialOverlay:
    @staticmethod
    def show(master):
        steps = [
            ("🔍 Поиск", "Введите запросы в файл queries.txt\nили отредактируйте через кнопку «Ред.»"),
            ("📁 Источник", "Укажите файл или папку с данными"),
            ("▶ Запуск", "Нажмите Start и следите за прогрессом"),
            ("📊 Монитор", "Во вкладке Monitor смотрите скорость,\nнайденные строки и ETA"),
            ("📤 Результаты", "После скана откройте Results\nдля просмотра найденного"),
        ]
        w = ctk.CTkToplevel(master, fg_color=th("bg"))
        w.title("Быстрый старт")
        w.geometry("500x380")
        w.after(100, w.lift)
        w.resizable(False, False)
        w.attributes("-topmost", True)

        ctk.CTkLabel(w, text="🚀 Быстрый старт", font=("Segoe UI", 18, "bold"), text_color=th("text")).pack(pady=(16, 4))
        ctk.CTkLabel(w, text="5 шагов для первого скана", font=("Segoe UI", 11), text_color=th("text_sec")).pack()

        frame = ctk.CTkFrame(w, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=12)

        for i, (icon, text) in enumerate(steps, 1):
            row = ctk.CTkFrame(frame, fg_color=th("card"), corner_radius=8, height=48)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            ctk.CTkLabel(row, text=f"  {i}", font=("Segoe UI", 16, "bold"),
                         text_color=th("accent"), width=36).pack(side="left")
            ctk.CTkLabel(row, text=text, font=("Segoe UI", 11), text_color=th("text"),
                         justify="left", anchor="w").pack(side="left", padx=8)

        ctk.CTkButton(w, text="✓ Понятно", command=w.destroy,
                      fg_color=th("accent"), font=("Segoe UI", 12)).pack(pady=16)
