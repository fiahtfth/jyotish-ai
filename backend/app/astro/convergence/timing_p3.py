"""P3 Tajika (Varsha Pravesha annual chart) + Triple Sudarshana, spec 1.4.

One PillarResult per solar-return year overlapping [start, end]. Items:
  2 annual E-lord strong (Pancha-vargiya bala) AND Ithasala with Varsha Lagna lord / Varsheshwara
  3 Muntha: ONLY the intent override (cfg.TAJ.muntha_supportive) is enabled; the generic
    favourable/adverse sets are VERIFY -> disabled -> reported NE with ne_reason
  4 Varsheshwara links (L1-L6, annual chart) to an annual E-house
  5 Mudda periods of planets linked to an annual E-house -> month windows (evidence intervals)
  6 Triple Sudarshana score 0-3 (Lagna, Moon, Sun references)
Annual-chart placements are distinct facts from natal ones, so their factor strings carry a
"VARSHA:" namespace (as natal.py namespaces varga facts). NE without birth time.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from jhora import utils

from .. import constants as K
from .. import precision, varsha
from . import _ivl, links, rulepack
from .promise import resolve_karakas
from .types import A, M, NE, S, W, Evidence, IntentConfig, PillarResult

PILLAR = "P3"
RULE_ELORD = "P3_ANNUAL_ELORD_ITHASALA"
RULE_OVERRIDE = "P3_MUNTHA_INTENT_OVERRIDE"
RULE_GENERIC = "P3_MUNTHA_FAVOURABLE_SETS"       # VERIFY, disabled in the core pack
RULE_VARSHESHWARA = "P3_VARSHESHWARA_LINK"
RULE_MUDDA = "P3_MUDDA_WINDOWS"
RULE_SUDARSHANA = "P3_SUDARSHANA_TRIPLE"
RULE_RESULT = "P3_RESULT"
GENERIC_GOOD = {1, 2, 3, 5, 9, 10, 11}
GENERIC_BAD = {4, 6, 7, 8, 12}
REFS = (("lagna", "Lagna"), ("moon", "Moon"), ("sun", "Sun"))
NO_BIRTH_TIME = "P3 needs an exact birth time (Varsha Lagna, Muntha, Sudarshana are Lagna-based)"


def event_houses(cfg: IntentConfig) -> tuple:
    return tuple(cfg.E or cfg.E_adverse_explicit)


def taj_houses(cfg: IntentConfig) -> tuple:
    """(houses, note). Falls back to cfg.E when cfg.TAJ.houses is empty, and says so."""
    if cfg.TAJ["houses"]:
        return tuple(cfg.TAJ["houses"]), None
    return event_houses(cfg), "TAJ.houses empty: annual houses fall back to the intent's E houses"


def _ev(rule, direction, weight, factors, text, fids=(), interval=None, ne_reason=None):
    return Evidence(rule, rulepack.version(rule), tuple(fids), direction, round(weight, 4),
                    frozenset(factors), interval, text, ne_reason)


def _vns(factors):
    return {f"VARSHA:{f}" for f in factors}


def _annual_facts(v: dict) -> dict:
    """Minimal facts-shaped view of the annual chart so links.py (L1-L6) can run on it."""
    pos = {p: (int(s), float(d)) for p, (s, d) in v["positions"]}
    lagna = pos["L"][0]
    planets = {K.PLANET_NAMES[p]: {"sign": s, "degree": d} for p, (s, d) in pos.items() if p != "L"}
    houses = {h: {"sign": (lagna + h - 1) % 12, "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]}
              for h in range(1, 13)}
    return {"lagna": {"sign": lagna}, "planets": planets, "houses": houses}


def _link_evs(planet, houses, af, rule_note):
    """Annual-chart L1-L6 evidence from the Varsha Lagna only, factors namespaced."""
    out = []
    for e in links.links_to_houses(planet, houses, af, refs=("lagna",), direction=1):
        out.append(Evidence(e.rule_id, e.rule_version, e.fact_ids, 1, e.weight, frozenset(_vns(e.factors)),
                            None, f"{rule_note}: {e.text}"))
    return out


def _year_bounds(birth, cy: int) -> tuple:
    a = _ivl.to_date(utils.jd_to_gregorian(varsha.return_jd(birth, cy))[:3])
    b = _ivl.to_date(utils.jd_to_gregorian(varsha.return_jd(birth, cy + 1))[:3])
    return (a, _ivl.day_before(b))


def _mudda_md_windows(v: dict, year: tuple) -> list:
    """Collapse Mudda MD-AD rows into MD (month-level) windows clipped to the solar-return year."""
    periods = (v.get("mudda") or {}).get("periods") or []
    out = []
    for i, p in enumerate(periods):
        lords = p["lords"]
        s = _ivl.to_date(p["start"])
        e = _ivl.to_date(p["end"]) if p.get("end") else year[1]
        if out and out[-1][0] == lords[0]:
            out[-1][2] = e
        else:
            out.append([lords[0], s, e])
    res = []
    for lord, s, e in out:
        iv = _ivl.overlap((s, e), year)
        if iv:
            res.append((lord, iv))
    return res


def _muntha(v, cfg, strong_lookup):
    """(evidences, supportive, adverse). Only the intent override is enabled."""
    mh = v["muntha"]["house_from_varsha_lagna"]
    evs, supportive, adverse = [], False, False
    msign = v["muntha"]["sign"]
    base = _vns({f"MUNTHA:{msign}", f"HOUSE:{mh}"})
    override = set(cfg.TAJ["muntha_supportive"])
    if mh in override:
        supportive = True
        evs.append(_ev(RULE_OVERRIDE, 1, 1.0, base,
                       f"Muntha in house {mh} from the Varsha Lagna (intent override set {sorted(override)})",
                       [f"varsha.{v['completed_years']}.muntha"]))
    reason = rulepack.ne_reason(RULE_GENERIC)
    if reason:
        evs.append(_ev(RULE_GENERIC, 0, 0.0, base,
                       "generic Muntha favourable/adverse house sets not evaluated", ne_reason=reason))
    else:   # reachable only once a source check enables the rule
        lord = K.PLANET_NAMES[K.SIGN_LORD[msign]]
        strong = strong_lookup(lord)
        if strong is not None:
            if (mh in GENERIC_GOOD or mh in event_houses(cfg)) and strong:
                supportive = True
                evs.append(_ev(RULE_GENERIC, 1, 1.0, base, f"Muntha in house {mh} with strong lord {lord}"))
            elif mh in GENERIC_BAD and not strong:
                adverse = True
                evs.append(_ev(RULE_GENERIC, -1, 1.0, base, f"Muntha in house {mh} with weak lord {lord}"))
    return evs, supportive, adverse


def sudarshana_score(facts: dict, birth, cfg: IntentConfig, when: date) -> tuple:
    """(score 0-3, evidences). Reference signs come from the natal chart; the year sign per
    reference from precision.sudarshana_year_signs. Active if the year sign equals an E house
    from that reference, or contains / is aspected by a D1 E-lord or karaka in K."""
    ys = precision.sudarshana_year_signs(birth, when)
    E = event_houses(cfg)
    planets = []
    for h in E:
        planets.append((links.lord_of(facts, h), f"LORD:H{h}"))
    for k in resolve_karakas(cfg, facts):
        planets.append((k, "KARAKA"))
    refs = {"lagna": facts["lagna"]["sign"], "moon": facts["planets"]["Moon"]["sign"],
            "sun": facts["planets"]["Sun"]["sign"]}
    evs, score = [], 0
    for key, label in REFS:
        y, r = ys[key], refs[key]
        why = [f"year sign is house {h} from {label}" for h in E if (r + h - 1) % 12 == y]
        fac = {f"SUDARSHANA:{key.upper()}:{y}"}
        for p, tag in planets:
            if facts["planets"][p]["sign"] == y:
                why.append(f"{p} ({tag}) in the year sign")
                fac.add(f"PLANET:{p.upper()}")
            elif links.aspects_sign(p, facts, y):
                why.append(f"{p} ({tag}) aspects the year sign")
                fac.add(f"PLANET:{p.upper()}")
        if why:
            score += 1
            evs.append(_ev(RULE_SUDARSHANA, 1, 1.0, fac,
                           f"Sudarshana {label} reference, year sign {K.SIGN_NAMES[y]}: " + "; ".join(why),
                           [f"sudarshana.{key}"]))
    return score, evs


def _year_result(facts, birth, cfg, cy: int) -> PillarResult:
    year = _year_bounds(birth, cy)
    v = varsha.varsha(birth, cy, natal_lagna_sign=facts["lagna"]["sign"])
    houses, taj_note = taj_houses(cfg)
    af = _annual_facts(v)
    vl_sign = af["lagna"]["sign"]
    pvb = v.get("pancha_vargeeya_bala")
    yl = (v.get("year_lord") or {}).get("planet")
    vl_lord = K.PLANET_NAMES[K.SIGN_LORD[vl_sign]]
    evs, met = [], {}

    def strong_of(p):
        return None if not pvb or p not in pvb else pvb[p] > varsha._PVB_THRESHOLD

    # item 2 -------------------------------------------------------------
    ith = [y for y in (v.get("tajika") or {}).get("yogas", []) if y["yoga"] == "Ithasala"]
    item2 = False
    unavailable = []
    if pvb is None:
        unavailable.append("annual E-lord strength (Pancha-vargiya bala unavailable)")
    for h in houses:
        lord = af["houses"][h]["lord"]
        st = strong_of(lord)
        fac = _vns({f"LORD:H{h}", f"PLANET:{lord.upper()}", f"HOUSE:{h}"})
        if st is None:
            continue
        partners = [p for p in dict.fromkeys([vl_lord, yl]) if p and p != lord]
        hit = [y for y in ith if lord in y["planets"] and any(p in y["planets"] for p in partners)]
        if st and hit:
            item2 = True
            y = hit[0]
            other = next(p for p in y["planets"] if p != lord)
            evs.append(_ev(RULE_ELORD, 1, 1.0, fac | _vns({f"PLANET:{other.upper()}"}),
                           f"annual house {h} lord {lord} strong (bala {pvb[lord]}) with {y.get('type', '')} "
                           f"Ithasala to {other}", [f"varsha.{cy}.tajika", f"varsha.{cy}.pancha_vargeeya_bala"]))
        elif not st:
            evs.append(_ev(RULE_ELORD, -1, 0.5, fac,
                           f"annual house {h} lord {lord} weak (bala {pvb[lord]})",
                           [f"varsha.{cy}.pancha_vargeeya_bala"]))
        else:
            evs.append(_ev(RULE_ELORD, 0, 0.0, fac,
                           f"annual house {h} lord {lord} strong but no Ithasala with Varsha Lagna lord "
                           f"{vl_lord} or Varsheshwara {yl}"))
    met[2] = item2
    elord_weak = any(strong_of(af["houses"][h]["lord"]) is False for h in houses) and not item2

    # item 3 -------------------------------------------------------------
    m_evs, m_sup, m_adv = _muntha(v, cfg, strong_of)
    evs += m_evs
    met[3] = m_sup

    # item 4 -------------------------------------------------------------
    item4 = False
    if yl:
        lev = _link_evs(yl, houses, af, f"Varsheshwara {yl}")
        item4 = bool(lev)
        evs += lev
    else:
        unavailable.append("Varsheshwara unavailable")
    met[4] = item4

    # item 5 -------------------------------------------------------------
    item5 = False
    for lord, iv in _mudda_md_windows(v, year):
        lev = _link_evs(lord, houses, af, f"Mudda {lord}")
        if lev:
            item5 = True
            fac = set().union(*(e.factors for e in lev))
            evs.append(_ev(RULE_MUDDA, 1, min(links.weight(lev), 2.0), fac,
                           f"Mudda period of {lord} ({_ivl.fmt(iv)}) links to annual E-house", [f"varsha.{cy}.mudda"], iv))
    met[5] = item5

    # item 6 -------------------------------------------------------------
    sud = 0
    try:
        sud, sev = sudarshana_score(facts, birth, cfg, year[0] + timedelta(days=182))
        evs += sev
    except Exception as exc:           # degrade to unavailable, never guess
        unavailable.append(f"Sudarshana unavailable ({type(exc).__name__})")
    met[6] = sud >= 1

    if item2 and (m_sup or sud >= 2):
        value = S
    elif item2 and m_adv:
        value = M
    elif m_adv and elord_weak and sud == 0:
        value = A
    else:
        value = W            # partial (>=1 of items 2-6) or no activation at all; never counts toward n
    if value == W and not any(met.values()):
        evs.append(_ev(RULE_RESULT, 0, 0.0, set(), "no Tajika item met for this year"))
    if taj_note:
        evs.append(_ev(RULE_RESULT, 0, 0.0, set(), taj_note))
    for u in unavailable:
        evs.append(_ev(RULE_RESULT, 0, 0.0, set(), f"not evaluated: {u}", ne_reason=u))
    evs.append(_ev(RULE_RESULT, 0, 0.0, set(),
                   f"Sudarshana score {sud}/3; items met {sorted(k for k, x in met.items() if x)}"))
    return PillarResult(PILLAR, value, tuple(evs), year)


def evaluate(facts: dict, birth, cfg: IntentConfig, start, end) -> list:
    """One PillarResult per solar-return year overlapping [start, end] (dates)."""
    start, end = _ivl.to_date(start), _ivl.to_date(end)
    if getattr(birth, "birth_time_precision", "exact") == "unknown" or not facts.get("lagna"):
        return [PillarResult.not_evaluated(PILLAR, NO_BIRTH_TIME, (start, end))]
    if not event_houses(cfg):
        return [PillarResult.not_evaluated(PILLAR, "intent has no event houses", (start, end))]
    c0 = max(0, precision.completed_solar_years(birth, start))
    c1 = precision.completed_solar_years(birth, end)
    out = []
    for cy in range(c0, c1 + 1):
        try:
            out.append(_year_result(facts, birth, cfg, cy))
        except Exception as exc:
            out.append(PillarResult.not_evaluated(PILLAR, f"annual chart unavailable for year {cy + 1}: "
                                                          f"{type(exc).__name__}: {exc}"))
    return out or [PillarResult.not_evaluated(PILLAR, "range precedes birth", (start, end))]
