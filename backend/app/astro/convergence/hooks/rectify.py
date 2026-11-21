"""#60 BIRTH_TIME_CHECK (rectification support): never 'verified', at best 'consistent with'.

1 stability windows per varga across +-span (stability.lagna_windows / moon_pada_window);
2 one representative time per distinct (D1, D9, D10 Lagna sign, Moon pada) combination;
3 #59 past-event check on the user's >= 3 events for each candidate; score = total n;
4 rank; the top candidate needs a clear lead (better explains >= clear_lead events than the
  runner-up, and a higher total) else "cannot distinguish"; 5 dasha-balance difference."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from ... import stability
from ...engine import engine
from .. import rulepack
from . import past_event

R = "HOOK_RECTIFY_CLEAR_LEAD"
MIN_EVENTS = 3
DEFAULT_CLEAR_LEAD = 2


def shifted(birth, seconds: float):
    dt = datetime(birth.year, birth.month, birth.day, birth.hour, birth.minute, birth.second) + \
        timedelta(seconds=round(seconds))
    return dataclasses.replace(birth, year=dt.year, month=dt.month, day=dt.day, hour=dt.hour,
                               minute=dt.minute, second=dt.second)


def _signature(facts) -> tuple:
    v = facts.get("vargas") or {}
    moon = facts["planets"]["Moon"]["nakshatra"]
    return (facts["lagna"]["sign"], (v.get("D9") or {}).get("Lagna", {}).get("sign"),
            (v.get("D10") or {}).get("Lagna", {}).get("sign"), (moon["index"], moon["pada"]))


def candidates(birth, span_min: int = 15) -> list:
    """[(offset_seconds, shifted_birth, facts, signature)] -- one per distinct combination."""
    span = span_min * 60
    lw = stability.lagna_windows(birth, vargas=(1, 9, 10), span_s=span)
    mp = stability.moon_pada_window(birth, span_s=span)
    cuts = sorted({c for w in lw.values() for c in w["changes_s"] if -span < c < span} |
                  {c for c in mp["changes_s"] if -span < c < span})
    edges = [-span, *cuts, span]
    out, seen = [], set()
    for a, b in zip(edges, edges[1:]):
        if b - a < 1:
            continue
        mid = (a + b) / 2
        sb = shifted(birth, mid)
        f = engine.compute(sb)
        sig = _signature(f)
        if sig in seen:
            continue
        seen.add(sig)
        out.append((round(mid), sb, f, sig))
    return out


def rank(scored: list, clear_lead: int = DEFAULT_CLEAR_LEAD) -> dict:
    """scored: [{"id", "per_event_n": [..], ...}] (same event order). Pure function."""
    rows = sorted(scored, key=lambda r: -sum(r["per_event_n"]))
    for r in rows:
        r["total_n"] = sum(r["per_event_n"])
    if len(rows) < 2:
        return {"verdict": "cannot distinguish" if not rows else "consistent with", "ranked": rows,
                "margin": None, "events_better_explained": None}
    top, second = rows[0], rows[1]
    better = sum(a > b for a, b in zip(top["per_event_n"], second["per_event_n"]))
    worse = sum(a < b for a, b in zip(top["per_event_n"], second["per_event_n"]))
    clear = top["total_n"] > second["total_n"] and better - worse >= clear_lead
    return {"verdict": "consistent with" if clear else "cannot distinguish", "ranked": rows,
            "margin": top["total_n"] - second["total_n"], "events_better_explained": better,
            "events_worse_explained": worse, "clear_lead_required": clear_lead}


def rectify(birth, events: list, span_min: int = 15, clear_lead: int = DEFAULT_CLEAR_LEAD) -> dict:
    if len(events) < MIN_EVENTS:
        return {"status": "needs_input", "reason": f"at least {MIN_EVENTS} dated life events are needed"}
    pack = rulepack.pack_hash()
    scored = []
    for off, sb, f, sig in candidates(birth, span_min):
        recs = [past_event.evaluate_event(f, sb, e["date"], e["type"], pack) for e in events]
        bal = (f.get("vimshottari") or {}).get("birth_balance") or {}
        scored.append({"id": f"{off:+d}s", "offset_seconds": off,
                       "time": f"{sb.hour:02d}:{sb.minute:02d}:{sb.second:02d}",
                       "signature": {"D1": sig[0], "D9": sig[1], "D10": sig[2], "moon_nakshatra_pada": list(sig[3])},
                       "per_event_n": [r.n for r in recs], "dasha_balance": bal})
    res = rank(scored, clear_lead)
    if res["ranked"] and len(res["ranked"]) >= 2:
        a, b = res["ranked"][0]["dasha_balance"], res["ranked"][1]["dasha_balance"]
        res["dasha_balance_difference"] = {"top": a, "runner_up": b,
                                           "years": None if a.get("lord") != b.get("lord") or a.get("years") is None
                                           else round(a["years"] - b["years"], 4)}
    if res["verdict"] == "consistent with" and res["ranked"]:
        res["text"] = f"Events are most consistent with the window around {res['ranked'][0]['time']} (never 'verified')."
    else:
        res["text"] = "The events cannot distinguish between the candidate birth-time windows."
    res.update(rule_id=R, rule_version=rulepack.version(R), rulepack_hash=pack, span_minutes=span_min)
    return res
