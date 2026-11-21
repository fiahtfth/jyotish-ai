"""Stage-0 natal promise gate (spec 1.3): six factors, each -1/0/+1.

A factor whose input data is absent from `facts` is reported unavailable
(score 0, noted) -- never fabricated. WEAK promise caps the final result at
`weak_indication` (enforced in dedup.converge).
"""
from __future__ import annotations

from .. import constants as K
from .. import yogas as yogas_mod
from . import links
from ._facts import varga_unusable
from .types import (Evidence, IntentConfig, PromiseFactor, PromiseResult, PROMISE_MODERATE, PROMISE_NE,
                    PROMISE_STRONG, PROMISE_WEAK, JAIMINI_KARAKAS)

RULE_VERSION = "1.0"
RULE_F = {"F1": "PROMISE_F1", "F2": "PROMISE_F2", "F3": "PROMISE_F3", "F4": "PROMISE_F4",
          "F5": "PROMISE_F5", "F6": "PROMISE_F6"}
RULE_LEVELS = "PROMISE_LEVELS"
KENDRA_TRIKONA = {1, 4, 5, 7, 9, 10}
DUSTHANA = {6, 8, 12}
GOOD_RELATIONS = {"own", "adhimitra", "friend"}
BAD_RELATIONS = {"enemy", "adhishatru"}
KARAKA_FULL = {"AK": "Atmakaraka", "AmK": "Amatyakaraka", "BK": "Bhratrukaraka", "MK": "Matrukaraka",
               "PK": "Putrakaraka", "GK": "Gnatikaraka", "DK": "Darakaraka"}


def _ev(factor, planet_or_house_factors, direction, text, fids):
    return Evidence(RULE_F[factor], RULE_VERSION, tuple(fids), direction, 1.0,
                    frozenset(planet_or_house_factors), None, text)


def _unavail(name, note):
    return PromiseFactor(name, 0, False, note)


def resolve_karakas(cfg: IntentConfig, facts: dict) -> list:
    """Planet names for cfg.K (natural karakas, Jaimini karakas, LORD:Hn). STRONGEST_LINKED is skipped."""
    out = []
    jk = (facts.get("jaimini") or {}).get("karakas") or {}
    for tok in cfg.K:
        planet = None
        if tok in KARAKA_FULL:
            planet = jk.get(KARAKA_FULL[tok])
        elif tok.startswith("LORD:H"):
            planet = links.lord_of(facts, int(tok[6:]))
        elif tok in facts["planets"]:
            planet = tok
        if planet and planet in facts["planets"] and planet not in out:
            out.append(planet)
    return out


def _ratio(facts, planet):
    """Shadbala ratio vs the BPHS minimum (facts['strength']) for Sun..Saturn; falls back to
    PyJHora's row 8 of facts['shadbala'] when the strength block is absent; None for nodes."""
    st = (facts.get("strength") or {}).get(planet) or {}
    if st.get("shadbala_ratio") is not None:
        return float(st["shadbala_ratio"])
    shad = facts.get("shadbala")
    pid = {v: k for k, v in K.PLANET_NAMES.items()}[planet]
    if shad and len(shad) > 8 and pid < len(shad[8]):
        return float(shad[8][pid])
    return None


def _vimshopaka(facts, planet):
    v = facts.get("vimshopaka")
    return float(v[planet]) if v and planet in v else None


def _neecha_bhanga(facts, planet):
    return any(y.get("planet") == planet for y in yogas_mod.neecha_bhanga(facts))


def _is_strong(facts, planet):
    r, v = _ratio(facts, planet), _vimshopaka(facts, planet)
    if r is None and v is None:
        return None
    return bool((r is not None and r >= 1.0) or (v is not None and v >= 10))


def _f1(facts, lord, h):
    r, v = _ratio(facts, lord), _vimshopaka(facts, lord)
    if r is None and v is None:
        return _unavail("F1_lord_strength", "shadbala/vimshopaka absent")
    fac = {f"PLANET:{lord.upper()}", f"LORD:H{h}"}
    p = facts["planets"][lord]
    score, note = 0, f"{lord}: shadbala ratio {r}, vimshopaka {v}"
    if (r is not None and r >= 1.0) or (v is not None and v >= 10):
        score = 1
    elif r is not None and r < 0.8 and "debilitated" in p["dignity"] and not _neecha_bhanga(facts, lord):
        score = -1
        note += "; debilitated without Neecha Bhanga"
    ev = (_ev("F1", fac, score, note, [f"shadbala.{lord}", f"vimshopaka.{lord}"]),) if score else ()
    return PromiseFactor("F1_lord_strength", score, True, note, ev)


def _f2(facts, lord, h):
    cd = (facts.get("compound_dignity") or {}).get(lord)
    if not cd:
        return _unavail("F2_lord_dignity", "compound_dignity fact absent")
    p = facts["planets"][lord]
    rel = cd.get("relation")
    tags = set(p["dignity"])
    good = bool(tags & {"exalted", "moolatrikona", "own sign"}) or rel in GOOD_RELATIONS
    bad = "debilitated" in tags or rel in BAD_RELATIONS or bool(p.get("combust"))
    score = 1 if good and not bad else (-1 if bad and not good else 0)
    note = f"{lord} dignity {sorted(tags)}, sign-lord relation {rel}, combust={bool(p.get('combust'))}"
    fac = {f"PLANET:{lord.upper()}", f"LORD:H{h}"}
    ev = (_ev("F2", fac, score, note, [f"planets.{lord}.dignity", f"compound_dignity.{lord}"]),) if score else ()
    return PromiseFactor("F2_lord_dignity", score, True, note, ev)


def _f3(facts, h):
    sign = links.house_sign(facts, h)
    occ = [n for n, p in facts["planets"].items() if p["sign"] == sign]
    asp = [n for n in facts["planets"] if links.aspects_sign(n, facts, sign)]
    infl = set(occ) | set(asp)
    ben = bool(infl & {K.PLANET_NAMES[i] for i in K.NATURAL_BENEFICS})
    mal = bool(infl & {K.PLANET_NAMES[i] for i in K.NATURAL_MALEFICS})
    sav = (facts.get("sarvastakavarga") or [None] * 12)[sign]
    plus = ben or (sav is not None and sav >= 28)
    minus = (mal and not ben) or (sav is not None and sav < 25)
    score = 1 if plus and not minus else (-1 if minus and not plus else 0)
    note = f"house {h}: influences {sorted(infl)}, SAV {sav}"
    ev = (_ev("F3", {f"HOUSE:{h}"}, score, note, [f"houses.{h}", "sarvastakavarga"]),) if score else ()
    return PromiseFactor("F3_house_condition", score, True, note, ev)


def _vhouse(facts, varga, planet):
    v = (facts.get("vargas") or {}).get(varga)
    if not v or planet not in v or "Lagna" not in v:
        return None
    return (v[planet]["sign"] - v["Lagna"]["sign"]) % 12 + 1


def _f4(facts, lord, h, varga):
    if not varga:
        return _unavail("F4_varga", "no varga configured")
    gated = varga_unusable(facts, varga)
    if gated:
        return _unavail("F4_varga", gated)
    vh = _vhouse(facts, varga, lord)
    if vh is None:
        return _unavail("F4_varga", f"{varga} not available")
    verdict = 0
    if facts["planets"][lord].get("vargottama") or vh in KENDRA_TRIKONA:
        verdict = 1
    elif vh in DUSTHANA:
        verdict = -1
    note = f"{lord} in house {vh} of {varga}"
    fac = {f"{varga}:PLANET:{lord.upper()}"}
    ev = (_ev("F4", fac, verdict, note, [f"vargas.{varga}.{lord}"]),) if verdict else ()
    return PromiseFactor("F4_varga", verdict, True, note, ev)


def _f5(facts, karakas, varga):
    if not karakas:
        return _unavail("F5_karaka", "no karaka resolvable")
    scores, evs, notes = [], [], []
    for k in karakas:
        p = facts["planets"][k]
        strong = _is_strong(facts, k)
        vh = _vhouse(facts, varga, k) if varga else None
        bad = "debilitated" in p["dignity"] or p.get("combust") or p["house"] in DUSTHANA
        well = p["house"] not in DUSTHANA and (vh is None or vh not in DUSTHANA)
        if bad:
            s = -1
        elif strong and well:
            s = 1
        else:
            s = 0
        scores.append(s)
        notes.append(f"{k}: strong={strong}, D1 house {p['house']}, {varga} house {vh}")
        if s:
            evs.append(_ev("F5", {f"PLANET:{k.upper()}"}, s, notes[-1], [f"planets.{k}"]))
    half = -(-len(karakas) // 2)
    tot = sum(scores)
    score = 1 if tot >= half else (-1 if tot <= -half else 0)
    return PromiseFactor("F5_karaka", score, True, "; ".join(notes), tuple(evs))


_YOGA_PLANETS = {"GAJAKESARI": {"Jupiter", "Moon"}, "BUDHADITYA": {"Sun", "Mercury"}}


def _f6(facts, relevant):
    found = yogas_mod.detect(facts)
    hits = []
    for y in found:
        if y.get("level") != "classical":
            continue
        planets = {y.get(k) for k in ("planet", "lord")} | set(y.get("planets") or ())
        planets |= _YOGA_PLANETS.get(y["id"].split(".")[0], set())
        if planets & relevant:
            hits.append(y)
    ev = tuple(_ev("F6", {f"PLANET:{p.upper()}" for p in (set([y.get("planet")]) - {None})} or {f"YOGA:{y['id']}"},
                   1, f"{y['name']} (classical conditions met)", [f"yogas.{y['id']}"]) for y in hits)
    note = "supportive classical yoga: " + ", ".join(y["name"] for y in hits) if hits \
        else "no relevant classical yoga; no denial combinations enabled in rule pack"
    return PromiseFactor("F6_yogas", 1 if hits else 0, True, note, ev)


def promise_gate(facts: dict, cfg: IntentConfig) -> PromiseResult:
    """Score the natal promise for cfg's primary event house."""
    h = cfg.primary_house
    if h is None:
        names = ("F1_lord_strength", "F2_lord_dignity", "F3_house_condition", "F4_varga", "F5_karaka", "F6_yogas")
        fs = tuple(_unavail(n, "intent has no event houses") for n in names)
        return PromiseResult(PROMISE_NE, 0, fs, (), tuple(f.name for f in fs))
    lord = links.lord_of(facts, h)
    karakas = resolve_karakas(cfg, facts)
    varga = cfg.primary_varga
    factors = (_f1(facts, lord, h), _f2(facts, lord, h), _f3(facts, h), _f4(facts, lord, h, varga),
               _f5(facts, karakas, varga), _f6(facts, {lord, *karakas}))
    score = sum(f.score for f in factors)
    unavailable = tuple(f.name for f in factors if not f.available)
    if all(not f.available for f in factors):
        level = PROMISE_NE
    elif score >= 3:
        level = PROMISE_STRONG
    elif score >= 0:
        level = PROMISE_MODERATE
    else:
        level = PROMISE_WEAK
    evidence = tuple(e for f in factors for e in f.evidence)
    return PromiseResult(level, score, factors, evidence, unavailable)
