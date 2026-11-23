"""Trust and safety: unknown-time Moon chart, chart markers, minors, consent, residence, distress."""
import json
import uuid
from datetime import date

import pytest

from tests import test_jyotish as T
from tests.test_jyotish import client, send, ARJUN, _reset_auth_throttle  # noqa: F401 (autouse)
from app.chat import safety


@pytest.fixture
def model(monkeypatch):
    from app.llm import providers
    calls = []

    def generate(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return "Model reply.", "groq"

    monkeypatch.setattr(providers, "generate", generate)
    return calls


def _register(age_confirmed=True):
    email = f"ts_{uuid.uuid4().hex[:8]}@test.dev"
    body = {"terms_accepted": True, "email": email, "password": "password123"}
    if age_confirmed is not None:
        body["age_confirmed"] = age_confirmed
    return client.post("/api/auth/register", json=body)


def _user(profile=None):
    r = _register()
    assert r.status_code == 200, r.text
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    r = client.put("/api/profile", json=profile or ARJUN, headers=h)
    assert r.status_code == 200, r.text
    return h


def _open(h):
    T._open_calibrated(h)


# ---------------------------------------------------------------- age confirmation

def test_registration_requires_age_confirmation():
    assert _register(age_confirmed=None).status_code == 422
    assert _register(age_confirmed=False).status_code == 422
    r = _register()
    assert r.status_code == 200
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=h).json()["age_confirmed"] is True
    assert client.get("/api/auth/me/export", headers=h).json()["account"]["age_confirmed_at"]


# ---------------------------------------------------------------- unknown birth time

UNKNOWN = {**ARJUN, "hour": 12, "minute": 0, "birth_time_precision": "unknown"}
FORBIDDEN_KEYS = ("bhava", "shadbala", "bhava_bala", "education", "yogas", "ashtakavarga")


def test_unknown_time_model_context_has_no_lagna_data(model):
    h = _user(UNKNOWN)
    _open(h)
    send("how is my career looking?", h)
    call = model[-1]
    facts = call["facts"]
    assert facts["lagna"]["chandra_lagna"] is True
    assert facts["lagna"]["sign_name"] == facts["planets"]["Moon"]["sign_name"]
    assert facts["planets"]["Moon"]["house"] == 1
    assert facts["bhava"] == {} and set(facts["vargas"]) == {"D1"}
    for key in FORBIDDEN_KEYS[1:]:
        assert key not in facts
    assert "arudha_lagna" not in facts["jaimini"] and "arudhas" not in facts["jaimini"]
    assert not facts["functional"].get("benefics")
    assert call["analysis"] is None
    assert "UNKNOWN" in call["context_note"] and "Chandra Lagna" in call["context_note"]
    from app.llm import providers
    brief = providers._facts_brief(facts, birth=call.get("birth"), today=call.get("today"), domain="career")
    assert "BIRTH TIME UNKNOWN" in brief
    assert "Lagna: Taurus" not in brief and "House lords from Lagna" not in brief
    assert "Arudhas" not in brief and "bhava-chalit" not in brief


def test_unknown_time_chart_endpoint_is_moon_chart(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "KP_ENABLED", True)       # off by default (Phase 4 flags)
    h = _user(UNKNOWN)
    r = client.get("/api/chart/D1", headers=h).json()
    assert r["chandra_lagna"] is True
    assert r["chart"]["Lagna"]["sign"] == r["chart"]["Moon"]["sign"]
    assert client.get("/api/chart/D9", headers=h).status_code == 404
    assert client.get("/api/kp", headers=h).status_code == 409
    dash = client.get("/api/chart-dashboard", headers=h).json()
    assert dash["time_known"] is False and set(dash["vargas"]) == {"D1"}


def test_moon_sign_change_day_gives_both_possibilities(model):
    # 2024-01-02 (Chennai): the Moon moves from Libra into Scorpio late that day in sidereal terms
    from app.astro.engine import BirthInput
    from app import moonmode
    changed = None
    for d in range(1, 29):
        b = BirthInput("x", 2024, 1, d, 12, 0, 0, 13.0827, 80.2707, 5.5, "Chennai")
        info = moonmode.moon_possibilities(b)
        if info["sign_changes"]:
            changed = (d, info)
            break
    assert changed, "the Moon changes sign within any 28 days"
    day, info = changed
    assert len(info["possibilities"]) == 2
    assert info["possibilities"][0]["sign_name"] != info["possibilities"][1]["sign_name"]
    assert info["sign_change_about"]
    h = _user({**UNKNOWN, "year": 2024, "month": 1, "day": day})
    _open(h)
    send("what does my future hold?", h)
    facts = model[-1]["facts"]
    mm = facts["moon_mode"]
    assert mm["sign_changes"] and len(mm["houses_if_moon_in"]) == 2
    assert "uncertain" in model[-1]["context_note"]
    from app.llm import providers
    assert "changes sign on the birth date" in providers._facts_brief(facts)


def test_approximate_time_is_labelled_provisional(model):
    h = _user({**ARJUN, "birth_time_precision": "approximate"})
    _open(h)
    send("how is my career looking?", h)
    assert "provisional" in model[-1]["context_note"]
    assert model[-1]["facts"]["lagna"].get("chandra_lagna") is None   # real Lagna still supplied


def test_exact_time_keeps_lagna_in_model_context(model):
    h = _user()
    _open(h)
    send("how is my career looking?", h)
    assert model[-1]["facts"]["lagna"]["sign_name"] == "Taurus"
    assert "UNKNOWN" not in model[-1]["context_note"]


def test_unknown_time_chart_request_in_chat_is_moon_chart():
    h = _user(UNKNOWN)
    _open(h)
    out = send("show my D9 chart", h)
    assert "needs a birth time" in out[-1]["content"]
    out = send("show my chart", h)
    assert out[-1]["kind"] == "chart" and out[-1]["meta"]["chandra_lagna"] is True


# ---------------------------------------------------------------- chart markers

def test_markers_merged_and_nodes_never_retrograde():
    from app import moonmode
    from app.chat import orchestrator
    from app.db import SessionLocal, BirthProfile
    h = _user()
    d1 = client.get("/api/chart/D1", headers=h).json()["chart"]
    d9 = client.get("/api/chart/D9", headers=h).json()["chart"]
    for chart in (d1, d9):
        assert "retrograde" in chart["Sun"] or "retrograde" in chart["Saturn"]
        assert "retrograde" not in chart["Rahu"] and "retrograde" not in chart["Ketu"]
    assert all("combust" in v for n, v in d1.items() if n not in ("Lagna", "Rahu", "Ketu"))
    facts = {"planets": {"Mars": {"retrograde": True, "combust": True}, "Rahu": {"retrograde": True, "combust": False}}}
    out = moonmode.merge_markers(facts, {"Mars": {"sign": 1, "degree": 1}, "Rahu": {"sign": 2, "degree": 3}}, "D1")
    assert out["Mars"]["retrograde"] and out["Mars"]["combust"]
    assert "retrograde" not in out["Rahu"]
    d9m = moonmode.merge_markers(facts, {"Mars": {"sign": 1, "degree": 1}}, "D9")
    assert d9m["Mars"]["retrograde"] and "combust" not in d9m["Mars"]
    dash = client.get("/api/chart-dashboard", headers=h).json()
    assert "retrograde" in dash["vargas"]["D1"]["Sun"] and "retrograde" not in dash["vargas"]["D1"]["Rahu"]


# ---------------------------------------------------------------- minors

def _minor_profile():
    today = date.today()
    return {**ARJUN, "year": today.year - 14, "month": 3, "day": 10, "relation": "son",
            "permission_confirmed": True}


def test_minor_intercept_blocks_romance_and_health():
    assert safety.private_reply("when will I get married?", minor=True)
    assert safety.private_reply("how is my health", minor=True)
    assert safety.private_reply("do I have a girlfriend in the chart", minor=True)
    assert safety.private_reply("which stream suits me?", minor=True) is None
    assert safety.private_reply("when will I get married?") is None


def test_minor_chat_intercept_and_aptitude_note(model):
    h = _user(_minor_profile())
    assert client.get("/api/profile", headers=h).json()["is_minor"] is True
    _open(h)
    out = send("when will he get married?", h)
    assert out[-1]["kind"] == "private" and "under 18" in out[-1]["content"]
    assert not model
    send("which stream suits him?", h)
    assert "aptitude" in model[-1]["context_note"]
    adult = _user()
    assert client.get("/api/profile", headers=adult).json()["is_minor"] is False


# ---------------------------------------------------------------- consent withdrawal

def test_withdraw_consent_switches_to_computed_only(monkeypatch):
    from app.llm import providers
    seen = []

    def generate(messages, **kw):
        seen.append(kw["allow_external"])
        return "Model reply.", "groq"

    monkeypatch.setattr(providers, "generate", generate)
    h = _user()
    _open(h)
    send("how is my career looking?", h)
    assert seen[-1] is True
    r = client.post("/api/auth/me/withdraw-consent", headers=h)
    assert r.status_code == 200 and r.json()["ai_processing_enabled"] is False
    me = client.get("/api/auth/me", headers=h).json()
    assert me["ai_processing_enabled"] is False and me["llm_consent"] is False
    send("how is my career looking?", h)
    assert seen[-1] is False
    assert client.get("/api/auth/me/export", headers=h).json()["account"]["ai_withdrawn_at"]
    assert client.post("/api/auth/me/withdraw-consent", headers=h).status_code == 200   # idempotent
    r = client.post("/api/auth/me/resume-consent", json={"terms_accepted": True}, headers=h)
    assert r.json()["ai_processing_enabled"] is True
    send("how is my career looking?", h)
    assert seen[-1] is True


def test_withdrawn_account_gets_computed_reply_without_external_call(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "k")

    def boom(*a, **k):
        raise AssertionError("external provider must not be called")

    monkeypatch.setitem(providers.PROVIDERS, "gemini", boom)
    h = _user()
    _open(h)
    client.post("/api/auth/me/withdraw-consent", headers=h)
    out = send("what is my lagna?", h)
    assert "Taurus" in out[-1]["content"]


# ---------------------------------------------------------------- residence and gender

def test_residence_and_gender_round_trip(model):
    h = _user({**ARJUN, "gender": "female", "residence_name": "Bengaluru", "residence_state": "Karnataka",
               "residence_country": "India", "residence_latitude": 12.9716, "residence_longitude": 77.5946})
    p = client.get("/api/profile", headers=h).json()
    assert p["gender"] == "female" and p["residence_name"] == "Bengaluru"
    assert p["residence_latitude"] == pytest.approx(12.9716) and p["residence_timezone_name"] == "Asia/Kolkata"
    assert p["place_name"] == "Chennai"
    # an edit that omits the optional fields keeps them
    again = client.put("/api/profile", json=ARJUN, headers=h).json()
    assert again["gender"] == "female" and again["residence_name"] == "Bengaluru"
    _open(h)
    send("how is my career looking?", h)
    assert "lives in Bengaluru" in model[-1]["context_note"]
    # clearing
    cleared = client.put("/api/profile", json={**ARJUN, "residence_name": "", "gender": "prefer_not_to_say"}, headers=h).json()
    assert cleared["residence_name"] == "" and cleared["gender"] == "prefer_not_to_say"
    assert client.put("/api/profile", json={**ARJUN, "gender": "x"}, headers=h).status_code == 422


# ---------------------------------------------------------------- distress / gambling / legal / medical

@pytest.mark.parametrize("text", [
    "mujhe marna hai", "main mar jaunga", "zindagi khatam kar dunga", "suicide karna chahta hoon",
    "jeena nahi chahta", "khud ko khatam kar lunga", "मुझे मरना है", "मैं मर जाऊँगा", "ज़िंदगी खत्म करनी है",
    "thatkolai panna poren", "chanipovalani undi", "I want to die",
])
def test_hinglish_and_regional_distress_gets_crisis_reply(text):
    reply = safety.private_reply(text)
    assert reply and "14416" in reply


def test_distress_chat_never_reaches_model(model):
    h = _user()
    _open(h)
    out = send("mujhe marna hai", h)
    assert out[-1]["kind"] == "private" and "14416" in out[-1]["content"]
    assert not model


@pytest.mark.parametrize("text", [
    "which lottery number will win this week", "satta matka ka number batao", "bitcoin kab kharidu",
    "when should I bet on the IPL match", "will I win the jackpot",
])
def test_gambling_is_declined(text):
    reply = safety.private_reply(text)
    assert reply and "don't predict" in reply


def test_legal_questions_get_a_no_verdict_note():
    assert "lawyer" in safety.context_note("will I win my court case?")
    assert safety.context_note("how is my career") == ""


def test_medical_diagnosis_is_declined():
    reply = safety.private_reply("do I have cancer?")
    assert reply and "diagnose" in reply
    assert safety.private_reply("how is my health in 2027") is None


def test_remedy_note_is_graded_and_cautious():
    note = safety.context_note("which gemstone should I wear?")
    assert "Rahu, Ketu or Saturn" in note and "trial" in note and "paid pujas" in note


def test_unknown_time_profile_gets_no_generated_birth_time_questions():
    from types import SimpleNamespace as NS
    from app.chat import orchestrator as o
    prof = NS(birth_time_precision="unknown")
    assert o._ensure_events(None, prof, {}) == 0
