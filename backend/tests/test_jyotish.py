"""Jyotish AI test suite: calculations, calibration gate, verifier, sensitivity."""
import os, sys, json, uuid

os.environ["JYOTISH_DATABASE_URL"] = "sqlite:////tmp/jyotish_test.db"
os.environ["JYOTISH_LLM_PROVIDER"] = "offline"
os.environ["JYOTISH_JWT_SECRET"] = "test-only-jwt-secret-" + uuid.uuid4().hex
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

if os.path.exists("/tmp/jyotish_test.db"):
    os.remove("/tmp/jyotish_test.db")

from app.main import app  # noqa: E402
from app.db import init_db  # noqa: E402
from app.policy import TERMS_VERSION  # noqa: E402
from app.astro.engine import engine, BirthInput  # noqa: E402
from app.astro import verify as V  # noqa: E402
from app.astro import calibration as C  # noqa: E402

init_db()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_auth_throttle():
    """Many tests register users from the same TestClient IP."""
    from app.main import reset_auth_throttle
    reset_auth_throttle()
    yield
    reset_auth_throttle()

ARJUN = dict(display_name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
             place_name="Chennai", place_state="Tamil Nadu", place_country="India",
             latitude=13.0827, longitude=80.2707, birth_time_precision="exact")


# ---------- 1. Deterministic calculation regression ----------

def make_facts():
    b = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
                   second=0, lat=13.0827, lon=80.2707, tz_offset=5.5,
                   place_label="Chennai", birth_time_precision="exact")
    return b, engine.compute(b)

def test_engine_deterministic():
    _, f1 = make_facts(); _, f2 = make_facts()
    assert json.dumps(f1["planets"], sort_keys=True) == json.dumps(f2["planets"], sort_keys=True)

def test_known_positions():
    """Swiss Ephemeris reference: 1990-05-15 06:15 IST Chennai, Lahiri, mean nodes.
    Verified against pyswisseph directly — tolerance 0.35°."""
    _, f = make_facts()
    p = f["planets"]
    # Sun just ingressed sidereal Taurus (0.22°); Moon in Sagittarius / Uttara Ashadha
    assert p["Sun"]["sign"] == 1 and 0.0 < p["Sun"]["degree"] < 0.6
    assert p["Moon"]["sign"] == 8 and 27.0 < p["Moon"]["degree"] < 28.5
    assert p["Moon"]["nakshatra"]["name"] == "Uttara Ashadha"
    # Rahu/Ketu in Capricorn/Cancer for mid-1990 (mean nodes)
    assert p["Rahu"]["sign"] == 9 and p["Ketu"]["sign"] == 3
    # Lagna Taurus
    assert f["lagna"]["sign"] == 1
    # all 9 grahas present with houses
    for name in ("Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn","Rahu","Ketu"):
        assert 1 <= p[name]["house"] <= 12, name

def test_locked_facts_shape():
    _, f = make_facts()
    for key in ("meta","lagna","planets","houses","functional","vimshottari","jaimini",
                "sarvastakavarga","vargas"):
        assert key in f, key
    assert len(f["jaimini"]["karakas"]) == 7
    assert len(f["jaimini"]["arudhas"]) == 12
    assert "D9" in f["vargas"] and "D10" in f["vargas"] and "D60" in f["vargas"]

def test_birth_time_sensitivity():
    """A 20-minute change must move Lagna degree but keep the pipeline stable."""
    b1 = BirthInput("A",1990,5,15,6,15,0,13.0827,80.2707,5.5,"Chennai")
    b2 = BirthInput("A",1990,5,15,6,35,0,13.0827,80.2707,5.5,"Chennai")
    f1, f2 = engine.compute(b1), engine.compute(b2)
    assert f1["lagna"]["degree"] != f2["lagna"]["degree"]
    assert f1["planets"]["Sun"]["sign"] == f2["planets"]["Sun"]["sign"]  # Sun robust

def test_vimshottari_covers_120_years():
    _, f = make_facts()
    ps = f["vimshottari"]["periods"]
    span = ps[-1]["end_jd"] - ps[0]["start_jd"]
    assert 118*365 < span < 121*365
    # antar-dasha rows all inside their own maha period ordering
    assert all(p["end_jd"] > p["start_jd"] for p in ps)


# ---------- 2. Factual verifier ----------

def test_verifier_passes_truth():
    _, f = make_facts()
    sun_sign = f["planets"]["Sun"]["sign_name"]
    r = V.verify_response(f"Your Sun is in {sun_sign}.", f, {})
    assert r["ok"], r["issues"]

def test_verifier_catches_wrong_sign():
    _, f = make_facts()
    wrong = "Sagittarius" if f["planets"]["Sun"]["sign_name"] != "Sagittarius" else "Leo"
    r = V.verify_response(f"Your Sun is in {wrong} and that means luck.", f, {})
    assert not r["ok"]
    fixed = V.repair_response(f"Your Sun is in {wrong}. Nice.", r["issues"])
    assert wrong not in fixed

def test_verifier_bans_probabilities():
    _, f = make_facts()
    r = V.verify_response("There is a 78% chance of promotion.", f, {})
    assert not r["ok"]

def test_verifier_bans_injected_degrees():
    _, f = make_facts()
    r = V.verify_response("Your Sun sits at 14.732 degrees — precise!", f, {})
    assert not r["ok"]


def test_groq_fallback_after_primary_failure(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)

    def failing(system, messages, timeout=None):
        raise RuntimeError("primary down")

    def groq_ok(system, messages, timeout=None):
        return "Fallback reply."

    monkeypatch.setitem(providers.PROVIDERS, "gemini", failing)
    monkeypatch.setitem(providers.PROVIDERS, "groq", groq_ok)
    text, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert provider == "groq"
    assert text == "Fallback reply."


def test_openrouter_fallback_after_groq_failure(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)

    def failing(system, messages, timeout=None):
        raise RuntimeError("provider down")

    def openrouter_ok(system, messages, timeout=None):
        return "OpenRouter fallback reply."

    monkeypatch.setitem(providers.PROVIDERS, "gemini", failing)
    monkeypatch.setitem(providers.PROVIDERS, "groq", failing)
    monkeypatch.setitem(providers.PROVIDERS, "openrouter", openrouter_ok)
    text, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert provider == "openrouter"
    assert text == "OpenRouter fallback reply."


def test_llm_turn_deadline_falls_back_to_offline(monkeypatch):
    import time as _time
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "LLM_TURN_DEADLINE_SECONDS", 3)
    timeouts = []

    def hanging(system, messages, timeout=None):
        timeouts.append(timeout)
        _time.sleep(min(timeout, 1.2))
        raise RuntimeError("upstream timeout")

    for name in ("gemini", "groq", "openrouter"):
        monkeypatch.setitem(providers.PROVIDERS, name, hanging)
    t0 = _time.monotonic()
    _, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert provider == "offline"
    assert _time.monotonic() - t0 < 4
    assert timeouts and all(t <= 3 for t in timeouts)


def test_llm_concurrency_limit_falls_back_to_offline(monkeypatch):
    import threading
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers, "_llm_slots", threading.BoundedSemaphore(1))
    calls = []
    monkeypatch.setitem(providers.PROVIDERS, "gemini",
                        lambda s, m, timeout=None: calls.append(1) or "LLM reply.")
    assert providers._llm_slots.acquire(blocking=False)
    try:
        _, provider = providers.generate([{"role": "user", "content": "hello"}])
    finally:
        providers._llm_slots.release()
    assert provider == "offline" and not calls
    _, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert provider == "gemini"


def test_openrouter_rejects_paid_model(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "OPENROUTER_MODEL", "openai/gpt-4")
    with pytest.raises(RuntimeError, match="free models"):
        providers._openrouter("system", [{"role": "user", "content": "hi"}])


# ---------- 3. Calibration gate via API ----------

def register_and_profile():
    email = f"t_{uuid.uuid4().hex[:8]}@test.dev"
    r = client.post("/api/auth/register", json={"terms_accepted": True, "email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    h = {"authorization": f"Bearer {tok}"}
    r = client.put("/api/profile", json=ARJUN, headers=h)
    assert r.status_code == 200, r.text
    return h

def send(text, h):
    r = client.post("/api/chat/send", json={"text": text}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()

def test_full_calibration_flow_and_gate():
    h = register_and_profile()
    msgs = client.get("/api/chat/history", headers=h).json()
    assert msgs and msgs[0]["role"] == "assistant"
    answers = ["Yes, that happened", "Yes, that happened", "Yes, that happened"]
    last = []
    for a in answers:
        last = send(a, h)
    # after 3 confirmations the gate must be open
    prof = client.get("/api/profile", headers=h).json()
    assert prof["calibration_state"] in ("calibrated", "partial")
    assert prof["predictions_allowed"] is True
    # future question now answered, not gated
    r = send("What does 2027 look like for my career?", h)
    text = " ".join(m["content"] for m in r)
    assert "calibrat" not in text.lower() or "2027" in text

def test_question_during_first_check_is_answered_in_same_turn():
    h = register_and_profile()
    hist = client.get("/api/chat/history", headers=h).json()
    assert "Continue with the reading" in hist[-1]["meta"]["options"]
    reply = send("Will I get a promotion next year?", h)
    assert reply[-1]["meta"]["analysis"]["precision"]["calibrated"] is False
    assert any("less accurate" in m["content"] for m in reply)
    cal = client.get("/api/calibration", headers=h).json()
    assert cal["state"] == "skipped" and cal["predictions_allowed"]
    assert all(not event["user_feedback"] for event in cal["events"])


def test_explicit_skip_survives_reset_and_keeps_the_partial_history():
    h = register_and_profile()
    send("No, that didn't happen", h)
    reply = send("Continue with the reading", h)
    assert "less accurate" in reply[-1]["content"]
    assert client.post("/api/chat/reset", headers=h).status_code == 200
    hist = client.get("/api/chat/history", headers=h).json()
    assert all(not m["meta"].get("event_id") for m in hist)
    events = client.get("/api/calibration", headers=h).json()["events"]
    assert [e["user_feedback"] for e in events] == ["rejected", "", ""]
    turn = _parse_sse(client.post("/api/chat/stream", json={"text": "What is my Moon sign?"}, headers=h))
    assert "Sagittarius" in turn[-1]["messages"][-1]["content"]


def test_opening_a_previously_blocked_chat_offers_a_reading_once():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    conv.state = "rectify"
    prof.calibration_state = "uncalibrated"
    prof.predictions_allowed = True
    db.commit()
    db.close()
    history = client.get("/api/chat/history", headers=h).json()
    assert "Continue with the reading" in history[-1]["meta"]["options"]
    assert client.get("/api/chat/history", headers=h).json() == history


def test_failed_checks_allow_a_career_reading():
    h = register_and_profile()
    for _ in range(3):
        out = send("No, that didn't happen", h)
    assert "less accurate" in out[-1]["content"]
    prof = client.get("/api/profile", headers=h).json()
    assert prof["calibration_state"] == "uncalibrated" and prof["predictions_allowed"]
    assert (prof["hour"], prof["minute"]) == (6, 15)
    r = send("Will I get a promotion next year?", h)
    assert r[-1]["meta"]["analysis"]["precision"]["calibrated"] is False
    assert all("less accurate" not in m["content"] for m in r)
    assert any(m["kind"] == "chart" for m in send("show me my D9 chart", h))


def test_profile_edit_retriggers_calibration():
    """Editing birth details after calibration must retire the old answers and
    re-open the calibration flow — never leave predictions dead-locked."""
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    for a in ["Yes, that happened", "Yes, that happened", "Yes, that happened"]:
        send(a, h)
    prof = client.get("/api/profile", headers=h).json()
    assert prof["predictions_allowed"] is True
    # a material birth-data change locks the gate and resets the conversation
    edited = {k: prof[k] for k in (
        "display_name","year","month","day","hour","minute","second","place_name",
        "place_state","place_country","latitude","longitude","birth_time_precision")}
    edited["hour"] = 10
    prof = client.put("/api/profile", json=edited, headers=h).json()
    assert prof["calibration_state"] == "pending"
    assert prof["predictions_allowed"] is False
    history = client.get("/api/chat/history", headers=h).json()
    assert any(m["kind"] == "options" for m in history)
    for a in ["Yes, that happened", "Yes, that happened", "Yes, that happened"]:
        send(a, h)
    prof = client.get("/api/profile", headers=h).json()
    assert prof["predictions_allowed"] is True


def test_unauthenticated_rejected():
    assert client.get("/api/chat/history").status_code in (401, 403)
    assert client.post("/api/chat/send", json={"text": "hi"}).status_code in (401, 403)


def test_api_responses_no_store():
    """API responses must never be browser-cached — per-user data isolation."""
    h = register_and_profile()
    r = client.get("/api/chat/history", headers=h)
    assert r.headers.get("cache-control") == "no-store"
    assert "authorization" in (r.headers.get("vary") or "").lower()


def test_health_domain_and_disclaimer():
    from app.astro import pillars
    from app.astro.constants import DOMAINS, HEALTH_DISCLAIMER
    from datetime import date
    assert "health" in DOMAINS and DOMAINS["health"]["disclaimer"] == HEALTH_DISCLAIMER
    b, facts = make_facts()
    r = pillars.evaluate(facts, b, "health", date(2026, 1, 1), date(2027, 6, 30))
    assert set(r["pillars"]) == {"parashari", "jaimini", "tajika", "micro_timing"}
    assert r["convergence"].startswith("Traditional convergence: ") and "/4 pillars" in r["convergence"]

    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    for a in ["Yes, that happened", "Yes, that happened", "Yes, that happened"]:
        send(a, h)
    r = send("will my health improve this year", h)
    body = " ".join(m["content"] for m in r)
    assert body.count(HEALTH_DISCLAIMER) == 1


def test_pillar_gap_features():
    """Arudha labels, Muntha-lord dignity, BAV + nakshatra evidence all reachable."""
    from app.astro import pillars
    from datetime import date
    b, facts = make_facts()
    assert facts["binnashtakavarga"] is not None
    r = pillars.evaluate(facts, b, "relationship", date(2026, 1, 1), date(2027, 6, 30))
    ev = " ".join(r["calculation_evidence_ids"])
    # targets are labeled with the significator/arudha that was touched
    assert "(Darakaraka)" in ev or "A7" in ev or "A12" in ev
    # Muntha-lord dignity and BAV bindus now appear in evidence when they fire
    assert "Muntha" in ev


def test_token_revoked_after_account_deletion():
    from jose import jwt
    from app.config import settings
    email_a = f"a_{uuid.uuid4().hex[:8]}@test.dev"
    tok_a = client.post("/api/auth/register",
                        json={"terms_accepted": True, "email": email_a, "password": "password123"}).json()["access_token"]
    ha = {"authorization": f"Bearer {tok_a}"}
    uid_a = client.get("/api/auth/me", headers=ha).json()["id"]
    assert client.delete("/api/auth/me", headers=ha).status_code == 200

    email_b = f"b_{uuid.uuid4().hex[:8]}@test.dev"
    tok_b = client.post("/api/auth/register",
                        json={"terms_accepted": True, "email": email_b, "password": "password123"}).json()["access_token"]
    uid_b = client.get("/api/auth/me", headers={"authorization": f"Bearer {tok_b}"}).json()["id"]
    assert uid_b != uid_a
    assert client.get("/api/auth/me", headers=ha).status_code == 401

    # Even if an id is reused (e.g. DB reset), a token minted for a previous
    # account (different nonce) or without a nonce must not authenticate.
    claims = jwt.decode(tok_a, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    for extra in ({"nonce": claims["nonce"]}, {}):
        forged = jwt.encode({"sub": str(uid_b), "exp": claims["exp"], **extra},
                            settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        r = client.get("/api/auth/me", headers={"authorization": f"Bearer {forged}"})
        assert r.status_code == 401


# ---------- 4. Review-fix regressions ----------

def _db_profile_and_conv(h):
    from app.db import SessionLocal, Conversation, BirthProfile
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    db = SessionLocal()
    conv = db.query(Conversation).filter(Conversation.user_id == uid).first()
    prof = db.query(BirthProfile).filter(BirthProfile.user_id == uid).first()
    return db, conv, prof


def test_existing_rectification_chat_continues_with_notice():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    conv.state = "rectify_domain"
    prof.calibration_state = "uncalibrated"
    prof.predictions_allowed = True
    db.commit()
    db.close()
    r = send("What does 2027 look like for my career?", h)
    assert any("less accurate" in m["content"] for m in r)
    assert r[-1]["meta"]["analysis"]["domain"] == "career"


def test_offline_lead_varies_with_support_count():
    from app.llm import providers
    msgs = [{"role": "user", "content": "will i get a job"}]

    def lead(support, conflict):
        a = {"domain": "career", "support_count": support, "conflict_count": conflict,
             "calculation_evidence_ids": [], "convergence": "x"}
        return providers.offline_response(msgs, None, a)
    strong, substantial, mixed, weak = lead(3, 0), lead(2, 0), lead(2, 1), lead(0, 0)
    assert "line up quite well" in strong
    assert "mostly supportive" in substantial
    assert "genuinely mixed" in mixed
    assert "weak" in weak
    assert len({strong, substantial, mixed, weak}) == 4


def test_put_profile_invalid_calendar_date_is_422():
    h = register_and_profile()
    r = client.put("/api/profile", json={**ARJUN, "month": 2, "day": 31}, headers=h)
    assert r.status_code == 422


def _status_error(code):
    import httpx
    req = httpx.Request("POST", "https://example.invalid/x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))


def test_generate_does_not_retry_on_401_but_retries_5xx(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.time, "sleep", lambda seconds: None)
    calls = {"gemini": 0, "groq": 0}

    def gemini_401(system, messages, timeout=45):
        calls["gemini"] += 1
        raise _status_error(401)

    def groq_503_then_ok(system, messages, timeout=45):
        calls["groq"] += 1
        if calls["groq"] < 2:
            raise _status_error(503)
        return "ok"

    monkeypatch.setitem(providers.PROVIDERS, "gemini", gemini_401)
    monkeypatch.setitem(providers.PROVIDERS, "groq", groq_503_then_ok)
    text, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert calls == {"gemini": 1, "groq": 2}
    assert (text, provider) == ("ok", "groq")


def test_engine_cache_is_lru_capped():
    from app.astro import engine as E
    eng = E.ChartEngine(cache_size=2)

    def b(minute):
        return BirthInput(name="x", year=1990, month=5, day=15, hour=6, minute=minute,
                          second=0, lat=13.0827, lon=80.2707, tz_offset=5.5,
                          place_label="Chennai")
    eng.compute(b(0)); eng.compute(b(1))
    eng.compute(b(0))                       # hit: b(0) becomes most recent
    eng.compute(b(2))                       # evicts b(1)
    assert len(eng._cache) == 2
    minutes = {k[4] for k in eng._cache}
    assert minutes == {0, 2}


def test_fingerprint_depends_on_birth_inputs():
    from app.astro.engine import birth_fingerprint
    b1, _ = make_facts()
    b2 = BirthInput(**{**b1.__dict__, "minute": 16})
    b3 = BirthInput(**b1.__dict__)
    assert birth_fingerprint(b1) != birth_fingerprint(b2)
    assert birth_fingerprint(b1) == birth_fingerprint(b3)


def test_login_throttled_after_10_bad_attempts():
    email = f"thr_{uuid.uuid4().hex[:8]}@test.dev"
    codes = [client.post("/api/auth/login", json={"email": email, "password": "wrongpass1"}).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_insufficient_history_state(monkeypatch):
    monkeypatch.setattr(C, "generate_statements", lambda *a, **k: [])
    h = register_and_profile()
    msgs = client.get("/api/chat/history", headers=h).json()
    assert any("enough past history" in m["content"] for m in msgs)
    prof = client.get("/api/profile", headers=h).json()
    assert prof["calibration_state"] == "insufficient_history"
    assert prof["predictions_allowed"] is True
    r = send("will i get a promotion next year", h)
    assert r[-1]["meta"]["analysis"]["precision"]["calibrated"] is False


def test_domain_detection_word_boundaries():
    from app.chat.orchestrator import detect_domain, _apply_disclaimer
    assert detect_domain("of course") is None
    assert detect_domain("my network is slow") is None
    assert detect_domain("any job change soon") == "career"
    assert detect_domain("should I do a house shift") == "relocation"
    assert detect_domain("which course should I take") == "education"
    from app.astro.constants import HEALTH_DISCLAIMER
    assert HEALTH_DISCLAIMER in _apply_disclaimer("hello", "health")
    assert detect_domain("when will I pass my exams") == "education"
    assert detect_domain("jobs") == "career"
    assert detect_domain("investing") == "finance"


def test_successful_logins_do_not_consume_email_budget():
    email = f"ok_{uuid.uuid4().hex[:8]}@test.dev"
    assert client.post("/api/auth/register", json={"terms_accepted": True, "email": email, "password": "password123"}).status_code == 200
    from app import main as M
    for _ in range(9):
        assert client.post("/api/auth/login", json={"email": email, "password": "password123"}).status_code == 200
        M._auth_attempts.pop("ip:testclient", None)   # isolate the per-email budget
    assert len(M._auth_attempts.get("email:" + email, ())) == 0
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"}).status_code == 401
        M._auth_attempts.pop("ip:testclient", None)
    r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 429


# ---------- JWT secret configuration ----------

def test_jwt_secret_required(monkeypatch):
    from app.config import _load_jwt_secret
    monkeypatch.delenv("JYOTISH_JWT_SECRET", raising=False)
    monkeypatch.delenv("JYOTISH_DEV_INSECURE_JWT", raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        _load_jwt_secret()
    monkeypatch.setenv("JYOTISH_JWT_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="shorter than 32 bytes"):
        _load_jwt_secret()

def test_jwt_secret_accepts_strong_value(monkeypatch):
    from app.config import _load_jwt_secret
    monkeypatch.setenv("JYOTISH_JWT_SECRET", "x" * 32)
    assert _load_jwt_secret() == "x" * 32

def test_jwt_secret_dev_flag_uses_random_secret(monkeypatch):
    from app.config import _load_jwt_secret
    monkeypatch.delenv("JYOTISH_JWT_SECRET", raising=False)
    monkeypatch.setenv("JYOTISH_DEV_INSECURE_JWT", "true")
    a, b = _load_jwt_secret(), _load_jwt_secret()
    assert a != b and len(a.encode()) >= 32

def test_jwt_secret_dev_flag_ignored_in_prod(monkeypatch):
    from app.config import _load_jwt_secret
    monkeypatch.delenv("JYOTISH_JWT_SECRET", raising=False)
    monkeypatch.setenv("JYOTISH_DEV_INSECURE_JWT", "true")
    monkeypatch.setenv("JYOTISH_ENV", "prod")
    with pytest.raises(RuntimeError, match="not set"):
        _load_jwt_secret()


# ---------- resource-exhaustion guards ----------

def test_profile_material_changes_rate_limited(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PROFILE_RATE_LIMIT_PER_MIN", 3)
    h = register_and_profile()  # 1st material change
    codes = []
    for minute in range(16, 22):
        r = client.put("/api/profile", json={**ARJUN, "minute": minute}, headers=h)
        codes.append(r.status_code)
    assert codes[:2] == [200, 200]
    assert all(c == 429 for c in codes[2:])
    # non-material re-submits are still accepted
    prof = client.get("/api/profile", headers=h).json()
    same = {**ARJUN, "minute": prof["minute"]}
    assert client.put("/api/profile", json=same, headers=h).status_code == 200


def test_profile_create_and_edit_by_id_share_rate_limit(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "PROFILE_RATE_LIMIT_PER_MIN", 3)
    h = register_and_profile()  # 1st material change
    mum = client.post("/api/profiles", json=MUM, headers=h)
    assert mum.status_code == 200
    r = client.put(f"/api/profiles/{mum.json()['id']}", json=dict(MUM, minute=1), headers=h)
    assert r.status_code == 200
    assert client.post("/api/profiles", json=dict(MUM, display_name="X"), headers=h).status_code == 429
    r = client.put(f"/api/profiles/{mum.json()['id']}", json=dict(MUM, minute=2), headers=h)
    assert r.status_code == 429


def test_geo_search_rate_limited(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GEO_RATE_LIMIT_PER_MIN", 2)
    h = register_and_profile()
    codes = [client.get("/api/geo/search", params={"q": "Chen"}, headers=h).status_code
             for _ in range(4)]
    assert codes == [200, 200, 429, 429]


def test_engine_cache_is_bounded():
    from app.astro.engine import ChartEngine
    e = ChartEngine(cache_size=3)
    for minute in range(5):
        e.compute(BirthInput(name="x", year=1990, month=5, day=15, hour=6,
                             minute=minute, second=0, lat=13.0827, lon=80.2707,
                             tz_offset=5.5, place_label="Chennai",
                             birth_time_precision="exact"))
    assert len(e._cache) == 3


# ---------- 5. Consent, data export, privacy ----------

def test_generate_without_user_consent_never_calls_external(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "test")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    calls = []
    for name in ("gemini", "groq", "openrouter"):
        monkeypatch.setitem(providers.PROVIDERS, name,
                            lambda s, m, timeout=None, _n=name: calls.append(_n) or "external")
    _, provider = providers.generate([{"role": "user", "content": "hello"}],
                                     allow_external=False)
    assert provider == "offline" and not calls
    _, provider = providers.generate([{"role": "user", "content": "hello"}])
    assert provider == "gemini"


def test_ai_enabled_by_accepting_signup_terms():
    h = register_and_profile()
    account = client.get("/api/auth/me", headers=h).json()
    assert account["llm_consent"] is True
    assert account["ai_terms_required"] is False
    exported = client.get("/api/auth/me/export", headers=h).json()["account"]
    assert exported["terms_version"] == TERMS_VERSION
    assert exported["terms_accepted_at"]
    assert client.put("/api/auth/consent", json={"llm_consent": False}, headers=h).status_code in (404, 405)


def test_register_records_consent():
    email = f"c_{uuid.uuid4().hex[:8]}@test.dev"
    r = client.post("/api/auth/register",
                    json={"terms_accepted": True, "email": email, "password": "password123", "llm_consent": True})
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=h).json()["llm_consent"] is True


def test_legacy_accounts_accept_terms_once_before_ai(monkeypatch):
    from app.llm import providers
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    conv.state = "open"
    prof.user.terms_version = None
    prof.user.terms_accepted_at = None
    prof.user.llm_consent = False
    db.commit(); db.close()
    seen = []
    def generate(*a, **kw):
        seen.append(kw.get("allow_external"))
        return "AI is answering.", "groq"
    monkeypatch.setattr(providers, "generate", generate)
    assert client.get("/api/auth/me", headers=h).json()["ai_terms_required"] is True
    for endpoint in ("send", "stream"):
        assert client.post(f"/api/chat/{endpoint}", json={"text":"hello"}, headers=h).status_code == 403
    assert seen == []
    assert client.post("/api/auth/terms", json={"terms_accepted": False}, headers=h).status_code == 422
    assert client.post("/api/auth/terms", json={"terms_accepted": True}, headers=h).status_code == 200
    exported = client.get("/api/auth/me/export", headers=h).json()["account"]
    timestamp = exported["terms_accepted_at"]
    assert timestamp and exported["llm_consent"] is True
    assert exported["terms_version"] == TERMS_VERSION
    send("tell me about my moon", h)
    assert seen == [True]
    client.post("/api/auth/terms", json={"terms_accepted": True}, headers=h)
    assert client.get("/api/auth/me/export", headers=h).json()["account"]["terms_accepted_at"] == timestamp


def test_data_export_contains_everything():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    r = client.get("/api/auth/me/export", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["account"]["email"].endswith("@test.dev")
    assert d["birth_profile"]["place_name"]
    assert len(d["calibration_events"]) in (0, 3)
    assert d["conversations"] and d["conversations"][0]["messages"]
    assert "password_hash" not in json.dumps(d)
    assert client.get("/api/auth/me/export").status_code == 401


def test_geo_csv_resolves():
    from app import geo
    assert os.path.exists(geo._CSV)


# ---------- 6. Password reset + email verification ----------

@pytest.fixture
def outbox(monkeypatch):
    from app import mailer
    box = []
    monkeypatch.setattr(mailer, "send_email", lambda to, subj, body: box.append((to, subj, body)))
    return box


def _token_from(mail, path):
    import re
    m = re.search(rf"/{path}\?token=([\w-]+)", mail[2])
    assert m, mail
    return m.group(1)


def _register(email=None, password="password123"):
    email = email or f"r_{uuid.uuid4().hex[:8]}@test.dev"
    r = client.post("/api/auth/register", json={"terms_accepted": True, "email": email, "password": password})
    assert r.status_code == 200, r.text
    return email, {"authorization": f"Bearer {r.json()['access_token']}"}


def test_register_sends_verification_and_verify_is_single_use(outbox):
    email, h = _register()
    assert client.get("/api/auth/me", headers=h).json()["email_verified"] is False
    assert len(outbox) == 1 and outbox[0][0] == email
    tok = _token_from(outbox[0], "verify")
    assert client.post("/api/auth/verify", json={"token": tok}).json() == {"ok": True}
    assert client.get("/api/auth/me", headers=h).json()["email_verified"] is True
    r = client.post("/api/auth/verify", json={"token": tok})
    assert r.status_code == 400 and r.json()["detail"] == "invalid or expired link"
    assert client.post("/api/auth/verify", json={"token": "garbage"}).status_code == 400


def test_verify_resend_requires_auth_is_rate_limited_and_revokes_old(outbox):
    assert client.post("/api/auth/verify/resend").status_code == 401
    _, h = _register()
    first = _token_from(outbox[0], "verify")
    for _ in range(3):
        assert client.post("/api/auth/verify/resend", headers=h).json() == {"ok": True}
    assert client.post("/api/auth/verify/resend", headers=h).status_code == 429
    assert client.post("/api/auth/verify", json={"token": first}).status_code == 400
    assert client.post("/api/auth/verify", json={"token": _token_from(outbox[-1], "verify")}).status_code == 200
    n = len(outbox)
    assert client.post("/api/auth/verify/resend", headers=h).json() == {"ok": True}
    assert len(outbox) == n          # already verified: nothing sent


def test_login_and_chat_not_blocked_by_unverified_email():
    _, h = _register()
    assert client.get("/api/auth/me", headers=h).json()["email_verified"] is False
    assert client.put("/api/profile", json=ARJUN, headers=h).status_code == 200
    assert client.get("/api/chat/history", headers=h).status_code == 200


def test_forgot_does_not_enumerate_accounts(outbox):
    email, _ = _register()
    outbox.clear()
    r1 = client.post("/api/auth/forgot", json={"email": email})
    r2 = client.post("/api/auth/forgot", json={"email": "nobody@test.dev"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json() == {"ok": True}
    assert len(outbox) == 1 and outbox[0][0] == email
    assert "/reset?token=" in outbox[0][2]


def test_forgot_is_ip_throttled(outbox):
    for _ in range(10):
        assert client.post("/api/auth/forgot", json={"email": "x@test.dev"}).status_code == 200
    assert client.post("/api/auth/forgot", json={"email": "x@test.dev"}).status_code == 429


def test_reset_changes_password_rotates_nonce_and_is_single_use(outbox):
    email, h = _register()
    outbox.clear()
    client.post("/api/auth/forgot", json={"email": email})
    tok = _token_from(outbox[0], "reset")
    assert client.post("/api/auth/reset", json={"token": tok, "password": "short"}).status_code == 422
    r = client.post("/api/auth/reset", json={"token": tok, "password": "brand-new-pass"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    # old JWT is dead, old password rejected, new one works
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "brand-new-pass"}).status_code == 200
    r = client.post("/api/auth/reset", json={"token": tok, "password": "another-pass-1"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid or expired link"


def test_reset_token_expiry_and_purpose_separation(outbox):
    from app.db import SessionLocal, AuthToken, _utcnow
    from datetime import timedelta
    email, _ = _register()
    verify_tok = _token_from(outbox[-1], "verify")
    client.post("/api/auth/forgot", json={"email": email})
    tok = _token_from(outbox[-1], "reset")
    # a verify token can't reset a password and vice versa
    assert client.post("/api/auth/reset", json={"token": verify_tok, "password": "password456"}).status_code == 400
    assert client.post("/api/auth/verify", json={"token": tok}).status_code == 400
    db = SessionLocal()
    try:
        recs = db.query(AuthToken).filter(AuthToken.purpose == "reset").all()
        rec = recs[-1]
        assert tok not in rec.token_hash                 # only a hash is stored
        assert abs((rec.expires_at - _utcnow()) - timedelta(hours=1)) < timedelta(minutes=1)
        rec.expires_at = _utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert client.post("/api/auth/reset", json={"token": tok, "password": "password456"}).status_code == 400
    # the verify token is untouched by the expiry and still valid (48h)
    assert client.post("/api/auth/verify", json={"token": verify_tok}).status_code == 200


def test_new_reset_request_revokes_previous_link(outbox):
    email, _ = _register()
    outbox.clear()
    client.post("/api/auth/forgot", json={"email": email})
    client.post("/api/auth/forgot", json={"email": email})
    old, new = _token_from(outbox[0], "reset"), _token_from(outbox[1], "reset")
    assert client.post("/api/auth/reset", json={"token": old, "password": "password456"}).status_code == 400
    assert client.post("/api/auth/reset", json={"token": new, "password": "password456"}).status_code == 200


def test_mailer_dev_mode_logs_and_prod_never_logs_token(monkeypatch, caplog):
    import logging
    from app import mailer
    monkeypatch.setattr(mailer.settings, "SMTP_HOST", "")
    caplog.set_level(logging.INFO)
    monkeypatch.delenv("JYOTISH_ENV", raising=False)
    mailer.send_email("a@b.c", "subj", "link?token=SECRET123")
    assert "SECRET123" in caplog.text
    caplog.clear()
    monkeypatch.setenv("JYOTISH_ENV", "prod")
    mailer.send_email("a@b.c", "subj", "link?token=SECRET123")
    assert "SECRET123" not in caplog.text


def test_mailer_smtp_uses_starttls(monkeypatch):
    from app import mailer
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): log.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): log.append("starttls")
        def login(self, u, p): log.append(("login", u))
        def send_message(self, msg): log.append(("send", msg["To"], msg["Subject"]))
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(mailer.settings, "SMTP_USER", "u")
    assert mailer.send_email("to@x.y", "S", "body") is True
    assert log == [("connect", "smtp.test", 587), "starttls", ("login", "u"), ("send", "to@x.y", "S")]


# ---------- 7. Alembic migrations ----------

def test_init_db_fresh_sqlite_reaches_head(tmp_path):
    from sqlalchemy import create_engine, inspect
    from app import db as D
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    D.init_db(eng)
    D.init_db(eng)      # idempotent
    insp = inspect(eng)
    assert {"users", "auth_tokens", "prediction_records", "alembic_version"} <= set(insp.get_table_names())
    assert "email_verified" in {c["name"] for c in insp.get_columns("users")}
    with eng.connect() as c:
        assert c.exec_driver_sql("select version_num from alembic_version").scalar() == "0013"


def test_init_db_upgrades_pre_alembic_database(tmp_path):
    from sqlalchemy import create_engine, inspect
    from app import db as D
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:   # the oldest schema: no token_nonce/consent/rectified_from
        c.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "email VARCHAR NOT NULL, password_hash VARCHAR NOT NULL, "
                          "display_name VARCHAR, created_at DATETIME)")
        c.exec_driver_sql("CREATE UNIQUE INDEX ix_users_email ON users (email)")
        c.exec_driver_sql("CREATE TABLE birth_profiles (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, "
                          "display_name VARCHAR, year INTEGER, month INTEGER, day INTEGER, hour INTEGER, "
                          "minute INTEGER, second INTEGER, place_name VARCHAR, place_state VARCHAR, "
                          "place_country VARCHAR, latitude FLOAT, longitude FLOAT, timezone_name VARCHAR, "
                          "utc_offset_hours FLOAT, birth_time_precision VARCHAR, chart_json TEXT, "
                          "calc_fingerprint VARCHAR, calibration_state VARCHAR, predictions_allowed BOOLEAN)")
        c.exec_driver_sql("CREATE TABLE calibration_events (id INTEGER PRIMARY KEY, profile_id INTEGER, "
                          "event_id VARCHAR, domain VARCHAR, predicted_event TEXT, predicted_window_start VARCHAR, "
                          "predicted_window_end VARCHAR, user_feedback VARCHAR, actual_date VARCHAR, "
                          "matched BOOLEAN, rules_evaluated TEXT, pillars_json TEXT, chat_text TEXT, "
                          "calc_fingerprint VARCHAR, asked BOOLEAN)")
        c.exec_driver_sql("CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER, title VARCHAR, "
                          "state VARCHAR, pending_event_id VARCHAR, created_at DATETIME, updated_at DATETIME)")
        c.exec_driver_sql("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, role VARCHAR, "
                          "content TEXT, kind VARCHAR, meta_json TEXT, created_at DATETIME)")
        c.exec_driver_sql("INSERT INTO users (email, password_hash, display_name) VALUES ('old@x.y', 'h', 'Old')")
    D.init_db(eng)
    insp = inspect(eng)
    cols = {c["name"] for c in insp.get_columns("users")}
    assert {"token_nonce", "llm_consent", "llm_consent_at", "email_verified"} <= cols
    assert "rectified_from" in {c["name"] for c in insp.get_columns("birth_profiles")}
    assert {"auth_tokens", "prediction_records"} <= set(insp.get_table_names())
    with eng.connect() as c:
        row = c.exec_driver_sql("select token_nonce, email_verified from users").one()
        assert row[0] and not row[1]          # nonce backfilled, unverified
        assert c.exec_driver_sql("select version_num from alembic_version").scalar() == "0013"


# ---------- 8. Streaming chat ----------

def _parse_sse(resp):
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in resp.text.split("\n\n"):
        if block.strip():
            assert block.startswith("data: ")
            events.append(json.loads(block[len("data: "):]))
    return events


def _open_conv(h):
    client.get("/api/chat/history", headers=h)
    db, conv, _ = _db_profile_and_conv(h)
    conv.state = "open"
    db.commit(); db.close()


def test_stream_offline_yields_delta_then_done_matching_persisted():
    h = register_and_profile()
    _open_conv(h)
    r = client.post("/api/chat/stream", json={"text": "tell me about my moon"}, headers=h)
    ev = _parse_sse(r)
    assert ev[-1]["type"] == "done" and [e["type"] for e in ev[:-1]] and \
        all(e["type"] == "delta" and e["text"] for e in ev[:-1])
    assert sum(e["type"] == "done" for e in ev) == 1
    hist = client.get("/api/chat/history", headers=h).json()
    n = len(ev[-1]["messages"])
    assert n >= 1 and hist[-n:] == ev[-1]["messages"]
    assert ev[-1]["messages"][0]["role"] == "user"      # same shape as /api/chat/send
    assert ev[-1]["messages"][-1]["role"] == "assistant"


def test_stream_calibration_turn_emits_only_done():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)      # conversation starts in calibration
    ev = _parse_sse(client.post("/api/chat/stream", json={"text": "yes"}, headers=h))
    assert [e["type"] for e in ev] == ["done"]
    hist = client.get("/api/chat/history", headers=h).json()
    assert hist[-len(ev[0]["messages"]):] == ev[0]["messages"]


def test_past_accident_lookup_reads_saved_rahu_dates_and_handles_followups(monkeypatch):
    from app.chat import orchestrator
    from app.db import PredictionRecord
    from app.llm import providers

    def unexpected_model(*args, **kwargs):
        pytest.fail("A timeline lookup should work without an external model")

    monkeypatch.setattr(providers, "generate", unexpected_model)
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    db, conv, profile = _db_profile_and_conv(h)
    initial_state = conv.state
    periods = orchestrator.chart_facts(profile)["vimshottari"]["periods"]
    rahu = [row for row in periods if row["maha"] == "Rahu"]
    timeframe = f"from {rahu[0]['start']} to {rahu[-1]['end']}"
    events = _parse_sse(client.post("/api/chat/stream", headers=h, json={
        "text": "Can you tell me the month my accident happened during Rahu’s Mahādasha?",
    }))
    reply = events[-1]["messages"][-1]["content"]
    assert timeframe in reply and "can’t establish the month" in reply

    db.refresh(conv)
    conv.messages[-1].meta_json = json.dumps({"fingerprint": profile.calc_fingerprint, "provider": "offline"})
    db.commit()
    reply = send("Which month?", h)[-1]["content"]
    assert timeframe in reply and "can’t establish the month" in reply
    midpoint = rahu[0]["start"][:4] + "-12-31"
    reply = send(f"It happened on {midpoint}", h)[-1]["content"]
    assert timeframe in reply and "Rahu–Rahu" in reply
    assert "31 December" in reply

    db.refresh(conv)
    assert conv.state == initial_state
    assert db.query(PredictionRecord).filter_by(profile_id=profile.id).count() == 0
    db.close()


def test_vimshottari_dates_and_sequence_use_saved_timeline(monkeypatch):
    from app.llm import providers

    def unexpected_model(*args, **kwargs):
        pytest.fail("Mahadasha dates are deterministic")

    monkeypatch.setattr(providers, "generate", unexpected_model)
    h = register_and_profile()
    timeline = send("Show me the full Mahadasha sequence", h)[-1]["content"]
    assert len(timeline.split("\n- ")) == 10
    rahu_dates = next(line.removeprefix("- Rahu ") for line in timeline.splitlines()
                      if line.startswith("- Rahu "))
    assert rahu_dates in send("Rahu ki Mahadasha kab shuru hui?", h)[-1]["content"]
    assert rahu_dates in send("राहु की महादशा कब शुरू हुई?", h)[-1]["content"]


def test_named_dasha_interpretation_grounds_provider_with_engine_dates(monkeypatch):
    from app.llm import providers

    seen = {}

    def generate(messages, *, facts, analysis, **kwargs):
        seen.update(facts)
        return "This is a traditional interpretation.", "offline"

    monkeypatch.setattr(providers, "generate", generate)
    h = register_and_profile()
    _open_conv(h)
    send("What is the traditional interpretation of my Rahu mahadasha?", h)
    assert len(seen["current_vimshottari"]) == 3
    assert [p["lord"] for p in seen["referenced_mahadashas"]] == ["Rahu"]
    rahu = seen["referenced_mahadashas"][0]
    grounding = providers.grounding_text(seen, None)
    assert f"Vimshottari mahadasha of Rahu: {rahu['start']} through {rahu['end']}" in grounding
    assert f"Vimshottari running today: {seen['current_vimshottari'][0]['lords'][0]}" in grounding


def test_asked_period_grounds_provider_with_window_vimshottari(monkeypatch):
    from app.llm import providers

    seen = {}

    def generate(messages, *, facts, analysis, **kwargs):
        seen.update(facts)
        return "This is a traditional interpretation.", "offline"

    monkeypatch.setattr(providers, "generate", generate)
    h = register_and_profile()
    _open_conv(h)
    send("i had an accident way back in Jan 2014", h)
    assert seen["window_label"] == "January 2014"
    covering = seen["window_vimshottari"]
    assert covering and all(p["start"] <= "2014-01-31" and "2014-01-01" <= p["end"] for p in covering)
    grounding = providers.grounding_text(seen, seen.get("analysis"))
    assert "Vimshottari active during January 2014" in grounding


def test_dasha_correction_complaint_gets_lookup_not_date_prompt():
    h = register_and_profile()
    _open_conv(h)
    r = send("i think you are not able to predict properly...."
             "my accident happened in rahu dash in 2014..."
             "you are connecting it to 2027", h)
    reply = r[-1]["content"]
    assert "Which dates did you mean" not in reply
    assert "Rahu" in reply and "2014" in reply


def test_oversized_year_range_offers_the_first_year():
    h = register_and_profile()
    _open_conv(h)
    r = send("tell me my future from 2027 to 2040", h)
    reply = r[-1]
    assert "one year at a time" in reply["content"] and "2027" in reply["content"]
    assert reply["meta"]["requested_window"] == ["2027-01-01", "2027-12-31"]
    # the offer is a real selection — "yes" must not be asked for dates again
    r = send("yes", h)
    assert "Which dates did you mean" not in r[-1]["content"]


def test_stream_same_guards_as_send():
    assert client.post("/api/chat/stream", json={"text": "hi"}).status_code == 401
    email, h = _register()
    assert client.post("/api/chat/stream", json={"text": "hi"}, headers=h).status_code == 428
    assert client.post("/api/chat/stream", json={"text": ""}, headers=h).status_code == 422


def test_stream_first_message_without_history_call():
    h = register_and_profile()
    ev = _parse_sse(client.post("/api/chat/stream", json={"text": "hello"}, headers=h))
    assert ev[-1]["type"] == "done"


def test_generate_streams_provider_deltas_and_no_retry_after_delta(monkeypatch):
    from app.llm import providers
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    got = []

    def ok(system, messages, on_delta, timeout=None):
        on_delta("Hel"); on_delta("lo *there*")
        return "Hello *there*"
    monkeypatch.setitem(providers.STREAM_PROVIDERS, "groq", ok)
    text, prov = providers.generate([{"role": "user", "content": "hi"}], on_delta=got.append)
    assert prov == "groq" and text == "Hello there" and got == ["Hel", "lo there"]

    calls = []

    def dies(system, messages, on_delta, timeout=None):
        calls.append(1)
        on_delta("partial")
        raise _status_error(503)
    monkeypatch.setitem(providers.STREAM_PROVIDERS, "groq", dies)
    monkeypatch.setitem(providers.STREAM_PROVIDERS, "openrouter",
                        lambda *a, **k: calls.append("or") or "x")
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    got.clear()
    text, prov = providers.generate([{"role": "user", "content": "hi"}], on_delta=got.append)
    assert prov == "offline" and calls == [1] and got == ["partial"]

    # failure before any delta IS retried
    calls.clear()

    def flaky(system, messages, on_delta, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _status_error(503)
        on_delta("fine")
        return "fine"
    monkeypatch.setitem(providers.STREAM_PROVIDERS, "groq", flaky)
    got.clear()
    text, prov = providers.generate([{"role": "user", "content": "hi"}], on_delta=got.append)
    assert prov == "groq" and text == "fine" and len(calls) == 2


def test_openai_and_gemini_sse_parsing(monkeypatch):
    from app.llm import providers
    import contextlib

    def fake_stream(lines):
        class R:
            def raise_for_status(self): pass
            def iter_lines(self): return iter(lines)

        @contextlib.contextmanager
        def cm(method, url, **kw):
            seen.update(url=url, **kw)
            yield R()
        return cm
    seen = {}
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "GEMINI_API_KEY", "gk")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.httpx, "stream", fake_stream([
        'data: {"choices":[{"delta":{"content":"A"}}]}', "",
        'data: {"choices":[{"delta":{}}]}',
        'data: {"choices":[{"delta":{"content":"B"}}]}', "data: [DONE]"]))
    got = []
    assert providers._groq_stream("s", [{"role": "user", "content": "x"}], got.append) == "AB"
    assert got == ["A", "B"] and seen["json"]["stream"] is True
    monkeypatch.setattr(providers.httpx, "stream", fake_stream([
        'data: {"candidates":[{"content":{"parts":[{"text":"G1"}]}}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"G2"}]}}]}']))
    got.clear()
    assert providers._gemini_stream("s", [{"role": "user", "content": "x"}], got.append) == "G1G2"
    assert "streamGenerateContent?alt=sse" in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "gk" and "key=" not in seen["url"]


# ---------- 9. Prediction follow-ups ----------

def _open_calibrated(h):
    client.get("/api/chat/history", headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    conv.state = "open"
    prof.calibration_state = "calibrated"
    prof.predictions_allowed = True
    db.commit(); db.close()


def _age_predictions(h, days=400):
    from app.db import SessionLocal, PredictionRecord, BirthProfile
    from datetime import date, timedelta
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    db = SessionLocal()
    pid = db.query(BirthProfile).filter(BirthProfile.user_id == uid).first().id
    for r in db.query(PredictionRecord).filter(PredictionRecord.profile_id == pid).all():
        r.forecast = "event_indicated"
        r.success_criteria = "A formal promotion takes effect within the recorded window."
        r.window_start = date.today() - timedelta(days=days + 365)
        r.window_end = date.today() - timedelta(days=days)
    db.commit(); db.close()


def test_future_analysis_persists_prediction_record():
    h = register_and_profile()
    assert client.get("/api/predictions", headers=h).json()["aggregate"]["total"] == 0
    _open_calibrated(h)
    send("Will I get a promotion in my career next year?", h)
    d = client.get("/api/predictions", headers=h).json()
    assert d["aggregate"] == {"total": 1, "happened": 0, "partly": 0, "did_not": 0,
                              "unsure": 0, "outside_window": 0, "pending": 1}
    p = d["predictions"][0]
    assert p["domain"] == "career" and "promotion" in p["question"]
    assert p["window_start"] and p["window_end"] and p["convergence"] and p["outcome"] is None


def test_followup_asked_after_window_and_reply_records_outcome():
    h = register_and_profile()
    assert client.put("/api/predictions/followups", json={"enabled": True}, headers=h).status_code == 200
    _open_calibrated(h)
    send("Will I get a promotion in my career next year?", h)
    # window still in the future: no follow-up
    assert all(m["kind"] != "options" for m in send("tell me about my moon", h))
    _age_predictions(h)
    msgs = send("tell me about my lagna", h)
    opts = [m for m in msgs if m["kind"] == "options"]
    assert len(opts) == 1 and opts[0]["role"] == "assistant"
    assert opts[0]["meta"]["options"] == ["It happened", "Partly", "It didn't happen", "Outside the window", "Not sure"]
    fid = opts[0]["meta"]["followup_id"]
    # asked once only
    assert all(m["kind"] != "options" for m in send("and my moon?", h))
    reply = send("Partly", h)
    assert len(reply) == 2 and reply[1]["role"] == "assistant"
    d = client.get("/api/predictions", headers=h).json()
    assert d["aggregate"]["partly"] == 1 and d["aggregate"]["pending"] == 0
    rec = d["predictions"][0]
    assert rec["id"] == fid and rec["outcome"] == "partly" and rec["outcome_at"]
    # a later "Partly" with nothing pending is ordinary chat
    assert all("noted" not in m["content"].lower() for m in send("Partly", h))
    assert client.get("/api/predictions", headers=h).json()["aggregate"]["total"] == 1


@pytest.mark.parametrize("text,outcome", [("It happened", "happened"),
                                          ("it didn’t happen", "did_not"),
                                          ("Not sure", "unsure")])
def test_followup_option_mapping(text, outcome):
    h = register_and_profile()
    assert client.put("/api/predictions/followups", json={"enabled": True}, headers=h).status_code == 200
    _open_calibrated(h)
    send("Will I get a promotion in my career next year?", h)
    _age_predictions(h)
    send("hello", h)
    send(text, h)
    assert client.get("/api/predictions", headers=h).json()["predictions"][0]["outcome"] == outcome


def test_no_followup_while_calibrating_and_export_includes_predictions():
    h = register_and_profile()
    assert client.put("/api/predictions/followups", json={"enabled": True}, headers=h).status_code == 200
    _open_calibrated(h)
    send("Will I get a promotion in my career next year?", h)
    _age_predictions(h)
    db, conv, _ = _db_profile_and_conv(h)
    conv.state = "cal_ask"
    db.commit(); db.close()
    assert all(m["meta"].get("followup_id") is None for m in send("hello", h))
    exp = client.get("/api/auth/me/export", headers=h).json()
    assert len(exp["predictions"]) == 1 and exp["predictions"][0]["domain"] == "career"
    assert client.get("/api/predictions").status_code == 401


def test_account_deletion_removes_predictions_and_tokens(outbox):
    from app.db import SessionLocal, PredictionRecord, AuthToken
    h = register_and_profile()
    _open_calibrated(h)
    send("Will I get a promotion in my career next year?", h)
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    assert client.delete("/api/auth/me", headers=h).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(AuthToken).filter(AuthToken.user_id == uid).count() == 0
        from app.db import BirthProfile
        live = [p.id for p in db.query(BirthProfile).all()]
        assert db.query(PredictionRecord).filter(
            ~PredictionRecord.profile_id.in_(live)).count() == 0
    finally:
        db.close()


# ---------- 6. Failed calibration: restore, milestones, reset ----------

def _fail_calibration(h):
    """Answer no to each opening check."""
    client.get("/api/chat/history", headers=h)
    out = []
    for _ in range(3):
        out = send("No, that didn't happen", h)
    return out


def test_failed_calibration_offers_milestones_and_edit(monkeypatch):
    h = register_and_profile()
    out = _fail_calibration(h)
    last = out[-1]
    assert last["kind"] == "options"
    assert last["meta"]["options"] == ["Continue with the reading", "Share life events", "Edit birth details"]
    assert last["meta"]["actions"]["Edit birth details"] == "edit_birth"
    assert "Profile" not in last["content"]
    prof = client.get("/api/profile", headers=h).json()
    assert prof["calibration_state"] == "uncalibrated" and prof["predictions_allowed"]


def test_parse_milestones():
    from datetime import date
    from app.chat.orchestrator import parse_milestones, looks_like_event
    born, today = date(1990, 5, 15), date(2026, 11, 17)
    ev, prob = parse_milestones("started my first job in July 2012", born, today)
    assert ev == [{"year": 2012, "month": 7, "domain": "career",
                   "description": "started my first job in July 2012"}] and not prob
    ev, _ = parse_milestones("got married March 2016 and moved to Pune in 2019; "
                             "graduated 05/2011", born, today)
    assert [(e["domain"], e["year"], e["month"]) for e in ev] == [
        ("relationship", 2016, 3), ("relocation", 2019, None), ("education", 2011, 5)]
    ev, _ = parse_milestones("In 2012, I joined Infosys", born, today)
    assert [(e["domain"], e["year"]) for e in ev] == [("career", 2012)]
    ev, prob = parse_milestones("married in 1985. moved in 2031", born, today)
    assert ev == [] and len(prob) == 2
    assert looks_like_event("I got promoted in 2015")
    assert not looks_like_event("what was my dasha in 2015?")
    assert not looks_like_event("will I get promoted in 2027")


def test_milestone_flow_no_improvement(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)
    monkeypatch.setattr(C, "search_with_milestones", lambda *a, **k: None)
    send("Share life events", h)
    r = send("started my first job in July 2012", h)
    assert "career, July 2012" in r[-1]["content"]
    r = send("got married March 2016", h)
    assert "That's all, check my time" in r[-1]["meta"]["options"]
    r = send("moved to Pune in 2019", h)          # third event runs the search
    text = " ".join(m["content"] for m in r)
    assert "keep the recorded time" in text
    db, conv, prof = _db_profile_and_conv(h)
    assert prof.milestone_search_done and len(prof.milestones) == 3
    assert (prof.hour, prof.minute) == (6, 15) and prof.predictions_allowed
    db.close()
    # The original birth time still supports a qualified reading.
    r = send("Will I get a promotion next year?", h)
    assert r[-1]["meta"]["analysis"]["precision"]["calibrated"] is False


def test_milestone_flow_adopted_then_fresh_checks(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)

    def better(birth, facts, ms, eng):
        assert len(ms) == 2
        nb = BirthInput(**{**birth.__dict__, "hour": 7, "minute": 5})
        return {"birth": nb, "delta_minutes": 50}
    monkeypatch.setattr(C, "search_with_milestones", better)
    send("I joined my first job in July 2012 and got married in March 2016", h)
    r = send("That's all, check my time", h)
    assert r[-1]["meta"]["options"] == ["Yes, use 07:05", "No, keep my time"]
    db, conv, prof = _db_profile_and_conv(h)
    assert conv.state == "rectify_confirm" and (prof.hour, prof.minute) == (6, 15)
    db.close()
    r = send("Yes, use 07:05", h)
    db, conv, prof = _db_profile_and_conv(h)
    assert (prof.hour, prof.minute) == (7, 5) and prof.rectified_from == "1990-05-15 06:15:00"
    assert conv.state == "cal_ask" and not prof.predictions_allowed   # unlocks only via checks
    db.close()
    assert r[-1]["kind"] == "options" and r[-1]["meta"].get("event_id")
    # the new checks fail too -> original time restored, no more searches offered
    for _ in range(3):
        r = send("No, that didn't happen", h)
    db, conv, prof = _db_profile_and_conv(h)
    assert (prof.hour, prof.minute) == (6, 15) and prof.rectified_from is None
    assert conv.state == "rectify" and prof.predictions_allowed
    db.close()
    assert r[-1]["meta"]["options"] == ["Continue with the reading", "Edit birth details"]


def test_milestone_unknown_domain_asks(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)
    send("Share life events", h)
    r = send("Something big happened in June 2014", h)
    assert "What kind of event" in r[-1]["content"]
    r = send("Career", h)
    assert "career, June 2014" in r[-1]["content"]


def test_question_with_year_not_swallowed(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)
    send("what was my dasha in 2015?", h)
    db, conv, prof = _db_profile_and_conv(h)
    assert len(prof.milestones) == 0 and conv.state == "open"
    db.close()


def test_reset_does_not_reask_checks_when_uncalibrated(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)
    assert client.post("/api/chat/reset", headers=h).status_code == 200
    hist = client.get("/api/chat/history", headers=h).json()
    assert len(hist) == 1 and "Share life events" in hist[0]["meta"]["options"]
    assert all(not m["meta"].get("event_id") for m in hist)
    send("Yes, that happened", h)
    prof = client.get("/api/profile", headers=h).json()
    assert prof["calibration_state"] == "uncalibrated" and prof["predictions_allowed"]


def test_reset_keeps_answers_while_pending():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    send("No, that didn't happen", h)
    first = client.get("/api/calibration", headers=h).json()["events"][0]
    client.post("/api/chat/reset", headers=h)
    client.get("/api/chat/history", headers=h)
    evs = client.get("/api/calibration", headers=h).json()["events"]
    assert evs[0]["event_id"] == first["event_id"] and evs[0]["user_feedback"] == "rejected"


def test_profile_edit_clears_milestones(monkeypatch):
    h = register_and_profile()
    _fail_calibration(h)
    send("started my first job in July 2012", h)
    exp = client.get("/api/auth/me/export", headers=h).json()
    assert exp["milestones"] and exp["milestones"][0]["year"] == 2012
    p = client.get("/api/profile", headers=h).json()
    edited = {k: p[k] for k in ARJUN}
    edited["minute"] = 40
    client.put("/api/profile", json=edited, headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    assert prof.milestones == [] and not prof.milestone_search_done
    db.close()


# ---------- 10. Failed stream turn keeps the user's message ----------

def test_stream_error_event_keeps_user_message(monkeypatch):
    from app.chat import orchestrator as O
    h = register_and_profile()
    _open_conv(h)
    before = len(client.get("/api/chat/history", headers=h).json())

    def boom(*a, **k):
        raise RuntimeError("llm exploded")
    monkeypatch.setattr(O, "handle_message", boom)
    ev = _parse_sse(client.post("/api/chat/stream", json={"text": "do not lose me"}, headers=h))
    assert [e["type"] for e in ev] == ["error"]
    monkeypatch.undo()
    hist = client.get("/api/chat/history", headers=h).json()
    assert len(hist) == before + 1
    assert hist[-1]["role"] == "user" and hist[-1]["content"] == "do not lose me"


# ---------- 11. Tester feedback ----------

def _assistant_msg(h, kind="text"):
    hist = client.get("/api/chat/history", headers=h).json()
    return next(m for m in hist if m["role"] == "assistant" and m["kind"] == kind)


def test_message_feedback_toggle_change_clear_and_isolation():
    h = register_and_profile()
    m = _assistant_msg(h)
    url = f"/api/messages/{m['id']}/feedback"
    assert client.post(url, json={"rating": 1}, headers=h).json()["rating"] == 1
    r = client.post(url, json={"rating": -1, "comment": " too vague "}, headers=h)
    assert r.json() == {"rating": -1, "comment": "too vague"}        # changed, still one vote
    from app.db import SessionLocal, MessageFeedback
    db = SessionLocal()
    assert db.query(MessageFeedback).filter(MessageFeedback.message_id == m["id"]).count() == 1
    db.close()
    hist = client.get("/api/chat/history", headers=h).json()
    assert next(x for x in hist if x["id"] == m["id"])["rating"] == -1
    assert client.post(url, json={"rating": 0}, headers=h).json()["rating"] == 0
    assert next(x for x in client.get("/api/chat/history", headers=h).json()
                if x["id"] == m["id"])["rating"] == 0
    # validation, other users, unauthenticated, non-rateable kinds
    assert client.post(url, json={"rating": 2}, headers=h).status_code == 422
    assert client.post(url, json={"rating": 1, "comment": "x" * 501}, headers=h).status_code == 422
    assert client.post(url, json={"rating": 1}).status_code == 401
    other = register_and_profile()
    assert client.post(url, json={"rating": 1}, headers=other).status_code == 404
    opt = _assistant_msg(h, "options")
    assert client.post(f"/api/messages/{opt['id']}/feedback", json={"rating": 1},
                       headers=h).status_code == 400


def test_problem_report_context_and_validation():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    assert client.post("/api/feedback/report", json={"text": ""}, headers=h).status_code == 422
    assert client.post("/api/feedback/report", json={"text": "x" * 2001}, headers=h).status_code == 422
    r = client.post("/api/feedback/report", headers=h,
                    json={"text": "chart looks wrong", "page": "/chat", "app_version": "web-1"})
    assert r.status_code == 200
    from app.db import SessionLocal, ProblemReport
    db = SessionLocal()
    rep = db.query(ProblemReport).order_by(ProblemReport.id.desc()).first()
    ctx = json.loads(rep.context_json)
    db.close()
    assert ctx["page"] == "/chat" and ctx["client_version"] == "web-1"
    assert 1 <= len(ctx["last_message_ids"]) <= 10
    assert ctx["profile"]["calibration_state"] == "pending"


def test_admin_feedback_access_and_content(monkeypatch):
    from app.main import settings as S
    h = register_and_profile()
    assert client.get("/api/admin/feedback", headers=h).status_code == 403
    assert client.get("/api/admin/feedback").status_code == 401
    assert client.get("/api/auth/me", headers=h).json()["is_admin"] is False
    # a user's thumbs-down on an answer to a question, plus a report
    _open_conv(h)
    send("tell me about my moon", h)
    hist = client.get("/api/chat/history", headers=h).json()
    ans = hist[-1]
    client.post(f"/api/messages/{ans['id']}/feedback", json={"rating": -1, "comment": "meh"}, headers=h)
    up = _assistant_msg(h)
    client.post(f"/api/messages/{up['id']}/feedback", json={"rating": 1}, headers=h)
    client.post("/api/feedback/report", json={"text": "broken thing"}, headers=h)
    email = client.get("/api/auth/me", headers=h).json()["email"]
    monkeypatch.setattr(S, "ADMIN_EMAILS", frozenset({email.upper().lower()}))
    assert client.get("/api/auth/me", headers=h).json()["is_admin"] is True
    d = client.get("/api/admin/feedback", headers=h).json()
    assert d["totals"]["up"] >= 1 and d["totals"]["down"] >= 1 and d["totals"]["reports"] >= 1
    row = next(x for x in d["down_votes"] if x["message"]["id"] == ans["id"])
    assert row["comment"] == "meh" and row["message"]["content"] == ans["content"]
    assert row["previous_user_message"]["content"] == "tell me about my moon"
    assert row["user_email"] == email
    assert any(r["text"] == "broken thing" and r["context"]["page"] == "" for r in d["reports"])
    ids = [r["id"] for r in d["reports"]]
    assert ids == sorted(ids, reverse=True)


def test_feedback_exported_and_deleted_with_account():
    from app.db import SessionLocal, MessageFeedback, ProblemReport
    h = register_and_profile()
    m = _assistant_msg(h)
    client.post(f"/api/messages/{m['id']}/feedback", json={"rating": -1, "comment": "c"}, headers=h)
    client.post("/api/feedback/report", json={"text": "r1"}, headers=h)
    exp = client.get("/api/auth/me/export", headers=h).json()
    assert exp["message_feedback"][0]["comment"] == "c" and exp["problem_reports"][0]["text"] == "r1"
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    assert client.delete("/api/auth/me", headers=h).status_code == 200
    db = SessionLocal()
    assert db.query(MessageFeedback).filter(MessageFeedback.user_id == uid).count() == 0
    assert db.query(ProblemReport).filter(ProblemReport.user_id == uid).count() == 0
    db.close()


# ---------- 12. Multiple birth profiles (family members) ----------

MUM = dict(ARJUN, display_name="Mum", relation="mother", permission_confirmed=True, year=1962, month=3, day=2,
           hour=14, minute=5)


def _profiles(h):
    r = client.get("/api/profiles", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_migration_0006_preserves_data_and_allows_many_profiles(tmp_path):
    from sqlalchemy import create_engine, inspect
    from alembic import command
    from app import db as D
    eng = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with eng.begin() as conn:
        command.upgrade(D._alembic_config(conn), "0004")
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO users (id, token_nonce, email, password_hash) "
                          "VALUES (1, 'n', 'a@x.y', 'h'), (2, 'n2', 'b@x.y', 'h')")
        c.exec_driver_sql("INSERT INTO birth_profiles (id, user_id, display_name, year, calibration_state, "
                          "rectification_attempted, milestone_search_done) VALUES "
                          "(7, 1, 'Ann', 1990, 'calibrated', 0, 0), (9, 2, 'Bob', 1980, 'uncalibrated', 0, 0)")
        c.exec_driver_sql("INSERT INTO conversations (id, user_id, title, state) VALUES "
                          "(3, 1, 'c', 'open'), (4, 2, 'c', 'cal_intro')")
        c.exec_driver_sql("INSERT INTO messages (id, conversation_id, role, content, kind) "
                          "VALUES (1, 3, 'user', 'hello', 'text')")
        c.exec_driver_sql("INSERT INTO calibration_events (id, profile_id, event_id) VALUES (1, 7, 'e1')")
    D.init_db(eng)
    insp = inspect(eng)
    assert {"relation", "user_id"} <= {c["name"] for c in insp.get_columns("birth_profiles")}
    assert not [u for u in insp.get_unique_constraints("birth_profiles")
                if u["column_names"] == ["user_id"]]
    with eng.begin() as c:
        rows = c.exec_driver_sql("select id, display_name, relation, calibration_state from birth_profiles "
                                 "order by id").all()
        assert rows == [(7, "Ann", "self", "calibrated"), (9, "Bob", "self", "uncalibrated")]
        assert c.exec_driver_sql("select predictions_allowed from birth_profiles where id = 9").scalar()
        assert c.exec_driver_sql("select id, active_profile_id from users order by id").all() == [(1, 7), (2, 9)]
        assert c.exec_driver_sql("select id, profile_id from conversations order by id").all() == [(3, 7), (4, 9)]
        assert c.exec_driver_sql("select content from messages").scalar() == "hello"
        assert c.exec_driver_sql("select profile_id from calibration_events").scalar() == 7
        # a second profile for the same user is now legal
        c.exec_driver_sql("INSERT INTO birth_profiles (id, user_id, relation) VALUES (10, 1, 'mother')")
        assert c.exec_driver_sql("select version_num from alembic_version").scalar() == "0013"
        assert c.exec_driver_sql("select calc_preset from birth_profiles where id = 7").scalar() == "legacy_tropical"
    D.init_db(eng)       # idempotent


def test_profiles_create_list_activate_and_separate_conversations():
    h = register_and_profile()
    first = client.get("/api/chat/history", headers=h).json()
    ps = _profiles(h)
    assert len(ps) == 1 and ps[0]["relation"] == "self" and ps[0]["is_active"]
    r = client.post("/api/profiles", json=MUM, headers=h)
    assert r.status_code == 200, r.text
    mum = r.json()
    assert mum["relation"] == "mother" and mum["is_active"] and mum["calibration_state"] == "pending"
    ps = _profiles(h)
    assert [p["is_active"] for p in ps] == [False, True]
    assert client.get("/api/profile", headers=h).json()["id"] == mum["id"]     # legacy = active
    # Mum's own calibration starts, worded about her
    hist = client.get("/api/chat/history", headers=h).json()
    assert hist[0]["content"] != first[0]["content"] and "Mum" in hist[0]["content"]
    ask = hist[-1]["content"]
    assert "Mum's chart" in ask and "ask your own question" in ask
    assert "your career" not in ask and "your work path" not in ask
    # answering Mum's questions doesn't touch the first person's chat
    send("yes", h)
    cal = client.get("/api/calibration", headers=h).json()
    assert [e["user_feedback"] for e in cal["events"]].count("confirmed") == 1
    me_id = ps[0]["id"]
    assert client.post(f"/api/profiles/{me_id}/activate", headers=h).json()["is_active"]
    again = client.get("/api/chat/history", headers=h).json()
    assert [m["content"] for m in again] == [m["content"] for m in first]
    assert [e["user_feedback"] for e in client.get("/api/calibration", headers=h).json()["events"]] == ["", "", ""]
    # per-profile rate limit stays per user; export has everything
    exp = client.get("/api/auth/me/export", headers=h).json()
    assert len(exp["birth_profiles"]) == 2 and {c["profile_id"] for c in exp["conversations"]} == {me_id, mum["id"]}
    assert sum(e["profile_id"] == mum["id"] for e in exp["calibration_events"]) == 3


def test_family_member_calibration_wording_uses_name_only_for_others():
    from app.astro import calibration as C2
    b = BirthInput(name="Mum", year=1962, month=3, day=2, hour=14, minute=5, second=0,
                   lat=13.0827, lon=80.2707, tz_offset=5.5, place_label="Chennai")
    facts = engine.compute(b)
    own = C2.generate_statements(facts, b, "fp")
    other = C2.generate_statements(facts, b, "fp", subject="Mum")
    assert own and other and all("Mum" not in s["chat_text"] for s in own)
    joined = " ".join(s["chat_text"] for s in other)
    assert "Mum" in joined and " your " not in joined and "you lived" not in joined
    assert C2.subject_words("Chris")["poss"] == "Chris'"


def test_profile_ownership_cross_user_is_404():
    a = register_and_profile()
    b = register_and_profile()
    pid = _profiles(a)[0]["id"]
    bid = _profiles(b)[0]["id"]
    assert client.get(f"/api/profiles/{pid}", headers=b).status_code == 404
    assert client.put(f"/api/profiles/{pid}", json=ARJUN, headers=b).status_code == 404
    assert client.post(f"/api/profiles/{pid}/activate", headers=b).status_code == 404
    assert client.delete(f"/api/profiles/{pid}", headers=b).status_code == 404
    assert client.get("/api/profile", headers=b).json()["id"] == bid      # untouched
    assert len(_profiles(a)) == 1
    assert client.get(f"/api/profiles/{pid}", headers=a).status_code == 200
    assert client.get("/api/profiles").status_code == 401
    assert client.get("/api/profiles/99999999", headers=a).status_code == 404


def test_profile_delete_rules_and_cascade():
    from app.db import SessionLocal, Conversation, Message, MessageFeedback, CalibrationEvent
    h = register_and_profile()
    first = _profiles(h)[0]["id"]
    assert client.delete(f"/api/profiles/{first}", headers=h).status_code == 400   # last one
    mum = client.post("/api/profiles", json=MUM, headers=h).json()
    hist = client.get("/api/chat/history", headers=h).json()
    client.post(f"/api/messages/{hist[0]['id']}/feedback", json={"rating": 1}, headers=h)
    send("yes", h)
    r = client.delete(f"/api/profiles/{mum['id']}", headers=h)           # deleting the active one
    assert r.status_code == 200 and r.json()["active_profile_id"] == first
    ps = _profiles(h)
    assert [p["id"] for p in ps] == [first] and ps[0]["is_active"]
    db = SessionLocal()
    try:
        assert db.query(Conversation).filter(Conversation.profile_id == mum["id"]).count() == 0
        assert db.query(CalibrationEvent).filter(CalibrationEvent.profile_id == mum["id"]).count() == 0
        assert db.query(Message).filter(Message.id == hist[0]["id"]).count() == 0
        assert db.query(MessageFeedback).filter(MessageFeedback.message_id == hist[0]["id"]).count() == 0
    finally:
        db.close()
    assert client.get("/api/chat/history", headers=h).status_code == 200


def test_profile_limit_and_validation():
    h = register_and_profile()
    for i in range(9):
        assert client.post("/api/profiles", json=dict(MUM, display_name=f"P{i}"), headers=h).status_code == 200
    assert len(_profiles(h)) == 10
    assert client.post("/api/profiles", json=MUM, headers=h).status_code == 400
    h2 = register_and_profile()
    assert client.post("/api/profiles", json=dict(MUM, relation="cousin"), headers=h2).status_code == 422
    assert client.post("/api/profiles", json=dict(MUM, month=2, day=30), headers=h2).status_code == 422


def test_put_profile_by_id_edits_that_profile_and_keeps_relation_when_omitted():
    h = register_and_profile()
    first = _profiles(h)[0]["id"]
    mum = client.post("/api/profiles", json=MUM, headers=h).json()
    edited = {k: v for k, v in MUM.items() if k != "relation"}
    edited["display_name"] = "Amma"
    r = client.put(f"/api/profiles/{mum['id']}", json=edited, headers=h)
    assert r.status_code == 200 and r.json()["display_name"] == "Amma" and r.json()["relation"] == "mother"
    # name-only edit re-words the pending questions without restarting calibration
    ev = client.get("/api/calibration", headers=h).json()["events"]
    assert all("Mum" not in e["predicted_event"] for e in ev)
    # legacy PUT /api/profile edits the ACTIVE profile (Mum), not the first
    client.put("/api/profile", json=dict(edited, display_name="Mummy"), headers=h)
    names = {p["id"]: p["display_name"] for p in _profiles(h)}
    assert names[mum["id"]] == "Mummy" and names[first] == "Arjun"


def test_stream_uses_profile_active_at_request_time():
    h = register_and_profile()
    mum = client.post("/api/profiles", json=MUM, headers=h).json()
    ev = _parse_sse(client.post("/api/chat/stream", json={"text": "yes"}, headers=h))
    assert ev[-1]["type"] == "done"
    cal = client.get("/api/calibration", headers=h).json()
    assert cal["events"][0]["user_feedback"] == "confirmed"
    first = [p for p in _profiles(h) if p["id"] != mum["id"]][0]["id"]
    client.post(f"/api/profiles/{first}/activate", headers=h)
    assert all(e["user_feedback"] == "" for e in
               client.get("/api/calibration", headers=h).json()["events"])


def test_account_deletion_removes_all_profiles():
    from app.db import SessionLocal, BirthProfile, Conversation
    h = register_and_profile()
    client.post("/api/profiles", json=MUM, headers=h)
    client.get("/api/chat/history", headers=h)
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    assert client.delete("/api/auth/me", headers=h).status_code == 200
    db = SessionLocal()
    assert db.query(BirthProfile).filter(BirthProfile.user_id == uid).count() == 0
    assert db.query(Conversation).filter(Conversation.user_id == uid).count() == 0
    db.close()


# Chat regressions: routing, context and interrupted calibration replies.
@pytest.mark.parametrize('question, expected', [
    ('show my D24 chart', 'D24'), ('show my D10 chart', 'D10'),
    ('show my D-60 chart', 'D60'), ('my chaturvimshamsa chart', 'D24'),
    ('show my D12 chart', 'D12'), ('my relationship', None),
])
def test_chart_request_uses_exact_varga(question, expected):
    from app.chat.orchestrator import detect_varga
    assert detect_varga(question) == expected


def test_prediction_and_chart_followups_keep_context(monkeypatch):
    from app.chat import orchestrator as O
    h = register_and_profile()
    _open_conv(h)
    db, conv, prof = _db_profile_and_conv(h)
    prof.predictions_allowed = True
    prof.calibration_state = 'calibrated'
    db.commit(); db.close()
    chart = send('show my D24 chart', h)
    assert chart[-1]['meta']['varga'] == 'D24'
    captured = []
    def generate(messages, **kwargs):
        captured.append(messages)
        return 'I have the earlier chart and question in context.', 'offline'
    monkeypatch.setattr(O.providers, 'generate', generate)
    send('What does this mean?', h)
    assert any(m['content'] == chart[-1]['content'] for m in captured[-1])
    send('Will I change my job next year?', h)
    assert any(m['content'] == 'What does this mean?' for m in captured[-1])
    assert captured[-1][-1]['content'] == 'Will I change my job next year?'


def test_why_domain_question_is_answered_instead_of_old_evidence(monkeypatch):
    from app.chat import orchestrator as O
    h = register_and_profile()
    _open_conv(h)
    seen = []
    def generate(messages, **kwargs):
        seen.append(messages[-1]['content'])
        return 'Let us look at your question.', 'offline'
    monkeypatch.setattr(O.providers, 'generate', generate)
    send('Why is my career difficult?', h)
    send('Explain my Moon placement', h)
    assert seen == ['Why is my career difficult?', 'Explain my Moon placement']


def test_calibration_date_followup_does_not_swallow_questions():
    h = register_and_profile()
    client.get('/api/chat/history', headers=h)
    send('Something similar, different time', h)
    before = client.get('/api/calibration', headers=h).json()['events']
    out = send('What does my chart mean?', h)
    after = client.get('/api/calibration', headers=h).json()['events']
    assert [e['user_feedback'] for e in before] == [e['user_feedback'] for e in after]
    assert any("less accurate" in m["content"] for m in out)
    assert "lagna" in out[-1]["content"].lower()
    assert all(not e["actual_date"] for e in after)


def test_next_month_prediction_window_includes_last_day():
    import calendar
    from datetime import date
    from app.chat.language import requested_window
    start, end = requested_window('next month', date.today())
    assert start.day == 1
    assert end.day == calendar.monthrange(start.year, start.month)[1]


@pytest.mark.parametrize('streaming', [False, True])
def test_slow_primary_leaves_time_for_healthy_backup(monkeypatch, streaming):
    from app.llm import providers as P
    monkeypatch.setattr(P.settings, 'LLM_PROVIDER', 'gemini')
    monkeypatch.setattr(P.settings, 'GEMINI_API_KEY', 'test')
    monkeypatch.setattr(P.settings, 'GROQ_API_KEY', 'test')
    monkeypatch.setattr(P.settings, 'OPENROUTER_API_KEY', 'test')
    monkeypatch.setattr(P.settings, 'LLM_EXTERNAL_CONSENT', True)
    monkeypatch.setattr(P.settings, 'LLM_TURN_DEADLINE_SECONDS', 30)
    clock = [0.0]
    calls = []
    monkeypatch.setattr(P.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(P.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def slow(system, messages, *args, timeout):
        calls.append(('gemini', timeout))
        clock[0] += timeout
        raise P.httpx.ReadTimeout('primary timed out')
    def backup(system, messages, *args, timeout):
        calls.append(('groq', timeout))
        if args:
            args[0]('Backup reply.')
        return 'Backup reply.'
    registry = P.STREAM_PROVIDERS if streaming else P.PROVIDERS
    monkeypatch.setitem(registry, 'gemini', slow)
    monkeypatch.setitem(registry, 'groq', backup)
    got = []
    reply, provider = P.generate([{'role':'user','content':'hello'}], on_delta=got.append if streaming else None)
    assert (reply, provider) == ('Backup reply.', 'groq')
    assert calls[0] == ('gemini', 10)
    assert calls[1][0] == 'groq' and calls[1][1] > 0
    if streaming:
        assert got == ['Backup reply.']


def test_offline_reply_explains_missing_account_consent(monkeypatch):
    from app.llm import providers as P
    monkeypatch.setattr(P.settings, 'LLM_PROVIDER', 'gemini')
    reply, provider = P.generate([{'role':'user','content':'tell me about myself'}], allow_external=False)
    assert provider == 'offline'
    assert 'Accept the updated service terms' in reply
    assert 'external providers' in reply
    assert 'I read the chart, not a script' not in reply


def test_signup_requires_affirmative_service_terms():
    for extra in ({}, {"terms_accepted": False}):
        r = client.post("/api/auth/register", json={"email": f"terms_{uuid.uuid4().hex[:8]}@test.dev", "password": "password123", **extra})
        assert r.status_code == 422


def test_terms_migration_does_not_invent_acceptance(tmp_path):
    from sqlalchemy import create_engine
    from alembic import command
    from app import db as D
    eng = create_engine(f"sqlite:///{tmp_path / 'terms.db'}")
    with eng.begin() as conn:
        command.upgrade(D._alembic_config(conn), "0007")
        conn.exec_driver_sql("INSERT INTO users (id, token_nonce, email, password_hash, llm_consent) VALUES (1, 'n', 'x@test.dev', 'h', 0)")
    D.init_db(eng)
    D.init_db(eng)
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT terms_version, terms_accepted_at, llm_consent FROM users WHERE id=1").one() == (None, None, 0)


def test_frozen_prediction_and_dated_outcomes_are_owned_and_window_checked():
    from datetime import date, datetime, timedelta
    h = register_and_profile()
    _open_calibrated(h)
    send('Will I get a promotion next year?', h)
    original = client.get('/api/predictions', headers=h).json()['predictions'][0]
    assert original['protocol'] and original['success_criteria']
    assert original['snapshot']['analysis']['sensitivity']['samples']
    assert original['snapshot']['analysis']['decision']['disposition'] == original['forecast']
    # Isolate reporting behavior using an explicit issued-forecast fixture.
    from app.db import SessionLocal, PredictionRecord
    db = SessionLocal(); rec = db.get(PredictionRecord, original['id'])
    rec.forecast = 'event_indicated'
    rec.created_at = datetime(2020,1,1)
    rec.window_start, rec.window_end = date(2020,2,1), date(2020,2,28)
    db.commit(); db.close()
    endpoint = f"/api/predictions/{original['id']}/outcome"
    other = register_and_profile()
    assert client.post(endpoint, json={'outcome':'happened','event_date':'2020-02-15'},headers=other).status_code == 404
    assert client.post(endpoint, json={'outcome':'happened'},headers=h).status_code == 422
    out = client.post(endpoint,json={'outcome':'happened','event_date':'2020-03-01'},headers=h)
    assert out.json()['outcome'] == 'outside_window'
    data = client.get('/api/predictions',headers=h).json()
    assert data['scorecard']['misses'] == 1 and data['scorecard']['hits'] == 0
    assert data['predictions'][0]['snapshot'] == original['snapshot']
    client.post(endpoint,json={'outcome':'partly'},headers=h)
    data = client.get('/api/predictions',headers=h).json()
    assert data['scorecard']['scored'] == 0 and data['scorecard']['partial'] == 1
    client.post(endpoint,json={'outcome':'happened','event_date':'2020-02-15'},headers=h)
    assert client.get('/api/predictions',headers=h).json()['scorecard']['hits'] == 1
    db=SessionLocal();rec=db.get(PredictionRecord,original['id']);rec.window_end=date.today()+timedelta(days=10);db.commit();db.close()
    assert client.post(endpoint,json={'outcome':'did_not'},headers=h).status_code == 409


def test_general_domain_reading_does_not_create_an_implicit_forecast():
    h = register_and_profile(); _open_calibrated(h)
    out=send('How is my career looking?',h)
    r=client.get('/api/predictions',headers=h).json()
    assert r['scorecard']['abstentions'] == 0
    assert r['scorecard']['scored'] == 0
    assert "can't make a reliable event forecast" not in out[-1]['content']
    assert "analysis" not in out[-1]["meta"]
    assert "coming year" not in out[-1]["content"]


def test_career_followup_keeps_model_answer_instead_of_replaying_intro(monkeypatch):
    from app.llm import providers
    h=register_and_profile(); _open_calibrated(h)
    replies=iter([
        'You may be weighing a new professional direction. What kind of work are you considering?',
        'For a job change, compare the responsibilities of the new role with your current work. What is motivating the move?',
    ])
    histories=[]
    def generate(messages, **kw):
        histories.append(messages)
        return next(replies), 'groq'
    monkeypatch.setattr(providers,'generate',generate)
    first=send('How is my career?',h)[-1]['content']
    second=send('I am considering a job change',h)[-1]['content']
    assert first.startswith('You may be weighing')
    assert second.startswith('For a job change, compare')
    assert first != second and 'Are you mainly thinking' not in second
    assert any(m['content'] == first for m in histories[-1])
    assert histories[-1][-1]['content'] == 'I am considering a job change'


def test_conversational_correction_uses_new_event_and_same_month_over_stream():
    h = register_and_profile()
    _open_calibrated(h)
    turns = [
        ("Will I change jobs?", "job_change"),
        ("What about July 2027?", "job_change"),
        ("Actually, I meant a promotion at my current company.", "promotion"),
    ]
    for index, (question, event) in enumerate(turns):
        done = _parse_sse(client.post("/api/chat/stream", json={"text": question}, headers=h))[-1]
        assert done["type"] == "done"
        reply = done["messages"][-1]
        if index == 0:
            assert reply["meta"]["pending_event"]["event_type"] == event
            assert "analysis" not in reply["meta"]
            continue
        analysis = reply["meta"]["analysis"]
        assert analysis["decision"]["event"]["event_type"] == event
        if index:
            assert analysis["analysis_window"] == {"start": "2027-07-01", "end": "2027-07-31"}
            assert "July 2027" in reply["content"]
        assert "try sending" not in reply["content"].lower()
    records = client.get("/api/predictions", headers=h).json()["predictions"]
    record = next(r for r in records if r["question"] == turns[-1][0])
    assert record["event_type"] == "promotion" and record["window_end"] == "2027-07-31"
    assert "promotion" in reply["content"].lower()
    assert "analysis" not in send("Where is my Saturn?", h)[-1]["meta"]
    assert "analysis" not in send("What about October 2028?", h)[-1]["meta"]
    changed = send("Marriage", h)[-1]["meta"]["analysis"]
    assert changed["domain"] == "relationship" and changed["analysis_window"]["end"] == "2028-10-31"


def test_chart_display_interpretation_and_followup_use_computed_varga(monkeypatch):
    from app.llm import providers
    h = register_and_profile()
    send("Show my D10 chart", h)
    answer = send("What does my D10 chart suggest about leadership?", h)[-1]
    assert answer["kind"] == "text" and "D10" in answer["content"] and "authority" in answer["content"]
    chart = client.get("/api/chart/D10", headers=h).json()["chart"]
    from app.astro.constants import SIGN_NAMES
    assert SIGN_NAMES[chart["Sun"]["sign"]] in answer["content"]
    captured = []
    def generate(messages, **kwargs):
        captured.append(kwargs["facts"]["selected_chart"])
        return "Interpreting the selected chart.", "gemini"
    monkeypatch.setattr(providers, "generate", generate)
    send("What does that mean?", h)
    assert captured[-1]["name"] == "D10"
    assert captured[-1]["placements"]["Sun"]["house"] == (chart["Sun"]["sign"] - chart["Lagna"]["sign"]) % 12 + 1


def test_semantic_topic_accepts_only_known_labels_and_respects_consent(monkeypatch):
    from app.llm import providers as p
    monkeypatch.setattr(p.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(p.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(p.settings, "GEMINI_API_KEY", "test")
    labels = iter(["promotion", "invented event"])
    seen = []
    def classify(system, messages, timeout):
        seen.append(messages[-1]["content"])
        return next(labels)
    monkeypatch.setitem(p.PROVIDERS, "gemini", classify)
    msg = [{"role": "user", "content": "Mere kaam mein tarakki ka koi yog hai?"}]
    assert p.conversation_topic(msg, allow_external=False) is None and not seen
    h = register_and_profile()
    _open_calibrated(h)
    monkeypatch.setattr(p, "generate", lambda *a, **k: ("Synthetic reading", "gemini"))
    pending = send(msg[0]["content"], h)[-1]["meta"]
    assert pending["pending_event"]["event_type"] == "promotion"
    analysis = send("next month", h)[-1]["meta"]["analysis"]
    assert analysis["decision"]["event"]["event_type"] == "promotion"
    assert p.conversation_topic(msg, allow_external=True) is None
    assert seen == [msg[0]["content"]] * 2


def test_conversational_periods_are_calendar_intervals():
    from datetime import date
    from app.chat.language import requested_window
    today = date(2026, 11, 18)
    prior = (date(2028, 1, 1), date(2028, 12, 31))
    assert requested_window("And February?", today, prior) == (date(2028, 2, 1), date(2028, 2, 29))
    assert requested_window("next July", today) == (date(2027, 7, 1), date(2027, 7, 31))
    assert requested_window("15 July 2027", today) == (date(2027, 7, 15),) * 2
    assert requested_window("जुलाई 2027", today) == (date(2027, 7, 1), date(2027, 7, 31))
    assert requested_window("may I change jobs?", today) is None
    assert requested_window("And the month after that?", today, (date(2027, 12, 1), date(2027, 12, 31))) == (
        date(2028, 1, 1), date(2028, 1, 31))
    assert requested_window("June 15 to July 2, 2027", today) == (date(2027, 6, 15), date(2027, 7, 2))
    with pytest.raises(ValueError):
        requested_window("31 February 2027", today)
    with pytest.raises(ValueError):
        requested_window("2027-01-01 to 2099-12-31", today)


def test_year_ranges_parse_then_hit_the_one_year_cap():
    from datetime import date
    from app.chat.language import requested_window, raw_window
    today = date(2026, 11, 18)
    assert raw_window("2027 to 2040", today) == (date(2027, 1, 1), date(2040, 12, 31))
    assert raw_window("between 2027 and 2040", today) == (date(2027, 1, 1), date(2040, 12, 31))
    assert raw_window("2027-2040", today) == (date(2027, 1, 1), date(2040, 12, 31))
    assert raw_window("nov 2027 to 2040", today) == (date(2027, 11, 1), date(2040, 12, 31))
    for q in ("2027 to 2040", "nov 2027 to 2040", "between 2027 and 2040"):
        with pytest.raises(ValueError, match="one year"):
            requested_window(q, today)


def test_bare_dash_names_a_mahadasha_and_accident_keeps_its_own_clause():
    from datetime import date
    from app.chat.language import named_mahadasha, reported_accident_window
    today = date(2026, 11, 18)
    complaint = ("i think you are not able to predict properly...."
                 "my accident happened in rahu dash in 2014...you are connecting it to 2027")
    assert named_mahadasha(complaint) == "Rahu"
    assert reported_accident_window(complaint, today) == (date(2014, 1, 1), date(2014, 12, 31))


def test_repair_response_preserves_line_breaks():
    issues = ["unsupported date '2027-08-09'"]
    fixed = V.repair_response(
        "Fine sentence here.\n\n- bullet one stays.\n- Expect news on 2027-08-09.", issues)
    assert fixed == "Fine sentence here.\n\n- bullet one stays."
    # A claim wrapped across lines is still caught (the wrap must not bypass
    # the filter), while kept sentences preserve their original newlines.
    wrapped = V.repair_response(
        "You will\nreceive news on 2027-08-09.\nFine line stays.", issues)
    assert wrapped == "Fine line stays."
    # Unpunctuated rows read as one sentence: only the bad row is dropped.
    table = V.repair_response(
        "| Work | grows\n| Health | 2027-08-09\n| Family | steady", issues)
    assert table == "| Work | grows\n| Family | steady"
    # Rows already flattened to "a · b" by _plain_reply count as rows too.
    flat = V.repair_response(
        "Work · grows\nHealth · 2027-08-09\nFamily · steady", issues)
    assert flat == "Work · grows\nFamily · steady"
    # A wrapped claim riding on a row run: the rows survive, both halves of
    # the claim go.
    tail = V.repair_response(
        "| Work | grows\n| Home | steady\n| Family | calm\nyou will\nreceive news on 2027-08-09.",
        issues)
    assert tail == "| Work | grows\n| Home | steady\n| Family | calm"
    # A caveat heading before the table is kept when only one row is bad.
    caveat = V.repair_response(
        "Indicative timings\n| Work | 2027-08-09\n| Home | steady\n| Family | calm",
        issues)
    assert caveat == "Indicative timings\n| Home | steady\n| Family | calm"
    # A bad prose line after the table doesn't take the last row with it.
    tailrow = V.repair_response(
        "| Work | grows\n| Home | steady\n| Family | calm\nYou will receive news on 2027-08-09",
        issues)
    assert tailrow == "| Work | grows\n| Home | steady\n| Family | calm"
    # When every row is rejected, a bare lead-in is no reply — full fallback.
    empty = V.repair_response(
        "Key dates\n| Work | 2027-08-09\n| Home | 2027-08-09\n| Family | 2027-08-09",
        issues)
    assert "doesn't support" in empty
    # A claim wrapped as a bullet plus continuation drops both halves.
    wrapbullet = V.repair_response(
        "- Saturn sits\n  in Aries\n- Home steady",
        ["Saturn in Aries claim"])
    assert wrapbullet == "- Home steady"
    # When rows all fail, a substantive prose takeaway still answers.
    takeaway = V.repair_response(
        "- Work | 2027-08-09\n- Home | 2027-08-09\n- Family | 2027-08-09\n"
        "Overall the period still looks broadly supportive",
        issues)
    assert takeaway == "Overall the period still looks broadly supportive"
    # A colon lead-in under a fully rejected list is still no reply.
    colon = V.repair_response(
        "Here are the key dates:\n- a | 2027-08-09\n- b | 2027-08-09\n- c | 2027-08-09",
        issues)
    assert "doesn't support" in colon
    # A valid bullet and prose line sharing the claim's words are kept —
    # neither alone makes the rejected claim.
    shared = V.repair_response(
        "- Saturn rises\nAries supports you\n- Home steady",
        ["Saturn in Aries claim"])
    assert shared == "- Saturn rises\nAries supports you\n- Home steady"
    # Prose halves separated by dropped rows must not rejoin into the claim.
    rejoined = V.repair_response(
        "The chart places Saturn in\n- x | 2027-08-09\n- y | 2027-08-09\n"
        "- z | 2027-08-09\nthe sign of Aries",
        issues + ["Saturn in Aries claim"])
    assert "doesn't support" in rejoined
    # Wrapped prose in a 3-line sentence still drops whole — its leading
    # fragment must not survive row recovery.
    wrapped3 = V.repair_response(
        "Intro line\nYou will\nreceive news on 2027-08-09.\nCloser stays.", issues)
    assert wrapped3 == "Closer stays."


def test_llm_markdown_is_flattened_to_plain_text():
    from app.llm.providers import _plain_reply
    text = ("Intro sentence. ### Health outlook\n\n"
            "| Theme | Jupiter | Saturn |\n|---|---|---|\n| Work | grows | steady |\n\n**Keep going.**")
    out = _plain_reply(text)
    assert "###" not in out and "|" not in out and "**" not in out
    assert "Health outlook" in out and "Work · grows · steady" in out
    # Indentation marks a wrapped continuation — repair_response needs it.
    wrapped = _plain_reply("- Saturn sits\n  in Aries\n- Home steady")
    assert wrapped == "- Saturn sits\n  in Aries\n- Home steady"
    # An indented table divider is still a divider, not a bogus row.
    table = _plain_reply("| Work | grows |\n  |---|---|\n| Home | steady |")
    assert table == "Work · grows\nHome · steady"



def test_initial_checks_score_the_displayed_window(monkeypatch):
    from datetime import date
    birth, facts = make_facts()
    scored = []
    def evaluate(facts, birth, domain, start, end):
        scored.append((start, end))
        return {"support_count": 2, "conflict_count": 0, "traditional_rule_ids": [],
                "pillars": {}, "convergence": "support"}
    monkeypatch.setattr(C.pillars, "evaluate", evaluate)
    statements = C.generate_statements(facts, birth, "fp")
    assert len(statements) == 3
    for statement in statements:
        start = date.fromisoformat(statement["predicted_window"]["start"] + "-01")
        end_month = date.fromisoformat(statement["predicted_window"]["end"] + "-01")
        assert start >= date(birth.year, birth.month, birth.day)
        assert (end_month - start).days <= 397
        assert any(a == start and b.year == end_month.year and b.month == end_month.month for a, b in scored)


def test_untouched_old_checks_refresh_on_history_load():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    db, conv, prof = _db_profile_and_conv(h)
    for event in prof.calibrations:
        event.event_id = event.event_id.replace("recent_", "")
    conv.pending_event_id = conv.pending_event_id.replace("recent_", "")
    db.commit()
    db.close()
    history = client.get("/api/chat/history", headers=h).json()
    assert history[-1]["meta"]["event_id"].startswith("recent_calibration_")
    assert client.get("/api/chat/history", headers=h).json() == history



def test_opening_windows_allow_older_periods_and_periods_before_age_fifteen(monkeypatch):
    from datetime import date
    from dataclasses import replace
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 18)
    monkeypatch.setattr(C, "date", Today)
    birth, _ = make_facts()
    birth = replace(birth, year=2009, month=5, day=15)
    facts = {"vimshottari": {"periods": [
        {"lords": ["Sun", "Moon"], "start": "2021-01-01", "end": "2026-01-01"}]}}
    windows = C._past_ad_windows(facts, birth)
    assert windows
    assert min(w["start"] for w in windows) == date(2021, 1, 1)
    assert any(w["start"] < date(2024, 5, 15) for w in windows)
    birth = replace(birth, year=2012)
    assert C._past_ad_windows(facts, birth)



def test_opening_ranks_all_domains_and_accepts_two_indications(monkeypatch):
    from datetime import date
    birth, facts = make_facts()
    windows = [{"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
               {"start": date(2024, 1, 1), "end": date(2024, 12, 31)}]
    monkeypatch.setattr(C, "_past_ad_windows", lambda *args: windows)
    def evaluate(facts, birth, domain, start, end):
        score = 4 if domain == "relationship" and start.year == 2024 else 1
        return {"support_count": score, "conflict_count": 0, "traditional_rule_ids": [],
                "pillars": {}, "convergence": "support"}
    monkeypatch.setattr(C.pillars, "evaluate", evaluate)
    statements = C.generate_statements(facts, birth, "fp")
    assert len(statements) == 2
    assert statements[0]["domain"] == "relationship"
    outcome = C.calibration_outcome([{"user_feedback": "confirmed"}] * 2)
    assert outcome["state"] == "calibrated"
    assert "three" not in outcome["label"]


def test_mismatched_indications_invite_past_events_directly():
    h = register_and_profile()
    for _ in range(3):
        replies = send("No, that didn't happen", h)
    invitation = replies[-1]
    assert "two or three significant events" in invitation["content"]
    assert "approximate year" in invitation["content"]
    reply = send("started my first job in July 2012", h)
    assert "career, July 2012" in reply[-1]["content"]
    assert "Continue with the reading" in reply[-1]["meta"]["options"]


def test_frontend_assets_do_not_fall_back_to_html():
    page = client.get("/chat")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    missing = client.get("/_next/static/chunks/missing-deploy.js")
    assert missing.status_code == 404
    assert "text/html" not in missing.headers.get("content-type", "")
    assert missing.headers["cache-control"] == "no-store"
    from pathlib import Path
    assets = Path(__file__).resolve().parents[2] / "frontend/out/_next/static/chunks"
    chunk = next(assets.glob("*.js"))
    response = client.get("/_next/static/chunks/" + chunk.name)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "immutable" in response.headers["cache-control"]


def test_reset_preserves_completed_birth_time_checks():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    for _ in range(3):
        send("Yes, that happened", h)
    before = client.get("/api/calibration", headers=h).json()
    assert before["state"] == "calibrated"
    client.post("/api/chat/reset", headers=h)
    history = client.get("/api/chat/history", headers=h).json()
    after = client.get("/api/calibration", headers=h).json()
    assert after["state"] == before["state"]
    assert [(e["event_id"], e["user_feedback"]) for e in after["events"]] == [
        (e["event_id"], e["user_feedback"]) for e in before["events"]]
    assert all(not m["meta"].get("event_id") for m in history)


def test_factual_chart_lookup_does_not_repeat_birth_time_question():
    h = register_and_profile()
    history = client.get("/api/chat/history", headers=h).json()
    event_id = history[-1]["meta"]["event_id"]
    send("show my D9 chart", h)
    for _ in range(3):
        history = client.get("/api/chat/history", headers=h).json()
    assert sum(m["meta"].get("event_id") == event_id for m in history) == 1
    send("Yes, that happened", h)
    events = client.get("/api/calibration", headers=h).json()["events"]
    assert events[0]["user_feedback"] == "confirmed"


def test_forecast_asks_for_period_and_uses_conversational_duration(monkeypatch):
    from app.chat import orchestrator as O
    from datetime import date
    monkeypatch.setattr(O, "_today_at", lambda birth: date(2026, 11, 20))
    h = register_and_profile()
    send("Continue with the reading", h)
    first = send("Will I get a promotion?", h)[-1]
    assert first["meta"]["pending_domain"] == "career"
    assert "analysis" not in first["meta"] and "period" in first["content"]
    assert client.get("/api/predictions", headers=h).json()["predictions"] == []
    answer = send("next three months", h)[-1]
    a = answer["meta"]["analysis"]
    assert a["decision"]["event"]["event_type"] == "promotion"
    assert a["analysis_window"] == {"start": "2026-11-21", "end": "2027-02-19"}
    assert a["period_requested"]
    changed = send("Actually, only March 2027", h)[-1]["meta"]["analysis"]
    assert changed["analysis_window"] == {"start": "2027-03-01", "end": "2027-03-31"}


def test_duration_parser_handles_month_ends_and_short_periods():
    from app.chat.language import requested_window
    from datetime import date
    today = date(2027, 1, 31)
    assert requested_window("next one month", today) == (today, date(2027, 2, 27))
    assert requested_window("next 2 weeks", today) == (today, date(2027, 2, 13))
    assert requested_window("last six months", today) == (date(2026, 7, 31), date(2027, 1, 30))


def test_career_match_collects_current_options_and_preserves_timing():
    h = register_and_profile()
    first = send("Which job profile suits me?", h)[-1]
    assert first["meta"]["career_match"]["asked"] == "options"
    choices = send("BI analyst or corporate trainer", h)[-1]
    assert [r["title"] for r in choices["meta"]["career_result"]["roles"]] == [
        "Business intelligence analyst", "Learning and development specialist"]
    response = client.post("/api/chat/stream", json={"text": "I built SQL dashboards and I enjoy reporting."}, headers=h)
    reading = _parse_sse(response)[-1]["messages"][-1]
    assert reading["meta"]["career_result"]["leader"] == "Business intelligence analyst"
    assert client.get("/api/predictions", headers=h).json()["predictions"] == []
    chart = send("What does my chart say about this career?", h)[-1]
    assert chart["meta"]["classical"]["tables"]
    assert chart["meta"]["career_result"]["leader"] == "Business intelligence analyst"
    timing = send("Will I receive a job offer?", h)[-1]
    assert timing["meta"]["pending_event"]["event_type"] == "job_offer"
    assert "analysis" not in timing["meta"]
    assert "period" in timing["content"]
    forecast = send("next month", h)[-1]["meta"]
    assert forecast["analysis"]["decision"]["event"]["event_type"] == "job_offer"
    assert forecast["analysis"]["period_requested"]


def test_career_match_uses_offer_duties_and_rejects_constraint_conflicts():
    h = register_and_profile()
    text = (
        "Compare these offers\n"
        "Option A: Data analyst\nResponsibilities: SQL dashboards\nWork mode: remote\n"
        "Option B: Data analyst\nResponsibilities: Client meetings\nWork mode: on-site\n"
        "Option C: Data analyst\nResponsibilities: SQL dashboards\nWork mode: remote\n"
        "Requirements: master's degree\nSkills: SQL, dashboards\n"
        "Education: I don't have a master's degree\nConstraints: remote only"
    )
    result = send(text, h)[-1]["meta"]["career_result"]
    assert result["leader"] == "Option a · Data analyst"
    options = {r["title"]: r for r in result["roles"]}
    assert options["Option b · Data analyst"]["matched"] == []
    assert options["Option b · Data analyst"]["blockers"]
    assert "requires master’s degree" in options["Option c · Data analyst"]["blockers"]


def test_career_discovery_uses_stated_interests_and_leaves_ties_open():
    h = register_and_profile()
    first = send("Suggest careers. I am a student in India and I enjoy designing courses and lesson materials.", h)[-1]
    assert first["meta"]["career_result"]["leader"] == "Instructional designer"
    reply = send("Compare data analyst and BI analyst. Skills: SQL, dashboards", h)[-1]
    # A new comparison can use the person's existing context, while a single
    # skill shared by both roles doesn't decide the comparison.
    assert reply["meta"]["career_result"]["leader"] is None
    assert "are close" in reply["content"]
    winner = send("I prefer reporting.", h)[-1]
    assert winner["meta"]["career_result"]["leader"] == "BI analyst"


def test_career_intake_stays_with_its_profile():
    h = register_and_profile()
    own_id = client.get("/api/profile", headers=h).json()["id"]
    # Lookups of chart concepts must not enter the career intake.
    assert "career_match" not in send("Compare Saturn and Jupiter", h)[-1]["meta"]
    first = send("Suggest careers. I built SQL dashboards and I like reporting.", h)[-1]
    assert first["meta"]["career_result"]["leader"] == "Business intelligence analyst"
    assert client.post("/api/profiles", json=MUM, headers=h).status_code == 200
    other = send("Which job profile suits me?", h)[-1]["meta"]["career_match"]
    assert other["evidence"] == [] and other["options"] == []
    assert client.post(f"/api/profiles/{own_id}/activate", headers=h).status_code == 200
    again = client.get("/api/chat/history", headers=h).json()[-1]
    assert again["meta"]["career_result"]["leader"] == "Business intelligence analyst"


def test_career_match_accepts_uncatalogued_roles_and_stated_skills():
    h = register_and_profile()
    reply = send(
        "Compare these roles\n"
        "Option A: Optical bench technician\nDuties:\n- Laser alignment\n"
        "Option B: Test engineer\nDuties: software testing\n"
        "Skills: laser alignment", h)[-1]
    assert reply["meta"]["career_result"]["leader"] == "Option a · Optical bench technician"
    roles = reply["meta"]["career_result"]["roles"]
    assert roles[0]["matched"] == ["laser alignment"] and roles[0]["code"] is None


def test_chat_reuses_only_relevant_user_facts_after_they_leave_recent_history(monkeypatch):
    from app.chat import memory
    from app.llm import providers
    h = register_and_profile()
    _open_calibrated(h)
    statements = "I joined my first job in 2015. I work as a data analyst. My sister moved to Delhi in 2021."
    saved = send(statements, h)[0]["meta"][memory.KEY]
    assert [entry["kind"] for entry in saved] == ["milestone", "personal", "family"]
    send("Actually, I work as a school principal now.", h)
    assert memory.KEY not in send("Will I move to Mumbai next year?", h)[0]["meta"]
    for _ in range(8):
        send("Thanks.", h)
    remembered = []

    def generate(messages, **kwargs):
        assert not any(m["content"] == statements for m in messages)
        remembered.extend(kwargs["consultation_memory"])
        return "Let's discuss your career.", "offline"

    monkeypatch.setattr(providers, "generate", generate)
    send("What does my chart say about leadership in my career?", h)
    quotes = {entry["quote"] for entry in remembered}
    assert quotes == {"I joined my first job in 2015.", "Actually, I work as a school principal now."}
    recall = send("What do you remember about me?", h)[-1]["content"]
    assert "school principal" in recall and "sister moved" in recall
    assert "data analyst" not in recall


def test_chat_memory_stays_with_the_birth_profile_and_resets_with_chat():
    from app.chat.memory import KEY
    h = register_and_profile()
    own = client.get("/api/profile", headers=h).json()["id"]
    send("I got married in 2021.", h)
    other_profile = {**MUM, "relation": "mother", "display_name": "Mother"}
    assert client.post("/api/profiles", headers=h, json=other_profile).status_code == 200
    assert KEY not in send("I work as a data analyst.", h)[0]["meta"]
    assert KEY not in send("My father retired in 2018.", h)[0]["meta"]
    assert send("My mother retired in 2020.", h)[0]["meta"][KEY][0]["kind"] == "family"
    recall = send("What do you remember about me?", h)[-1]["content"]
    assert "mother retired" in recall and "married" not in recall
    assert client.post(f"/api/profiles/{own}/activate", headers=h).status_code == 200
    assert "married in 2021" in send("What do you remember about me?", h)[-1]["content"]
    exported = client.get("/api/auth/me/export", headers=h).json()
    assert any(m.get("saved_details") for c in exported["conversations"] for m in c["messages"])
    assert client.post("/api/chat/reset", headers=h).status_code == 200
    assert "married" not in send("What do you remember about me?", h)[-1]["content"]


def test_chat_keeps_reaction_to_reading_without_scoring_it_as_forecast_outcome():
    from app.chat.memory import KEY
    h = register_and_profile()
    _open_calibrated(h)
    reading = send("Will I get a promotion in my career next year?", h)[-1]
    feedback = send("Your prediction about my promotion was wrong.", h)
    entry = feedback[0]["meta"][KEY][0]
    assert entry["reading_id"] == reading["id"] and entry["status"] == "disagreed"
    assert "noted your feedback" in feedback[-1]["content"]
    assert "didn't match your experience" in send("What do you remember about me?", h)[-1]["content"]
    assert client.get("/api/predictions", headers=h).json()["predictions"][0]["outcome"] is None


def test_memory_extraction_rejects_invented_facts_and_partial_quotes(monkeypatch):
    from app.chat import memory
    from app.llm import providers
    line = "मैं पुणे में नृत्य सिखाती हूँ।"
    negative = "I am not a doctor."
    result = [
        {"kind": "personal", "domain": "career", "slot": "role", "quote": line},
        {"kind": "personal", "domain": "career", "slot": "role", "quote": "I am a doctor."},
        {"kind": "personal", "domain": "career", "slot": "role", "quote": "a doctor."},
    ]
    monkeypatch.setattr(providers, "consultation_memories", lambda *a, **k: result)
    captured = memory.capture(f"{line} {negative}", relation="self", allow_external=True)
    assert [entry["quote"] for entry in captured] == [line]


def test_career_comparison_uses_previously_shared_experience():
    h = register_and_profile()
    _open_calibrated(h)
    send("I have experience in SQL dashboards.", h)
    result = send("Compare BI analyst and corporate trainer", h)[-1]["meta"]["career_result"]
    assert result["leader"] == "BI analyst"
    assert "dashboards" in result["roles"][0]["matched"]


def test_provider_receives_saved_details_as_user_data(monkeypatch):
    from app.llm import providers
    seen = []

    def complete(system, messages, timeout):
        seen.append((system, messages))
        return "Let's consider your current work."

    monkeypatch.setattr(providers, "_available_providers", lambda allow_external: ["groq"])
    monkeypatch.setitem(providers.PROVIDERS, "groq", complete)
    question = "What should I look for in a new job?"
    saved = "I work as a school principal."
    providers.generate([{"role": "user", "content": question}],
                       consultation_memory=[{"kind": "personal", "quote": saved}])
    system, messages = seen[0]
    assert saved not in system
    assert messages[-1]["role"] == "user"
    assert saved in messages[-1]["content"] and messages[-1]["content"].endswith(question)


def _decision_answer(label, options, probability=0.9):
    other = (1 - probability) / (len(options) - 1)
    return {"type": "choice", "choice": label,
            "probabilities": {key: probability if key == label else other for key in options}}


def test_decider_uses_openrouter_decisions_and_preserves_the_confirmed_period(monkeypatch):
    import httpx
    from app.llm import decider, providers
    monkeypatch.setattr(providers.settings, "DECIDER_ENABLED", True)
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    calls = []
    choices = iter([("job_change", "keep"), ("career", "fresh"), ("job_offer", "fresh")])

    def post(url, *, headers, json, timeout):
        calls.append(json)
        assert url == decider.URL
        assert json["model"] == "perplexity/pplx-decider-flash-v1.3:free"
        assert "messages" not in json
        assert timeout <= 1.8
        label, period = next(choices)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"answers": {
            "topic": _decision_answer(label, json["questions"]["topic"]["criteria"]),
            "period": _decision_answer(period, json["questions"]["period"]["criteria"]),
        }})

    monkeypatch.setattr(decider.httpx, "post", post)
    h = register_and_profile()
    _open_calibrated(h)
    first = send("Will I get a promotion in July 2027?", h)[-1]["meta"]["analysis"]
    assert first["decision"]["event"]["event_type"] == "promotion" and not calls
    text = "Nahi, promotion nahi. Company change ki baat kar raha hoon, same period."
    done = _parse_sse(client.post("/api/chat/stream", json={"text": text}, headers=h))[-1]
    corrected = done["messages"][-1]["meta"]["analysis"]
    assert corrected["decision"]["event"]["event_type"] == "job_change"
    assert corrected["analysis_window"] == {"start": "2027-07-01", "end": "2027-07-31"}
    state = json.loads(calls[0]["state"])
    assert state["active_outcome"] == "promotion" and state["latest_user_message"] == text
    broad = send("Nahi, promotion nahi. Usi period mein general career outlook batao.", h)[-1]["meta"]["analysis"]
    assert broad["decision"]["event"] is None
    assert broad["analysis_window"] == corrected["analysis_window"]
    fresh = send("Separately, will I get a job offer?", h)[-1]
    assert fresh["meta"]["pending_event"]["event_type"] == "job_offer"
    assert "analysis" not in fresh["meta"] and "What period" in fresh["content"]
    assert len(calls) == 3


@pytest.mark.parametrize("failure", ["uncertain", "invalid_label", "truncated", "rate_limit", "timeout"])
def test_decider_falls_back_within_the_routing_budget(monkeypatch, failure):
    import httpx
    from app.llm import decider, providers
    monkeypatch.setattr(providers.settings, "DECIDER_ENABLED", True)
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    messages = [{"role": "user", "content": "Mere kaam mein tarakki ka koi yog hai?"}]
    fallbacks = []

    def post(url, *, headers, json, timeout):
        assert "period" not in json["questions"]
        request = httpx.Request("POST", url)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        answer = _decision_answer("promotion", decider.TOPICS, 0.4 if failure == "uncertain" else 0.9)
        if failure == "invalid_label":
            answer["choice"] = "invented_outcome"
        return httpx.Response(429 if failure == "rate_limit" else 200, request=request, json={
            "truncated": failure == "truncated", "answers": {"topic": answer},
        })

    def fallback(history, *, allow_external, timeout):
        fallbacks.append(timeout)
        return "promotion"

    monkeypatch.setattr(decider.httpx, "post", post)
    monkeypatch.setattr(providers, "conversation_topic", fallback)
    assert providers.route_topic(messages, allow_external=True) == "promotion"
    assert len(fallbacks) == 1 and 0 < fallbacks[0] <= 3


def test_decider_skips_external_request_without_both_consent_gates(monkeypatch):
    from app.llm import decider, providers
    monkeypatch.setattr(providers.settings, "DECIDER_ENABLED", True)
    monkeypatch.setattr(providers.settings, "OPENROUTER_API_KEY", "test")
    messages = [{"role": "user", "content": "What about then?"}]

    def unexpected(*args, **kwargs):
        pytest.fail("Decider should only run when the app and user allow external AI")

    monkeypatch.setattr(decider, "classify", unexpected)
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", False)
    assert providers.route_topic(messages, allow_external=True, use_fallback=False) is None
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    assert providers.route_topic(messages, allow_external=False, use_fallback=False) is None


def test_calculation_views_use_the_active_chart_and_show_versions():
    h = register_and_profile()
    dashboard = client.get("/api/chart-dashboard?as_of=2027-07-12", headers=h)
    assert dashboard.status_code == 200, dashboard.text
    data = dashboard.json()
    assert data["settings"]["dasha_year"] == {"mode": "julian", "days": 365.25}
    assert data["settings"]["varga_rule_version"]
    assert data["sensitivity"]["D4"]["margin_before_s"]
    assert data["vargas"]["D9"]["Moon"] and data["dashas"]["vimshottari"][-1]["lords"]
    assert sum(data["ashtakavarga"]["sav"]) == 337
    assert client.get("/api/chart-dashboard?as_of=1880-01-01", headers=h).status_code == 422
    coverage = client.get("/api/coverage").json()
    assert len(coverage["intents"]) == 60 and sum(coverage["counts"].values()) == 60
    assert sum(intent["phase"] == 1 for intent in coverage["intents"]) == 18
    ids = {intent["intent_id"] for intent in coverage["intents"]}
    assert len(ids) == 60
    saturday = client.get("/api/chart-transits?start=2019-01-01&end=2031-01-01&planet=Saturn", headers=h)
    assert saturday.status_code == 200, saturday.text
    events = saturday.json()
    assert all(e["at"].endswith("Z") for e in events["events"])
    assert {"sign_ingress", "nakshatra_ingress", "station"} <= {e["kind"] for e in events["events"]}
    assert len(events["sade_sati"]) > len({phase["phase"] for phase in events["sade_sati"]})
    assert events["kakshya_slices"] and any(row["bindu_active"] for row in events["kakshya_slices"])
    vedic_before = client.get("/api/chart/D1", headers=h).json()
    kp_result = client.get("/api/kp", headers=h)
    assert kp_result.status_code == 200, kp_result.text
    separate = kp_result.json()
    assert separate["frame"]["houses"] == "Placidus" and len(separate["cusps"]) == 12
    segments = separate["segments"]
    assert len(segments) == 249 and segments[0]["start_arcsec"] == 0 and segments[-1]["end_arcsec"] == 1296000
    assert all(left["end_arcsec"] == right["start_arcsec"] for left, right in zip(segments, segments[1:]))
    assert separate["ruling_planets"]["weekday_lord"]
    assert client.get("/api/chart/D1", headers=h).json() == vedic_before


def test_distress_never_routes_through_chart_memory_or_external_provider(monkeypatch):
    from app.chat import memory
    from app.llm import providers
    h = register_and_profile()
    _open_calibrated(h)
    def unexpected(*args, **kwargs):
        pytest.fail("Sensitive turn was sent through memory or a model")
    monkeypatch.setattr(memory, "capture", unexpected)
    monkeypatch.setattr(providers, "generate", unexpected)
    reply = send("I want to end my life. What does my chart say?", h)[-1]
    assert "14416" in reply["content"] and reply["kind"] == "private"
    pregnancy = send("Can I conceive next month according to my chart?", h)[-1]
    assert pregnancy["kind"] == "private" and "clinician" in pregnancy["content"]
    assert not client.get("/api/predictions", headers=h).json()["predictions"]


def test_shared_profile_requires_recorded_permission_and_supports_revocation():
    h = register_and_profile()
    assert client.post("/api/profiles", json={**MUM, "permission_confirmed": False}, headers=h).status_code == 422
    second = client.post("/api/profiles", json=MUM, headers=h).json()
    assert second["permission_confirmed"]
    endpoint = f"/api/profiles/{second['id']}/permission"
    assert client.put(endpoint, json={"permission_confirmed": False}, headers=h).status_code == 200
    assert client.get("/api/chart-dashboard", headers=h).status_code == 409
    assert client.get("/api/chat/history", headers=h).status_code == 409
    assert client.put(endpoint, json={"permission_confirmed": True}, headers=h).status_code == 200
    assert client.get("/api/chart-dashboard", headers=h).status_code == 200


def test_automatic_outcome_requests_default_to_off():
    h = register_and_profile()
    _open_calibrated(h)
    send("Will I get a promotion in July 2027?", h)
    _age_predictions(h)
    assert not any(m["meta"].get("followup_id") for m in send("Hello", h))
    assert client.get("/api/predictions", headers=h).json()["followups_enabled"] is False
    assert client.put("/api/predictions/followups", json={"enabled": True}, headers=h).status_code == 200
    assert any(m["meta"].get("followup_id") for m in send("Hello", h))


# ---------- professional-review improvements ----------

def test_verifier_lordship_claims():
    _, f = make_facts()
    h3 = f["houses"][3]["lord"]
    wrong = "Mars" if h3 != "Mars" else "Venus"
    r = V.verify_response(f"Your {h3} rules the 3rd house.", f, {})
    assert r["ok"], r["issues"]
    r = V.verify_response(f"Your {wrong} rules the 3rd house.", f, {})
    assert not r["ok"]


def test_verifier_varga_claims():
    _, f = make_facts()
    d9_sun = f["vargas"]["D9"]["Sun"]
    right = f["vargas"]["D9"]["Sun"]["sign_name"] if "sign_name" in d9_sun else None
    if right is None:
        from app.astro.constants import SIGN_NAMES
        right = SIGN_NAMES[d9_sun["sign"]]
    wrong = "Sagittarius" if right != "Sagittarius" else "Leo"
    r = V.verify_response(f"Sun is in {right} navamsa.", f, {})
    assert r["ok"], r["issues"]
    r = V.verify_response(f"Sun is in {wrong} navamsa.", f, {})
    assert not r["ok"]


def test_verifier_transit_claims():
    _, f = make_facts()
    f = {**f, "window_transits": {"Jupiter": ["Taurus", "Gemini"]}}
    r = V.verify_response("Jupiter is transiting Taurus now.", f, {})
    assert r["ok"], r["issues"]
    r = V.verify_response("Jupiter is transiting Aries now.", f, {})
    assert not r["ok"]


def test_facts_lines_include_pratyantar_transits_and_remedy():
    from app.llm.providers import _facts_lines
    _, f = make_facts()
    f = {**f,
         "window_label": "2027",
         "window_pratyantar": [{"lords": ["Jupiter", "Saturn", "Sun"],
                                "start": "2027-01-01", "end": "2027-02-15"}],
         "window_transits": {"Jupiter": ["Taurus"]},
         "domain_remedy": ("Jupiter", "Thursday observance — yellow donation")}
    text = "\n".join(_facts_lines(f))
    assert "Pratyantardasha" in text and "2027-01-01 to 2027-02-15" in text
    assert "Jupiter in Taurus" in text
    assert "Thursday observance" in text
    assert "Natal yogas" in text or "aspects" in text  # yogas only if fired


def test_dasha_overview_marks_verdicts():
    from app.chat.orchestrator import _dasha_overview
    from datetime import date
    facts = {"vimshottari": {"periods": [
        {"lords": ["Jupiter", "Saturn"], "start": "2027-01-01", "end": "2028-01-01"},
        {"lords": ["Jupiter", "Mars"], "start": "2028-01-01", "end": "2029-01-01"}]},
        "functional": {"benefics": ["Jupiter", "Mars"], "malefics": ["Saturn"],
                       "yogakaraka": None}}
    lines = _dasha_overview(facts, (date(2027, 1, 1), date(2030, 1, 1)))
    assert len(lines) == 2
    assert "Jupiter–Saturn" in lines[0] and "frictional" in lines[0]
    assert "Jupiter–Mars" in lines[1] and "supportive" in lines[1]


def test_new_event_types_parse():
    from app.astro.prediction import event_spec
    assert event_spec("when will I buy a house", "property")["event_type"] == "property_purchase"
    assert event_spec("will I settle abroad", "relocation")["event_type"] == "foreign_settlement"
    assert event_spec("will I travel abroad", "relocation")["event_type"] == "foreign_travel"
    assert event_spec("will I win the court case", "litigation")["event_type"] == "litigation_win"
    assert event_spec("when will the court case resolve", "litigation")["event_type"] == "litigation_resolution"
    assert event_spec("when will I be debt free", "debt")["event_type"] == "debt_cleared"


def test_transit_lookup_shortcut(monkeypatch):
    h = register_and_profile()
    _open_calibrated(h)
    replies = send("when does Jupiter enter my 7th house", h)
    assert any("Jupiter" in m["content"] for m in replies), replies


def test_prashna_answer(monkeypatch):
    h = register_and_profile()
    _open_calibrated(h)
    replies = send("will i ever travel", h)
    assert any("Prashna" in m["content"] or "prashna" in m["content"].lower() for m in replies), replies


def test_childbirth_prediction_is_declined():
    from app.chat.safety import private_reply
    assert private_reply("when will I have a baby")
    assert private_reply("when will childbirth happen")


def test_surgery_question_gets_no_prashna_verdict():
    h = register_and_profile()
    _open_calibrated(h)
    replies = send("will my surgery go well", h)
    assert not any("Prashna" in m["content"] for m in replies)


def test_conception_possibility_is_declined_but_child_schooling_is_not():
    from app.chat.safety import private_reply
    assert private_reply("is it possible for me to conceive and have children")
    assert private_reply("will i have children")
    assert private_reply("when will my baccha get college admission") is None
    assert private_reply("will my wife and i have a baccha")
    assert private_reply("i have children. when will i get a promotion") is None
    assert private_reply("if i do ivf, what are my chances")
    assert private_reply("when i conceive, will it be safe")


def test_surgery_timing_suggestion_carries_health_disclaimer():
    from app.astro.constants import HEALTH_DISCLAIMER
    h = register_and_profile()
    _open_calibrated(h)
    replies = send("which day is good for my surgery", h)
    assert any(HEALTH_DISCLAIMER in m["content"] for m in replies), replies
