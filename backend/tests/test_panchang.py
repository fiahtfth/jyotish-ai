"""Panchang + electional timing + report tests."""
import os, sys, json, uuid
from datetime import date

os.environ["JYOTISH_DATABASE_URL"] = "sqlite:////tmp/jyotish_test.db"
os.environ["JYOTISH_LLM_PROVIDER"] = "offline"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.astro import panchang as PA  # noqa: E402
from app.astro import report as RP    # noqa: E402
from app.astro import precision as P  # noqa: E402
from app.astro.engine import engine, BirthInput  # noqa: E402

B = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
               second=0, lat=13.0827, lon=80.2707, tz_offset=5.5,
               place_label="Chennai", birth_time_precision="exact")
PLACE = PA.place_of(B)
DAY = date(2027, 3, 1)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_auth_throttle():
    """Many tests register users from the same TestClient IP."""
    from app.main import reset_auth_throttle
    reset_auth_throttle()
    yield
    reset_auth_throttle()


def make_facts():
    return engine.compute(B)


# ---------- name tables ----------

def test_tithi_names():
    assert PA._tithi_name(1) == "Pratipada"
    assert PA._tithi_name(15) == "Purnima"
    assert PA._tithi_name(16) == "Pratipada"   # Krishna paksha restarts
    assert PA._tithi_name(30) == "Amavasya"
    assert PA._tithi_class(4) == "Rikta"
    assert PA._tithi_class(15) == "Purna"


def test_karana_names():
    assert PA._karana_name(1) == "Kimstughna"
    assert PA._karana_name(2) == "Bava"
    assert PA._karana_name(8) == "Vishti"      # end of first movable cycle
    assert PA._karana_name(58) == "Shakuni"
    assert PA._karana_name(60) == "Naga"


# ---------- daily panchang ----------

def test_daily_panchang_shape():
    pan = PA.daily_panchang(DAY, PLACE)
    assert pan["date"] == "2027-03-01"
    assert 1 <= pan["tithi"]["index"] <= 30
    assert 1 <= pan["nakshatra"]["index"] <= 27
    assert 1 <= pan["yoga"]["index"] <= 27
    assert 1 <= pan["karana"]["index"] <= 60
    assert 0 <= pan["vaara"]["index"] <= 6
    assert pan["vaara"]["name"] == PA.VAARA_NAMES[pan["vaara"]["index"]]
    assert pan["vaara"]["lord"] == PA.VAARA_LORDS[pan["vaara"]["index"]]
    for key in ("rahu_kaalam", "yamaganda", "gulika", "abhijit"):
        s, e = pan["windows"][key]
        assert s < e and ":" in s
    dm = pan["windows"]["durmuhurta"]
    assert len(dm) in (2, 4) and dm[0] < dm[1]
    assert pan["moon"] and 0 <= pan["moon"]["sign"] <= 11
    assert "personal" not in pan          # no natal chart supplied


def test_personal_layer():
    facts = make_facts()
    pan = PA.daily_panchang(DAY, PLACE, facts)
    per = pan["personal"]
    janma = facts["planets"]["Moon"]["nakshatra"]["index"]
    ti, tn = P.tara_of(pan["nakshatra"]["index"], janma)
    assert per["tara"]["index"] == ti and per["tara"]["name"] == tn
    assert per["tara"]["adverse"] == (ti in P.ADVERSE_TARAS)
    expected_cs = ((pan["moon"]["sign"] - facts["planets"]["Moon"]["sign"])
                   % 12) == 7
    assert per["chandrashtama"] == expected_cs


def test_personal_moon_and_saturn_layers():
    facts = make_facts()
    pan = PA.daily_panchang(DAY, PLACE, facts)
    per = pan["personal"]
    assert 1 <= per["moon_house_from_janma"] <= 12
    assert per["chandrashtama"] == (per["moon_house_from_janma"] == 8)
    sfm = per["saturn_from_moon"]
    assert 1 <= sfm["house"] <= 12
    assert sfm["sade_sati"] == (sfm["house"] in (12, 1, 2))
    assert sfm["ashtama"] == (sfm["house"] == 8)
    assert sfm["kantaka"] == (sfm["house"] == 4)


def test_choghadiya_structure():
    pan = PA.daily_panchang(DAY, PLACE)
    ch = pan["choghadiya"]
    assert len(ch["day"]) == 8 and len(ch["night"]) == 8
    for slot in ch["day"] + ch["night"]:
        assert slot["name"] == PA.CHOGHADIYA_NAMES[slot["type"]]
        assert slot["good"] == (slot["type"] in PA.CHOGHADIYA_GOOD)
        assert ":" in slot["start"] and ":" in slot["end"]
    # every day offers at least two good slots
    assert sum(s["good"] for s in ch["day"]) >= 2


def test_vaara_matches_civil_weekday():
    """Regression: drik.vaara at the second-rounded sunrise jd flips the
    weekday on ~half of all days — it must be read at the noon jd."""
    for d in range(1, 8):
        when = date(2027, 3, d)
        pan = PA.daily_panchang(when, PLACE)
        assert pan["vaara"]["index"] == (when.weekday() + 1) % 7


def test_dms_to_hours_day_offset_suffix():
    # drik emits 'HH:MM:SS (+1)' past midnight / '(-1)' before — parse both
    assert PA._dms_to_hours("01:30:00 (+1)") == 25.5
    assert PA._dms_to_hours("23:00:00 (-1)") == -1.0
    assert PA._dms_to_hours("10:15:00") == 10.25


def test_hhmm_never_emits_60():
    assert PA._hhmm(6.9999) == "07:00"      # round() used to give '06:60'
    assert PA._hhmm(25.5) == "01:30"


def test_suggest_days_isolates_failures(monkeypatch):
    facts = make_facts()
    real = PA._score_day
    def flaky(f, b, p, when, a):
        if when == DAY:
            raise ValueError("simulated drik failure")
        return real(f, b, p, when, a)
    monkeypatch.setattr(PA, "_score_day", flaky)
    sug = PA.suggest_days(facts, B, DAY, days=10)
    assert sug["failed_days"] == 1
    assert sug["scanned_days"] == 10


# ---------- timing suggestions ----------

def test_detect_activity():
    assert PA.detect_activity("when should I buy a car") == "home"
    assert PA.detect_activity("best day to sign the contract") == "finance"
    assert PA.detect_activity("good time to travel") == "travel"
    assert PA.detect_activity("suitable time for the exam") == "education"
    assert PA.detect_activity("best time this month") == "general"


def test_detect_activity_word_boundaries():
    # substring bugs: "car" ⊂ "career", "trip" ⊂ "strip", "move" ⊂ "remove"
    assert PA.detect_activity("best day for a career change") == "new_work"
    assert PA.detect_activity("good time to strip the walls") != "travel"
    assert PA.detect_activity("best day to remove old files") != "travel"
    assert PA.detect_activity("best day to deal with the paperwork") == "finance"
    assert PA.detect_activity("best day for dealing with paperwork") != "finance"
    assert PA.detect_activity("the foundation of the plan") != "new_work"


def test_suggest_days_structure():
    facts = make_facts()
    sug = PA.suggest_days(facts, B, DAY, days=30, activity="finance")
    assert sug["scanned_days"] == 30
    assert 1 <= len(sug["days"]) <= 3
    scores = [d["score"] for d in sug["days"]]
    assert scores == sorted(scores, reverse=True)
    for d in sug["days"]:
        assert 1 <= d["score"] <= 5
        assert d["reasons"]               # score implies at least one reason
        win = d["suggested_window"]
        assert win and ":" in win["start"] and ":" in win["end"]
        # suggested window must not fall inside Rahu Kaalam
        rk = d["avoid"]["rahu_kaalam"]
        s_h = PA._dms_to_hours(win["start"] + ":00" if len(win["start"]) == 5
                               else win["start"])
        e_h = PA._dms_to_hours(win["end"] + ":00" if len(win["end"]) == 5
                               else win["end"])
        assert not (s_h < PA._dms_to_hours(rk[1])
                    and e_h > PA._dms_to_hours(rk[0]))


def test_suggest_days_deterministic():
    facts = make_facts()
    a = PA.suggest_days(facts, B, DAY, days=30)
    b = PA.suggest_days(facts, B, DAY, days=30)
    assert [d["date"] for d in a["days"]] == [d["date"] for d in b["days"]]
    assert [d["score"] for d in a["days"]] == [d["score"] for d in b["days"]]


def _fake_pan(**over):
    pan = {
        "windows": {"rahu_kaalam": ("10:00:00", "11:30:00"),
                    "yamaganda": ("14:00:00", "15:00:00"),
                    "gulika": ("16:00:00", "17:00:00"),
                    "durmuhurta": ["12:00:00", "12:30:00"],
                    "abhijit": ("11:50:00", "12:35:00")},   # overlaps durmuhurta
        "sunrise": {"time": "06:00"}, "sunset": {"time": "18:00"},
        "choghadiya": {"day": [
            {"type": 3, "name": "Amrit", "good": True,
             "start": "07:30", "end": "09:00"},
            {"type": 0, "name": "Udveg", "good": False,
             "start": "09:00", "end": "10:30"},
            {"type": 5, "name": "Shubha", "good": True,
             "start": "10:30", "end": "12:00"}],
            "night": []}}
    pan.update(over)
    return pan


def test_clean_window_prefers_good_choghadiya():
    win = PA._clean_window(_fake_pan())
    # abhijit is dirty -> first clean GOOD choghadiya wins
    assert win == {"start": "07:30", "end": "08:30",
                   "kind": "choghadiya:Amrit"}


def test_clean_window_falls_back_without_choghadiya():
    pan = _fake_pan()
    del pan["choghadiya"]
    win = PA._clean_window(pan)
    assert win["kind"] == "open" and win["start"] == "06:00"


def test_score_day_tolerates_missing_facts():
    # suggest_days on a chart-less call must not KeyError on "personal"
    r = PA._score_day(None, B, PLACE, DAY, "general")
    assert r["date"] == DAY.isoformat()


# ---------- report ----------

def test_report_structure_with_predictions():
    facts = make_facts()
    rep = RP.build_report(facts, B, calibrated=True,
                          predictions_allowed=True,
                          today=date(2027, 1, 15))
    assert rep["predictions_allowed"] is True
    assert len(rep["domains"]) == 7
    for d in rep["domains"]:
        assert d["confirmation"] in ("Both confirmation methods support", "Mostly aligned",
                                     "Mixed indications", "Hidden friction",
                                     "Unavailable")
        assert "%" not in json.dumps(d)
    assert rep["chart"]["lagna"]["sign"]
    assert "reading" in rep and "%" not in "".join(rep["reading"])
    assert any("Twelve-month outlook" in l for l in rep["reading"])
    health = next(d for d in rep["domains"] if d["domain"] == "health")
    assert health["disclaimer"]


def test_report_paused_predictions():
    facts = make_facts()
    rep = RP.build_report(facts, B, calibrated=False,
                          predictions_allowed=False)
    assert rep["domains"] == [] and rep["watch_months"] == []
    assert any("paused" in l for l in rep["reading"])
    # chart facts are still fully present even when predictions are off
    assert rep["chart"]["moon"]["nakshatra"]["name"]


def test_report_mangal_dosha_and_today_section():
    facts = make_facts()
    rep = RP.build_report(facts, B, calibrated=True,
                          predictions_allowed=False)
    md = rep["chart"]["mangal_dosha"]
    assert set(md) == {"present", "house_from_lagna", "also_from_moon"}
    assert 1 <= md["house_from_lagna"] <= 12
    t = rep["today"]
    assert t["tara"]["name"] and 1 <= t["moon_house_from_janma"] <= 12
    if md["present"]:
        assert any("Mangal" in l for l in rep["reading"])
    assert json.dumps(rep)                       # whole section JSON-safe


def test_report_pattern_ignores_bug_reports():
    from app.chat import orchestrator as O
    assert not O.REPORT_PAT.search("i want to report a bug")
    assert not O.REPORT_PAT.search("report a problem with the chart")
    assert O.REPORT_PAT.search("give me my report")
    assert O.REPORT_PAT.search("full reading please")


def test_daily_pattern():
    from app.chat import orchestrator as O
    assert O.DAILY_PAT.search("how is today for me")
    assert O.DAILY_PAT.search("how's my day tomorrow")
    assert O.DAILY_PAT.search("daily horoscope")
    assert not O.DAILY_PAT.search("how is my career going")


def test_timing_pattern_false_positives():
    from app.chat import orchestrator as O
    assert not O.TIMING_PAT.search("have a good day")
    assert not O.TIMING_PAT.search("we had a good time at the party")
    assert not O.TIMING_PAT.search("which day is it today")
    assert O.TIMING_PAT.search("good day to invest")
    assert O.TIMING_PAT.search("which day is best for the exam")
    assert O.TIMING_PAT.search("when should I travel")


# ---------- chat integration ----------

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import init_db
    init_db()
    return TestClient(app)


ARJUN = dict(display_name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
             place_name="Chennai", place_state="Tamil Nadu", place_country="India",
             latitude=13.0827, longitude=80.2707, birth_time_precision="exact")


def _new_user():
    c = _client()
    email = f"pa_{uuid.uuid4().hex[:8]}@test.dev"
    tok = c.post("/api/auth/register",
                 json={"terms_accepted": True, "email": email, "password": "password123"}).json()["access_token"]
    h = {"authorization": f"Bearer {tok}"}
    c.put("/api/profile", json=ARJUN, headers=h)
    return c, h


def _calibrated_client():
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    for _ in range(3):
        c.post("/api/chat/send", json={"text": "Yes, that happened"}, headers=h)
    return c, h


def test_panchang_chat_unauthenticated_gate_free():
    """Panchang is factual — available before calibration passes."""
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    # answer every pending check until the profile leaves 'pending'
    # (event count can vary), so the panchang ask lands in a steady state
    for _ in range(8):
        if c.get("/api/profile", headers=h).json()["calibration_state"] != "pending":
            break
        rr = c.post("/api/chat/send", json={"text": "No, that didn't happen"},
                    headers=h)
        assert rr.status_code == 200
    r = c.post("/api/chat/send", json={"text": "what's today's panchang?"},
               headers=h)
    assert r.status_code == 200
    m = next((m for m in reversed(r.json()) if m.get("kind") == "panchang"), None)
    assert m is not None, [(_m.get("kind"), _m.get("content")) for _m in r.json()]
    pan = m["meta"]["panchang"]
    assert pan["tithi"]["name"] and pan["nakshatra"]["name"]
    assert "Rahu Kaalam" in m["content"]


def test_timing_chat_gated_then_allowed():
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    # uncalibrated: timing question routed through the prediction gate
    r = c.post("/api/chat/send",
               json={"text": "when should I buy a car?"}, headers=h)
    body = " ".join(m["content"] for m in r.json()).lower()
    assert "suggested window" not in body

    c, h = _calibrated_client()
    r = c.post("/api/chat/send",
               json={"text": "when should I buy a car?"}, headers=h)
    assert r.status_code == 200
    m = next(m for m in reversed(r.json())
             if m.get("kind") == "timing")
    assert m["meta"]["timing"]["activity"] == "home"
    assert m["meta"]["timing"]["days"]
    assert "screened out" in m["content"]


def test_report_chat_calibrated():
    c, h = _calibrated_client()
    r = c.post("/api/chat/send",
               json={"text": "give me a full report on my chart"}, headers=h)
    assert r.status_code == 200
    m = next(m for m in reversed(r.json()) if m.get("kind") == "report")
    rep = m["meta"]["report"]
    assert rep["predictions_allowed"] is True
    assert len(rep["domains"]) == 7
    assert "Twelve-month outlook" in m["content"]
    assert "%" not in m["content"]


def test_report_chat_gated():
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    r = c.post("/api/chat/send",
               json={"text": "show me my report"}, headers=h)
    body = " ".join(m["content"] for m in r.json()).lower()
    assert "twelve-month outlook" not in body


def test_panchang_during_calibration_keeps_event_pending():
    """Mid-calibration, a panchang question is answered factually and the
    pending check is re-asked — not swallowed or treated as an answer."""
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    r = c.post("/api/chat/send", json={"text": "what's today's panchang?"},
               headers=h)
    assert r.status_code == 200
    kinds = [m.get("kind") for m in r.json()]
    assert "panchang" in kinds, [(m.get("kind"), m.get("content"))
                                 for m in r.json()]
    assert "options" in kinds                    # the check is re-asked
    assert c.get("/api/profile",
                headers=h).json()["calibration_state"] == "pending"


def test_daily_reading_gate_free():
    c, h = _new_user()
    c.get("/api/chat/history", headers=h)
    for _ in range(8):
        if c.get("/api/profile",
                 headers=h).json()["calibration_state"] != "pending":
            break
        c.post("/api/chat/send", json={"text": "No, that didn't happen"},
               headers=h)
    r = c.post("/api/chat/send", json={"text": "how is today for me?"},
               headers=h)
    m = next((m for m in reversed(r.json()) if m.get("kind") == "panchang"),
             None)
    assert m is not None, [(m.get("kind"), m.get("content"))
                           for m in r.json()]


def test_why_after_timing_shows_reasoning():
    c, h = _calibrated_client()
    c.post("/api/chat/send", json={"text": "when should I buy a car?"},
           headers=h)
    r = c.post("/api/chat/send", json={"text": "why"}, headers=h)
    body = " ".join(m["content"] for m in r.json()).lower()
    assert "ranked" in body or "scored" in body, body
