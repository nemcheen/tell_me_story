"""
autoedit.py

Фоновый скрипт для занятия "ИТ-термины и общая история".

Каждые POLL_INTERVAL секунд скрипт проверяет файлы words.txt и story.txt.

1. words.txt — список строк вида:
       термин (Имя ученика)
   Термин может быть одним словом или словосочетанием (несколько слов через
   пробелы). За каждый такой пункт (строку) ученик получает 2 балла.

2. story.txt — история. Предложения идут друг за другом (через точку), каждое
   предложение оканчивается именем автора в скобках:
       ... текст ... (Имя)
   Скрипт ищет в каждом предложении термины из words.txt. За КАЖДОЕ
   употребление термина в предложении автор предложения получает 3 балла.

   Правило совпадения (эвристика):
     - длинное слово (>6 букв):  отбрасываем 3 последние буквы;
     - слово 5-6 букв:            отбрасываем 2 последние буквы;
     - короткое слово (<=4 букв): оставляем слово целиком.
   В любом случае ищем слова в предложении по НАЧАЛУ (слово, начинающееся с
   основы), поэтому окончания и склонения (байт -> байта, байтов) не мешают.
     - для словосочетания: все его слова должны встретиться в предложении.

3. В файл words.txt перед термином, который уже встречался в story.txt,
   ставится галочка и пробел:   ✅ термин (Имя).
   Неиспользованные термины (без галочки) записываются выше использованных
   (сортировка по галочке). Файл story.txt НЕ изменяется.

4. chart.txt — таблица баллов:
       Имя: ███ 5
   Полоска из квадратиков пропорциональна баллам, затем число. Строки
   отсортированы по убыванию баллов; каждая полоска — своего цвета (ANSI,
   если включён USE_COLORS). Запущенный скрипт также выводит эту таблицу
   в консоль (с цветом) каждый раз, когда она обновляется.

Файлы читаются/записываются в кодировке UTF-8.  Остановка — Ctrl+C.
"""

import os
import re
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORDS_FILE = os.path.join(SCRIPT_DIR, "words.txt")
STORY_FILE = os.path.join(SCRIPT_DIR, "story.txt")
CHART_FILE = os.path.join(SCRIPT_DIR, "chart.txt")

POINTS_FOR_TERM = 2  # за внесение термина в words.txt
POINTS_FOR_USE = 3  # за каждое употребление термина в предложении
POLL_INTERVAL = 2.5  # секунды между проверками

CHECK_EMOJI = "\u2705"  # ✅
BAR_CHAR = "\u2588"  # █  (U+2588 FULL BLOCK)

# Цветные полоски в chart.txt (ANSI-коды).
# Включаются только если USE_COLORS=True И PALETTE задан. Работает в терминалах,
# поддерживающих ANSI (Windows Terminal, VS Code, новый PowerShell); в обычном
# блокноте вместо цвета будут видны служебные символы.
USE_COLORS = False
COLOR_RESET = "\x1b[0m"
PALETTE = [
    "\x1b[91m",
    "\x1b[92m",
    "\x1b[93m",
    "\x1b[94m",
    "\x1b[95m",
    "\x1b[96m",
    "\x1b[97m",
]

# Выводить всю таблицу баллов (chart.txt) в консоль при обновлении.
# При CLEAR_SCREEN=True экран очищается перед каждой отрисовкой (живая доска).
PRINT_CHART_TO_CONSOLE = True
CLEAR_SCREEN = True


def read_file(path):
    """Читает UTF-8 файл; отсутствующий файл считает пустым."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def write_file(path, text):
    """Пишет файл в UTF-8. newline='' — переносы строк пишем как есть."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def detect_newline(text):
    """Определяет перенос строки, использованный в тексте."""
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    return os.linesep

def enable_windows_ansi():
    """Включает обработку ANSI-кодов (цвета и очистка экрана) в консоли Windows.
    Использует ctypes — нативный модуль, без сторонних библиотек.
    На других ОС ничего не делает."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:                                 # noqa: BLE001
        pass




# --------------------------------------------------------------------------
# Разбор файлов
# --------------------------------------------------------------------------


def parse_entry(content):
    """Разбирает строку words.txt -> {'term','name'} или None для пустой."""
    t = content.strip()
    if not t:
        return None
    # убрать уже стоящую галочку, если она есть
    if t.startswith(CHECK_EMOJI):
        t = t[len(CHECK_EMOJI) :].strip()
    # имя ученика — последняя группа в скобках в конце строки
    m = re.search(r"\(([^()]*)\)\s*$", t)
    if m:
        name = m.group(1).strip()
        term = t[: m.start()].strip()
    else:
        name = "Неизвестный"
        term = t.strip()
    if not term:
        return None
    return {"term": term, "name": name, "used": False}


def parse_words(raw):
    """Разбирает words.txt на чанки, сохраняя переносы строк и пустые строки."""
    chunks = []
    lines = raw.splitlines(keepends=True)
    for raw_line in lines:
        content = raw_line.rstrip("\r\n")
        ending = raw_line[len(content) :]
        data = parse_entry(content) if content.strip() else None
        if data is None:
            chunks.append(
                {"kind": "blank", "content": content, "ending": ending, "data": None}
            )
        else:
            chunks.append(
                {"kind": "entry", "content": content, "ending": ending, "data": data}
            )
    return chunks


def parse_story(raw):
    """Разбирает story.txt на (текст_предложения, автор) по именам в скобках."""
    segments = []
    name_pat = re.compile(r"\(([^()\n]*)\)")
    prev = 0
    for m in name_pat.finditer(raw):
        text = raw[prev : m.start()]
        author = m.group(1).strip()
        segments.append((text, author))
        prev = m.end()
    return segments


# --------------------------------------------------------------------------
# Совпадение терминов (учёт склонений / окончаний)
# --------------------------------------------------------------------------


def build_stem(word):
    """Возвращает основу слова по договорённому правилу."""
    n = len(word)
    if n > 6:
        return word[:-3]  # убираем 3 последние буквы
    if n >= 5:
        return word[:-2]  # убираем 2 последние буквы
    return word  # <=4 букв — целое слово


def make_term_regex(term_word):
    """Рег. выражение для поиска одного слова термина в тексте.
    Всегда ищем по НАЧАЛУ слова (слово, начинающееся с основы), поэтому
    окончания и склонения в предложении (байт -> байта, байтов) не мешают.
    """
    stem = build_stem(term_word)
    return re.compile(r"(?<!\w)" + re.escape(stem) + r"\w*", re.IGNORECASE)


def phrase_present(term_words, seg_text):
    """Все слова словосочетания должны встретиться в предложении."""
    return all(make_term_regex(w).search(seg_text) for w in term_words)


# --------------------------------------------------------------------------
# Баллы и chart.txt
# --------------------------------------------------------------------------


def build_chart(points):
    """Строит содержимое chart.txt: сортировка по убыванию баллов, потом по имени.
    Каждому ученику — полоска своего цвета (циклически по палитре)."""
    names = sorted(points, key=lambda n: (-points[n], n.casefold()))
    lines = []
    for i, name in enumerate(names):
        p = points[name]
        bar = BAR_CHAR * p
        if USE_COLORS and PALETTE:
            color = PALETTE[i % len(PALETTE)]
            line = f"{name}: {color}{bar}{COLOR_RESET} {p}"
        else:
            line = f"{name}: {bar} {p}"
        lines.append(line)
    return "\r\n".join(lines) + "\r\n"


def draw_chart(chart_text):
    """Выводит всю таблицу баллов (с цветными полосками) в консоль."""
    if not PRINT_CHART_TO_CONSOLE:
        return
    if CLEAR_SCREEN:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
    body = chart_text.rstrip("\r\n").replace("\r\n", "\n")
    print("=== ТАБЛИЦА БАЛЛОВ ===")
    print(body)
    print("-" * 50)


# --------------------------------------------------------------------------
# Основная обработка
# --------------------------------------------------------------------------


def process():
    """Один проход: читает файлы, считает баллы, возвращает новые тексты файлов."""
    words_raw = read_file(WORDS_FILE)
    story_raw = read_file(STORY_FILE)

    chunks = parse_words(words_raw)
    entries = [c for c in chunks if c["kind"] == "entry"]
    segments = parse_story(story_raw)

    points = {}

    def add_points(name, number):
        if number <= 0:
            return
        points[name] = points.get(name, 0) + number

    # 2 балла за каждую строку words.txt (внесение термина)
    for c in entries:
        add_points(c["data"]["name"], POINTS_FOR_TERM)

    # за каждое употребление термина в предложении — 3 балла автору предложения
    for seg_text, author in segments:
        for c in entries:
            e = c["data"]
            term_words = e["term"].split()
            if len(term_words) == 1:
                rx = make_term_regex(term_words[0])
                count = len(rx.findall(seg_text))
                if count > 0:
                    e["used"] = True
                    add_points(author, count * POINTS_FOR_USE)
            else:
                if phrase_present(term_words, seg_text):
                    e["used"] = True
                    add_points(author, POINTS_FOR_USE)

    # пересобрать words.txt: неиспользованные термины идут ВЫШЕ использованных,
    # внутри групп — исходный порядок (устойчивая сортировка, по сути по галочке)
    entries_sorted = sorted(entries, key=lambda c: c["data"]["used"])
    nl = detect_newline(words_raw)
    out_lines = []
    for c in entries_sorted:
        e = c["data"]
        line = "{0} ({1})".format(e["term"], e["name"])
        if e["used"]:
            line = CHECK_EMOJI + " " + line
        out_lines.append(line)
    words_out = nl.join(out_lines)
    if out_lines:
        words_out += nl

    chart_out = build_chart(points)

    return words_out, chart_out, points


def main():
    enable_windows_ansi()
    print("Фоновая проверка запущена.")
    print(f"Отслеживаются файлы: {WORDS_FILE}")
    print("Для остановки нажмите Ctrl+C.")
    print("-" * 50)

    last_words = None
    last_chart = None

    while True:
        try:
            words_out, chart_out, points = process()

            if words_out != last_words:
                write_file(WORDS_FILE, words_out)
                last_words = words_out
                print("[words.txt] обновлён (отмечены использованные термины)")

            if chart_out != last_chart:
                write_file(CHART_FILE, chart_out)
                last_chart = chart_out
                draw_chart(chart_out)

        except KeyboardInterrupt:
            print("\nОстановлено.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка во время проверки: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
