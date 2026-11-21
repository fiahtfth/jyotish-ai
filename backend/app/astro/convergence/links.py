"""Planet-to-house links L1-L6 (spec 1.4), ADV houses and weighted aggregation.

Counted from Lagna (weight 1.0) and Moon (weight 0.5). Each link type is a
separate Evidence item carrying the factor strings used for de-duplication.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .. import constants as K
from .types import Evidence

RULE_L = {"L1": "LINK_L1", "L2": "LINK_L2", "L3": "LINK_L3", "L4": "LINK_L4", "L5": "LINK_L5", "L6": "LINK_L6"}
RULE_ADV = "ADV_HOUSES"
RULE_BALANCE = "LINK_BALANCE"
RULE_VERSION = "1.0"
# Base weight per link type (spec is silent; fixed here and recorded in the rule pack).
LINK_WEIGHTS = {"L1": 1.0, "L2": 1.0, "L3": 0.75, "L4": 0.5, "L5": 0.5, "L6": 0.25}
REF_WEIGHT = {"lagna": 1.0, "moon": 0.5}
_PID = {n: i for i, n in K.PLANET_NAMES.items()}


def ref_sign(facts: dict, ref: str) -> int:
    if ref == "lagna":
        return facts["lagna"]["sign"]
    if ref == "moon":
        return facts["planets"]["Moon"]["sign"]
    raise ValueError(f"unknown reference {ref!r}")


def house_sign(facts: dict, house: int, ref: str = "lagna") -> int:
    return (ref_sign(facts, ref) + house - 1) % 12


def house_of_sign(sign: int, facts: dict, ref: str = "lagna") -> int:
    return (sign - ref_sign(facts, ref)) % 12 + 1


def lord_of(facts: dict, house: int, ref: str = "lagna") -> str:
    return K.PLANET_NAMES[K.SIGN_LORD[house_sign(facts, house, ref)]]


def adv(E: Iterable[int], extra: Iterable[int] = ()) -> tuple:
    """ADV = 12th from each house in E (computed, never hand-listed); E members are excluded.
    `extra` adds an intent's explicit adverse houses (IntentConfig.E_adverse_explicit)."""
    e = set(E)
    out = {((h - 2) % 12) + 1 for h in e} | set(extra)
    return tuple(sorted(out - e))


def aspects_sign(planet: str, facts: dict, sign: int) -> bool:
    """Graha drishti onto `sign` (the planet's own sign is not an aspect)."""
    psign = facts["planets"][planet]["sign"]
    return sign != psign and sign in K.reaches(planet, psign)


def _ev(lt, planet, house, ref, factors, fids, text, direction=1, extra_w=1.0):
    pre = "" if ref == "lagna" else "MOON_"
    fac = {f"PLANET:{planet.upper()}", *factors}
    return Evidence(RULE_L[lt], RULE_VERSION, tuple(fids), direction,
                    round(LINK_WEIGHTS[lt] * REF_WEIGHT[ref] * extra_w, 4), frozenset(fac), None, text)


def link_evidence(planet: str, house: int, facts: dict, ref: str = "lagna", direction: int = 1) -> list:
    """All L1-L6 links of `planet` to `house` counted from `ref` ('lagna' | 'moon')."""
    if planet not in facts["planets"]:
        return []
    pre = "" if ref == "lagna" else "MOON_"
    hs = house_sign(facts, house, ref)
    lord = lord_of(facts, house, ref)
    p = facts["planets"][planet]
    psign = p["sign"]
    HOUSE, LORD = f"{pre}HOUSE:{house}", f"{pre}LORD:H{house}"
    where = "Lagna" if ref == "lagna" else "Moon"
    out = []
    pf = [f"planets.{planet}.sign"]
    if planet == lord:
        out.append(_ev("L1", planet, house, ref, {HOUSE, LORD}, pf + [f"houses.{house}.lord"],
                       f"{planet} lords house {house} from {where}", direction))
    if psign == hs:
        out.append(_ev("L2", planet, house, ref, {HOUSE}, pf,
                       f"{planet} occupies house {house} from {where}", direction))
    if aspects_sign(planet, facts, hs):
        out.append(_ev("L3", planet, house, ref, {HOUSE}, pf,
                       f"{planet} aspects house {house} from {where}", direction))
    if lord != planet and lord in facts["planets"]:
        lsign = facts["planets"][lord]["sign"]
        if lsign == psign or aspects_sign(planet, facts, lsign):
            out.append(_ev("L4", planet, house, ref, {HOUSE, LORD, f"PLANET:{lord.upper()}"},
                           pf + [f"planets.{lord}.sign"],
                           f"{planet} is conjunct with or aspects {lord}, lord of house {house} from {where}", direction))
    nl = (p.get("nakshatra") or {}).get("lord")
    if nl and nl in facts["planets"]:
        if nl == lord or facts["planets"][nl]["sign"] == hs:
            out.append(_ev("L5", planet, house, ref, {HOUSE, f"PLANET:{nl.upper()}"},
                           pf + [f"planets.{planet}.nakshatra"],
                           f"{planet}'s nakshatra lord {nl} lords or occupies house {house} from {where}", direction))
    if K.PLANET_NAMES[K.SIGN_LORD[psign]] == lord and planet != lord:
        out.append(_ev("L6", planet, house, ref, {HOUSE, LORD}, pf,
                       f"{planet} occupies a sign owned by {lord}, lord of house {house} from {where}", direction))
    return out


def links_to_houses(planet: str, houses: Iterable[int], facts: dict, refs=("lagna", "moon"), direction=1) -> list:
    out = []
    for ref in refs:
        for h in houses:
            out.extend(link_evidence(planet, h, facts, ref, direction))
    return out


def links_to_E(planet: str, E: Iterable[int], facts: dict, refs=("lagna", "moon")) -> list:
    """Supportive (+1) Evidence for links to event houses E."""
    return links_to_houses(planet, E, facts, refs, +1)


def links_to_ADV(planet: str, E: Iterable[int], facts: dict, refs=("lagna", "moon"), extra_adv=()) -> list:
    """Adverse (-1) Evidence for links to ADV = 12th-from-each-E houses (+ explicit adverse houses)."""
    return links_to_houses(planet, adv(E, extra_adv), facts, refs, -1)


def weight(evs: Iterable[Evidence]) -> float:
    return round(sum(e.weight for e in evs), 4)


def link_balance(planet: str, E: Iterable[int], facts: dict, refs=("lagna", "moon"), extra_adv=()) -> dict:
    """Weighted E-links vs ADV-links; `adverse_dominates` when ADV outweighs E (spec P1 item 5)."""
    e_ev, a_ev = links_to_E(planet, E, facts, refs), links_to_ADV(planet, E, facts, refs, extra_adv)
    ew, aw = weight(e_ev), weight(a_ev)
    return {"E": e_ev, "ADV": a_ev, "E_weight": ew, "ADV_weight": aw,
            "activates": ew > 0, "adverse_dominates": aw > ew}
