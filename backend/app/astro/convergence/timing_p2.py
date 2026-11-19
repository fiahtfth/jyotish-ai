"""Pillar P2: Jaimini timing (Chara Dasha per configured chara_dasha_school), spec 1.4.

One PillarResult per Chara Antardasha sign overlapping [start, end]; the Chara MD sign is
evaluated too and reported as extra supportive evidence (it never changes the value).
Items: 1 temporary-Lagna activation | 2 primary karaka activation | 3 Jupiter transit support |
4 adverse (dasha sign 6/8/12 from a relevant arudha). The "malefics without benefic
rashi-aspect" sub-check is VERIFY (rule P2_ADVERSE_DASHA_SIGN, disabled) -> reported NE, not applied.
S = (1 or 2) + 3 and no adverse; M = (1 or 2) + adverse; W = (1 or 2) only (or nothing yet);
A = adverse only. Window = the AD-sign interval. Mode B (no birth time) -> NE.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .. import constants as K
from .. import jaimini as J
from .. import transits
from . import links, rulepack
from .timing_p1 import _note, date_to_jd, hull_iso, iso, jd_to_date, merge, to_date
from .types import A, M, S, W, Evidence, IntentConfig, PillarResult

log = logging.getLogger(__name__)

R_TEMP, R_ALT, R_JUP = "P2_TEMP_LAGNA", "P2_ALT_KARAKA", "P2_JUPITER_TRANSIT"
R_ADV, R_ADV_VERIFY, R_RES = "P2_ADVERSE_ARUDHA", "P2_ADVERSE_DASHA_SIGN", "P2_RESULT"
KARAKA_CODES = {"AK": "Atmakaraka", "AmK": "Amatyakaraka", "BK": "Bhratrukaraka", "MK": "Matrukaraka",
                "PK": "Putrakaraka", "GK": "Gnatikaraka", "DK": "Darakaraka"}
ADVERSE_FROM_ARUDHA = {6, 8, 12}
_PID = {n: i for i, n in K.PLANET_NAMES.items()}


def _sign_name(s: int) -> str:
    return K.SIGN_NAMES[s]


def j_points(facts: dict, cfg: IntentConfig) -> list:
    """Resolve cfg.J to [(name, sign, planet|None, kind, factors)]; unresolved names are skipped
    (the caller reports them). kind in {"karaka","arudha","planet","derived"}."""
    jm = facts.get("jaimini") or {}
    kar = jm.get("karakas") or {}
    ar = jm.get("arudhas") or {}
    out = []
    for name in cfg.J:
        if name in KARAKA_CODES:
            planet = kar.get(KARAKA_CODES[name])
            if planet:
                out.append((name, facts["planets"][planet]["sign"], planet, "karaka",
                            frozenset({f"PLANET:{planet.upper()}"})))
        elif name in K.PLANET_NAMES.values() and name in facts["planets"]:
            out.append((name, facts["planets"][name]["sign"], name, "planet", frozenset({f"PLANET:{name.upper()}"})))
        elif name in ar:                                   # A1..A12
            out.append((name, ar[name], None, "arudha", frozenset({f"ARUDHA:{name}"})))
        elif name in ("AL", "UL") and ar:
            out.append((name, ar["A1" if name == "AL" else "A12"], None, "arudha", frozenset({f"ARUDHA:{name}"})))
        elif name in ("UL_2", "AL_11", "AL_12") and ar:
            base, off = {"UL_2": ("A12", 1), "AL_11": ("A1", 10), "AL_12": ("A1", 11)}[name]
            out.append((name, (ar[base] + off) % 12, None, "arudha", frozenset({f"ARUDHA:{name}"})))
        elif name in ("KARAKAMSHA", "KARAKAMSHA_12"):
            ak = kar.get("Atmakaraka")
            d9 = (facts.get("vargas") or {}).get("D9") or {}
            if ak and ak in d9:
                s = d9[ak]["sign"] if name == "KARAKAMSHA" else (d9[ak]["sign"] + 11) % 12
                out.append((name, s, None, "derived", frozenset({f"KARAKAMSHA:{name}"})))
    return out


def _chara_rows(facts: dict, birth) -> list:
    pos = {"L": (facts["lagna"]["sign"], facts["lagna"].get("degree", 0.0))}
    for n, p in facts["planets"].items():
        pos[_PID[n]] = (p["sign"], p["degree"])
    cs = birth.settings
    year_days = float(facts["meta"]["dasha_year"]["days"])
    return J.chara_periods(pos, float(facts["meta"]["julian_day"]), cs.chara_school, year_days,
                           colord_rule=cs.colord_rule)


def _activation(facts, cfg, E0, dsign, points) -> list:
    """Item 1 evidence for dasha sign `dsign` taken as temporary Lagna."""
    es = (dsign + E0 - 1) % 12
    evs = []
    for name, ps, planet, kind, fac in points:
        if ps == es or J._rashi_aspects(ps, es):
            how = "occupies" if ps == es else "rashi-aspects"
            evs.append(_note(R_TEMP, +1, fac, f"J point {name} ({_sign_name(ps)}) {how} house {E0} from dasha sign "
                             f"{_sign_name(dsign)} ({_sign_name(es)})", [f"jaimini.{name}"], 1.0))
    lord = links.lord_of(facts, E0)
    ls = facts["planets"][lord]["sign"]
    if ls == es or J._rashi_aspects(ls, es):
        evs.append(_note(R_TEMP, +1, {f"PLANET:{lord.upper()}", f"LORD:H{E0}"},
                         f"D1 E-lord {lord} ({_sign_name(ls)}) occupies/rashi-aspects house {E0} from dasha sign "
                         f"{_sign_name(dsign)}", [f"planets.{lord}.sign"], 1.0))
    return evs


def _karaka_item(points, cfg, dsign) -> list:
    code = next((j for j in cfg.J if j in KARAKA_CODES), None)
    if code is None:
        return [_note(R_ALT, 0, (), "no Jaimini karaka in J", ne_reason="no karaka configured")]
    row = next((p for p in points if p[0] == code), None)
    if row is None:
        return [_note(R_ALT, 0, (), f"karaka {code} unavailable", ne_reason=f"karaka {code} unavailable")]
    _, ks, _, _, fac = row
    if ks == dsign or J._rashi_aspects(dsign, ks):
        how = "contains" if ks == dsign else "rashi-aspects"
        return [_note(R_ALT, +1, fac, f"dasha sign {_sign_name(dsign)} {how} karaka {code} ({_sign_name(ks)})",
                      [f"jaimini.{code}"], 1.0)]
    return []


def _jupiter_item(jup_ivs, targets, ad_iv) -> list:
    """Item 3: transiting Jupiter occupies/rashi-aspects the dasha sign or a relevant arudha."""
    evs = []
    for label, tsign, fac in targets:
        hit = merge((max(a, ad_iv[0]), min(b, ad_iv[1])) for s, a, b in jup_ivs
                    if (s == tsign or J._rashi_aspects(s, tsign)) and a <= ad_iv[1] and b >= ad_iv[0])
        if hit:
            evs.append(_note(R_JUP, +1, {"TRANSIT:JUPITER", *fac}, f"transiting Jupiter occupies/rashi-aspects {label}",
                             ["transit.Jupiter"], 1.0, hull_iso(hit)))
    return evs


def _adverse_item(points, dsign) -> list:
    evs = []
    for name, asign, _, kind, fac in points:
        if kind != "arudha":
            continue
        h = (dsign - asign) % 12 + 1
        if h in ADVERSE_FROM_ARUDHA:
            evs.append(_note(R_ADV, -1, fac, f"dasha sign {_sign_name(dsign)} is house {h} from arudha {name}",
                             [f"jaimini.{name}"], 1.0))
    return evs


def _classify(act: bool, jup: bool, adverse: bool) -> str:
    if act:
        if adverse:
            return M
        return S if jup else W
    return A if adverse else W


def evaluate(facts: dict, birth, cfg: IntentConfig, start, end) -> list:
    start, end = to_date(start), to_date(end)
    if (facts.get("meta") or {}).get("birth_time_precision") == "unknown":
        return [PillarResult.not_evaluated("P2", "birth time unknown (Mode B): Jaimini Chara Dasha needs the Lagna")]
    E = cfg.E or cfg.E_adverse_explicit
    if not E:
        return [PillarResult.not_evaluated("P2", "intent has no event houses")]
    E0 = cfg.primary_house
    try:
        periods = _chara_rows(facts, birth)
    except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        log.exception("chara dasha unavailable")
        return [PillarResult.not_evaluated("P2", f"chara dasha unavailable: {exc}")]
    sj, ej = date_to_jd(start), date_to_jd(end + timedelta(days=1))
    rows = [(md, ad) for md in periods for ad in md["antardashas"] if ad["end_jd"] > sj and ad["start_jd"] < ej]
    if not rows:
        return [PillarResult.not_evaluated("P2", "no Chara antardasha in the requested range")]
    points = j_points(facts, cfg)
    if not points and not facts.get("planets"):
        return [PillarResult.not_evaluated("P2", "Jaimini points unavailable")]
    try:
        jup_ivs = transits.sign_intervals(birth, "Jupiter", start, end)
        jup_err = None
    except Exception as exc:
        log.exception("jupiter scan failed")
        jup_ivs, jup_err = [], str(exc)
    arudha_pts = [p for p in points if p[3] == "arudha"]
    out = []
    for md, ad in rows:
        a0 = max(start, jd_to_date(ad["start_jd"]))
        a1 = min(end, jd_to_date(ad["end_jd"]) - timedelta(days=1))
        ad_iv = (a0, max(a0, a1))
        ds = ad["sign"]
        evs = _activation(facts, cfg, E0, ds, points)
        evs_alt = _karaka_item(points, cfg, ds)
        act = bool(evs) or any(e.direction > 0 for e in evs_alt)
        md_ev = [_note(R_TEMP, +1, e.factors, f"Chara MD sign {_sign_name(md['sign'])}: {e.text}", e.fact_ids, 0.5)
                 for e in _activation(facts, cfg, E0, md["sign"], points)] if md["sign"] != ds else []
        targets = [(f"dasha sign {_sign_name(ds)}", ds, ())] + \
                  [(f"arudha {n} ({_sign_name(s)})", s, f) for n, s, _, _, f in arudha_pts]
        jev = _jupiter_item(jup_ivs, targets, ad_iv)
        adv = _adverse_item(points, ds)
        notes = [_note(R_ADV_VERIFY, 0, (), "malefics-without-benefic-rashi-aspect sub-check not applied",
                       ne_reason=rulepack.ne_reason(R_ADV_VERIFY) or "rule disabled pending source check")]
        if jup_err:
            notes.append(_note(R_JUP, 0, (), "transit scan unavailable", ne_reason=jup_err))
        value = _classify(act, bool(jev), bool(adv))
        notes.append(_note(R_RES, 0, (), f"school={birth.settings.chara_school}; items: activation={act} "
                           f"jupiter={bool(jev)} adverse={bool(adv)} -> {value}"))
        out.append(PillarResult("P2", value, tuple(evs + evs_alt + md_ev + jev + adv + notes),
                                (iso(ad_iv[0]), iso(ad_iv[1]))))
    return out
