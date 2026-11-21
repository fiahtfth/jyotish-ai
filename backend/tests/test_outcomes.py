"""Outcome tracking: pre-registration immutability, due list, outcome capture, backtest math, admin guard."""
import json
from datetime import date, datetime, timedelta

import pytest

from tests.test_jyotish import client, register_and_profile  # noqa: E402  (sets up the test DB)
from app.db import (BirthProfile, PredictionRecord, PreRegistrationError, SessionLocal)
from app.astro import backtest, preregistration as PR


def _analysis(support=3):
    return {"domain": "career", "analysis_window": {"start": "2020-02-01", "end": "2020-02-28"},
            "support_count": support, "conflict_count": 0, "unavailable_count": 0,
            "convergence": f"Traditional convergence: {support}/4 pillars indicate this window",
            "pillars": {"parashari": "support", "jaimini": "neutral"},
            "classical": {"promise": "Strong"},
            "decision": {"disposition": "event_indicated", "success_criteria": "promotion in window",
                         "event": {"event_type": "promotion", "definition": "A formal promotion."}},
            "evidence": [{"module": "parashari", "rule_id": "PARASHARI.DOMAIN_PERIOD", "rule_version": "v1",
                          "triggered_rules": ["dasha@2020-02-01: Sun/Moon", "dasha@2020-02-14: Sun/Mars",
                                              "transit Saturn in house 10 (first seen 2020-02-01)"]},
                         {"module": "jaimini", "rule_id": "JAIMINI.CHARA_CONTACT", "rule_version": "v1",
                          "triggered_rules": []}]}


def _profile_id(h):
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    with SessionLocal() as db:
        return db.query(BirthProfile).filter(BirthProfile.user_id == uid).first().id


def _make(pid, *, start=date(2020, 2, 1), end=date(2020, 2, 28), forecast="event_indicated", outcome=None):
    with SessionLocal() as db:
        rec = PredictionRecord(profile_id=pid, domain="career", question="Will I get a promotion?",
                               window_start=start, window_end=end, forecast=forecast, event_type="promotion",
                               convergence="x", success_criteria="promotion in window", outcome=outcome)
        payload = PR.build(_analysis(), settings_dict={"a": 1}, calc_fingerprint="fp")
        payload["window"] = {"start": start.isoformat(), "end": end.isoformat()}
        rec.registration = PR.make_registration(payload)
        db.add(rec)
        db.commit()
        return rec.id


def test_preregistration_payload_has_required_fields_and_stable_rule_ids():
    p = PR.build(_analysis(), settings_dict={"a": 1}, calc_fingerprint="fp", protocol="p1")
    fired = p["rules_fired"]["parashari"]["fired"]
    # dates/planets/house numbers are dropped so rule IDs are stable across charts
    assert fired == ["PARASHARI.DOMAIN_PERIOD/dasha", "PARASHARI.DOMAIN_PERIOD/transit_in_house"]
    assert p["convergence"]["n_of_4"] == 3 and p["promise_grade"] == "Strong"
    assert p["window"] == {"start": "2020-02-01", "end": "2020-02-28"}
    assert p["event"]["event_type"] == "promotion"
    assert len(p["settings_fingerprint"]) == 64 and len(p["rule_pack"]["sha256"]) == 64
    assert p["rule_pack"]["version"] == "v1" and p["app_version"] and p["registered_at"].endswith("Z")


def test_outcome_update_cannot_change_rules_or_window():
    pid = _profile_id(register_and_profile())
    rid = _make(pid)
    with SessionLocal() as db:
        rec = db.get(PredictionRecord, rid)
        before = rec.registration.payload_json
        rec.outcome, rec.outcome_at, rec.event_date = "happened", datetime(2020, 3, 1), date(2020, 2, 10)
        db.commit()                                   # outcome fields are editable
        rec.window_end = date(2030, 1, 1)
        with pytest.raises(PreRegistrationError):
            db.commit()
        db.rollback()
        rec = db.get(PredictionRecord, rid)
        rec.registration.payload_json = "{}"
        with pytest.raises(PreRegistrationError):
            db.commit()
        db.rollback()
        rec = db.get(PredictionRecord, rid)
        rec.snapshot_json = "tampered"
        with pytest.raises(PreRegistrationError):
            db.commit()
        db.rollback()
        rec = db.get(PredictionRecord, rid)
        assert rec.registration.payload_json == before and rec.outcome == "happened"
        assert PR.verify(rec.registration, rec)
        rec.registration.payload_sha256 = "0" * 64
        with pytest.raises(PreRegistrationError):
            db.commit()


def test_verify_detects_out_of_band_edits():
    pid = _profile_id(register_and_profile())
    rid = _make(pid, outcome="happened")
    with SessionLocal() as db:
        db.query(PredictionRecord).filter_by(id=rid).update({"window_end": date(2031, 1, 1)})  # bypasses ORM
        db.commit()
        rec = db.get(PredictionRecord, rid)
        assert not PR.verify(rec.registration, rec)
        rows, excluded = backtest.rows_from_db(db)
        assert excluded.get("registration_mismatch", 0) >= 1 and all(r["id"] != rid for r in rows)


def test_due_list_and_outcome_recording_validation():
    h = register_and_profile()
    other = register_and_profile()
    pid = _profile_id(h)
    due = _make(pid)
    _make(pid, start=date.today() + timedelta(days=1), end=date.today() + timedelta(days=30))   # not ended
    _make(pid, forecast="abstain")                                                               # not scorable
    answered = _make(pid, outcome="did_not")
    ids = [r["id"] for r in client.get("/api/predictions/due", headers=h).json()["due"]]
    assert ids == [due]
    assert client.get("/api/predictions/due", headers=other).json()["count"] == 0
    assert client.get("/api/predictions/due").status_code == 401
    assert [r["id"] for r in client.get("/api/predictions/history", headers=h).json()["answered"]] == [answered]

    url = f"/api/predictions/{due}/outcome"
    assert client.post(url, json={"outcome": "bogus"}, headers=h).status_code == 422
    assert client.post(url, json={"outcome": "happened"}, headers=h).status_code == 422          # needs a date
    assert client.post(url, json={"outcome": "happened", "event_date": "2999-01-01"}, headers=h).status_code == 422
    assert client.post(url, json={"outcome": "partly"}, headers=other).status_code == 404
    r = client.post(url, json={"outcome": "outside_window", "event_date": "2020-04-01"}, headers=h)
    assert r.status_code == 200 and r.json()["outcome"] == "outside_window"
    assert client.get("/api/predictions/due", headers=h).json()["count"] == 0
    with SessionLocal() as db:
        rec = db.get(PredictionRecord, due)
        assert rec.event_date == date(2020, 4, 1) and PR.verify(rec.registration, rec)


def _synthetic():
    rows = []
    for i in range(200):
        in_a = i < 80
        hit = (i % 5 < 3) if in_a else (i % 5 == 0)       # A: 48/80 = 60%; rest: 24/120 = 20%
        rows.append({"event_type": "promotion", "window_days": 365, "n_support": 3 if in_a else 2,
                     "outcome": "happened" if hit else "did_not",
                     "pillars": {"parashari": "support" if in_a else "neutral"},
                     "rules": (["R/a"] if in_a else []) + (["R/b"] if i % 4 == 0 else []) +
                              (["R/rare"] if i in (3, 90, 150) else [])})
    return rows


def test_backtest_math_lift_null_and_insufficient_data_guard():
    rep = backtest.build_report(_synthetic())
    assert rep["status"] == "evaluated" and rep["data"] == {"scored": 200, "hits": 72, "excluded": {}}
    a = rep["rules"]["R/a"]
    assert a["n"] == 80 and a["hit_rate"] == 0.6 and a["base_rate"] == 0.36
    assert a["lift"] == pytest.approx(0.6 / 0.36, abs=1e-3)
    assert a["null_hit_rate"] == pytest.approx(0.36, abs=0.02)        # shuffled-chart null sits at the base rate
    assert a["p_value"] < 0.01 and a["significant"]
    assert rep["pillars"]["parashari"]["lift"] == a["lift"]
    assert rep["rules"]["R/b"]["significant"] is False
    rare = rep["rules"]["R/rare"]
    assert rare["status"] == "insufficient data" and "hit_rate" not in rare
    assert rep["base_rates"] == [{"event_type": "promotion", "window": ">6m", "n": 200, "hits": 72,
                                  "base_rate": 0.36, "status": "evaluated"}]
    rel = {r["convergence"]: r for r in rep["convergence"]["reliability"]}
    assert rel["3/4"]["hit_rate"] == 0.6 and rel["2/4"]["hit_rate"] == 0.2
    b = rep["convergence"]["brier"]
    assert b["level_brier"] < b["base_rate_brier"] and b["skill"] > 0
    md = backtest.to_markdown(rep)
    assert "R/a" in md and "insufficient data" in md

    small = backtest.build_report(_synthetic()[:29])
    assert small["status"] == "insufficient data" and small["pillars"] == {} and small["rules"] == {}
    assert small["convergence"]["brier"] is None
    assert backtest.rule_weights(small) == {}


def test_shuffled_null_does_not_flag_random_rules():
    import random
    rng = random.Random(1)
    rows = [{"event_type": "x", "window_days": 30, "n_support": 3, "outcome": rng.choice(["happened", "did_not"]),
             "pillars": {}, "rules": ["R/noise"] if rng.random() < .5 else []} for _ in range(300)]
    e = backtest.build_report(rows)["rules"]["R/noise"]
    assert e["status"] == "evaluated" and not e["significant"]


def test_rule_weights_default_one_and_only_significant_rules_move(monkeypatch, tmp_path):
    rep = backtest.build_report(_synthetic())
    w = backtest.rule_weights(rep)
    assert w["R/a"] == 1.5 and w["R/b"] == 1.0 and w["R/rare"] == 1.0    # lift 1.67 clamped to 1.5
    assert backtest.rule_weights(path=tmp_path / "missing.json") == {}
    assert backtest.rule_weight("anything", {}) == 1.0
    from app.config import settings
    assert settings.USE_BACKTEST_WEIGHTS is False and backtest.active_rule_weights(tmp_path / "x.json") == {}
    backtest.write_report(rep, tmp_path)
    assert backtest.rule_weights(path=tmp_path / "backtest_report.json")["R/a"] == 1.5
    assert (tmp_path / "backtest_report.md").exists()


def test_admin_backtest_guard(monkeypatch):
    from app.main import settings as S
    h = register_and_profile()
    assert client.get("/api/admin/backtest").status_code == 401
    assert client.get("/api/admin/backtest", headers=h).status_code == 403
    email = client.get("/api/auth/me", headers=h).json()["email"]
    monkeypatch.setattr(S, "ADMIN_EMAILS", frozenset({email.lower()}))
    monkeypatch.setattr(backtest, "load_report", lambda *a, **k: None)
    r = client.get("/api/admin/backtest", headers=h)
    assert r.status_code == 200 and r.json()["status"] in ("evaluated", "insufficient data")
    assert "config" in r.json() and "data" in r.json()
