# URLmonster

Высокопроизводительный парсер URL/логинов для Windows.

Python + Rust (PyO3) — поиск по маскам в больших файлах (4+ GB/мин).

---

## 🔧 Установка

### Зависимости

- Python 3.10+
- Rust (https://rustup.rs) — для сборки `rust_scan.pyd`

```bash
# Python пакеты
pip install -r requirements.txt
```

### Сборка Rust-модуля

```bash
cd rust_engine_src
cargo build --release
```

Готовый файл: `rust_engine_src/target/release/rust_scan.dll`

Переименуйте в `rust_scan.pyd` и скопируйте в корень проекта:

```bash
copy rust_engine_src\target\release\rust_scan.dll rust_scan.pyd
```

---

## 🚀 Запуск

### GUI

```bash
python URLmonster.py
```

### CLI

```bash
python URLmonster.py --src "C:\data\base.txt" --queries "email,pass" --out results
```

---

## 📋 Запросы (`queries.txt`)

Список запросов, один на строку. Поддерживаются группы и префиксы:

```
[Credentials]
login:email
full:password

[URLs]
full:https://example.com
site.com
```

| Префикс | Что сохраняется |
|---------|----------------|
| `full:` | Полная строка с `https://` |
| `login:` | Только логин |
| *(нет)* | По настройке «Сохранять строку целиком» |

---

## ⚙️ Режимы сканирования

| Режим | Описание |
|-------|----------|
| **Auto** | Автоопределение формата по первым строкам |
| **Default** | Делит по `:`, последние два поля = login:password |
| **URL** | Для строк вида `url:login:pass` |
| **Exact** | Требует ровно 2 части через разделитель |
| **Domain** | Нормализует запрос до домена |

---

## 🔍 Движки поиска

1. **Rust** — `process_block()` через PyO3, Aho-Corasick, 16 MB блоки
2. **Aho-Corasick** — fallback если Rust-модуль не загружен
3. **Regex** — регулярные выражения
4. **Substring** — регистронезависимый поиск

---

## 🏗 Сборка EXE (Nuitka)

```bash
pip install nuitka zstandard
python -m nuitka --onefile --windows-disable-console --enable-plugin=tk-inter --zig URLmonster.py
```

---

## 📁 Структура проекта

```
URLmonster.py              — главный скрипт
rust_scan.pyd              — Rust-модуль (скомпилированный)
queries.txt                — запросы
requirements.txt           — Python-зависимости
README.md                  — этот файл

rust_engine_src/           — исходный код Rust
├── Cargo.toml
├── .gitignore
└── src/
    └── lib.rs             — 3 экспорта: process_block, scan_block_rust, merge_dedup_lines
```

---

## ⚡ Производительность

- **Rust-ядро** — до 4 GB/мин на SSD (Aho-Corasick, 16 MB блоки)
- **Worker count** — HDD=2, SSD=4, NVMe=4
- **Буфер** чтения 16 MB, записи 4 MB
- **Дедупликация** — cross-file в памяти, cross-run по MD5-хешам (8 байт)

---

## 🖥 Системный трей

Встроенная поддержка через WinAPI (`Shell_NotifyIconW`). Без внешних зависимостей — ПКМ меню, двойной клик, уведомления.
