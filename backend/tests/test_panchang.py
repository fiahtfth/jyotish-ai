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


# ---------- timing suggestions ----------

def test_detect_activity():
    assert PA.detect_activity("when should I buy a car") == "home"
    assert PA.detect_activity("best day to sign the contract") == "finance"
    assert PA.detect_activity("good time to travel") == "travel"
    assert PA.detect_activity("suitable time for the exam") == "education"
    assert PA.detect_activity("best time this month") == "general"


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


# ---------- report ----------

def test_report_structure_with_predictions():
    facts = make_facts()
    rep = RP.build_report(facts, B, calibrated=True,
                          predictions_allowed=True,
                          today=date(2027, 1, 15))
    assert rep["predictions_allowed"] is True
    assert len(rep["domains"]) == 7
    for d in rep["domains"]:
        assert d["confirmation"] in ("High conviction", "Mostly aligned",
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
                 json={"email": email, "password": "password123"}).json()["access_token"]
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
    for _ in range(3):
        c.post("/api/chat/send", json={"text": "No, that didn't happen"},
               headers=h)
    r = c.post("/api/chat/send", json={"text": "what's today's panchang?"},
               headers=h)
    assert r.status_code == 200
    m = next(m for m in reversed(r.json()) if m.get("kind") == "panchang")
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
