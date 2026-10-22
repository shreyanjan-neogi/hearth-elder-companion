"""Tests for the care logic. Run with:  python -m pytest -q"""
import pytest


@pytest.mark.parametrize("text,expected", [
    ("8am", "08:00"), ("8:30 pm", "20:30"), ("20:00", "20:00"), ("12am", "00:00"), ("12pm", "12:00"),
    ("morning", "08:00"), ("9 PM", "21:00"),
])
def test_parse_time(core, text, expected):
    assert core.parse_time(text) == expected


@pytest.mark.parametrize("bad", ["", "banana", "25:00", "8:75"])
def test_parse_time_rejects_nonsense(core, bad):
    with pytest.raises(ValueError):
        core.parse_time(bad)


def test_spoken_and_label(core):
    assert core.spoken("13:00") == "1 PM"
    assert core.spoken("08:05") == "8:05 AM"
    assert core.label("00:00") == "12:00 AM"
    assert core.label("13:05") == "1:05 PM"


def test_statuses_at_morning(core):
    core.CLOCK.set("08:20")
    doses = core.list_medications_today()["doses"]
    by = {(d["medication"], d["time"]): d["status"] for d in doses}
    assert by[("Metformin", "08:00")] == "due"
    assert by[("Amlodipine", "08:00")] == "due"
    assert by[("Vitamin D", "13:00")] == "upcoming"
    assert by[("Metformin", "20:00")] == "upcoming"


def test_unconfirmed_is_never_called_missed(core):
    core.CLOCK.set("13:10")
    r = core.list_medications_today()
    assert any(d["status"] == "unconfirmed" for d in r["doses"])
    assert "missed" not in str(r).lower()


def test_log_dose_and_not_due_yet(core):
    core.CLOCK.set("08:20")
    ok = core.log_dose_taken("Metformin")
    assert ok["ok"] and ok["slot"] == "08:00" and not ok["late"]
    too_early = core.log_dose_taken("Vitamin D")
    assert not too_early["ok"] and too_early["error"] == "not_due_yet"
    # the evening Metformin is hours away, so a second "I took it" must not be recorded
    again = core.log_dose_taken("Metformin")
    assert not again["ok"] and again["error"] == "not_due_yet"


def test_already_logged(core):
    core.CLOCK.set("21:00")
    assert core.log_dose_taken("Vitamin D")["ok"]          # late for 1 PM
    assert core.log_dose_taken("Vitamin D")["error"] == "already_logged"


def test_late_dose_is_marked_late(core):
    core.CLOCK.set("11:00")
    r = core.log_dose_taken("Amlodipine")
    assert r["ok"] and r["late"] and r["slot"] == "08:00"


def test_fuzzy_medicine_names(core):
    core.CLOCK.set("08:20")
    assert core.log_dose_taken("metformine")["ok"]          # rough spelling from speech
    assert core.log_dose_taken("my amlodipine tablet")["ok"]
    nf = core.log_dose_taken("aspirin")
    assert nf["error"] == "medication_not_found" and "Metformin" in nf["known_medications"]


def test_whats_next(core):
    core.CLOCK.set("08:20")
    r = core.whats_next()
    assert "Amlodipine" in r["summary"] and "Vitamin D at 1 PM" in r["summary"]
    core.CLOCK.set("13:10")
    r = core.whats_next()
    assert "haven't heard" in r["summary"]                  # morning doses still unconfirmed


def test_mood_flags(core):
    assert core.log_mood(5, "lovely day")["flagged"] is False
    low = core.log_mood(2, "I feel lonely")
    assert low["flagged"] and low["suggest_notify_caregiver"] and "lonely" in low["concern_keywords"]
    assert core.log_mood(3, "I feel confused")["urgent_keywords"] == ["confused"]
    assert core.log_mood(99, "x")["score"] == 5             # clamped


def test_alert_never_claims_to_call_emergency_services(core):
    r = core.alert_caregiver("I fell")
    assert r["ok"] and "cannot call emergency services" in r["guidance"]
    s = core.get_caregiver_summary()
    assert s["flags"][0]["level"] == "urgent"
    assert "asked for help" in s["headline"]


def test_caregiver_summary_story(core):
    core.CLOCK.set("13:10")
    s = core.get_caregiver_summary()
    assert "hasn't confirmed" in s["headline"]
    assert any(f["level"] == "attention" for f in s["flags"])
    assert len(s["history"]) == 7
    assert s["history"][-2]["mood"] == 2.0                  # the seeded low-mood day


def test_add_and_remove_medication(core):
    assert core.add_medication("Atorvastatin", "10 mg", ["9pm"])["ok"]
    assert core.add_medication("Foo", "", [])["error"] == "times_required"
    assert core.add_medication("Foo", "", ["banana"])["error"] == "bad_time"
    assert core.add_medication("Atorvastatin", "20 mg", ["9pm", "9am"])["summary"].startswith("Updated")
    assert core.remove_medication("atorvastatin")["ok"]
    assert core.remove_medication("nothing")["error"] == "medication_not_found"


def test_messages(core):
    assert core.send_caregiver_message("  ")["error"] == "empty_message"
    assert core.send_caregiver_message("I'm fine")["to"] == "Priya"
