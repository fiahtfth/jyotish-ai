"""#57 LIFE_TRANSITION: count independent structural markers in the same 12-month span.

Markers (24 months ahead): Vimshottari MD change; Chara MD sign change; Saturn / Jupiter return;
Rahu return or half-return; Sade Sati start/end; Sudarshana year at 1/4/7/10 from all three
references. Markers sharing an underlying factor (e.g. Saturn return and Sade Sati both
TRANSIT:SATURN) count once. Output is a marker count, not a probability."""
from __future__ import annotations

from datetime import date, timedelta

from ... import constants as K
from ... import precision, transits
from .. import _ivl, rulepack, timing_p1, timing_p2
from .._facts import unknown_time
from . import sade_sati

R = "HOOK_TRANSITION_MARKERS"
HORIZON_DAYS = 730
SPAN_DAYS = 365


def _returns(birth, planet, natal_sign, a, b, kind, factor, extra_sign=None):
    out = []
    for sign, s, _ in transits.sign_intervals(birth, planet, a, b)[1:]:
        if sign == natal_sign:
            out.append({"kind": kind, "date": s.isoformat(), "factor": factor})
        elif extra_sign is not None and sign == extra_sign:
            out.append({"kind": kind.replace("return", "half-return"), "date": s.isoformat(), "factor": factor})
    return out


def markers(facts: dict, birth, today=None) -> list:
    a = _ivl.to_date(today) if today else date.today()
    b = a + timedelta(days=HORIZON_DAYS)
    out, ai, bi = [], a.isoformat(), b.isoformat()
    rows = facts["vimshottari"]["periods"]
    for prev, cur in zip(rows, rows[1:]):
        if cur["maha"] != prev["maha"] and ai <= cur["start"] <= bi:
            out.append({"kind": f"Vimshottari MD change to {cur['maha']}", "date": cur["start"],
                        "factor": "MOON_NAKSHATRA"})
    if not unknown_time(facts, birth):
        try:
            for md in timing_p2._chara_rows(facts, birth):
                d = timing_p1.jd_to_date(md["start_jd"])
                if a <= d <= b:
                    out.append({"kind": f"Chara MD sign change to {K.SIGN_NAMES[md['sign']]}", "date": d.isoformat(),
                                "factor": "LAGNA_SIGN:CHARA"})
        except Exception:
            pass
    p = facts["planets"]
    out += _returns(birth, "Saturn", p["Saturn"]["sign"], a, b, "Saturn return", "TRANSIT:SATURN")
    out += _returns(birth, "Jupiter", p["Jupiter"]["sign"], a, b, "Jupiter return", "TRANSIT:JUPITER")
    out += _returns(birth, "Rahu", p["Rahu"]["sign"], a, b, "Rahu/Ketu return", "TRANSIT:NODES",
                    extra_sign=p["Ketu"]["sign"])
    ss = sade_sati.phases(facts, birth, a, b, include_dhaiya=False)["phases"]
    for r in ss:
        if r["phase"] and r["phase"].startswith("rising") and not r["start_clipped"]:
            out.append({"kind": "Sade Sati starts", "date": r["start"], "factor": "TRANSIT:SATURN"})
        if r["phase"] and r["phase"].startswith("setting") and not r["end_clipped"]:
            out.append({"kind": "Sade Sati ends", "date": r["end"], "factor": "TRANSIT:SATURN"})
    if not unknown_time(facts, birth):
        refs = {"lagna": facts["lagna"]["sign"], "moon": p["Moon"]["sign"], "sun": p["Sun"]["sign"]}
        d = a
        seen = set()
        while d <= b:
            try:
                ys = precision.sudarshana_year_signs(birth, d)
            except Exception:
                break
            houses = {k: (ys[k] - refs[k]) % 12 + 1 for k in refs}
            start = _ivl.to_date(ys.get("start") or d)
            if a <= start <= b and start not in seen and all(h in (1, 4, 7, 10) for h in houses.values()):
                seen.add(start)
                out.append({"kind": "Sudarshana year angular (1/4/7/10) from Lagna, Moon and Sun",
                            "date": start.isoformat(), "factor": "SUDARSHANA"})
            d += timedelta(days=180)
    return sorted(out, key=lambda m: m["date"])


def count_in_span(ms: list, span_days: int = SPAN_DAYS) -> dict:
    """Pure: best 12-month span by number of DISTINCT factors among markers."""
    best = {"count": 0, "start": None, "end": None, "markers": []}
    for m in ms:
        s = _ivl.to_date(m["date"])
        e = s + timedelta(days=span_days - 1)
        inside = [x for x in ms if s <= _ivl.to_date(x["date"]) <= e]
        c = len({x["factor"] for x in inside})
        if c > best["count"]:
            best = {"count": c, "start": s.isoformat(), "end": e.isoformat(), "markers": inside}
    return best


def life_transition(facts: dict, birth, today=None) -> dict:
    ms = markers(facts, birth, today)
    best = count_in_span(ms)
    return {"markers": ms, "best_span": best, "badge": f"Independent transition markers in one 12-month span: {best['count']}",
            "rule_id": R, "rule_version": rulepack.version(R),
            "note": "A count of structural markers, not a probability; Lagna-based markers are skipped without a birth time."}
