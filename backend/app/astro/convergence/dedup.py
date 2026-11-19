"""Factor de-duplication (spec 1.2) and window convergence (spec 1.4)."""
from __future__ import annotations

from dataclasses import replace
from typing import Optional, Sequence

from ..pillars import CONVERGENCE_DISCLAIMER
from .types import (A, M, NE, S, W, INSUFFICIENT_DATA, MIXED_PERIOD, PILLAR_NAMES, PROMISE_WEAK,
                    SUPPORTIVE_PERIOD, WEAK_INDICATION, IntentConfig, PillarResult, PromiseResult,
                    WindowResult)

RULE_DEDUP = "DEDUP_FACTORS"
RULE_RESULT = "RESULT_TYPE"
RULE_NARROW = "WINDOW_NARROWING"
KP_NOT_EVALUATED = "not evaluated"


def dedup_pillars(ordered: Sequence[PillarResult]) -> tuple:
    """Apply factor de-duplication in priority order.

    Returns (updated_results, n, dependent_names). A pillar counts only if at least
    one SUPPORTIVE evidence item uses a factor not already counted by a higher-priority
    counted pillar; otherwise it stays S but is flagged dependent and adds nothing to n.
    """
    counted: dict = {}           # factor -> pillar that first counted it
    out, n, dependent = [], 0, []
    for p in ordered:
        if p.value != S:
            out.append(p)
            continue
        sup = [e for e in p.evidence if e.direction > 0]
        new = any(f not in counted for e in sup for f in e.factors)
        if new:
            n += 1
            for e in sup:
                for f in e.factors:
                    counted.setdefault(f, p.pillar)
            out.append(replace(p, dependent=False, dependent_on=()))
        else:
            shared = sorted({counted[f] for e in sup for f in e.factors if f in counted})
            dependent.append(p.pillar)
            out.append(replace(p, dependent=True, dependent_on=tuple(shared)))
    return tuple(out), n, tuple(dependent)


def _intersect(a: Optional[tuple], b: Optional[tuple]) -> Optional[tuple]:
    if a is None or b is None:
        return None
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


def narrow_window(pillars: Sequence[PillarResult], default: Optional[tuple] = None) -> tuple:
    """P1 -> P2 -> P3 -> P4 intersection. Returns (interval, notes). A non-overlapping
    pillar window is not forced: the broader window is kept and the pillar reported in notes."""
    notes = []
    ev = [p for p in pillars if p.value != NE and p.interval is not None]
    if not ev:
        return default, notes
    cur = ev[0].interval
    for p in ev[1:]:
        if p.value != S:
            continue
        nxt = _intersect(cur, p.interval)
        if nxt is None:
            notes.append(f"{p.pillar} window does not overlap the {ev[0].pillar} window; shown separately")
        else:
            cur = nxt
    return cur, notes


def badge_text(prefix: str, n: int, k: int, total: int = 4) -> str:
    text = f"{prefix}: {n}/{total}"
    if k < total:
        text += f" ({k} of {total} methods evaluated)"
    return text


def _classify(n, k, promise, pillars, min_n):
    if k <= 1:
        return INSUFFICIENT_DATA
    if promise is not None and promise.level == PROMISE_WEAK:
        return WEAK_INDICATION
    has_a = any(p.value == A for p in pillars)
    has_am = any(p.value in (A, M) for p in pillars)
    if n >= min_n and not has_a:
        return SUPPORTIVE_PERIOD
    if n >= 2 and has_am:
        return MIXED_PERIOD
    return WEAK_INDICATION


def converge(pillars: Sequence[PillarResult], promise: Optional[PromiseResult], cfg: IntentConfig,
             kp: Optional[PillarResult] = None, interval: Optional[tuple] = None) -> WindowResult:
    """Combine P1..P4 into a WindowResult. Missing pillars are NE; KP never adds to n."""
    by = {p.pillar: p for p in pillars}
    ordered = [by.get(name) or PillarResult.not_evaluated(name, "module not provided") for name in PILLAR_NAMES]
    deduped, n, dependent = dedup_pillars(ordered)
    k = sum(p.value != NE for p in deduped)
    result_type = _classify(n, k, promise, deduped, cfg.min_n_for_label)
    win, notes = narrow_window(deduped, interval)
    notes = list(notes)
    for p in deduped:
        if p.dependent:
            notes.append(f"{p.pillar}: {p.label}")
    if promise is not None and promise.level == PROMISE_WEAK:
        notes.append("natal promise WEAK: result capped at weak_indication")
    evid = [e for p in deduped for e in p.evidence]
    kp = kp or PillarResult.not_evaluated("KP", "KP not verified; reported separately")
    return WindowResult(
        interval=win, pillars=deduped, n=n, k_evaluated=k, dependent=dependent, promise=promise,
        result_type=result_type, kp=kp, badge=badge_text("Traditional convergence", n, k),
        disclaimer=CONVERGENCE_DISCLAIMER, notes=tuple(notes),
        supportive_evidence=tuple(e for e in evid if e.direction > 0),
        conflicting_evidence=tuple(e for e in evid if e.direction < 0),
        ne_pillars=tuple(p.pillar for p in deduped if p.value == NE))


def kp_label(kp: Optional[PillarResult]) -> str:
    if kp is None or kp.value == NE:
        return "KP: not evaluated"
    return "KP: supportive" if kp.value == S else "KP: not supportive"
