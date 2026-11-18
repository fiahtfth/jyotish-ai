"""Precision layer tests: kakshya, tara, filters, per-layer verdicts."""
import os, sys, json, uuid
from datetime import date

os.environ["JYOTISH_DATABASE_URL"] = "sqlite:////tmp/jyotish_test.db"
os.environ["JYOTISH_LLM_PROVIDER"] = "offline"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.astro import precision as P  # noqa: E402
from app.astro import pillars  # noqa: E402
from app.astro import constants as K  # noqa: E402
from app.astro.engine import engine, BirthInput  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_auth_throttle():
    """Many tests register users from the same TestClient IP."""
    from app.main import reset_auth_throttle
    reset_auth_throttle()
    yield
    reset_auth_throttle()


def make_facts(precision="exact"):
    b = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
                   second=0, lat=13.0827, lon=80.2707, tz_offset=5.5,
                   place_label="Chennai", birth_time_precision=precision)
    return b, engine.compute(b)


# ---------- pure functions ----------

def test_kakshya_slices():
    assert P.kakshya_of(0.0) == 0
    assert P.kakshya_of(3.74) == 0
    assert P.kakshya_of(3.75) == 1
    assert P.kakshya_of(15.0) == 4
    assert P.kakshya_of(29.99) == 7
    lords = [P.kakshya_lord(i) for i in range(8)]
    assert lords == ["Saturn", "Jupiter", "Mars", "Sun", "Venus",
                     "Mercury", "Moon", "Lagna"]


def test_tara_sequence():
    # janma = Rohini (index 4): counting forward gives the 9-tara cycle
    seq = [P.tara_of(4 + i, 4)[1] for i in range(9)]
    assert seq == P.TARA_NAMES
    for i in (2, 4, 6):  # Vipat, Pratyari, Naidhana slots
        assert P.tara_of(4 + i, 4)[0] in P.ADVERSE_TARAS
    assert P.tara_of(4 + 27, 4)[0] == 1  # wraps back to Janma


def test_prastara_matches_bav():
    """prastara[p][c][s] summed over contributors c must equal bav[p][s]."""
    b, facts = make_facts()
    pr = P._prastara(facts, b)
    assert pr is not None
    bav = facts["binnashtakavarga"]
    for p in range(7):
        for s in range(12):
            assert sum(pr[p][c][s] for c in range(8)) == bav[p][s], (p, s)


# ---------- layer outputs ----------

def test_evaluate_shape_and_verdict_passthrough():
    b, facts = make_facts()
    start, end = date(2027, 1, 1), date(2027, 12, 31)
    r = P.evaluate(facts, b, "career", start, end)
    core = pillars.evaluate(facts, b, "career", start, end)
    assert r["verdict"] == core
    for key in ("confirmation", "timing", "magnitude", "fast_triggers",
                "layer_verdicts"):
        assert key in r, key
    assert r["calibrated"] is True
    lv = r["layer_verdicts"]
    assert lv["core_pillars"] == core["convergence"]
    assert lv["yogini"] in ("support", "neutral", "conflict", "unavailable")
    # mid-2027 MD lord is Rahu for this chart — nodes have no shadbala row,
    # so "skipped" is also a correct outcome here
    assert lv["magnitude"] in ("modest", "notable", "major", "skipped")


def test_confirmation_labels():
    b, facts = make_facts()
    c = P.confirmation(facts, b, "career", date(2027, 1, 1), date(2027, 12, 31),
                       calibrated=True)
    assert c["label"] in ("Both confirmation methods support", "Mostly aligned",
                          "Mixed indications", "Hidden friction", "Unavailable")
    assert set(c["yogini"]["lords"])  # real lords were seen


def test_uncalibrated_skips_lagna_layers():
    b, facts = make_facts(precision="unknown")
    r = P.evaluate(facts, b, "career", date(2027, 1, 1), date(2027, 12, 31),
                   calibrated=False)
    assert r["calibrated"] is False
    assert r["magnitude"]["applied"] is False
    assert r["fast_triggers"]["ithasala"]["applied"] is False
    # moon-referenced domain signs, and no lagna frame in sudarshana
    assert r["timing"]["reference"] == "moon"
    frames = r["confirmation"]["sudarshana"].get("frames")
    assert frames == ["moon", "sun"]
    # planet-degree layers still run
    assert r["layer_verdicts"]["kakshya_timing"] == "applied"


def test_magnitude_on_calibrated_chart():
    b, facts = make_facts()
    # 2031 is inside Jupiter mahadasha for this chart — a real graha with a
    # shadbala row (mid-2027 sits in Rahu, which has none)
    m = P.magnitude(facts, b, date(2031, 6, 15), calibrated=True)
    assert m["applied"] is True
    assert m["label"] in ("modest", "notable", "major")
    assert m["dasha_lord"] in K.PLANET_NAMES.values()
    assert m["basis"]


def test_timing_windows_bounded():
    b, facts = make_facts()
    t = P.timing_windows(facts, b, "career", date(2027, 1, 1),
                         date(2028, 6, 30), calibrated=True)
    assert len(t["windows"]) <= 3
    from datetime import datetime as dt
    for w in t["windows"]:
        s = dt.strptime(w["start"], "%Y-%m-%d").date()
        e = dt.strptime(w["end"], "%Y-%m-%d").date()
        assert (e - s).days <= 28
        assert s >= date(2027, 1, 1) and e <= date(2028, 7, 7)
        assert w["why"]


def test_eclipse_detection():
    """A window covering 2027 must surface real eclipses."""
    b, facts = make_facts()
    hits = P._eclipse_hits(facts, b, date(2027, 1, 1), date(2027, 12, 31), True)
    kinds = {h["kind"] for h in hits}
    assert kinds == {"solar", "lunar"}
    dates = [h["date"] for h in hits]
    assert "2027-08-02" in dates          # known total solar eclipse
    for h in hits:
        assert isinstance(h["touches"], list)


def test_ithasala_and_watch_months():
    b, facts = make_facts()
    r = P.fast_triggers(facts, b, date(2027, 1, 1), date(2028, 6, 30), True)
    assert r["ithasala"]["applied"] is True
    for h in r["eclipses"]:
        if h["touches"]:
            assert h["date"][:7] in r["watch_months"]


def test_determinism():
    b, facts = make_facts()
    r1 = P.evaluate(facts, b, "relationship", date(2027, 1, 1), date(2027, 12, 31))
    r2 = P.evaluate(facts, b, "relationship", date(2027, 1, 1), date(2027, 12, 31))
    assert r1 == r2


def test_all_domains_run():
    b, facts = make_facts()
    for d in K.DOMAINS:
        r = P.evaluate(facts, b, d, date(2027, 1, 1), date(2027, 12, 31))
        assert r["verdict"]["convergence"]


# ---------- wired into the app: prediction records + replies ----------

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import init_db
    init_db()
    return TestClient(app)


ARJUN = dict(display_name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
             place_name="Chennai", place_state="Tamil Nadu", place_country="India",
             latitude=13.0827, longitude=80.2707, birth_time_precision="exact")


def _calibrated_client():
    c = _client()
    email = f"p_{uuid.uuid4().hex[:8]}@test.dev"
    tok = c.post("/api/auth/register",
                 json={"terms_accepted": True, "email": email, "password": "password123"}).json()["access_token"]
    h = {"authorization": f"Bearer {tok}"}
    c.put("/api/profile", json=ARJUN, headers=h)
    c.get("/api/chat/history", headers=h)
    for _ in range(3):
        c.post("/api/chat/send", json={"text": "Yes, that happened"}, headers=h)
    return c, h


def test_prediction_record_stores_layer_verdicts():
    c, h = _calibrated_client()
    prof = c.get("/api/profile", headers=h).json()
    assert prof["predictions_allowed"] is True
    r = c.post("/api/chat/send",
               json={"text": "Will I get a promotion in 2027?"}, headers=h)
    assert r.status_code == 200
    meta = next(m for m in reversed(r.json()) if "analysis" in m.get("meta", {}))
    assert "precision" in meta["meta"]["analysis"]
    assert meta["meta"]["analysis"]["precision"]["calibrated"] is True

    from app.db import SessionLocal, PredictionRecord
    db = SessionLocal()
    rec = (db.query(PredictionRecord)
           .order_by(PredictionRecord.id.desc()).first())
    lv = json.loads(rec.layer_verdicts)
    db.close()
    assert lv["core_pillars"].endswith(("Confirmed", "Conditional",
                                      "Conditional — weak signal")) \
        or "/4" in lv["core_pillars"]
    assert lv["confirmation"] in ("Both confirmation methods support", "Mostly aligned",
                                  "Mixed indications", "Hidden friction")
    assert "kakshya_timing" in lv and "eclipse" in lv


def test_why_reply_shows_precision_layers():
    c, h = _calibrated_client()
    c.post("/api/chat/send",
           json={"text": "Will I get a promotion in 2027?"}, headers=h)
    r = c.post("/api/chat/send", json={"text": "why"}, headers=h)
    body = " ".join(m["content"] for m in r.json())
    assert "Confirmation:" in body


def test_track_record_endpoint_includes_layer_verdicts():
    c, h = _calibrated_client()
    c.post("/api/chat/send",
           json={"text": "Will I get a promotion in 2027?"}, headers=h)
    rows = c.get("/api/predictions", headers=h).json()
    rec = next(r for r in reversed(rows["predictions"]) if r.get("layer_verdicts"))
    assert "yogini" in rec["layer_verdicts"]


def test_annual_records_cover_window_and_use_seven_planet_lords():
    b, facts = make_facts()
    result = P.fast_triggers(facts, b, date(2027, 1, 1), date(2027, 12, 31), True)["ithasala"]
    assert result["status"] == "applied" and result["errors"] == []
    assert [(r["varsha_start"], r["varsha_end_exclusive"], r["year_lord"]) for r in result["year_lords"]] == [
        ("2026-05-15", "2027-05-15", "Moon"), ("2027-05-15", "2028-05-15", "Venus")]


def test_failed_annual_chart_is_not_reported_as_applied(monkeypatch):
    b, facts = make_facts()
    def broken(*a, **kw):
        raise RuntimeError("annual calculation failed")
    monkeypatch.setattr(P.tajaka, "annual_chart", broken)
    r = P.fast_triggers(facts, b, date(2027, 1, 1), date(2027, 12, 31), True)
    assert r["ithasala"]["status"] == "unavailable"
    assert not r["ithasala"]["applied"] and r["ithasala"]["errors"]


def test_missing_precision_inputs_are_explicitly_unavailable(monkeypatch):
    b, facts = make_facts()
    monkeypatch.setattr(P, '_prastara', lambda *a: None)
    monkeypatch.setattr(P.yogini, 'get_running_dhasa_for_given_date', lambda *a, **kw: [])
    monkeypatch.setattr(P.drik, 'next_solar_eclipse', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('failed')))
    r = P.evaluate(facts, b, 'career', date(2027, 1, 1), date(2027, 12, 31), True)
    assert r['layer_verdicts']['kakshya_timing'] == 'unavailable'
    assert r['layer_verdicts']['yogini'] == 'unavailable'
    assert r['layer_verdicts']['eclipse'] == 'unavailable'


def test_strong_agreement_cannot_ignore_a_conflicting_pillar(monkeypatch):
    for i, name in enumerate(pillars.PILLARS):
        monkeypatch.setitem(pillars.PILLARS, name, lambda *a, _i=i: {'verdict': 'conflict' if _i == 3 else 'support'})
    r = pillars.evaluate({}, None, 'career', date(2027, 1, 1), date(2027, 12, 31))
    assert 'Strong' not in r['convergence'] and 'Confirmed' not in r['convergence']
    assert r['conflict_count'] == 1
