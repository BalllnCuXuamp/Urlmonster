#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URLmonster PRO – полный рабочий код с современным интерфейсом на CustomTkinter.
ВСЕ ФУНКЦИИ ЧЕКЕРА ВКЛЮЧЕНЫ.
"""

# ---- Базовые импорты (без GUI — worker-safe) ----
import os, sys, re, json, time, queue, shutil, hashlib, tempfile, logging, logging.handlers, argparse, threading, subprocess, math
from datetime import datetime
from collections import Counter
import multiprocessing as mp
from multiprocessing import Process, Value

# ---- PSUTIL — опционально, для мониторинга системы ----
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ---- AHOCORASICK — легковесный ----
try:
    import ahocorasick
    AHOCORASICK_AVAILABLE = True
except ImportError:
    AHOCORASICK_AVAILABLE = False

# ---- RUST_SCAN — высокоскоростной многонитевой поиск ----
try:
    import rust_scan
    RUST_SCAN_AVAILABLE = True
except ImportError:
    RUST_SCAN_AVAILABLE = False

# ---- GUI-импорты — только в главном процессе (spawn-воркеры их не грузят) ----
if mp.current_process().name == 'MainProcess':
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    try:
        import customtkinter as ctk
    except ImportError:
        print("CustomTkinter не установлен. Установите: pip install customtkinter")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
            import customtkinter as ctk
            print("CustomTkinter успешно установлен!")
        except Exception as e:
            print(f"Не удалось установить customtkinter: {e}")
            sys.exit(1)
else:
    tk = None
    ctk = None

try:
    from ui_components import TitleBar, TabBar, LiveLog, MetricCard, th
    _UI_OK = True
except Exception:
    TitleBar = TabBar = LiveLog = MetricCard = None
    th = lambda k: "#ffffff"
    _UI_OK = False

try:
    from tools import FileSplitter, MergeTool
    from help_system import HelpWindow, TutorialOverlay
except Exception:
    FileSplitter = MergeTool = HelpWindow = TutorialOverlay = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# ---- WEB UI — встроенный HTTP-сервер ----
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
WEBUI_AVAILABLE = True

# ---- TRAY — системный трей (Windows native) ----
import struct, ctypes, ctypes.wintypes as wint, threading, queue
TRAY_AVAILABLE = True
_tray_window = None
_tray_hwnd = None
_tray_icon_id = 1001
_tray_callback_ref = None
_tray_action_queue = queue.Queue()

_WM_APP = 0x8000
_WM_TRAY_CALLBACK = _WM_APP + 1001
_NIM_ADD = 0
_NIM_DELETE = 2
_NIM_MODIFY = 1
_NIF_MESSAGE = 1
_NIF_ICON = 2
_NIF_TIP = 4
_NIF_SHOWTIP = 0x4000
_NIF_INFO = 0x10
_WM_LBUTTONDBLCLK = 0x203
_WM_RBUTTONUP = 0x205

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wint.DWORD),
        ("hWnd", wint.HWND),
        ("uID", wint.UINT),
        ("uFlags", wint.UINT),
        ("uCallbackMessage", wint.UINT),
        ("hIcon", wint.HICON),
        ("szTip", wint.WCHAR * 128),
        ("dwState", wint.DWORD),
        ("dwStateMask", wint.DWORD),
        ("szInfo", wint.WCHAR * 256),
        ("uVersion", wint.UINT),
        ("szInfoTitle", wint.WCHAR * 64),
        ("dwInfoFlags", wint.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wint.HICON),
    ]

WNDPROC = ctypes.CFUNCTYPE(ctypes.c_long, wint.HWND, wint.UINT, wint.WPARAM, wint.LPARAM)

class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wint.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wint.HINSTANCE),
        ("hIcon", wint.HICON),
        ("hCursor", wint.HICON),
        ("hbrBackground", wint.HBRUSH),
        ("lpszMenuName", wint.LPCWSTR),
        ("lpszClassName", wint.LPCWSTR),
    ]

_shell32 = ctypes.windll.shell32
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.CreateWindowExW.restype = wint.HWND
_user32.SetWindowLongPtrW.restype = ctypes.c_void_p
_user32.GetMessageW.restype = ctypes.c_long

def _create_tray_icon():
    """Создаём HICON 16x16 — сначала через PIL, иначе стандартная иконка Windows"""
    try:
        from PIL import Image, ImageDraw, ImageWin
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((1, 1, 14, 14), fill="#1DB954")
        draw.text((4, 2), "U", fill="#000000")
        hicon = ImageWin.Handle(img, None)
        if hasattr(hicon, "hicon"):
            return hicon.hicon
    except Exception:
        pass
    return _user32.LoadIconW(0, 32512)  # IDI_APPLICATION

def _tray_thread(callback):
    global _tray_hwnd

    hinstance = _kernel32.GetModuleHandleW(None)

    wc = WNDCLASS()
    wc.style = 0
    wc.lpfnWndProc = ctypes.cast(_user32.DefWindowProcW, WNDPROC)
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinstance
    wc.hIcon = 0
    wc.hCursor = 0
    wc.hbrBackground = 0
    wc.lpszMenuName = None
    wc.lpszClassName = "URLmonsterTrayWindow"
    _user32.RegisterClassW(ctypes.byref(wc))

    hwnd = _user32.CreateWindowExW(
        0, "URLmonsterTrayWindow", "", 0,
        0, 0, 0, 0, 0, 0, hinstance, None
    )
    _tray_hwnd = hwnd

    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd
    nid.uID = _tray_icon_id
    nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP | _NIF_SHOWTIP
    nid.uCallbackMessage = _WM_TRAY_CALLBACK
    nid.hIcon = _create_tray_icon()
    nid.szTip = "URLmonster"
    _shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid))

    OLD_PROC = ctypes.c_void_p(_user32.SetWindowLongPtrW(hwnd, -4, 0))

    @ctypes.CFUNCTYPE(ctypes.c_long, wint.HWND, wint.UINT, wint.WPARAM, wint.LPARAM)
    def tray_wndproc(wnd, msg, wp, lp):
        if msg == _WM_TRAY_CALLBACK:
            if lp == _WM_LBUTTONDBLCLK:
                _tray_action_queue.put("show")
            elif lp == _WM_RBUTTONUP:
                _tray_action_queue.put("menu")
        return _user32.CallWindowProcW(OLD_PROC, wnd, msg, wp, lp)

    _user32.SetWindowLongPtrW(hwnd, -4, tray_wndproc)

    msg = wint.MSG()
    while _user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        _user32.TranslateMessage(ctypes.byref(msg))
        _user32.DispatchMessageW(ctypes.byref(msg))

def _poll_tray_queue():
    try:
        while True:
            action = _tray_action_queue.get_nowait()
            cb = _tray_callback_ref
            if cb:
                try:
                    cb(action)
                except Exception:
                    pass
    except queue.Empty:
        pass
    import tkinter as tk
    root = tk._default_root
    if root:
        root.after(100, _poll_tray_queue)

def tray_setup(callback, parent=None):
    global _tray_callback_ref
    _tray_callback_ref = callback
    t = threading.Thread(target=_tray_thread, args=(callback,), daemon=True)
    t.start()
    import tkinter as tk
    root = tk._default_root
    if root:
        root.after(500, _poll_tray_queue)

def tray_remove():
    global _tray_hwnd
    if _tray_hwnd:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = _tray_hwnd
        nid.uID = _tray_icon_id
        _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid))
        _tray_hwnd = None

def tray_notify(title, text):
    global _tray_hwnd
    if not _tray_hwnd:
        return
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = _tray_hwnd
    nid.uID = _tray_icon_id
    nid.uFlags = _NIF_INFO
    nid.szInfo = text[:255]
    nid.szInfoTitle = title[:63]
    nid.dwInfoFlags = 1
    _shell32.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(nid))

# ---- Глобальные пути ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
QUERIES_FILE = os.path.join(BASE_DIR, "queries.txt")
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")
STATE_FILE = os.path.join(BASE_DIR, "processed_files.json")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "checkpoint.json")
UNIQUE_DB_FILE = os.path.join(BASE_DIR, "unique_strings.bin")
UNIQUE_DB_FILE_OLD = os.path.join(BASE_DIR, "unique_strings.json")
_HASH_BYTES = 8  # 8 байт на хеш (64-bit) — риск коллизий 3e-10 на 100K строк

MAX_CHUNK_SIZE = 2 * 1024 * 1024 * 1024  # 2 ГБ — меньше чанков, меньше процессов, меньше contention

# ---- Цветовая палитра (современный неон) ----
BG        = "#0D0F12"
CARD      = "#16181D"
FIELD     = "#1E2127"
ACCENT    = "#1DB954"
ACCENT_HV = "#25D366"
TEXT      = "#E4E6EB"
MUTED     = "#8A8F98"
RADIUS    = 10
FONT      = ("Segoe UI", 13)
FONT_BOLD = ("Segoe UI Semibold", 14)
MONO      = ("JetBrains Mono", 12)

THEMES = {
    "Изумруд": {"bg":"#0D0F12","card":"#16181D","field":"#1E2127","accent":"#1DB954","accent_hv":"#25D366","text":"#E4E6EB","muted":"#8A8F98","pb":"#7CE0A0"},
    "Аметист": {"bg":"#120D1A","card":"#1E1628","field":"#2A1F38","accent":"#A855F7","accent_hv":"#C084FC","text":"#EEE5FF","muted":"#9A8FB8","pb":"#C084FC"},
    "Сапфир":  {"bg":"#0D111F","card":"#161B30","field":"#1E2440","accent":"#3B82F6","accent_hv":"#60A5FA","text":"#E0E8FF","muted":"#8899CC","pb":"#60A5FA"},
    "Рубин":   {"bg":"#1A0D0D","card":"#2A1616","field":"#3A1E1E","accent":"#EF4444","accent_hv":"#F87171","text":"#FFE0E0","muted":"#CC8888","pb":"#F87171"},
    "Солнце":  {"bg":"#1A170D","card":"#2A2516","field":"#3A331E","accent":"#F59E0B","accent_hv":"#FBBF24","text":"#FFF8E0","muted":"#CCB888","pb":"#FBBF24"},
    "Неон":    {"bg":"#0D0D1A","card":"#16162A","field":"#1E1E3A","accent":"#06B6D4","accent_hv":"#22D3EE","text":"#E0F8FF","muted":"#88AACC","pb":"#22D3EE"},
}

# ---- Глобальные переменные ----
QUERIES_DATA = []   # список (query, flag)
QUERIES_GROUPS = {} # dict group_name -> [(query, flag), ...]
_unique_hashes = None
LANGUAGE = "ru"  # текущий язык интерфейса

LANGUAGES = {
    "ru": {
        "app_title": "URLmonster PRO",
        "base_label": "База (файл или папка)",
        "out_label": "Папка результатов",
        "mode_label": "Режим",
        "mode_auto": "Авто",
        "mode_default": "Стандарт",
        "mode_url": "URL",
        "mode_exact": "Точный",
        "mode_domain": "Домен",
        "filters": "Фильтры",
        "filter_exclude_empty": "Исключать пустые",
        "filter_case_sensitive": "Учитывать регистр",
        "options": "Опции",
        "opt_multiprocess": "Мультипроцесс",
        "opt_resume": "Режим докачки",
        "opt_regex": "Регулярки",
        "opt_unique_db": "Уникальная БД",
        "opt_save_full": "Сохранять строку целиком",
        "opt_split": "Разбить файлы (строк)",
        "opt_delim": "Разделитель",
        "opt_dry_run": "Тест (без сохр.)",
        "delim_colon": "двоеточие",
        "delim_semicolon": "точка с запятой",
        "delim_pipe": "пайп",
        "delim_tab": "табуляция",
        "delim_login": "login:password",
        "delim_password": "password:login",
        "perf_mode": "Производительность",
        "perf_auto": "Авто",
        "perf_hdd": "HDD",
        "perf_ssd": "SSD",
        "perf_nvme": "NVMe",
        "theme": "Тема",
        "preset": "Пресет",
        "preset_default": "(по умолчанию)",
        "group": "Группа",
        "group_all": "все",
        "queries_label": "запросов",
        "queries_edit": "Ред.",
        "queries_empty": "В выбранной группе нет запросов!",
        "blacklist_label": "Blacklist",
        "blacklist_edit": "Редактировать",
        "btn_start": "Запуск",
        "btn_stop": "Стоп",
        "btn_watch_start": "Наблюдать",
        "btn_watch_stop": "Наблюдение...",
        "btn_results": "Результаты",
        "btn_webui": "Web UI",
        "btn_file": "Файл",
        "btn_folder": "Папка",
        "btn_save": "Сохранить",
        "btn_cancel": "Отмена",
        "btn_delete": "Удалить",
        "btn_add": "Добавить",
        "btn_ok": "OK",
        "stat_speed": "Скорость",
        "stat_found": "Найдено",
        "stat_eta": "Осталось",
        "stat_files": "Файлы",
        "stat_elapsed": "Время",
        "log_title": "ЛОГ",
        "err_no_src": "Укажите путь к базе!",
        "err_no_queries": "Добавьте запросы через редактор!",
        "err_no_outdir": "Папка результатов не найдена!",
        "err_no_results": "Нет результатов!",
        "err_no_result_files": "Нет файлов результатов в последней папке!",
        "err_no_watch_dir": "Для наблюдения укажите папку в поле 'База'!",
        "err_group_empty": "В выбранной группе нет запросов!",
        "watch_started": "Наблюдение запущено",
        "watch_stopped": "Наблюдение остановлено",
        "check_started": "Запуск чека...",
        "check_done": "Чек завершён",
        "check_unexpected": "Поток завершился неожиданно",
        "check_stopping": "Останавливаю...",
        "check_stopped": "Остановлено пользователем",
        "success_title": "МИССИЯ ВЫПОЛНЕНА",
        "success_new": "Новых уникальных строк",
        "success_dup": "Уже существовало",
        "success_total_db": "Всего в базе уникальных строк",
        "success_time": "Время",
        "success_speed": "Средняя скорость",
        "success_results": "Результаты",
        "edit_queries_title": "Редактор запросов",
        "edit_queries_placeholder": "Введите запрос (или full:/login:)",
        "edit_queries_add": "Добавить",
        "edit_blacklist_title": "Blacklist",
        "edit_blacklist_header": "ИСКЛЮЧАЮЩИЕ ФРАЗЫ (по одной на строку)",
        "results_viewer_title": "Просмотр результатов",
        "results_file": "Файл",
        "results_search": "Поиск",
        "results_filter_placeholder": "Фильтр...",
        "results_rows": "Строк",
        "results_shown": "Показано",
        "preset_save_title": "Сохранить пресет",
        "preset_save_prompt": "Введите название пресета:",
        "preset_delete_confirm": "Удалить пресет '%s'?",
        "preset_delete_title": "Удалить",
        "lang": "Язык",
        "watch_new_files": "Найдены новые файлы, запускаю...",
        "btn_merge": "Объединить",
        "btn_split": "Разделить",
        "btn_help": "Помощь",
        "tab_dashboard": "Дашборд",
        "tab_monitor": "Монитор",
        "tab_settings": "Настройки",
        "tab_results": "Результаты",
        "tab_history": "История",
        "dash_speed_mb": "Скорость (МБ/с)",
        "dash_speed_lines": "Скорость (строк/с)",
        "dash_found": "Найдено",
        "dash_files": "Файлы",
        "dash_eta": "Осталось",
        "dash_elapsed": "Времени прошло",
        "dash_progress": "Прогресс",
    },
    "en": {
        "app_title": "URLmonster PRO",
        "base_label": "Source (file or folder)",
        "out_label": "Output folder",
        "mode_label": "Mode",
        "mode_auto": "Auto",
        "mode_default": "Default",
        "mode_url": "URL",
        "mode_exact": "Exact",
        "mode_domain": "Domain",
        "filters": "Filters",
        "filter_exclude_empty": "Exclude empty",
        "filter_case_sensitive": "Case sensitive",
        "options": "Options",
        "opt_multiprocess": "Multiprocess",
        "opt_resume": "Resume mode",
        "opt_regex": "Regex",
        "opt_unique_db": "Unique DB",
        "opt_save_full": "Save full line",
        "opt_split": "Split files (lines)",
        "opt_delim": "Delimiter",
        "opt_dry_run": "Dry run",
        "delim_colon": "colon",
        "delim_semicolon": "semicolon",
        "delim_pipe": "pipe",
        "delim_tab": "tab",
        "delim_login": "login:password",
        "delim_password": "password:login",
        "perf_mode": "Performance",
        "perf_auto": "Auto",
        "perf_hdd": "HDD",
        "perf_ssd": "SSD",
        "perf_nvme": "NVMe",
        "theme": "Theme",
        "preset": "Preset",
        "preset_default": "(default)",
        "group": "Group",
        "group_all": "all",
        "queries_label": "queries",
        "queries_edit": "Edit",
        "queries_empty": "No queries in selected group!",
        "blacklist_label": "Blacklist",
        "blacklist_edit": "Edit",
        "btn_start": "Start",
        "btn_stop": "Stop",
        "btn_watch_start": "Watch",
        "btn_watch_stop": "Watching...",
        "btn_results": "Results",
        "btn_webui": "Web UI",
        "btn_file": "File",
        "btn_folder": "Folder",
        "btn_save": "Save",
        "btn_cancel": "Cancel",
        "btn_delete": "Delete",
        "btn_add": "Add",
        "btn_ok": "OK",
        "stat_speed": "Speed",
        "stat_found": "Found",
        "stat_eta": "ETA",
        "stat_files": "Files",
        "stat_elapsed": "Elapsed",
        "log_title": "LOG",
        "err_no_src": "Specify a source file or folder!",
        "err_no_queries": "Add queries in the editor!",
        "err_no_outdir": "Output folder not found!",
        "err_no_results": "No results!",
        "err_no_result_files": "No result files in the latest folder!",
        "err_no_watch_dir": "Specify a folder as source for watch mode!",
        "err_group_empty": "No queries in the selected group!",
        "watch_started": "Watch started",
        "watch_stopped": "Watch stopped",
        "check_started": "Starting check...",
        "check_done": "Check finished",
        "check_unexpected": "Thread ended unexpectedly",
        "check_stopping": "Stopping...",
        "check_stopped": "Stopped by user",
        "success_title": "MISSION COMPLETE",
        "success_new": "New unique strings",
        "success_dup": "Already existed",
        "success_total_db": "Total unique strings in DB",
        "success_time": "Time",
        "success_speed": "Average speed",
        "success_results": "Results",
        "edit_queries_title": "Query editor",
        "edit_queries_placeholder": "Enter query (or full:/login:)",
        "edit_queries_add": "Add",
        "edit_blacklist_title": "Blacklist",
        "edit_blacklist_header": "EXCLUDING PHRASES (one per line)",
        "results_viewer_title": "Results viewer",
        "results_file": "File",
        "results_search": "Search",
        "results_filter_placeholder": "Filter...",
        "results_rows": "Rows",
        "results_shown": "Shown",
        "preset_save_title": "Save preset",
        "preset_save_prompt": "Enter preset name:",
        "preset_delete_confirm": "Delete preset '%s'?",
        "preset_delete_title": "Delete",
        "lang": "Language",
        "watch_new_files": "New files found, starting...",
        "btn_merge": "Merge",
        "btn_split": "Split",
        "btn_help": "Help",
        "tab_dashboard": "Dashboard",
        "tab_monitor": "Monitor",
        "tab_settings": "Settings",
        "tab_results": "Results",
        "tab_history": "History",
        "dash_speed_mb": "Speed (MB/s)",
        "dash_speed_lines": "Speed (lines/s)",
        "dash_found": "Found",
        "dash_files": "Files",
        "dash_eta": "ETA",
        "dash_elapsed": "Elapsed",
        "dash_progress": "Progress",
    },
}

def _(key, *args):
    """Translate a UI string key. Pass LANGUAGE from global scope."""
    lang = LANGUAGE
    entry = LANGUAGES.get(lang, LANGUAGES["ru"]).get(key, LANGUAGES["ru"].get(key, key))
    if args:
        return entry % args
    return entry

# ============================================================
#  ВСЕ ФУНКЦИИ ЧЕКЕРА
# ============================================================

def _try_migrate_json():
    if os.path.exists(UNIQUE_DB_FILE_OLD) and not os.path.exists(UNIQUE_DB_FILE):
        try:
            with open(UNIQUE_DB_FILE_OLD, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                raw = b''.join(bytes.fromhex(h)[:_HASH_BYTES] for h in data if isinstance(h, str))
                with open(UNIQUE_DB_FILE, "wb") as f:
                    f.write(raw)
                os.remove(UNIQUE_DB_FILE_OLD)
                logging.getLogger("URLChecker").info(f"Migrated unique DB: JSON -> binary ({len(data)} hashes)")
        except Exception as e:
            logging.getLogger("URLChecker").error(f"Migration failed: {e}")

def load_unique_db():
    global _unique_hashes
    if _unique_hashes is None:
        _try_migrate_json()
        if os.path.exists(UNIQUE_DB_FILE):
            try:
                with open(UNIQUE_DB_FILE, "rb") as f:
                    data = f.read()
                _unique_hashes = {data[i:i+_HASH_BYTES] for i in range(0, len(data) - len(data) % _HASH_BYTES, _HASH_BYTES)} if data else set()
            except Exception:
                _unique_hashes = set()
        else:
            _unique_hashes = set()
    return _unique_hashes

def save_unique_db(hashes):
    try:
        with open(UNIQUE_DB_FILE, "wb") as f:
            f.write(b''.join(hashes))
    except Exception as e:
        logging.error(f"Не удалось сохранить базу уникальных строк: {e}")

def add_unique_strings(new_hashes):
    hashes = load_unique_db()
    before = len(hashes)
    hashes.update(new_hashes)
    if len(hashes) != before:
        save_unique_db(hashes)
    return len(hashes)

def sanitize_for_json(obj):
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, dict):
        return {sanitize_for_json(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    return str(obj)

def safe_filename(q):
    s = re.sub(r'[\\/:*?"<>|]', '_', q)
    if len(s) > 100:
        hash_part = hashlib.md5(q.encode()).hexdigest()[:8]
        s = s[:50] + "_" + hash_part
    return s

def build_filename_map(queries):
    safe_to_orig, orig_to_safe = {}, {}
    for q in queries:
        safe = safe_filename(q)
        if safe in safe_to_orig:
            c = 1
            while f"{safe}_{c}" in safe_to_orig:
                c += 1
            safe = f"{safe}_{c}"
        safe_to_orig[safe] = q
        orig_to_safe[q] = safe
    return safe_to_orig, orig_to_safe

def fmt_time(s):
    if not isinstance(s, (int, float)):
        return "∞"
    if not math.isfinite(s):
        return "∞"
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

ARCHIVE_EXTS = {".zip", ".7z", ".tar", ".gz", ".tgz", ".rar", ".tar.gz", ".bz2", ".tar.bz2", ".xz", ".tar.xz"}

def is_archive(path):
    name = path.lower()
    for ext in ARCHIVE_EXTS:
        if name.endswith(ext):
            return True
    return False

def _find_unrar():
    """Find unrar executable path."""
    exe = shutil.which("unrar")
    if exe:
        return exe
    common = [
        r"C:\Program Files\WinRAR\unrar.exe",
        r"C:\Program Files (x86)\WinRAR\unrar.exe",
        os.path.join(os.path.dirname(sys.executable), "unrar.exe"),
        os.path.join(os.path.dirname(__file__), "unrar.exe"),
    ]
    for p in common:
        if os.path.isfile(p):
            return p
    return None

def _extract_rar(path, dest_dir):
    extracted = []
    unrar_path = _find_unrar()
    if unrar_path:
        try:
            subprocess.run([unrar_path, "x", path, dest_dir + os.sep],
                           capture_output=True, timeout=120)
            for root, _, names in os.walk(dest_dir):
                for n in names:
                    extracted.append(os.path.join(root, n))
            if extracted:
                return extracted
        except Exception:
            pass
    try:
        import rarfile
        rf = rarfile.RarFile(path)
        rf.extractall(dest_dir)
        for root, _, names in os.walk(dest_dir):
            for n in names:
                extracted.append(os.path.join(root, n))
        if extracted:
            return extracted
    except Exception:
        pass
    winrar = shutil.which("winrar")
    if winrar:
        try:
            subprocess.run([winrar, "x", path, dest_dir + os.sep],
                           capture_output=True, timeout=60)
            for root, _, names in os.walk(dest_dir):
                for n in names:
                    extracted.append(os.path.join(root, n))
            if extracted:
                return extracted
        except Exception:
            pass
    try:
        subprocess.run(["7z", "x", path, f"-o{dest_dir}", "-y"],
                       capture_output=True, timeout=60)
        for root, _, names in os.walk(dest_dir):
            for n in names:
                extracted.append(os.path.join(root, n))
    except Exception:
        pass
    return extracted

def extract_archive(path, dest_dir):
    """Extract archive to dest_dir. Returns list of extracted file paths."""
    extracted = []
    try:
        if path.lower().endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(path) as zf:
                zf.extractall(dest_dir)
                extracted = [os.path.join(dest_dir, f) for f in zf.namelist()
                             if os.path.isfile(os.path.join(dest_dir, f))]
        elif path.lower().endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
            import tarfile
            with tarfile.open(path) as tf:
                tf.extractall(dest_dir)
                extracted = [os.path.join(dest_dir, m.name) for m in tf.getmembers()
                             if m.isfile()]
        elif path.lower().endswith(".gz") and not path.lower().endswith(".tar.gz"):
            import gzip
            out_name = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(dest_dir, out_name)
            with gzip.open(path, 'rb') as fin:
                with open(out_path, 'wb') as fout:
                    shutil.copyfileobj(fin, fout)
            extracted.append(out_path)
        elif path.lower().endswith(".bz2") and not path.lower().endswith(".tar.bz2"):
            import bz2
            out_name = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(dest_dir, out_name)
            with bz2.open(path, 'rb') as fin:
                with open(out_path, 'wb') as fout:
                    shutil.copyfileobj(fin, fout)
            extracted.append(out_path)
        elif path.lower().endswith(".xz") and not path.lower().endswith(".tar.xz"):
            try:
                subprocess.run(["xz", "-d", "-k", "-c", path],
                               capture_output=True, timeout=60,
                               stdout=open(os.path.join(dest_dir, os.path.splitext(os.path.basename(path))[0]), 'wb'))
                for root, _, names in os.walk(dest_dir):
                    for n in names:
                        extracted.append(os.path.join(root, n))
            except Exception:
                pass
        elif path.lower().endswith(".7z"):
            try:
                subprocess.run(["7z", "x", path, f"-o{dest_dir}", "-y"],
                               capture_output=True, timeout=60)
                for root, _, names in os.walk(dest_dir):
                    for n in names:
                        extracted.append(os.path.join(root, n))
            except Exception:
                pass
        elif path.lower().endswith(".rar"):
            extracted = _extract_rar(path, dest_dir)
    except Exception as e:
        logging.getLogger("URLChecker").warning(f"Failed to extract {path}: {e}")
    return extracted

def collect_files(path, name_filter=None):
    files = []
    temp_dirs = []
    if os.path.isfile(path):
        if is_archive(path):
            td = tempfile.mkdtemp(prefix="urlmonster_archive_")
            extracted = extract_archive(path, td)
            for f in extracted:
                if f.lower().endswith(".txt"):
                    if name_filter is None or name_filter(f):
                        files.append(f)
            temp_dirs.append(td)
        else:
            if name_filter is None or name_filter(path):
                files.append(path)
    elif os.path.isdir(path):
        for root, _, names in os.walk(path):
            for n in names:
                fp = os.path.join(root, n)
                if is_archive(fp):
                    td = tempfile.mkdtemp(prefix="urlmonster_archive_")
                    extracted = extract_archive(fp, td)
                    for f in extracted:
                        if f.lower().endswith(".txt"):
                            if name_filter is None or name_filter(f):
                                files.append(f)
                    temp_dirs.append(td)
                elif n.lower().endswith(".txt"):
                    if name_filter is None or name_filter(fp):
                        files.append(fp)
    return files, temp_dirs

def parse_query_line(line):
    line = line.strip()
    if not line:
        return None, None
    if line.startswith("full:"):
        return line[5:], True
    elif line.startswith("login:"):
        return line[6:], False
    else:
        return line, None



def load_queries_from_file():
    """Returns (flat_list, groups_dict). Groups parsed from [Group] headers."""
    global QUERIES_GROUPS
    result = []
    groups = {"General": []}
    current = "General"
    if os.path.exists(QUERIES_FILE):
        try:
            with open(QUERIES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        current = line[1:-1].strip()
                        if current not in groups:
                            groups[current] = []
                        continue
                    q, flag = parse_query_line(line)
                    if q is not None:
                        result.append((q, flag))
                        groups.setdefault(current, []).append((q, flag))
        except Exception:
            pass
    QUERIES_GROUPS = groups
    return result  # keep returning flat list for backward compat

def save_queries_to_file(queries_data, groups=None):
    if groups is None:
        groups = QUERIES_GROUPS if QUERIES_GROUPS else {}
    if not groups:
        groups = {"General": queries_data}
    flat_map = {q: flag for q, flag in queries_data}
    lines = []
    for name, gqueries in groups.items():
        valid = [(q, f) for q, f in gqueries if q in flat_map]
        if not valid:
            continue
        lines.append(f"[{name}]")
        for q, f in valid:
            flat_map.pop(q, None)
            lines.append(f"full:{q}" if f is True else f"login:{q}" if f is False else q)
    if flat_map:
        lines.append("[General]")
        for q, f in flat_map.items():
            lines.append(f"full:{q}" if f is True else f"login:{q}" if f is False else q)
    try:
        with open(QUERIES_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logging.error(f"Не удалось сохранить запросы: {e}")

def setup_logger(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("URLChecker")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        logger.handlers.clear()
    handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir, "checker.log"), maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console)
    return logger

def save_settings(src, out, queries_data, mode, filters, use_multiprocess, use_resume, regex_mode, blacklist, split_size, export_delim, theme, default_save_full, use_unique_db, perf_mode='auto'):
    try:
        data = {k: sanitize_for_json(v) for k, v in [('src',src),('out',out),('queries_data',queries_data),('mode',mode),('filters',filters),('use_multiprocess',use_multiprocess),('use_resume',use_resume),('regex_mode',regex_mode),('blacklist',blacklist),('split_size',split_size),('export_delim',export_delim),('theme',theme),('default_save_full',default_save_full),('use_unique_db',use_unique_db),('perf_mode',perf_mode)]}
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Не удалось сохранить настройки: {e}")

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def load_presets():
    if os.path.exists(PRESETS_FILE):
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_presets(presets):
    try:
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(sanitize_for_json(presets), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Не удалось сохранить пресеты: {e}")

def load_processed_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_processed_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sanitize_for_json(state), f, indent=2)
    except Exception as e:
        logging.error(f"Не удалось сохранить состояние: {e}")

def get_new_files(files, state):
    new_files = []
    for f in files:
        try:
            st = os.stat(f)
            if f not in state:
                new_files.append(f)
            else:
                old = state[f]
                if isinstance(old, (list, tuple)) and len(old) == 2:
                    if old[0] != st.st_size or old[1] != st.st_mtime:
                        new_files.append(f)
                else:
                    new_files.append(f)
        except Exception:
            new_files.append(f)
    return new_files

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_checkpoint_state(done_files, current_file, offset, total_bytes):
    data = {"done": list(done_files), "current": current_file, "offset": offset, "total_bytes": total_bytes, "timestamp": time.time()}
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"Не удалось сохранить чекпоинт: {e}")

def clear_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            os.remove(CHECKPOINT_FILE)
        except Exception:
            pass

# ---- Чекпоинты для чанков (возобновление после краша) ----

PROGRESS_FILE = os.path.join(BASE_DIR, "_progress.json")

def load_progress_state():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"files": {}, "processed_bytes": 0, "found": 0}

def save_progress_state(state):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass

def update_progress_chunk(state, file_path, chunk_start, chunk_end, chunk_bytes, chunk_found):
    fname = os.path.abspath(file_path)
    if fname not in state["files"]:
        state["files"][fname] = {"chunks_done": [], "size": 0}
    finfo = state["files"][fname]
    finfo["size"] = max(finfo["size"], chunk_end)
    finfo["chunks_done"].append([chunk_start, chunk_end])
    state["processed_bytes"] += chunk_bytes
    state["found"] += chunk_found
    save_progress_state(state)

def get_undone_chunks(file_path, chunk_size, size, state):
    fname = os.path.abspath(file_path)
    finfo = state.get("files", {}).get(fname)
    if not finfo:
        return list(range(0, size, chunk_size))  # all chunks
    done = set()
    for s, e in finfo.get("chunks_done", []):
        done.add(s)
    undone = []
    for start in range(0, size, chunk_size):
        if start not in done:
            undone.append(start)
    return undone

def clear_progress_state():
    if os.path.exists(PROGRESS_FILE):
        try:
            os.remove(PROGRESS_FILE)
        except Exception:
            pass




_format_cache = {}
def detect_format(file_path, num_lines=30):
    if file_path in _format_cache:
        return _format_cache[file_path]
    with open(file_path, "rb") as f:
        header = f.read(3)
        if header == b'\xef\xbb\xbf':
            pass
        else:
            f.seek(0)
        lines = []
        for _ in range(num_lines):
            line = f.readline().strip()
            if line:
                lines.append(line)
    if not lines:
        result = (b':', "default")
    else:
        delims = [b';', b'|', b'\t', b':']
        delim_scores = {d: 0 for d in delims}
        has_proto = 0
        for line in lines:
            if b'://' in line:
                has_proto += 1
            for delim in delims:
                parts = line.split(delim)
                if len(parts) >= 2:
                    delim_scores[delim] += 1
        best_delim = max(delims, key=lambda d: delim_scores[d])
        if delim_scores[best_delim] == 0:
            best_delim = b':'
        mode = "url" if has_proto >= len(lines) // 2 else "default"
        result = (best_delim, mode)
    _format_cache[file_path] = result
    return result


ALT_DELIMS = [b';', b'|', b'\t', b':']

def parse_line_bytes(line, mode, delim=b':'):
    if not line:
        return None
    if mode == "exact":
        parts = line.split(delim)
        if len(parts) != 2:
            return None
        login, password = parts
        if not login or not password:
            return None
        return login + b':' + password
    delims = [delim] + [d for d in ALT_DELIMS if d != delim]
    for d in delims:
        parts = line.split(d)
        if len(parts) >= 2:
            login, password = parts[-2], parts[-1]
            if login and password:
                if b'/' in login:
                    login = login.rsplit(b'/', 1)[-1]
                    if not login:
                        login = parts[-2]
                return login + b':' + password
    return None

def normalize_query_for_domain(query):
    q = query.lower().strip()
    q = re.sub(r'^https?://', '', q)
    q = re.sub(r'^www\.', '', q)
    q = q.split('/')[0]
    return q

def build_automaton(queries):
    if not AHOCORASICK_AVAILABLE or not queries:
        return None
    A = ahocorasick.Automaton()
    for idx, q in enumerate(queries):
        A.add_word(q.lower(), (idx, q))
    A.make_automaton()
    return A

def _detect_disk_type(file_path):
    """Определяет тип диска: 'ssd', 'hdd' или None. Fallback: benchmark-чтение 20 МБ."""
    try:
        abspath = os.path.abspath(file_path)
        drive_letter = os.path.splitdrive(abspath)[0].strip(':')
        if not drive_letter:
            return None
        # PowerShell: MediaType через Get-Partition → Get-Disk (+ Get-PhysicalDisk fallback)
        ps_script = f'''
$disk = Get-Partition -DriveLetter {drive_letter} -ErrorAction SilentlyContinue | Get-Disk -ErrorAction SilentlyContinue
if ($disk) {{
    $mt = $disk.MediaType
    if (-not $mt) {{
        $pd = Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object {{ $_.DeviceId -eq $disk.Number }}
        if ($pd) {{ $mt = $pd.MediaType }}
    }}
    if ($mt) {{ Write-Output $mt }}
}}
'''
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_script],
            capture_output=True, text=True, timeout=15)
        out = r.stdout.strip().lower()
        if out in ('ssd', 'nvme', 'unspecified'): return 'ssd'
        if out == 'hdd': return 'hdd'
        if out: return 'ssd'
    except Exception:
        pass
    # Fallback: benchmark — читаем 20 МБ, замеряем скорость
    try:
        size = min(os.path.getsize(file_path), 20 * 1024 * 1024)
        if size < 4096:
            return None
        t0 = time.perf_counter()
        with open(file_path, 'rb', buffering=size) as f:
            f.read(size)
        elapsed = time.perf_counter() - t0
        mbps = (size / (1024*1024)) / elapsed if elapsed > 0 else 0
        return 'ssd' if mbps > 50 else ('hdd' if mbps > 0 else None)
    except Exception:
        return None

def pool_worker(file_path, queries, flags, mode, delim, filters, temp_dir,
                chunk_queue, progress_value, found_value, stop_event, overlap=1, regex_mode=False,
                blacklist=None, export_delim=b':', default_save_full=False):
    """Обёртка: забирает чанки из очереди, вызывает worker_process.
    Автомат строится ОДИН раз на воркер, а не на каждый чанк.
    Выход по sentinel (None)."""
    # build automaton ONCE for this worker
    automaton = None
    patterns = {}
    if not regex_mode and AHOCORASICK_AVAILABLE:
        automaton = build_automaton(queries)
    elif regex_mode:
        for q in queries:
            try:
                patterns[q] = re.compile(q.encode(), re.IGNORECASE)
            except Exception:
                pass
    while True:
        chunk = chunk_queue.get()
        if chunk is None:
            break
        start, end = chunk
        worker_process(file_path, start, end, queries, flags, mode, delim, filters,
                      temp_dir, progress_value, found_value, stop_event, overlap, regex_mode,
                      blacklist, export_delim, default_save_full,
                      automaton=automaton, patterns=patterns)

def file_worker(file_queue, queries, flags, mode, delim, filters, temp_dir,
                progress_value, found_value, stop_event, overlap, regex_mode,
                blacklist, export_delim, default_save_full, perf_mode,
                completed_queue=None, dry_run=False):
    """Worker: pull files from queue, process each entirely. Build automaton once.
    Writes all results to ONE consolidated temp file _{pid}.tmp with query markers."""
    _worker_start_ts = time.time()
    logger = logging.getLogger("URLChecker")
    logger.info(f"WORKER старт: proc={mp.current_process().name} pid={os.getpid()} thread={threading.current_thread().name}")
    automaton = None
    patterns = {}
    if not regex_mode and AHOCORASICK_AVAILABLE:
        automaton = build_automaton(queries)
    elif regex_mode:
        for q in queries:
            try:
                patterns[q] = re.compile(q.encode(), re.IGNORECASE)
            except Exception:
                pass
    # один выходной файл на весь воркер
    out_path = os.path.join(temp_dir, f"_{os.getpid()}.tmp")
    with open(out_path, "ab", buffering=4*1024*1024) as out_file:
        while True:
            try:
                item = file_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                break
            if stop_event.value:
                break
            if isinstance(item, tuple):
                file_path, file_delim, file_mode = item
            else:
                file_path, file_delim, file_mode = item, delim, mode
            size = os.path.getsize(file_path)
            stat = None
            if size > 0:
                stat = worker_process(file_path, 0, size, queries, flags, file_mode, file_delim, filters,
                                     temp_dir, progress_value, found_value, stop_event, overlap, regex_mode,
                                     blacklist, export_delim, default_save_full,
                                     automaton=automaton, patterns=patterns,
                                     out_file=out_file, dry_run=dry_run)
            if completed_queue is not None:
                if stat is not None:
                    completed_queue.put((file_path, stat[1], size))
                else:
                    completed_queue.put((file_path, 0, size))
    logger.info(f"WORKER финиш: proc={mp.current_process().name} pid={os.getpid()} time={time.time()-_worker_start_ts:.1f}s")

def worker_process(file_path, start, end, queries, flags, mode, delim, filters, temp_dir, progress_value, found_value, stop_event, overlap=1, regex_mode=False, blacklist=None, export_delim=b':', default_save_full=False, automaton=None, patterns=None, out_file=None, dry_run=False):
    """Returns (bytes_processed, total_found) or None if skipped."""
    logger = logging.getLogger("URLChecker")
    out_files = {}
    try:
        file_size = os.path.getsize(file_path)
        bytes_processed = 0
        local_found = 0
        total_file_found = 0
        _lock_time = 0
        _compute_time = 0
        _last_t = time.perf_counter_ns()
        if file_size == 0:
            return None

        read_start = max(0, start - overlap)
        read_end = min(file_size, end + overlap)
        if read_end - read_start > MAX_CHUNK_SIZE:
            read_end = read_start + MAX_CHUNK_SIZE

        # automaton/patterns переданы из pool_worker — не перестраиваем
        if out_file is None:
            for q in queries:
                safe_q = safe_filename(q)
                of = os.path.join(temp_dir, f"{safe_q}_{os.getpid()}.tmp")
                out_files[q] = open(of, "ab", buffering=4*1024*1024)

        case_sensitive = filters.get('case_sensitive', False)
        exclude_empty = filters.get('exclude_empty', True)
        require_email = filters.get('require_email', False)

        if dry_run:
            logger.info(f"DRY_RUN pid={os.getpid()} file={os.path.basename(file_path)} buf=4MB skip_write=True")
        elif time.time() - getattr(worker_process, '_buf_log_ts', 0) > 10:
            worker_process._buf_log_ts = time.time()
            logger.info(f"BUF pid={os.getpid()} file={os.path.basename(file_path)} buf=4MB")
        with open(file_path, "rb", buffering=4*1024*1024) as f:
            f.seek(read_start)
            if read_start == 0:
                header = f.read(3)
                if header == b'\xef\xbb\xbf':
                    read_start = 3
                else:
                    f.seek(0)
            else:
                f.seek(read_start)
                f.readline()  # skip partial first line

            BLOCK_SIZE = 16 * 1024 * 1024  # 16 MB — насыщает SSD
            tail = b''
            while f.tell() < read_end and not stop_event.value:
                raw = f.read(BLOCK_SIZE)
                if not raw:
                    break

                chunk = tail + raw
                last_nl = chunk.rfind(b'\n')
                if last_nl < 0:
                    # весь кусок — оборванная строка (ненормально для 16МБ, но бывает)
                    tail = chunk
                    continue

                tail = chunk[last_nl + 1:]
                block_data = chunk[:last_nl]

                # ---- Rust process_block ----
                try:
                    pb_results = rust_scan.process_block(
                        block_data,
                        [q.encode() for q in queries],
                        {q: flags.get(q, default_save_full) for q in queries},
                        mode, delim, export_delim,
                        default_save_full, exclude_empty, require_email,
                        case_sensitive, regex_mode, blacklist,
                    )
                    for q_name, line_bytes in pb_results:
                        if not dry_run:
                            if out_file is not None:
                                out_file.write(line_bytes)
                            else:
                                out_files[q_name].write(line_bytes)
                    total_file_found += len(pb_results)
                    local_found += len(pb_results)
                    if local_found >= 10000:
                        t0 = time.perf_counter_ns()
                        with found_value.get_lock():
                            found_value.value += local_found
                        _lock_time += time.perf_counter_ns() - t0
                        local_found = 0
                except Exception as e:
                    logger.error(f"process_block error: {e}")
                bytes_processed += len(block_data)
            # Process remaining tail data (CRITICAL: was lost before!)
            if tail.strip() and not stop_event.value:
                try:
                    pb_results = rust_scan.process_block(
                        tail,
                        [q.encode() for q in queries],
                        {q: flags.get(q, default_save_full) for q in queries},
                        mode, delim, export_delim,
                        default_save_full, exclude_empty, require_email,
                        case_sensitive, regex_mode, blacklist,
                    )
                    for q_name, line_bytes in pb_results:
                        if not dry_run:
                            if out_file is not None:
                                out_file.write(line_bytes)
                            else:
                                out_files[q_name].write(line_bytes)
                    total_file_found += len(pb_results)
                    local_found += len(pb_results)
                    if local_found >= 10000:
                        t0 = time.perf_counter_ns()
                        with found_value.get_lock():
                            found_value.value += local_found
                        _lock_time += time.perf_counter_ns() - t0
                        local_found = 0
                except Exception as e:
                    logger.error(f"process_block tail error: {e}")
                bytes_processed += len(tail)

        # flush remaining found count
        if local_found > 0:
            t0 = time.perf_counter_ns()
            with found_value.get_lock():
                found_value.value += local_found
            _lock_time += time.perf_counter_ns() - t0

    except Exception as e:
        logger.error(f"Worker ошибка для {file_path}[{start}:{end}]: {e}", exc_info=True)
    finally:
        if out_file is None:
            for f in out_files.values():
                try:
                    f.close()
                except Exception:
                    pass
        t0 = time.perf_counter_ns()
        with progress_value.get_lock():
            progress_value.value += bytes_processed
        _lock_time += time.perf_counter_ns() - t0
        _compute_time = time.perf_counter_ns() - _last_t - _lock_time
        logger.info(f"LOCK_STAT pid={os.getpid()} file={os.path.basename(file_path)} "
                    f"lock_time={_lock_time/1e6:.1f}ms compute+io={_compute_time/1e6:.1f}ms "
                    f"pct_lock={_lock_time/(_lock_time+_compute_time)*100:.1f}%")
        return bytes_processed, total_file_found

def parallel_process_file(file_path, queries, flags, mode, delim, filters, temp_dir, num_workers=None, overlap=1, regex_mode=False, blacklist=None, export_delim=b':', default_save_full=False, perf_mode='auto'):
    size = os.path.getsize(file_path)
    if size == 0:
        return {q: [] for q in queries}, 0, 0
    if num_workers is None:
        num_workers = max(1, mp.cpu_count())
    # chunk от 1 МБ до MAX_CHUNK_SIZE
    chunk_size = max(1*1024*1024, (size + num_workers - 1) // num_workers)
    chunk_size = min(chunk_size, MAX_CHUNK_SIZE)
    total_chunks = max(1, (size + chunk_size - 1) // chunk_size)
    # определяем макс воркеров (кап 4 на файл — SSD не любит параллельные seek внутри одного файла)
    if perf_mode == 'hdd':
        max_workers = min(total_chunks, 2)
    elif perf_mode == 'ssd':
        max_workers = min(total_chunks, 4)
    else:  # auto
        disk_type = _detect_disk_type(file_path)
        if disk_type == 'ssd':
            max_workers = min(total_chunks, 4)
        elif disk_type == 'hdd':
            max_workers = min(total_chunks, 2)
        else:
            max_workers = min(total_chunks, 4)
    progress_value = Value('q', 0)
    found_value = Value('q', 0)
    stop_event = Value('b', False)
    # очередь чанков + sentinel-ы
    chunk_queue = mp.Queue()
    for i in range(total_chunks):
        start = i * chunk_size
        end = (i+1) * chunk_size if i < total_chunks-1 else size
        chunk_queue.put((start, end))
    for _ in range(max_workers):
        chunk_queue.put(None)
    processes = []
    for _ in range(max_workers):
        p = Process(target=pool_worker, args=(file_path, queries, flags, mode, delim, filters, temp_dir, chunk_queue, progress_value, found_value, stop_event, overlap, regex_mode, blacklist, export_delim, default_save_full))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
    result_files = {q: [] for q in queries}
    for p in processes:
        pid = p.pid
        for q in queries:
            safe_q = safe_filename(q)
            tmp_file = os.path.join(temp_dir, f"{safe_q}_{pid}.tmp")
            if os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 0:
                result_files[q].append(tmp_file)
    return result_files, progress_value.value, found_value.value

def merge_dedup_files(input_files, output_file, unique_hashes=None, stop_flag=None):
    """Однопроходное слияние temp-файлов в финальный. Внутренний дедуп — set[bytes].
    Возвращает (total_unique, cross_worker_skipped, db_skipped, new_hashes_set)."""
    if not input_files:
        return 0, 0, 0, set()
    seen = set()
    total = 0
    cross_skip = 0
    db_skip = 0
    new_hashes = set()
    with open(output_file, 'wb') as out:
        for fname in input_files:
            if stop_flag is not None and stop_flag.is_set():
                break
            if not os.path.exists(fname) or os.path.getsize(fname) == 0:
                continue
            with open(fname, 'rb') as f:
                for line in f:
                    if stop_flag is not None and stop_flag.is_set():
                        break
                    line_stripped = line.rstrip(b'\r\n')
                    if not line_stripped:
                        continue
                    null_pos = line_stripped.find(b'\x00')
                    content = line_stripped[null_pos + 1:] if null_pos >= 0 else line_stripped
                    if content in seen:
                        cross_skip += 1
                        continue
                    if unique_hashes is not None:
                        h = hashlib.md5(content).digest()[:_HASH_BYTES]
                        if h in unique_hashes:
                            db_skip += 1
                            continue
                        new_hashes.add(h)
                    seen.add(content)
                    out.write(content + b'\n')
                    total += 1
    for fname in input_files:
        try:
            os.remove(fname)
        except Exception:
            pass
    return total, cross_skip, db_skip, new_hashes

def parallel_merge(temp_dir, queries, orig_to_safe, out_dir_date, unique_hashes=None, export_delim=b':', ui_queue=None, total_scan_found=0, stop_flag=None):
    """Параллельный merge: разбивает запросы на cpu_count() батчей,
    каждый батч дедупит и пишет свои .txt в отдельном процессе.
    stop_flag — threading.Event для отмены из GUI."""
    import math, logging
    logger = logging.getLogger("URLChecker")
    worker_files = []
    for fname in os.listdir(temp_dir):
        if fname.startswith('_') and fname.endswith('.tmp'):
            fpath = os.path.join(temp_dir, fname)
            if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                worker_files.append(fpath)
    if not worker_files:
        return 0, 0, set()

    n_procs = max(1, mp.cpu_count())
    batch_size = max(1, (len(queries) + n_procs - 1) // n_procs)
    batches = [queries[i:i+batch_size] for i in range(0, len(queries), batch_size)]
    total_batches = len(batches)

    if total_batches == 1:
        tf, td, nh = _merge_batch(worker_files, out_dir_date, unique_hashes, export_delim,
                                  orig_to_safe, batches[0])
        if ui_queue:
            ui_queue.put(("status", "[+] Дедупликация: 100%"))
        return tf, td, nh

    # Multi-batch: Manager для прогресса и стоп-флага (picklable между процессами)
    with mp.Manager() as manager:
        stop_event = manager.Value('b', False)
        progress_value = manager.Value('q', 0)
        total_merged = 0
        last_progress_time = time.time()

        with mp.Pool(processes=total_batches) as pool:
            args_list = [(worker_files, out_dir_date, unique_hashes, export_delim,
                          {q: orig_to_safe[q] for q in batch}, batch, progress_value, stop_event)
                         for batch in batches]
            result_async = pool.starmap_async(_merge_batch_prog, args_list)

            while not result_async.ready():
                # Остановка по требованию пользователя
                if stop_flag is not None and stop_flag.is_set():
                    stop_event.value = True

                # Обновление прогресса
                cur_prog = progress_value.value
                if cur_prog != total_merged and ui_queue:
                    total_merged = cur_prog
                    if total_scan_found > 0:
                        pct = int(min(100, total_merged * 100 / total_scan_found))
                        ui_queue.put(("status", f"MERGE: {total_merged/1e6:.1f}M / {total_scan_found/1e6:.1f}M строк ({pct}%)"))
                        ui_queue.put(("progress", pct))
                    last_progress_time = time.time()

                # Hang-detection: 120 секунд без прогресса — terminate
                if total_scan_found > 0 and time.time() - last_progress_time > 120:
                    if progress_value.value == total_merged:
                        logger.warning("MERGE hang detected — terminating pool")
                        pool.terminate()
                        pool.join()
                        break
                    last_progress_time = time.time()

                time.sleep(0.5)

            # Забираем результаты с таймаутом (если pool не terminat-нут)
            try:
                results = result_async.get(timeout=30)
            except Exception:
                logger.warning("MERGE result_async.get() failed — using partial results")
                results = []

    total_found = sum(r[0] for r in results) if results else 0
    total_dup = sum(r[1] for r in results) if results else 0
    new_hashes = set()
    if results:
        for _, _, nh in results:
            new_hashes.update(nh)

    for fpath in worker_files:
        try: os.remove(fpath)
        except Exception: pass
    if ui_queue:
        ui_queue.put(("status", f"[+] Дедупликация готова: +{total_found} новых строк"))
    return total_found, total_dup, new_hashes


def _merge_batch(worker_files, out_dir_date, unique_hashes, export_delim, orig_to_safe_slice, queries_batch):
    """Обработка одного батча запросов (однопоточный, без прогресса)."""
    return _merge_batch_prog(worker_files, out_dir_date, unique_hashes, export_delim,
                            orig_to_safe_slice, queries_batch, None, None)


def _merge_batch_prog(worker_files, out_dir_date, unique_hashes, export_delim,
                      orig_to_safe_slice, queries_batch, progress_value=None, stop_event=None):
    """Однопроходное слияние: один проход по worker_files, диспетчеризация по словарю.
    Возвращает (total_found, total_dup, new_hashes)."""
    qmap = {}
    for q in queries_batch:
        safe = orig_to_safe_slice[q]
        final_path = os.path.join(out_dir_date, f"{safe}.txt")
        qmap[q.encode()] = {
            'out': open(final_path, 'ab', buffering=4*1024*1024),
            'seen': set(),
            'found': 0,
            'dup': 0,
            'new_hashes': set(),
        }

    acc = 0

    for fpath in worker_files:
        if stop_event is not None and stop_event.value:
            break
        try:
            with open(fpath, 'rb', buffering=8*1024*1024) as f:
                for line in f:
                    line_stripped = line.rstrip(b'\r\n')
                    if not line_stripped:
                        continue
                    parts = line_stripped.split(b'\x00', 1)
                    if len(parts) != 2:
                        continue
                    info = qmap.get(parts[0])
                    if info is None:
                        continue
                    content = parts[1]
                    h = hashlib.md5(content).digest()[:_HASH_BYTES]
                    if h in info['seen']:
                        info['dup'] += 1
                        continue
                    if unique_hashes is not None:
                        if h in unique_hashes:
                            info['dup'] += 1
                            continue
                        info['new_hashes'].add(h)
                    info['seen'].add(h)
                    info['out'].write(content + b'\n')
                    info['found'] += 1
                    acc += 1
                    if acc >= 10000:
                        if stop_event is not None and stop_event.value:
                            break
                        if progress_value is not None:
                            try:
                                progress_value.value = progress_value.value + acc
                            except Exception:
                                pass
                        acc = 0
        except Exception:
            pass

    # flush remaining progress before early exit or normal finish
    if progress_value is not None and acc:
        try:
            progress_value.value = progress_value.value + acc
        except Exception:
            pass

    for info in qmap.values():
        info['out'].close()

    total_found = sum(v['found'] for v in qmap.values())
    total_dup = sum(v['dup'] for v in qmap.values())
    new_hashes = set()
    for v in qmap.values():
        new_hashes.update(v['new_hashes'])

    return total_found, total_dup, new_hashes

def generate_report(out_dir, queries, orig_to_safe, total_found, total_duplicates, total_unique_db, elapsed, avg_speed, top_domains):
    # Считаем строки в каждом файле один раз
    import html as _html
    line_counts = {}
    for q in queries:
        safe = orig_to_safe[q]
        fpath = os.path.join(out_dir, f"{safe}.txt")
        if os.path.exists(fpath):
            with open(fpath, 'rb') as f:
                line_counts[q] = sum(1 for _ in f)
        else:
            line_counts[q] = 0

    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as rep:
        rep.write(f"Отчёт от {datetime.now()}\n")
        rep.write(f"Новых уникальных строк: {total_found}\n")
        rep.write(f"Уже существовало: {total_duplicates}\n")
        rep.write(f"Всего в базе уникальных строк: {total_unique_db}\n")
        rep.write(f"Время: {fmt_time(elapsed)}\n")
        rep.write(f"Ср. скорость: {avg_speed:.0f} МБ/с\n\n")
        for q in queries:
            rep.write(f"Запрос '{q}': {line_counts[q]} новых строк\n")
        if top_domains:
            rep.write("\nТОП ДОМЕНОВ:\n")
            for domain, count in top_domains.most_common(20):
                rep.write(f"  {domain}: {count}\n")
    html_date = datetime.now()
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>URLmonster Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>body{{font-family:'Segoe UI',sans-serif;background:#0a0a0a;color:#00cc00;padding:20px;}}table{{border-collapse:collapse;width:100%;}}th,td{{border:1px solid #00cc00;padding:8px;text-align:left;}}th{{background:#1a1a1a;}}</style>
</head><body>
<h1>URLmonster Report</h1>
<p>Date: {html_date}</p>
<p>New unique lines: {total_found}</p>
<p>Already existed: {total_duplicates}</p>
<p>Total unique strings in DB: {total_unique_db}</p>
<p>Time: {fmt_time(elapsed)}</p>
<p>Avg speed: {avg_speed:.0f} MB/s</p>
<h2>Results per query</h2><table><tr><th>Query</th><th>New lines</th></tr>
""")
        for q in queries:
            f.write(f"<tr><td>{_html.escape(q)}</td><td>{line_counts[q]}</td></tr>\n")
        f.write("</table>")
        if top_domains:
            f.write("<h2>Top Domains</h2><table><tr><th>Domain</th><th>Count</th></tr>")
            for domain, count in top_domains.most_common(20):
                f.write(f"<tr><td>{_html.escape(domain)}</td><td>{count}</td></tr>")
            f.write("</table>")
            labels = [d for d, _ in top_domains.most_common(10)]
            values = [c for _, c in top_domains.most_common(10)]
            f.write(f'<canvas id="domainsChart" width="400" height="200"></canvas><script>const ctx=document.getElementById("domainsChart").getContext("2d");new Chart(ctx,{{type:"bar",data:{{labels:{json.dumps(labels)},datasets:[{{label:"Domain count",data:{json.dumps(values)},backgroundColor:"#00cc00",borderColor:"#00cc00",borderWidth:1}}]}}}});</script>')
        f.write("</body></html>")
    data = {"timestamp": str(datetime.now()), "new_unique": total_found, "duplicates": total_duplicates, "total_unique_db": total_unique_db, "elapsed": elapsed, "avg_speed_mb": avg_speed, "queries": line_counts, "top_domains": dict(top_domains.most_common(20))}
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as jf:
        json.dump(data, jf, indent=2, ensure_ascii=False)

def split_file(file_path, lines_per_file):
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return
    total = 0
    with open(file_path, 'rb') as f:
        for _ in f:
            total += 1
    if total <= lines_per_file:
        return
    base, ext = os.path.splitext(file_path)
    parts = []
    try:
        with open(file_path, 'rb') as f:
            part_idx = 1
            part = open(f"{base}_part{str(part_idx).zfill(3)}{ext}", 'wb')
            parts.append(part)
            written = 0
            for line in f:
                if written >= lines_per_file:
                    part.close()
                    part_idx += 1
                    part = open(f"{base}_part{str(part_idx).zfill(3)}{ext}", 'wb')
                    parts.append(part)
                    written = 0
                part.write(line)
                written += 1
    finally:
        for p in parts:
            try:
                p.close()
            except Exception:
                pass
    # Все части записаны успешно — удаляем оригинал
    os.remove(file_path)

def run_check(src, queries_data, out_dir, mode, filters, use_multiprocess, use_resume, ui_queue, stop_flag, regex_mode=False, blacklist=None, split_size=0, export_delim=b':', theme='dark', default_save_full=False, use_unique_db=True, perf_mode='auto', dry_run=False):
    date_folder = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir_date = os.path.join(out_dir, date_folder)
    os.makedirs(out_dir_date, exist_ok=True)
    logger = setup_logger(os.path.join(out_dir_date, "logs"))
    _format_cache.clear()
    queries = []
    flags = {}
    for q, flag in queries_data:
        q = q.strip()
        if q:
            queries.append(q)
            if flag is None:
                flags[q] = default_save_full
            else:
                flags[q] = flag
    if blacklist:
        blacklist = [b.strip() for b in blacklist if b.strip()]
    temp_dirs = []
    try:
        if not queries:
            ui_queue.put(("status", "[!] Нет запросов!"))
            ui_queue.put(("done", None))
            return
        all_files, temp_dirs = collect_files(src)
        if not all_files:
            ui_queue.put(("status", "[!] База не найдена!"))
            ui_queue.put(("done", None))
            for td in temp_dirs:
                try: shutil.rmtree(td, ignore_errors=True)
                except Exception: pass
            return
        done_files = set()
        current_file = None
        cp = None
        if use_resume:
            progress_state = load_progress_state()
            cp = load_checkpoint()
            if cp:
                done_files = set(cp.get("done", []))
                current_file = cp.get("current")
                ui_queue.put(("status", f"[+] Возобновление с {current_file}"))
            if progress_state.get("processed_bytes", 0) > 0:
                ui_queue.put(("status", f"[+] Восстановлено {progress_state['processed_bytes']//(1024*1024)} МБ из чекпоинта"))
        else:
            clear_progress_state()
            progress_state = {}
            state = {}
        if use_resume:
            state = load_processed_state()
            if cp:
                files_to_process = [f for f in all_files if f not in done_files]
                if current_file and current_file not in done_files:
                    if current_file not in files_to_process:
                        files_to_process.append(current_file)
                files_to_process = [f for f in all_files if f in files_to_process]
            else:
                files_to_process = get_new_files(all_files, state)
        else:
            files_to_process = all_files
            state = {}
        if not files_to_process:
            ui_queue.put(("status", "[✓] Все файлы уже обработаны"))
            ui_queue.put(("done", None))
            return
        total_files = len(files_to_process)
        total_size = sum(os.path.getsize(f) for f in files_to_process if os.path.exists(f))
        total_work = total_size
        processed_bytes = progress_state.get("processed_bytes", 0) if progress_state else 0
        found_total = progress_state.get("found", 0) if progress_state else 0
        ui_queue.put(("status", f"[+] Всего файлов: {total_files}, общий размер: {total_size//(1024*1024)} МБ"))
        if regex_mode:
            engine = "regex"
        elif AHOCORASICK_AVAILABLE:
            engine = "aho-corasick"
        else:
            engine = "substring (цикл)"
        logger.info(f"Движок матчинга: {engine} | запросов: {len(queries)} | regex_mode={regex_mode} | ahocorasick={AHOCORASICK_AVAILABLE}")
        ui_queue.put(("status", f"[+] Движок матчинга: {engine}"))
        processed_files = 0
        start_time = time.time()
        last_update = start_time
        last_checkpoint_save = start_time
        _, orig_to_safe = build_filename_map(queries)
        temp_dir = tempfile.mkdtemp(prefix="urlmonster_")
        all_temp_files = {q: [] for q in queries}
        top_domains_counter = Counter()
        # ---- Файл-уровневый параллелизм (файл = задача, не чанки) ----
        if use_multiprocess and total_files >= 1:
            # Фильтруем уже обработанные (resume) и пред-детектим формат
            filtered_files = []
            file_items = []
            for f in files_to_process:
                if use_resume and f in done_files:
                    continue
                filtered_files.append(f)
                if mode == "auto":
                    d, m = detect_format(f)
                else:
                    d, m = b':', mode
                delim_name = {b':': ':', b';': ';', b'|': '|', b'\t': 'tab'}.get(d, d.decode(errors='replace'))
                logger.info(f"detect_format: {os.path.basename(f)} -> delim={delim_name} mode={m}")
                file_items.append((f, d, m))
            if not file_items:
                ui_queue.put(("status", "[✓] Все файлы уже обработаны"))
                ui_queue.put(("done", None))
                return
            total_files = len(file_items)
            # Файловый пул — кап по I/O, не по CPU
            disk_type_s = '--'
            if perf_mode == 'hdd':
                max_workers = min(total_files, 2)
                disk_type_s = 'hdd'
            elif perf_mode == 'ssd':
                max_workers = min(total_files, max(1, min(4, mp.cpu_count() * 2)))
                disk_type_s = 'ssd'
            else:  # auto
                disk_type = _detect_disk_type(filtered_files[0])
                disk_type_s = disk_type or 'unknown'
                if disk_type == 'hdd':
                    max_workers = min(total_files, 2)
                elif disk_type == 'ssd':
                    max_workers = min(total_files, max(1, min(4, mp.cpu_count() * 2)))
                else:
                    max_workers = min(total_files, max(1, min(4, mp.cpu_count())))
            logger.info(f"Запущено {max_workers} воркеров на {total_files} файлов | perf_mode={perf_mode} disk={disk_type_s}")
            # Все файлы — через файловый пул (каждый воркер читает весь файл последовательно)
            file_queue = mp.Queue()
            for item in file_items:
                file_queue.put(item)
            for _ in range(max_workers):
                file_queue.put(None)
            progress_value = Value('q', 0)
            found_value = Value('q', 0)
            stop_event = Value('b', False)
            completed_queue = mp.Queue()
            processes = []
            for _ in range(max_workers):
                p = Process(target=file_worker, args=(
                    file_queue, queries, flags, mode, b':', filters, temp_dir,
                    progress_value, found_value, stop_event, 1, regex_mode,
                    blacklist, export_delim, default_save_full, perf_mode,
                    completed_queue, dry_run))
                p.start()
                processes.append(p)
            # Мониторинг прогресса
            last_update = time.time()
            last_checkpoint_save = time.time()
            last_sys_log = time.time()
            disk_snapshot = None
            if PSUTIL_AVAILABLE:
                disk_snapshot = psutil.disk_io_counters()
            while any(p.is_alive() for p in processes):
                if stop_flag.is_set():
                    stop_event.value = True
                # Собираем завершённые файлы
                while not completed_queue.empty():
                    try:
                        item = completed_queue.get_nowait()
                        fname = item[0] if isinstance(item, tuple) else item
                        done_files.add(fname)
                        # Per-file stats в лог
                        if isinstance(item, tuple) and ui_queue:
                            fpath, ffound, fsize = item
                            basename = os.path.basename(fpath)
                            ui_queue.put(("status", f"  [{basename}] found: {ffound}, size: {fsize/1024/1024:.1f} MB, match: {ffound*100/max(1, fsize):.1f}%"))
                    except queue.Empty:
                        break
                time.sleep(0.25)
                now = time.time()
                if now - last_update >= 1.0:
                    last_update = now
                    elapsed = now - start_time
                    cur_proc = progress_value.value
                    total_so_far = processed_bytes + cur_proc  # checkpoint + new
                    cur_found = found_value.value
                    alive = sum(1 for p in processes if p.is_alive())
                    done_cnt = max_workers - alive
                    pct = (total_so_far / total_work) * 100 if total_work > 0 else 0
                    speed_mb = (total_so_far / (1024*1024)) / elapsed if elapsed > 0 else 0
                    speed_lines = cur_found / elapsed if elapsed > 0 else 0
                    left = (total_work - total_so_far) / (total_so_far / elapsed) if elapsed > 0 and total_so_far > 0 else 0
                    left_str = fmt_time(left) if left > 0 else "расчёт..."
                    files_left = total_files - done_cnt
                    ui_queue.put(("status", f"[+] {pct:.1f}% | файл {done_cnt}/{total_files} | осталось {files_left} | {speed_mb:.0f} МБ/с | {speed_lines:,.0f} строк/с | найдено {cur_found} | ~{left_str}"))
                    ui_queue.put(("progress", pct))
                    ui_queue.put(("stats", {"pct": pct, "speed_mb": speed_mb, "speed_lines": speed_lines, "eta": left_str, "processed_gb": total_so_far/(1024**3), "total_gb": total_work/(1024**3), "files_done": done_cnt, "files_total": total_files, "found": cur_found, "elapsed": fmt_time(elapsed)}))
                if now - last_sys_log >= 5 and PSUTIL_AVAILABLE and disk_snapshot is not None:
                    last_sys_log = now
                    new_disk = psutil.disk_io_counters()
                    dt = 5.0
                    read_mb_s = (new_disk.read_bytes - disk_snapshot.read_bytes) / (1024*1024) / dt
                    write_mb_s = (new_disk.write_bytes - disk_snapshot.write_bytes) / (1024*1024) / dt
                    disk_snapshot = new_disk
                    cpu = psutil.cpu_percent()
                    ram = psutil.virtual_memory().percent
                    logger.info(f"SYS: CPU={cpu}% RAM={ram}% DISK_R={read_mb_s:.0f} DISK_W={write_mb_s:.0f} МБ/с")
                if progress_state and now - last_checkpoint_save >= 10:
                    last_checkpoint_save = now
                    cur_proc = progress_value.value
                    cur_found = found_value.value
                    progress_state["processed_bytes"] = processed_bytes + cur_proc
                    progress_state["found"] = found_total + cur_found
                    save_progress_state(progress_state)
            for p in processes:
                p.join()
            # Собираем остаток из очереди после остановки
            if stop_flag.is_set():
                while not completed_queue.empty():
                    try:
                        done_files.add(completed_queue.get_nowait())
                    except queue.Empty:
                        break
            logger.info(f"Фаза ЧТЕНИЕ: все воркеры завершились, начинаем MERGE (однопоточный)")
            processed_bytes += progress_value.value  # checkpoint + new
            found_total += found_value.value
            processed_files = total_files
            # Всегда делаем consolidated merge (даже при остановке — частичные результаты)
            merge_start = time.time()
            ui_queue.put(("status", "[+] Дедупликация..."))
            ui_queue.put(("progress", 0))
            logger.info(f"Фаза MERGE: старт parallel_merge | запросов: {len(queries)} | воркеров: {mp.cpu_count()}")
            unique_hashes = load_unique_db() if use_unique_db else None
            total_found, total_duplicates, new_hashes = parallel_merge(
                temp_dir, queries, orig_to_safe, out_dir_date,
                unique_hashes if use_unique_db else None, export_delim, ui_queue,
                total_scan_found=found_total, stop_flag=stop_flag)
            merge_time = time.time() - merge_start
            logger.info(f"Фаза MERGE: завершён за {merge_time:.1f}s")
            ui_queue.put(("progress", 0))
            files_to_split = []
            # Domain counting on final files
            for q in queries:
                safe_name = orig_to_safe[q]
                final_path = os.path.join(out_dir_date, f"{safe_name}.txt")
                if not os.path.exists(final_path):
                    continue
                with open(final_path, 'rb') as rf:
                    for line in rf:
                        parts = line.split(export_delim)
                        if len(parts) >= 2:
                            login = parts[0].decode('utf-8', errors='ignore')
                            if '@' in login:
                                domain = login.split('@')[-1]
                                top_domains_counter[domain] += 1
                if split_size > 0 and os.path.exists(final_path):
                    files_to_split.append(final_path)
            if use_unique_db and new_hashes:
                add_unique_strings(new_hashes)
                total_unique_db = len(load_unique_db())
            else:
                total_unique_db = len(unique_hashes) if unique_hashes is not None else 0
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Остаток при остановке
            if stop_flag.is_set():
                ui_queue.put(("status", "[!] Остановлено пользователем — сохраняю обработанное..."))
                if progress_state:
                    progress_state["processed_bytes"] = processed_bytes
                    progress_state["found"] = found_total
                    save_progress_state(progress_state)
                remaining_files = [f for f, _, _ in file_items if f not in done_files]
                if remaining_files:
                    remainder_path = os.path.join(out_dir_date, "_остаток.txt")
                    with open(remainder_path, "w", encoding="utf-8") as rf:
                        for f in remaining_files:
                            try:
                                with open(f, "r", encoding="utf-8", errors="ignore") as inf:
                                    rf.writelines(inf)
                            except Exception:
                                pass
                    ui_queue.put(("status", f"[+] {len(remaining_files)} необработанных файлов ({sum(os.path.getsize(f) for f in remaining_files)//(1024*1024)} МБ) сохранено в {remainder_path}"))
            if split_size > 0:
                for fp in files_to_split:
                    split_file(fp, split_size)
            ui_queue.put(("status", "[+] Генерация отчёта..."))
            elapsed = time.time() - start_time
            avg_speed = (processed_bytes / (1024*1024)) / elapsed if elapsed > 0 else 0
            generate_report(out_dir_date, queries, orig_to_safe, total_found, total_duplicates, total_unique_db, elapsed, avg_speed, top_domains_counter)
            ui_queue.put(("progress", 100))
            if stop_flag.is_set():
                ui_queue.put(("status", f"[!] Прервано. Добавлено {total_found} строк, пропущено {total_duplicates} дублей | время {fmt_time(elapsed)} | ср. {avg_speed:.0f} МБ/с"))
                ui_queue.put(("success", {"found": total_found, "duplicates": total_duplicates, "total_db": total_unique_db, "elapsed": fmt_time(elapsed), "speed": f"{avg_speed:.0f}", "out": out_dir_date, "stopped": True}))
            else:
                ui_queue.put(("status", f"[✓] Готово! Добавлено {total_found} новых строк, пропущено {total_duplicates} дублей | время {fmt_time(elapsed)} | ср. {avg_speed:.0f} МБ/с"))
                ui_queue.put(("success", {"found": total_found, "duplicates": total_duplicates, "total_db": total_unique_db, "elapsed": fmt_time(elapsed), "speed": f"{avg_speed:.0f}", "out": out_dir_date}))
            try:
                import winsound
                winsound.Beep(1000, 500)
            except Exception:
                pass
            if stop_flag.is_set() and progress_state:
                save_progress_state(progress_state)
            else:
                clear_checkpoint()
                clear_progress_state()
            if use_resume:
                for f in files_to_process:
                    try:
                        st = os.stat(f)
                        state[f] = [st.st_size, st.st_mtime]
                    except Exception:
                        pass
                save_processed_state(state)
            return
        else:
            # Последовательная обработка (один файл или однопоточный режим)
            last_sys_log = time.time()
            disk_snapshot = None
            if PSUTIL_AVAILABLE:
                disk_snapshot = psutil.disk_io_counters()
            for idx, file_path in enumerate(files_to_process):
                if stop_flag.is_set():
                    break
                if use_resume and file_path in done_files:
                    continue
                delim, mode_detected = detect_format(file_path)
                if mode == "auto":
                    current_mode = mode_detected
                    current_delim = delim
                else:
                    current_mode = mode
                    current_delim = b':'
                delim_name = {b':': ':', b';': ';', b'|': '|', b'\t': 'tab'}.get(current_delim, current_delim.decode(errors='replace'))
                ui_queue.put(("status", f"[+] {os.path.basename(file_path)} (mode:{current_mode} delim:{delim_name})..."))
                if stop_flag.is_set():
                    break
                temp_files, bytes_proc, found_proc = parallel_process_file(file_path, queries, flags, current_mode, current_delim, filters, temp_dir, num_workers=1, regex_mode=regex_mode, blacklist=blacklist, export_delim=export_delim, default_save_full=default_save_full, perf_mode=perf_mode)
                fsize = os.path.getsize(file_path)
                ui_queue.put(("status", f"  [{os.path.basename(file_path)}] found: {found_proc}, size: {fsize/1024/1024:.1f} MB, match: {found_proc*100/max(1, fsize):.1f}%"))
                for q in queries:
                    all_temp_files[q].extend(temp_files.get(q, []))
                processed_bytes += bytes_proc
                found_total += found_proc
                processed_files += 1
                now = time.time()
                if now - last_update >= 1.0:
                    last_update = now
                    elapsed = now - start_time
                    pct = (processed_bytes / total_work) * 100 if total_work > 0 else 0
                    speed_mb = (processed_bytes / (1024*1024)) / elapsed if elapsed > 0 else 0
                    speed_lines = found_total / elapsed if elapsed > 0 else 0
                    left = (total_work - processed_bytes) / (processed_bytes / elapsed) if elapsed > 0 and processed_bytes > 0 else 0
                    files_left = total_files - processed_files
                    left_str = fmt_time(left) if left > 0 else "расчёт..."
                    ui_queue.put(("status", f"[+] {pct:.1f}% | файл {processed_files}/{total_files} | осталось {files_left} | {speed_mb:.0f} МБ/с | {speed_lines:,.0f} строк/с | найдено {found_total} | ~{left_str}"))
                    ui_queue.put(("progress", pct))
                    ui_queue.put(("stats", {
                        "pct": pct, "speed_mb": speed_mb, "speed_lines": speed_lines,
                        "eta": left_str, "processed_gb": processed_bytes/(1024**3),
                        "total_gb": total_work/(1024**3), "files_done": processed_files,
                        "files_total": total_files, "found": found_total,
                        "elapsed": fmt_time(elapsed)
                    }))
                if now - last_sys_log >= 5 and PSUTIL_AVAILABLE and disk_snapshot is not None:
                    last_sys_log = now
                    new_disk = psutil.disk_io_counters()
                    dt = 5.0
                    read_mb_s = (new_disk.read_bytes - disk_snapshot.read_bytes) / (1024*1024) / dt
                    write_mb_s = (new_disk.write_bytes - disk_snapshot.write_bytes) / (1024*1024) / dt
                    disk_snapshot = new_disk
                    cpu = psutil.cpu_percent()
                    ram = psutil.virtual_memory().percent
                    logger.info(f"SYS: CPU={cpu}% RAM={ram}% DISK_R={read_mb_s:.0f} DISK_W={write_mb_s:.0f} МБ/с")
                if progress_state and now - last_checkpoint_save >= 10:
                    last_checkpoint_save = now
                    progress_state["processed_bytes"] = processed_bytes
                    progress_state["found"] = found_total
                    save_progress_state(progress_state)
                if use_resume:
                    done_files.add(file_path)
                    save_checkpoint_state(done_files, file_path, 0, processed_bytes)
            if stop_flag.is_set():
                ui_queue.put(("status", "[!] Остановлено пользователем — сохраняю обработанное..."))
                if progress_state:
                    progress_state["processed_bytes"] = processed_bytes
                    progress_state["found"] = found_total
                    save_progress_state(progress_state)
                remaining_files = files_to_process[idx:]
                if remaining_files:
                    remainder_path = os.path.join(out_dir_date, "_остаток.txt")
                    with open(remainder_path, "w", encoding="utf-8") as rf:
                        for f in remaining_files:
                            try:
                                with open(f, "r", encoding="utf-8", errors="ignore") as inf:
                                    rf.writelines(inf)
                            except Exception:
                                pass
                    ui_queue.put(("status", f"[+] {len(remaining_files)} необработанных файлов сохранено в {remainder_path}"))
        ui_queue.put(("status", "[+] Дедупликация..."))
        files_to_split = []
        total_found = 0
        total_duplicates = 0
        total_unique_db = 0
        unique_hashes = load_unique_db() if use_unique_db else None
        new_hashes = set()
        for q in queries:
            if stop_flag.is_set():
                break
            if not all_temp_files[q]:
                continue
            safe_name = orig_to_safe[q]
            final_path = os.path.join(out_dir_date, f"{safe_name}.tmp")
            cnt, cross_skip, db_skip, new_q_hashes = merge_dedup_files(all_temp_files[q], final_path, unique_hashes if use_unique_db else None, stop_flag=stop_flag)
            total_found += cnt
            total_duplicates += cross_skip + db_skip
            if use_unique_db:
                new_hashes.update(new_q_hashes)
            # Domain counting on final file
            with open(final_path, 'rb') as rf:
                for line in rf:
                    parts = line.split(export_delim)
                    if len(parts) >= 2:
                        login = parts[0].decode('utf-8', errors='ignore')
                        if '@' in login:
                            domain = login.split('@')[-1]
                            top_domains_counter[domain] += 1
            final_real = os.path.join(out_dir_date, f"{safe_name}.txt")
            if os.path.exists(final_real):
                try:
                    os.remove(final_real)
                except Exception:
                    base, ext2 = os.path.splitext(final_real)
                    counter = 1
                    while os.path.exists(f"{base}_{counter}{ext2}"):
                        counter += 1
                    final_real = f"{base}_{counter}{ext2}"
            os.rename(final_path, final_real)
            if split_size > 0:
                files_to_split.append(final_real)
        if use_unique_db and new_hashes:
            add_unique_strings(new_hashes)
            total_unique_db = len(load_unique_db())
        else:
            total_unique_db = len(load_unique_db()) if use_unique_db else 0
        shutil.rmtree(temp_dir, ignore_errors=True)
        # Сохраняем состояние обработанных файлов (размер/mtime) для resume
        if use_resume:
            for f in files_to_process:
                try:
                    st = os.stat(f)
                    state[f] = [st.st_size, st.st_mtime]
                except Exception:
                    pass
            save_processed_state(state)
        ui_queue.put(("status", "[+] Генерация отчёта..."))
        elapsed = time.time() - start_time
        avg_speed = (processed_bytes / (1024*1024)) / elapsed if elapsed > 0 else 0
        generate_report(out_dir_date, queries, orig_to_safe, total_found, total_duplicates, total_unique_db, elapsed, avg_speed, top_domains_counter)
        if split_size > 0:
            for fp in files_to_split:
                split_file(fp, split_size)
        ui_queue.put(("progress", 100))
        if stop_flag.is_set():
            ui_queue.put(("status", f"[!] Прервано. Добавлено {total_found} строк, пропущено {total_duplicates} дублей | время {fmt_time(elapsed)} | ср. {avg_speed:.0f} МБ/с"))
            ui_queue.put(("success", {"found": total_found, "duplicates": total_duplicates, "total_db": total_unique_db, "elapsed": fmt_time(elapsed), "speed": f"{avg_speed:.0f}", "out": out_dir_date, "stopped": True}))
        else:
            ui_queue.put(("status", f"[✓] Готово! Добавлено {total_found} новых строк, пропущено {total_duplicates} дублей | время {fmt_time(elapsed)} | ср. {avg_speed:.0f} МБ/с"))
            ui_queue.put(("success", {"found": total_found, "duplicates": total_duplicates, "total_db": total_unique_db, "elapsed": fmt_time(elapsed), "speed": f"{avg_speed:.0f}", "out": out_dir_date}))
        try:
            import winsound
            winsound.Beep(1000, 500)
        except Exception:
            pass
        if stop_flag.is_set() and progress_state:
            save_progress_state(progress_state)
        else:
            clear_checkpoint()
            clear_progress_state()
    except Exception as e:
        ui_queue.put(("status", f"[!] Ошибка: {e}"))
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        ui_queue.put(("done", None))
        try:
            for td in temp_dirs:
                shutil.rmtree(td, ignore_errors=True)
        except Exception:
            pass

def main_cli():
    parser = argparse.ArgumentParser(description="URLmonster CLI")
    parser.add_argument("--src", required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", default="results")
    parser.add_argument("--mode", choices=["auto","default","url","exact","domain"], default="auto")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--blacklist")
    parser.add_argument("--split", type=int, default=0)
    parser.add_argument("--delim", choices=["colon","semicolon","pipe","tab","login","password"], default="colon")
    parser.add_argument("--no-multiprocess", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--save-full", action="store_true")
    parser.add_argument("--no-unique-db", action="store_true")
    parser.add_argument("--theme", choices=["dark"], default="dark")
    args = parser.parse_args()
    delim_map = {"colon": b':', "semicolon": b';', "pipe": b'|', "tab": b'\t', "login": b'login', "password": b'password'}
    export_delim = delim_map.get(args.delim, b':')
    blacklist = args.blacklist.split(",") if args.blacklist else None
    queries_data = []
    for item in args.queries.split(","):
        q = item.strip()
        if q.startswith("full:"):
            queries_data.append((q[5:], True))
        elif q.startswith("login:"):
            queries_data.append((q[6:], False))
        else:
            queries_data.append((q, None))
    ui_queue = queue.Queue()
    stop_flag = threading.Event()
    filters = {"exclude_empty": True, "case_sensitive": False}
    def dummy_ui_put(*args, **kwargs): pass
    ui_queue.put = dummy_ui_put
    run_check(args.src, queries_data, args.out, args.mode, filters, not args.no_multiprocess, args.resume, ui_queue, stop_flag, args.regex, blacklist, args.split, export_delim, args.theme, args.save_full, not args.no_unique_db)

# ============================================================
#  GUI НА CUSTOMTKINTER
# ============================================================

def open_queries_window(root, update_callback):
    global QUERIES_DATA
    win = ctk.CTkToplevel(root)
    win.title("Редактор запросов")
    win.geometry("600x450")
    win.focus()
    win.configure(fg_color=CARD)

    ctk.CTkLabel(win, text="ЗАПРОСЫ (отметьте Full для сохранения полной строки)", text_color=TEXT, font=("Segoe UI", 12, "bold")).pack(pady=8)

    tree = ttk.Treeview(win, columns=("query", "full"), show="headings", height=10)
    tree.heading("query", text="Запрос")
    tree.heading("full", text="Full")
    tree.column("query", width=400, anchor="w")
    tree.column("full", width=60, anchor="center")
    tree.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

    check_vars = {}
    item_to_query = {}

    def toggle_full(item):
        if item not in check_vars:
            return
        var = check_vars[item]
        var.set(not var.get())
        tree.set(item, "full", "☑" if var.get() else "☐")

    def add_query_to_tree(q, flag):
        var = tk.BooleanVar(value=flag if flag is not None else False)
        item = tree.insert("", tk.END, values=(q, "☑" if var.get() else "☐"))
        check_vars[item] = var
        item_to_query[item] = q
        def on_var_change(*args):
            tree.set(item, "full", "☑" if var.get() else "☐")
        var.trace_add("write", on_var_change)
        return item

    for q, flag in QUERIES_DATA:
        add_query_to_tree(q, flag)

    def on_tree_click(event):
        region = tree.identify_region(event.x, event.y)
        if region == "cell":
            column = tree.identify_column(event.x)
            if column == "#2":
                item = tree.identify_row(event.y)
                if item:
                    toggle_full(item)
    tree.bind("<Button-1>", on_tree_click)

    btn_frame = ctk.CTkFrame(win, fg_color="transparent")
    btn_frame.pack(pady=5)

    def add_query():
        q = simpledialog.askstring("Добавить запрос", "Введите запрос:", parent=win)
        if q:
            q = q.strip()
            if q:
                add_query_to_tree(q, None)
    ctk.CTkButton(btn_frame, text="Добавить", command=add_query, fg_color=ACCENT, hover_color=ACCENT_HV, text_color="#000000", corner_radius=RADIUS, font=("Segoe UI", 10, "bold"), width=10).pack(side="left", padx=5)

    def delete_selected():
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Инфо", "Выберите запрос для удаления")
            return
        for item in selected:
            if item in check_vars:
                del check_vars[item]
            if item in item_to_query:
                del item_to_query[item]
            tree.delete(item)
    ctk.CTkButton(btn_frame, text="Удалить", command=delete_selected, fg_color="#ff4444", hover_color="#cc0000", text_color="#FFFFFF", corner_radius=RADIUS, font=("Segoe UI", 10, "bold"), width=10).pack(side="left", padx=5)

    def save_queries():
        global QUERIES_DATA
        new_data = []
        for item in tree.get_children():
            values = tree.item(item, "values")
            if values:
                q = values[0]
                var = check_vars.get(item)
                flag = None
                if var is not None:
                    flag = var.get()
                new_data.append((q, flag))
        QUERIES_DATA = new_data
        save_queries_to_file(QUERIES_DATA)
        update_callback()
        win.destroy()
    ctk.CTkButton(btn_frame, text="Сохранить", command=save_queries, fg_color=ACCENT, hover_color=ACCENT_HV, text_color="#000000", corner_radius=RADIUS, font=("Segoe UI", 11, "bold"), width=12).pack(side="left", padx=5)
    ctk.CTkButton(btn_frame, text="Отмена", command=win.destroy, fg_color="#333333", hover_color="#555555", text_color=TEXT, corner_radius=RADIUS, font=("Segoe UI", 11), width=12).pack(side="left", padx=5)

def show_success_window(root, info):
    win = ctk.CTkToplevel(root)
    win.title("Успех")
    win.geometry("400x300")
    win.focus()
    ctk.CTkLabel(win, text="✔ МИССИЯ ВЫПОЛНЕНА", text_color=ACCENT, font=("Segoe UI", 18, "bold")).pack(pady=10)
    ctk.CTkLabel(win, text=f"Новых уникальных строк: {info['found']}", text_color=TEXT, font=FONT).pack()
    ctk.CTkLabel(win, text=f"Уже существовало: {info['duplicates']}", text_color=TEXT, font=FONT).pack()
    ctk.CTkLabel(win, text=f"Всего в базе уникальных строк: {info['total_db']}", text_color=TEXT, font=FONT).pack()
    ctk.CTkLabel(win, text=f"Время: {info['elapsed']}", text_color=TEXT, font=FONT).pack()
    ctk.CTkLabel(win, text=f"Средняя скорость: {info['speed']} МБ/с", text_color=TEXT, font=FONT).pack()
    ctk.CTkLabel(win, text=f"Результаты: {info['out']}", text_color=MUTED, font=FONT, wraplength=350).pack(pady=5)
    ctk.CTkButton(win, text="OK", command=win.destroy, fg_color=ACCENT, hover_color=ACCENT_HV, corner_radius=RADIUS, width=80).pack(pady=10)

if DND_AVAILABLE and ctk is not None:
    class AppBase(ctk.CTk, TkinterDnD.Tk):
        def __init__(self, *a, **kw):
            ctk.CTk.__init__(self, *a, **kw)
            try:
                self.tk.eval('package require tkdnd')
                TkinterDnD.Tk._register(self)
            except Exception:
                pass
    _AppBase = AppBase
else:
    _AppBase = ctk.CTk if ctk is not None else object

WEBUI_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>URLmonster Web UI</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0D0F12;color:#E4E6EB;font-family:system-ui,sans-serif;padding:20px}
h1{color:#1DB954;margin-bottom:16px}
.card{background:#16181D;border-radius:10px;padding:16px;margin-bottom:12px}
.row{display:flex;gap:8px;margin:8px 0;flex-wrap:wrap}
label{color:#8A8F98;min-width:80px}
.val{color:#E4E6EB}
.btn{background:#1DB954;border:none;color:#000;padding:8px 20px;border-radius:10px;cursor:pointer;font-size:14px}
.btn:hover{background:#25D366}
.btn.stop{background:#ff4444;color:#fff}
pre{background:#1E2127;padding:12px;border-radius:8px;overflow:auto;max-height:400px;font-size:13px}
select{background:#1E2127;color:#E4E6EB;border:1px solid #333;border-radius:8px;padding:6px;font-size:13px}
</style></head>
<body>
<h1>URLmonster</h1>
<div class="card">
<div class="row"><label>Source:</label><span class="val" id="src">-</span></div>
<div class="row"><label>Mode:</label><span class="val" id="mode">-</span></div>
<div class="row"><label>Queries:</label><span class="val" id="queries">-</span></div>
<div class="row" id="progress_row" style="display:none">
<label>Progress:</label>
<progress id="progress" value="0" max="100" style="flex:1"></progress>
<span class="val" id="pct">0%</span>
</div>
</div>
<div class="row">
<button class="btn" onclick="action('start')">Start</button>
<button class="btn stop" onclick="action('stop')">Stop</button>
</div>
<div class="card" id="results_card" style="display:none">
<div class="row">
<label>File:</label>
<select id="file_sel" onchange="loadFile()"></select>
<button class="btn" onclick="refreshFiles()">Refresh</button>
</div>
<pre id="file_content">Select a file</pre>
</div>
<script>
let currentFile=null;
async function api(path){let r=await fetch(path);return r.json()}
async function action(cmd){await fetch('/api/'+cmd);await updateStatus()}
async function updateStatus(){let s=await api('/api/status');
document.getElementById('src').textContent=s.src||'-';
document.getElementById('mode').textContent=s.mode||'-';
document.getElementById('queries').textContent=s.queries||'-';
if(s.running){document.getElementById('progress_row').style.display='flex';
document.getElementById('progress').value=s.progress;
document.getElementById('pct').textContent=Math.round(s.progress)+'%'}else{
document.getElementById('progress_row').style.display='none'}}
async function refreshFiles(){let r=await api('/api/results');
let sel=document.getElementById('file_sel');
sel.innerHTML='';
if(r.files&&r.files.length){document.getElementById('results_card').style.display='block';
r.files.forEach(f=>{let o=document.createElement('option');o.value=f;o.textContent=f;sel.appendChild(o)});
if(currentFile&&r.files.includes(currentFile))sel.value=currentFile;
loadFile()}else{document.getElementById('results_card').style.display='none'}}
async function loadFile(){let sel=document.getElementById('file_sel');
if(!sel.value)return;
currentFile=sel.value;
let r=await api('/api/results?file='+encodeURIComponent(sel.value));
document.getElementById('file_content').textContent=r.content||'Error'}
setInterval(updateStatus,2000);updateStatus();refreshFiles()
</script></body></html>"""

class App(_AppBase):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        self.title("URLmonster PRO")
        self.geometry("1000x680")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        # Переменные настроек
        self.src_var = tk.StringVar(value="")
        self.out_var = tk.StringVar(value=os.path.join(os.getcwd(), "results"))
        self.mode_var = tk.StringVar(value="auto")

        # Фильтры – используем BooleanVar
        self.filter_exclude_empty = tk.BooleanVar(value=True)
        self.filter_case_sensitive = tk.BooleanVar(value=False)

        self.use_multiprocess_var = tk.BooleanVar(value=True)
        self.use_resume_var = tk.BooleanVar(value=False)
        self.regex_var = tk.BooleanVar(value=False)
        self.use_unique_db_var = tk.BooleanVar(value=True)
        self.default_save_full_var = tk.BooleanVar(value=False)
        self.split_var = tk.IntVar(value=0)
        self.delim_var = tk.StringVar(value="colon")
        self.perf_mode_var = tk.StringVar(value="auto")
        self.dry_run_var = tk.BooleanVar(value=False)
        self._blacklist = []
        self._blacklist_label = None
        self.theme_name = "Изумруд"
        self.lang_var = tk.StringVar(value="ru")

        # Web UI server
        self._webui_thread = None
        self._webui_port = 8765

        # Tray icon
        self._tray_icon = None
        self._tray_thread = None
        self._in_tray = False

        # Загружаем настройки
        self.load_gui_settings()

        # DnD
        if DND_AVAILABLE:
            try:
                self.tk.eval('package require tkdnd')
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self._on_drop_files)
            except Exception:
                pass

        # Создаём интерфейс (новый табовый дизайн)
        self.overrideredirect(True)  # убираем стандартный заголовок
        self._group_display = {"all": "all"}
        self._group_rev = {"all": "all"}
        self._tab_content = {}

        # TitleBar
        self._titlebar = TitleBar(
            self, title="URLmonster PRO",
            on_close=self.on_closing,
            on_min=lambda: self.iconify() if not self._in_tray else self.withdraw(),
            on_max=lambda: self._toggle_maximized(),
        )
        # TabBar
        self._tab_bar = TabBar(
            self, tabs=[
                ("Дашборд", "📊", _("tab_dashboard")),
                ("Монитор", "📋", _("tab_monitor")),
                ("Настройки", "⚙️", _("tab_settings")),
                ("Результаты", "📁", _("tab_results")),
                ("История", "🕐", _("tab_history")),
            ],
            on_switch=self._switch_tab,
        )

        # Content container
        self._content = ctk.CTkFrame(self, fg_color=BG)
        self._content.pack(fill="both", expand=True)
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        # Build tabs
        self._build_dashboard_tab()
        self._build_monitor_tab()
        self._build_settings_tab()
        self._build_results_tab()
        self._build_history_tab()

        # Footer with start/stop/tools
        self._build_new_footer()

        self._show_tab("Дашборд")
        self.after(50, lambda: self._apply_theme(self.theme_name))
        self.after(200, self._setup_tray)
        self.bind("<Unmap>", lambda e: self.after(50, self._check_minimize))

        # Очередь и флаг для воркера
        self.ui_queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker_thread = None
        self.running = False
        self._done_received = False

        # Запуск обработки очереди
        self.after(100, self._poll_queue)

    def load_gui_settings(self):
        settings = load_settings()
        self.src_var.set(settings.get("src", ""))
        self.out_var.set(settings.get("out", os.path.join(os.getcwd(), "results")))
        self.mode_var.set(settings.get("mode", "auto"))
        # Фильтры
        filters = settings.get("filters", {})
        if isinstance(filters, dict):
            self.filter_exclude_empty.set(filters.get("exclude_empty", True))
            self.filter_case_sensitive.set(filters.get("case_sensitive", False))
        self.use_multiprocess_var.set(settings.get("use_multiprocess", True))
        self.use_resume_var.set(settings.get("use_resume", False))
        self.regex_var.set(settings.get("regex_mode", False))
        self.use_unique_db_var.set(settings.get("use_unique_db", True))
        self.default_save_full_var.set(settings.get("default_save_full", False))
        self.split_var.set(settings.get("split_size", 0))
        self.delim_var.set(settings.get("export_delim", "colon"))
        self.perf_mode_var.set(settings.get("perf_mode", "auto"))
        self._blacklist = settings.get("blacklist", [])
        if not isinstance(self._blacklist, list):
            self._blacklist = []
        self.theme_name = settings.get("gui_theme", "Изумруд")
        if self.theme_name not in THEMES:
            self.theme_name = "Изумруд"
        theme = settings.get("theme", "dark")
        lang = settings.get("lang", "ru")
        global LANGUAGE
        LANGUAGE = lang
        self.lang_var.set(lang)
        if theme == "light":
            ctk.set_appearance_mode("light")
        else:
            ctk.set_appearance_mode("dark")

    def save_gui_settings(self):
        filters = {
            "exclude_empty": self.filter_exclude_empty.get(),
            "case_sensitive": self.filter_case_sensitive.get()
        }
        settings = {
            "src": self.src_var.get(),
            "out": self.out_var.get(),
            "mode": self.mode_var.get(),
            "filters": filters,
            "use_multiprocess": self.use_multiprocess_var.get(),
            "use_resume": self.use_resume_var.get(),
            "regex_mode": self.regex_var.get(),
            "use_unique_db": self.use_unique_db_var.get(),
            "default_save_full": self.default_save_full_var.get(),
            "split_size": self.split_var.get(),
            "export_delim": self.delim_var.get(),
            "theme": "dark" if ctk.get_appearance_mode() == "Dark" else "light",
            "gui_theme": self.theme_name,
            "blacklist": self._blacklist,
            "perf_mode": self.perf_mode_var.get(),
            "lang": self.lang_var.get()
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _add_file_row(self, parent, row, label, var):
        ctk.CTkLabel(parent, text=label, text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, sticky="w", padx=16, pady=(6, 2))
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=1, sticky="ew", padx=16, pady=4)
        wrap.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(wrap, textvariable=var, placeholder_text="...", fg_color=FIELD,
                             border_width=0, corner_radius=RADIUS, height=38, font=FONT, text_color=TEXT)
        entry.grid(row=0, column=0, sticky="ew")
        btn_file = ctk.CTkButton(wrap, text=_("btn_file"), width=70, fg_color=ACCENT, hover_color=ACCENT_HV,
                                 corner_radius=RADIUS, command=self._pick_file)
        btn_file.grid(row=0, column=1, padx=(8, 0))
        btn_folder = ctk.CTkButton(wrap, text=_("btn_folder"), width=70, fg_color=ACCENT, hover_color=ACCENT_HV,
                                   corner_radius=RADIUS, command=self._pick_folder)
        btn_folder.grid(row=0, column=2, padx=(8, 0))

    def _add_field_row(self, parent, row, label, placeholder, callback):
        ctk.CTkLabel(parent, text=label, text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, sticky="w", padx=16, pady=(6, 2))
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(row=row, column=1, sticky="ew", padx=16, pady=4)
        wrap.grid_columnconfigure(0, weight=1)
        status_lbl = ctk.CTkLabel(wrap, text=placeholder, text_color=MUTED, font=FONT, anchor="w")
        status_lbl.grid(row=0, column=0, sticky="w")
        if label == _("blacklist_label"):
            self._blacklist_label = status_lbl
        btn = ctk.CTkButton(wrap, text=_("blacklist_edit"), width=100, fg_color=ACCENT, hover_color=ACCENT_HV,
                            corner_radius=RADIUS, command=callback)
        btn.grid(row=0, column=1, padx=(8, 0))

    def _update_queries_label(self):
        if self.queries_status_label:
            self.queries_status_label.configure(text=f"{len(QUERIES_DATA)} {_('queries_label')}")
        self._update_group_queries()

    def _update_group_queries(self):
        groups = list(QUERIES_GROUPS.keys())
        self._group_display = {"all": _("group_all")}
        self._group_display.update({g: g for g in groups})
        self._group_rev = {v: k for k, v in self._group_display.items()}
        display = list(self._group_display.values())
        current = self.group_var.get()
        cur_disp = self._group_display.get(current, _("group_all"))
        self.group_menu.configure(values=display)
        self.group_var.set(cur_disp if cur_disp in display else _("group_all"))

    def _on_lang_change(self, lang):
        global LANGUAGE
        LANGUAGE = lang
        self.title(_("app_title"))
        self._rebuild_ui()

    def _rebuild_ui(self):
        """Перестраивает GUI при смене языка."""
        for w in self.winfo_children():
            w.destroy()
        self._tab_content.clear()
        # rebuild new layout
        self.overrideredirect(True)
        self._titlebar = TitleBar(
            self, title="URLmonster PRO",
            on_close=self.on_closing,
            on_min=lambda: self.iconify() if not self._in_tray else self.withdraw(),
            on_max=lambda: self._toggle_maximized(),
        )
        self._tab_bar = TabBar(
            self, tabs=[
                ("Дашборд", "📊", _("tab_dashboard")),
                ("Монитор", "📋", _("tab_monitor")),
                ("Настройки", "⚙️", _("tab_settings")),
                ("Результаты", "📁", _("tab_results")),
                ("История", "🕐", _("tab_history")),
            ],
            on_switch=self._switch_tab,
        )
        self._content = ctk.CTkFrame(self, fg_color=BG)
        self._content.pack(fill="both", expand=True)
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)
        self._build_dashboard_tab()
        self._build_monitor_tab()
        self._build_settings_tab()
        self._build_results_tab()
        self._build_history_tab()

        self._show_tab("Дашборд")
        self._build_new_footer()

    def _on_drop_files(self, event):
        paths = []
        for raw in event.data.split():
            p = raw.strip("{}").strip()
            if p and (os.path.isfile(p) or os.path.isdir(p)):
                paths.append(p)
        if len(paths) == 1:
            self.src_var.set(paths[0])
        elif len(paths) > 1:
            dirs = [p for p in paths if os.path.isdir(p)]
            if dirs:
                self.src_var.set(dirs[0])
            else:
                common = os.path.commonpath(paths)
                self.src_var.set(common if os.path.isdir(common) else os.path.dirname(common))

    def _apply_preset(self, name):
        if name == _("preset_default"):
            return
        presets = load_presets()
        p = presets.get(name)
        if not p:
            return
        self.src_var.set(p.get("src", ""))
        self.out_var.set(p.get("out", ""))
        self.mode_var.set(p.get("mode", "auto"))
        filters = p.get("filters", {})
        if isinstance(filters, dict):
            self.filter_exclude_empty.set(filters.get("exclude_empty", True))
            self.filter_case_sensitive.set(filters.get("case_sensitive", False))
        self.use_multiprocess_var.set(p.get("use_multiprocess", True))
        self.use_resume_var.set(p.get("use_resume", False))
        self.regex_var.set(p.get("regex_mode", False))
        self.use_unique_db_var.set(p.get("use_unique_db", True))
        self.default_save_full_var.set(p.get("default_save_full", False))
        self.split_var.set(p.get("split_size", 0))
        self.delim_var.set(p.get("export_delim", "colon"))
        self.perf_mode_var.set(p.get("perf_mode", "auto"))
        self.dry_run_var.set(p.get("dry_run", False))
        self._blacklist = list(p.get("blacklist", []))
        if self._blacklist_label:
            self._blacklist_label.configure(text=f"{len(self._blacklist)} элементов")

    def _save_preset(self):
        name = ctk.CTkInputDialog(text=_("preset_save_prompt"), title=_("preset_save_title")).get_input()
        if not name:
            return
        presets = load_presets()
        presets[name] = {
            "src": self.src_var.get(),
            "out": self.out_var.get(),
            "mode": self.mode_var.get(),
            "filters": {
                "exclude_empty": self.filter_exclude_empty.get(),
                "case_sensitive": self.filter_case_sensitive.get(),
            },
            "use_multiprocess": self.use_multiprocess_var.get(),
            "use_resume": self.use_resume_var.get(),
            "regex_mode": self.regex_var.get(),
            "use_unique_db": self.use_unique_db_var.get(),
            "default_save_full": self.default_save_full_var.get(),
            "split_size": self.split_var.get(),
            "export_delim": self.delim_var.get(),
            "perf_mode": self.perf_mode_var.get(),
            "dry_run": self.dry_run_var.get(),
            "blacklist": list(self._blacklist),
        }
        save_presets(presets)
        default_name = _("preset_default")
        self.preset_menu.configure(values=[default_name] + sorted(presets.keys()))
        self.preset_var.set(name)

    def _delete_preset(self):
        name = self.preset_var.get()
        default_name = _("preset_default")
        if name == default_name:
            return
        if not messagebox.askyesno(_("preset_delete_title"), _("preset_delete_confirm", name.replace("%", "%%"))):
            return
        presets = load_presets()
        presets.pop(name, None)
        save_presets(presets)
        self.preset_menu.configure(values=[default_name] + sorted(presets.keys()))
        self.preset_var.set(default_name)

    def _pick_file(self):
        p = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.src_var.set(p)

    def _pick_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.src_var.set(p)

    def _edit_queries(self):
        open_queries_window(self, self._update_queries_label)

    def _edit_blacklist(self):
        win = ctk.CTkToplevel(self)
        win.title("Blacklist")
        win.geometry("500x350")
        win.focus()
        win.configure(fg_color=CARD)

        ctk.CTkLabel(win, text="ИСКЛЮЧАЮЩИЕ ФРАЗЫ (по одной на строку)", text_color=TEXT, font=("Segoe UI", 12, "bold")).pack(pady=8)

        tree = ttk.Treeview(win, columns=("phrase",), show="headings", height=12)
        tree.heading("phrase", text="Фраза")
        tree.column("phrase", width=450, anchor="w")
        tree.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        items = {}
        for phrase in self._blacklist:
            item = tree.insert("", tk.END, values=(phrase,))
            items[item] = phrase

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(pady=5)

        def add_phrase():
            p = simpledialog.askstring("Добавить фразу", "Введите исключающую фразу:", parent=win)
            if p:
                p = p.strip()
                if p:
                    item = tree.insert("", tk.END, values=(p,))
                    items[item] = p
        ctk.CTkButton(btn_frame, text="Добавить", command=add_phrase, fg_color=ACCENT, hover_color=ACCENT_HV, text_color="#000000", corner_radius=RADIUS, font=("Segoe UI", 10, "bold"), width=10).pack(side="left", padx=5)

        def delete_selected():
            selected = tree.selection()
            if not selected:
                messagebox.showinfo("Инфо", "Выберите фразу для удаления")
                return
            for item in selected:
                if item in items:
                    del items[item]
                tree.delete(item)
        ctk.CTkButton(btn_frame, text="Удалить", command=delete_selected, fg_color="#ff4444", hover_color="#cc0000", text_color="#FFFFFF", corner_radius=RADIUS, font=("Segoe UI", 10, "bold"), width=10).pack(side="left", padx=5)

        def save_blacklist():
            self._blacklist = [tree.item(item, "values")[0] for item in tree.get_children()]
            if self._blacklist_label:
                self._blacklist_label.configure(text=f"{len(self._blacklist)} элементов")
            win.destroy()
        ctk.CTkButton(btn_frame, text="Сохранить", command=save_blacklist, fg_color=ACCENT, hover_color=ACCENT_HV, text_color="#000000", corner_radius=RADIUS, font=("Segoe UI", 11, "bold"), width=12).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Отмена", command=win.destroy, fg_color="#333333", hover_color="#555555", text_color=TEXT, corner_radius=RADIUS, font=("Segoe UI", 11), width=12).pack(side="left", padx=5)

    def _apply_theme(self, name):
        if name not in THEMES:
            return
        self.theme_name = name
        t = THEMES[name]
        global BG, CARD, FIELD, ACCENT, ACCENT_HV, TEXT, MUTED
        BG, CARD, FIELD = t["bg"], t["card"], t["field"]
        ACCENT, ACCENT_HV = t["accent"], t["accent_hv"]
        TEXT, MUTED = t["text"], t["muted"]
        self.configure(fg_color=BG)
        self._recolor_widgets(self)

    def _recolor_widgets(self, widget):
        for w in widget.winfo_children():
            cls = w.__class__.__name__
            try:
                if cls == "CTkScrollableFrame":
                    w.configure(fg_color=CARD)
                elif cls in ("CTkFrame",):
                    fg = w.cget("fg_color")
                    if fg and fg not in ("transparent",):
                        w.configure(fg_color=CARD)
                elif cls == "CTkTextbox":
                    w.configure(fg_color=FIELD)
                elif cls == "CTkEntry":
                    w.configure(fg_color=FIELD)
                elif cls == "CTkProgressBar":
                    w.configure(progress_color=ACCENT, fg_color=FIELD)
                elif cls == "CTkButton":
                    try:
                        txt = w.cget("text")
                        accent_btns = [_("btn_start"), _("btn_file"), _("btn_folder"), _("blacklist_edit"), _("queries_edit")]
                        if txt in accent_btns:
                            w.configure(fg_color=ACCENT, hover_color=ACCENT_HV)
                        elif txt == _("btn_stop"):
                            w.configure(fg_color=FIELD, hover_color="#ff4444")
                        else:
                            w.configure(fg_color=FIELD)
                    except Exception:
                        pass
                elif cls == "CTkLabel":
                    w.configure(text_color=TEXT)
                elif cls == "CTkSwitch":
                    w.configure(progress_color=ACCENT, text_color=TEXT)
                elif cls == "CTkSegmentedButton":
                    w.configure(selected_color=ACCENT, selected_hover_color=ACCENT_HV,
                                fg_color=FIELD, unselected_color=FIELD)
                elif cls == "CTkOptionMenu":
                    w.configure(fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                dropdown_text_color=TEXT, text_color=TEXT)
                elif cls == "CTkRadioButton":
                    w.configure(fg_color=ACCENT, text_color=TEXT)
            except Exception:
                pass
            try:
                self._recolor_widgets(w)
            except Exception:
                pass

    def _build_log(self):
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=RADIUS)
        card.grid(row=0, column=1, padx=(8, 16), pady=16, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=_("log_title"), text_color=TEXT, font=FONT_BOLD).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self.log_text = ctk.CTkTextbox(card, fg_color=FIELD, text_color="#7CE0A0", font=MONO, corner_radius=RADIUS, border_width=0)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_text.tag_config("ts", foreground="#555555")
        self.log_text.tag_config("INFO", foreground="#7CE0A0")
        self.log_text.tag_config("ERROR", foreground="#FF6B6B")
        self.log_text.tag_config("OK", foreground="#4ECDC4")
        self.log_text.insert("end", "[+] Готов к работе\n")
        self.log_text.configure(state="disabled")

    def _toggle_watch(self):
        if self.watch_active:
            self.watch_active = False
            self.btn_watch.configure(text="🔍 "+_("btn_watch_start"), fg_color=FIELD)
            self._log("[!] " + _("watch_stopped"))
        else:
            src = self.src_var.get()
            if not src or not os.path.isdir(src):
                messagebox.showerror("Ошибка", _("err_no_watch_dir"))
                return
            self._watch_src = src
            self.watch_active = True
            self.btn_watch.configure(text="🔍 "+_("btn_watch_stop"), fg_color=ACCENT)
            self._log("[+] " + _("watch_started"))
            self.watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.watch_thread.start()

    def _watch_loop(self):
        import time
        while self.watch_active:
            try:
                if not self.running:
                    src = self._watch_src
                    if src and os.path.isdir(src):
                        files_list, _ = collect_files(src)
                        state = load_processed_state()
                        new_files = get_new_files(files_list, state)
                        if new_files:
                            self.ui_queue.put(("watch_trigger", None))
                time.sleep(5)
            except Exception:
                import traceback
                traceback.print_exc()
                break

    # ---- New Tab UI Methods ----
    def _toggle_maximized(self):
        try:
            if self.attributes('-fullscreen'):
                self.attributes('-fullscreen', False)
            else:
                self.attributes('-fullscreen', True)
        except Exception:
            # fallback для override-redirect окон
            self.state('zoomed' if self.state() != 'zoomed' else 'normal')

    def _switch_tab(self, name):
        self._show_tab(name)

    def _show_tab(self, name):
        f = self._tab_content.get(name)
        if f:
            for ff in self._tab_content.values():
                ff.pack_forget()
            f.pack(fill="both", expand=True)

    def _build_dashboard_tab(self):
        f = ctk.CTkFrame(self._content, fg_color=BG)
        f.grid_rowconfigure(2, weight=1)
        for c in range(4):
            f.grid_columnconfigure(c, weight=1)
        self._dash_cards = {}
        cards_data = [
            ("speed_mb", _("dash_speed_mb"), "0.0", "МБ/с", "🚀", 0, 0),
            ("speed_lines", _("dash_speed_lines"), "0", "строк/с", "⚡", 0, 1),
            ("found", _("dash_found"), "0", "", "🎯", 0, 2),
            ("files", _("dash_files"), "0/0", "", "📂", 0, 3),
            ("eta", _("dash_eta"), "—", "", "⏱", 1, 0),
            ("elapsed", _("dash_elapsed"), "—", "", "🕐", 1, 1),
            ("progress", _("dash_progress"), "0%", "", "📈", 1, 2),
        ]
        for key, label, val, unit, icon, r, c in cards_data:
            card = MetricCard(f, label=label, value=val, unit=unit, icon=icon)
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            self._dash_cards[key] = card
        self._dash_log = LiveLog(f, fg_color=FIELD, text_color="#7CE0A0", font=MONO, corner_radius=RADIUS, border_width=0)
        self._dash_log.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=6, pady=(0, 6))
        self._tab_content["Дашборд"] = f

    def _build_monitor_tab(self):
        f = ctk.CTkFrame(self._content, fg_color=BG)
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)
        self._build_log_into(f)
        self._tab_content["Монитор"] = f

    def _build_settings_tab(self):
        f = ctk.CTkFrame(self._content, fg_color=BG)
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)
        self._build_main_into(f)
        self._tab_content["Настройки"] = f

    def _build_results_tab(self):
        f = ctk.CTkFrame(self._content, fg_color=BG)
        btn = ctk.CTkButton(f, text="📁 Открыть результаты", fg_color=ACCENT, hover_color=ACCENT_HV,
                            corner_radius=RADIUS, command=self._open_results_viewer)
        btn.pack(pady=40, padx=20, expand=True)
        self._tab_content["Результаты"] = f

    def _build_history_tab(self):
        f = ctk.CTkFrame(self._content, fg_color=BG)
        f.grid_rowconfigure(1, weight=1)
        f.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 4))
        ctk.CTkLabel(top, text="История проверок", text_color=TEXT,
                     font=("Segoe UI", 16, "bold")).pack(side="left")
        ctk.CTkButton(top, text="🔄 Обновить", fg_color=ACCENT, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=32, font=FONT,
                      command=lambda: self._refresh_history(history_list)).pack(side="right", padx=(8, 0))
        ctk.CTkButton(top, text="📂 Открыть", fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=32, font=FONT,
                      command=self._open_results_viewer).pack(side="right")
        scroll = ctk.CTkScrollableFrame(f, fg_color=CARD, corner_radius=RADIUS)
        scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 16))
        history_list = ctk.CTkFrame(scroll, fg_color="transparent")
        history_list.pack(fill="x", expand=True)
        self._refresh_history(history_list)
        self._tab_content["История"] = f

    def _refresh_history(self, container):
        for w in container.winfo_children():
            w.destroy()
        out_dir = self.out_var.get()
        if not os.path.isdir(out_dir):
            ctk.CTkLabel(container, text="Папка результатов не найдена", text_color=MUTED, font=FONT).pack(pady=30)
            return
        folders = []
        for name in os.listdir(out_dir):
            fpath = os.path.join(out_dir, name)
            if os.path.isdir(fpath) and os.path.exists(os.path.join(fpath, "report.txt")):
                folders.append((name, fpath))
        folders.sort(key=lambda x: x[0], reverse=True)
        if not folders:
            ctk.CTkLabel(container, text="Нет завершённых проверок", text_color=MUTED, font=FONT).pack(pady=30)
            return
        for name, fpath in folders:
            row = ctk.CTkFrame(container, fg_color=FIELD, corner_radius=RADIUS)
            row.pack(fill="x", padx=4, pady=3)
            try:
                with open(os.path.join(fpath, "report.txt"), "r", encoding="utf-8") as rf:
                    first_line = rf.readline().strip()
            except Exception:
                first_line = name
            ctk.CTkLabel(row, text=f"📁 {name}", text_color=TEXT, font=("Segoe UI", 12, "bold"),
                         anchor="w").pack(side="left", padx=12, pady=8, fill="x", expand=True)
            ctk.CTkLabel(row, text=first_line, text_color=MUTED, font=("Segoe UI", 10),
                         anchor="w").pack(side="left", padx=4, pady=8, fill="x", expand=True)
            ctk.CTkButton(row, text="📂", width=36, height=32, fg_color=ACCENT, hover_color=ACCENT_HV,
                          corner_radius=RADIUS, font=FONT,
                          command=lambda p=fpath: os.startfile(p)).pack(side="right", padx=8, pady=4)

    def _build_main_into(self, parent):
        card = ctk.CTkScrollableFrame(parent, fg_color=CARD, corner_radius=RADIUS)
        card.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)
        row = 0
        # Пресеты
        frm_preset = ctk.CTkFrame(card, fg_color="transparent")
        frm_preset.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))
        ctk.CTkLabel(frm_preset, text=_("preset") + ":", text_color=TEXT, font=FONT).pack(side="left", padx=(0, 6))
        default_name = _("preset_default")
        self.preset_var = ctk.StringVar(value=default_name)
        preset_values = [default_name] + sorted(load_presets().keys())
        self.preset_menu = ctk.CTkOptionMenu(frm_preset, variable=self.preset_var, values=preset_values,
                                             fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                             dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                             dropdown_text_color=TEXT, text_color=TEXT,
                                             corner_radius=RADIUS, font=FONT,
                                             command=self._apply_preset)
        self.preset_menu.pack(side="left", padx=2)
        ctk.CTkButton(frm_preset, text="💾", width=30, fg_color=ACCENT, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, command=self._save_preset).pack(side="left", padx=2)
        ctk.CTkButton(frm_preset, text="🗑", width=30, fg_color="#ff4444", hover_color="#cc0000",
                      corner_radius=RADIUS, command=self._delete_preset).pack(side="left", padx=2)
        ctk.CTkLabel(frm_preset, text="🌐", font=("Segoe UI", 16)).pack(side="left", padx=(12, 2))
        self.lang_menu = ctk.CTkOptionMenu(frm_preset, variable=self.lang_var, values=["ru", "en"],
                                           fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                           dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                           dropdown_text_color=TEXT, text_color=TEXT,
                                           corner_radius=RADIUS, font=FONT,
                                           command=self._on_lang_change)
        self.lang_menu.pack(side="left", padx=2)
        row += 1
        # База
        self._add_file_row(card, row, _("base_label"), self.src_var)
        row += 1
        # Папка сохранения
        ctk.CTkLabel(card, text=_("out_label"), text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, sticky="w", padx=16, pady=(6, 2))
        row += 1
        wrap_out = ctk.CTkFrame(card, fg_color="transparent")
        wrap_out.grid(row=row, column=1, sticky="ew", padx=16, pady=4)
        wrap_out.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(wrap_out, textvariable=self.out_var, placeholder_text=_("out_label")+"...", fg_color=FIELD,
                     border_width=0, corner_radius=RADIUS, height=38, font=FONT, text_color=TEXT).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(wrap_out, text=_("btn_folder"), width=70, fg_color=ACCENT, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, command=lambda: self.out_var.set(filedialog.askdirectory() or self.out_var.get())).grid(row=0, column=1, padx=(8, 0))
        row += 1
        frm_queries = ctk.CTkFrame(card, fg_color="transparent")
        frm_queries.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=4)
        self.queries_status_label = ctk.CTkLabel(frm_queries, text=f"{len(QUERIES_DATA)} {_('queries_label')}", text_color=TEXT, font=FONT)
        self.queries_status_label.pack(side="left", padx=(0, 10))
        ctk.CTkButton(frm_queries, text=_("queries_edit"), width=40, fg_color=ACCENT, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, command=self._edit_queries).pack(side="left", padx=2)
        ctk.CTkLabel(frm_queries, text=_("group")+":", text_color=TEXT, font=FONT).pack(side="left", padx=(10, 2))
        self.group_var = ctk.StringVar(value="all")
        self.group_menu = ctk.CTkOptionMenu(frm_queries, variable=self.group_var, values=["all"],
                                            fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                            dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                            dropdown_text_color=TEXT, text_color=TEXT, corner_radius=RADIUS, font=FONT,
                                            command=lambda _: self._update_group_queries())
        self.group_menu.pack(side="left")
        self._group_display = {"all": _("group_all")}
        self._group_rev = {"all": "all"}
        row += 1
        self._add_field_row(card, row, _("blacklist_label"), f"{len(self._blacklist)} {_('queries_label')}", self._edit_blacklist)
        row += 1
        ctk.CTkLabel(card, text=_("mode_label"), text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 2))
        row += 1
        self._mode_lbl = {"auto": _("mode_auto"), "default": _("mode_default"), "url": "URL", "exact": _("mode_exact"), "domain": _("mode_domain")}
        self._mode_rev = {v: k for k, v in self._mode_lbl.items()}
        mode_menu = ctk.CTkOptionMenu(card, values=list(self._mode_lbl.values()),
                                      fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                      dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                      dropdown_text_color=TEXT, text_color=TEXT,
                                      corner_radius=RADIUS, font=FONT,
                                      command=lambda val: self.mode_var.set(self._mode_rev.get(val, "auto")))
        mode_menu.grid(row=row, column=0, sticky="w", padx=16, pady=(2, 6))
        mode_menu.set(self._mode_lbl.get(self.mode_var.get(), _("mode_auto")))
        row += 1
        frm_filters = ctk.CTkFrame(card, fg_color="transparent")
        frm_filters.grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=4)
        ctk.CTkLabel(frm_filters, text=_("filters")+":", text_color=TEXT, font=FONT_BOLD).pack(side="left", padx=(0, 10))
        sw_excl = ctk.CTkSwitch(frm_filters, text=_("filter_exclude_empty"), variable=self.filter_exclude_empty,
                                progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                                font=FONT, text_color=TEXT)
        sw_excl.pack(side="left", padx=5)
        sw_case = ctk.CTkSwitch(frm_filters, text=_("filter_case_sensitive"), variable=self.filter_case_sensitive,
                                progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                                font=FONT, text_color=TEXT)
        sw_case.pack(side="left", padx=5)
        row += 1
        frm_opts = ctk.CTkFrame(card, fg_color="transparent")
        frm_opts.grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=4)
        ctk.CTkLabel(frm_opts, text=_("options")+":", text_color=TEXT, font=FONT_BOLD).pack(side="left", padx=(0, 10))
        sw_mp = ctk.CTkSwitch(frm_opts, text=_("opt_multiprocess"), variable=self.use_multiprocess_var,
                              progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                              font=FONT, text_color=TEXT)
        sw_mp.pack(side="left", padx=5)
        sw_res = ctk.CTkSwitch(frm_opts, text=_("opt_resume"), variable=self.use_resume_var,
                               progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                               font=FONT, text_color=TEXT)
        sw_res.pack(side="left", padx=5)
        sw_regex = ctk.CTkSwitch(frm_opts, text="Regex", variable=self.regex_var,
                                progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                                font=FONT, text_color=TEXT)
        sw_regex.pack(side="left", padx=5)
        row += 1
        sw_full = ctk.CTkSwitch(card, text=_("opt_save_full"), variable=self.default_save_full_var,
                                progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                                font=FONT, text_color=TEXT)
        sw_full.grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=4)
        row += 1
        sw_uniq = ctk.CTkSwitch(card, text=_("opt_unique_db"), variable=self.use_unique_db_var,
                                progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                                font=FONT, text_color=TEXT)
        sw_uniq.grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=4)
        row += 1
        sw_dry = ctk.CTkSwitch(card, text=_("opt_dry_run"), variable=self.dry_run_var,
                               progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HV,
                               font=FONT, text_color=TEXT)
        sw_dry.grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=4)
        row += 1
        ctk.CTkLabel(card, text=_("opt_delim"), text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 2))
        row += 1
        frm_export = ctk.CTkFrame(card, fg_color="transparent")
        frm_export.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 4))
        delim_rev = {"colon": ":", "semicolon": ";", "pipe": "|", "tab": "tab", "login": "login", "password": "pass"}
        delim_display_label = ctk.CTkLabel(frm_export, text=f"[ {delim_rev.get(self.delim_var.get(), ':')} ]",
                                           text_color=ACCENT, font=("Segoe UI", 13, "bold"))
        delim_display_label.pack(side="left", padx=(0, 8))
        delim_seg = ctk.CTkSegmentedButton(frm_export, values=[":", ";", "|", "tab", "login", "pass"],
                                            selected_color=ACCENT, selected_hover_color=ACCENT_HV,
                                            fg_color=FIELD, unselected_color="#3a3a3a", corner_radius=RADIUS,
                                            font=("Segoe UI", 11),
                                            command=lambda val: (self.delim_var.set({":":"colon",";":"semicolon","|":"pipe","tab":"tab","login":"login","pass":"password"}.get(val, "colon")), delim_display_label.configure(text=f"[ {val} ]")))
        delim_seg.pack(side="left")
        delim_seg.set(delim_rev.get(self.delim_var.get(), ":"))
        ctk.CTkLabel(frm_export, text="    "+_("opt_split")+":", text_color=TEXT, font=FONT).pack(side="left", padx=(10, 5))
        spin = ctk.CTkEntry(frm_export, width=80, textvariable=self.split_var, fg_color=FIELD, corner_radius=RADIUS, font=FONT)
        spin.pack(side="left")
        row += 1
        ctk.CTkLabel(card, text=_("theme"), text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 2))
        row += 1
        theme_names = list(THEMES.keys())
        self.theme_menu = ctk.CTkOptionMenu(card, values=theme_names,
                                            fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                            dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                            dropdown_text_color=TEXT, text_color=TEXT,
                                            corner_radius=RADIUS, font=FONT,
                                            command=self._apply_theme)
        self.theme_menu.grid(row=row, column=0, sticky="w", padx=16, pady=(2, 6))
        self.theme_menu.set(self.theme_name if self.theme_name in theme_names else "Изумруд")
        row += 1
        ctk.CTkLabel(card, text=_("perf_mode"), text_color=TEXT, font=FONT_BOLD).grid(row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 2))
        row += 1
        self._perf_lbl = {"auto": _("perf_auto"), "ssd": _("perf_ssd"), "hdd": _("perf_hdd")}
        self._perf_rev = {v: k for k, v in self._perf_lbl.items()}
        perf_menu = ctk.CTkOptionMenu(card, values=list(self._perf_lbl.values()),
                                      fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                      dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                      dropdown_text_color=TEXT, text_color=TEXT,
                                      corner_radius=RADIUS, font=FONT,
                                       command=lambda val: self.perf_mode_var.set(self._perf_rev.get(val, "auto")))
        perf_menu.grid(row=row, column=0, sticky="w", padx=16, pady=(2, 6))
        perf_menu.set(self._perf_lbl.get(self.perf_mode_var.get(), _("perf_auto")))

    def _build_log_into(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=RADIUS)
        card.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=_("log_title"), text_color=TEXT, font=FONT_BOLD).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self.log_text = ctk.CTkTextbox(card, fg_color=FIELD, text_color="#7CE0A0", font=MONO, corner_radius=RADIUS, border_width=0)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_text.tag_config("ts", foreground="#555555")
        self.log_text.tag_config("INFO", foreground="#7CE0A0")
        self.log_text.tag_config("ERROR", foreground="#FF6B6B")
        self.log_text.tag_config("OK", foreground="#4ECDC4")
        self.log_text.insert("end", "[+] Готов к работе\n")
        self.log_text.configure(state="disabled")

    def _build_new_footer(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 16))
        bar.grid_columnconfigure(0, weight=1)

        self.pb = ctk.CTkProgressBar(bar, progress_color=ACCENT, fg_color=FIELD, height=18, corner_radius=RADIUS)
        self.pb.set(0)
        self.pb.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.pct = ctk.CTkLabel(bar, text="0%", text_color=TEXT, font=("Segoe UI", 12, "bold"))
        self.pct.grid(row=0, column=1, sticky="e", padx=(0, 20))
        bar.grid_columnconfigure(1, weight=0)

        self.stat_frame = ctk.CTkFrame(bar, fg_color="transparent")
        self.stat_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        self.stat_frame.grid_columnconfigure(0, weight=1)
        self.stat_labels = {}
        stat_items = [
            ("speed", _("stat_speed")), ("found", _("stat_found")),
            ("eta", _("stat_eta")), ("files", _("stat_files")), ("elapsed", _("stat_elapsed"))
        ]
        lbls = []
        for key, label in stat_items:
            lbl = ctk.CTkLabel(self.stat_frame, text=f"{label}: --", text_color=MUTED, font=("Segoe UI", 11))
            lbls.append(lbl)
            self.stat_labels[key] = lbl
        for i, lbl in enumerate(lbls):
            lbl.grid(row=0, column=i, sticky="w", padx=(0, 16))
        self.stat_frame.grid()

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, pady=(12, 0))
        self.btn_start = ctk.CTkButton(btns, text=_("btn_start"), fg_color=ACCENT, hover_color=ACCENT_HV,
                                       corner_radius=RADIUS, height=40, width=120,
                                       font=("Segoe UI", 13, "bold"),
                                       command=self._start_check)
        self.btn_start.pack(side="left", padx=3)
        self.btn_stop = ctk.CTkButton(btns, text=_("btn_stop"), fg_color=FIELD, hover_color="#ff4444",
                                      corner_radius=RADIUS, height=40, width=90,
                                      font=("Segoe UI", 13),
                                      command=self._stop_check, state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        self.btn_watch = ctk.CTkButton(btns, text="🔍 "+_("btn_watch_start"), fg_color=FIELD, hover_color=ACCENT_HV,
                                       corner_radius=RADIUS, height=40, width=120,
                                       font=("Segoe UI", 13),
                                       command=self._toggle_watch)
        self.btn_watch.pack(side="left", padx=3)
        self.watch_active = False
        self.watch_thread = None
        ctk.CTkButton(btns, text="📄 "+_("btn_results"), fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=40, width=120,
                      font=("Segoe UI", 13),
                      command=self._open_results_viewer).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="🌐 "+_("btn_webui"), fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=40, width=100,
                      font=("Segoe UI", 13),
                      command=self._toggle_webui).pack(side="left", padx=3)
        self.btn_tray = ctk.CTkButton(btns, text="🔽 Tray", fg_color=FIELD, hover_color=ACCENT_HV,
                                      corner_radius=RADIUS, height=40, width=90,
                                      font=("Segoe UI", 13),
                                      command=self._minimize_to_tray)
        self.btn_tray.pack(side="left", padx=3)
        # New tool buttons
        ctk.CTkButton(btns, text=_("btn_merge"), fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=40, width=90,
                      font=("Segoe UI", 13),
                      command=self._open_merge_tool).pack(side="left", padx=3)
        ctk.CTkButton(btns, text=_("btn_split"), fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=40, width=90,
                      font=("Segoe UI", 13),
                      command=self._open_splitter).pack(side="left", padx=3)
        ctk.CTkButton(btns, text=_("btn_help"), fg_color=FIELD, hover_color=ACCENT_HV,
                      corner_radius=RADIUS, height=40, width=90,
                      font=("Segoe UI", 13),
                      command=self._open_help).pack(side="left", padx=3)

    def _open_merge_tool(self):
        try:
            MergeTool(self)
        except Exception as e:
            messagebox.showerror("Error", f"Merge Tool: {e}")

    def _open_splitter(self):
        try:
            FileSplitter(self)
        except Exception as e:
            messagebox.showerror("Error", f"Splitter: {e}")

    def _open_help(self):
        try:
            HelpWindow(self)
        except Exception as e:
            messagebox.showerror("Error", f"Help: {e}")

    def _open_tutorial(self):
        try:
            TutorialOverlay(self)
        except Exception as e:
            messagebox.showerror("Error", f"Tutorial: {e}")

    def _open_results_viewer(self):
        out_dir = self.out_var.get()
        if not os.path.isdir(out_dir):
            messagebox.showerror("Ошибка", _("err_no_outdir"))
            return
        subdirs = [os.path.join(out_dir, d) for d in os.listdir(out_dir)
                   if os.path.isdir(os.path.join(out_dir, d))]
        if not subdirs:
            messagebox.showerror("Ошибка", _("err_no_results"))
            return
        latest = max(subdirs, key=os.path.getmtime)
        txt_files = sorted(f for f in os.listdir(latest) if f.endswith(".txt") and f != "report.txt")
        if not txt_files:
            messagebox.showerror("Ошибка", _("err_no_result_files"))
            return

        win = ctk.CTkToplevel(self)
        win.title(_("results_viewer_title"))
        win.geometry("900x650")
        win.focus()
        win.configure(fg_color=BG)

        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(top, text=_("results_file")+":", text_color=TEXT, font=FONT).pack(side="left", padx=(0, 5))
        file_var = ctk.StringVar(value=txt_files[0])
        file_menu = ctk.CTkOptionMenu(top, variable=file_var, values=txt_files,
                                      fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HV,
                                      dropdown_fg_color=FIELD, dropdown_hover_color=ACCENT,
                                      dropdown_text_color=TEXT, text_color=TEXT,
                                      corner_radius=RADIUS, font=FONT)
        file_menu.pack(side="left", padx=2)
        ctk.CTkLabel(top, text=_("results_search")+":", text_color=TEXT, font=FONT).pack(side="left", padx=(10, 5))
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(top, textvariable=search_var, placeholder_text=_("results_filter_placeholder"),
                                    fg_color=FIELD, border_width=0, corner_radius=RADIUS,
                                    height=32, font=FONT, text_color=TEXT)
        search_entry.pack(side="left", fill="x", expand=True, padx=2)

        text_frame = ctk.CTkFrame(win, fg_color=CARD, corner_radius=RADIUS)
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)
        textbox = ctk.CTkTextbox(text_frame, fg_color=CARD, text_color=TEXT, font=("Consolas", 11),
                                 wrap="none", state="disabled")
        textbox.pack(fill="both", expand=True, padx=2, pady=2)
        scroll_y = ctk.CTkScrollbar(text_frame, orientation="vertical", command=textbox.yview)
        scroll_y.pack(side="right", fill="y")
        textbox.configure(yscrollcommand=scroll_y.set)

        status_lbl = ctk.CTkLabel(win, text=f"{_('results_rows')}: 0 | {_('results_shown')}: 0", text_color=MUTED, font=FONT)
        status_lbl.pack(pady=(0, 6))

        MAX_VIEW_SIZE = 50 * 1024 * 1024  # 50 MB

        def load_file(*_args, _tr=_):
            path = os.path.join(latest, file_var.get())
            try:
                if os.path.getsize(path) > MAX_VIEW_SIZE:
                    lines = [f"[!] Файл слишком большой ({os.path.getsize(path)/(1024*1024):.0f} МБ). Показываю первые 10 000 строк.\n"]
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f):
                            if i >= 10000:
                                break
                            lines.append(line)
                else:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
            except Exception as e:
                lines = [f"Ошибка чтения: {e}"]
            textbox.configure(state="normal")
            textbox.delete("1.0", "end")
            filter_text = search_var.get().lower()
            shown = 0
            for line in lines:
                if filter_text and filter_text not in line.lower():
                    continue
                textbox.insert("end", line)
                shown += 1
            textbox.configure(state="disabled")
            status_lbl.configure(text=f"{_tr('results_rows')}: {len(lines)} | {_tr('results_shown')}: {shown}")

        search_var.trace_add("write", load_file)
        file_var.trace_add("write", load_file)
        load_file()

    def _toggle_webui(self):
        if self._webui_thread and self._webui_thread.is_alive():
            self._webui_thread.server.shutdown()
            self._webui_thread = None
            self._log("[!] Web UI остановлен")
            return
        if not WEBUI_AVAILABLE:
            self._log("[!] Web UI недоступен (нет http.server)")
            return
        port = self._webui_port
        app = self

        class WebUIHandler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                if path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(WEBUI_HTML.encode("utf-8"))
                elif path == "/api/status":
                    data = {"running": app.running, "progress": app.pb.get()*100,
                            "src": app.src_var.get(), "out": app.out_var.get(),
                            "mode": app.mode_var.get(), "queries": len(QUERIES_DATA)}
                    self._json(data)
                elif path == "/api/start":
                    if not app.running:
                        app.after(0, app._start_check)
                        self._json({"ok": True})
                    else:
                        self._json({"ok": False, "error": "already running"})
                elif path == "/api/stop":
                    if app.running:
                        app.after(0, app._stop_check)
                        self._json({"ok": True})
                    else:
                        self._json({"ok": False, "error": "not running"})
                elif path.startswith("/api/results"):
                    out_dir = app.out_var.get()
                    if os.path.isdir(out_dir):
                        subdirs = [os.path.join(out_dir, d) for d in os.listdir(out_dir)
                                   if os.path.isdir(os.path.join(out_dir, d))]
                        if subdirs:
                            latest = max(subdirs, key=os.path.getmtime)
                            txt_files = sorted(f for f in os.listdir(latest)
                                               if f.endswith(".txt") and f != "report.txt")
                            qs = urllib.parse.parse_qs(parsed.query)
                            fname = qs.get("file", [None])[0]
                            if fname and fname in txt_files:
                                try:
                                    fpath = os.path.join(latest, fname)
                                    size = os.path.getsize(fpath)
                                    max_bytes = 2 * 1024 * 1024
                                    truncated = size > max_bytes
                                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                                        content = f.read(max_bytes) if truncated else f.read()
                                    self._json({"files": txt_files, "file": fname, "content": content, "truncated": truncated})
                                except Exception as e:
                                    self._json({"error": str(e)})
                            else:
                                self._json({"files": txt_files, "file": None, "content": None})
                        else:
                            self._json({"files": []})
                    else:
                        self._json({"files": []})
                else:
                    self.send_response(404)
                    self.end_headers()
            def _json(self, data):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            def do_POST(self):
                self.do_GET()

        try:
            server = HTTPServer(("127.0.0.1", port), WebUIHandler)
            self._webui_thread = threading.Thread(target=server.serve_forever, daemon=True)
            self._webui_thread.server = server
            self._webui_thread.start()
            self._log(f"[+] Web UI: http://127.0.0.1:{port}")
        except Exception as e:
            self._log(f"[!] Web UI ошибка: {e}")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        if msg.startswith("[!]"):
            tag = "ERROR"
        elif msg.startswith("[✓]") or msg.startswith("[✔]"):
            tag = "OK"
        else:
            tag = "INFO"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] ", "ts")
        self.log_text.insert("end", msg + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


    def _start_check(self):
        if self.running:
            return

        src = self.src_var.get()
        if not src:
            messagebox.showerror("Ошибка", _("err_no_src"))
            return
        if not QUERIES_DATA:
            messagebox.showerror("Ошибка", _("err_no_queries"))
            return
        out_dir = self.out_var.get()
        mode = self.mode_var.get()
        # Фильтры – собираем из BooleanVar
        filters = {
            "exclude_empty": self.filter_exclude_empty.get(),
            "case_sensitive": self.filter_case_sensitive.get()
        }
        use_multiprocess = self.use_multiprocess_var.get()
        use_resume = self.use_resume_var.get()
        regex_mode = self.regex_var.get()
        use_unique_db = self.use_unique_db_var.get()
        default_save_full = self.default_save_full_var.get()
        split_size = self.split_var.get()
        delim = self.delim_var.get()
        delim_map = {"colon": b':', "semicolon": b';', "pipe": b'|', "tab": b'\t', "login": b'login', "password": b'password'}
        export_delim = delim_map.get(delim, b':')
        blacklist = [b.encode() for b in self._blacklist] if self._blacklist else None
        perf_mode = self.perf_mode_var.get()

        # Фильтрация запросов по выбранной группе
        active_group = self._group_rev.get(self.group_var.get(), "all")
        if active_group != "all" and active_group in QUERIES_GROUPS:
            group_queries = QUERIES_GROUPS[active_group]
            group_set = {q for q, _ in group_queries}
            active_queries_data = [(q, f) for q, f in QUERIES_DATA if q in group_set]
        else:
            active_queries_data = QUERIES_DATA
        if not active_queries_data:
            messagebox.showerror("Ошибка", _("err_group_empty"))
            return

        self.save_gui_settings()
        self.running = True
        self._done_received = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.pb.set(0)
        self.pct.configure(text="0%")
        if not use_resume:
            clear_checkpoint()
            if os.path.exists(STATE_FILE):
                try:
                    os.remove(STATE_FILE)
                except Exception:
                    pass
        self._log("[+] Запуск чека...")
        self.stop_flag.clear()

        self.worker_thread = threading.Thread(
            target=run_check,
            args=(src, active_queries_data, out_dir, mode, filters, use_multiprocess, use_resume,
                  self.ui_queue, self.stop_flag, regex_mode, blacklist, split_size,
                  export_delim, "dark", default_save_full, use_unique_db, perf_mode,
                  self.dry_run_var.get()),
            daemon=True
        )
        self.worker_thread.start()

    def _stop_check(self):
        if self.running:
            self.stop_flag.set()
            self._log("[!] Остановка — сохраняю результаты и остаток...")
            self.btn_stop.configure(state="disabled")

    def _poll_queue(self):
        try:
            for _ in range(500):
                kind, payload = self.ui_queue.get_nowait()
                if kind == "status":
                    self._log(payload)
                elif kind == "progress":
                    val = payload / 100.0
                    self.pb.set(val)
                    self.pct.configure(text=f"{int(payload)}%")
                    if hasattr(self, '_dash_cards') and self._dash_cards:
                        self._dash_cards["progress"].set(f"{int(payload)}%", "")
                elif kind == "stats":
                    self._update_stats(payload)
                    self._update_dashboard_stats(payload)
                elif kind == "success":
                    self._done_received = True
                    self._log(f"[✔] Успешно! Добавлено {payload['found']} строк, пропущено {payload['duplicates']} дублей")
                    self.running = False
                    self.stat_frame.grid_remove()
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    if self._in_tray:
                        tray_notify("URLmonster", f"Scan done: {payload['found']} new, {payload['duplicates']} dup")
                    else:
                        show_success_window(self, payload)
                elif kind == "done":
                    self._done_received = True
                    self.running = False
                    self.stat_frame.grid_remove()
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self._log("[+] Чек завершён")
                    if self._in_tray:
                        tray_notify("URLmonster", "Scan finished")
                elif kind == "watch_trigger":
                    if not self.running and self.watch_active:
                        self.use_resume_var.set(True)
                        self._start_check()
        except queue.Empty:
            pass
        if self.running:
            if self._done_received:
                self.running = False
                self.stat_frame.grid_remove()
                self.btn_start.configure(state="normal")
                self.btn_stop.configure(state="disabled")
            elif self.worker_thread and not self.worker_thread.is_alive():
                self.running = False
                self.stat_frame.grid_remove()
                self.btn_start.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                self._log("[!] Поток завершился неожиданно")
        self.after(100, self._poll_queue)

    def _update_stats(self, s):
        self.stat_frame.grid()
        self.stat_labels["speed"].configure(
            text=f"{_('stat_speed')}: {s['speed_mb']:.0f} МБ/с | {s['speed_lines']:,.0f} строк/с")
        self.stat_labels["found"].configure(
            text=f"{_('stat_found')}: {s['found']:,}")
        self.stat_labels["eta"].configure(
            text=f"{_('stat_eta')}: ~{s['eta']}")
        self.stat_labels["files"].configure(
            text=f"{_('stat_files')}: {s['files_done']}/{s['files_total']}")
        self.stat_labels["elapsed"].configure(
            text=f"{_('stat_elapsed')}: {s['elapsed']}")

    def _update_dashboard_stats(self, s):
        if not hasattr(self, '_dash_cards'):
            return
        self._dash_cards["speed_mb"].set(f"{s['speed_mb']:.1f}", "МБ/с")
        self._dash_cards["speed_lines"].set(f"{s['speed_lines']:,.0f}", "строк/с")
        self._dash_cards["found"].set(f"{s['found']:,}", "")
        self._dash_cards["files"].set(f"{s['files_done']}/{s['files_total']}", "")
        self._dash_cards["eta"].set(f"~{s['eta']}", "")
        self._dash_cards["elapsed"].set(s['elapsed'], "")


    def on_closing(self):
        if TRAY_AVAILABLE:
            self._minimize_to_tray()
        else:
            self.stop_flag.set()
            self.save_gui_settings()
            self.destroy()

    def _check_minimize(self):
        if self.wm_state() == "iconic" and TRAY_AVAILABLE and not self._in_tray:
            self._minimize_to_tray()

    def _tray_callback(self, action):
        if action == "show":
            self._toggle_tray_show()
        elif action == "menu":
            self._tray_show_menu()

    def _tray_show_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Show/Hide", command=self._toggle_tray_show)
        menu.add_command(label="Start", command=self._tray_start)
        menu.add_command(label="Stop", command=self._tray_stop)
        menu.add_separator()
        menu.add_command(label="Quit", command=self._tray_quit)
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _setup_tray(self):
        if not TRAY_AVAILABLE or self._tray_icon:
            return
        self._tray_icon = True
        tray_setup(self._tray_callback)

    def _minimize_to_tray(self):
        self._in_tray = True
        self.withdraw()
        if not self._tray_icon:
            self._setup_tray()
        if self._tray_icon:
            tray_notify("URLmonster", "URLmonster свёрнут в трей. Двойной клик — показать.")

    def _toggle_tray_show(self):
        if self._in_tray:
            self.after(0, self.deiconify)
            self.after(0, self.lift)
            self.after(0, self.focus)
            self._in_tray = False
        else:
            self.after(0, self._minimize_to_tray)

    def _tray_start(self):
        self.after(0, self._start_check)

    def _tray_stop(self):
        self.after(0, self._stop_check)

    def _tray_quit(self):
        self.stop_flag.set()
        self.after(0, self.save_gui_settings)
        tray_remove()
        self.after(0, self.destroy)
        self.after(100, sys.exit)

# ============================================================
#  ЗАПУСК
# ============================================================

def main():
    global QUERIES_DATA
    settings = load_settings()
    QUERIES_DATA = load_queries_from_file() or settings.get("queries_data", [])
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

if __name__ == "__main__":
    mp.freeze_support()
    if len(sys.argv) > 1:
        main_cli()
    else:
        main()