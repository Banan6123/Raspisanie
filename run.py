#!/usr/bin/env python3
"""Запуск раз в день: скачать PDF -> обновить schedule.json -> написать в Telegram.

  python run.py            # режим выбирается по времени: до 12:00 - сегодня, после - завтра
  python run.py today      # расписание на сегодня
  python run.py tomorrow   # расписание на завтра
Без TELEGRAM_TOKEN / TELEGRAM_CHAT_ID просто печатает сообщение (проверка).
"""
import datetime as dt, json, os, sys, urllib.request, urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo
import parse

TZ = ZoneInfo(os.environ.get("SCHEDULE_TZ", "Europe/Moscow"))
ANCHOR = dt.date(2026, 10, 26)  # понедельник 1 недели (числитель)
TIMES = {1: "8:30", 2: "10:35", 3: "12:40", 4: "14:30", 5: "16:15", 6: "18:00", 7: "19:35"}
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
EVM, CM, FZK = "Элементы высшей математики", "Численные методы", "ФЗК"
IYA, AAS = "Иностранный язык в профессиональной деятельности", "Архитектура аппаратных средств"
OS_, IT = "Операционные системы и среды", "Информационные технологии"
DM, IST = "Дискретная математика с элементами математической логики", "История"
OAP, ABP = "Основы алгоритмизации и программирования", "Автоматизация бизнес-процессов"
BASE = {  # неделя -> день (1=Пн) -> [(пара, предмет)]
    1: {1: [(2, AAS), (3, AAS), (4, IST)], 2: [(2, FZK), (3, OS_)], 3: [(2, IYA), (3, IT), (4, DM)],
        4: [(5, OAP), (6, ABP), (7, ABP)], 5: [(1, EVM), (2, CM), (3, OAP)], 6: [(3, IT), (4, OAP), (5, IST), (6, ABP)]},
    2: {1: [(3, AAS), (4, IST), (5, DM)], 2: [(2, FZK), (3, OS_)], 3: [(2, IYA), (3, IT), (4, DM)],
        4: [(4, OS_), (5, OAP), (6, ABP), (7, ABP)], 5: [(1, EVM), (2, CM), (3, EVM)], 6: [(4, OAP), (5, IST), (6, ABP)]},
}
FILE = Path("schedule.json")


def week_of(day):
    return 1 if ((day - ANCHOR).days // 7) % 2 == 0 else 2


def base_pairs(day):
    wd = day.weekday() + 1
    return [{"n": n, "subj": s, "room": "", "teacher": ""} for n, s in BASE[week_of(day)].get(wd, [])]


def from_pdf(day):
    url = parse.URL.format(dd=f"{day.day:02d}", mm=f"{day.month:02d}")
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/"), headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = urllib.request.urlopen(req, timeout=30).read()
        date, pairs = parse.extract(data, day)
    except Exception as e:
        print("PDF недоступен:", e)
        return None
    if pairs is None or date != day:
        print("В PDF нет нужной колонки или дата не совпала")
        return None
    return pairs


def get_pairs(day, store):
    pairs = from_pdf(day)
    if pairs is not None:
        store[day.isoformat()] = pairs
        return pairs, "pdf"
    if day.isoformat() in store:
        return store[day.isoformat()], "saved"
    return base_pairs(day), "base"


def fmt(day, pairs, src, label):
    wk = "числитель" if week_of(day) == 1 else "знаменатель"
    out = [f"📅 {label}, {DAYS[day.weekday()]} {day:%d.%m} · {wk}", ""]
    for p in sorted(pairs, key=lambda p: p["n"]):
        out.append(f"{p['n']} пара · {TIMES[p['n']]} · {p['subj']}")
        extra = " · ".join(x for x in ((("ауд. " + p["room"]) if p.get("room") else ""), p.get("teacher", "")) if x)
        if extra:
            out.append("   " + extra)
    if src == "base":
        out += ["", "ℹ️ Расписание на этот день ещё не опубликовано — показано основное (без аудиторий)."]
    return "\n".join(out)


def send(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("(токен не задан — печатаю вместо отправки)\n" + text)
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body), timeout=30)
    print("Отправлено в Telegram")


def main():
    now = dt.datetime.now(TZ)
    mode = sys.argv[1] if len(sys.argv) > 1 else ("today" if now.hour < 12 else "tomorrow")
    day = now.date() + dt.timedelta(days=1 if mode == "tomorrow" else 0)
    store = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    pairs, src = get_pairs(day, store)
    FILE.write_text(json.dumps(dict(sorted(store.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    if not pairs:
        print(f"{day}: пар нет — сообщение не отправляю")
        return
    send(fmt(day, pairs, src, "Сегодня" if mode == "today" else "Завтра"))


if __name__ == "__main__":
    main()
