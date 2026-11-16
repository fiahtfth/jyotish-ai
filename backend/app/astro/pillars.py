"""Four-pillar convergence engine.

Every important timing statement runs through all four traditional
perspectives. Each pillar returns support / conflict / neutral /
unavailable plus the evidence and rule ids that produced it. Rules are
documented heuristics, never probability claims.
"""
from datetime import date, datetime

from jhora.panchanga import drik
from jhora import utils

from . import constants as K
from .engine import BirthInput, engine


def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _mid(d1: date, d2: date) -> date:
    return d1 + (d2 - d1) / 2


def _month_samples(start: date, end: date, step_days=31) -> list[date]:
    pts = []
    cur = start
    while cur <= end:
        pts.append(cur)
        cur = cur.fromordinal(cur.toordinal() + step_days)
    if end not in pts:
        pts.append(end)
    return pts


def _house_of(sign, lagna_sign):
    return (sign - lagna_sign) % 12 + 1


def _lord_of_house(facts, h):
    return facts["houses"][str(h)]["lord"] if str(h) in facts["houses"] else facts["houses"][h]["lord"]


# ---------------------------------------------------------------- pillars

def pillar_parashari(facts, birth: BirthInput, domain: str, start: date, end: date) -> dict:
    """P1 — Vimshottari MD/AD/PD lordship + relevant varga."""
    spec = K.DOMAINS[domain]
    houses = spec["houses"]
    evidence, rules = [], []
    weights = 0
    conflicts = 0

    for t in [start, _mid(start, end), end]:
        run = engine.running_vimshottari(birth, (t.year, t.month, t.day))
        if len(run) < 2:
            continue
        md_lord = run[0]["lords"][0]
        ad_lord = run[1]["lords"][1]
        rules.append(f"dasha@{t}: {md_lord}/{ad_lord}")

        for lord in {md_lord, ad_lord}:
            # lord owns a domain house?
            owned = [h for h in range(1, 13) if facts["houses"][h]["lord"] == lord]
            if any(h in houses for h in owned):
                weights += 1
                hs = "/".join(str(h) for h in sorted(set(owned) & set(houses)))
                evidence.append(f"{lord} rules house {hs} relevant to {domain}")
            # lord sits in a domain house?
            if lord in facts["planets"] and facts["planets"][lord]["house"] in houses:
                weights += 1
                evidence.append(f"{lord} placed in house {facts['planets'][lord]['house']} relevant to {domain}")
            # dignity in the domain varga
            varga = facts["vargas"].get(spec["varga"])
            if varga and lord in varga:
                vsign = varga[lord]["sign"]
                d1sign = facts["planets"][lord]["sign"] if lord in facts["planets"] else None
                if d1sign is not None and vsign == d1sign:
                    evidence.append(f"{lord} vargottama in {spec['varga']}")
                    weights += 1
            # lord of difficult houses for the domain
            dusthana = [h for h in owned if h in (6, 8, 12)]
            if dusthana and lord in facts["functional"]["maraka_lords"]:
                conflicts += 1
                evidence.append(f"{lord} is a maraka lord ({dusthana}) — friction in this domain")
            if lord in facts["planets"] and "debilitated" in facts["planets"][lord]["dignity"]:
                conflicts += 1
                evidence.append(f"{lord} debilitated in D1")

    if weights >= 3:
        verdict = "support"
    elif weights >= 1 and conflicts == 0:
        verdict = "support" if weights >= 2 else "neutral"
    elif conflicts > 0 and weights == 0:
        verdict = "conflict"
    else:
        verdict = "neutral"
    return {"verdict": verdict, "weights": weights, "conflicts": conflicts,
            "evidence": evidence, "rules": rules}


def pillar_jaimini(facts, birth: BirthInput, domain: str, start: date, end: date) -> dict:
    """P2 — Chara dasha sign vs relevant karaka / arudha indicators."""
    spec = K.DOMAINS[domain]
    karaka_name = spec["karaka"]
    evidence, rules = [], []
    karaka_planet = facts["jaimini"]["karakas"].get(karaka_name)
    if not karaka_planet or karaka_planet not in facts["planets"]:
        return {"verdict": "unavailable", "evidence": ["karaka not computed"], "rules": []}
    karaka_sign = facts["planets"][karaka_planet]["sign"]

    arudhas = facts["jaimini"].get("arudhas", {})
    target_signs = {karaka_sign}
    target_labels = {karaka_sign: karaka_name}
    for a_name in spec.get("arudhas", []):
        a_sign = arudhas.get(a_name)
        if a_sign is not None:
            target_signs.add(a_sign)
            target_labels[a_sign] = f"{target_labels.get(a_sign, '')}+{a_name}".lstrip("+")

    mid = _mid(start, end)
    runs = engine.running_chara(birth, (mid.year, mid.month, mid.day))
    if not runs:
        return {"verdict": "unavailable", "evidence": ["chara dasha unavailable"], "rules": []}
    md_sign_name = runs[0]["signs"][0]
    md_sign = K.SIGN_NAMES.index(md_sign_name)
    rules.append(f"chara_dasha@{mid}: {md_sign_name}")

    # Rashi drishti: movable signs aspect all fixed signs except adjacent; fixed
    # aspect all movable except adjacent; dual aspect dual.
    def _aspects(s):
        m = K.SIGN_MODALITY[s]
        if m == "dual":
            return {x for x in range(12) if K.SIGN_MODALITY[x] == "dual" and x != s}
        other = "fixed" if m == "movable" else "movable"
        return {x for x in range(12) if K.SIGN_MODALITY[x] == other and abs(x - s) != 1}

    hits = {s for s in target_signs if s == md_sign or s in _aspects(md_sign)}
    if hits:
        verdict = "support"
        evidence.append(f"Chara dasha of {md_sign_name} touches "
                        f"{', '.join(f'{K.SIGN_NAMES[s]} ({target_labels[s]})' for s in hits)} "
                        f"(karaka={karaka_planet} in {K.SIGN_NAMES[karaka_sign]})")
    else:
        # conflict if dasha sign is 6/8/12 from karaka sign
        dist = _house_of(md_sign, karaka_sign)
        if dist in (6, 8, 12):
            verdict = "conflict"
            evidence.append(f"Chara dasha sign is {dist}th from {karaka_name} sign")
        else:
            verdict = "neutral"
    return {"verdict": verdict, "evidence": evidence, "rules": rules}


def pillar_tajika(facts, birth: BirthInput, domain: str, start: date, end: date) -> dict:
    """P3 — Muntha sign progression for the year(s) covering the window.

    Simplified annual sign progression per spec (full Varshaphala chart is a
    Phase-2+ item); labeled as such in evidence.
    """
    lagna_sign = facts["lagna"]["sign"]
    evidence, rules = [], []
    supports, conflicts = 0, 0
    years_seen = set()
    for t in [start, _mid(start, end), end]:
        completed = t.year - birth.year - ((t.month, t.day) < (birth.month, birth.day))
        if completed < 0:
            continue
        years_seen.add(completed)
    for cy in sorted(years_seen):
        ms = engine.muntha_sign(lagna_sign, cy) - 1  # -> 0-based
        house = _house_of(ms, lagna_sign)
        rules.append(f"muntha year {cy}: {K.SIGN_NAMES[ms]} (house {house})")
        if house in K.DOMAINS[domain]["houses"]:
            supports += 1
            ordn = {1:"1st",2:"2nd",3:"3rd"}.get(house, f"{house}th")
            evidence.append(f"Muntha in {K.SIGN_NAMES[ms]}, the {ordn} house — relevant to {domain}")
        elif house in (6, 8, 12):
            conflicts += 1
            evidence.append(f"Muntha in dusthana (house {house})")
        # Muntha lord's natal dignity qualifies the year's promise
        mlord = K.SIGN_LORD[ms]
        mrec = facts["planets"].get(K.PLANET_NAMES[mlord])
        if mrec:
            dign = mrec.get("dignity", [])
            if "debilitated" in dign:
                conflicts += 1
                evidence.append(f"Muntha lord {K.PLANET_NAMES[mlord]} debilitated in D1 — weakens the year's promise")
            elif any(t in dign for t in ("exalted", "own sign", "moolatrikona")):
                supports += 1
                evidence.append(f"Muntha lord {K.PLANET_NAMES[mlord]} dignified ({'/'.join(dign)}) — strengthens the year")
    verdict = "support" if supports and not conflicts else ("conflict" if conflicts and not supports else "neutral")
    return {"verdict": verdict, "evidence": evidence, "rules": rules,
            "method_note": "simplified Muntha progression, not the full Tajika return chart"}


def pillar_micro_timing(facts, birth: BirthInput, domain: str, start: date, end: date) -> dict:
    """P4 — double transit + fast transits, SAV/BAV bindus, nakshatra sub-period."""
    lagna_sign = facts["lagna"]["sign"]
    spec = K.DOMAINS[domain]
    houses = spec["houses"]
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    evidence, rules = [], []
    supports, conflicts = 0, 0
    months = _month_samples(start, end)
    ju_hits, sa_hits, fast_hits = set(), set(), set()
    for t in months:
        pos = engine.transit_positions((t.year, t.month, t.day), place)
        for name in ("Jupiter", "Saturn"):
            if name not in pos:
                continue
            h = _house_of(pos[name]["sign"], lagna_sign)
            if h in houses:
                (ju_hits if name == "Jupiter" else sa_hits).add((t.year, t.month))
                rules.append(f"transit {name} in house {h} at {t}")
        for name in ("Sun", "Mars"):
            if name in pos:
                h = _house_of(pos[name]["sign"], lagna_sign)
                if h in houses:
                    fast_hits.add(name)
                    rules.append(f"fast transit {name} in house {h} at {t}")
        if "Saturn" in pos:
            moon_house = _house_of(pos["Saturn"]["sign"], facts["planets"]["Moon"]["sign"])
            if moon_house == 8:
                conflicts += 1
                evidence.append("Saturn transiting 8th from natal Moon (ashtama Shani)")
    sav = facts.get("sarvastakavarga")
    if ju_hits and sa_hits:
        supports += 2
        evidence.append(f"Jupiter–Saturn double-transit both touched {domain} houses during window")
    elif ju_hits or sa_hits:
        supports += 1
        who = "Jupiter" if ju_hits else "Saturn"
        evidence.append(f"{who} transited {domain}-relevant houses during the window")
    if fast_hits:
        evidence.append(f"fast transit trigger ({'/'.join(sorted(fast_hits))}) crossing {domain} houses")
        supports += 1
    if sav is not None and supports:
        strong = [K.SIGN_NAMES[s] for s, b in enumerate(sav) if b >= 28 and _house_of(s, lagna_sign) in houses]
        if strong:
            evidence.append(f"SAV ≥28 bindus in {', '.join(strong)}")
    # BAV: the domain karaka's own bindus in domain-house signs (>=4 is strong)
    karaka_planet = facts["jaimini"]["karakas"].get(spec["karaka"])
    bav = facts.get("binnashtakavarga")
    if bav and karaka_planet:
        pid = {v: k for k, v in K.PLANET_NAMES.items()}.get(karaka_planet)
        if pid is not None and pid < len(bav):
            strong_bav = [K.SIGN_NAMES[s] for s in range(12)
                          if bav[pid][s] >= 4 and _house_of(s, lagna_sign) in houses]
            weak_bav = [K.SIGN_NAMES[s] for s in range(12)
                        if bav[pid][s] <= 2 and _house_of(s, lagna_sign) in houses]
            if strong_bav:
                supports += 1
                evidence.append(f"{karaka_planet} BAV ≥4 bindus in {', '.join(strong_bav)}")
            elif weak_bav:
                conflicts += 1
                evidence.append(f"{karaka_planet} BAV thin (≤2 bindus) in {', '.join(weak_bav)}")
    # nakshatra micro-timing: pratyantar (sub-sub) lord at window mid
    mid = _mid(start, end)
    run = engine.running_vimshottari(birth, (mid.year, mid.month, mid.day))
    if len(run) >= 3:
        pd_lord = run[2]["lords"][2]
        prec = facts["planets"].get(pd_lord)
        if prec:
            nak = prec["nakshatra"]
            rules.append(f"sub-period lord {pd_lord}, natal {nak['name']} pada {nak['pada']}")
            owned = [h for h in range(1, 13) if facts["houses"][h]["lord"] == pd_lord]
            if prec["house"] in houses or any(h in houses for h in owned):
                supports += 1
                evidence.append(f"sub-period lord {pd_lord} ({nak['name']} pada {nak['pada']}) "
                                f"activates {domain} houses")
    verdict = "support" if supports >= 2 or (supports and not conflicts) else \
        ("conflict" if conflicts and not supports else "neutral")
    return {"verdict": verdict, "evidence": evidence, "rules": rules}


PILLARS = {"parashari": pillar_parashari, "jaimini": pillar_jaimini,
           "tajika": pillar_tajika, "micro_timing": pillar_micro_timing}


def evaluate(facts, birth: BirthInput, domain: str, start: date, end: date) -> dict:
    """Full four-pillar evaluation for (domain, [start,end]). Spec JSON shape."""
    pillars = {}
    evidence_ids, rule_ids, limitations = [], [], []
    for name, fn in PILLARS.items():
        try:
            r = fn(facts, birth, domain, start, end)
        except Exception as e:
            r = {"verdict": "unavailable", "evidence": [f"{name} pillar error: {e}"], "rules": []}
        pillars[name] = r["verdict"]
        for e in r.get("evidence", []):
            item = f"{name}: {e}"
            if item not in evidence_ids:
                evidence_ids.append(item)
        for r_ in r.get("rules", []):
            item = f"{name}: {r_}"
            if item not in rule_ids:
                rule_ids.append(item)
        if r["verdict"] == "unavailable":
            limitations.append(f"{name} pillar unavailable")
    support = sum(1 for v in pillars.values() if v == "support")
    conflict = sum(1 for v in pillars.values() if v == "conflict")
    unavail = sum(1 for v in pillars.values() if v == "unavailable")
    if support >= 3:
        label = f"{support}/4 Confirmed"
    else:
        label = f"{support}/4 Conditional" + (" — weak signal" if support <= 1 else "")
    if conflict or unavail:
        label += f" ({conflict} conflicting, {unavail} unavailable)"
    return {
        "domain": domain,
        "analysis_window": {"start": start.isoformat(), "end": end.isoformat()},
        "pillars": pillars,
        "support_count": support, "conflict_count": conflict, "unavailable_count": unavail,
        "convergence": label,
        "calculation_evidence_ids": evidence_ids,
        "traditional_rule_ids": rule_ids,
        "limitations": limitations,
    }
