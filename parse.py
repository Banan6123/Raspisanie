#!/usr/bin/env python3
"""Берёт PDF расписания 1 корпуса phtt.ru, достаёт колонку группы и
дописывает день в schedule.json.

Установка:  pip install pdfplumber
Примеры:
  python parse.py                      # сегодняшняя дата
  python parse.py --date 27.10         # конкретный день (ДД.ММ)
  python parse.py --pdf "1 корпус 26.10.pdf"   # уже скачанный файл
  python parse.py --pdf file.pdf --debug       # показать таблицу из PDF
"""
import argparse, datetime as dt, io, json, re, sys, urllib.request
from pathlib import Path
from urllib.parse import quote

GROUP = "ИС-25-4"
OUT = Path("schedule.json")
URL = "https://phtt.ru/files/files/Расписание/1 корпус {dd}.{mm}.pdf"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

# Как в таблице (без пробелов, дефисов, регистра) -> как показываем в приложении.
# Если скрипт напишет «не знаю название», добавьте сюда строку.
ALIASES = {
    "ААС": "Архитектура аппаратных средств",
    "ОС": "Операционные системы и среды",
    "ИТ": "Информационные технологии",
    "ИСТОРИЯ": "История",
    "ФИЗРА": "ФЗК",
    "ИНЯЗВПД": "Иностранный язык в профессиональной деятельности",
}


def key(s):
    return re.sub(r"[\s\-]", "", s or "").upper()


def pretty_teacher(raw):
    """'Никоно\\nва ЕА' -> 'Никонова Е. А.' ; 'Волкова\\nАС' -> 'Волкова А. С.'"""
    s = "".join(raw)
    s = re.sub(r"([а-яё])([А-ЯЁ]{2})$", r"\1 \2", s)
    m = re.match(r"^(.*?)\s*([А-ЯЁ])\s*([А-ЯЁ])$", s)
    if m:
        return f"{m.group(1).strip()} {m.group(2)}. {m.group(3)}."
    return s.strip()


def parse_cell(text):
    """Ячейка -> {'subj','room','teacher'} или None, если пусто."""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    if not lines:
        return None
    room_i = next((i for i, l in enumerate(lines) if re.fullmatch(r"\d{3}|ДО", l)), None)
    if room_i is None:  # нет аудитории (напр. физ-ра): преподаватель — последние 2 строки
        last = lines[-1]
        if len(lines) > 2 and (re.fullmatch(r"[А-ЯЁ]{2}", last) or re.fullmatch(r"[а-яё]+ [А-ЯЁ]{2}", last)):
            subj_lines, room, teacher_lines = lines[:-2], "", lines[-2:]
        else:
            subj_lines, room, teacher_lines = lines, "", []
    else:
        subj_lines, room, teacher_lines = lines[:room_i], lines[room_i], lines[room_i + 1:]
    subj = ALIASES.get(key("".join(subj_lines)))
    if subj is None:
        subj = ALIASES.get(key(" ".join(subj_lines)))
    if subj is None:
        subj = " ".join(subj_lines)
        print(f"  ! не знаю название «{subj}» — добавьте в ALIASES (ключ: {key(subj)})")
    return {"subj": subj, "room": room, "teacher": pretty_teacher(teacher_lines) if teacher_lines else ""}


def pdf_date(text, fallback):
    m = re.search(r"на\s+(\d{1,2})\s+([а-я]+)\s+(\d{4})", text or "")
    if m and m.group(2) in MONTHS:
        return dt.date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
    return fallback


def extract(pdf_bytes, fallback_date, debug=False):
    import pdfplumber
    want = key(GROUP)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            date = pdf_date(page.extract_text(), fallback_date)
            for table in page.extract_tables():
                if debug:
                    for row in table:
                        print([(c or "").replace("\n", "|") for c in row])
                    print("-" * 40)
                col = None
                for row in table[:4]:
                    for j, cell in enumerate(row):
                        if want in key(cell):
                            col = j
                if col is None:
                    continue
                pairs = []
                for row in table:
                    first = (row[0] or "").split("\n")[0].strip()
                    if first in ROMAN and col < len(row):
                        p = parse_cell(row[col])
                        if p:
                            pairs.append({"n": ROMAN[first], **p})
                return date, pairs
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="ДД.ММ (по умолчанию сегодня)")
    ap.add_argument("--pdf", help="путь к уже скачанному PDF")
    ap.add_argument("--debug", action="store_true", help="напечатать таблицы из PDF")
    ap.add_argument("--allow-empty", action="store_true", help="записать день без пар")
    a = ap.parse_args()

    today = dt.date.today()
    if a.date:
        d, m = map(int, a.date.split(".")[:2])
        day = dt.date(today.year, m, d)
    else:
        day = today

    if a.pdf:
        data = Path(a.pdf).read_bytes()
    else:
        url = URL.format(dd=f"{day.day:02d}", mm=f"{day.month:02d}")
        print("Скачиваю", url)
        req = urllib.request.Request(quote(url, safe=":/"), headers={"User-Agent": "Mozilla/5.0"})
        try:
            data = urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:  # файла на эту дату может ещё не быть
            print("Не удалось скачать:", e)
            return 0

    date, pairs = extract(data, day, a.debug)
    if pairs is None:
        print(f"Колонка {GROUP} не найдена. Запустите с --debug и пришлите вывод.")
        return 1
    if not pairs and not a.allow_empty:
        print(f"Для {GROUP} пар не нашлось — не записываю (проверьте через --debug или --allow-empty).")
        return 1

    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    store[date.isoformat()] = pairs
    OUT.write_text(json.dumps(dict(sorted(store.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{date}: записано пар — {len(pairs)}")
    for p in pairs:
        print(f"  {p['n']} пара · {p['subj']} · ауд. {p['room']} · {p['teacher']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
