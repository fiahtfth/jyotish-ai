"""#48 SADE_SATI: deterministic Saturn phases against the natal Moon (no convergence badge).

Phases from transiting Saturn's sidereal sign intervals (retrograde re-entries kept as
separate rows); classification reuses gochara.saturn_states. Dhaiya (Kantaka 4th / Ashtama
8th) is included when requested. Optional Saturn BAV per phase sign (>=4 = traditionally milder)."""
from __future__ import annotations

from datetime import date, timedelta

from ... import constants as K
from ... import gochara, transits
from .. import _ivl, rulepack

R_SADE, R_DHAIYA = "HOOK_SADE_SATI", "HOOK_DHAIYA"
SATURN = 6


def phases(facts: dict, birth, start, end, include_dhaiya: bool = True) -> dict:
    start, end = _ivl.to_date(start), _ivl.to_date(end)
    moon = int(facts["planets"]["Moon"]["sign"])
    bav = facts.get("binnashtakavarga")
    rows = []
    for sign, a, b in transits.sign_intervals(birth, "Saturn", start, end):
        st = gochara.saturn_states(K.house_from(sign, moon))
        kind = "sade_sati" if st["sade_sati"] else ("kantaka" if st["kantaka"] else
                                                     ("ashtama" if st["ashtama"] else None))
        if kind is None or (kind != "sade_sati" and not include_dhaiya):
            continue
        b_val = int(bav[SATURN][sign]) if bav and len(bav) > SATURN else None
        rows.append({"kind": kind, "phase": st["sade_sati_phase"], "sign": K.SIGN_NAMES[sign],
                     "house_from_moon": st["house_from_moon"], "start": a.isoformat(), "end": b.isoformat(),
                     "start_clipped": a == start, "end_clipped": b == end, "saturn_bav": b_val,
                     "bav_note": None if b_val is None else ("traditionally milder (BAV >= 4)" if b_val >= 4
                                                              else "BAV below 4"),
                     "rule_id": R_SADE if kind == "sade_sati" else R_DHAIYA,
                     "rule_version": rulepack.version(R_SADE if kind == "sade_sati" else R_DHAIYA)})
    active = [r for r in rows if r["start"] <= date.today().isoformat() <= r["end"]]
    return {"natal_moon_sign": K.SIGN_NAMES[moon], "range": [start.isoformat(), end.isoformat()],
            "phases": rows, "active_today": active,
            "note": "Dates are sidereal sign ingresses of Saturn in the chart's ayanamsa; retrograde "
                    "re-entries appear as separate rows. A traditional transit period, not a forecast of hardship."}


def default_range(today=None) -> tuple:
    today = _ivl.to_date(today) if today else date.today()
    return today - timedelta(days=366 * 3), today + timedelta(days=366 * 10)
