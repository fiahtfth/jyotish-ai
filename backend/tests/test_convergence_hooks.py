"""SPECIAL hooks: sade_sati, current_dasha, muhurta, compatibility, past_event, rectify, annual, transition."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.astro import transits
from app.astro.convergence import intents, rulepack, template_t
from app.astro.convergence.hooks import (annual, compatibility, current_dasha, muhurta, past_event, rectify,
                                         sade_sati, special, transition)
from app.astro.engine import BirthInput, engine

D = date.fromisoformat
ARJUN = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0, lat=13.0827,
                   lon=80.2707, tz_offset=5.5, place_label="Chennai", birth_time_precision="exact")
PARTNER = BirthInput(name="P", year=1992, month=8, day=3, hour=14, minute=0, second=0, lat=19.07, lon=72.87,
                     tz_offset=5.5, place_label="Mumbai", birth_time_precision="exact")
EVENTS = [{"date": "2015-06-01", "type": "job"}, {"date": "2019-02-10", "type": "marriage"},
          {"date": "2022-08-01", "type": "relocation"}]


@pytest.fixture(scope="module")
def facts():
    return engine.compute(ARJUN)


def test_sade_sati_phases(facts, monkeypatch):
    # natal Moon Sagittarius (8): Scorpio=12th (rising), Sagittarius=1st, Capricorn=2nd, Pisces=4th, Cancer=8th
    rows = [(7, D("2014-11-02"), D("2017-01-25")), (8, D("2017-01-26"), D("2017-06-20")),
            (7, D("2017-06-21"), D("2017-10-25")), (8, D("2017-10-26"), D("2020-01-23")),
            (9, D("2020-01-24"), D("2022-04-28")), (10, D("2022-04-29"), D("2025-03-28")),
            (11, D("2025-03-29"), D("2027-06-02"))]
    monkeypatch.setattr(transits, "sign_intervals", lambda b, p, s, e: rows)
    out = sade_sati.phases(facts, ARJUN, D("2014-11-02"), D("2027-06-02"))
    kinds = [(r["kind"], r["phase"]) for r in out["phases"]]
    assert kinds[:5] == [("sade_sati", "rising (first)"), ("sade_sati", "peak (second)"),
                         ("sade_sati", "rising (first)"), ("sade_sati", "peak (second)"),
                         ("sade_sati", "setting (third)")]            # retrograde re-entry kept
    assert kinds[-1] == ("kantaka", None) and out["phases"][-1]["rule_id"] == "HOOK_DHAIYA"
    assert all(r["saturn_bav"] is not None for r in out["phases"])
    no_d = sade_sati.phases(facts, ARJUN, D("2014-11-02"), D("2027-06-02"), include_dhaiya=False)
    assert all(r["kind"] == "sade_sati" for r in no_d["phases"])


def test_current_dasha_shape(facts):
    out = current_dasha.current(facts, ARJUN, D("2026-06-01"))
    assert out["available"] and set(out["lords"]) == {"MD", "AD", "PD"}
    md = out["lords"]["MD"]
    assert md["lord"] == "Rahu" and md["occupies_house"] == 9 and "D9" in md["vargas"]
    assert out["most_activated_houses"] and out["chara"]["available"]
    assert "cross-check" in out["yogini"]["note"]
    assert out["rule_id"] == "HOOK_CURRENT_DASHA"


def test_muhurta_badge():
    slot = {"factors": [{"id": "F-VARA", "ok": True}, {"id": "F-TITHI", "ok": True}, {"id": "F-NAK", "ok": True},
                        {"id": "F-YOGA", "ok": True}, {"id": "F-TARA", "ok": False}, {"id": "F-CHANDRA", "ok": True},
                        {"id": "F-LAGNA", "ok": True}, {"id": "F-8H", "ok": True}, {"id": "F-BEN", "ok": True},
                        {"id": "F-MOON", "ok": True}, {"id": "F-DURM", "ok": True}]}
    g = muhurta.group_slot(slot)
    assert g["badge4"] == "Muhurta factors satisfied: 3/4" and g["groups"]["tarabala_chandrabala"]["status"] == "not_satisfied"
    g2 = muhurta.group_slot({"factors": [{"id": "F-VARA", "ok": True}]})
    assert g2["badge4"] == "Muhurta factors satisfied: 1/4 (1 of 4 evaluated)"


def test_compatibility_requires_consent_and_badge(facts):
    other = engine.compute(PARTNER)
    with pytest.raises(compatibility.ConsentRequired):
        compatibility.compatibility(facts, other, consent=False)
    out = compatibility.compatibility(facts, other, consent=True)
    assert out["badge"].startswith("Compatibility methods agreeing: ") and 0 <= out["n"] <= 4
    assert [m["method"] for m in out["methods"]] == ["M1_ashtakoota", "M2_mangal_dosha", "M3_cross_links",
                                                      "M4_dasha_alignment"]
    assert "doom" not in out["note"].lower()


def test_past_event_record_frozen(facts):
    out = past_event.check(facts, ARJUN, EVENTS)
    assert out["rulepack_hash"] == rulepack.pack_hash() and len(out["records"]) == 3
    rec = out["records"][0]
    assert rec.intent_id == "JOB_TIMING" and rec.badge.startswith("Traditional convergence: ")
    assert rec.kp_label == "KP: not evaluated" and len(rec.pillars) == 4
    assert past_event.verify_record(rec)
    with pytest.raises(FrozenInstanceError):
        rec.n = 4
    with pytest.raises(TypeError):
        rec.payload["window"] = None
    tampered = replace(rec, n=rec.n + 1)
    assert not past_event.verify_record(tampered)
    with pytest.raises(ValueError):
        past_event.check(facts, ARJUN, [{"date": "2020-01-01", "type": "no_such_event"}])


def test_rectify_clear_lead_rule():
    clear = rectify.rank([{"id": "a", "per_event_n": [3, 3, 2]}, {"id": "b", "per_event_n": [1, 1, 2]}])
    assert clear["verdict"] == "consistent with" and clear["ranked"][0]["id"] == "a" and clear["margin"] == 4
    close = rectify.rank([{"id": "a", "per_event_n": [3, 1, 2]}, {"id": "b", "per_event_n": [1, 2, 2]}])
    assert close["verdict"] == "cannot distinguish"
    assert rectify.rectify(ARJUN, EVENTS[:2])["status"] == "needs_input"
    full = rectify.rectify(ARJUN, EVENTS, span_min=5)
    assert full["verdict"] in ("consistent with", "cannot distinguish") and "verified" not in full["verdict"]
    sigs = [tuple(map(str, r["signature"].values())) for r in full["ranked"]]
    assert len(sigs) == len(set(sigs)) >= 1            # one representative per distinct combination


def test_annual_rank(facts):
    s = {"career": {"best_n": 3, "supportive_days": 40, "caution_score": 10, "month_markers": []},
         "finance": {"best_n": 3, "supportive_days": 90, "caution_score": 5, "month_markers": []},
         "property": {"best_n": 1, "supportive_days": 0, "caution_score": 300, "month_markers": []},
         "education": {"best_n": 2, "supportive_days": 0, "caution_score": 0, "month_markers": []}}
    r = annual.rank_domains(s)
    assert r["top_themes"] == ["finance", "career", "education"] and r["caution_theme"] == "property"
    out = annual.annual_themes(facts, ARJUN, D("2026-06-01"))
    assert len(out["top_themes"]) == 3 and set(out["domains"]) == set(annual.DOMAINS)
    assert out["year"][0] == "2026-05-15"


def test_transition_marker_count(facts):
    ms = [{"kind": "MD", "date": "2026-01-01", "factor": "MOON_NAKSHATRA"},
          {"kind": "Saturn return", "date": "2026-03-01", "factor": "TRANSIT:SATURN"},
          {"kind": "Sade Sati starts", "date": "2026-04-01", "factor": "TRANSIT:SATURN"},
          {"kind": "Jupiter return", "date": "2026-11-01", "factor": "TRANSIT:JUPITER"},
          {"kind": "Chara", "date": "2027-12-01", "factor": "LAGNA_SIGN:CHARA"}]
    best = transition.count_in_span(ms)
    assert best["count"] == 3 and best["start"] == "2026-01-01"       # Saturn markers count once
    out = transition.life_transition(facts, ARJUN, D("2026-06-01"))
    assert out["badge"].startswith("Independent transition markers") and all(
        D("2026-06-01") <= D(m["date"]) <= D("2028-06-01") for m in out["markers"])


def test_special_dispatch_needs_input(facts):
    for iid in ("MUHURTA", "PAST_EVENT_CHECK", "BIRTH_TIME_CHECK", "COMPATIBILITY"):
        out = special.dispatch(intents.get(iid), facts, ARJUN)
        assert out["status"] == "needs_input"
    stress = special.dispatch(intents.get("STRESS_PHASE"), facts, ARJUN, today=D("2026-06-01"))
    assert "14416" in stress["note"] and stress["badge"] is None
