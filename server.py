"""Hearth MCP server (Streamable HTTP) + the demo web app.

One process serves three things:
  /mcp          the real MCP endpoint (Streamable HTTP). This is what a voice assistant connects to.
  /             the demo page: a voice-assistant simulator + the caregiver's dashboard
  /api/...      small helper endpoints for the demo page. They call the same MCP tools over MCP.
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from . import core
from .assistant import mcp_call, respond

HOST = os.environ.get("HEARTH_HOST", "127.0.0.1")
PORT = int(os.environ.get("HEARTH_PORT", "8765"))
STATIC = Path(__file__).parent / "static"

INSTRUCTIONS = """Hearth helps a family look after an older person who lives independently.
The elder talks to a voice assistant; the assistant calls these tools; a family caregiver sees a short summary.

Rules for any assistant using these tools:
- Never give medical advice or suggest changing, doubling or skipping a dose. Send those questions to a pharmacist or doctor.
- A dose nobody confirmed is 'unconfirmed', not 'missed'.
- If the person describes an emergency, call alert_caregiver AND tell them to contact local emergency services.
- Speak warmly, in short sentences. Use the `summary` field of each result as a safe starting point."""

mcp = MCPServer("hearth", title="Hearth: daily check-ins for elders", instructions=INSTRUCTIONS, version="1.0.0")


# ----------------------------------------------------------------------------- tools
@mcp.tool()
def list_medications_today() -> dict:
    """List every medicine dose scheduled for today with its status: taken, due (now), upcoming, or
    unconfirmed (past its window and nobody has said it was taken)."""
    return core.list_medications_today()


@mcp.tool()
def whats_next() -> dict:
    """Say which medicine is due right now or comes next, and mention earlier doses that are still unconfirmed."""
    return core.whats_next()


@mcp.tool()
def log_dose_taken(medication: str) -> dict:
    """Record that the elder took a medicine. Use the medicine name as the person said it (spelling can be rough).
    It is matched to the dose that is due or most recent. It will not record a dose that is not due yet."""
    return core.log_dose_taken(medication)


@mcp.tool()
def log_mood(score: int, note: str = "") -> dict:
    """Record how the elder feels today. score: 1 (very low) to 5 (great). note: their own words, if any.
    The result says whether to offer to tell the caregiver."""
    return core.log_mood(score, note)


@mcp.tool()
def get_daily_checkin() -> dict:
    """Start the daily check-in: a greeting, today's medicine summary, and whether to ask how they feel."""
    return core.get_daily_checkin()


@mcp.tool()
def send_caregiver_message(message: str, urgent: bool = False) -> dict:
    """Send a short message from the elder to their caregiver. Only send when the elder asks for it or agrees to it."""
    return core.send_caregiver_message(message, urgent)


@mcp.tool()
def alert_caregiver(reason: str) -> dict:
    """Urgently alert the caregiver (the elder asked for help, fell, or described an emergency). This does NOT call
    emergency services, so also tell the elder to call their local emergency number."""
    return core.alert_caregiver(reason)


@mcp.tool()
def get_caregiver_summary(days: int = 7) -> dict:
    """Caregiver view: headline, flags that need attention, today's doses, mood, messages, and a daily history
    for the last `days` days (1 to 14)."""
    return core.get_caregiver_summary(days)


@mcp.tool()
def add_medication(name: str, dose: str = "", times: list[str] | None = None, notes: str = "") -> dict:
    """Add or update a medicine. times: one or more times of day such as '8am', '1:30 pm' or '20:00'."""
    return core.add_medication(name, dose, times, notes)


@mcp.tool()
def remove_medication(name: str) -> dict:
    """Stop scheduling a medicine. Past records are kept."""
    return core.remove_medication(name)


@mcp.tool()
def setup_profile(elder_name: str, caregiver_name: str, caregiver_relation: str = "family member") -> dict:
    """Set who is being looked after and who the caregiver is."""
    return core.setup_profile(elder_name, caregiver_name, caregiver_relation)


# ----------------------------------------------------------------------------- demo web app
@mcp.custom_route("/", methods=["GET"])
async def index(_: Request):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@mcp.custom_route("/api/health", methods=["GET"])
async def health(_: Request):
    return JSONResponse({"ok": True, "demo_clock": core.CLOCK.is_demo, "mcp_endpoint": "/mcp"})


@mcp.custom_route("/api/chat", methods=["POST"])
async def chat(request: Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return JSONResponse({"error": "Say or type something first."}, status_code=400)
    return JSONResponse(await respond(text))


@mcp.custom_route("/api/summary", methods=["GET"])
async def summary(_: Request):
    result = await mcp_call("get_caregiver_summary", {"days": 7})
    return JSONResponse(result["data"])


@mcp.custom_route("/api/medications", methods=["POST"])
async def medications(request: Request):
    body = await request.json()
    times = [t.strip() for t in str(body.get("times", "")).split(",") if t.strip()]
    result = await mcp_call("add_medication", {"name": str(body.get("name", "")), "dose": str(body.get("dose", "")),
                                               "times": times})
    return JSONResponse(result)


@mcp.custom_route("/api/clock", methods=["POST"])
async def clock(request: Request):
    body = await request.json()
    value = body.get("time")
    try:
        core.CLOCK.set(value) if value else core.CLOCK.clear()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "demo_clock": core.CLOCK.is_demo})


@mcp.custom_route("/api/reset", methods=["POST"])
async def reset(_: Request):
    from . import assistant
    assistant.SESSION["pending"] = None
    return JSONResponse(core.seed_demo())


# ----------------------------------------------------------------------------- run
def build_app():
    from mcp.server.transport_security import TransportSecuritySettings

    security = None
    if HOST not in ("127.0.0.1", "localhost"):
        # Running somewhere public: allow the real host name(s). Set HEARTH_ALLOWED_HOSTS="myapp.example.com".
        hosts = [h.strip() for h in os.environ.get("HEARTH_ALLOWED_HOSTS", "*").split(",") if h.strip()]
        security = TransportSecuritySettings(enable_dns_rebinding_protection=hosts != ["*"],
                                             allowed_hosts=[] if hosts == ["*"] else hosts,
                                             allowed_origins=[])
    return mcp.streamable_http_app(host=HOST, transport_security=security)


def main() -> None:
    with core.db() as conn:
        empty = conn.execute("SELECT COUNT(*) c FROM medications").fetchone()["c"] == 0
    if empty:
        core.seed_demo()
    print(f"\n  Hearth is running.\n  Open the demo:   http://{HOST}:{PORT}/\n  MCP endpoint:    http://{HOST}:{PORT}/mcp\n")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
