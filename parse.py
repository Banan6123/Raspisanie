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


def key(s):
    return re.sub(r"[^а-яё0-9]", "", (s or "").lower())


def canon_subject(lines):
    t = " ".join(lines).strip()
    k = key(t)
    if k in CFG["aliases"]:
        return CFG["aliases"][k]
    for p, name in CFG["prefixes"].items():
        if k.startswith(p):
            return name
    m = difflib.get_close_matches(k, {key(x): x for x in CFG["subjects"]}, n=1, cutoff=0.8)
    return {key(x): x for x in CFG["subjects"]}[m[0]] if m else t


ROOM = re.compile(r"^(\d{3}[а-я]?|ДО|спортзал)$")


def parse_cell(raw):
    """Ячейка бывает с переносами посреди слов: 'Федене / ва ЮА' -> Феденева Ю. А."""
    lines = [norm(l) for l in (raw or "").split("\n") if norm(l)]
    if not lines:
        return None
    ri = next((i for i, l in enumerate(lines) if ROOM.match(l)), None)
    if ri is not None:
        subj, room, tl = lines[:ri], lines[ri], lines[ri + 1:]
    else:
        subj, room, tl = lines[:1], "", lines[1:]
    teacher = ""
    if tl:
        text = " ".join(tl)
        m = re.search(r"(?:^|\s)([А-ЯЁ]{2})$", text)
        ini = m.group(1) if m else ""
        sur = (text[:m.start()] if m else text).replace(" ", "")
        if ini and key(sur) in CFG.get("initials_are_room", []):
            room = room or ini  # у таких преподавателей две буквы после фамилии это место
        teacher = sur  # только фамилия, без инициалов
    return {"subj": canon_subject(subj), "room": room, "teacher": teacher}


ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}


def row_number(cell):
    c = norm(cell)
    m = re.match(r"^(VII|VI|IV|V|III|II|I)(?![A-Za-zА-Яа-я])", c)
    if m:
        return ROMAN[m.group(1)]
    m = re.search(r"(\d{1,2})\s?[:.]?\s?(\d{2})", c)
    if m and f"{int(m[1]):02d}:{m[2]}" in T2N:
        return T2N[f"{int(m[1]):02d}:{m[2]}"]
    return None


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
                for row in tb[hr + 1:]:
                    n = row_number(row[0]) if row else None
                    cell = row[gc] if gc < len(row) else None
                    print("  строка:", repr(row[0] if row else None), "->", n, "|", repr(cell))
                    p = parse_cell(cell)
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
    main()
