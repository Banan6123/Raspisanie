import difflib, io, json, os, re, sys, datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
OUT = os.path.join(ROOT, "schedule.json")
URL = "https://phtt.ru/files/files/Расписание/1 корпус {}.pdf"
T2N = {v: int(k) for k, v in CFG["times"].items()}


def norm(s):
    s = re.sub(r"[\u00ad\u200b\u200c\u200d\ufeff]", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def canon_subject(t):
    low = t.lower().strip(" .")
    if low in CFG["aliases"]:
        return CFG["aliases"][low]
    for s in CFG["subjects"]:
        if s.lower() == low:
            return s
    m = difflib.get_close_matches(t, CFG["subjects"], n=1, cutoff=0.75)
    return m[0] if m else t


def canon_teacher(t):
    sur = t.split()[0].lower()
    for full in CFG["teachers"]:
        if full.split()[0].lower().startswith(sur):
            return full
    return t


def parse_cell(raw):
    """'Физ-ра\\nЛунего\\nв АИ' -> {subj:'ФЗК', teacher:'Лунегов А. И.', room:'АИ'}"""
    t = norm(" ".join((raw or "").split("\n")))  # перенос строки -> ПРОБЕЛ
    if not t:
        return None
    room = teacher = ""
    m = (re.search(r"\s(?:[вВ]\s+|ауд\.?\s*)(\S+)$", t)
         or re.search(r"\s(\d{2,4}[а-яА-Я]?)$", t)
         or re.search(r"\s([А-ЯЁ]{2,5})$", t))
    if m:
        room, t = m.group(1), t[:m.start()]
    m = re.search(r"\s([А-ЯЁ][а-яё-]+(?:\s[А-ЯЁ]\.\s?[А-ЯЁ]\.?)?)$", t)
    if m and t[:m.start()].strip():
        teacher, t = m.group(1), t[:m.start()]
    return {"subj": canon_subject(t.strip()), "room": room,
            "teacher": canon_teacher(teacher) if teacher else ""}


def key(s):
    return re.sub(r"[\s\u2010-\u2015\-]", "", s or "").lower()


def parse_pdf(data, group):
    import pdfplumber
    found, seen = {}, False
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for tb in page.extract_tables():
                loc = next(((ri, ci) for ri, row in enumerate(tb)
                            for ci, c in enumerate(row) if key(group) in key(c)), None)
                if not loc:
                    continue
                seen = True
                hr, gc = loc
                n = None
                for row in tb[hr + 1:]:
                    for c in row[:max(gc, 1)]:
                        c = norm(c)
                        mt = re.match(r"^(\d{1,2})[:.](\d{2})", c)
                        if mt and f"{int(mt[1]):02d}:{mt[2]}" in T2N:
                            n = T2N[f"{int(mt[1]):02d}:{mt[2]}"]; break
                        mn = re.match(r"^([1-7])\b", c)
                        if mn:
                            n = int(mn[1]); break
                    p = parse_cell(row[gc]) if gc < len(row) else None
                    if p and n:
                        found[n] = {"n": n, **p}
    if not seen:
        print(f"  таблица с группой {group} не найдена")
    return [found[k] for k in sorted(found)]


def tg(text):
    tok, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT_ID")
    if not (tok and chat):
        print("telegram: секреты TG_TOKEN / TG_CHAT_ID не заданы")
        return
    import requests
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=20)
    print("telegram:", r.status_code, r.text[:200])


def fmt(day, lst):
    d = dt.date.fromisoformat(day)
    head = f"📅 {CFG['group']} · {d.strftime('%d.%m')}"
    if not lst:
        return head + "\nПар нет"
    return head + "\n" + "\n".join(
        f"{p['n']} пара {CFG['times'][str(p['n'])]} — {p['subj']}"
        + (f" · {p['room']}" if p["room"] else "") + (f" · {p['teacher']}" if p["teacher"] else "")
        for p in lst)


def main():
    import requests
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"days": {}}
    days, today = dict(old.get("days", {})), dt.datetime.now(ZoneInfo(CFG["tz"])).date()
    changed = []
    for i in range(CFG["days_ahead"] + 1):
        d = today + dt.timedelta(days=i)
        r = requests.get(URL.format(d.strftime("%d.%m")), timeout=30)
        print(d, r.status_code)
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            continue
        lst = parse_pdf(r.content, CFG["group"])
        print("  найдено пар:", len(lst))
        k = d.isoformat()
        if lst and lst != days.get(k):
            days[k] = lst
            changed.append(k)
    if changed:
        json.dump({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "days": days},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for k in changed:
            tg(fmt(k, days[k]))
    print("изменено:", changed or "нет")
    if os.getenv("FORCE_SEND"):
        k = (today + dt.timedelta(days=1)).isoformat()
        tg(fmt(k, days[k]) if k in days else "Расписания на завтра пока нет")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        for s in ["Физ-ра\nЛунего\nв АИ", "Операционные системы\nи среды\nКудрина Е. З.\n309", "История\nАндронова А. В.\n420"]:
            print(repr(s), "->", parse_cell(s))
    else:
        main()
