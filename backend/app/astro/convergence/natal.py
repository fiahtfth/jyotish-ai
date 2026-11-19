"""Template N (natal agreement), spec 1.5: M1 D1, M2 Varga, M3 Jaimini, M4 Strength.

Badge "Natal agreement: n/4"; factor de-duplication as spec 1.2 (M1>M2>M3>M4).
Varga facts are namespaced by chart ("D9:PLANET:VENUS") because the placement
in a varga is a distinct fact from the D1 placement. KP is never counted.
"""
from __future__ import annotations

from typing import Callable, Optional

from .. import constants as K
from .. import jaimini as jaimini_mod
from .. import yogas as yogas_mod
from . import links
from .dedup import badge_text, dedup_pillars
from .promise import (DUSTHANA, GOOD_RELATIONS, BAD_RELATIONS, KENDRA_TRIKONA, _neecha_bhanga, _ratio,
                      _vhouse, _vimshopaka, promise_gate, resolve_karakas)
from ..pillars import CONVERGENCE_DISCLAIMER
from .types import (A, M, NE, NATAL_NAMES, S, W, INSUFFICIENT_DATA, WEAK_INDICATION, Evidence,
                    IntentConfig, PillarResult, WindowResult)

RULE = {"M1": "NATAL_M1", "M2": "NATAL_M2", "M3": "NATAL_M3", "M4": "NATAL_M4"}
RULE_VERSION = "1.0"
NATAL_THEME = "natal_theme"
GOOD_HOUSES = {1, 2, 4, 5, 7, 9, 10, 11}
BENEFICS = {K.PLANET_NAMES[i] for i in K.NATURAL_BENEFICS}
MALEFICS = {K.PLANET_NAMES[i] for i in K.NATURAL_MALEFICS}

P1Overlay = Callable[[dict, IntentConfig], PillarResult]


def _e(m, factors, direction, text, fids, weight=1.0):
    return Evidence(RULE[m], RULE_VERSION, tuple(fids), direction, weight, frozenset(factors), None, text)


def grade(evs) -> str:
    sup = sum(e.weight for e in evs if e.direction > 0)
    adv = sum(e.weight for e in evs if e.direction < 0)
    if sup >= 2:
        return S if adv == 0 else M
    if sup > 0:
        return W
    return A if adv > 0 else W


def _influences(facts, sign):
    occ = {n for n, p in facts["planets"].items() if p["sign"] == sign}
    asp = {n for n in facts["planets"] if links.aspects_sign(n, facts, sign)}
    return occ | asp


def _m1(facts, cfg):
    evs = []
    for h in cfg.E:
        lord = links.lord_of(facts, h)
        p = facts["planets"][lord]
        base = {f"PLANET:{lord.upper()}", f"LORD:H{h}", f"HOUSE:{h}"}
        if p["house"] in GOOD_HOUSES:
            evs.append(_e("M1", base, 1, f"{lord}, lord of {h}, sits in house {p['house']}", [f"planets.{lord}.house"]))
        elif p["house"] in DUSTHANA:
            evs.append(_e("M1", base, -1, f"{lord}, lord of {h}, sits in dusthana {p['house']}", [f"planets.{lord}.house"]))
        rel = ((facts.get("compound_dignity") or {}).get(lord) or {}).get("relation")
        tags = set(p["dignity"])
        if tags & {"exalted", "moolatrikona", "own sign"} or (rel in GOOD_RELATIONS):
            evs.append(_e("M1", base, 1, f"{lord} dignified ({sorted(tags) or rel})", [f"planets.{lord}.dignity"]))
        elif "debilitated" in tags and not _neecha_bhanga(facts, lord) or rel in BAD_RELATIONS or p.get("combust"):
            evs.append(_e("M1", base, -1, f"{lord} weakened ({sorted(tags) or rel})", [f"planets.{lord}.dignity"]))
        infl = _influences(facts, links.house_sign(facts, h)) - {lord}
        ben, mal = infl & BENEFICS, infl & MALEFICS
        if ben:
            evs.append(_e("M1", {f"HOUSE:{h}"}, 1, f"house {h} has benefic influence {sorted(ben)}", [f"houses.{h}"]))
        elif mal:
            evs.append(_e("M1", {f"HOUSE:{h}"}, -1, f"house {h} has only malefic influence {sorted(mal)}", [f"houses.{h}"]))
    relevant = {links.lord_of(facts, h) for h in cfg.E} | set(resolve_karakas(cfg, facts))
    for y in yogas_mod.detect(facts):
        if y.get("level") == "classical" and ({y.get("planet"), y.get("lord")} & relevant):
            evs.append(_e("M1", {f"YOGA:{y['id']}"}, 1, f"{y['name']} (classical conditions met)", [f"yogas.{y['id']}"]))
    return PillarResult("M1", grade(evs), tuple(evs))


def _m2(facts, cfg):
    v = cfg.primary_varga
    chart = (facts.get("vargas") or {}).get(v) if v else None
    if not v or not chart or "Lagna" not in chart:
        return PillarResult.not_evaluated("M2", f"varga {v or '(none configured)'} not available")
    evs = []
    h = cfg.E[0] if cfg.E else None
    targets = [(links.lord_of(facts, h), f"lord of {h}")] if h else []
    targets += [(k, "karaka") for k in resolve_karakas(cfg, facts)]
    for planet, role in targets:
        vh = _vhouse(facts, v, planet)
        if vh is None:
            continue
        fac = {f"{v}:PLANET:{planet.upper()}"}
        if vh in KENDRA_TRIKONA:
            evs.append(_e("M2", fac, 1, f"{planet} ({role}) in house {vh} of {v}", [f"vargas.{v}.{planet}"]))
        elif vh in DUSTHANA:
            evs.append(_e("M2", fac, -1, f"{planet} ({role}) in dusthana {vh} of {v}", [f"vargas.{v}.{planet}"]))
    if h:
        sign = (chart["Lagna"]["sign"] + h - 1) % 12
        occ = {n for n, rec in chart.items() if n in facts["planets"] and rec["sign"] == sign}
        ben, mal = occ & BENEFICS, occ & MALEFICS
        fac = {f"{v}:HOUSE:{h}"}
        if ben:
            evs.append(_e("M2", fac, 1, f"benefic {sorted(ben)} in house {h} of {v}", [f"vargas.{v}"]))
        elif mal:
            evs.append(_e("M2", fac, -1, f"only malefic {sorted(mal)} in house {h} of {v}", [f"vargas.{v}"]))
        lord = K.PLANET_NAMES[K.SIGN_LORD[sign]]
        if lord in chart:
            lh = (chart[lord]["sign"] - chart["Lagna"]["sign"]) % 12 + 1
            fl = {f"{v}:HOUSE:{h}", f"{v}:LORD:H{h}"}
            if lh in KENDRA_TRIKONA:
                evs.append(_e("M2", fl, 1, f"{v} house-{h} lord {lord} in house {lh}", [f"vargas.{v}.{lord}"]))
            elif lh in DUSTHANA:
                evs.append(_e("M2", fl, -1, f"{v} house-{h} lord {lord} in dusthana {lh}", [f"vargas.{v}.{lord}"]))
    return PillarResult("M2", grade(evs), tuple(evs))


def _jaimini_signs(facts, cfg):
    j = facts.get("jaimini")
    if not j:
        return None
    karakas = j.get("karakas") or {}
    ar = j.get("arudhas") or {}
    al = (j.get("arudha_lagna") or {}).get("sign")
    ul = (j.get("upapada_lagna") or {}).get("sign")
    ak = karakas.get("Atmakaraka")
    kam = ((facts.get("vargas") or {}).get("D9") or {}).get(ak, {}).get("sign") if ak else None
    full = {"AK": "Atmakaraka", "AmK": "Amatyakaraka", "BK": "Bhratrukaraka", "MK": "Matrukaraka",
            "PK": "Putrakaraka", "GK": "Gnatikaraka", "DK": "Darakaraka"}
    out = {}
    for t in cfg.J:
        sign = None
        if t in full:
            pl = karakas.get(full[t])
            sign = facts["planets"][pl]["sign"] if pl in facts["planets"] else None
        elif t == "AL":
            sign = al
        elif t == "UL":
            sign = ul
        elif t in ar:
            sign = ar[t]
        elif t == "UL_2":
            sign = None if ul is None else (ul + 1) % 12
        elif t == "AL_11":
            sign = None if al is None else (al + 10) % 12
        elif t == "AL_12":
            sign = None if al is None else (al + 11) % 12
        elif t == "KARAKAMSHA":
            sign = kam
        elif t == "KARAKAMSHA_12":
            sign = None if kam is None else (kam + 11) % 12
        elif t in facts["planets"]:
            sign = facts["planets"][t]["sign"]
        if sign is not None:
            out[t] = sign
    return out


def _rashi_infl(facts, sign):
    occ = {n for n, p in facts["planets"].items() if p["sign"] == sign}
    asp = {n for n, p in facts["planets"].items() if jaimini_mod._rashi_aspects(p["sign"], sign)}
    return occ | asp


def _m3(facts, cfg):
    pts = _jaimini_signs(facts, cfg)
    if pts is None:
        return PillarResult.not_evaluated("M3", "jaimini facts unavailable")
    if not pts:
        return PillarResult.not_evaluated("M3", "no Jaimini points configured/resolvable")
    e_signs = [links.house_sign(facts, h) for h in cfg.E]
    evs = []
    for tok, sign in pts.items():
        fac = {f"JAIMINI:{tok}", f"SIGN:{sign}"}
        infl = _rashi_infl(facts, sign)
        ben, mal = infl & BENEFICS, infl & MALEFICS
        linked = sign in e_signs or any(jaimini_mod._rashi_aspects(sign, es) for es in e_signs)
        if linked:
            evs.append(_e("M3", fac | {f"HOUSE:{links.house_of_sign(sign, facts)}"}, 1,
                          f"{tok} sign links to an event house (occupied or rashi-aspected)", [f"jaimini.{tok}"]))
        if ben:
            evs.append(_e("M3", fac, 1, f"{tok}: benefic influence {sorted(ben)}", [f"jaimini.{tok}"], 0.5))
        elif mal:
            evs.append(_e("M3", fac, -1, f"{tok}: only malefic influence {sorted(mal)}", [f"jaimini.{tok}"], 0.5))
        if tok.startswith("A") or tok in ("AL", "UL"):
            for off, name in ((1, "2nd"), (6, "7th"), (11, "12th")):
                s2 = (sign + off) % 12
                i2 = _rashi_infl(facts, s2)
                f2 = {f"JAIMINI:{tok}:{name}", f"SIGN:{s2}"}
                if i2 & BENEFICS:
                    evs.append(_e("M3", f2, 1, f"benefic influence on {name} from {tok}", [f"jaimini.{tok}"], 0.5))
                elif i2 & MALEFICS:
                    evs.append(_e("M3", f2, -1, f"only malefic influence on {name} from {tok}", [f"jaimini.{tok}"], 0.5))
    return PillarResult("M3", grade(evs), tuple(evs))


def _m4(facts, cfg):
    evs, avail = [], False
    planets = []
    if cfg.E:
        planets.append(links.lord_of(facts, cfg.E[0]))
    planets += resolve_karakas(cfg, facts)
    for pl in dict.fromkeys(planets):
        fac = {f"PLANET:{pl.upper()}"}
        r, v = _ratio(facts, pl), _vimshopaka(facts, pl)
        if r is not None:
            avail = True
            if r >= 1.0:
                evs.append(_e("M4", fac, 1, f"{pl} shadbala ratio {r}", [f"shadbala.{pl}"]))
            elif r < 0.8:
                evs.append(_e("M4", fac, -1, f"{pl} shadbala ratio {r}", [f"shadbala.{pl}"]))
        if v is not None:
            avail = True
            if v >= 10:
                evs.append(_e("M4", fac, 1, f"{pl} vimshopaka {v}", [f"vimshopaka.{pl}"]))
    for h in cfg.E[:1]:
        bb = (facts.get("bhava_bala") or {}).get("ratio")
        if bb:
            avail = True
            if bb[h - 1] >= 1.0:
                evs.append(_e("M4", {f"BHAVA_BALA:H{h}"}, 1, f"bhava bala ratio {bb[h - 1]} for house {h}", ["bhava_bala"]))
            elif bb[h - 1] < 0.8:
                evs.append(_e("M4", {f"BHAVA_BALA:H{h}"}, -1, f"bhava bala ratio {bb[h - 1]} for house {h}", ["bhava_bala"]))
        sav = facts.get("sarvastakavarga")
        if sav:
            avail = True
            val = sav[links.house_sign(facts, h)]
            if val >= 28:
                evs.append(_e("M4", {f"SAV:H{h}"}, 1, f"SAV {val} for house {h}", ["sarvastakavarga"]))
            elif val < 25:
                evs.append(_e("M4", {f"SAV:H{h}"}, -1, f"SAV {val} for house {h}", ["sarvastakavarga"]))
    if not avail:
        return PillarResult.not_evaluated("M4", "strength facts unavailable")
    return PillarResult("M4", grade(evs), tuple(evs))


def template_N(facts: dict, cfg: IntentConfig, p1_overlay: Optional[P1Overlay] = None) -> WindowResult:
    """Natal agreement for cfg. `p1_overlay(facts, cfg)` may return a PillarResult for
    "Is this theme active now?" (current MD/AD/PD); it is attached, never counted in n."""
    unknown_time = (facts.get("meta") or {}).get("birth_time_precision") == "unknown"
    if unknown_time:
        res = [PillarResult.not_evaluated(m, "birth time unknown") for m in NATAL_NAMES]
    elif not cfg.E:
        res = [PillarResult.not_evaluated(m, "intent has no event houses (handled by its hook)") for m in NATAL_NAMES]
    else:
        res = [_m1(facts, cfg), _m2(facts, cfg), _m3(facts, cfg), _m4(facts, cfg)]
    deduped, n, dependent = dedup_pillars(res)
    k = sum(p.value != NE for p in deduped)
    result_type = INSUFFICIENT_DATA if k <= 1 else (NATAL_THEME if n >= cfg.min_n_for_label else WEAK_INDICATION)
    promise = promise_gate(facts, cfg) if (cfg.E and not unknown_time) else None
    overlay = p1_overlay(facts, cfg) if p1_overlay and not unknown_time else None
    evid = [e for p in deduped for e in p.evidence]
    return WindowResult(
        interval=None, pillars=deduped, n=n, k_evaluated=k, dependent=dependent, promise=promise,
        result_type=result_type, kp=PillarResult.not_evaluated("KP", "KP not verified; reported separately"),
        badge=badge_text("Natal agreement", n, k), disclaimer=CONVERGENCE_DISCLAIMER,
        notes=tuple(f"{p.pillar}: {p.label}" for p in deduped if p.dependent),
        supportive_evidence=tuple(e for e in evid if e.direction > 0),
        conflicting_evidence=tuple(e for e in evid if e.direction < 0),
        ne_pillars=tuple(p.pillar for p in deduped if p.value == NE), overlay=overlay)
