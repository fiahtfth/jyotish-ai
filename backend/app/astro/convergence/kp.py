"""KP (Krishnamurti Paddhati) frame for the convergence engine, spec 1.4 "KP".

Reported separately as "KP: supportive / not supportive / not evaluated". KP NEVER
contributes to the traditional convergence count n (dedup.converge ignores it).

Frame: Placidus cusps in the SAME sidereal frame as the rest of the chart -- swe.houses_ex
'P' with FLG_SIDEREAL after engine.apply(birth.settings), exactly as the engine computes the
Lagna, so cusp 1 equals the chart's Lagna and KP shares the chart's ayanamsa. Star /
sub / sub-sub lords come from PyJHora utils.kp_lords_for_longitude.

Significators (4 levels per house, KP Reader): 1 planets in the star of an occupant;
2 occupants; 3 planets in the star of the cusp-sign owner; 4 the owner.
Every KP favourable-house row (spec 2.4) is VERIFY: the computation runs and is shown,
but the KP verdict stays "not evaluated" until rule KP_FAVOURABLE_HOUSE_SETS and the
intent's KP row are source-checked (status 'enabled').
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date, timedelta
from typing import Optional

import swisseph as swe
from jhora import utils

from .. import constants as K
from .. import kp as legacy_kp
from ..engine import BirthInput, apply, birth_fingerprint, calc_lock, engine
from . import _ivl, links, rulepack
from ._facts import unknown_time
from .dedup import kp_label
from .types import NE, S, W, Evidence, IntentConfig, PillarResult

VERSION = "kp-convergence-v1"
R_LEVELS, R_CSL, R_DASHA = "KP_SIGNIFICATOR_LEVELS", "KP_CUSP_SUBLORD_PROMISE", "KP_DASHA_SIGNIFICATION"
R_SETS = "KP_FAVOURABLE_HOUSE_SETS"
SOURCE = "K. S. Krishnamurti, KP Readers (significators, cusp sub-lord theory)"
_PID = {n: i for i, n in K.PLANET_NAMES.items()}
_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 64
_CACHE_LOCK = threading.Lock()


class KPUnavailable(ValueError):
    pass


# ------------------------------------------------------------------ chart
def lords_for(lon: float) -> dict:
    """{star_lord, sub_lord, sub_sub_lord} for a sidereal longitude (PyJHora)."""
    row = list(utils.kp_lords_for_longitude(0, lon % 360.0, include_kp_index=False, levels=2).values())[0]
    star, sub, subsub = row[0], row[1], row[2]
    return {"star_lord": K.PLANET_NAMES[star], "sub_lord": K.PLANET_NAMES[sub],
            "sub_sub_lord": K.PLANET_NAMES[subsub]}


def _point(lon: float) -> dict:
    base = legacy_kp._point(lon)           # sign / nakshatra / segment number (249 table)
    return {"longitude": base["longitude"], "sign": base["sign"], "sign_index": base["sign_index"],
            "degree": base["degree"], "sign_lord": base["sign_lord"], "nakshatra": base["nakshatra"],
            "segment": base["segment"], **lords_for(lon)}


def _jd_ut(birth: BirthInput) -> float:
    return utils.julian_day_number((birth.year, birth.month, birth.day),
                                   (birth.hour, birth.minute, birth.second)) - birth.tz_offset / 24.0


def placidus_cusps(birth: BirthInput) -> list:
    """Sidereal Placidus cusp longitudes (12) in the chart's ayanamsa (birth.settings)."""
    with calc_lock:
        apply(birth.settings)
        try:
            cusps, _ = swe.houses_ex(_jd_ut(birth), birth.lat, birth.lon, b"P", swe.FLG_SIDEREAL)
        except swe.Error as exc:
            raise KPUnavailable("The requested location or time does not permit a KP Placidus chart.") from exc
    if len(cusps) == 13:        # some builds return a 1-based array
        cusps = cusps[1:]
    return [c % 360.0 for c in cusps[:12]]


def _weekday_lord(birth: BirthInput) -> Optional[str]:
    """Vedic weekday (sunrise-to-sunrise) lord at the birth instant."""
    jd_ut = _jd_ut(birth)
    midnight = swe.julday(birth.year, birth.month, birth.day, 0) - birth.tz_offset / 24.0
    with calc_lock:
        apply(birth.settings)
        status, rise = swe.rise_trans(midnight, swe.SUN, swe.CALC_RISE | swe.BIT_HINDU_RISING,
                                      (birth.lon, birth.lat, 0), flags=swe.FLG_SWIEPH)
    if status != 0:
        return None
    day = date(birth.year, birth.month, birth.day)
    if jd_ut < rise[0]:
        day -= timedelta(days=1)
    return ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"][day.weekday()]


def significator_table(planets: dict, cusps: list) -> list:
    """Per house: the four KP significator levels (strongest first)."""
    out = []
    for c in cusps:
        h = c["house"]
        occupants = [n for n, p in planets.items() if p["house"] == h]
        owner = c["sign_lord"]
        l1 = [n for n, p in planets.items() if p["star_lord"] in occupants]
        l3 = [n for n, p in planets.items() if p["star_lord"] == owner]
        out.append({"house": h, "stars_of_occupants": l1, "occupants": occupants, "stars_of_owner": l3,
                    "owner": owner, "levels": {"1": l1, "2": occupants, "3": l3, "4": [owner]}})
    return out


def planet_significations(table: list) -> dict:
    """{planet: {"houses": [...], "by_level": {"1": [...], ...}}} -- houses each planet signifies."""
    out = {n: {"houses": set(), "by_level": {str(i): [] for i in range(1, 5)}} for n in K.PLANET_NAMES.values()}
    for row in table:
        for lvl, names in row["levels"].items():
            for n in names:
                out[n]["by_level"][lvl].append(row["house"])
                out[n]["houses"].add(row["house"])
    return {n: {"houses": sorted(v["houses"]), "by_level": v["by_level"]} for n, v in out.items()}


def kp_chart(birth: BirthInput) -> dict:
    """Raw KP chart for display: cusps, planets (star/sub/sub-sub lords), significators.

    Superset of the legacy /api/kp payload (frame, cusps, planets, significators,
    ruling_planets, segments, limitations). Raises KPUnavailable without a birth time."""
    if getattr(birth, "birth_time_precision", "exact") == "unknown":
        raise KPUnavailable("KP needs the birth time; it is not available while the birth time is unknown.")
    key = birth_fingerprint(birth)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    facts = engine.compute(birth)
    ay = facts["meta"]["ayanamsa"]
    cusp_lons = placidus_cusps(birth)
    cusps = [{"house": i, **_point(lon)} for i, lon in enumerate(cusp_lons, 1)]
    planets = {}
    for name, p in facts["planets"].items():
        lon = float(p.get("abs_longitude", p["sign"] * 30 + p["degree"]))
        planets[name] = {**_point(lon), "house": legacy_kp._house(lon, cusp_lons),
                         "retrograde": bool(p.get("retrograde"))}
    table = significator_table(planets, cusps)
    rulers = {"weekday_lord": _weekday_lord(birth), "lagna_sign_lord": cusps[0]["sign_lord"],
              "lagna_star_lord": cusps[0]["star_lord"], "moon_sign_lord": planets["Moon"]["sign_lord"],
              "moon_star_lord": planets["Moon"]["star_lord"]}
    out = {"frame": {"ayanamsa": ay["id"], "dms": ay.get("dms", ""), "houses": "Placidus",
                     "node": birth.settings.node, "positions": birth.settings.positions,
                     "ayanamsa_basis": "chart settings (same ayanamsa as the Vedic chart)",
                     "rule_version": VERSION, "source": SOURCE},
           "cusps": cusps, "planets": planets, "significators": table,
           "planet_significations": planet_significations(table), "ruling_planets": rulers,
           "segments": [{"number": i, "start_arcsec": a, "end_arcsec": b, "nakshatra": K.NAKSHATRAS[s],
                         "sub_lord": K.PLANET_NAMES[lord]} for i, (a, b, s, lord) in enumerate(legacy_kp._segments(), 1)],
           "limitations": ["Ruling planets are shown for the chart instant using a sunrise-based weekday.",
                           "Rahu/Ketu are listed by their own star/sub only; KP node-agency (conjunction, aspect, "
                           "sign lord) is not applied.",
                           "KP favourable house sets are not source-verified; KP verdicts show 'not evaluated'."]}
    with _CACHE_LOCK:
        _CACHE[key] = out
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


# ------------------------------------------------------------------ report
def _sets(cfg: IntentConfig) -> tuple:
    fav = tuple(cfg.KP["houses"])
    neg = tuple(cfg.KP["negate"]) or links.adv(fav)
    return fav, tuple(h for h in neg if h not in fav)


def _kp_enabled(cfg: IntentConfig) -> Optional[str]:
    """None if this intent's KP row may produce a verdict, else the NE reason."""
    if cfg.KP["status"] != "enabled":
        return "KP house set for this matter is not source-verified (rule disabled pending source check)"
    return rulepack.ne_reason(R_SETS)


def _sig(chart, planet, fav, neg) -> dict:
    houses = set(chart["planet_significations"][planet]["houses"])
    return {"planet": planet, "houses": sorted(houses), "favourable": sorted(houses & set(fav)),
            "negating": sorted(houses & set(neg))}


def _dasha_lords(birth, when: date) -> list:
    try:
        rows = engine.running_vimshottari(birth, (when.year, when.month, when.day))
    except Exception:
        return []
    return list(rows[-1]["lords"]) if rows else []


def _pillar(value, evs, reason=None) -> PillarResult:
    return PillarResult("KP", value, tuple(evs), None, reason)


def kp_report(facts: dict, birth: BirthInput, cfg: IntentConfig, when=None) -> dict:
    """KP verdict for `cfg` at `when` (default today). Never feeds n.

    Returns {"label", "value", "reason", "pillar": PillarResult("KP"), "computed": {...}|None}.
    `computed` carries the cusp sub-lord and dasha-lord significations even while the verdict
    is NE because the house set is unverified."""
    when = _ivl.to_date(when) if when is not None else date.today()
    fav, neg = _sets(cfg)

    def done(pillar, computed=None):
        return {"label": kp_label(pillar), "value": pillar.value, "reason": pillar.ne_reason,
                "pillar": pillar, "computed": computed, "houses": list(fav), "negate": list(neg)}

    if cfg.KP["status"] == "ne" or not fav:
        return done(_pillar(NE, (), "KP is not defined for this matter (spec 2.4)"))
    if unknown_time(facts, birth):
        return done(_pillar(NE, (), "KP needs the birth time"))
    try:
        chart = kp_chart(birth)
    except (KPUnavailable, ValueError) as exc:
        return done(_pillar(NE, (), str(exc)))
    primary = cfg.primary_house
    cusp = chart["cusps"][primary - 1]
    csl = cusp["sub_lord"]
    csl_sig = _sig(chart, csl, fav, neg)
    promise_ok = bool(csl_sig["favourable"]) and len(csl_sig["negating"]) <= len(csl_sig["favourable"])
    lords = _dasha_lords(birth, when)
    dsig = [_sig(chart, p, fav, neg) for p in lords]
    n_fav = sum(bool(s["favourable"]) for s in dsig)
    dasha_ok = bool(dsig) and n_fav >= min(2, len(dsig)) and all(
        len(s["negating"]) <= len(s["favourable"]) for s in dsig)
    evs = [Evidence(R_CSL, rulepack.version(R_CSL), (f"kp.cusps.{primary}.sub_lord",), 1 if promise_ok else -1,
                    1.0, frozenset({f"KP:CSL:H{primary}", f"PLANET:{csl.upper()}"}), None,
                    f"cusp {primary} sub-lord {csl} signifies {csl_sig['houses']} "
                    f"(favourable {csl_sig['favourable']}, negating {csl_sig['negating']})"),
           Evidence(R_DASHA, rulepack.version(R_DASHA), ("vimshottari.running",), 1 if dasha_ok else -1, 1.0,
                    frozenset(f"PLANET:{p.upper()}" for p in lords) | {"KP:DASHA"}, (when, when),
                    "dasha lords " + "; ".join(f"{s['planet']}: fav {s['favourable']} neg {s['negating']}"
                                               for s in dsig))]
    computed = {"date": when.isoformat(), "primary_cusp": primary, "cusp_sub_lord": csl,
                "cusp_sub_lord_signifies": csl_sig, "promise_ok": promise_ok, "dasha_lords": lords,
                "dasha_significations": dsig, "dasha_ok": dasha_ok,
                "verdict_if_enabled": "supportive" if (promise_ok and dasha_ok) else "not supportive",
                "frame": chart["frame"]}
    reason = _kp_enabled(cfg)
    if reason:
        return done(_pillar(NE, evs, reason), computed)
    return done(_pillar(S if (promise_ok and dasha_ok) else W, evs), computed)
