"""Gated timing pipeline: the single timing path (spec §1.3–1.4 + workflow rules).

Order, each step stopping the reading when it fails:
    0 promise   — natal promise (Lagna, and the house checked from the Moon chart)
    1 varga     — only divisional charts whose Lagna is stable inside the
                  stated birth-time uncertainty; unreliable vargas are dropped
                  and the confidence/window widened accordingly
    2 dasha     — an antardasha (or pratyantardasha) lord must link to the topic
    3 transit   — Jupiter AND Saturn must jointly reach the house or its lord
    4 micro     — Ashtakavarga/kakshya weeks inside the surviving months
P2 (Chara) and P3 (Tajika) always run: they are the independent methods whose
agreement produces the n/4 convergence badge.

The result keeps EVERY gate's status so the reply can say where it stopped
("the chart does not strongly promise this; here is why") instead of dressing
up a weak answer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Optional

from .. import constants as K
from .. import stability, transits
from . import dedup, links, natal as natal_mod, timing_p1, timing_p2, timing_p3, timing_p4
from .promise import promise_gate
from .types import (A, M, NE, S, W, INSUFFICIENT_DATA, MIXED_PERIOD, PROMISE_STRONG, PROMISE_MODERATE,
                    PROMISE_WEAK, SUPPORTIVE_PERIOD, WEAK_INDICATION, IntentConfig, PillarResult,
                    PromiseFactor, PromiseResult, WindowResult)

log = logging.getLogger(__name__)

R_MOON = "PROMISE_F7"
_RANK = {S: 4, M: 3, W: 2, A: 1, NE: 0}
PROMISE_LABEL = {PROMISE_STRONG: "Strong", PROMISE_MODERATE: "Moderate",
                 PROMISE_WEAK: "Weak", "NE": "Unavailable"}


# ------------------------------------------------------------------ result container

@dataclass(frozen=True)
class Gate:
    name: str            # promise | varga | dasha | transit | micro
    status: str          # passed | narrowed | skipped | stopped
    detail: str


@dataclass(frozen=True)
class TimingRun:
    cfg: IntentConfig
    result: WindowResult
    gates: tuple
    narrowing: tuple          # [(stage, interval)]
    confidence: str           # high | moderate | limited | low
    unreliable_vargas: tuple = ()
    timing_unstable: bool = False       # Moon pada flips inside the uncertainty
    lookback: Optional[dict] = None
    track_record: Optional[dict] = None

    @property
    def stopped_at(self) -> Optional[str]:
        stop = next((g for g in self.gates if g.status == "stopped"), None)
        return stop.name if stop else None


# ------------------------------------------------------------------ promise from the Moon chart

def _moon_house_factor(facts, cfg) -> PromiseFactor:
    """The E-house counted from the Moon must not carry only malefic influence."""
    h = cfg.primary_house
    if h is None:
        return PromiseFactor("F7_moon_house", 0, False, "intent has no event houses")
    sign = links.house_sign(facts, h, "moon")
    occ = [n for n, p in facts["planets"].items() if p["sign"] == sign]
    asp = [n for n in facts["planets"] if links.aspects_sign(n, facts, sign)]
    infl = set(occ) | set(asp)
    ben = bool(infl & {K.PLANET_NAMES[i] for i in K.NATURAL_BENEFICS})
    mal = bool(infl & {K.PLANET_NAMES[i] for i in K.NATURAL_MALEFICS})
    score = 1 if ben or not mal else -1
    note = f"house {h} counted from the Moon: influences {sorted(infl) or 'none'}"
    ev = ()
    if score:
        ev = (promise_ev(score, {f"MOON:HOUSE:{h}"}, note, [f"moon_chart.houses.{h}"]),)
    return PromiseFactor("F7_moon_house", score, True, note, ev)


def promise_ev(direction, factors, text, fids=()):
    from .types import Evidence
    from . import rulepack
    return Evidence(R_MOON, rulepack.version(R_MOON), tuple(fids), direction, 0.5,
                    frozenset(factors), None, text)


def promise_with_moon(facts, cfg) -> PromiseResult:
    """promise_gate plus the Moon-chart check as an eighth view of the same score."""
    res = promise_gate(facts, cfg)
    moon = _moon_house_factor(facts, cfg)
    factors = res.factors + (moon,)
    score = res.score + moon.score
    unavailable = res.unavailable + (() if moon.available else (moon.name,))
    if all(not f.available for f in factors):
        level = "NE"
    elif score >= 3:
        level = PROMISE_STRONG
    elif score >= 0:
        level = PROMISE_MODERATE
    else:
        level = PROMISE_WEAK
    return PromiseResult(level, score, factors, res.evidence + moon.evidence, unavailable)


# ------------------------------------------------------------------ reliability of the vargas

def varga_reliability(birth, vargas) -> dict:
    """{varga: 'stable'|'cusp_sensitive'|'unavailable'} for the configured vargas.

    A varga whose Lagna sign flips inside the stated birth-time uncertainty
    cannot carry a kendra/trikona confirmation — that check is dropped and the
    reading says so rather than pretending precision it does not have.
    """
    out = {}
    names = [v for v in vargas if v != "D1"]
    if not names:
        return out
    try:
        windows = stability.lagna_windows(birth, vargas=names)
    except Exception as exc:
        log.exception("varga reliability scan failed")
        return {v: "unavailable" for v in names}
    for v, w in windows.items():
        out[v] = w["status"]
    return out


def moon_stability(birth) -> Optional[dict]:
    """Moon nakshatra-pada stability — Vimshottari dates depend on it."""
    try:
        return stability.moon_pada_window(birth)
    except Exception:
        log.exception("moon pada stability scan failed")
        return None


# ------------------------------------------------------------------ helpers

def _start_key(p: PillarResult):
    if p.interval:
        try:
            return -timing_p1.to_date(p.interval[0]).toordinal()
        except Exception:
            return 0
    return 0


def _pick(results: list, pillar: str) -> PillarResult:
    """The strongest evaluated sub-window for the badge count; ties → earliest."""
    evals = [p for p in results if p.value != NE]
    if not evals:
        return results[0] if results else PillarResult.not_evaluated(pillar, "no results")
    return max(evals, key=lambda p: (_RANK[p.value], _start_key(p)))


def _activated(p: PillarResult) -> bool:
    return any(e.rule_id == "P1_ACTIVATION" and e.direction > 0 for e in p.evidence)


def _iv_str(a, b):
    a, b = timing_p1.to_date(a), timing_p1.to_date(b)
    return (a.isoformat(), b.isoformat())


def _union_dates(results) -> list:
    ivs = []
    for p in results:
        if p.interval:
            try:
                ivs.append((timing_p1.to_date(p.interval[0]), timing_p1.to_date(p.interval[1])))
            except Exception:
                continue
    return timing_p1.merge(ivs)


def aggregate_p4(results: list, window) -> PillarResult:
    """P4 verdict inside `window`: the best micro-window, or A when every trigger
    planet's BAV in range is <=2, else the range's own result."""
    inside = [p for p in results
              if p.value != NE and p.interval
              and timing_p1.intersect([p.interval], [window])]
    if not inside:
        return next((p for p in results if p.value != NE),
                    PillarResult.not_evaluated("P4", "no micro-timing evidence in range", window))
    best = max(inside, key=lambda p: (_RANK[p.value], _start_key(p)))
    return best


def _confidence(run_parts) -> str:
    n, promise, stopped, unreliable, timing_unstable, lookback = run_parts
    if stopped or n <= 0:
        return "low"
    score = n
    if promise and promise.level == PROMISE_STRONG:
        score += 1
    if unreliable:
        score -= 1
    if timing_unstable:
        score -= 1
    if lookback and lookback.get("checked") and lookback.get("flagged", 0) < lookback["checked"]:
        score -= 1
    return "high" if score >= 4 else "moderate" if score >= 3 else "limited" if score >= 2 else "low"


# ------------------------------------------------------------------ the gated timing run

def timing_run(facts, birth, cfg: IntentConfig, start, end, *, reliability=None,
               moon_check=None, rule_weights=None, lookback_events=None,
               include_p4=True) -> TimingRun:
    start, end = timing_p1.to_date(start), timing_p1.to_date(end)
    gates: list = []

    # Gate 0 — natal promise --------------------------------------------------
    if reliability is None:
        reliability = varga_reliability(birth, cfg.V)
    if moon_check is None:
        moon_check = moon_stability(birth)
    unreliable = tuple(v for v in cfg.V if v != "D1" and reliability.get(v) != "stable")
    cfg_eff = replace(cfg, V=tuple(v for v in cfg.V if v == "D1" or reliability.get(v) == "stable"))
    # when every divisional chart was dropped, the varga item must be NE —
    # otherwise P1 quietly confirms on D1 while the gate reports a dropped check
    divisionals_dropped = bool(unreliable) and not any(v != "D1" for v in cfg_eff.V)
    promise = promise_with_moon(facts, cfg_eff)
    timing_unstable = bool(moon_check and moon_check.get("status") == "cusp_sensitive")

    gate0 = Gate("promise", "passed" if promise.level in (PROMISE_STRONG, PROMISE_MODERATE)
                 else ("skipped" if promise.level == "NE" else "stopped"),
                 f"natal promise {promise.level} (score {promise.score})" +
                 (f"; unavailable factors: {', '.join(promise.unavailable)}" if promise.unavailable else ""))
    gates.append(gate0)

    if unreliable:
        gates.append(Gate("varga", "skipped",
                          f"{', '.join(unreliable)} Lagna changes inside the stated birth-time "
                          "uncertainty — those divisional checks were dropped"))
    elif cfg.primary_varga:
        gates.append(Gate("varga", "passed", f"{cfg.primary_varga} Lagna is stable at the stated time"))

    if timing_unstable:
        gates.append(Gate("dasha", "narrowed",
                          "the Moon's nakshatra pada changes inside the birth-time uncertainty, "
                          "so dasha boundaries can shift; the window is reported wider"))

    if promise.level == PROMISE_WEAK:
        wr = dedup.converge([], promise, cfg_eff, interval=_iv_str(start, end))
        return TimingRun(cfg, wr, tuple(gates), (), "low", unreliable, timing_unstable)

    # Gate 2 — dasha activation ------------------------------------------------
    p1s = timing_p1.evaluate(facts, birth, cfg_eff, start, end,
                             divisionals_dropped=divisionals_dropped)
    activated = [p for p in p1s if _activated(p)]
    if not activated:
        gates.append(Gate("dasha", "stopped",
                          "no dasha or antardasha lord in this span links to the topic houses — "
                          "the periods running then are not about this"))
        wr = dedup.converge([_pick(p1s, "P1")], promise, cfg_eff, interval=_iv_str(start, end))
        return TimingRun(cfg, wr, tuple(gates), (), "low", unreliable, timing_unstable)
    gates.append(Gate("dasha", "passed",
                      f"{len(activated)} antardasha(s) link a period lord to the topic"))

    # Gate 3 — double transit --------------------------------------------------
    # must hold in an ACTIVATED antardasha: a W pillar can carry transit
    # evidence with no dasha link, which would forecast outside every
    # period gate 2 accepted
    supported = [p for p in activated
                 if any(e.rule_id == "P1_DOUBLE_TRANSIT" and e.direction > 0
                        for e in p.evidence)]
    if not supported:
        gates.append(Gate("transit", "stopped",
                          "the dasha lords link to the topic, but Jupiter and Saturn do not jointly "
                          "reach the house or its lord in this span"))
        wr = dedup.converge([_pick(p1s, "P1")], promise, cfg_eff, interval=_iv_str(start, end))
        return TimingRun(cfg, wr, tuple(gates), (), "limited", unreliable, timing_unstable)
    p1_ivs = _union_dates(supported)
    gates.append(Gate("transit", "passed",
                      "Jupiter and Saturn jointly reach the topic in " +
                      "; ".join(f"{a.isoformat()} to {b.isoformat()}" for a, b in p1_ivs[:3])))

    # Gates in sequence produce the narrowing stages --------------------------
    act_h = timing_p1.hull_iso(_union_dates(activated)) or (start, end)
    narrowing = [("antardasha", _iv_str(*act_h)),
                 ("double_transit", _iv_str(*timing_p1.hull_iso(p1_ivs)))]

    # Gate 4 — micro-timing inside the surviving months ------------------------
    m_start = min(a for a, _ in p1_ivs)
    m_end = max(b for _, b in p1_ivs)
    p4s = timing_p4.evaluate(facts, birth, cfg_eff, m_start, m_end) if include_p4 else []
    micro = [p for p in p4s if p.value in (S, W) and p.interval]
    if micro:
        micro_ivs = timing_p1.intersect(_union_dates(micro), p1_ivs)
        gates.append(Gate("micro", "passed" if micro_ivs else "narrowed",
                          f"{len(micro)} supportive micro-window(s) inside the months"))
        if micro_ivs:
            narrowing.append(("ashtakavarga_kakshya", _iv_str(*timing_p1.hull_iso(micro_ivs))))
    elif include_p4:
        gates.append(Gate("micro", "skipped", "no trigger-planet micro-window inside the months"))
    else:
        gates.append(Gate("micro", "skipped", "micro-timing not evaluated in this run"))

    # Independent methods for the n/4 ------------------------------------------
    p2s = timing_p2.evaluate(facts, birth, cfg_eff, start, end)
    p3s = timing_p3.evaluate(facts, birth, cfg_eff, start, end)
    p4_pick = (aggregate_p4(p4s, _iv_str(m_start, m_end)) if include_p4
               else PillarResult.not_evaluated("P4", "micro-timing not evaluated", _iv_str(m_start, m_end)))
    chosen = [_pick(p1s, "P1"), _pick(p2s, "P2"), _pick(p3s, "P3"), p4_pick]
    if rule_weights:
        chosen = [_reweight(p, rule_weights) for p in chosen]
    wr = dedup.converge(chosen, promise, cfg_eff, interval=_iv_str(start, end))
    lookback = lookback_result(facts, birth, cfg_eff, lookback_events) if lookback_events else None
    conf = _confidence((wr.n, promise, False, unreliable, timing_unstable, lookback))
    return TimingRun(cfg, wr, tuple(gates), tuple(narrowing), conf, unreliable, timing_unstable, lookback)


def _reweight(p: PillarResult, weights: dict) -> PillarResult:
    """Scale evidence weight by the measured track record of each rule; a pillar
    whose support rests only on down-weighted rules demotes S/M -> W."""
    evs, sup_w = [], 0.0
    for e in p.evidence:
        w = weights.get(e.rule_id, 1.0)
        evs.append(replace(e, weight=round(e.weight * w, 4)))
        if e.direction > 0:
            sup_w += e.weight * w
    value = W if (p.value in (S, M) and sup_w and sup_w < 0.75) else p.value
    return replace(p, value=value, evidence=tuple(evs))


# ------------------------------------------------------------------ look-back on past events

def lookback_result(facts, birth, cfg: IntentConfig, events) -> dict:
    """Run the dasha gate on reported past events of the same topic.

    events: [{"year": int, "month": int|None, "label": str}]
    A method that would not have flagged the client's own past earns less
    confidence on the future window.
    """
    checked, flagged, detail = 0, 0, []
    for ev in events[:5]:
        year = ev.get("year")
        if not year:
            continue
        month = ev.get("month")
        try:
            if month:
                start = date(int(year), max(1, min(12, int(month))), 1)
                end = (date(start.year + start.month // 12, start.month % 12 + 1, 1)
                       - timedelta(days=1))
            else:
                start, end = date(int(year), 1, 1), date(int(year), 12, 31)
        except (TypeError, ValueError):
            continue
        p1s = timing_p1.evaluate(facts, birth, cfg, start, end)
        hit = any(_activated(p) and p.value in (S, M, W) for p in p1s)
        checked += 1
        flagged += int(hit)
        detail.append({"label": ev.get("label") or "reported event", "year": year,
                       "verdict": "flagged" if hit else "not flagged"})
    return {"checked": checked, "flagged": flagged, "events": detail}


# ------------------------------------------------------------------ natal template

def natal_run(facts, birth, cfg: IntentConfig, *, reliability=None) -> TimingRun:
    """Template N (and N+T's natal half)."""
    if reliability is None:
        reliability = varga_reliability(birth, cfg.V)
    unreliable = tuple(v for v in cfg.V if v != "D1" and reliability.get(v) != "stable")
    cfg_eff = replace(cfg, V=tuple(v for v in cfg.V if v == "D1" or reliability.get(v) == "stable"))
    wr = natal_mod.template_N(facts, cfg_eff)
    gates = [Gate("promise", "passed" if wr.promise is None or wr.promise.level != PROMISE_WEAK else "stopped",
                  "natal agreement computed")]
    if unreliable:
        gates.append(Gate("varga", "skipped",
                          f"{', '.join(unreliable)} Lagna changes inside the stated birth-time "
                          "uncertainty — those divisional checks were dropped"))
    return TimingRun(cfg, wr, tuple(gates), (),
                     "moderate" if not unreliable else "limited", unreliable)


# ------------------------------------------------------------------ uniform "why" summary

_PILLAR_NAMES = {"P1": "Parashari (Vimshottari)", "P2": "Jaimini (Chara dasha)",
                 "P3": "Tajika (annual chart)", "P4": "Micro-timing (Ashtakavarga)",
                 "M1": "D1 chart", "M2": "Divisional chart", "M3": "Jaimini", "M4": "Strength"}

_VALUE_WORDS = {S: "supports", M: "mixed", W: "weak", A: "conflicts", NE: "not evaluated"}

_STAGE_NAMES = {"antardasha": "antardasha link", "double_transit": "Jupiter+Saturn transit",
                "ashtakavarga_kakshya": "Ashtakavarga/kakshya"}


def why_summary(run: TimingRun, domain: str) -> str:
    """One plain-language evidence summary, the same shape every time."""
    wr = run.result
    lines = ["Why this reading:"]
    if wr.promise is not None:
        top = [f for f in wr.promise.factors if f.score]
        bits = "; ".join(f.note for f in top[:2]) if top else "no factor decisive"
        lines.append(f"Promise: {wr.promise.level} ({bits}).")
    methods = [f"{_PILLAR_NAMES.get(p.pillar, p.pillar)} {_VALUE_WORDS[p.value]}"
               + (f" ({p.ne_reason})" if p.value == NE and p.ne_reason else "")
               for p in wr.pillars]
    lines.append("Methods: " + "; ".join(methods) + ".")
    conflicting = any(e.direction < 0 for p in wr.pillars for e in p.evidence)
    confirmation = ("Hidden friction" if any(p.value == A for p in wr.pillars)
                    else "Both confirmation methods support" if wr.n >= 2 and not conflicting
                    else "Mixed indications" if conflicting else "Mostly aligned")
    lines.append(f"Confirmation: {confirmation}.")
    sup = [e.text for e in wr.supportive_evidence[:3] if e.text]
    con = [e.text for e in wr.conflicting_evidence[:3] if e.text]
    if sup:
        lines.append("Supporting: " + "; ".join(sup) + ".")
    if con:
        lines.append("Conflicting: " + "; ".join(con) + ".")
    if wr.result_type in (WEAK_INDICATION, INSUFFICIENT_DATA):
        lines.append(f"Overall: nothing notable indicated for {domain} in this period.")
    elif wr.interval:
        stage = run.narrowing[-1][0] if run.narrowing else "window"
        lines.append(f"Narrowed window ({_STAGE_NAMES.get(stage, stage)}): "
                     f"{wr.interval[0]} to {wr.interval[1]}.")
    stop = next((g for g in run.gates if g.status == "stopped"), None)
    if stop:
        lines.append(f"Stopped at the {stop.name} check: {stop.detail}.")
    if run.lookback and run.lookback.get("checked"):
        lb = run.lookback
        lines.append(f"Look-back: this method flagged {lb['flagged']} of {lb['checked']} "
                     "of your reported past events in this area.")
    return "\n".join(lines)


# ------------------------------------------------------------------ analysis mapping

def analysis_from_run(run: TimingRun, domain: str, start, end, *, calibrated=True,
                      intent=None, lookback_events=None) -> dict:
    """Produce the `analysis` dict the chat layer, decision protocol and saver read."""
    wr = run.result
    start_s, end_s = start if isinstance(start, str) else start.isoformat(), \
                     end if isinstance(end, str) else end.isoformat()
    pillar_labels = {p.pillar: p.label for p in wr.pillars}
    support = sum(p.value == S for p in wr.pillars)
    conflict = sum(p.value == A for p in wr.pillars)
    ne = len(wr.ne_pillars)

    offers_window = wr.result_type in (SUPPORTIVE_PERIOD, MIXED_PERIOD)
    # the published window is the converged intersection (every strong method
    # agrees), tightened by the last narrowing stage — never a gap-spanning hull
    ivs = []
    if wr.interval and offers_window:
        ivs = [wr.interval]
        if run.narrowing and wr.result_type == SUPPORTIVE_PERIOD:
            ivs = timing_p1.intersect(ivs, [run.narrowing[-1][1]])
    timing_windows = [{"start": timing_p1.iso(timing_p1.to_date(a)),
                       "end": timing_p1.iso(timing_p1.to_date(b))} for a, b in ivs]
    yogini_ev = any(e.rule_id == "P1_YOGINI_XCHECK" for p in wr.pillars for e in p.evidence)
    p3 = next((p for p in wr.pillars if p.pillar == "P3"), None)
    sud = "evaluated" if p3 and p3.value != NE else "unavailable"
    conflicting = any(e.direction < 0 for p in wr.pillars for e in p.evidence)
    confirmation = ("Hidden friction" if any(p.value == A for p in wr.pillars)
                    else "Both confirmation methods support" if wr.n >= 2 and not conflicting
                    else "Mixed indications" if conflicting else "Mostly aligned")
    magnitude = ("significant" if (wr.promise and wr.promise.level == PROMISE_STRONG and wr.n >= 3)
                 else "moderate" if wr.n >= 2 else "modest")
    gates = [{"gate": g.name, "status": g.status, "detail": g.detail} for g in run.gates]
    rule_ids = sorted({e.rule_id for p in wr.pillars for e in p.evidence})
    evidence = [{"id": e.rule_id, "module": p.pillar, "direction": {1: "supportive", -1: "conflicting", 0: "neutral"}[e.direction],
                 "details": [e.text], "rule_id": e.rule_id, "rule_version": e.rule_version,
                 "weight": e.weight,
                 "depends_on_factors": sorted(e.factors),
                 "uncertainty_flags": [e.ne_reason] if e.ne_reason else []}
                for p in wr.pillars for e in p.evidence]
    analysis = {
        "domain": domain,
        "analysis_window": {"start": start_s, "end": end_s},
        "convergence": wr.badge,
        "convergence_disclaimer": wr.disclaimer,
        "result_type": wr.result_type,
        "pillars": pillar_labels,
        "evidence": evidence,
        "rule_ids": rule_ids,
        "support_count": support,
        "conflict_count": conflict,
        "unavailable_count": ne,
        "calculation_evidence_ids": [f"{e.rule_id}: {e.text}" for p in wr.pillars for e in p.evidence if e.text][:15],
        "gates": gates,
        "confidence": run.confidence,
        "narrowing": [{"stage": s, "start": timing_p1.iso(timing_p1.to_date(iv[0])),
                       "end": timing_p1.iso(timing_p1.to_date(iv[1]))} for s, iv in run.narrowing],
        "not_indicated": wr.result_type in (WEAK_INDICATION, INSUFFICIENT_DATA),
        "reliability": {"unreliable_vargas": list(run.unreliable_vargas),
                        "timing_unstable": run.timing_unstable},
        "lookback": run.lookback,
        "track_record": run.track_record,
        "why": why_summary(run, domain),
        "precision": {
            "calibrated": calibrated,
            "confirmation": confirmation,
            "yogini": "evaluated" if yogini_ev else "unavailable",
            "sudarshana": sud,
            "timing_windows": timing_windows,
            "excluded_windows": [],
            "magnitude": magnitude,
            "ithasala": None,
            "eclipse_watch_months": [],
            "layer_verdicts": {
                "core_pillars": wr.badge,
                "pillars": pillar_labels,
                "yogini": "evaluated" if yogini_ev else "unavailable",
                "sudarshana": sud,
                "confirmation": confirmation,
                "kakshya_timing": "applied" if any(p.pillar == "P4" and p.value != NE
                                                 for p in wr.pillars) else "unavailable",
                "magnitude": magnitude,
                "ithasala": "unavailable",
                "eclipse": "unavailable",
            },
        },
        "sensitivity": {
            "verdict_stable": not run.unreliable_vargas,
            "timing_stable": not run.timing_unstable,
        },
        "classical": {
            "promise": PROMISE_LABEL.get(wr.promise.level if wr.promise else "NE", "Unavailable"),
            "scores": [{"complete": wr.k_evaluated >= 2, "count": wr.n}],
            "tables": [{"title": "Gate report", "columns": ["Gate", "Result", "Detail"],
                        "rows": [[g["gate"], g["status"], g["detail"]] for g in gates]}],
            "timing_sensitive": run.timing_unstable or bool(run.unreliable_vargas),
        },
    }
    if intent:
        analysis["intent"] = intent
    return analysis
