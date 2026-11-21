"""Backtest weighting: score rules and topics against recorded outcomes.

Each PredictionRecord's snapshot stores the rule ids that produced the
reading. Once a user reports an outcome, every rule that voted for a
confirmed forecast earns credit; rules that keep missing get down-weighted.
Weights stay inside a band so a handful of outcomes cannot flip a verdict —
they temper evidence strength and confidence, they never invent support.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Optional

MIN_SCORED = 4            # fewer outcomes than this: weight stays 1.0
W_MIN, W_MAX = 0.5, 1.5   # tempering band

HIT = {"happened", "partly"}
# "unsure" carries no failure signal — scoring it as a miss would weight every
# rule down on pure uncertainty. "outside_window" is a confirmed timing miss:
# the event happened, just not when the rules said, so it scores against them.
SCORED_OUTCOMES = HIT | {"did_not", "outside_window"}


def _snapshot_rules(rec) -> list:
    try:
        snap = json.loads(rec.snapshot_json or "{}")
    except (TypeError, ValueError):
        return []
    return ((snap.get("analysis") or {}).get("rule_ids")
            or [f.get("rule_id") for f in (snap.get("analysis") or {}).get("evidence", [])
                if f.get("rule_id")])


def score_records(records) -> dict:
    """{rule_id: {"scored": n, "hits": n}} over records that have an outcome."""
    scored, hits = Counter(), Counter()
    for rec in records:
        if rec.outcome not in SCORED_OUTCOMES:
            continue
        rules = set(_snapshot_rules(rec))
        for rid in rules:
            scored[rid] += 1
            if rec.outcome in HIT:
                hits[rid] += 1
    return {rid: {"scored": scored[rid], "hits": hits[rid]} for rid in scored}


def rule_weights(records) -> dict:
    """{rule_id: weight} — >1 for rules beating a coin flip, <1 for the rest."""
    out = {}
    for rid, s in score_records(records).items():
        if s["scored"] < MIN_SCORED:
            continue
        rate = s["hits"] / s["scored"]
        out[rid] = round(max(W_MIN, min(W_MAX, 0.5 + rate)), 3)
    return out


def track_record(records, domain: str, intent_id: Optional[str]) -> Optional[dict]:
    """Per-topic track record for internal use: outcomes the engine called
    and how they landed. `intent_id` narrows to the same topic when stored."""
    rows = [r for r in records if r.outcome and (r.domain or "") == domain]
    if intent_id:
        same = [r for r in rows if intent_id in _snapshot_rules(r)
                or _intent_of(r) == intent_id]
        rows = same or rows
    if not rows:
        return None
    scored_rows = [r for r in rows if r.outcome in SCORED_OUTCOMES]
    hits = sum(1 for r in scored_rows if r.outcome in HIT)
    misses = len(scored_rows) - hits
    scored = len(scored_rows)
    return {"domain": domain, "intent_id": intent_id, "scored": scored,
            "hits": hits, "misses": misses, "unsure": len(rows) - scored,
            "hit_rate": round(hits / scored, 3) if scored else None}


def _intent_of(rec) -> Optional[str]:
    try:
        snap = json.loads(rec.snapshot_json or "{}")
    except (TypeError, ValueError):
        return None
    return ((snap.get("analysis") or {}).get("intent") or {}).get("id")


def lookback_events(records, domain: str) -> list:
    """Past events for the look-back gate: milestone rows in the same domain."""
    out = []
    for rec in records:
        year = getattr(rec, "year", None)
        if getattr(rec, "domain", None) != domain or not year:
            continue
        out.append({"year": rec.year, "month": getattr(rec, "month", None),
                    "label": getattr(rec, "description", None)})
    return out
