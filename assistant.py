"""The voice-assistant simulator.

On a real Alexa+ device, the assistant's language model listens, decides which tool to use, and calls
the MCP server. This file plays that part for the demo, so anyone can try Hearth without an Alexa device.

Important: every action goes through the real MCP protocol (Streamable HTTP, `mcp.Client`).
Nothing here imports the care logic directly except the user's own name and contacts, which a real
assistant would already know about its user.

The language understanding here is deliberately simple (patterns, not a language model). That keeps the
demo fast, free and predictable. The tools do not care who calls them.
"""
from __future__ import annotations

import json
import os
import re
from difflib import get_close_matches
from typing import Any

from mcp import Client

from . import core

SESSION: dict[str, Any] = {"pending": None}   # a follow-up we are waiting on, e.g. "shall I tell Priya?"


def _url() -> str:
    host = os.environ.get("HEARTH_HOST", "127.0.0.1")
    host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{host}:{os.environ.get('HEARTH_PORT', '8765')}/mcp"


def _parse(result) -> dict:
    text = result.content[0].text if result.content else "{}"
    if getattr(result, "is_error", False):
        return {"ok": False, "summary": text.split("\n")[0]}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": True, "summary": text}


async def mcp_call(name: str, args: dict | None = None) -> dict:
    """One tool call over MCP. Returns {'tool', 'args', 'ok', 'data'}."""
    async with Client(_url()) as client:
        data = _parse(await client.call_tool(name, args or {}))
    return {"tool": name, "args": args or {}, "ok": bool(data.get("ok", True)), "data": data}


# ----------------------------------------------------------------------------- language patterns
def _clean(text: str) -> str:
    text = text.lower().replace("\u2019", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s':/]", " ", text)).strip()


EMERGENCY_RE = re.compile(
    r"\b(emergency|i fell|i have fallen|i've fallen|fallen down|can'?t breathe|cannot breathe|chest pain|"
    r"heart attack|stroke|call (an )?ambulance|i fainted|i'm bleeding|going to faint|about to faint|feel faint|"
    r"(feel|feeling|i'm feeling|i am feeling) (very |really |suddenly |so )?(confused|disoriented)|"
    r"don'?t know where i am|can'?t think straight)\b|^(please )?(help( me)?|i need help)( please)?$")
MED_STRONG_RE = re.compile(
    r"\b(double|overdose|stop taking|too many|side effects?|take two|took two|two (more )?(pills|tablets|doses|of)|"
    r"extra (dose|pill|tablet)|another (dose|pill|tablet))\b")
MED_WEAK_RE = re.compile(r"\b(skip|forgot|forget|missed|miss|twice|safe to)\b")
MED_CONTEXT_RE = re.compile(r"\b(pill|pills|tablet|tablets|medicine|medicines|medication|medications|dose|doses|meds)\b")
TOOK_RE = re.compile(r"\b(i (have |just |already |also )?(took|taken|had|swallowed|finished|popped)|"
                     r"i've (just |already )?(taken|had|swallowed))\b")
GENERIC_MED_RE = re.compile(r"\b(pill|pills|tablet|tablets|medicine|medicines|meds|medication|medications|dose|doses|"
                            r"morning|afternoon|evening|night|lunch)\b")
NEXT_RE = re.compile(r"\b(next (dose|pill|medicine|tablet|one)|what'?s next|what is next|when (do|should) i (take|have)|"
                     r"what should i take|is it time|time for my (pills|medicine|meds))\b")
SCHEDULE_RE = re.compile(r"\b(what|which)\b.*\b(medicine|medicines|pills|meds|medication|tablets)\b|"
                         r"\b(my )?(schedule|medicine list|medication list|pill list)\b|\bwhat do i (take|need to take)\b")
CHECKIN_RE = re.compile(r"^(good (morning|afternoon|evening)|hello|hi|hey|check ?in|daily check ?in|how am i doing|"
                        r"start my check ?in)\b")
YES_RE = re.compile(r"^(yes|yeah|yep|yup|sure|please|ok|okay|go ahead|do that|please do)\b")
NO_RE = re.compile(r"^(no|nope|not now|don't|no thanks|no thank you|that's ok|leave it)\b")
THANKS_RE = re.compile(r"\b(thanks|thank you|bye|goodbye|good night|that's all)\b")
CAPS_RE = re.compile(r"\b(what can you do|what can i say|how do you work|what do you do)\b")

NOT_WELL_RE = re.compile(r"\bnot (so |very |feeling |too )?(good|well|great|fine|okay|ok)\b")
VERY_LOW = ["terrible", "awful", "horrible", "miserable", "really bad", "very bad", "worst", "dreadful"]
LOW = ["sad", "down", "low", "lonely", "worried", "anxious", "unwell", "sick", "dizzy", "achy", "sore", "bad",
       "under the weather", "in pain", "pain", "depressed", "scared", "unhappy", "nauseous", "a bit off"]
GREAT = ["great", "wonderful", "fantastic", "happy", "cheerful", "excellent", "amazing", "marvellous"]
GOOD = ["good", "fine", "well", "better", "nice", "content", "calm", "pleasant", "relaxed"]
OKAY = ["ok", "okay", "alright", "so so", "meh", "tired", "sleepy", "average"]
MOOD_CONTEXT_RE = re.compile(r"\b(feel|feeling|felt|mood|i'm|i am|i've been|been|day)\b")


def _has(words: list[str], text: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def mood_score(text: str) -> int | None:
    m = re.search(r"\b([1-5])\s*(?:out of|/)\s*5\b", text) or re.search(r"\bmood (?:is|was)? ?([1-5])\b", text)
    if m:
        return int(m.group(1))
    short = len(text.split()) <= 3
    if text in ("ok", "okay"):
        return None   # a bare "okay" is an acknowledgement, not a mood
    if not (MOOD_CONTEXT_RE.search(text) or short):
        return None
    if NOT_WELL_RE.search(text):
        return 2
    if "not bad" in text:
        return 4
    for score, words in ((1, VERY_LOW), (2, LOW), (5, GREAT), (4, GOOD), (3, OKAY)):
        if _has(words, text):
            return score
    return None


def _period(text: str) -> tuple[str, str] | None:
    if "morning" in text:
        return ("00:00", "11:59")
    if "afternoon" in text:
        return ("12:00", "16:59")
    if "lunch" in text:
        return ("11:00", "15:00")
    if "evening" in text or "night" in text:
        return ("17:00", "23:59")
    return None


def _mentioned(names: list[str], text: str) -> list[str]:
    found = []
    words = [w for w in text.split() if len(w) >= 5]
    for n in names:
        nn = core._norm(n)
        if nn in text or any(get_close_matches(w, [nn], cutoff=0.8) for w in words):
            found.append(n)
    return found


# ----------------------------------------------------------------------------- the conversation
async def respond(utterance: str) -> dict:
    p = core.get_profile()
    elder, cg = p["elder_name"], p["caregiver_name"]
    text = _clean(utterance)
    calls: list[dict] = []

    async with Client(_url()) as client:
        async def call(name: str, **args) -> dict:
            data = _parse(await client.call_tool(name, args))
            calls.append({"tool": name, "args": args, "ok": bool(data.get("ok", True)), "summary": data.get("summary", "")})
            return data

        cache: dict[str, dict] = {}

        async def listing() -> dict:
            if "list" not in cache:
                cache["list"] = await call("list_medications_today")
            return cache["list"]

        def done(reply: str, intent: str, pending: bool = False) -> dict:
            return {"reply": reply, "intent": intent, "tools": calls, "waiting_for_answer": pending}

        # --- answering a question we asked last turn
        pending = SESSION.get("pending")
        if pending:
            SESSION["pending"] = None
            if pending["action"] == "compose" and not NO_RE.match(text):
                r = await call("send_caregiver_message", message=f"{elder}: {utterance.strip()}")
                return done(f"Done. I've sent that to {cg}.", "message") if r["ok"] else done(r["summary"], "message")
            if pending["action"] == "notify":
                if YES_RE.match(text):
                    r = await call("send_caregiver_message", message=pending["text"])
                    return done(f"Okay, I've let {cg} know. I'm here if you need anything else.", "notify")
                if NO_RE.match(text):
                    return done("Alright, I'll leave it. I'm here if you change your mind.", "notify")

        # --- emergencies come first, always
        if EMERGENCY_RE.search(text):
            await call("alert_caregiver", reason=utterance.strip())
            return done(f"I've alerted {cg} right now. If this is an emergency, please call "
                        f"{core.EMERGENCY} straight away. I'm staying right here with you.", "emergency")

        # --- questions about changing doses are not ours to answer
        weak = MED_WEAK_RE.search(text) and (MED_CONTEXT_RE.search(text) or _mentioned(
            sorted({d["medication"] for d in (await listing()).get("doses", [])}), text))
        if MED_STRONG_RE.search(text) or weak:
            SESSION["pending"] = {"action": "notify", "text": f"{elder} has a question about their medicine: \"{utterance.strip()}\""}
            return done("I can't tell you what to do about a dose, and I don't want you to guess. "
                        "Please ask your pharmacist or doctor. Would you like me to let "
                        f"{cg} know so they can help?", "medicine_question", True)

        # --- message the caregiver
        names = [re.escape(x) for x in {cg.lower(), p["caregiver_relation"].lower(), "caregiver", "daughter", "son", "family"} if x]
        m = re.search(rf"\b(tell|message|text|let|inform|write to|send (a )?message to)\b.{{0,20}}?\b({'|'.join(names)})\b", text)
        if m:
            rest = re.split(rf"\b(?:{'|'.join(names)})\b", utterance, maxsplit=1, flags=re.I)[-1]
            rest = re.sub(r"^[\s,:\-]*(know\b|that\b)?[\s,:\-]*(that\b)?[\s,:\-]*", "", rest, flags=re.I).strip()
            if not rest:
                SESSION["pending"] = {"action": "compose"}
                return done(f"Of course. What would you like to say to {cg}?", "message", True)
            await call("send_caregiver_message", message=f"{elder}: {rest}")
            return done(f"Done. I've sent that to {cg}.", "message")

        # --- taking medicine
        if TOOK_RE.search(text) and (GENERIC_MED_RE.search(text) or re.search(r"\b(took|taken|had my|take my)\b", text)):
            doses = (await listing()).get("doses", [])
            names = sorted({d["medication"] for d in doses})
            named = _mentioned(names, text)
            targets: list[str] = []
            if named:
                targets = named
            elif GENERIC_MED_RE.search(text):
                window = _period(text)
                inside = lambda d: not window or window[0] <= d["time"] <= window[1]
                pool = [d for d in doses if d["status"] == "due" and inside(d)]
                if not pool:
                    pool = [d for d in doses if d["status"] == "unconfirmed" and inside(d)]
                targets = [d["medication"] for d in pool]
            if targets:
                results = [await call("log_dose_taken", medication=t) for t in targets]
                oks = [r for r in results if r["ok"]]
                bad = [r for r in results if not r["ok"]]
                parts = []
                if oks:
                    parts.append(f"Lovely. I've noted {core._join([r['medication'] for r in oks])} as taken.")
                    if any(r.get("late") for r in oks):
                        parts.append("I've marked it as a little late, so it's accurate.")
                parts += [r["summary"] for r in bad]
                if oks:
                    nxt = await call("whats_next")
                    if nxt.get("next") and nxt["next"]["status"] == "upcoming":
                        parts.append(f"Next up is {nxt['next']['medication']} at {core.spoken(nxt['next']['time'])}.")
                    elif nxt.get("due_now"):
                        parts.append(f"You've still got {core._join([d['medication'] for d in nxt['due_now']])} to take.")
                    else:
                        parts.append("That's everything for now.")
                return done(" ".join(parts), "log_dose")
            if GENERIC_MED_RE.search(text):
                nxt = await call("whats_next")
                return done("I don't see a dose due right now. " + nxt["summary"], "log_dose")

        # --- greetings and the daily check-in
        if CHECKIN_RE.match(text):
            r = await call("get_daily_checkin")
            return done(r["summary"], "checkin", bool(r.get("questions")))

        # --- mood
        score = mood_score(text)
        if score is not None and not (NEXT_RE.search(text) or SCHEDULE_RE.search(text)):
            r = await call("log_mood", score=score, note=utterance.strip())
            if r.get("urgent_keywords"):
                await call("alert_caregiver", reason=f"{elder} said: {utterance.strip()}")
                return done(f"I'm worried about that, {elder}. I've alerted {cg}. If this is an emergency, "
                            f"please call {core.EMERGENCY} now.", "emergency")
            if score >= 4:
                return done(f"I'm glad to hear that, {elder}. I've noted it down.", "mood")
            if score == 3:
                return done(f"Thanks for telling me, {elder}. I've noted it down.", "mood")
            SESSION["pending"] = {"action": "notify", "text": f"{elder} said: \"{utterance.strip()}\" (mood logged as low)"}
            extra = ""
            if any(k in r.get("concern_keywords", []) for k in ("dizzy", "pain", "breath", "chest", "faint")):
                extra = f" If it gets worse, please speak to your doctor, or call {core.EMERGENCY} if it feels urgent."
            return done(f"I'm sorry you're not feeling your best, {elder}. I've noted it.{extra} "
                        f"Would you like me to let {cg} know?", "mood", True)

        # --- what's next / schedule
        if NEXT_RE.search(text):
            r = await call("whats_next")
            return done(r["summary"], "whats_next")
        if SCHEDULE_RE.search(text):
            r = await call("list_medications_today")
            return done(r["summary"], "schedule")

        if CAPS_RE.search(text):
            return done(f"I can keep track of your medicines, tell you what's next, note how you're feeling, "
                        f"and send a message to {cg}. Try saying: I took my morning pills.", "help")
        if text in ("ok", "okay", "alright", "all right"):
            return done("Alright. I'm here if you need me.", "ack")
        if THANKS_RE.search(text):
            return done(f"You're very welcome, {elder}. I'm here whenever you need me.", "thanks")

        return done(f"Sorry, I didn't catch that. You can tell me which pills you've taken, ask what's next, "
                    f"say how you're feeling, or ask me to message {cg}.", "unknown")
