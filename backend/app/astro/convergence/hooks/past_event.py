"""#59 PAST_EVENT_CHECK: retrospective T per user-entered event, frozen and immutable.

The rule-pack hash is taken BEFORE any evaluation (rules frozen before feedback); each record
is a frozen dataclass whose `record_hash` covers its full JSON content, so it can be stored
append-only and verified later. Output wording: "consistent with", never proof."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType

from ...engine import birth_fingerprint
from .. import _ivl, dedup, intents, rulepack
from .. import kp as kp_mod
from .. import timing_p1, timing_p2, timing_p3, timing_p4
from .._facts import unknown_time
from ..promise import promise_gate
from ..serialize import jsonable
from ..types import PILLAR_NAMES, PillarResult

R = "HOOK_PAST_EVENT_FREEZE"
EVENT_TYPES = {"job": "JOB_TIMING", "first_job": "JOB_TIMING", "promotion": "CAREER_PROMOTION",
               "job_change": "JOB_CHANGE", "marriage": "MARRIAGE_TIMING", "engagement": "MARRIAGE_TIMING",
               "relocation": "CITY_RELOCATION", "foreign_travel": "FOREIGN_TRAVEL",
               "foreign_settlement": "FOREIGN_SETTLEMENT", "property": "PROPERTY_PURCHASE",
               "vehicle": "VEHICLE_PURCHASE", "exam": "COMPETITIVE_EXAMS", "admission": "COLLEGE_ADMISSION",
               "business": "BUSINESS_START", "income": "INCOME_IMPROVEMENT", "child": "PARENTHOOD"}
P4_HALF_WINDOW = 15


@dataclass(frozen=True)
class PastEventRecord:
    event_date: str
    event_type: str
    intent_id: str
    badge: str
    n: int
    k_evaluated: int
    pillars: tuple                 # ((pillar, value, dependent, ne_reason), ...)
    kp_label: str
    rulepack_hash: str
    chart_fingerprint: str
    frozen_at: str
    payload: MappingProxyType      # full jsonable evidence (read-only)
    record_hash: str

    def as_dict(self) -> dict:
        return {k: (dict(v) if isinstance(v, MappingProxyType) else v) for k, v in self.__dict__.items()}


def _content_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _one(results, day):
    for r in results:
        iv = _ivl.norm(r.interval) if r.interval else None
        if iv and iv[0] <= day <= iv[1]:
            return r
    return results[0] if results else None


def evaluate_event(facts: dict, birth, event_date, event_type: str, pack_hash: str) -> PastEventRecord:
    day = _ivl.to_date(event_date)
    iid = EVENT_TYPES.get(event_type, event_type)
    cfg = intents.get(iid)
    if cfg is None or not cfg.is_timing:
        raise ValueError(f"unknown or non-timing event type {event_type!r}")
    p = []
    for name, fn, lo, hi in (("P1", timing_p1.evaluate, day, day), ("P2", timing_p2.evaluate, day, day),
                             ("P3", timing_p3.evaluate, day, day),
                             ("P4", timing_p4.evaluate, day - timedelta(days=P4_HALF_WINDOW),
                              day + timedelta(days=P4_HALF_WINDOW))):
        try:
            res = fn(facts, birth, cfg, lo, hi)
        except Exception as exc:
            res = [PillarResult.not_evaluated(name, f"{name} unavailable: {exc}")]
        if name == "P4":
            from ..template_t import aggregate_p4
            p.append(aggregate_p4(res, (lo, hi)))
        else:
            got = _one(res, day) or PillarResult.not_evaluated(name, "no result")
            p.append(replace(got, interval=_ivl.norm(got.interval) if got.interval else None))
    promise = None if unknown_time(facts, birth) or cfg.template == "T_adverse" else promise_gate(facts, cfg)
    kp = kp_mod.kp_report(facts, birth, cfg, when=day)
    w = dedup.converge(p, promise, cfg, kp=kp["pillar"], interval=(day, day))
    try:
        fp = birth_fingerprint(birth)
    except Exception:
        fp = "synthetic"
    payload = jsonable({"window": w, "kp": {k: v for k, v in kp.items() if k != "pillar"}})
    body = {"event_date": day.isoformat(), "event_type": event_type, "intent_id": cfg.intent_id,
            "badge": w.badge, "n": w.n, "k_evaluated": w.k_evaluated,
            "pillars": tuple((x.pillar, x.value, x.dependent, x.ne_reason) for x in w.pillars),
            "kp_label": kp["label"], "rulepack_hash": pack_hash, "chart_fingerprint": fp,
            "frozen_at": datetime.now(timezone.utc).isoformat()}
    h = _content_hash({**body, "payload": payload})
    return PastEventRecord(**body, payload=MappingProxyType(payload), record_hash=h)


def check(facts: dict, birth, events: list) -> dict:
    """events: [{"date": "YYYY-MM-DD", "type": "marriage"}, ...]."""
    pack_hash = rulepack.pack_hash()          # frozen before any evaluation / feedback
    records = [evaluate_event(facts, birth, e["date"], e["type"], pack_hash) for e in events]
    if rulepack.pack_hash() != pack_hash:
        raise RuntimeError("rule pack changed during a frozen past-event check")
    return {"rule_id": R, "rule_version": rulepack.version(R), "rulepack_hash": pack_hash,
            "records": records, "total_n": sum(r.n for r in records),
            "wording": "Methods active at each date are shown as n/4: 'consistent with', never proof."}


def verify_record(rec: PastEventRecord) -> bool:
    body = {k: v for k, v in rec.__dict__.items() if k not in ("payload", "record_hash")}
    return _content_hash({**body, "payload": dict(rec.payload)}) == rec.record_hash
