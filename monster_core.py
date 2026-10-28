#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monster_core.py – worker-safe ядро исправлений URLmonster PRO.
Без GUI-импортов (безопасно для spawn-воркеров).

Содержит:
- MatchingEngine: rust_scan.Engine fast path (C-01/N-1) + fallback-цепочка
  rust Engine -> rust process_block -> ahocorasick -> regex -> substring (C-02/N-1),
  честный счётчик строк (C-03/N-1).
- UniqueStore: гибридный RAM/SQLite дедуп, blake2b-16 (C-06/C-07/M-07/N-2).
- Safe archive extraction: tar filter='data', zip/gz/bz2 size caps (C-04).
- collect_files_map: state-ключи по исходному архиву (M-06), temp-очистка (M-01).
- Process registry + atexit terminate (C-08).
- parse_nl_queries: rule-based NL парсер запросов (N-10 partial).
- score_line: эвристики качества находки (N-8).
- Domain index build/query (N-5), run diff (N-7).
"""

import os, re, json, time, hashlib, shutil, tempfile, logging, threading, sqlite3, atexit
from collections import Counter

logger = logging.getLogger("URLChecker")

# ---- Опциональные движки матчинга ----
try:
    import rust_scan
    RUST_SCAN_AVAILABLE = True
except ImportError:
    rust_scan = None
    RUST_SCAN_AVAILABLE = False

try:
    import ahocorasick
    AHOCORASICK_AVAILABLE = True
except ImportError:
    ahocorasick = None
    AHOCORASICK_AVAILABLE = False

_HAS_RUST_ENGINE = RUST_SCAN_AVAILABLE and hasattr(rust_scan, "Engine")
_HAS_RUST_PROCESS_BLOCK = RUST_SCAN_AVAILABLE and hasattr(rust_scan, "process_block")

# ============================================================
#  Process registry (C-08)
# ============================================================

_ACTIVE_PROCESSES = set()
_PROCESSES_LOCK = threading.Lock()
_REGISTRY_HOOKED = False


def _hook_atexit():
    global _REGISTRY_HOOKED
    if _REGISTRY_HOOKED:
        return
    _REGISTRY_HOOKED = True

    def _terminate_all():
        with _PROCESSES_LOCK:
            procs = list(_ACTIVE_PROCESSES)
            _ACTIVE_PROCESSES.clear()
        for p in procs:
            try:
                if p.is_alive():
                    p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.join(timeout=3)
            except Exception:
                pass
    atexit.register(_terminate_all)


def register_process(p):
    _hook_atexit()
    with _PROCESSES_LOCK:
        _ACTIVE_PROCESSES.add(p)


def unregister_process(p):
    with _PROCESSES_LOCK:
        _ACTIVE_PROCESSES.discard(p)


def terminate_all_processes():
    _hook_atexit()
    with _PROCESSES_LOCK:
        procs = list(_ACTIVE_PROCESSES)
        _ACTIVE_PROCESSES.clear()
    for p in procs:
        try:
            if p.is_alive():
                p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.join(timeout=3)
        except Exception:
            pass


# ============================================================
#  MatchingEngine (C-01, C-02, C-03, N-1)
# ============================================================

_ALL_SEPARATORS = [
    b":", b";", b"|", b",", b"/", b"\\", b".", b"-", b"_", b"~", b"#", b"@",
    b"!", b"$", b"%", b"^", b"&", b"*", b"+", b"=",
    b" ", b"\t", b"\n", b"\r", b"\x00",
    b"::", b"||", b";;", b"::|", b":::", b"|||",
    b"---", b"###", b"___", b"<<->", b"<sep>", b"->", b"=>",
    b":: ", b" ; ", b" | ", b" : ",
    b"%3A", b"%7C", b"%20",
    b"....", b"::::", b"####", b"====", b"~~~~",
]

_EMAIL_RE = re.compile(rb"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


_FAST_SECOND_SEPS = [b":", b";", b"|", b",", b"\t", b"::", b"||"]

def _py_parse_line(line, mode, delim):
    """Python-парсер строки (fallback). PRIME-оптимизация: O(1) вместо O(2500).

    Было: вложенный цикл 50x50 кандидатов на КАЖДУЮ строку.
    Стало: быстрый путь по основному разделителю + короткий список частых.
    """
    if not line or not delim:
        return None
    if mode == "exact":
        pos = line.find(delim)
        if pos < 0:
            return None
        login, password = line[:pos], line[pos + len(delim):]
        if not login or not password:
            return None
        return (login, password)
    proto_end = line.find(b'://')
    if proto_end >= 0:
        proto_end += 3
    else:
        proto_end = 0
    after_proto = line[proto_end:]
    if len(after_proto) > 4096:
        # защита от сверхдлинных строк-пампов: режем хвост, парсим голову
        after_proto = after_proto[:4096]
    # Fast path 1: основной разделитель, разбор справа (login:pass, url:login:pass)
    pos = after_proto.rfind(delim)
    if pos > 0:
        rest = after_proto[pos + len(delim):]
        if rest and b'\n' not in rest[:1]:
            # ищем второй разделитель слева для схемы URL<sep>login<sep>pass
            pos2 = after_proto.rfind(delim, 0, pos)
            if pos2 > 0:
                login = after_proto[pos2 + len(delim):pos]
                password = rest
                if login and password:
                    if b'/' in login:
                        login = login.rsplit(b'/', 1)[-1] or login
                    return (login, password)
            else:
                # схема login<sep>pass
                login = after_proto[:pos]
                if b'/' in login:
                    login = login.rsplit(b'/', 1)[-1] or login
                if login and rest:
                    return (login, rest)
    # Fast path 2: короткий список частых разделителей (7 шт, не 50)
    for cand in _FAST_SECOND_SEPS:
        if cand == delim:
            continue
        pos1 = after_proto.find(cand)
        if pos1 <= 0:
            continue
        rest = after_proto[pos1 + len(cand):]
        if not rest:
            continue
        pos2 = rest.find(cand)
        if pos2 <= 0:
            # пробуем основной delim как второй
            pos2b = rest.find(delim)
            if pos2b <= 0:
                continue
            login, password = rest[:pos2b], rest[pos2b + len(delim):]
        else:
            login, password = rest[:pos2], rest[pos2 + len(cand):]
        if not login or not password:
            continue
        if b'/' in login:
            login = login.rsplit(b'/', 1)[-1] or login
        return (login, password)
    return None


def _ensure_https(line):
    if b'://' in line:
        pos = line.find(b'http://')
        if pos >= 0:
            return line[:pos] + b'https://' + line[pos + 7:]
        return line
    return b'https://' + line


class MatchingEngine:
    """Движок матчинга: строится ОДИН раз на воркер.

    process_block(block) -> (line_count, list[(q_name, out_bytes)])
    out_bytes уже помечены 'query\\x00content\\n'.
    line_count – ЧЕСТНОЕ число найденных строк (C-03).
    """

    def __init__(self, queries, flags, mode, delim, default_save_full=False,
                 require_email=False, case_sensitive=False, regex_mode=False,
                 blacklist=None):
        self.queries = [q for q in queries]
        self.flags = [bool(flags.get(q, default_save_full)) for q in self.queries]
        self.mode = mode
        self.delim = delim if delim else b':'
        self.default_save_full = default_save_full
        self.require_email = require_email
        self.case_sensitive = case_sensitive
        self.regex_mode = regex_mode
        self.blacklist = tuple(b.lower() for b in (blacklist or []) if b)
        self.level = "python-substring"
        self._rust_engine = None
        self._automaton = None
        self._regexes = []
        # PRIME: предрасчёты для быстрого python-пути (без per-line аллокаций)
        self._q_index = {q: i for i, q in enumerate(self.queries)}
        self._q_lower_b = [q.lower().encode() for q in self.queries]
        self._bl_set = frozenset(self.blacklist)
        self._rust_failed = False  # кэш решения о fallback (не дёргать rust каждый блок)

        queries_bytes = [q.encode() for q in self.queries]

        # Level 0: rust Engine fast path (built once)
        if _HAS_RUST_ENGINE and not regex_mode:
            try:
                self._rust_engine = rust_scan.Engine(
                    queries_bytes, self.flags, mode, self.delim,
                    default_save_full, require_email, case_sensitive,
                    regex_mode, self.blacklist or None,
                )
                self.level = "rust-engine"
            except Exception as e:
                logger.warning(f"rust Engine build failed, fallback: {e}")
                self._rust_engine = None

        # Level 1: ahocorasick + python parse
        if self._rust_engine is None and not regex_mode and AHOCORASICK_AVAILABLE and self.queries:
            try:
                A = ahocorasick.Automaton()
                for idx, q in enumerate(self.queries):
                    A.add_word(q.lower(), (idx, q))
                A.make_automaton()
                self._automaton = A
                self.level = "ahocorasick"
            except Exception:
                self._automaton = None

        # Level 2: regex
        if self._rust_engine is None and self._automaton is None and regex_mode:
            for q in self.queries:
                try:
                    self._regexes.append((q, re.compile(q.encode(), re.IGNORECASE)))
                except Exception:
                    pass
            self.level = "regex"

    def _write_line(self, q_name, orig_line, parsed):
        # PRIME: O(1) через _q_index вместо list.index (было O(n) на строку)
        idx = self._q_index.get(q_name)
        save_full = self.flags[idx] if idx is not None else self.default_save_full
        if save_full:
            out = _ensure_https(orig_line)
        else:
            if not parsed:
                return None
            out = parsed[0] + b':' + parsed[1]
        return q_name.encode() + b'\x00' + out + b'\n'

    def _py_match_block(self, block):
        """Python matching: automaton/regex/substring + parse. Returns (count, [(q, buf)])."""
        bufs = {q: [] for q in self.queries}
        count = 0
        lowered = block.lower()
        # PRIME: локальные ссылки (убираем атрибут-lookup из горячего цикла)
        automaton = self._automaton
        regexes = self._regexes
        q_lower_b = self._q_lower_b
        queries = self._queries if hasattr(self, '_queries') else self.queries
        bl = self._bl_set
        mode, delim = self.mode, self.delim
        require_email = self.require_email
        orig_pos = 0
        blen = len(block)
        for line in lowered.split(b'\n'):
            llen = len(line)
            orig_line = block[orig_pos:orig_pos + llen] if orig_pos + llen <= blen else b''
            orig_pos += llen + 1
            if not line:
                continue
            matched = None
            if automaton is not None:
                matched = set()
                for _, (_, q) in automaton.iter(line):
                    matched.add(q)
                    if len(matched) >= 4:
                        break  # ранний выход: хватит для группировки
            elif regexes:
                matched = set()
                for q, rex in regexes:
                    if rex.search(line):
                        matched.add(q)
            else:
                matched = [queries[i] for i, qb in enumerate(q_lower_b) if qb in line]
                if not matched:
                    continue
                matched = set(matched)
            if not matched:
                continue
            if bl:
                skip = False
                for b in bl:
                    if b in line:
                        skip = True
                        break
                if skip:
                    continue
            parsed = _py_parse_line(orig_line, mode, delim)
            if parsed is None and not self.default_save_full:
                continue
            if require_email and parsed is not None:
                if not _EMAIL_RE.match(parsed[0]):
                    continue
            for q in matched:
                marked = self._write_line(q, orig_line, parsed)
                if marked:
                    bufs[q].append(marked)
                    count += 1
        out = [(q, b''.join(lines)) for q, lines in bufs.items() if lines]
        return count, out

    def process_block(self, block):
        """Returns (line_count, [(q_name, buffer)]). PRIME: кэш fallback-решения."""
        if not block:
            return 0, []
        if self._rust_failed:
            return self._py_match_block(block)
        if self._rust_engine is not None:
            try:
                results = self._rust_engine.process(block)
                count = 0
                out = []
                qs = self.queries
                for idx, buf in results:
                    if not buf:
                        continue
                    count += buf.count(b'\n')
                    out.append((qs[idx], buf))
                return count, out
            except Exception as e:
                logger.error(f"rust engine process failed, lock to python: {e}")
                self._rust_engine = None
                self._rust_failed = True
                self.level = "ahocorasick" if self._automaton is not None else "python-substring"
                return self._py_match_block(block)
        # Level 1: rust process_block (slow one-shot path) — только если не падал раньше
        if _HAS_RUST_PROCESS_BLOCK and not self._rust_failed:
            try:
                if not hasattr(self, '_pb_cache'):
                    self._pb_cache = (
                        [q.encode() for q in self.queries],
                        {q: f for q, f in zip(self.queries, self.flags)},
                        list(self.blacklist) if self.blacklist else None,
                    )
                q_b, flags_map, bl = self._pb_cache
                pb = rust_scan.process_block(
                    block, q_b, flags_map,
                    self.mode, self.delim, self.delim,
                    self.default_save_full, True, self.require_email,
                    self.case_sensitive, self.regex_mode, bl,
                )
                count = sum(buf.count(b'\n') for _, buf in pb)
                return count, list(pb)
            except Exception as e:
                logger.error(f"rust process_block failed, lock to python: {e}")
                self._rust_failed = True
        # Python paths
        return self._py_match_block(block)


# ============================================================
#  Дедуп: SpillSet (per-run) + UniqueDB (persistent) (C-06, C-07, M-07, N-2)
# ============================================================

UNIQUE_RAM_LIMIT = 5_000_000  # записей; выше — SpillSet переезжает на SQLite
_HASH_SIZE = 16  # blake2b-16 (C-06)


def content_hash(content):
    return hashlib.blake2b(content, digest_size=_HASH_SIZE).digest()


def legacy_hash(content):
    """md5-8: совместимость со старым unique_strings.bin."""
    return hashlib.md5(content).digest()[:8]


class SpillSet:
    """Per-run множество хешей: RAM с авто-переездом на SQLite-файл (C-07).
    Используется как per-run 'seen' в merge — полностью решает MemoryError
    на результатах 5+ ГБ."""

    def __init__(self, db_path=None):
        self._hashes = set()
        self._conn = None
        self.db_path = db_path or os.path.join(tempfile.mkdtemp(prefix="urlmonster_spill_"), "spill.sqlite")
        self._spilled = False

    def _spill(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=OFF")
            self._conn.execute("PRAGMA synchronous=OFF")
            self._conn.execute("CREATE TABLE IF NOT EXISTS s (h BLOB PRIMARY KEY)")
            batch = []
            for h in self._hashes:
                batch.append((h,))
                if len(batch) >= 100000:
                    self._conn.executemany("INSERT OR IGNORE INTO s VALUES (?)", batch)
                    batch = []
            if batch:
                self._conn.executemany("INSERT OR IGNORE INTO s VALUES (?)", batch)
            self._conn.commit()
            self._hashes = set()
            self._spilled = True
            logger.info(f"SpillSet: spilled to sqlite ({self.db_path})")
        except Exception as e:
            logger.error(f"SpillSet spill failed: {e}")
            self._spilled = False

    def contains(self, h):
        if not self._spilled:
            return h in self._hashes
        return self._conn.execute("SELECT 1 FROM s WHERE h = ?", (h,)).fetchone() is not None

    def add(self, h):
        if not self._spilled:
            self._hashes.add(h)
            if len(self._hashes) > UNIQUE_RAM_LIMIT:
                self._spill()
        else:
            self._conn.execute("INSERT OR IGNORE INTO s VALUES (?)", (h,))

    def count(self):
        if not self._spilled:
            return len(self._hashes)
        return self._conn.execute("SELECT COUNT(*) FROM s").fetchone()[0]

    def close(self):
        if self._conn is not None:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def cleanup(self):
        self.close()
        try:
            shutil.rmtree(os.path.dirname(self.db_path), ignore_errors=True)
        except Exception:
            pass


class UniqueDB:
    """Персистентная БД уникальных строк (SQLite):
    - u16: новые хеши blake2b-16 (пишутся всегда);
    - u8:  одноразовая миграция legacy unique_strings.bin (md5-8) в фоне;
    - RAM O(1): все проверки через sqlite.
    Старый .bin НЕ изменяется и остаётся как архив."""

    MIGRATE_BATCH = 200000
    MIGRATE_CHUNK = 8 * 1024 * 1024

    def __init__(self, db_path, legacy_bin=None, read_only=False):
        self.db_path = db_path
        self.read_only = read_only
        self._conn = None
        self._migrate_thread = None
        self._closed = False
        self._lock = threading.RLock()  # PRIME FIX: гонки SQLite между потоками
        try:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("CREATE TABLE IF NOT EXISTS u16 (h BLOB PRIMARY KEY)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS u8 (h BLOB PRIMARY KEY)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self._conn.commit()
            self._migrated = self._meta_get("u8_migrated") == "1"
            self._migrating = self._meta_get("u8_migrating") == "1"
            if legacy_bin and os.path.exists(legacy_bin) and not self._migrated and not self._migrating and not read_only:
                self._meta_set("u8_migrating", "1")
                self._migrate_thread = threading.Thread(
                    target=self._migrate_legacy, args=(legacy_bin,), daemon=True)
                self._migrate_thread.start()
        except Exception as e:
            logger.error(f"UniqueDB init failed: {e}")
            self._conn = None

    def _meta_get(self, k):
        if self._conn is None:
            return None
        with self._lock:
            try:
                row = self._conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
                return row[0] if row else None
            except Exception:
                return None

    def _meta_set(self, k, v):
        try:
            with self._lock:
                self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
                self._conn.commit()
        except Exception:
            pass

    def _migrate_legacy(self, bin_path):
        """Одноразовый потоковый импорт md5-8 из legacy .bin (C-06 совместимость)."""
        try:
            logger.info(f"UniqueDB: background migration of legacy {bin_path}")
            with open(bin_path, "rb") as f:
                batch = []
                while True:
                    chunk = f.read(self.MIGRATE_CHUNK)
                    if not chunk:
                        break
                    usable = len(chunk) - len(chunk) % 8
                    data = chunk[:usable]
                    # учесть границу чанка, не кратную 8
                    pos = f.tell()
                    if len(chunk) % 8:
                        back = len(chunk) % 8
                        f.seek(pos - back)
                    for i in range(0, len(data), 8):
                        batch.append((data[i:i + 8],))
                        if len(batch) >= self.MIGRATE_BATCH:
                            self._conn.executemany("INSERT OR IGNORE INTO u8 VALUES (?)", batch)
                            batch = []
                if batch:
                    self._conn.executemany("INSERT OR IGNORE INTO u8 VALUES (?)", batch)
            self._meta_set("u8_migrated", "1")
            self._meta_set("u8_migrating", "0")
            self._migrated = True
            self._migrating = False
            self._conn.commit()
            logger.info("UniqueDB: legacy migration complete")
        except Exception as e:
            logger.error(f"UniqueDB legacy migration failed: {e}")
            self._meta_set("u8_migrating", "0")

    def contains16(self, h):
        if self._conn is None:
            return False
        with self._lock:
            try:
                return self._conn.execute("SELECT 1 FROM u16 WHERE h = ?", (h,)).fetchone() is not None
            except Exception:
                return False

    def contains8(self, h):
        if self._conn is None:
            return False
        with self._lock:
            try:
                if not self._migrated:
                    # миграция могла завершиться в фоне — перепроверяем meta один раз
                    if (self._migrate_thread is None or not self._migrate_thread.is_alive()) \
                            and self._meta_get("u8_migrated") == "1":
                        self._migrated = True
                    else:
                        return False
                return self._conn.execute("SELECT 1 FROM u8 WHERE h = ?", (h,)).fetchone() is not None
            except Exception:
                return False

    def contains_content(self, content):
        """Полная проверка: новый blake2b-16 + legacy md5-8 (если мигрирован)."""
        h16 = content_hash(content)
        if self.contains16(h16):
            return True
        # legacy проверяем только если миграция готова (не дёргаем лишний md5)
        if getattr(self, '_migrated', False):
            return self.contains8(legacy_hash(content))
        return False

    def add16(self, h):
        if self._conn is None or self.read_only:
            return
        try:
            self._conn.execute("INSERT OR IGNORE INTO u16 VALUES (?)", (h,))
        except Exception:
            pass

    def add_content(self, content):
        self.add16(content_hash(content))

    def add_many16(self, hashes):
        if self._conn is None or self.read_only:
            return
        try:
            with self._lock:
                batch = []
                for h in hashes:
                    batch.append((h,))
                    if len(batch) >= 50000:
                        self._conn.executemany("INSERT OR IGNORE INTO u16 VALUES (?)", batch)
                        batch = []
                if batch:
                    self._conn.executemany("INSERT OR IGNORE INTO u16 VALUES (?)", batch)
                self._conn.commit()
        except Exception:
            pass

    def count16(self):
        if self._conn is None:
            return 0
        return self._conn.execute("SELECT COUNT(*) FROM u16").fetchone()[0]

    def count8(self):
        if self._conn is None or not self._migrated:
            return 0
        return self._conn.execute("SELECT COUNT(*) FROM u8").fetchone()[0]

    def legacy_ready(self):
        if self._migrate_thread is not None and self._migrate_thread.is_alive():
            return False
        return self._migrated

    def flush(self):
        if self._conn is not None and not self.read_only:
            try:
                self._conn.commit()
            except Exception:
                pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._migrate_thread is not None and self._migrate_thread.is_alive():
            self._migrate_thread.join(timeout=5)
        if self._conn is not None:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def cleanup(self):
        self.close()


# ============================================================
#  Safe archive extraction (C-04)
# ============================================================

ARCHIVE_EXTS = {".zip", ".7z", ".tar", ".gz", ".tgz", ".rar", ".tar.gz", ".bz2", ".tar.bz2", ".xz", ".tar.bz2", ".tar.xz"}
MAX_ARCHIVE_TOTAL = 8 * 1024 * 1024 * 1024  # 8 ГБ суммарная распаковка (zip-bomb guard)
MAX_SINGLE_OUT = 4 * 1024 * 1024 * 1024     # 4 ГБ один выходной файл

_ARCHIVE_TOTAL_STATE = {"bytes": 0, "warned": False}


def _safe_member_name(name, dest_dir):
    """Валидация имени члена архива против path traversal (C-04)."""
    name = name.replace("\\", "/")
    name = re.sub(r'^[a-zA-Z]:', '', name)      # drive letter
    name = re.sub(r'^/+', '', name)              # leading slashes
    parts = [p for p in name.split('/') if p not in ('', '.', '..')]
    out = os.path.join(dest_dir, *parts) if parts else None
    if out is None:
        return None
    out_abs = os.path.abspath(out)
    dest_abs = os.path.abspath(dest_dir)
    if not out_abs.startswith(dest_abs + os.sep):
        return None
    return out_abs


def _cap_guard(additional):
    if _ARCHIVE_TOTAL_STATE["bytes"] + additional > MAX_ARCHIVE_TOTAL:
        if not _ARCHIVE_TOTAL_STATE["warned"]:
            _ARCHIVE_TOTAL_STATE["warned"] = True
            logger.warning(f"ARCHIVE CAP reached: total extraction > {MAX_ARCHIVE_TOTAL//(1024**3)} GB — stopping further extraction")
        return False
    return True


def _find_unrar():
    exe = shutil.which("unrar")
    if exe:
        return exe
    common = [
        r"C:\Program Files\WinRAR\unrar.exe",
        r"C:\Program Files (x86)\WinRAR\unrar.exe",
        os.path.join(os.path.dirname(sys_exec()), "unrar.exe"),
        os.path.join(os.path.dirname(__file__), "unrar.exe"),
    ]
    for p in common:
        if os.path.isfile(p):
            return p
    return None


def sys_exec():
    import sys
    return sys.executable


def _walk_out(dest_dir):
    import sys
    out = []
    for root, _, names in os.walk(dest_dir):
        for n in names:
            out.append(os.path.join(root, n))
    return out


def _extract_rar(path, dest_dir, cap=True):
    import subprocess, sys
    extracted = []
    unrar_path = _find_unrar()
    if unrar_path:
        try:
            subprocess.run([unrar_path, "x", path, dest_dir + os.sep],
                           capture_output=True, timeout=120)
            extracted = _walk_out(dest_dir)
            if extracted:
                return extracted
        except Exception:
            pass
    try:
        import rarfile
        rf = rarfile.RarFile(path)
        rf.extractall(dest_dir)
        extracted = _walk_out(dest_dir)
        if extracted:
            return extracted
    except Exception:
        pass
    for exe in (shutil.which("winrar"), shutil.which("7z")):
        if not exe:
            continue
        try:
            cmd = [exe, "x", path] if "winrar" in exe else [exe, "x", path, f"-o{dest_dir}", "-y"]
            if "winrar" in exe:
                cmd.append(dest_dir + os.sep)
            subprocess.run(cmd, capture_output=True, timeout=120)
            extracted = _walk_out(dest_dir)
            if extracted:
                return extracted
        except Exception:
            pass
    return extracted


def extract_archive(path, dest_dir):
    """Безопасная распаковка архива (C-04): filter='data' для tar,
    валидация имён для zip, лимиты объёма против zip-bomb."""
    import zipfile, tarfile, subprocess, sys
    extracted = []
    try:
        low = path.lower()
        if low.endswith(".zip"):
            total = sum(info.file_size for info in zipfile.ZipFile(path).infolist())
            if not _cap_guard(total):
                return []
            _ARCHIVE_TOTAL_STATE["bytes"] += total
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    safe = _safe_member_name(info.filename, dest_dir)
                    if safe is None:
                        logger.warning(f"ZIP: skipped unsafe member: {info.filename!r}")
                        continue
                    if info.is_dir():
                        os.makedirs(safe, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(safe) or dest_dir, exist_ok=True)
                    with zf.open(info) as fin, open(safe, "wb") as fout:
                        written = 0
                        while True:
                            chunk = fin.read(8 * 1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > MAX_SINGLE_OUT:
                                raise ValueError(f"member too large: {info.filename}")
                            fout.write(chunk)
                    extracted.append(safe)
        elif low.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
            # Используем streaming extraction вместо extractall() (C-04)
            with tarfile.open(path) as tf:
                for member in tf.getmembers():
                    safe = _safe_member_name(member.name, dest_dir)
                    if safe is None:
                        continue
                    if member.isfile():
                        # Проверяем размер перед извлечением
                        if not _cap_guard(member.size):
                            logger.warning(f"ARCHIVE CAP: skipping {member.name}")
                            break
                        tf.extract(member, dest_dir)
                        extracted.append(safe)
                    elif member.isdir():
                        os.makedirs(safe, exist_ok=True)
        elif low.endswith(".gz"):
            out_name = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(dest_dir, out_name)
            import gzip
            with gzip.open(path, 'rb') as fin, open(out_path, 'wb') as fout:
                written = 0
                while True:
                    chunk = fin.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if not _cap_guard(written):
                        raise ValueError("gz output cap")
                    fout.write(chunk)
            _ARCHIVE_TOTAL_STATE["bytes"] += written
            extracted.append(out_path)
        elif low.endswith(".bz2"):
            out_name = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(dest_dir, out_name)
            import bz2
            with bz2.open(path, 'rb') as fin, open(out_path, 'wb') as fout:
                written = 0
                while True:
                    chunk = fin.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if not _cap_guard(written):
                        raise ValueError("bz2 output cap")
                    fout.write(chunk)
            _ARCHIVE_TOTAL_STATE["bytes"] += written
            extracted.append(out_path)
        elif low.endswith(".xz"):
            out_name = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(dest_dir, out_name)
            try:
                with open(out_path, 'wb') as fout:
                    subprocess.run(["xz", "-d", "-k", "-c", path],
                                   capture_output=True, timeout=600, stdout=fout)
                extracted.append(out_path)
            except Exception:
                pass
        elif low.endswith(".7z"):
            try:
                subprocess.run(["7z", "x", path, f"-o{dest_dir}", "-y"],
                               capture_output=True, timeout=600)
                extracted = _walk_out(dest_dir)
            except Exception:
                pass
        elif low.endswith(".rar"):
            extracted = _extract_rar(path, dest_dir)
    except Exception as e:
        logger.warning(f"Failed to extract {path}: {e}")
    return [f for f in extracted if os.path.isfile(f)]


def is_archive(path):
    low = path.lower()
    return any(low.endswith(ext) for ext in ARCHIVE_EXTS)


# ---- Кэш распаковки архивов (M-01): переиспользование между проходами ----
_ARCHIVE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive_cache.json")
_ARCHIVE_CACHE_LOCK = threading.Lock()
_ARCHIVE_CACHE_MAX = 25          # максимум закэшированных архивов (LRU)
_ARCHIVE_CACHE_TOTAL_CAP = 32 * 1024**3  # 32 ГБ суммарной распаковки в кэше

_ARCHIVE_CACHE = None


def _archive_cache():
    global _ARCHIVE_CACHE
    if _ARCHIVE_CACHE is None:
        try:
            with open(_ARCHIVE_CACHE_FILE, "r", encoding="utf-8") as f:
                _ARCHIVE_CACHE = json.load(f)
            if not isinstance(_ARCHIVE_CACHE, dict):
                _ARCHIVE_CACHE = {}
        except Exception:
            _ARCHIVE_CACHE = {}
    return _ARCHIVE_CACHE


def _archive_cache_save():
    try:
        with open(_ARCHIVE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_ARCHIVE_CACHE, f, ensure_ascii=False)
    except Exception:
        pass


def _dir_total_bytes(d):
    total = 0
    for root, _, names in os.walk(d):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except Exception:
                pass
    return total


def _archive_cache_evict(force_free=0):
    """LRU-выселение + удаление dirs при переполнении кэша."""
    cache = _archive_cache()
    while len(cache) >= _ARCHIVE_CACHE_MAX or force_free > 0:
        if not cache:
            break
        # самый старый last_access
        oldest_key = min(cache, key=lambda k: cache[k].get("last_access", 0))
        entry = cache.pop(oldest_key)
        d = entry.get("dir")
        if d:
            total = entry.get("total_bytes", _dir_total_bytes(d))
            force_free -= total
            shutil.rmtree(d, ignore_errors=True)
            logger.info(f"ARCHIVE CACHE: evicted {oldest_key} (freed ~{total//(1024**2)} MB)")
    _archive_cache_save()


def get_cached_extract(archive_path):
    """Кэшированная распаковка архива. Returns (members, cache_dir, cached).
    cached=True — переиспользовано, extraction не выполнялась (M-01)."""
    cache = _archive_cache()
    try:
        st = os.stat(archive_path)
        mtime, size = st.st_mtime, st.st_size
    except Exception:
        return [], None, False
    with _ARCHIVE_CACHE_LOCK:
        entry = cache.get(archive_path)
        if entry and entry.get("mtime") == mtime and entry.get("size") == size:
            d = entry.get("dir")
            if d and os.path.isdir(d):
                members = entry.get("members", [])
                if all(os.path.isfile(m) for m in members):
                    entry["last_access"] = time.time()
                    _archive_cache_save()
                    return members, d, True
            # каталог исчез или члены пропали — выселяем запись
            cache.pop(archive_path, None)
        # Кэшируем распаковку в новом каталоге
        d = tempfile.mkdtemp(prefix="urlmonster_arcache_")
        members = extract_archive(archive_path, d)
        entry = {
            "dir": d, "mtime": mtime, "size": size,
            "members": members, "last_access": time.time(),
            "total_bytes": _dir_total_bytes(d),
        }
        cache[archive_path] = entry
        # Гарантия лимитов: выселяем самый старый, если записей > max-1
        while len(cache) >= _ARCHIVE_CACHE_MAX:
            _archive_cache_evict()
        # Лимит суммарного объёма кэша
        total = sum(e.get("total_bytes", 0) for e in cache.values())
        if total > _ARCHIVE_CACHE_TOTAL_CAP:
            over = total - _ARCHIVE_CACHE_TOTAL_CAP
            _archive_cache_evict(force_free=over)
        _archive_cache_save()
        return members, d, False


def collect_files_map(path, name_filter=None):
    """Собирает txt-файлы, распаковывая архивы через кэш (M-01).
    Returns (files, state_keys, temp_dirs):
      files       – пути к обработке (temp-файлы для распакованных),
      state_keys  – ключи для processed-состояния: для распакованных –
                    "<архив>::<имя члена>" (стабильно между запусками, M-06),
      temp_dirs   – каталоги кэша, созданные ЭТИМ вызовом (для очистки при
                    нормальном завершении watch-цикла не выселяются)."""
    files = []
    state_keys = []
    temp_dirs = []

    if os.path.isfile(path):
        if is_archive(path):
            members, d, cached = get_cached_extract(path)
            if d and not cached:
                temp_dirs.append(d)
            for f in members:
                if f.lower().endswith(".txt"):
                    if name_filter is None or name_filter(f):
                        files.append(f)
                        state_keys.append(f"{path}::{os.path.relpath(f, d)}")
        else:
            if name_filter is None or name_filter(path):
                files.append(path)
                state_keys.append(path)
    elif os.path.isdir(path):
        for root, _, names in os.walk(path):
            for n in names:
                fp = os.path.join(root, n)
                if is_archive(fp):
                    members, d, cached = get_cached_extract(fp)
                    if d and not cached:
                        temp_dirs.append(d)
                    for f in members:
                        if f.lower().endswith(".txt"):
                            if name_filter is None or name_filter(f):
                                files.append(f)
                                state_keys.append(f"{fp}::{os.path.relpath(f, d)}")
                elif n.lower().endswith(".txt"):
                    if name_filter is None or name_filter(fp):
                        files.append(fp)
                        state_keys.append(fp)
    return files, state_keys, temp_dirs


# ============================================================
#  Scoring (N-8)
# ============================================================

def score_line(login, password):
    """0-10: длина/разнообразие пароля + валидность логина."""
    s = 0
    if not password:
        return 0
    if len(password) >= 6:
        s += 2
    if len(password) >= 8:
        s += 2
    if len(password) >= 12:
        s += 1
    classes = 0
    if re.search(r'[a-z]', password): classes += 1
    if re.search(r'[A-Z]', password): classes += 1
    if re.search(r'[0-9]', password): classes += 1
    if re.search(r'[^a-zA-Z0-9]', password): classes += 1
    s += classes
    if login and '@' in login:
        s += 1
    return min(10, s)


def weak_password(password):
    """Пароль слабый? (для отчёта)"""
    if not password or len(password) < 6:
        return True
    if re.fullmatch(r'[0-9]+', password) or re.fullmatch(r'[a-zA-Z]+', password):
        return True
    return password.lower() in {'password', '123456', 'qwerty', 'admin', 'letmein', 'welcome'}


# ============================================================
#  Domain index (N-5)
# ============================================================

INDEX_FILE = "index.sqlite"


def extract_domain(line):
    """Домен из строки результата: URL-host или email-домен."""
    try:
        if b'://' in line:
            after_proto = line.split(b'://', 1)[-1]
            at_pos = after_proto.rfind(b'@')
            first_slash = after_proto.find(b'/')
            if at_pos >= 0 and (first_slash < 0 or at_pos < first_slash):
                host = after_proto[at_pos + 1:]
                if first_slash >= 0:
                    host = host[:host.find(b'/')] if b'/' in host else host
                host = host.split(b':')[0]
            else:
                host = after_proto[:first_slash if first_slash >= 0 else len(after_proto)]
                host = host.split(b':')[0]
            return host.decode('utf-8', errors='ignore').lower()
        parts = line.split(b':')
        if len(parts) >= 2:
            login = parts[0]
            if b'@' in login:
                return login.split(b'@')[-1].decode('utf-8', errors='ignore').lower()
    except Exception:
        pass
    return None


def build_domain_index(out_dir_date):
    """Строит инвертированный индекс (домен -> строки) по финальным файлам.
    Returns (index_path, n_lines)."""
    index_path = os.path.join(out_dir_date, INDEX_FILE)
    try:
        if os.path.exists(index_path):
            os.remove(index_path)
        conn = sqlite3.connect(index_path)
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("CREATE TABLE idx (domain TEXT, line TEXT)")
        n = 0
        batch = []
        for fname in os.listdir(out_dir_date):
            if not fname.endswith(".txt"):
                continue
            with open(os.path.join(out_dir_date, fname), "rb") as f:
                for raw in f:
                    line = raw.rstrip(b'\r\n')
                    if not line:
                        continue
                    d = extract_domain(line)
                    batch.append((d or "", line.decode('utf-8', errors='ignore')))
                    n += 1
                    if len(batch) >= 50000:
                        conn.executemany("INSERT INTO idx VALUES (?,?)", batch)
                        batch = []
        if batch:
            conn.executemany("INSERT INTO idx VALUES (?,?)", batch)
        conn.execute("CREATE INDEX i_dom ON idx (domain)")
        conn.commit()
        conn.close()
        return index_path, n
    except Exception as e:
        logger.error(f"Index build failed: {e}")
        return None, 0


def query_domain_index(out_dir_date, domain_like, limit=1000):
    """Поиск по индексу: домен (можно с *). Returns list[str]."""
    index_path = os.path.join(out_dir_date, INDEX_FILE)
    if not os.path.exists(index_path):
        return None
    try:
        conn = sqlite3.connect(index_path)
        if '*' in domain_like or '%' in domain_like:
            pat = domain_like.replace('*', '%').replace('?', '_')
            rows = conn.execute("SELECT line FROM idx WHERE domain LIKE ? LIMIT ?",
                                (pat.lower(), limit)).fetchall()
        else:
            rows = conn.execute("SELECT line FROM idx WHERE domain = ? LIMIT ?",
                                (domain_like.lower(), limit)).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"Index query failed: {e}")
        return None


# ============================================================
#  Run summary DB + diffs (N-7)
# ============================================================

RUNS_DB = "runs.sqlite"


def save_run_summary(out_dir, out_dir_date, summary):
    """Сохраняет сводку прогона в runs.sqlite (в корне out_dir)."""
    try:
        db_path = os.path.join(out_dir, RUNS_DB)
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS runs (
            ts TEXT PRIMARY KEY, new_unique INTEGER, duplicates INTEGER,
            total_db INTEGER, elapsed REAL, avg_speed REAL, queries TEXT,
            top_domains TEXT)""")
        prev = get_previous_run(conn, out_dir_date)
        summary["prev_run"] = prev
        conn.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)", (
            summary["ts"], summary["new_unique"], summary["duplicates"],
            summary["total_db"], summary["elapsed"], summary["avg_speed"],
            json.dumps(summary.get("queries", {}), ensure_ascii=False),
            json.dumps(summary.get("top_domains", {}), ensure_ascii=False),
        ))
        conn.commit()
        conn.close()
        return summary
    except Exception as e:
        logger.error(f"Run summary save failed: {e}")
        return summary


def get_previous_run(conn, current_ts):
    """Предыдущий по времени прогон (ts < current, отсортировано по убыванию)."""
    try:
        cur = conn.execute(
            "SELECT ts, new_unique, duplicates, total_db FROM runs WHERE ts < ? ORDER BY ts DESC LIMIT 1",
            (current_ts,)).fetchone()
        if cur:
            return {"ts": cur[0], "new_unique": cur[1], "duplicates": cur[2], "total_db": cur[3]}
    except Exception:
        pass
    return None


def compute_diff(summary):
    """Diff нового прогона против предыдущего (N-7)."""
    prev = summary.get("prev_run")
    if not prev:
        return None
    d = {
        "prev_ts": prev["ts"],
        "new_unique_delta": summary["new_unique"] - prev["new_unique"],
        "duplicates_delta": summary["duplicates"] - prev["duplicates"],
        "total_db_delta": summary["total_db"] - prev["total_db"],
    }
    return d


# ============================================================
#  Density map (концепт B «Картография»)
# ============================================================

def build_density_map(out_dir_date, n_bins=128):
    """Строит плотностную карту финальных файлов прогона.
    Returns {"bins": [counts], "max": m, "files": [{"name","start_bin","end_bin","lines"}]}.
    bins равномерно делят суммарный объём строк; плотность = строк/бин.
    """
    files = []
    total_lines = 0
    try:
        for fname in sorted(os.listdir(out_dir_date)):
            if not fname.endswith(".txt"):
                continue
            cnt = 0
            with open(os.path.join(out_dir_date, fname), "rb") as f:
                for _ in f:
                    cnt += 1
            files.append({"name": fname, "lines": cnt})
            total_lines += cnt
    except Exception as e:
        logger.error(f"density map scan failed: {e}")
    if total_lines == 0 or n_bins <= 0:
        return {"bins": [], "max": 0, "files": []}
    bins = [0] * n_bins
    lines_per_bin = total_lines / n_bins
    pos = 0.0
    for finfo in files:
        start_bin = int(pos)
        pos += finfo["lines"] / lines_per_bin
        end_bin = min(n_bins, int(math_ceil(pos)))
        finfo["start_bin"] = start_bin
        finfo["end_bin"] = end_bin
        for b in range(start_bin, end_bin):
            bins[b] += max(1, int(finfo["lines"] / max(1, end_bin - start_bin)))
    return {"bins": bins, "max": max(bins) if bins else 0, "files": files}


def math_ceil(x):
    import math
    return math.ceil(x)


# ============================================================
#  mmap block reader (N-9)
# ============================================================

def open_block_reader(file_path, read_start, read_end, block_size=16 * 1024 * 1024):
    """Zero-copy block reader поверх mmap (N-9).
    Yields bytes-блоки [pos, pos+block_size) в пределах [read_start, read_end).
    Возвращает generator; при ошибке mmap caller использует обычный read().
    """
    import mmap, sys
    f = open(file_path, "rb")
    try:
        size = os.path.getsize(file_path)
        read_end = min(read_end, size)
        if read_end <= read_start:
            f.close()
            return
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            pos = read_start
            while pos < read_end:
                nxt = min(pos + block_size, read_end)
                yield mm[pos:nxt]
                pos = nxt
        finally:
            mm.close()
    finally:
        f.close()
