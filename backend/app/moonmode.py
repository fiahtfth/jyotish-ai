"""Moon-chart (Chandra Lagna) mode for profiles whose birth time is unknown.

Without a birth time the Lagna, houses counted from it, Lagna-based divisional
charts, arudhas, KP and bhava data are guesses. In this mode the Moon sign is
used as the Lagna, everything that depends on the clock time of birth is
removed, and the two Moon possibilities for the birth date (00:00 and 23:59
local) are computed so a Moon sign/nakshatra change during that day is stated
openly. Also holds the retro/combust marker merge for chart drawing.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date

from .astro import constants as K
from .astro.engine import BirthInput, engine

NODES = ("Rahu", "Ketu")

# Keys of the locked facts that stay valid without a birth time (the strict,
# model-facing view). Everything else is dropped.
_MODEL_KEYS = ("meta", "planets", "vimshottari", "sarvastakavarga", "binnashtakavarga",
               "compound_dignity", "node_check", "current_vimshottari", "referenced_mahadashas")
# Keys removed from the lighter view used by computed (non-model) code paths.
_LAGNA_KEYS = ("bhava", "bhava_bala", "education", "yogas", "prastara_ashtakavarga", "shadbala",
               "vimshopaka", "ashtakavarga")


def is_unknown(profile_or_precision) -> bool:
    p = getattr(profile_or_precision, "birth_time_precision", profile_or_precision)
    return p == "unknown"


def merge_markers(facts: dict, chart: dict | None, varga: str = "D1") -> dict | None:
    """Copy of a varga chart carrying per-planet retrograde (all vargas) and combust (D1 only) flags.
    Rahu and Ketu are never marked retrograde: their backward motion is normal."""
    if not chart:
        return chart
    planets = facts.get("planets") or {}
    out = {}
    for name, rec in chart.items():
        rec = dict(rec)
        src = planets.get(name)
        if src is not None and name not in NODES:
            rec["retrograde"] = bool(src.get("retrograde"))
            if varga == "D1":
                rec["combust"] = bool(src.get("combust"))
        else:
            rec.pop("retrograde", None)
            rec.pop("combust", None)
        out[name] = rec
    return out


def merged_vargas(facts: dict) -> dict:
    return {v: merge_markers(facts, c, v) for v, c in (facts.get("vargas") or {}).items()}


# ------------------------------------------------------------------ Moon possibilities

def _moon_at(birth: BirthInput, hour: int, minute: int, second: int) -> dict:
    f = engine.compute(replace(birth, hour=hour, minute=minute, second=second,
                               birth_time_precision="exact"))
    return f["planets"]["Moon"]


def _poss(label: str, moon: dict) -> dict:
    nk = moon["nakshatra"]
    return {"label": label, "sign": moon["sign"], "sign_name": moon["sign_name"],
            "nakshatra": nk["name"], "pada": nk["pada"], "nakshatra_lord": nk.get("lord"),
            "_lon": moon["abs_longitude"]}


def _change_time(a: dict, b: dict, boundary: float) -> str:
    delta = (b["_lon"] - a["_lon"]) % 360.0
    if delta <= 0:
        return ""
    frac = ((boundary - a["_lon"]) % 360.0) / delta
    minutes = int(round(min(max(frac, 0.0), 1.0) * 1439))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def moon_possibilities(birth: BirthInput, today: date | None = None) -> dict:
    """What the Moon could be on the birth date: start of day, end of day, and what changes."""
    start = _poss("start of the day (00:00)", _moon_at(birth, 0, 0, 0))
    end = _poss("end of the day (23:59)", _moon_at(birth, 23, 59, 0))
    sign_changes = start["sign"] != end["sign"]
    nak_changes = (start["nakshatra"] != end["nakshatra"])
    pada_changes = start["pada"] != end["pada"] and not nak_changes
    info = {"sign_changes": sign_changes, "nakshatra_changes": nak_changes, "pada_changes": pada_changes,
            "possibilities": [start, end] if (sign_changes or nak_changes) else [start]}
    if sign_changes:
        info["sign_change_about"] = _change_time(start, end, end["sign"] * 30.0)
    if nak_changes and not sign_changes:
        info["nakshatra_change_about"] = _change_time(
            start, end, (int(start["_lon"] // K.NAK_SPAN) + 1) * K.NAK_SPAN % 360.0)
    if nak_changes and today is not None:
        when = (today.year, today.month, today.day)
        info["running_dasha_if"] = []
        for poss, (h, m) in ((start, (0, 0)), (end, (23, 59))):
            try:
                run = engine.running_vimshottari(replace(birth, hour=h, minute=m, second=0), when)
            except Exception:
                continue
            if run:
                info["running_dasha_if"].append({"label": poss["label"], "lords": run[-1]["lords"],
                                                 "start": run[-1]["start"], "end": run[-1]["end"]})
    for p in info["possibilities"]:
        p.pop("_lon", None)
    return info


# ------------------------------------------------------------------ rotation

def _lord_of(sign: int) -> str:
    return K.PLANET_NAMES[K.SIGN_LORD[sign]]


def _rotated_planets(planets: dict, moon_sign: int) -> dict:
    return {n: {**rec, "house": (rec["sign"] - moon_sign) % 12 + 1} for n, rec in planets.items()}


def chandra_facts(facts: dict, birth: BirthInput | None = None, today: date | None = None,
                  *, strict: bool = False) -> dict:
    """Facts re-anchored on the Moon sign. `strict` keeps only what is safe to show a model."""
    if facts.get("moon_mode"):
        return facts if not strict else _strict(facts)
    moon = facts["planets"]["Moon"]
    ms = moon["sign"]
    out = {k: v for k, v in facts.items() if k not in _LAGNA_KEYS}
    out["planets"] = _rotated_planets(facts["planets"], ms)
    out["lagna"] = {"sign": ms, "sign_name": K.SIGN_NAMES[ms], "degree": moon["degree"], "lord": _lord_of(ms),
                    "nakshatra": moon["nakshatra"], "boundary_flags": [], "chandra_lagna": True}
    out["houses"] = {h: {"sign": (ms + h - 1) % 12, "sign_name": K.SIGN_NAMES[(ms + h - 1) % 12],
                         "lord": _lord_of((ms + h - 1) % 12)} for h in range(1, 13)}
    func = facts.get("functional") or {}
    out["functional"] = {k: ([] if isinstance(v, list) else {} if isinstance(v, dict) else None)
                         for k, v in func.items()}
    out["functional"]["source"] = "unavailable without a birth time"
    out["bhava"] = {}
    jk = facts.get("jaimini") or {}
    out["jaimini"] = {k: copy.deepcopy(jk[k]) for k in ("karakas", "karaka_scheme", "karaka_ties") if k in jk}
    d1 = (facts.get("vargas") or {}).get("D1") or {}
    d1 = {n: rec for n, rec in d1.items() if n != "Lagna"}
    d1["Lagna"] = {"sign": ms, "degree": moon["degree"], "abs_longitude": moon["abs_longitude"],
                   "chandra_lagna": True}
    out["vargas"] = {"D1": merge_markers(facts, d1, "D1")}
    mm = moon_possibilities(birth, today) if birth is not None else {}
    mm["basis"] = "chandra_lagna"
    if mm.get("sign_changes"):
        alt = {}
        for poss in mm["possibilities"]:
            houses = {n: (rec["sign"] - poss["sign"]) % 12 + 1 for n, rec in facts["planets"].items()
                      if n != "Moon"}
            alt[poss["sign_name"]] = houses
        mm["houses_if_moon_in"] = alt
    out["moon_mode"] = mm
    meta = dict(out.get("meta") or {})
    meta.pop("julian_day", None)
    if meta.get("birth_datetime_local"):
        meta["birth_datetime_local"] = str(meta["birth_datetime_local"]).split(" ")[0] + " (time unknown)"
    out["meta"] = meta
    return _strict(out) if strict else out


def _strict(facts: dict) -> dict:
    keep = set(_MODEL_KEYS) | {"lagna", "houses", "functional", "vargas", "moon_mode", "jaimini", "bhava"}
    out = {k: v for k, v in facts.items() if k in keep}
    out["bhava"] = {}
    return out


def prompt_lines(facts: dict) -> list[str]:
    """Plain-language CHART FACTS lines describing Chandra Lagna mode and Moon uncertainty."""
    mm = facts.get("moon_mode")
    if not mm:
        return []
    lines = ["BIRTH TIME UNKNOWN: the chart is read from the Moon sign as Lagna (Chandra Lagna). "
             "There is no Lagna, no houses from Lagna, no divisional-chart Lagnas, arudhas, KP or bhava data. "
             "House numbers below are counted from the Moon sign."]
    poss = mm.get("possibilities") or []
    if mm.get("sign_changes") and len(poss) == 2:
        when = f" at about {mm['sign_change_about']} local time" if mm.get("sign_change_about") else ""
        lines.append(f"The Moon changes sign on the birth date: {poss[0]['sign_name']} ({poss[0]['nakshatra']} "
                     f"pada {poss[0]['pada']}) early in the day, {poss[1]['sign_name']} ({poss[1]['nakshatra']} "
                     f"pada {poss[1]['pada']}) late in the day{when}. Give both possibilities and say that "
                     "Moon-sign readings, house readings and dasha timing are uncertain until the time is known; "
                     "Sun, Mars, Jupiter, Saturn and the nodes are unaffected.")
        for sign_name, houses in (mm.get("houses_if_moon_in") or {}).items():
            lines.append(f"If the Moon is in {sign_name}, houses from Moon: "
                         + ", ".join(f"{n} {h}" for n, h in houses.items()))
    elif mm.get("nakshatra_changes") and len(poss) == 2:
        lines.append(f"The Moon stays in {poss[0]['sign_name']} but changes nakshatra on the birth date: "
                     f"{poss[0]['nakshatra']} then {poss[1]['nakshatra']}. The Vimshottari balance and period dates "
                     "below are therefore uncertain; say so for any timing.")
        for r in mm.get("running_dasha_if") or []:
            lines.append(f"Running Vimshottari if born in the {r['label']}: "
                         f"{' / '.join(r['lords'])} ({r['start']} to {r['end']})")
    else:
        lines.append(f"The Moon stays in {poss[0]['sign_name']} ({poss[0]['nakshatra']}) through the birth date"
                     + (", though the pada can shift" if mm.get("pada_changes") else "")
                     + ", so Moon-sign readings are reliable.")
    return lines
