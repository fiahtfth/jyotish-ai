"""Bhava (house) judgement from locked chart facts.

`judge(facts)` returns {house: {score, grade, reasons, ...}} for houses 1..12.
Each reason carries a rule ID; the weights are an app convention (BH.WEIGHTS),
the factors themselves follow the standard bhava-judgement checklist:
lord's placement/dignity/strength, natural karaka, occupants, aspects received,
Ashtakavarga (SAV), the lord in the navamsa, bhava-chalit shifts and Bhava Bala.

Sources: BPHS ch.11-24 (bhava effects), BPHS ch.32 (karakas of houses),
BPHS ch.66-72 (Ashtakavarga), Phaladeepika ch.15 (bhava chinta).
Aspects are Parashari graha drishti (BPHS ch.26); node 5/9 aspects are a
school variant and are not scored.
"""
from __future__ import annotations

from . import constants as K

SOURCE = "BPHS ch.11-24 (bhava phala), ch.32 (bhava karakas); Phaladeepika ch.15"
# BPHS ch.32: natural significators of each house.
HOUSE_KARAKAS = {1: ["Sun"], 2: ["Jupiter"], 3: ["Mars"], 4: ["Moon", "Mercury"],
                 5: ["Jupiter"], 6: ["Mars", "Saturn"], 7: ["Venus"], 8: ["Saturn"],
                 9: ["Jupiter", "Sun"], 10: ["Sun", "Mercury", "Jupiter", "Saturn"],
                 11: ["Jupiter"], 12: ["Saturn"]}
NAT_BENEFICS = {"Moon", "Mercury", "Jupiter", "Venus"}
NAT_MALEFICS = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}
STRONG_DIG = {"exalted", "own sign", "moolatrikona"}
WEIGHTS = "app convention: +/-1 major factors, +/-0.5 minor; grade strong >= 2, weak <= -1"


def bhavat_bhavam(h: int) -> int:
    """The house that is as far from house h as h is from the Lagna."""
    return (2 * (int(h) - 1)) % 12 + 1


def _houses(facts, h):
    hs = facts["houses"]
    return hs[h] if h in hs else hs[str(h)]


def _sign_of(facts, h):
    return (int(facts["lagna"]["sign"]) + h - 1) % 12


def aspects_on(facts, sign: int) -> list[str]:
    p = facts["planets"]
    return sorted(n for n, r in p.items()
                  if int(r["sign"]) != sign and sign in K.parashari_reaches(n, int(r["sign"])))


def _d9_dignity(facts, name):
    d9 = (facts.get("vargas") or {}).get("D9") or {}
    if name not in d9:
        return None, []
    pid = {v: k for k, v in K.PLANET_NAMES.items()}[name]
    s = int(d9[name]["sign"])
    tags = []
    if K.EXALTATION.get(pid, (None,))[0] == s:
        tags.append("exalted")
    if K.DEBILITATION.get(pid, (None,))[0] == s:
        tags.append("debilitated")
    if s in K.OWN_SIGNS.get(pid, []):
        tags.append("own sign")
    return s, tags


def _chalit_shift(facts, h):
    bh = facts.get("bhava") or {}
    p = facts["planets"]
    moved_in = sorted(n for n, b in bh.items() if b == h and p.get(n, {}).get("house") != h)
    moved_out = sorted(n for n, r in p.items() if r["house"] == h and bh.get(n) not in (None, h))
    return {"moved_in": moved_in, "moved_out": moved_out}


def judge_house(facts: dict, h: int) -> dict:
    p = facts["planets"]
    func = facts.get("functional") or {}
    fben, fmal = set(func.get("benefics") or []), set(func.get("malefics") or [])
    strength = facts.get("strength") or {}
    sign = _sign_of(facts, h)
    lord = _houses(facts, h)["lord"]
    lrec = p[lord]
    reasons, score = [], 0.0
    dusthana_house = h in K.DUSTHANA_HOUSES
    upachaya = h in K.UPACHAYA_HOUSES

    def add(rule, pts, text):
        nonlocal score
        score += pts
        reasons.append({"id": rule, "points": pts, "text": text})

    lh = lrec["house"]
    if lh in K.KENDRA_HOUSES | K.TRIKONA_HOUSES:
        add("BH.LORD_KENDRA_TRIKONA", 1, f"lord {lord} in house {lh} (kendra/trikona)")
    elif lh in K.DUSTHANA_HOUSES:
        if dusthana_house:
            add("BH.DUSTHANA_LORD_IN_DUSTHANA", 0.5, f"dusthana lord {lord} in house {lh} (viparita tendency)")
        else:
            add("BH.LORD_DUSTHANA", -1, f"lord {lord} in dusthana {lh}")
    dig = set(lrec.get("dignity") or [])
    if dig & STRONG_DIG:
        add("BH.LORD_STRONG_DIGNITY", 1, f"lord {lord} {', '.join(sorted(dig & STRONG_DIG))}")
    if "debilitated" in dig:
        add("BH.LORD_DEBILITATED", -1, f"lord {lord} debilitated")
    if lrec.get("combust"):
        add("BH.LORD_COMBUST", -0.5, f"lord {lord} combust")
    st = strength.get(lord) or {}
    if st.get("shadbala_ratio") is not None:
        if st["shadbala_ratio"] >= 1.0:
            add("BH.LORD_SHADBALA_OK", 0.5, f"lord {lord} shadbala {st['shadbala_ratio']}x minimum")
        else:
            add("BH.LORD_SHADBALA_LOW", -0.5, f"lord {lord} shadbala {st['shadbala_ratio']}x minimum")

    occupants = sorted(n for n, r in p.items() if r["house"] == h)
    for n in occupants:
        if n in NAT_BENEFICS and not p[n].get("combust"):
            add("BH.BENEFIC_OCCUPANT", 0.5, f"benefic {n} in the house")
        elif n in NAT_MALEFICS and n != lord:
            if upachaya:
                add("BH.MALEFIC_IN_UPACHAYA", 0.5, f"malefic {n} in upachaya house")
            else:
                add("BH.MALEFIC_OCCUPANT", -0.5, f"malefic {n} in the house")
    asp = aspects_on(facts, sign)
    asp_detail = []
    for n in asp:
        nat = "benefic" if n in NAT_BENEFICS else "malefic"
        fn = "benefic" if n in fben else "malefic" if n in fmal else "neutral"
        asp_detail.append({"planet": n, "natural": nat, "functional": fn})
        if n == lord:
            add("BH.LORD_ASPECTS_HOUSE", 0.5, f"lord {lord} aspects its own house")
        elif nat == "benefic":
            add("BH.BENEFIC_ASPECT", 0.5, f"{n} aspects the house")
        elif not upachaya:
            add("BH.MALEFIC_ASPECT", -0.5, f"{n} aspects the house")

    karakas = HOUSE_KARAKAS[h]
    kar_state = {}
    for k in karakas:
        kd = set(p[k].get("dignity") or [])
        kar_state[k] = {"house": p[k]["house"], "dignity": sorted(kd)}
    k0 = p[karakas[0]]
    if set(k0.get("dignity") or []) & STRONG_DIG:
        add("BH.KARAKA_STRONG", 0.5, f"karaka {karakas[0]} in strong dignity")
    elif "debilitated" in (k0.get("dignity") or []):
        add("BH.KARAKA_WEAK", -0.5, f"karaka {karakas[0]} debilitated")
    if karakas[0] in occupants and h not in (1, 10) and len(karakas) == 1:
        reasons.append({"id": "BH.KARAKO_BHAVA_NASHAYA", "points": 0,
                        "text": f"karaka {karakas[0]} occupies its own house (karako bhava nashaya — noted, not scored)"})

    sav = facts.get("sarvastakavarga")
    sav_v = int(sav[sign]) if sav and len(sav) == 12 else None
    if sav_v is not None:
        if sav_v >= 30:
            add("BH.SAV_STRONG", 1, f"SAV {sav_v} bindus")
        elif sav_v < 25:
            add("BH.SAV_WEAK", -1, f"SAV {sav_v} bindus")

    d9_sign, d9_dig = _d9_dignity(facts, lord)
    if "exalted" in d9_dig or "own sign" in d9_dig:
        add("BH.LORD_D9_STRONG", 0.5, f"lord {lord} {d9_dig[0]} in D9")
    if "debilitated" in d9_dig:
        add("BH.LORD_D9_DEBILITATED", -0.5, f"lord {lord} debilitated in D9")

    bb = (facts.get("bhava_bala") or {}).get("ratio")
    bb_v = float(bb[h - 1]) if bb and len(bb) == 12 else None
    if bb_v is not None:
        if bb_v >= 1.0:
            add("BH.BHAVA_BALA_OK", 0.5, f"bhava bala {bb_v}x minimum")
        else:
            add("BH.BHAVA_BALA_LOW", -0.5, f"bhava bala {bb_v}x minimum")

    grade = "strong" if score >= 2 else "weak" if score <= -1 else "moderate"
    return {"house": h, "sign": K.SIGN_NAMES[sign], "lord": lord,
            "lord_placement": {"house": lh, "sign": lrec["sign_name"], "dignity": sorted(dig),
                               "combust": bool(lrec.get("combust")),
                               "strength": st.get("summary")},
            "karakas": kar_state, "occupants": occupants, "aspects_received": asp_detail,
            "sav": sav_v, "lord_in_d9": ({"sign": K.SIGN_NAMES[d9_sign], "dignity": d9_dig}
                                         if d9_sign is not None else None),
            "chalit": _chalit_shift(facts, h), "bhava_bala_ratio": bb_v,
            "bhavat_bhavam": bhavat_bhavam(h),
            "score": round(score, 2), "grade": grade, "reasons": reasons,
            "source": SOURCE, "weights": WEIGHTS}


def judge(facts: dict) -> dict:
    return {h: judge_house(facts, h) for h in range(1, 13)}
