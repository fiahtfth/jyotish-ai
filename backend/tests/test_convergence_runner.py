"""Gated timing runner: promise -> varga -> dasha -> transit -> micro, strict order."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.astro import constants as K
from app.astro.convergence import backtest, runner, select
from app.astro.convergence.runner import (_confidence, analysis_from_run, lookback_result,
                                          promise_with_moon, why_summary)
from app.astro.convergence.types import (A, M, NE, S, W, Evidence, IntentConfig, PillarResult,
                                         PROMISE_STRONG, PROMISE_WEAK, PromiseResult,
                                         SUPPORTIVE_PERIOD, WEAK_INDICATION, INSUFFICIENT_DATA)

ROOT = Path(__file__).resolve().parents[1]
SIGNS = {"Sun": 0, "Moon": 1, "Mars": 3, "Mercury": 2, "Jupiter": 11, "Venus": 2, "Saturn": 6, "Rahu": 8, "Ketu": 2}
NAK = {"Sun": "Sun", "Moon": "Sun", "Mars": "Sun", "Mercury": "Moon", "Jupiter": "Venus", "Venus": "Mercury",
       "Saturn": "Sun", "Rahu": "Jupiter", "Ketu": "Sun"}


def make_facts(signs=None, lagna=0, **extra):
    signs = {**SIGNS, **(signs or {})}
    planets = {n: {"sign": s, "house": (s - lagna) % 12 + 1, "nakshatra": {"lord": NAK[n]}, "dignity": [],
                   "combust": False, "retrograde": False, "vargottama": False} for n, s in signs.items()}
    houses = {h: {"sign": (lagna + h - 1) % 12, "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]}
              for h in range(1, 13)}
    facts = {"lagna": {"sign": lagna}, "planets": planets, "houses": houses,
             "meta": {"birth_time_precision": "exact"}}
    facts.update(extra)
    return facts


def cfg(**over):
    d = json.loads((ROOT / "data" / "intents" / "09_MARRIAGE_TIMING.json").read_text())
    d.update(over)
    return IntentConfig.from_dict(d)


def _res(value, pillar="P1", rid="R", direction=1, interval=None):
    ev = Evidence(rid, "1.0", (), direction, 1.0, frozenset({pillar + "_F"}), interval, "note")
    return PillarResult(pillar, value, (ev,), interval)


def _act(interval, value=S, double_transit=True):
    evs = [Evidence("P1_ACTIVATION", "1.0", (), 1, 1.0, frozenset({"P1_F"}), interval, "AD links")]
    if double_transit:
        evs.append(Evidence("P1_DOUBLE_TRANSIT", "1.0", (), 1, 1.0, frozenset(), interval,
                            "Jupiter+Saturn reach the house"))
    return PillarResult("P1", value, tuple(evs), interval)


BIRTH = MagicMock()


# ------------------------------------------------------------------ moon promise

def test_promise_adds_moon_chart_factor():
    f = make_facts()
    res = promise_with_moon(f, cfg())
    names = [fac.name for fac in res.factors]
    assert "F7_moon_house" in names
    f7 = res.factors[-1]
    assert f7.available and "Moon" in f7.note


# ------------------------------------------------------------------ gate order

def _stop_run(facts, **kw):
    kw.setdefault("reliability", {"D9": "stable"})
    kw.setdefault("moon_check", {"status": "stable"})
    return runner.timing_run(facts, BIRTH, cfg(), date(2027, 1, 1), date(2027, 12, 31), **kw)


def test_weak_promise_stops_before_dasha():
    f = make_facts()
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_WEAK, -2, (), (), ("F1",))), \
         patch.object(runner.timing_p1, "evaluate") as p1:
        run = _stop_run(f)
    p1.assert_not_called()                       # dasha never ran
    assert run.stopped_at == "promise"
    assert run.result.result_type in (WEAK_INDICATION, INSUFFICIENT_DATA)
    assert run.result.promise.level == PROMISE_WEAK
    assert run.confidence == "low"


def test_no_dasha_link_stops_before_transit():
    f = make_facts()
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())), \
         patch.object(runner.timing_p1, "evaluate",
                      return_value=[_res(W, interval=("2027-01-01", "2027-05-01"))]) as p1, \
         patch.object(runner.timing_p4, "evaluate") as p4:
        run = _stop_run(f)
    p1.assert_called_once()
    p4.assert_not_called()
    assert run.stopped_at == "dasha"
    assert "not about this" in next(g for g in run.gates if g.status == "stopped").detail


def test_no_double_transit_stops_before_micro():
    f = make_facts()
    p1_w = _act(("2027-01-01", "2027-05-01"), value=W, double_transit=False)  # linked, no transit support
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())), \
         patch.object(runner.timing_p1, "evaluate", return_value=[p1_w]), \
         patch.object(runner.timing_p4, "evaluate") as p4:
        run = _stop_run(f)
    p4.assert_not_called()
    assert run.stopped_at == "transit"


def test_full_path_runs_all_pillars_and_narrows():
    f = make_facts()
    iv = ("2027-03-01", "2027-06-01")
    p1 = _act(iv)
    p1 = PillarResult("P1", S, p1.evidence, iv)
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())), \
         patch.object(runner.timing_p1, "evaluate", return_value=[p1]), \
         patch.object(runner.timing_p2, "evaluate", return_value=[_res(S, "P2", interval=iv)]), \
         patch.object(runner.timing_p3, "evaluate", return_value=[_res(S, "P3", interval=iv)]), \
         patch.object(runner.timing_p4, "evaluate",
                      return_value=[_res(S, "P4", interval=("2027-04-01", "2027-05-01"))]):
        run = _stop_run(f)
    assert run.stopped_at is None
    assert [g.name for g in run.gates] == ["promise", "varga", "dasha", "transit", "micro"]
    stages = [s for s, _ in run.narrowing]
    assert stages == ["antardasha", "double_transit", "ashtakavarga_kakshya"]
    assert run.result.n >= 3
    # narrowed window is the agreement of the evaluated methods, not the asked year
    assert run.result.interval is not None


def test_unreliable_varga_drops_the_check():
    f = make_facts()
    p1 = _act(("2027-03-01", "2027-06-01"))
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())) as pm, \
         patch.object(runner.timing_p1, "evaluate", return_value=[p1]), \
         patch.object(runner.timing_p2, "evaluate", return_value=[_res(S, "P2")]), \
         patch.object(runner.timing_p3, "evaluate", return_value=[_res(S, "P3")]), \
         patch.object(runner.timing_p4, "evaluate", return_value=[_res(S, "P4")]):
        run = runner.timing_run(f, BIRTH, cfg(V=["D1", "D9"]), date(2027, 1, 1), date(2027, 12, 31),
                                reliability={"D9": "cusp_sensitive"},
                                moon_check={"status": "stable"})
    used_cfg = pm.call_args[0][1]
    assert "D9" not in used_cfg.V                 # the varga check was dropped
    assert run.unreliable_vargas == ("D9",)
    assert any(g.name == "varga" and g.status == "skipped" for g in run.gates)


# ------------------------------------------------------------------ why + analysis shape

def test_why_summary_lists_gates_and_not_indicated():
    f = make_facts()
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())), \
         patch.object(runner.timing_p1, "evaluate",
                      return_value=[_res(W, interval=("2027-01-01", "2027-05-01"))]):
        run = _stop_run(f)
    why = why_summary(run, "relationship")
    assert "Why this reading:" in why
    assert "Stopped at the dasha check" in why
    assert "nothing notable indicated" in why


def test_analysis_keys_match_consumers():
    f = make_facts()
    with patch.object(runner, "promise_with_moon",
                      return_value=PromiseResult(PROMISE_STRONG, 4, (), (), ())), \
         patch.object(runner.timing_p1, "evaluate",
                      return_value=[_res(W, interval=("2027-01-01", "2027-05-01"))]):
        run = _stop_run(f)
    a = analysis_from_run(run, "relationship", date(2027, 1, 1), date(2027, 12, 31))
    for key in ("domain", "analysis_window", "convergence", "pillars", "evidence",
                "support_count", "conflict_count", "unavailable_count", "precision",
                "sensitivity", "classical", "gates", "confidence", "why",
                "not_indicated", "rule_ids"):
        assert key in a, key
    assert a["precision"]["timing_windows"] == []
    assert a["classical"]["promise"] in ("Strong", "Moderate", "Weak", "Unavailable")
    assert all(g["status"] in ("passed", "narrowed", "skipped", "stopped") for g in a["gates"])
    assert a["rule_ids"]  # every evidence row carries a frozen rule id


def test_confidence_penalizes_lookback_misses():
    base = _confidence((3, PromiseResult(PROMISE_STRONG, 4, (), (), ()), False, (), False, None))
    missed = _confidence((3, PromiseResult(PROMISE_STRONG, 4, (), (), ()), False, (), False,
                          {"checked": 2, "flagged": 0}))
    order = ["low", "limited", "moderate", "high"]
    assert order.index(missed) < order.index(base)


# ------------------------------------------------------------------ look-back + backtest

def test_lookback_flags_matching_past_events():
    f = make_facts()
    events = [{"year": 2018, "month": 6, "label": "job change"},
              {"year": 2021, "label": "marriage"}]
    p1 = _act(("2018-06-01", "2018-06-30"))
    with patch.object(runner.timing_p1, "evaluate", return_value=[p1]):
        lb = lookback_result(f, BIRTH, cfg(), events)
    assert lb["checked"] == 2 and lb["flagged"] == 2
    assert lb["events"][0]["year"] == 2018


def test_backtest_weights_and_track_record():
    class R:
        def __init__(self, domain, outcome, rid):
            self.domain, self.outcome = domain, outcome
            self.snapshot_json = json.dumps({"analysis": {"rule_ids": [rid], "intent": {"id": "I"}}})
    records = [R("career", "happened", "P1_A")] * 3 + [R("career", "did_not", "P1_A")] * 5
    w = backtest.rule_weights(records)
    assert w["P1_A"] < 1.0
    tr = backtest.track_record(records, "career", "I")
    assert tr["scored"] == 8 and tr["hits"] == 3
    assert backtest.track_record(records, "finance", None) is None


# ------------------------------------------------------------------ intent selection

def test_select_for_event_and_domain():
    assert select.for_event("marriage").intent_id == "MARRIAGE_TIMING"
    assert select.for_event("job_offer").intent_id == "JOB_TIMING"
    assert select.for_event("property_purchase").intent_id == "PROPERTY_PURCHASE"
    assert select.for_domain("relationship").number == 9
    assert select.for_domain("career", "will i get a promotion").number == 2
    assert select.for_domain("relocation", "settle abroad permanently").number == 32
    assert select.for_domain("nonsense") is None


def test_unsure_outcomes_never_count_as_misses():
    class R:
        def __init__(self, domain, outcome, rid):
            self.domain, self.outcome = domain, outcome
            self.snapshot_json = json.dumps({"analysis": {"rule_ids": [rid], "intent": {"id": "I"}}})
    records = [R("career", "happened", "P1_A")] * 3 + [R("career", "unsure", "P1_A")] * 5
    assert backtest.score_records(records)["P1_A"] == {"scored": 3, "hits": 3}
    tr = backtest.track_record(records, "career", "I")
    assert tr["scored"] == 3 and tr["hits"] == 3 and tr["misses"] == 0 and tr["unsure"] == 5


def test_vehicle_event_selects_vehicle_intent():
    from app.astro import prediction
    spec = prediction.event_spec("Will I buy a car next year?", "property")
    assert spec["event_type"] == "vehicle_purchase"
    assert select.for_event(spec["event_type"]).intent_id == "VEHICLE_PURCHASE"
    spec = prediction.event_spec("Will I buy a flat next year?", "property")
    assert spec["event_type"] == "property_purchase"


def _analysis_with_p3(evidence, value=W):
    from app.astro.convergence.runner import TimingRun
    from app.astro.convergence.types import WindowResult
    p3 = PillarResult("P3", value, evidence, ("2027-01-01", "2027-12-31"))
    wr = WindowResult(None, (p3,), 0, 1, (),
                      PromiseResult(PROMISE_STRONG, 4, (), (), ()),
                      WEAK_INDICATION, None, "badge", "disc")
    run = TimingRun(cfg(), wr, (), (), "high")
    return analysis_from_run(run, "relationship", date(2027, 1, 1), date(2027, 12, 31))


def test_confirmation_availability_tracks_the_actual_check():
    # P3 completed but its Sudarshana sub-check failed -> unavailable
    fail = Evidence("P3_RESULT", "1.0", (), 0, 0.0, frozenset(), None, "not evaluated",
                    ne_reason="Sudarshana unavailable (RuntimeError)")
    a = _analysis_with_p3((fail,))
    assert a["precision"]["sudarshana"] == "unavailable"
    ok = Evidence("P3_SUDARSHANA_TRIPLE", "1.0", (), 1, 1.0, frozenset(), None, "year sign active")
    a = _analysis_with_p3((ok,), value=W)
    assert a["precision"]["sudarshana"] == "evaluated"
    # yogini: no cross-check evidence at all -> unavailable
    a = _analysis_with_p3((ok,), value=W)
    assert a["precision"]["yogini"] == "unavailable"
    # a completed check that found no link still emits a marker -> evaluated
    yog = Evidence("P1_YOGINI_XCHECK", "1.0", (), 0, 0.0, frozenset(), None, "no link")
    a = _analysis_with_p3((ok, yog), value=W)
    assert a["precision"]["yogini"] == "evaluated"
