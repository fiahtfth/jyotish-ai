"""Template T end-to-end: segmentation, per-window convergence, de-dup, promise cap, NE in unknown time,
natal overlay dispatch, specificity report shape, read-only API."""
import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.astro.convergence import dedup, intents, specificity, template_t
from app.astro.convergence.types import (A, NE, PROMISE_MODERATE, PROMISE_WEAK, S, W, Evidence, IntentConfig,
                                         PillarResult, PromiseResult)
from app.astro.engine import BirthInput, engine
from app.astro.settings import DEFAULT as DEFAULT_SETTINGS

D = date.fromisoformat
BIRTH = SimpleNamespace(settings=DEFAULT_SETTINGS, place_label="X", lat=0.0, lon=0.0, tz_offset=0.0,
                        year=1990, month=5, day=15, hour=6, minute=0, second=0, birth_time_precision="exact")
ARJUN = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0, lat=13.0827,
                   lon=80.2707, tz_offset=5.5, place_label="Chennai", birth_time_precision="exact")
RNG = (D("2025-01-01"), D("2025-12-31"))


@pytest.fixture(autouse=True)
def fresh_cache():
    template_t.clear_cache()          # stubs differ per test; the cache keys on the birth, not the stubs
    yield
    template_t.clear_cache()


def ev(*factors, d=1):
    return Evidence("X", "1", (), d, 1.0, frozenset(factors))


def cfg(template="T", **kw):
    d = {"intent_id": "TEST_INTENT", "number": 9, "phase": 1, "template": template, "E": [7], "E_optional": [],
         "E_adverse_explicit": [], "K": ["Venus"], "V": ["D9"], "J": ["DK"],
         "TAJ": {"houses": [7], "muntha_supportive": [7]}, "TRIG": {"slow": ["Saturn"], "fast": []},
         "KP": {"houses": [], "negate": [], "status": "ne"}, "hooks": [], "min_n_for_label": 3,
         "requires_consent": False, "safety_domain": "marriage_relationship", "legacy_ids": [],
         "forecast_events": []}
    d.update(kw)
    return IntentConfig.from_dict(d)


def synthetic(monkeypatch, promise_level=PROMISE_MODERATE, p1=None):
    p1 = p1 or [PillarResult("P1", S, (ev("PLANET:VENUS", "MOON_NAKSHATRA"),), ("2025-01-01", "2025-06-30")),
                PillarResult("P1", W, (ev("PLANET:SUN", "MOON_NAKSHATRA"),), ("2025-07-01", "2025-12-31"))]
    monkeypatch.setitem(template_t._EVALUATORS, "P1", lambda f, b, c, s, e: p1)
    monkeypatch.setitem(template_t._EVALUATORS, "P2", lambda f, b, c, s, e: [
        PillarResult("P2", S, (ev("ARUDHA:UL"),), ("2025-01-01", "2025-12-31"))])
    monkeypatch.setitem(template_t._EVALUATORS, "P3", lambda f, b, c, s, e: [
        PillarResult("P3", S, (ev("VARSHA:HOUSE:7"),), (D("2024-05-15"), D("2025-12-31")))])
    monkeypatch.setitem(template_t._EVALUATORS, "P4", lambda f, b, c, s, e: [
        PillarResult("P4", S, (ev("BAV:SATURN:6"),), (D("2025-03-01"), D("2025-03-20")))])
    monkeypatch.setattr(template_t, "promise_gate", lambda f, c: PromiseResult(promise_level, 1))
    return {"vimshottari": {"periods": []}, "meta": {"birth_time_precision": "exact"}}


def test_template_t_segments_and_converge(monkeypatch):
    f = synthetic(monkeypatch)
    out = template_t.template_T(f, BIRTH, cfg(), *RNG, with_kp=False)
    assert [w.segment for w in out.windows] == [(D("2025-01-01"), D("2025-06-30")), (D("2025-07-01"), D("2025-12-31"))]
    first, second = out.windows[0].result, out.windows[1].result
    assert first.n == 4 and first.result_type == "supportive_period"
    assert first.interval == (D("2025-03-01"), D("2025-03-20"))            # narrowed P1 -> P4
    assert first.badge == "Traditional convergence: 4/4"
    assert second.n == 2 and second.result_type == "weak_indication"      # P1 W, P4 nothing inside
    assert out.supportive == (out.windows[0],)
    ids = dedup.rule_ids(first)
    assert set(ids) == {"P1", "P2", "P3", "P4", "KP"} and ids["P1"] == ["X"]


def test_p4_aggregate():
    seg = (D("2025-01-01"), D("2025-01-31"))
    s = PillarResult("P4", S, (ev("BAV"),), (D("2025-01-10"), D("2025-01-12")))
    w = PillarResult("P4", W, (ev("T"),), (D("2025-01-01"), D("2025-02-10")))
    a = PillarResult("P4", A, (ev("B", d=-1),), (D("2025-01-05"), D("2025-01-20")))
    assert template_t.aggregate_p4([s, w], seg).interval == (D("2025-01-10"), D("2025-01-12"))
    assert template_t.aggregate_p4([a], seg).value == A
    assert template_t.aggregate_p4([a, w], seg).value == W
    assert template_t.aggregate_p4([PillarResult.not_evaluated("P4", "x")], seg).value == NE
    outside = PillarResult("P4", S, (ev("BAV"),), (D("2025-03-01"), D("2025-03-02")))
    assert template_t.aggregate_p4([outside], seg).value == W


def test_template_t_adverse_framing(monkeypatch):
    f = synthetic(monkeypatch)
    out = template_t.template_T(f, BIRTH, cfg("T_adverse"), *RNG, with_kp=False)
    assert out.framing == "pressure" and out.promise is None
    assert out.windows[0].display_type == "elevated_pressure_period"
    assert any("T_ADVERSE_FRAMING" in n for n in out.windows[0].result.notes)


def test_promise_weak_caps_result(monkeypatch):
    f = synthetic(monkeypatch, promise_level=PROMISE_WEAK)
    out = template_t.template_T(f, BIRTH, cfg(), *RNG, with_kp=False)
    r = out.windows[0].result
    assert r.n == 4 and r.result_type == "weak_indication"
    assert any("WEAK" in n for n in r.notes)


def test_dedup_vimshottari_yogini_one_factor_and_same_planet_dependent():
    c = cfg()
    # Vimshottari (P1) and Yogini share MOON_NAKSHATRA: a pillar resting only on it is dependent
    p1 = PillarResult("P1", S, (ev("PLANET:VENUS", "MOON_NAKSHATRA"),))
    yog = PillarResult("P2", S, (ev("MOON_NAKSHATRA"),))
    w = dedup.converge([p1, yog], None, c)
    assert w.n == 1 and w.dependent == ("P2",) and "dependent" in w.pillars[1].label
    # same planet in P1 and P2 -> P2 dependent; with a fresh factor it counts
    p2 = PillarResult("P2", S, (ev("PLANET:VENUS"),))
    assert dedup.converge([p1, p2], None, c).dependent == ("P2",)
    p2b = PillarResult("P2", S, (ev("PLANET:VENUS", "ARUDHA:UL"),))
    assert dedup.converge([p1, p2b], None, c).n == 2


def test_unknown_time_lagna_pillars_ne(monkeypatch):
    f = synthetic(monkeypatch)
    f["meta"]["birth_time_precision"] = "unknown"
    for name in ("P2", "P3", "P4"):              # real evaluators: must refuse without a birth time
        monkeypatch.setitem(template_t._EVALUATORS, name, template_t.__dict__["timing_p" + name[1]].evaluate)
    out = template_t.template_T(f, BIRTH, cfg(), *RNG, with_kp=True)
    assert out.promise is None
    for w in out.windows:
        r = w.result
        assert r.ne_pillars == ("P2", "P3", "P4") and r.result_type == "insufficient_data"
        assert "1 of 4 methods evaluated" in r.badge and r.kp.value == NE


def test_real_chart_end_to_end_and_cache():
    facts = engine.compute(ARJUN)
    c = intents.get("MARRIAGE_TIMING")
    template_t.clear_cache()
    out = template_t.template_T(facts, ARJUN, c, D("2026-01-01"), D("2027-12-31"))
    assert out.windows and out.windows[0].segment[0] == D("2026-01-01") and out.windows[-1].segment[1] == D("2027-12-31")
    for a, b in zip(out.windows, out.windows[1:]):
        assert (b.segment[0] - a.segment[1]).days == 1                    # contiguous tiling
    for w in out.windows:
        r = w.result
        assert 0 <= r.n <= r.k_evaluated <= 4 and r.kp.value == NE       # KP rows unverified
        assert r.interval is None or w.segment[0] <= r.interval[0] <= r.interval[1] <= w.segment[1]
    assert template_t.template_T(facts, ARJUN, c, D("2026-01-01"), D("2027-12-31")) is out
    with pytest.raises(ValueError):
        template_t.template_T(facts, ARJUN, intents.get("SPOUSE_NATURE"), D("2026-01-01"), D("2026-02-01"))


def test_run_intent_natal_overlay_dispatch():
    facts = engine.compute(ARJUN)
    res = template_t.run_intent(facts, ARJUN, "CAREER_STAGNATION", today=D("2026-06-01"))
    assert res["natal"].overlay is not None and res["natal"].overlay.pillar == "P1"
    assert "timing" not in res
    nt = template_t.run_intent(facts, ARJUN, "JOB_VS_BUSINESS", D("2026-01-01"), D("2026-06-30"), today=D("2026-06-01"))
    assert {"natal", "timing"} <= set(nt) and nt["natal"].overlay is not None
    sp = template_t.run_intent(facts, ARJUN, "SADE_SATI", today=D("2026-06-01"))
    assert sp["special"]["phases"]


def test_specificity_report_shape(tmp_path):
    rep = specificity.run(2, ["JOB_TIMING"], seed=1)
    row = rep["intents"]["JOB_TIMING"]
    assert set(row) >= {"status", "chart_windows", "supportive_chart_rate", "mean_supportive_window_share", "gate"}
    assert row["chart_windows"] == 2 and row["status"].startswith("provisional")
    assert rep["protocol"]["gate"].startswith("supportive_period on <= 25%")
    assert set(specificity.timing_intents(1)) == {
        "JOB_TIMING", "CAREER_PROMOTION", "JOB_CHANGE", "JOB_VS_BUSINESS", "MARRIAGE_TIMING", "INCOME_IMPROVEMENT",
        "COMPETITIVE_EXAMS", "FOREIGN_TRAVEL", "FOREIGN_SETTLEMENT", "PROPERTY_PURCHASE"}
    if specificity.REPORT.exists():           # committed report is readable by registry.coverage()
        data = json.loads(specificity.REPORT.read_text())
        assert data["intents"] and all("supportive_chart_rate" in r for r in data["intents"].values())
        from app.astro import registry
        cov = registry.coverage()["spec"]
        assert cov["specificity_report"]
        assert next(i for i in cov["intents"] if i["intent_id"] == "JOB_TIMING")["specificity"]


def test_api_convergence_endpoint():
    from tests.test_jyotish import ARJUN as ARJUN_PROFILE, client
    import uuid
    r = client.post("/api/auth/register", json={"terms_accepted": True, "age_confirmed": True,
                                                  "email": f"cv_{uuid.uuid4().hex[:8]}@test.dev",
                                                  "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert client.put("/api/profile", json=ARJUN_PROFILE, headers=h).status_code == 200
    out = client.post("/api/convergence/MARRIAGE_TIMING", json={"start": "2026-01-01", "end": "2026-12-31"}, headers=h)
    assert out.status_code == 200, out.text
    body = out.json()
    w = body["timing"]["windows"][0]
    assert w["badge"].startswith("Traditional convergence: ") and w["kp"] == "KP: not evaluated"
    assert {p["pillar"] for p in w["pillars"]} == {"P1", "P2", "P3", "P4"} and "rule_ids" in w
    assert client.post("/api/convergence/9", json={}, headers=h).status_code == 200
    assert client.post("/api/convergence/NOPE", json={}, headers=h).status_code == 404
    assert client.post("/api/convergence/MUHURTA", json={}, headers=h).status_code == 422
    assert client.post("/api/convergence/JOB_TIMING", json={"start": "2026-01-01", "end": "2031-01-01"},
                       headers=h).status_code == 422
    nat = client.post("/api/convergence/SPOUSE_NATURE", json={}, headers=h).json()
    assert nat["natal"]["badge"].startswith("Natal agreement: ")
    kp = client.get("/api/kp", headers=h).json()
    assert kp["frame"]["ayanamsa"] == "LAHIRI" and "sub_sub_lord" in kp["cusps"][0]
