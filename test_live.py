"""End-to-end tests against the real running server, over real MCP (Streamable HTTP)."""
import asyncio
import json
import urllib.request

import pytest
from mcp import Client


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def say(base, text):
    return post(base, "/api/chat", {"text": text})


def test_mcp_protocol_and_tools(live_server):
    async def go():
        async with Client(live_server + "/mcp") as c:
            tools = await c.list_tools()
            names = {t.name for t in tools.tools}
            result = await c.call_tool("list_medications_today", {})
            return c.protocol_version, names, json.loads(result.content[0].text)
    version, names, data = asyncio.run(go())
    assert version >= "2025-11-25", f"required spec is 2025-11-25 or later, got {version}"
    assert {"log_dose_taken", "log_mood", "alert_caregiver", "get_caregiver_summary", "whats_next"} <= names
    assert data["ok"] and data["doses"]


def test_voice_flow(live_server):
    post(live_server, "/api/reset", {})
    post(live_server, "/api/clock", {"time": "08:20"})

    r = say(live_server, "Good morning")
    assert r["intent"] == "checkin" and "Good morning, Rose" in r["reply"]            # greeting is not a mood

    r = say(live_server, "I took my morning pills")
    assert r["intent"] == "log_dose"
    assert [c["tool"] for c in r["tools"]].count("log_dose_taken") == 2
    assert "Amlodipine" in r["reply"] and "Metformin" in r["reply"] and "Vitamin D at 1 PM" in r["reply"]

    r = say(live_server, "I took my vitamin d")
    assert "isn't time" in r["reply"]                                                  # refuses to log a dose that is not due

    r = say(live_server, "I feel a bit lonely")
    assert r["intent"] == "mood" and r["waiting_for_answer"]
    r = say(live_server, "yes")
    assert r["tools"][0]["tool"] == "send_caregiver_message"

    r = say(live_server, "Tell Priya I'm going to the market")
    assert r["intent"] == "message" and r["tools"][0]["args"]["message"] == "Rose: I'm going to the market"

    r = say(live_server, "let Priya know I took my pills")                             # a message, not a dose
    assert r["intent"] == "message"


def test_never_advises_on_doses(live_server):
    post(live_server, "/api/reset", {})
    for q in ["can I take two metformin", "should I double my dose", "I forgot my amlodipine", "can I skip my pills"]:
        r = say(live_server, q)
        assert r["intent"] == "medicine_question", q
        assert "pharmacist or doctor" in r["reply"], q
        assert not any(c["tool"] == "log_dose_taken" for c in r["tools"]), q
    assert say(live_server, "no")["intent"] == "notify"


def test_emergencies(live_server):
    post(live_server, "/api/reset", {})
    for q in ["I fell", "I have chest pain", "I can't breathe", "help me", "I feel confused", "I feel faint", "I don't know where I am"]:
        r = say(live_server, q)
        assert r["intent"] == "emergency", q
        assert any(c["tool"] == "alert_caregiver" for c in r["tools"]), q
        assert "emergency number" in r["reply"], q
    # "help" inside a normal sentence is not an emergency
    assert say(live_server, "can you help me with my medicines")["intent"] != "emergency"
    assert say(live_server, "I'm confused about which pill is which")["intent"] != "emergency"


def test_dashboard_reflects_conversation(live_server):
    post(live_server, "/api/reset", {})
    post(live_server, "/api/clock", {"time": "13:10"})
    s = json.load(urllib.request.urlopen(live_server + "/api/summary"))
    assert "hasn't confirmed" in s["headline"]
    say(live_server, "I fell")
    s = json.load(urllib.request.urlopen(live_server + "/api/summary"))
    assert s["flags"][0]["level"] == "urgent"


def test_page_is_served(live_server):
    html = urllib.request.urlopen(live_server + "/").read().decode()
    assert "Hearth" in html and "/api/chat" in html
