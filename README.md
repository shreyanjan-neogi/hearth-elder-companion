# Hearth

**Voice check-ins for the people we look after.**

Hearth helps a family keep an eye on an older person who lives on their own, without calling every day and without
the older person having to learn anything new. They just talk: *"I took my morning pills."* *"I feel a bit lonely."*
*"I fell."* A voice assistant turns that into a few calm actions, and the family member sees a short, honest summary
on their phone.

Built for the **Alexa+ track** of the *Build, Ship, Shape: Amazon Developer Hackathon*.

## What is in the box

| Piece | What it is |
|---|---|
| **Hearth MCP server** | A real, self-hosted MCP server over **Streamable HTTP** at `/mcp`. It exposes 11 tools for medicines, mood, messages and alerts. Any MCP client can connect to it, including a voice assistant like Alexa+. |
| **Voice-assistant simulator** | A web page that plays the part of the assistant: you talk (or type), it picks tools and **calls the MCP server over MCP**, then speaks the answer. A panel shows every tool call as it happens. |
| **Caregiver dashboard** | A phone-sized view of what the family member would see: a one-line headline, anything that needs attention, today's doses, mood, a 7-day chart and messages. It reads its data through the same MCP tools. |

```
  Rose talks  ──►  voice assistant  ──MCP (Streamable HTTP)──►  Hearth MCP server  ──►  SQLite
 (living room)    (simulated here;                              /mcp   11 tools           │
                   Alexa+ in real life)                                                   │
                                                                                          ▼
                                            Priya's phone  ◄──── get_caregiver_summary ◄──┘
```

## Run it

You need **Python 3.10 or newer** and an internet connection for the first start.

- **Windows:** double-click `start.bat`
- **Mac / Linux:** run `./start.sh`

The first start sets itself up (about a minute). Your browser opens at **http://127.0.0.1:8765/**.
Use **Chrome** for the microphone; any browser works if you type instead.

Prefer the command line?

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m hearth.server
```

Settings (all optional, environment variables): `HEARTH_PORT` (8765), `HEARTH_TZ` (Asia/Kolkata),
`HEARTH_EMERGENCY_NUMBER` (shown in safety messages, for example `112` or `911`), `HEARTH_DB`.

## Try it

Use the **Demo time** menu (top right) to jump to 8:20 AM, then tap the lamp and say, or tap a phrase:

1. *"Good morning"* starts the daily check-in.
2. *"I took my morning pills"* makes two real tool calls and updates the phone.
3. *"I took my vitamin D"* is refused politely, because it is not time yet.
4. *"I feel a bit lonely"* is logged, and the assistant offers to tell Priya. Say *"yes"*.
5. *"Can I take two metformin?"* is **not answered**. It points to a pharmacist or doctor and offers to tell Priya.
6. *"I fell"* alerts Priya at once and tells Rose to call the local emergency number.

Switch the demo time to 1:10 PM to see the morning doses shown as **not confirmed** on the phone.

## The tools

| Tool | What it does |
|---|---|
| `get_daily_checkin` | Greeting, today's medicine summary, and whether to ask how they feel |
| `list_medications_today` | Every dose today: taken, due, upcoming or not confirmed |
| `whats_next` | What is due now or next, plus earlier doses nobody has confirmed |
| `log_dose_taken` | Records a dose (tolerates rough spelling; refuses doses that are not due) |
| `log_mood` | Records a 1 to 5 mood with the person's own words; flags worrying words |
| `send_caregiver_message` | Sends a short message to the caregiver |
| `alert_caregiver` | Urgent alert; also returns an instruction to call local emergency services |
| `get_caregiver_summary` | Headline, flags, today's doses, mood, messages and a daily history |
| `add_medication`, `remove_medication`, `setup_profile` | Setup |

## Designed to be safe

Elder care is not a place to be clever, so a few rules are built in and covered by tests:

- **No medical advice.** Questions about doubling, skipping or forgetting a dose are never answered. The assistant
  points to a pharmacist or doctor and offers to tell the caregiver.
- **"Not confirmed", never "missed".** Hearth cannot know whether a pill was taken, only whether someone said so.
- **It will not log a dose that is not due**, so a mistaken "I took it" cannot hide a real gap.
- **Emergencies come first.** Falls, chest pain, trouble breathing, fainting and sudden confusion alert the caregiver
  immediately. Hearth always says it **cannot call emergency services** and tells the person to do so.
- **Nothing is sent to the caregiver without the person's say-so**, except emergencies.

## Honest limitations

- The assistant in this repo is a **simulator** that uses simple language patterns, not a language model. It exists so
  the project runs anywhere, free, with predictable results. The MCP server does not depend on it. We have **not** tested
  against a real Alexa+ device or the Alexa+ Preview.
- It is a **single-household demo** with **no login**. Do not put real health data in it, and do not expose it to
  the internet as it is.
- The data you see is **made-up demo data** (a person named Rose and her daughter Priya).
- Dates and times use `HEARTH_TZ`. The *Demo time* menu fakes the clock for demos only.
- The page was checked by running its script against the live server in a simulated browser; it has not been
  checked visually on every device.

## Tests

```bash
pip install pytest
python -m pytest -q
```

30 tests cover the care logic, and also start the real server and check, over real MCP, that the negotiated protocol
version is **2025-11-25 or later** (the SDK negotiates `2026-07-28`), that tools list and run, and that the safety
rules above hold.

## Project layout

```
hearth/core.py        care logic and storage (no MCP code, easy to test)
hearth/server.py      MCP server (Streamable HTTP) + demo web routes
hearth/assistant.py   voice-assistant simulator; calls the server over MCP
hearth/static/        the demo page
tests/                unit and end-to-end tests
```

## License

MIT. See `LICENSE`.
