"""Pillar P1: Parashari timing (Vimshottari MD->AD->PD + varga + double transit), spec 1.4.

One PillarResult per Antardasha overlapping [start, end]; the Pratyantar (PD) sub-evaluation
narrows the window. Intervals are ISO date strings ("YYYY-MM-DD"), inclusive of both ends.

Items: 1 activation (AD lord links E, MD or PD lord also links E) | 2 varga (kendra/trikona
from V-Lagna or links to E in V) | 3 MD-AD relationship (clean / friction) | 4 double transit
(Jupiter AND Saturn occupy/aspect primary E-house or E-lord sign) | 5 adverse (ADV links outweigh
E links) | 6 Yogini cross-check (extra evidence only, factor MOON_NAKSHATRA, never a pillar).
S = 1+2+4 and no adverse dominance; M = 1 + friction; W = otherwise; A = adverse dominates.
Mode B (birth time unknown): Moon frame only and the varga item is NE, so S is unreachable.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import swisseph as swe

from .. import constants as K
from .. import transits
from .. import vimshottari as vim
from ..engine import apply, calc_lock
from . import links, rulepack
from .types import A, M, NE, S, W, Evidence, IntentConfig, PillarResult

log = logging.getLogger(__name__)

R_ACT, R_VARGA, R_REL = "P1_ACTIVATION", "P1_VARGA", "P1_MD_AD_RELATION"
R_DT, R_ADV, R_YOG, R_RES = "P1_DOUBLE_TRANSIT", "P1_ADVERSE", "P1_YOGINI_XCHECK", "P1_RESULT"
MOON_NAK = "MOON_NAKSHATRA"
CLEAN = {1, 7, 3, 11, 4, 10, 5, 9}
FRICTION = {2, 12, 6, 8}
KENDRA_TRIKONA = {1, 4, 7, 10, 5, 9}
SECONDARY_W = links.REF_WEIGHT["moon"]


# ---------------------------------------------------------------- date helpers
def to_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def iso(d: date) -> str:
    return d.isoformat()


def jd_to_date(jd: float) -> date:
    y, m, d, _ = swe.revjul(jd)
    return date(y, m, d)


def date_to_jd(d: date) -> float:
    return swe.julday(d.year, d.month, d.day, 0.0)


def merge(ivs: Iterable[tuple]) -> list:
    out = []
    for a, b in sorted((to_date(a), to_date(b)) for a, b in ivs):
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def intersect(xs: list, ys: list) -> list:
    out = []
    for a, b in xs:
        a, b = to_date(a), to_date(b)
        for c, d in ys:
            lo, hi = max(a, to_date(c)), min(b, to_date(d))
            if lo <= hi:
                out.append((lo, hi))
    return merge(out)


def hull_iso(ivs: list) -> Optional[tuple]:
    return (iso(min(a for a, _ in ivs)), iso(max(b for _, b in ivs))) if ivs else None


# ---------------------------------------------------------------- evidence helpers
def _tag(e: Evidence, *, rule=None, extra=(), interval=None, text=None, mult=1.0, direction=None) -> Evidence:
    return replace(e, rule_id=rule or e.rule_id,
                   rule_version=rulepack.version(rule) if rule else e.rule_version,
                   factors=e.factors | frozenset(extra), interval=interval or e.interval,
                   text=text if text is not None else e.text, weight=round(e.weight * mult, 4),
                   direction=e.direction if direction is None else direction)


def _note(rule, direction, factors, text, fids=(), weight=0.0, interval=None, ne_reason=None) -> Evidence:
    return Evidence(rule, rulepack.version(rule), tuple(fids), direction, weight, frozenset(factors), interval,
                    text, ne_reason)


def _vfacts(facts: dict, varga: str) -> Optional[dict]:
    v = (facts.get("vargas") or {}).get(varga)
    if not v or "Lagna" not in v:
        return None
    planets = {n: {"sign": r["sign"], "nakshatra": {}} for n, r in v.items() if n in facts["planets"]}
    return {"lagna": {"sign": v["Lagna"]["sign"]}, "planets": planets}


def _namespaced(e: Evidence, varga: str, rule: str, text: str) -> Evidence:
    return replace(e, rule_id=rule, rule_version=rulepack.version(rule),
                   factors=frozenset(f"{varga}:{f}" for f in e.factors), text=text)


def varga_check(facts: dict, cfg: IntentConfig, planet: str, mode_b: bool = False):
    """Item 2. Returns (met True/False/None(NE), [Evidence])."""
    if mode_b:
        return None, [_note(R_VARGA, 0, (), "varga check needs the birth time (Mode B)", ne_reason="birth time unknown")]
    vs = [v for v in cfg.V if v != "D1"] or ["D1"]
    evs, met, missing = [], False, []
    for v in vs:
        vf = _vfacts(facts, v)
        if vf is None or planet not in vf["planets"]:
            missing.append(v)
            continue
        vh = (vf["planets"][planet]["sign"] - vf["lagna"]["sign"]) % 12 + 1
        if vh in KENDRA_TRIKONA:
            met = True
            evs.append(_note(R_VARGA, +1, {f"{v}:PLANET:{planet.upper()}", f"{v}:HOUSE:{vh}"},
                             f"{planet} is in kendra/trikona (house {vh}) from {v}-Lagna", [f"vargas.{v}.{planet}"], 1.0))
        for e in links.links_to_E(planet, cfg.E, vf, refs=("lagna",)):
            met = True
            evs.append(_namespaced(e, v, R_VARGA, f"{e.text} (in {v})"))
    for v in missing:
        evs.append(_note(R_VARGA, 0, (), f"{v} not available", ne_reason=f"{v} not available"))
    if met:
        return True, evs
    return (None if missing else False), evs


# ---------------------------------------------------------------- transits
def _reach_intervals(sign_ivs: list, planet: str, targets: dict) -> tuple:
    """(merged intervals, matched target kinds) where `planet` occupies/aspects any target sign."""
    out, kinds = [], set()
    for sign, a, b in sign_ivs:
        hit = {k for k, t in targets.items() if t in K.reaches(planet, sign)}
        if hit:
            out.append((a, b))
            kinds |= hit
    return merge(out), kinds


def _targets(facts: dict, E0: int, ref: str) -> dict:
    lord = links.lord_of(facts, E0, ref)
    return {f"HOUSE:{E0}": links.house_sign(facts, E0, ref),
            f"LORD:H{E0}": facts["planets"][lord]["sign"], "_lord": lord}


def double_transit(facts: dict, birth, cfg: IntentConfig, start: date, end: date, refs=("lagna", "moon")) -> dict:
    """{ref: {"intervals": [...], "evidence": {planet: (kinds, intervals)}}} for Jupiter AND Saturn."""
    E0 = cfg.primary_house
    out = {}
    cache = {}
    for ref in refs:
        t = _targets(facts, E0, ref)
        lord = t.pop("_lord")
        res = {}
        for planet in ("Jupiter", "Saturn"):
            if planet not in cache:
                cache[planet] = transits.sign_intervals(birth, planet, start, end)
            ivs, kinds = _reach_intervals(cache[planet], planet, t)
            res[planet] = (kinds, ivs, lord)
        both = intersect(res["Jupiter"][1], res["Saturn"][1])
        out[ref] = {"intervals": both, "planets": res}
    return out


def _dt_evidence(dt_ref: dict, ref: str, window: list, E0: int) -> list:
    pre = "" if ref == "lagna" else "MOON_"
    mult = links.REF_WEIGHT[ref]
    evs = []
    for planet, (kinds, ivs, lord) in dt_ref["planets"].items():
        mine = intersect(ivs, window)
        if not mine:
            continue
        fac = {f"TRANSIT:{planet.upper()}"}
        for k in kinds:
            fac.add(f"{pre}{k}")
            if k.startswith("LORD"):
                fac.add(f"PLANET:{lord.upper()}")
        evs.append(_note(R_DT, +1, fac, f"transiting {planet} occupies/aspects house {E0} or its lord's sign"
                         f" (counted from {'Lagna' if ref == 'lagna' else 'Moon'})", [f"transit.{planet}"],
                         mult, hull_iso(mine)))
    return evs


# ---------------------------------------------------------------- yogini
def _yogini_lords(birth, when: date) -> list:
    """Yogini MD/AD lords at `when` (PyJHora, locked); [] when unavailable."""
    from jhora.horoscope.dhasa.graha import yogini
    from jhora.panchanga import drik
    from jhora import utils
    try:
        with calc_lock:
            apply(birth.settings)
            place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
            jd_birth = utils.julian_day_number((birth.year, birth.month, birth.day),
                                               (birth.hour, birth.minute, birth.second))
            rows = yogini.get_running_dhasa_for_given_date(
                utils.julian_day_number((when.year, when.month, when.day), (12, 0, 0)), jd_birth, place,
                dhasa_level_index=2)
        return [K.PLANET_NAMES[p] for row in rows for p in row[0]]
    except Exception:  # best-effort cross-check; never a pillar
        log.exception("yogini dasha unavailable")
        return []


# ---------------------------------------------------------------- main
def _classify(adverse: bool, item1: bool, friction: bool, item2, item4: bool) -> str:
    if adverse:
        return A
    if item1:
        if friction:
            return M
        return S if (item2 is True and item4) else W
    return W


def evaluate(facts: dict, birth, cfg: IntentConfig, start, end,
             divisionals_dropped: bool = False) -> list:
    """P1 for every Antardasha overlapping [start, end] (dates). One PillarResult per AD.
    divisionals_dropped: every divisional chart was unstable at the stated birth-time
    accuracy — the varga item becomes NE instead of quietly checking D1."""
    start, end = to_date(start), to_date(end)
    if not cfg.E and not cfg.E_adverse_explicit:
        return [PillarResult.not_evaluated("P1", "intent has no event houses")]
    E = cfg.E or cfg.E_adverse_explicit
    mode_b = (facts.get("meta") or {}).get("birth_time_precision") == "unknown"
    refs = ("moon",) if mode_b else ("lagna", "moon")
    sj, ej = date_to_jd(start), date_to_jd(end + timedelta(days=1))
    rows = [r for r in facts["vimshottari"]["periods"] if r["end_jd"] > sj and r["start_jd"] < ej]
    if not rows:
        return [PillarResult.not_evaluated("P1", "no Vimshottari antardasha in the requested range")]
    pds = vim.pd_periods(rows, sj, ej)
    try:
        dts = double_transit(facts, birth, cfg, start, end, refs)
    except Exception as exc:  # transit scan failure -> item 4 NE, never fabricated
        log.exception("double transit scan failed")
        dts, dt_err = {}, str(exc)
    else:
        dt_err = None
    results = []
    for row in rows:
        results.append(_eval_ad(facts, birth, cfg, E, row, pds, dts, dt_err, start, end,
                                refs, mode_b, divisionals_dropped))
    return results


def _eval_ad(facts, birth, cfg, E, row, all_pds, dts, dt_err, start, end, refs, mode_b,
             divisionals_dropped=False) -> PillarResult:
    md, ad = row["lords"][0], row["lords"][1]
    ad_iv = (max(start, jd_to_date(row["start_jd"])), min(end, jd_to_date(row["end_jd"]) - timedelta(days=1)))
    if ad_iv[1] < ad_iv[0]:
        ad_iv = (ad_iv[0], ad_iv[0])
    dasha_tag = (MOON_NAK,)
    bal = links.link_balance(ad, E, facts, refs)
    ad_e = [_tag(e, extra=dasha_tag, text=f"AD lord: {e.text}") for e in bal["E"]]
    md_e = [_tag(e, extra=dasha_tag, text=f"MD lord: {e.text}") for e in links.links_to_E(md, E, facts, refs)]
    evs = []
    pd_rows = [p for p in all_pds if p["lords"][:2] == row["lords"][:2]
               and p["start_jd"] >= row["start_jd"] - 1e-9 and p["end_jd"] <= row["end_jd"] + 1e-9]

    # item 4 window source: Lagna double transit if it intersects the AD, else Moon (secondary)
    dt_ref, dt_ivs, dt_mult = None, [], 1.0
    for ref in refs:
        got = intersect([ad_iv], dts.get(ref, {}).get("intervals", []))
        if got:
            dt_ref, dt_ivs, dt_mult = ref, got, links.REF_WEIGHT[ref] if ref != "lagna" else 1.0
            break

    windows, pd_hits = [], []
    for p in pd_rows:
        pl = p["lords"][2]
        pe = links.links_to_E(pl, E, facts, refs)
        if not pe:
            continue
        piv = [(max(start, jd_to_date(p["start_jd"])), min(end, jd_to_date(p["end_jd"]) - timedelta(days=1)))]
        piv = [x for x in piv if x[0] <= x[1]]
        pd_hits.append((pl, pe, piv))
        sub = intersect(piv, dt_ivs) if dt_ivs else []
        windows += sub
        shown = hull_iso(sub or piv)
        evs += [_tag(e, extra=dasha_tag, interval=shown, text=f"PD lord {pl}: {e.text}") for e in pe]
    if md_e and dt_ivs:
        windows += dt_ivs

    item1 = bool(ad_e) and (bool(md_e) or bool(pd_hits))
    evs = ad_e + md_e + evs
    evs.append(_note(R_ACT, +1 if item1 else 0, {f"PLANET:{ad.upper()}", MOON_NAK},
                     f"AD lord {ad} links to E={list(E)}: {bool(ad_e)}; MD lord links: {bool(md_e)}; "
                     f"PD lords linking: {[p[0] for p in pd_hits]}", [f"vimshottari.{md}.{ad}"]))

    # item 2 varga — NE when every divisional was dropped for instability
    if divisionals_dropped:
        item2 = None
        vev = [_note(R_VARGA, 0, (),
                     "divisional checks skipped — the divisional Lagna changes inside the "
                     "stated birth-time uncertainty", ne_reason="varga lagna unstable")]
    else:
        item2, vev = varga_check(facts, cfg, ad, mode_b)
    evs += vev

    # item 3 MD-AD relationship
    d = (facts["planets"][ad]["sign"] - facts["planets"][md]["sign"]) % 12 + 1
    friction = d in FRICTION
    evs.append(_note(R_REL, -1 if friction else 0, {f"PLANET:{md.upper()}", f"PLANET:{ad.upper()}"},
                     f"{ad} is house {d} from {md}: {'friction (2/12 or 6/8)' if friction else 'clean'}",
                     [f"planets.{md}.sign", f"planets.{ad}.sign"], 1.0 if friction else 0.0))

    # item 4 double transit
    if dt_err:
        evs.append(_note(R_DT, 0, (), "transit scan unavailable", ne_reason=dt_err))
    item4 = bool(windows)
    if dt_ref:
        evs += _dt_evidence(dts[dt_ref], dt_ref, windows or dt_ivs, cfg.primary_house)
    elif not dt_err:
        evs.append(_note(R_DT, 0, (), "Jupiter and Saturn do not jointly reach the E-house/E-lord sign in this AD"))
    item4 = item4 and bool(dt_ref)

    # item 5 adverse
    for e in bal["ADV"]:
        evs.append(_tag(e, extra=dasha_tag, text=f"AD lord: {e.text}"))
    if bal["adverse_dominates"]:
        evs.append(_note(R_ADV, -1, {f"PLANET:{ad.upper()}", MOON_NAK},
                         f"AD lord {ad}: ADV links ({bal['ADV_weight']}) outweigh E links ({bal['E_weight']})",
                         [f"planets.{ad}"], round(bal["ADV_weight"] - bal["E_weight"], 4)))

    # item 6 yogini cross-check (extra evidence only; shares MOON_NAKSHATRA)
    mid = jd_to_date((row["start_jd"] + row["end_jd"]) / 2)
    ylords = _yogini_lords(birth, mid)
    if ylords:
        yl = ylords[-1]
        for e in links.links_to_E(yl, E, facts, refs):
            evs.append(_tag(e, rule=R_YOG, extra=dasha_tag, mult=0.5,
                            text=f"Yogini cross-check (same Moon-nakshatra factor): Yogini lord {yl}: {e.text}"))

    value = _classify(bal["adverse_dominates"], item1, friction, item2, item4)
    interval = hull_iso(windows) if (item4 and windows) else (iso(ad_iv[0]), iso(ad_iv[1]))
    evs.append(_note(R_RES, 0, (), f"items: 1={item1} 2={item2} 3={'friction' if friction else 'clean'} "
                     f"4={item4} 5={bal['adverse_dominates']} -> {value}"))
    return PillarResult("P1", value, tuple(evs), interval)
