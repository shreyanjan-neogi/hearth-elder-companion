"""Hearth core: storage and care logic.

Nothing in this file imports MCP, so it is easy to test on its own.
The MCP server (server.py) wraps these functions as tools.

Design rules we follow on purpose:
- We never give medical advice. We only record what the person tells us.
- A dose nobody has confirmed is "unconfirmed", never "missed". We cannot know.
- Every function returns a plain dict with a short `summary` sentence that is
  safe to read aloud.
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from difflib import get_close_matches
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HEARTH_DB", os.path.join(os.path.dirname(HERE), "hearth.db"))
TZ = ZoneInfo(os.environ.get("HEARTH_TZ", "Asia/Kolkata"))
EMERGENCY = os.environ.get("HEARTH_EMERGENCY_NUMBER", "your local emergency number")

DUE_LEAD = timedelta(minutes=30)     # a dose counts as "due" this long before its time
DUE_WINDOW = timedelta(hours=2)      # ...and this long after, then it is "unconfirmed"
EARLY_LOG = timedelta(minutes=90)    # we accept "I took it" up to this long before the time

CONCERN_WORDS = [
    "dizzy", "faint", "fell", "fall", "chest", "breath", "confused",
    "pain", "lonely", "alone", "scared", "hopeless", "sad", "worried",
]
URGENT_WORDS = ["chest pain", "can't breathe", "cannot breathe", "fainted", "i fell", "confused"]


# --------------------------------------------------------------------------- clock
class Clock:
    """Real time, unless a demo time has been set (so a demo can show 8:20 AM at any hour)."""

    def __init__(self) -> None:
        self._real0: datetime | None = None
        self._sim0: datetime | None = None

    def now(self) -> datetime:
        real = datetime.now(TZ)
        if self._sim0 is None or self._real0 is None:
            return real
        return self._sim0 + (real - self._real0)

    def set(self, hhmm: str) -> None:
        h, m = map(int, parse_time(hhmm).split(":"))
        real = datetime.now(TZ)
        self._real0 = real
        self._sim0 = real.replace(hour=h, minute=m, second=0, microsecond=0)

    def clear(self) -> None:
        self._real0 = self._sim0 = None

    @property
    def is_demo(self) -> bool:
        return self._sim0 is not None


CLOCK = Clock()


# --------------------------------------------------------------------------- time helpers
def parse_time(text: str) -> str:
    """'8am', '8:30 pm', '20:00', 'morning' -> 'HH:MM' (24h)."""
    t = str(text).strip().lower().replace(".", "")
    words = {"morning": "08:00", "noon": "12:00", "lunch": "13:00", "afternoon": "15:00",
             "evening": "18:00", "night": "21:00", "bedtime": "21:00"}
    if t in words:
        return words[t]
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        raise ValueError(f"Could not understand the time '{text}'. Use a form like 8am, 8:30 pm or 20:00.")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ValueError(f"'{text}' is not a valid time.")
    return f"{h:02d}:{mi:02d}"


def label(hhmm: str) -> str:
    """'13:05' -> '1:05 PM' (written)."""
    h, m = map(int, hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def spoken(hhmm: str) -> str:
    """'13:00' -> '1 PM', '13:05' -> '1:05 PM' (as you would say it)."""
    h, m = map(int, hhmm.split(":"))
    base = f"{h % 12 or 12}" + ("" if m == 0 else f":{m:02d}")
    return f"{base} {'AM' if h < 12 else 'PM'}"


def _slot_dt(day: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=TZ)


def _join(names: list[str]) -> str:
    names = list(dict.fromkeys(names))
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()


# --------------------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS profile(
  id INTEGER PRIMARY KEY CHECK(id = 1),
  elder_name TEXT NOT NULL, caregiver_name TEXT NOT NULL, caregiver_relation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS medications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, dose TEXT DEFAULT '',
  times TEXT NOT NULL, notes TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS dose_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, med_id INTEGER NOT NULL, day TEXT NOT NULL,
  slot TEXT NOT NULL, taken_at TEXT NOT NULL, UNIQUE(med_id, day, slot));
CREATE TABLE IF NOT EXISTS mood_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, day TEXT NOT NULL,
  score INTEGER NOT NULL, note TEXT DEFAULT '', flagged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, day TEXT NOT NULL,
  text TEXT NOT NULL, urgent INTEGER NOT NULL DEFAULT 0);
"""


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM profile").fetchone():
            conn.execute("INSERT INTO profile VALUES (1, 'Rose', 'Priya', 'daughter')")


init_db()


def get_profile() -> dict:
    with db() as conn:
        r = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return {"elder_name": r["elder_name"], "caregiver_name": r["caregiver_name"],
            "caregiver_relation": r["caregiver_relation"]}


def setup_profile(elder_name: str, caregiver_name: str, caregiver_relation: str = "family member") -> dict:
    elder_name, caregiver_name = elder_name.strip(), caregiver_name.strip()
    if not elder_name or not caregiver_name:
        return {"ok": False, "error": "names_required", "summary": "Both names are needed."}
    with db() as conn:
        conn.execute("REPLACE INTO profile VALUES (1, ?, ?, ?)",
                     (elder_name, caregiver_name, caregiver_relation.strip() or "family member"))
    return {"ok": True, "summary": f"Saved. I'll look after {elder_name} and keep {caregiver_name} in the loop."}


# --------------------------------------------------------------------------- medicines
def _active_meds(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM medications WHERE active = 1 ORDER BY id").fetchall()


def _find_med(conn, name: str):
    n = _norm(name)
    if not n:
        return None
    rows = _active_meds(conn)
    for r in rows:
        if _norm(r["name"]) == n:
            return r
    for r in rows:
        rn = _norm(r["name"])
        if n in rn or rn in n:
            return r
    names = {_norm(r["name"]): r for r in rows}
    close = get_close_matches(n, list(names), n=1, cutoff=0.7)
    return names[close[0]] if close else None


def add_medication(name: str, dose: str = "", times: list[str] | None = None, notes: str = "") -> dict:
    name = name.strip()
    if not name:
        return {"ok": False, "error": "name_required", "summary": "What is the medicine called?"}
    try:
        clean = sorted({parse_time(t) for t in (times or [])})
    except ValueError as e:
        return {"ok": False, "error": "bad_time", "summary": str(e)}
    if not clean:
        return {"ok": False, "error": "times_required", "summary": "At what time of day should it be taken?"}
    with db() as conn:
        existing = _find_med(conn, name)
        if existing and _norm(existing["name"]) == _norm(name):
            conn.execute("UPDATE medications SET dose=?, times=?, notes=? WHERE id=?",
                         (dose, json.dumps(clean), notes, existing["id"]))
            verb = "Updated"
        else:
            conn.execute("INSERT INTO medications(name, dose, times, notes) VALUES (?,?,?,?)",
                         (name, dose, json.dumps(clean), notes))
            verb = "Added"
    when = _join([label(t) for t in clean])
    return {"ok": True, "medication": name, "times": clean,
            "summary": f"{verb} {name}{' (' + dose + ')' if dose else ''} at {when}."}


def remove_medication(name: str) -> dict:
    with db() as conn:
        med = _find_med(conn, name)
        if not med:
            return {"ok": False, "error": "medication_not_found", "summary": f"I don't have a medicine called {name}."}
        conn.execute("UPDATE medications SET active = 0 WHERE id = ?", (med["id"],))
    return {"ok": True, "summary": f"Removed {med['name']} from the schedule. Past records are kept."}


def _status(slot_dt: datetime, now: datetime, logged: bool) -> str:
    if logged:
        return "taken"
    if now < slot_dt - DUE_LEAD:
        return "upcoming"
    if now < slot_dt + DUE_WINDOW:
        return "due"
    return "unconfirmed"


def _day_slots(conn, day: str, now: datetime) -> list[dict]:
    logs = {(r["med_id"], r["slot"]): r for r in conn.execute("SELECT * FROM dose_log WHERE day = ?", (day,))}
    out = []
    for m in _active_meds(conn):
        for slot in json.loads(m["times"]):
            dt = _slot_dt(day, slot)
            log = logs.get((m["id"], slot))
            taken_dt = datetime.fromisoformat(log["taken_at"]) if log else None
            out.append({
                "med_id": m["id"], "medication": m["name"], "dose": m["dose"] or "", "notes": m["notes"] or "",
                "time": slot, "time_label": label(slot), "status": _status(dt, now, bool(log)),
                "taken_at": label(taken_dt.strftime("%H:%M")) if taken_dt else None,
                "late": bool(taken_dt and taken_dt > dt + DUE_WINDOW),
            })
    out.sort(key=lambda s: (s["time"], s["medication"]))
    return out


def _public(slot: dict) -> dict:
    return {k: v for k, v in slot.items() if k != "med_id"}


def list_medications_today() -> dict:
    with db() as conn:
        now = CLOCK.now()
        slots = _day_slots(conn, now.date().isoformat(), now)
    if not slots:
        return {"ok": True, "doses": [], "counts": {}, "now": label(now.strftime("%H:%M")),
                "summary": "No medicines are set up yet."}
    counts = {s: sum(1 for x in slots if x["status"] == s) for s in ("taken", "due", "upcoming", "unconfirmed")}
    parts = [f"Today there {'is' if len(slots) == 1 else 'are'} {len(slots)} dose{'s' if len(slots) != 1 else ''}"]
    detail = []
    if counts["taken"]:
        detail.append(f"{counts['taken']} taken")
    if counts["due"]:
        detail.append(f"{counts['due']} due now")
    if counts["unconfirmed"]:
        detail.append(f"{counts['unconfirmed']} not confirmed")
    if counts["upcoming"]:
        detail.append(f"{counts['upcoming']} later")
    text = parts[0] + (": " + ", ".join(detail) if detail else "") + "."
    due = [x["medication"] for x in slots if x["status"] == "due"]
    if due:
        text += f" Due now: {_join(due)}."
    up = next((x for x in slots if x["status"] == "upcoming"), None)
    if up:
        text += f" Next later: {up['medication']} at {spoken(up['time'])}."
    return {"ok": True, "now": label(now.strftime("%H:%M")), "counts": counts,
            "doses": [_public(s) for s in slots], "summary": text}


def whats_next() -> dict:
    with db() as conn:
        now = CLOCK.now()
        slots = _day_slots(conn, now.date().isoformat(), now)
    due = [s for s in slots if s["status"] == "due"]
    upcoming = [s for s in slots if s["status"] == "upcoming"]
    unconf = [s for s in slots if s["status"] == "unconfirmed"]
    bits = []
    if due:
        bits.append(f"Right now it's time for {_join([s['medication'] for s in due])}.")
        if upcoming:
            bits.append(f"After that, {upcoming[0]['medication']} at {spoken(upcoming[0]['time'])}.")
    elif upcoming:
        bits.append(f"Your next dose is {upcoming[0]['medication']} at {spoken(upcoming[0]['time'])}.")
    elif not slots:
        bits.append("No medicines are set up yet.")
    elif not unconf:
        bits.append("You're all done with medicines for today.")
    else:
        bits.append("There are no more doses scheduled for today.")
    if unconf:
        bits.append("I haven't heard about " + _join([f"{s['medication']} at {spoken(s['time'])}" for s in unconf])
                    + " yet. If you took it, just tell me.")
    nxt = (due or upcoming or [None])[0]
    return {"ok": True, "next": _public(nxt) if nxt else None, "due_now": [_public(s) for s in due],
            "unconfirmed": [_public(s) for s in unconf], "summary": " ".join(bits)}


def log_dose_taken(medication: str) -> dict:
    with db() as conn:
        now = CLOCK.now()
        day = now.date().isoformat()
        med = _find_med(conn, medication)
        if not med:
            known = [r["name"] for r in _active_meds(conn)]
            return {"ok": False, "error": "medication_not_found", "known_medications": known,
                    "summary": f"I don't have a medicine called {medication}."
                               + (f" I know about {_join(known)}." if known else "")}
        mine = [s for s in _day_slots(conn, day, now) if s["med_id"] == med["id"]]
        untaken = [s for s in mine if s["status"] != "taken"]
        eligible = [s for s in untaken if _slot_dt(day, s["time"]) <= now + EARLY_LOG]
        if not eligible:
            if not untaken:
                return {"ok": False, "error": "already_logged", "medication": med["name"],
                        "summary": f"{med['name']} is already marked as taken for today."}
            nxt = untaken[0]
            return {"ok": False, "error": "not_due_yet", "medication": med["name"], "next_time": nxt["time_label"],
                    "summary": f"It isn't time for {med['name']} yet. The next one is at {spoken(nxt['time'])}."}
        slot = max(eligible, key=lambda s: s["time"])
        conn.execute("INSERT INTO dose_log(med_id, day, slot, taken_at) VALUES (?,?,?,?)",
                     (med["id"], day, slot["time"], now.isoformat()))
        late = now > _slot_dt(day, slot["time"]) + DUE_WINDOW
        remaining = len(untaken) - 1
    return {"ok": True, "medication": med["name"], "slot": slot["time"], "slot_label": slot["time_label"],
            "late": late, "remaining_today": remaining,
            "summary": f"Noted: {med['name']} taken"
                       + (f" (the {spoken(slot['time'])} dose, a little late)" if late else "")
                       + f". {remaining} more dose{'s' if remaining != 1 else ''} of it today." if remaining
            else f"Noted: {med['name']} taken. That's all of it for today."}


# --------------------------------------------------------------------------- wellbeing
def log_mood(score: int, note: str = "") -> dict:
    score = max(1, min(5, int(score)))
    note = (note or "").strip()
    low = note.lower()
    keywords = [w for w in CONCERN_WORDS if w in low]
    urgent = [w for w in URGENT_WORDS if w in low]
    flagged = score <= 2 or bool(keywords)
    with db() as conn:
        now = CLOCK.now()
        conn.execute("INSERT INTO mood_log(ts, day, score, note, flagged) VALUES (?,?,?,?,?)",
                     (now.isoformat(), now.date().isoformat(), score, note, int(flagged)))
        since = (now.date() - timedelta(days=2)).isoformat()
        recent = [r["score"] for r in conn.execute("SELECT score FROM mood_log WHERE day >= ?", (since,))]
    pattern = sum(1 for s in recent if s <= 2) >= 2
    words = {1: "very low", 2: "low", 3: "so-so", 4: "good", 5: "great"}
    return {"ok": True, "score": score, "flagged": flagged, "concern_keywords": keywords,
            "urgent_keywords": urgent, "low_mood_pattern": pattern, "suggest_notify_caregiver": flagged,
            "summary": f"Logged today's mood as {words[score]}."
                       + (" This is the second low day in a row." if pattern else "")}


def send_caregiver_message(message: str, urgent: bool = False) -> dict:
    message = message.strip()
    if not message:
        return {"ok": False, "error": "empty_message", "summary": "What should the message say?"}
    p = get_profile()
    with db() as conn:
        now = CLOCK.now()
        conn.execute("INSERT INTO messages(ts, day, text, urgent) VALUES (?,?,?,?)",
                     (now.isoformat(), now.date().isoformat(), message, int(urgent)))
    return {"ok": True, "to": p["caregiver_name"], "urgent": urgent,
            "summary": f"Message sent to {p['caregiver_name']}."}


def alert_caregiver(reason: str) -> dict:
    p = get_profile()
    r = send_caregiver_message(f"ALERT: {reason.strip() or 'Asked for help'}", urgent=True)
    return {"ok": r["ok"], "to": p["caregiver_name"],
            "guidance": f"If this is an emergency, call {EMERGENCY} now. Hearth only alerts {p['caregiver_name']}; "
                        "it cannot call emergency services.",
            "summary": f"I've alerted {p['caregiver_name']}."}


# --------------------------------------------------------------------------- check-in and summary
def get_daily_checkin() -> dict:
    p = get_profile()
    now = CLOCK.now()
    greet = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
    meds = list_medications_today()
    with db() as conn:
        mood_today = conn.execute("SELECT COUNT(*) c FROM mood_log WHERE day = ?", (now.date().isoformat(),)).fetchone()["c"]
    asked = [] if mood_today else ["How are you feeling today?"]
    return {"ok": True, "greeting": f"{greet}, {p['elder_name']}.", "medicines": meds["summary"],
            "mood_logged_today": bool(mood_today), "questions": asked,
            "summary": f"{greet}, {p['elder_name']}. {meds['summary']}" + ("" if mood_today else " How are you feeling today?")}


def get_caregiver_summary(days: int = 7) -> dict:
    days = max(1, min(14, int(days)))
    p = get_profile()
    elder, cg = p["elder_name"], p["caregiver_name"]
    with db() as conn:
        now = CLOCK.now()
        today = now.date()
        slots_today = _day_slots(conn, today.isoformat(), now)
        history = []
        for back in range(days - 1, -1, -1):
            d = (today - timedelta(days=back)).isoformat()
            sl = _day_slots(conn, d, now)
            if back == 0:
                sl = [s for s in sl if s["status"] == "taken" or _slot_dt(d, s["time"]) <= now]
            sched = len(sl)
            taken = sum(1 for s in sl if s["status"] == "taken")
            moods = [r["score"] for r in conn.execute("SELECT score FROM mood_log WHERE day = ?", (d,))]
            history.append({"date": d, "scheduled": sched, "taken": taken,
                            "pct": round(100 * taken / sched) if sched else None,
                            "mood": round(sum(moods) / len(moods), 1) if moods else None})
        moods_today = [dict(time=label(datetime.fromisoformat(r["ts"]).strftime("%H:%M")), score=r["score"],
                            note=r["note"], flagged=bool(r["flagged"]))
                       for r in conn.execute("SELECT * FROM mood_log WHERE day = ? ORDER BY id", (today.isoformat(),))]
        since = (today - timedelta(days=2)).isoformat()
        msgs = [dict(time=label(datetime.fromisoformat(r["ts"]).strftime("%H:%M")), day=r["day"],
                     text=r["text"], urgent=bool(r["urgent"]))
                for r in conn.execute("SELECT * FROM messages WHERE day >= ? ORDER BY id DESC LIMIT 12", (since,))]
        recent_low = conn.execute("SELECT COUNT(*) c FROM mood_log WHERE day >= ? AND score <= 2", (since,)).fetchone()["c"]

    unconf = [s for s in slots_today if s["status"] == "unconfirmed"]
    urgent_today = [m for m in msgs if m["urgent"] and m["day"] == today.isoformat()]
    low_today = [m for m in moods_today if m["score"] <= 2]
    flags = []
    if urgent_today:
        flags.append({"level": "urgent", "text": f"{elder} asked for help at {urgent_today[0]['time']}."})
    if unconf:
        flags.append({"level": "attention", "text": "Not confirmed: "
                      + _join([f"{s['medication']} ({s['time_label']})" for s in unconf]) + "."})
    if low_today:
        flags.append({"level": "attention", "text": f"{elder} reported a low mood today."})
    elif recent_low >= 2:
        flags.append({"level": "attention", "text": "Mood has been low on more than one day this week."})
    if not moods_today and now.hour >= 12:
        flags.append({"level": "info", "text": "No mood check-in yet today."})

    if urgent_today:
        headline = f"{elder} asked for help. Please check in now."
    elif unconf:
        headline = f"{elder} hasn't confirmed {_join([s['medication'] for s in unconf])}."
    elif low_today:
        headline = f"{elder} said they're feeling low today."
    elif any(s["status"] == "due" for s in slots_today):
        due = [s["medication"] for s in slots_today if s["status"] == "due"]
        headline = f"{_join(due)} {'is' if len(set(due)) == 1 else 'are'} due now for {elder}."
    elif slots_today and all(s["status"] in ("taken", "upcoming") for s in slots_today):
        taken = sum(1 for s in slots_today if s["status"] == "taken")
        headline = f"{elder} is on track today ({taken} of {len(slots_today)} doses confirmed)."
    else:
        headline = f"No news from {elder} yet today."
    return {"ok": True, "elder_name": elder, "caregiver_name": cg, "caregiver_relation": p["caregiver_relation"],
            "now": label(now.strftime("%H:%M")), "demo_clock": CLOCK.is_demo, "headline": headline, "flags": flags,
            "doses_today": [_public(s) for s in slots_today], "mood_today": moods_today, "messages": msgs,
            "history": history, "summary": headline + (" " + " ".join(f["text"] for f in flags) if flags else "")}


# --------------------------------------------------------------------------- demo data
def seed_demo() -> dict:
    """Wipe everything and load a believable week. Clearly labelled demo data."""
    rng = random.Random(7)
    with db() as conn:
        for t in ("dose_log", "mood_log", "messages", "medications"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("REPLACE INTO profile VALUES (1, 'Rose', 'Priya', 'daughter')")
        meds = [("Metformin", "500 mg", ["08:00", "20:00"], "with food"),
                ("Amlodipine", "5 mg", ["08:00"], ""),
                ("Vitamin D", "1 tablet", ["13:00"], "with lunch")]
        ids = []
        for name, dose, times, notes in meds:
            cur = conn.execute("INSERT INTO medications(name, dose, times, notes) VALUES (?,?,?,?)",
                               (name, dose, json.dumps(times), notes))
            ids.append((cur.lastrowid, times))
        today = CLOCK.now().date()
        skipped = {(4, "Metformin", "20:00"), (2, "Vitamin D", "13:00")}
        for back in range(6, 0, -1):
            day = today - timedelta(days=back)
            for (mid, times), (name, *_rest) in zip(ids, meds):
                for slot in times:
                    if (back, name, slot) in skipped:
                        continue
                    when = _slot_dt(day.isoformat(), slot) + timedelta(minutes=rng.randint(0, 25))
                    conn.execute("INSERT INTO dose_log(med_id, day, slot, taken_at) VALUES (?,?,?,?)",
                                 (mid, day.isoformat(), slot, when.isoformat()))
        moods = [(6, 4, "Nice walk in the garden"), (5, 4, "Spoke to my grandson"), (4, 5, "Felt wonderful today"),
                 (3, 3, "Quiet day"), (2, 3, ""), (1, 2, "Rainy and a bit lonely")]
        for back, score, note in moods:
            ts = _slot_dt((today - timedelta(days=back)).isoformat(), "18:30")
            conn.execute("INSERT INTO mood_log(ts, day, score, note, flagged) VALUES (?,?,?,?,?)",
                         (ts.isoformat(), ts.date().isoformat(), score, note, int(score <= 2)))
        ts = _slot_dt((today - timedelta(days=3)).isoformat(), "17:10")
        conn.execute("INSERT INTO messages(ts, day, text, urgent) VALUES (?,?,?,0)",
                     (ts.isoformat(), ts.date().isoformat(), "Could you call me this weekend?"))
    return {"ok": True, "summary": "Demo data loaded: 3 medicines and a week of history for Rose."}
