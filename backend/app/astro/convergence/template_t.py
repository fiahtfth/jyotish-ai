"""Template T (timing), spec 1.4: P1..P4 per window -> de-duplicated convergence.

    template_T(facts, birth, cfg, start, end) -> TimingOutput

The range is split at every P1 (AD and double-transit window), P2 (Chara AD sign) and P3
(solar-return year) boundary (rule T_SEGMENTATION). Each elementary segment gets exactly one
P1/P2/P3 result plus the P4 micro-windows inside it (rule T_P4_AGGREGATE) and is converged
once with dedup.converge (factor de-dup, n, result type, narrowing P1->P4). Adjacent segments
with an identical outcome are merged. KP is attached per window and never adds to n.

Mode B (birth time unknown): P1 runs from the Moon frame only, P2/P3/P4 and KP are NE, the
promise gate is not run (it is Lagna-based), so results are at most `insufficient_data`.
Results are cached per (birth fingerprint, intent config, range, pillars, rule-pack hash).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import Optional, Sequence

from ..engine import birth_fingerprint
from . import _ivl, dedup, natal, rulepack
from . import intents as intents_mod
from . import kp as kp_mod
from . import timing_p1, timing_p2, timing_p3, timing_p4
from ._facts import unknown_time
from .promise import promise_gate
from .types import (A, NE, PILLAR_NAMES, S, SUPPORTIVE_PERIOD, W, Evidence, IntentConfig, PillarResult,
                    WindowResult)

log = logging.getLogger(__name__)
R_SEG, R_P4AGG, R_ADVERSE = "T_SEGMENTATION", "T_P4_AGGREGATE", "T_ADVERSE_FRAMING"
MAX_RANGE_DAYS = 366 * 5
PRESSURE_LABELS = {"supportive_period": "elevated_pressure_period", "mixed_period": "mixed_pressure_period",
                   "weak_indication": "weak_indication", "insufficient_data": "insufficient_data"}
_EVALUATORS = {"P1": timing_p1.evaluate, "P2": timing_p2.evaluate, "P3": timing_p3.evaluate,
               "P4": timing_p4.evaluate}
_CACHE: "OrderedDict[tuple, TimingOutput]" = OrderedDict()
_CACHE_MAX = 256
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class TimingWindow:
    segment: tuple                    # (date, date) elementary span this outcome holds for
    result: WindowResult              # converged result; result.interval is the narrowed window
    display_type: str                 # result_type, or the pressure wording for T_adverse intents


@dataclass(frozen=True)
class TimingOutput:
    intent_id: str
    template: str
    framing: str                      # "event" | "pressure"
    range: tuple
    promise: object
    windows: tuple
    pillars_run: tuple
    notes: tuple = ()
    rulepack_hash: str = ""
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def supportive(self) -> tuple:
        return tuple(w for w in self.windows if w.result.result_type == SUPPORTIVE_PERIOD)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _cfg_key(cfg: IntentConfig) -> str:
    raw = json.dumps(asdict(cfg), sort_keys=True, default=lambda x: sorted(x) if isinstance(x, (set, frozenset))
                     else list(x) if isinstance(x, tuple) else str(x))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_key(facts, birth, cfg, start, end, pillars, with_kp):
    try:
        fp = birth_fingerprint(birth)
    except Exception:            # synthetic births (tests) are not cached
        return None
    return (fp, (facts.get("meta") or {}).get("birth_time_precision"), _cfg_key(cfg), start, end,
            tuple(pillars), bool(with_kp), rulepack.pack_hash())


# ------------------------------------------------------------------ helpers
def _norm(p: PillarResult, rng: tuple) -> PillarResult:
    iv = _ivl.norm(p.interval) if p.interval is not None else None
    iv = _ivl.overlap(iv, rng) if iv else None
    return replace(p, interval=iv)


def _run(name, facts, birth, cfg, start, end) -> list:
    try:
        return list(_EVALUATORS[name](facts, birth, cfg, start, end))
    except Exception as exc:             # a pillar failure is NE, never a fabricated value
        log.exception("%s failed for %s", name, cfg.intent_id)
        return [PillarResult.not_evaluated(name, f"{name} unavailable: {type(exc).__name__}: {exc}")]


def _ne_cover(results, name, rng) -> Optional[list]:
    """If the pillar produced only NE results, one NE piece covering the whole range."""
    if results and all(r.value == NE for r in results):
        reasons = "; ".join(dict.fromkeys(r.ne_reason or "not evaluated" for r in results))
        return [PillarResult.not_evaluated(name, reasons, rng)]
    return None


def _p1_pieces(facts, birth, cfg, results, rng) -> list:
    """P1 coverage: AD intervals; an S AD narrowed to its PD ∩ double-transit hull is split so the
    rest of that AD carries W (activation without the double transit)."""
    cover = _ne_cover(results, "P1", rng)
    if cover:
        return cover
    rows = timing_p1.ad_rows(facts, rng[0], rng[1])
    if len(rows) != len(results):
        return [_norm(r, rng) for r in results if r.interval]
    out = []
    for row, r in zip(rows, results):
        ad = timing_p1.ad_interval(row, rng[0], rng[1])
        r = _norm(r, rng)
        iv = r.interval or ad
        if r.value != S or iv == ad:
            out.append(replace(r, interval=ad if r.value != S else iv))
            continue
        out.append(r)
        outside = [p for p in ((ad[0], _ivl.day_before(iv[0])), (iv[1] + timedelta(days=1), ad[1])) if p[0] <= p[1]]
        keep = tuple(e for e in r.evidence if not (e.rule_id == "P1_DOUBLE_TRANSIT" and e.direction > 0))
        note = Evidence("P1_RESULT", rulepack.version("P1_RESULT"), (), 0, 0.0, frozenset(), None,
                        "outside the PD/double-transit window of this AD: activation without double transit -> W")
        for p in outside:
            out.append(PillarResult("P1", W, keep + (note,), p))
    return out


def _pieces(results, name, rng) -> list:
    cover = _ne_cover(results, name, rng)
    if cover:
        return cover
    return [x for x in (_norm(r, rng) for r in results) if x.interval]


def _covering(pieces, day: date, name: str, rng) -> PillarResult:
    for p in pieces:
        if p.interval and p.interval[0] <= day <= p.interval[1]:
            return p
    return PillarResult.not_evaluated(name, "no result covers this span", None)


def aggregate_p4(results: Sequence[PillarResult], seg: tuple) -> PillarResult:
    """T_P4_AGGREGATE: S if any micro-window in `seg` is S (interval = hull of those parts);
    A only if every trigger result in `seg` is A; otherwise W. All-NE -> NE."""
    ev = [r for r in results if r.value != NE]
    if not ev:
        reasons = "; ".join(dict.fromkeys(r.ne_reason or "not evaluated" for r in results)) or "not evaluated"
        return PillarResult.not_evaluated("P4", reasons, seg)
    inside = [(r, _ivl.overlap(_ivl.norm(r.interval), seg)) for r in ev if r.interval]
    inside = [(r, iv) for r, iv in inside if iv]
    v = rulepack.version(R_P4AGG)
    if not inside:
        return PillarResult("P4", W, (Evidence(R_P4AGG, v, (), 0, 0.0, frozenset(), seg,
                                               "no trigger-planet transit inside this span"),), seg)
    s_parts = [(r, iv) for r, iv in inside if r.value == S]
    if s_parts:
        evs = tuple(e for r, _ in s_parts for e in r.evidence)
        return PillarResult("P4", S, evs, _ivl.hull([iv for _, iv in s_parts]))
    if all(r.value == A for r, _ in inside):
        return PillarResult("P4", A, tuple(e for r, _ in inside for e in r.evidence), seg)
    return PillarResult("P4", W, tuple(e for r, _ in inside for e in r.evidence), seg)


def _signature(w: WindowResult) -> tuple:
    return (w.result_type, w.n, w.k_evaluated, tuple((p.pillar, p.value, p.dependent) for p in w.pillars),
            w.kp.value if w.kp else None)


def _merge(a: TimingWindow, b: TimingWindow) -> TimingWindow:
    ra, rb = a.result, b.result
    seen = set()

    def uniq(xs):
        out = []
        for e in xs:
            k = (e.rule_id, e.text, e.interval)
            if k not in seen:
                seen.add(k)
                out.append(e)
        return tuple(out)

    merged = replace(ra, interval=_ivl.hull([ra.interval, rb.interval]),
                     supportive_evidence=uniq(ra.supportive_evidence + rb.supportive_evidence),
                     conflicting_evidence=(seen.clear() or uniq(ra.conflicting_evidence + rb.conflicting_evidence)),
                     notes=tuple(dict.fromkeys(ra.notes + rb.notes)))
    return TimingWindow((a.segment[0], b.segment[1]), merged, a.display_type)


# ------------------------------------------------------------------ main
def template_T(facts: dict, birth, cfg: IntentConfig, start, end, *, pillars: Sequence[str] = PILLAR_NAMES,
               with_kp: bool = True, use_cache: bool = True) -> TimingOutput:
    """Run P1..P4 over [start, end] (inclusive dates) and converge per window.

    `pillars` restricts which pillars run (the rest are NE "not run"), e.g. for the specificity gate."""
    start, end = _ivl.to_date(start), _ivl.to_date(end)
    if end < start:
        raise ValueError("end must not precede start")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError(f"range longer than {MAX_RANGE_DAYS} days")
    if not cfg.is_timing:
        raise ValueError(f"{cfg.intent_id} is not a timing intent (template {cfg.template})")
    key = _cache_key(facts, birth, cfg, start, end, pillars, with_kp) if use_cache else None
    if key is not None:
        with _CACHE_LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
    out = _template_T(facts, birth, cfg, start, end, tuple(pillars), with_kp)
    if key is not None:
        with _CACHE_LOCK:
            _CACHE[key] = out
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return out


def _template_T(facts, birth, cfg, start, end, pillars, with_kp) -> TimingOutput:
    rng = (start, end)
    adverse = cfg.template == "T_adverse"
    mode_b = unknown_time(facts, birth)
    notes = []
    if adverse:
        notes.append("adverse template: windows mark periods of elevated change/pressure, phrased as "
                     "preparation -- never a certain outcome")
    promise = None
    if mode_b:
        notes.append("birth time unknown: Lagna-dependent pillars (P2, P3, P4) and KP are not evaluated; "
                     "P1 uses the Moon frame only; the natal promise gate is not run")
    elif not adverse:
        promise = promise_gate(facts, cfg)
    raw = {}
    for name in PILLAR_NAMES:
        raw[name] = _run(name, facts, birth, cfg, start, end) if name in pillars else \
            [PillarResult.not_evaluated(name, "not run in this evaluation")]
    p1 = _p1_pieces(facts, birth, cfg, raw["P1"], rng)
    p2 = _pieces(raw["P2"], "P2", rng)
    p3 = _pieces(raw["P3"], "P3", rng)
    bounds = {start, end + timedelta(days=1)}
    for p in p1 + p2 + p3:
        if p.interval:
            bounds.add(max(start, p.interval[0]))
            bounds.add(min(end, p.interval[1]) + timedelta(days=1))
    bounds = sorted(b for b in bounds if start <= b <= end + timedelta(days=1))
    windows = []
    for lo, nxt in zip(bounds, bounds[1:]):
        seg = (lo, _ivl.day_before(nxt))
        chosen = []
        for name, pieces in (("P1", p1), ("P2", p2), ("P3", p3)):
            c = _covering(pieces, lo, name, rng)
            chosen.append(replace(c, interval=_ivl.overlap(c.interval, seg) if c.interval else seg))
        chosen.append(aggregate_p4(raw["P4"], seg))
        kp_pillar = None
        if with_kp:
            mid = seg[0] + (seg[1] - seg[0]) / 2
            kp_pillar = kp_mod.kp_report(facts, birth, cfg, when=mid)["pillar"]
        res = dedup.converge(chosen, promise, cfg, kp=kp_pillar, interval=seg)
        if adverse:
            res = replace(res, notes=res.notes + (f"{R_ADVERSE}: pressure framing; requires n >= "
                                                   f"{cfg.min_n_for_label} for 'elevated'",))
        disp = PRESSURE_LABELS[res.result_type] if adverse else res.result_type
        tw = TimingWindow(seg, res, disp)
        if windows and _signature(windows[-1].result) == _signature(res):
            windows[-1] = _merge(windows[-1], tw)
        else:
            windows.append(tw)
    return TimingOutput(cfg.intent_id, cfg.template, "pressure" if adverse else "event", rng, promise,
                        tuple(windows), tuple(pillars), tuple(notes), rulepack.pack_hash(), raw)


# ------------------------------------------------------------------ natal overlay / dispatcher
def p1_overlay_now(facts: dict, cfg: IntentConfig, birth, today=None) -> PillarResult:
    """'Is this theme active now?' = P1 for the running MD/AD/PD (spec 1.5). Never counted in n."""
    today = _ivl.to_date(today) if today else date.today()
    if not (cfg.E or cfg.E_adverse_explicit):
        return PillarResult.not_evaluated("P1", "intent has no event houses")
    res = _run("P1", facts, birth, cfg, today, today)
    return res[0] if res else PillarResult.not_evaluated("P1", "no running antardasha")


def run_intent(facts: dict, birth, intent, start=None, end=None, today=None, **kw) -> dict:
    """Dispatch by template: T/T_adverse -> template_T; N -> template_N (+ optional P1 overlay);
    N+T -> both; special -> hooks.special.dispatch. Returns {"template", "timing"?, "natal"?, "special"?}."""
    cfg = intent if isinstance(intent, IntentConfig) else intents_mod.get(intent)
    if cfg is None:
        raise KeyError(f"unknown intent {intent!r}")
    today = _ivl.to_date(today) if today else date.today()
    start = _ivl.to_date(start) if start else today
    end = _ivl.to_date(end) if end else start + timedelta(days=364)
    out = {"intent_id": cfg.intent_id, "template": cfg.template}
    if cfg.template == "special":
        from .hooks import special
        out["special"] = special.dispatch(cfg, facts, birth, start=start, end=end, today=today, **kw)
        return out
    if cfg.template in ("N", "N+T"):
        overlay = (lambda f, c: p1_overlay_now(f, c, birth, today)) if "p1_overlay" in cfg.hooks else None
        out["natal"] = natal.template_N(facts, cfg, p1_overlay=overlay)
    if cfg.template in ("T", "T_adverse", "N+T"):
        out["timing"] = template_T(facts, birth, cfg, start, end, **kw)
    return out
