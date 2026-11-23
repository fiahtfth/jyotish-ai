"""Core method: one transparent classical Parashari reading (promise -> period -> trigger).

docs/SIMPLIFICATION_PLAN.md Phase 1. Every output traces to fact IDs (dotted paths
into the locked chart facts, e.g. "planets.Saturn.dignity", "houses.10.lord";
transit facts are "transit.<planet>.<YYYY-MM>") and to rule IDs in
backend/data/rulepack/core_method.json (house judgement reuses bhava.py's BH.*
rules and dasha_craft's DC.AD_FROM_MD.*).

Steps
- promise(): topic primary house, its lord and the topic karakas, judged from the
  Lagna (weight 1) and the Moon (weight 0.5); Moon only when the birth time is unknown.
- periods(): Vimshottari AD (and PD) intervals whose lords link to the topic houses.
- triggers(): months where transiting Saturn AND Jupiter both occupy/aspect the
  primary house or its lord's sign (K.N. Rao double transit).
- answer(): the Card (verdict, window, confidence, <=2 reasons, one action line).

Weights and thresholds are app conventions (recorded in the rule pack), not
classical numbers. No probabilities are produced anywhere.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import bhava, dasha_craft
from . import constants as K
from . import vimshottari as V

TOPICS_PATH = Path(__file__).resolve().parents[2] / "data" / "topics.json"
PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
VARGAS = {"D1", "D2", "D3", "D4", "D7", "D9", "D10", "D12", "D16", "D20", "D24", "D30", "D60"}
SAFETY_DOMAINS = ("career", "marriage_relationship", "finance", "education", "foreign", "property",
                  "children_family", "wellbeing", "personality_spiritual", "general")
STRONG_DIG = {"exalted", "own sign", "moolatrikona"}
NODES = ("Rahu", "Ketu")
PAST_YEARS = 15

# Promise grade thresholds on the combined score (app convention, CORE.PROMISE).
PROMISE_STRONG_AT = 3.0
PROMISE_WEAK_BELOW = 1.0
REF_WEIGHT = {"lagna": 1.0, "moon": 0.5}

# Selectivity targets (firing-rate bands, measured by tests/test_core_selectivity.py
# over random charts). A method that says "strong"/"likely" for almost every chart
# carries no information; these bands keep the engine honest while being tuned.
TUNING = {
    "targets": {
        "promise_strong_max": 0.35,
        "promise_weak_min": 0.20,
        "likely_max": 0.50,
        "likely_topic_max": 0.60,
        "likely_day_share_max": 0.15,
        "likely_window_days_mean_max": 90,
        "confidence_high_max": 0.25,
    },
}


class TopicError(ValueError):
    pass


# ------------------------------------------------------------------ topics

def validate_topics(data: dict) -> dict:
    """Raise TopicError unless every topic is complete and consistent; returns the topics dict."""
    if not isinstance(data, dict) or not isinstance(data.get("topics"), dict) or not data["topics"]:
        raise TopicError("topics.json: expected {'topics': {id: {...}}}")
    keys = {"label", "houses", "karakas", "varga", "safety_domain", "timing", "questions"}
    for tid, t in data["topics"].items():
        if not isinstance(t, dict):
            raise TopicError(f"{tid}: must be an object")
        missing, unknown = keys - set(t), set(t) - keys
        if missing or unknown:
            raise TopicError(f"{tid}: missing {sorted(missing)} unknown {sorted(unknown)}")
        lab = t["label"]
        if not isinstance(lab, dict) or not all(isinstance(lab.get(k), str) and lab[k] for k in ("en", "hi")):
            raise TopicError(f"{tid}: label needs non-empty en and hi")
        hs = t["houses"]
        if (not isinstance(hs, list) or not hs or len(set(hs)) != len(hs)
                or not all(isinstance(h, int) and 1 <= h <= 12 for h in hs)):
            raise TopicError(f"{tid}: houses must be unique integers 1..12, primary first")
        if not isinstance(t["karakas"], list) or not t["karakas"] or not set(t["karakas"]) <= set(PLANETS):
            raise TopicError(f"{tid}: karakas must be planet names")
        if t["varga"] not in VARGAS:
            raise TopicError(f"{tid}: unknown varga {t['varga']!r}")
        if t["safety_domain"] not in SAFETY_DOMAINS:
            raise TopicError(f"{tid}: unknown safety_domain {t['safety_domain']!r}")
        if not isinstance(t["timing"], bool):
            raise TopicError(f"{tid}: timing must be true/false")
        if t["safety_domain"] == "wellbeing" and t["timing"]:
            raise TopicError(f"{tid}: wellbeing is a theme only and must not be timed")
        qs = t["questions"]
        if not isinstance(qs, list) or len(qs) < 3 or not all(isinstance(q, str) and q.strip() for q in qs):
            raise TopicError(f"{tid}: at least 3 sample question phrases required")
    return data["topics"]


@lru_cache(maxsize=1)
def load_topics() -> dict:
    return validate_topics(json.loads(TOPICS_PATH.read_text(encoding="utf-8")))


def topic(topic_id: str) -> dict:
    t = load_topics().get(topic_id)
    if t is None:
        raise TopicError(f"unknown topic {topic_id!r}")
    return t


def topics_list() -> list:
    return [{"id": tid, **t} for tid, t in load_topics().items()]


# ------------------------------------------------------------------ small helpers

def _ord(n: int) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _lord_of_sign(sign: int) -> str:
    return K.PLANET_NAMES[K.SIGN_LORD[int(sign) % 12]]


def _ref_sign(facts: dict, ref: str) -> int:
    return int(facts["lagna"]["sign"]) if ref == "lagna" else int(facts["planets"]["Moon"]["sign"])


def _house_sign(facts: dict, h: int, ref: str) -> int:
    return (_ref_sign(facts, ref) + int(h) - 1) % 12


def _aspects(planet: str, from_sign: int, sign: int) -> bool:
    return int(from_sign) != int(sign) and int(sign) in K.parashari_reaches(planet, int(from_sign))


def _area(t: dict) -> str:
    return t["label"]["en"].lower()


def _time_known(birth, time_known: Optional[bool] = None) -> bool:
    if time_known is not None:
        return bool(time_known)
    return getattr(birth, "birth_time_precision", "exact") != "unknown"


def _varga_ok(facts: dict, v: str, time_known: bool) -> bool:
    if v == "D1":
        return True
    return time_known and (facts.get("varga_reliability") or {}).get(v) == "reliable" \
        and v in (facts.get("vargas") or {})


def _view(facts: dict, ref: str, time_known: bool) -> dict:
    """Facts as seen from `ref` for bhava.judge_house. Moon view: houses re-counted from the
    Moon sign, no Lagna-only data (bhava bala, chalit). Time-sensitive data dropped when unknown."""
    v = dict(facts)
    if not _varga_ok(facts, "D9", time_known):
        v["vargas"] = {k: c for k, c in (facts.get("vargas") or {}).items() if k != "D9"}
    if not time_known:
        v["strength"] = {}
        v["bhava_bala"] = None
    if ref == "lagna":
        return v
    ms = int(facts["planets"]["Moon"]["sign"])
    v["planets"] = {n: {**r, "house": K.house_from(r["sign"], ms)} for n, r in facts["planets"].items()}
    v["lagna"] = {"sign": ms, "sign_name": K.SIGN_NAMES[ms], "lord": _lord_of_sign(ms)}
    v["houses"] = {h: {"sign": (ms + h - 1) % 12, "sign_name": K.SIGN_NAMES[(ms + h - 1) % 12],
                       "lord": _lord_of_sign(ms + h - 1)} for h in range(1, 13)}
    v["bhava_bala"] = None
    v["bhava"] = {}
    return v


def _planet_in(text: str) -> Optional[str]:
    for n in PLANETS:
        if n in text.split() or f"{n}," in text or text.startswith(n):
            return n
    return None


# ------------------------------------------------------------------ promise

def _explain(r: dict, jh: dict, h: int, ref: str, area: str, sign: int) -> tuple[str, list]:
    """Plain-language text and fact IDs for one bhava.py reason."""
    rid, lord = r["id"], jh["lord"]
    lp = jh["lord_placement"]
    rp = "" if ref == "lagna" else " (counted from your Moon sign)"
    base = "lagna.sign" if ref == "lagna" else "planets.Moon.sign"
    lord_pos = ([f"houses.{h}.lord", f"planets.{lord}.house"] if ref == "lagna"
                else [base, f"planets.{lord}.sign"])
    who = f"{lord}, ruler of your {_ord(h)} house of {area}"
    n = _planet_in(r["text"].replace("lord " + lord, "").replace("karaka ", "")) or lord

    def occ(p):
        return [f"planets.{p}.house"] if ref == "lagna" else [base, f"planets.{p}.sign"]

    table = {
        "BH.LORD_KENDRA_TRIKONA": (f"{who}, sits in the {_ord(lp['house'])} house, a strong and supportive "
                                   f"position{rp}.", lord_pos),
        "BH.LORD_DUSTHANA": (f"{who}, sits in the {_ord(lp['house'])} house, a difficult position that tends "
                             f"to slow results{rp}.", lord_pos),
        "BH.DUSTHANA_LORD_IN_DUSTHANA": (f"{who}, sits in the {_ord(lp['house'])} house; this reversal pattern "
                                         f"(Viparita) can turn obstacles into gains{rp}.", lord_pos),
        "BH.LORD_STRONG_DIGNITY": (f"{who}, is in a sign where it is at its best "
                                   f"({', '.join(sorted(set(lp['dignity']) & STRONG_DIG))}).",
                                   [f"planets.{lord}.dignity"]),
        "BH.LORD_DEBILITATED": (f"{who}, is in its weakest sign (debilitated).", [f"planets.{lord}.dignity"]),
        "BH.LORD_COMBUST": (f"{who}, is too close to the Sun (combust), which weakens it.",
                            [f"planets.{lord}.combust"]),
        "BH.LORD_SHADBALA_OK": (f"{lord}, ruler of your {area} house, has enough overall strength "
                                "(Shadbala at or above the classical minimum).", [f"strength.{lord}.shadbala_ratio"]),
        "BH.LORD_SHADBALA_LOW": (f"{lord}, ruler of your {area} house, has less overall strength than the "
                                 "classical minimum (Shadbala).", [f"strength.{lord}.shadbala_ratio"]),
        "BH.BENEFIC_OCCUPANT": (f"{n}, a helpful planet, sits in your {_ord(h)} house{rp}.", occ(n)),
        "BH.MALEFIC_IN_UPACHAYA": (f"{n} sits in your {_ord(h)} house; in this growth house a tough planet "
                                   f"helps through steady effort{rp}.", occ(n)),
        "BH.MALEFIC_OCCUPANT": (f"{n}, a tough planet, sits in your {_ord(h)} house and can add pressure{rp}.",
                                occ(n)),
        "BH.LORD_ASPECTS_HOUSE": (f"{lord} looks back at its own {_ord(h)} house and protects it{rp}.",
                                  [base, f"planets.{lord}.sign"]),
        "BH.BENEFIC_ASPECT": (f"{n}, a helpful planet, looks at your {_ord(h)} house{rp}.",
                              [base, f"planets.{n}.sign"]),
        "BH.MALEFIC_ASPECT": (f"{n}, a tough planet, looks at your {_ord(h)} house{rp}.",
                              [base, f"planets.{n}.sign"]),
        "BH.KARAKA_STRONG": (f"{n}, the natural indicator of your {_ord(h)} house, is in a strong sign.",
                             [f"planets.{n}.dignity"]),
        "BH.KARAKA_WEAK": (f"{n}, the natural indicator of your {_ord(h)} house, is in its weakest sign.",
                           [f"planets.{n}.dignity"]),
        "BH.SAV_STRONG": (f"Your {_ord(h)} house has {jh['sav']} Ashtakavarga points, above average, so it is "
                          f"well supported{rp}.", [f"sarvastakavarga.{sign}"]),
        "BH.SAV_WEAK": (f"Your {_ord(h)} house has only {jh['sav']} Ashtakavarga points, below average{rp}.",
                        [f"sarvastakavarga.{sign}"]),
        "BH.LORD_D9_STRONG": (f"{lord} is also strong in the Navamsa (D9) chart.", [f"vargas.D9.{lord}.sign"]),
        "BH.LORD_D9_DEBILITATED": (f"{lord} is weak in the Navamsa (D9) chart.", [f"vargas.D9.{lord}.sign"]),
        "BH.BHAVA_BALA_OK": (f"The {_ord(h)} house itself has enough strength (Bhava Bala).",
                             [f"bhava_bala.ratio.{h - 1}"]),
        "BH.BHAVA_BALA_LOW": (f"The {_ord(h)} house itself has low strength (Bhava Bala).",
                              [f"bhava_bala.ratio.{h - 1}"]),
    }
    if rid in table:
        return table[rid]
    return r["text"], [base]


def _role_points(roles: list) -> tuple[float, str]:
    if "yogakaraka" in roles:
        return 1.0, "is the yogakaraka for your Ascendant, the most helpful planet in your chart"
    if "lagna_lord" in roles:
        return 0.5, "also rules your Ascendant, which keeps it on your side"
    if "benefic_by_lordship" in roles:
        return 0.5, "is a helpful planet for your Ascendant (by the houses it rules)"
    if "malefic_by_lordship" in roles:
        return -0.5, "is a less helpful planet for your Ascendant (by the houses it rules)"
    return 0.0, ""


def _varga_dignity(facts: dict, v: str, name: str) -> list:
    rec = ((facts.get("vargas") or {}).get(v) or {}).get(name)
    if not rec or name in NODES:
        return []
    pid = {n: i for i, n in K.PLANET_NAMES.items()}[name]
    s = int(rec["sign"])
    tags = []
    if K.EXALTATION.get(pid, (None,))[0] == s:
        tags.append("exalted")
    if s in K.OWN_SIGNS.get(pid, []):
        tags.append("own sign")
    if K.DEBILITATION.get(pid, (None,))[0] == s:
        tags.append("debilitated")
    return tags


def _relevant_yogas(facts: dict, t: dict, lord: str) -> list:
    out = []
    for y in facts.get("yogas") or []:
        if y.get("status") != "active":
            continue
        hs = set(y.get("houses") or [])
        parts = set(y.get("participants") or y.get("planets") or [])
        if hs & set(t["houses"]) or lord in parts:
            out.append(y)
    return out


def promise(facts: dict, topic_id: str, *, time_known: bool = True) -> dict:
    """Natal promise for a topic: {grade, score, reasons[<=3 {text, fact_ids, rule_id, points}], rule_ids, details}."""
    t = topic(topic_id)
    h = t["houses"][0]
    area = _area(t)
    refs = ("lagna", "moon") if time_known else ("moon",)
    items, judged = [], {}
    for ref in refs:
        view = _view(facts, ref, time_known)
        jh = bhava.judge_house(view, h)
        judged[ref] = jh
        w = REF_WEIGHT[ref] / sum(REF_WEIGHT[r] for r in refs)
        sign = _house_sign(facts, h, ref)
        for r in jh["reasons"]:
            if not r["points"]:
                continue
            text, fids = _explain(r, jh, h, ref, area, sign)
            items.append({"text": text, "fact_ids": fids, "rule_id": r["id"], "ref": ref,
                          "points": round(r["points"] * w, 3)})
    base = round(sum(i["points"] for i in items), 3)
    lord = judged[refs[0]]["lord"]
    extras = []

    # functional role of the house lord (Lagna-based; BPHS ch.34)
    if time_known:
        roles = ((facts.get("functional") or {}).get("roles") or {}).get(lord) or []
        pts, why = _role_points(roles)
        if pts:
            extras.append({"text": f"{lord}, ruler of your {_ord(h)} house, {why}.",
                           "fact_ids": [f"functional.roles.{lord}"], "rule_id": "CORE.FUNC_ROLE",
                           "ref": "lagna", "points": pts})
    # compound dignity of the lord (sign-based, reference-independent)
    lord_dig = set(facts["planets"][lord].get("dignity") or [])
    rel = ((facts.get("compound_dignity") or {}).get(lord) or {}).get("relation")
    if not lord_dig & (STRONG_DIG | {"debilitated"}) and rel in ("adhimitra", "friend", "enemy", "adhishatru"):
        good = rel in ("adhimitra", "friend")
        extras.append({"text": f"{lord} sits in a {'friendly' if good else 'unfriendly'} sign "
                               f"({'comfortable' if good else 'uncomfortable'} there).",
                       "fact_ids": [f"compound_dignity.{lord}.relation"], "rule_id": "CORE.LORD_COMPOUND",
                       "ref": "sign", "points": 0.5 if good else -0.5})
    # topic karakas not already scored by bhava.py (its first house karaka)
    scored = bhava.HOUSE_KARAKAS[h][0]
    for k in [k for k in t["karakas"] if k != scored and k not in NODES][:2]:
        st = (facts.get("strength") or {}).get(k) if time_known else None
        dig = set(facts["planets"][k].get("dignity") or [])
        if st and st.get("summary") in ("strong", "weak"):
            good = st["summary"] == "strong"
            fid, how = f"strength.{k}.summary", "overall strength"
        elif dig & STRONG_DIG or "debilitated" in dig:
            good = bool(dig & STRONG_DIG)
            fid, how = f"planets.{k}.dignity", "sign placement"
        else:
            continue
        extras.append({"text": f"{k}, the natural indicator of {area}, is {'strong' if good else 'weak'} "
                               f"({how}).", "fact_ids": [fid], "rule_id": "CORE.KARAKA",
                       "ref": "sign", "points": 0.5 if good else -0.5})
    # active yogas tied to the topic (Lagna-based)
    if time_known:
        yp = 0.0
        for y in _relevant_yogas(facts, t, lord):
            if yp >= 1.0:
                break
            yp += 0.5
            extras.append({"text": f"{y.get('name', y['id'])} is active in your chart and supports {area}.",
                           "fact_ids": [f"yogas.{y['id']}"], "rule_id": "CORE.YOGA",
                           "ref": "lagna", "points": 0.5})
    # divisional-chart confirmation, only when that chart is reliable for this birth time
    v = t["varga"]
    varga_note = None
    if v not in ("D1", "D9"):
        if _varga_ok(facts, v, time_known):
            tags = _varga_dignity(facts, v, lord)
            if set(tags) & STRONG_DIG or "debilitated" in tags:
                good = bool(set(tags) & STRONG_DIG)
                extras.append({"text": f"In the {v} chart for {area}, {lord} is "
                                       f"{'strong (' + ', '.join(tags) + ')' if good else 'weak (debilitated)'}.",
                               "fact_ids": [f"vargas.{v}.{lord}.sign", f"varga_reliability.{v}"],
                               "rule_id": "CORE.VARGA_CONFIRM", "ref": v, "points": 0.5 if good else -0.5})
            varga_note = f"{v} used"
        else:
            varga_note = f"{v} not used: not reliable for this birth time"
    score = round(base + sum(e["points"] for e in extras), 2)
    grade = "strong" if score >= PROMISE_STRONG_AT else "weak" if score < PROMISE_WEAK_BELOW else "moderate"
    all_items = items + extras
    reasons = _pick_reasons(all_items, grade, 3)
    rule_ids = ["CORE.PROMISE"] + (["CORE.PROMISE_MOON"] if "moon" in refs else []) \
        + sorted({i["rule_id"] for i in all_items})
    return {"topic": topic_id, "grade": grade, "score": score, "reasons": reasons, "rule_ids": rule_ids,
            "details": {"house": h, "lord": lord, "refs": list(refs), "base": base, "time_known": time_known,
                        "factors": all_items, "varga": varga_note,
                        "house_judgement": {r: {"score": j["score"], "grade": j["grade"], "sign": j["sign"],
                                                "lord": j["lord"]} for r, j in judged.items()}}}


def _pick_reasons(items: list, grade: str, n: int) -> list:
    seen, uniq = set(), []
    for i in sorted(items, key=lambda i: -abs(i["points"])):
        if i["text"] in seen:
            continue
        seen.add(i["text"])
        uniq.append(i)
    pos = [i for i in uniq if i["points"] > 0]
    neg = [i for i in uniq if i["points"] < 0]
    if grade == "strong":
        out = pos[:n]
    elif grade == "weak":
        out = neg[:n]
    else:
        out = pos[:n - 1] + neg[:1]
    out = out or uniq[:n]
    return [{k: i[k] for k in ("text", "fact_ids", "rule_id", "points")} for i in out[:n]]


# ------------------------------------------------------------------ periods

# Link weights per type (app convention, CORE.PERIOD_LINK); primary house counts more.
_LINK_W = {"owns": (3.0, 2.0), "occupies": (3.0, 2.0), "aspects": (1.5, 1.0),
           "conjunct_lord": (1.0, 0.5), "star_lord": (1.0, 0.5), "dispositor": (1.0, 0.5)}


def planet_links(facts: dict, planet: str, t: dict, time_known: bool = True) -> dict:
    """How `planet` links to the topic houses: {score, strength, reasons[{text, fact_ids}]}."""
    p = facts["planets"]
    rec = p[planet]
    psign = int(rec["sign"])
    refs = ("lagna", "moon") if time_known else ("moon",)
    score, reasons = 0.0, []
    for ref in refs:
        rw = REF_WEIGHT[ref] if time_known else 1.0
        base = "lagna.sign" if ref == "lagna" else "planets.Moon.sign"
        rp = "" if ref == "lagna" else " from your Moon sign"
        for i, h in enumerate(t["houses"]):
            hs = _house_sign(facts, h, ref)
            lord = _lord_of_sign(hs)
            found = []
            if planet == lord:
                found.append(("owns", f"{planet} rules your {_ord(h)} house{rp}",
                              [f"houses.{h}.lord"] if ref == "lagna" else [base]))
            if psign == hs:
                found.append(("occupies", f"{planet} sits in your {_ord(h)} house{rp}",
                              [f"planets.{planet}.sign", base]))
            elif _aspects(planet, psign, hs):
                found.append(("aspects", f"{planet} looks at your {_ord(h)} house{rp}",
                              [f"planets.{planet}.sign", base]))
            if planet != lord and int(p[lord]["sign"]) == psign:
                found.append(("conjunct_lord", f"{planet} sits with {lord}, ruler of your {_ord(h)} house{rp}",
                              [f"planets.{planet}.sign", f"planets.{lord}.sign"]))
            nl = (rec.get("nakshatra") or {}).get("lord")
            if nl and nl != planet and nl in p and (nl == lord or int(p[nl]["sign"]) == hs):
                found.append(("star_lord", f"{planet} sits in a nakshatra ruled by {nl}, which "
                                           f"{'rules' if nl == lord else 'occupies'} your {_ord(h)} house{rp}",
                              [f"planets.{planet}.nakshatra", f"planets.{nl}.sign"]))
            if planet in NODES:
                disp = _lord_of_sign(psign)
                if disp == lord or int(p[disp]["sign"]) == hs:
                    found.append(("dispositor", f"{planet} acts for {disp}, which "
                                                f"{'rules' if disp == lord else 'occupies'} your {_ord(h)} house{rp}",
                                  [f"planets.{planet}.sign", f"planets.{disp}.sign"]))
            for kind, text, fids in found:
                w = _LINK_W[kind][0 if i == 0 else 1] * rw
                score += w
                reasons.append({"text": text, "fact_ids": fids, "kind": kind, "house": h, "ref": ref,
                                "points": round(w, 3)})
    score = round(score, 2)
    strength = "strong" if score >= 3 else "medium" if score >= 1.5 else "weak" if score > 0 else "none"
    reasons.sort(key=lambda r: -r["points"])
    return {"planet": planet, "score": score, "strength": strength, "reasons": reasons}


def _combined_strength(score: float) -> str:
    return "strong" if score >= 4 else "medium" if score >= 2 else "weak" if score > 0 else "none"


def periods(facts: dict, birth, topic_id: str, start: date, end: date, *,
            time_known: Optional[bool] = None) -> list:
    """Vimshottari AD intervals overlapping [start, end] whose MD/AD lords link to the topic houses,
    each with its linked PD sub-intervals. Sorted by start date."""
    from .engine import _ymd
    t = topic(topic_id)
    tk = _time_known(birth, time_known)
    rows = (facts.get("vimshottari") or {}).get("periods") or []
    s_iso, e_iso = start.isoformat(), end.isoformat()
    cache: dict = {}

    def link(pl):
        if pl not in cache:
            cache[pl] = planet_links(facts, pl, t, tk)
        return cache[pl]

    out = []
    for idx, r in enumerate(rows):
        if r["end"] <= s_iso or r["start"] > e_iso:
            continue
        md, ad = r["maha"], r["antar"]
        lm, la = link(md), link(ad)
        score = round(la["score"] + 0.5 * lm["score"], 2)
        strength = _combined_strength(score)
        if strength == "none":
            continue
        rel = dasha_craft.relation(K.house_from(facts["planets"][ad]["sign"], facts["planets"][md]["sign"]))
        reasons = [{"text": f"{x['text']}.", "fact_ids": x["fact_ids"] + [f"vimshottari.periods.{idx}"]}
                   for x in (la["reasons"][:2] + lm["reasons"][:1])]
        notes = []
        if rel["kind"] == "friction":
            notes.append(f"{ad} sits {_ord(rel['house'])} from {md}, so this sub-period can bring results "
                         "with some friction or delay.")
        pds = []
        if r.get("start_jd") is not None:
            for pd in V.pd_periods([r], r["start_jd"], r["end_jd"]):
                ps, pe = _ymd(pd["start_jd"]), _ymd(pd["end_jd"])
                if pe <= s_iso or ps > e_iso:
                    continue
                lp = link(pd["lords"][2])
                if lp["score"] <= 0:
                    continue
                pds.append({"lords": pd["lords"], "start": ps, "end": pe, "score": lp["score"],
                            "link": lp["strength"],
                            "reasons": [{"text": f"{x['text']}.", "fact_ids": x["fact_ids"]}
                                        for x in lp["reasons"][:1]]})
        out.append({"level": "AD", "md": md, "ad": ad, "lords": [md, ad], "start": r["start"], "end": r["end"],
                    "period_index": idx, "score": score, "link": strength,
                    "md_link": lm["strength"], "ad_link": la["strength"], "reasons": reasons,
                    "friction": {"kind": rel["kind"], "house": rel["house"], "rule_id": rel["id"],
                                 "verified": rel["verified"]},
                    "notes": notes, "pds": pds,
                    "rule_ids": ["CORE.PERIOD_LINK", rel["id"]]})
    return out


# ------------------------------------------------------------------ triggers

def _month_starts(start: date, end: date) -> list:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _month_end(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _signs_in(intervals: list, a: date, b: date) -> list:
    return sorted({s for s, f, l in intervals if f <= b and l >= a})


def _touch(planet: str, signs: list, targets: dict) -> Optional[dict]:
    """First (sign, target) where `planet` occupies or aspects a target sign."""
    for s in signs:
        for name, tsign in targets.items():
            if s == tsign:
                return {"sign": K.SIGN_NAMES[s], "via": "occupies", "target": name}
            if tsign in K.parashari_reaches(planet, s):
                return {"sign": K.SIGN_NAMES[s], "via": "aspects", "target": name}
    return None


def triggers(facts: dict, birth, topic_id: str, start: date, end: date, *,
             time_known: Optional[bool] = None) -> list:
    """Months in [start, end] where transiting Saturn AND Jupiter both occupy/aspect the topic's primary
    house or its lord's sign (from Lagna; from Moon as secondary). [{month, from_lagna, from_moon, ...}]."""
    from . import transits
    t = topic(topic_id)
    tk = _time_known(birth, time_known)
    h = t["houses"][0]
    refs = ("lagna", "moon") if tk else ("moon",)
    targets = {}
    for ref in refs:
        hs = _house_sign(facts, h, ref)
        lord = _lord_of_sign(hs)
        targets[ref] = {"house": hs, "lord": int(facts["planets"][lord]["sign"])}
    sat = transits.sign_intervals(birth, "Saturn", start, end)
    jup = transits.sign_intervals(birth, "Jupiter", start, end)
    out = []
    for m in _month_starts(start, end):
        a, b = max(m, start), min(_month_end(m), end)
        ss, js = _signs_in(sat, a, b), _signs_in(jup, a, b)
        row = {"month": m.isoformat()[:7], "from_lagna": False, "from_moon": False}
        for ref in refs:
            st, jt = _touch("Saturn", ss, targets[ref]), _touch("Jupiter", js, targets[ref])
            if st and jt:
                row[f"from_{ref}"] = True
                row.setdefault("saturn", st)
                row.setdefault("jupiter", jt)
                row.setdefault("ref", ref)
        if row["from_lagna"] or row["from_moon"]:
            ref = row["ref"]
            where = "" if ref == "lagna" else " (from your Moon sign)"
            lord = _lord_of_sign(targets[ref]["house"])
            def tgt(x):
                return f"your {_ord(h)} house" if x["target"] == "house" else f"{lord}, its ruler"
            row["text"] = (f"Saturn ({row['saturn']['via']} from {row['saturn']['sign']}) and Jupiter "
                           f"({row['jupiter']['via']} from {row['jupiter']['sign']}) both influence "
                           f"{tgt(row['saturn'])}{' and ' + tgt(row['jupiter']) if row['jupiter']['target'] != row['saturn']['target'] else ''}"
                           f"{where} in {row['month']}.")
            row["fact_ids"] = [f"transit.Saturn.{row['month']}", f"transit.Jupiter.{row['month']}",
                               "lagna.sign" if ref == "lagna" else "planets.Moon.sign", f"planets.{lord}.sign"]
            row["rule_id"] = "CORE.DOUBLE_TRANSIT"
            out.append(row)
    return out


# ------------------------------------------------------------------ card

ACTIONS = {
    "career": ("Use this window to ask for bigger responsibilities and make your work visible.",
               "Keep building skills and steady results; push for change when signals line up.",
               "Focus on consistency and skill-building rather than expecting a big shift now."),
    "job_change": ("Update your CV and reach out to contacts; this is a reasonable time to apply.",
                   "Explore options quietly and keep your current role until an offer is in hand.",
                   "Strengthen your current position; a move is better planned than rushed."),
    "promotion": ("Talk to your manager about growth and document your achievements.",
                  "Keep delivering and ask for clear goals that lead to the next level.",
                  "Invest in one visible skill; recognition may take longer than you hope."),
    "business": ("Prepare a clear plan and test it with a small, low-risk first step.",
                 "Start small, check the numbers often and keep a safety cushion.",
                 "Keep the idea on paper and build savings before committing money."),
    "wealth": ("Put a part of any extra income into steady savings first.",
               "Track spending closely and avoid large risky bets.",
               "Keep a simple budget and an emergency fund; avoid big financial risks."),
    "marriage": ("Be open to introductions and honest conversations with family.",
                 "Take your time, talk openly and let things develop naturally.",
                 "Focus on your own life and friendships; there is no need to rush."),
    "relationship": ("Make time for people who matter and say what you feel clearly.",
                     "Communicate patiently; small gestures help more than big promises.",
                     "Invest in friendships and self-care; there is no need to force anything."),
    "children": ("Plan together as a couple and follow your doctor's guidance.",
                 "Plan calmly and follow medical advice; timing is not fixed.",
                 "Follow medical advice for any family planning; the chart is only one view."),
    "education": ("Set a study timetable and apply for the courses you want.",
                  "Keep a steady study routine and ask teachers for help early.",
                  "Build strong basics; steady effort counts more than timing."),
    "foreign": ("Get your documents ready and research the options carefully.",
                "Collect information and keep paperwork ready without rushing a decision.",
                "Explore opportunities closer to home while keeping options open."),
    "property": ("Check finances and documents carefully before you commit.",
                 "Compare options patiently and get every paper verified.",
                 "Save towards it and keep looking without pressure to buy now."),
    "wellbeing": ("Keep a regular routine of sleep, movement and rest.",
                  "Keep a regular routine of sleep, movement and rest.",
                  "Keep a regular routine and consult a professional for any health concern."),
}
VERDICTS_FUTURE = ("likely", "mixed", "not_indicated")
VERDICTS_NATAL = ("strong", "moderate", "weak")
PRECISION_POINTS = {"exact": 0, "approximate": -1, "unknown": -2}
FIT_POINTS = {"good": 1, "partial": 0, "poor": -2}


@dataclass
class Card:
    topic: str
    label: str
    tense: str
    verdict: str
    window: Optional[dict]
    confidence: str
    why: list
    action: str
    rule_ids: dict
    time_known: bool
    range: Optional[dict] = None
    candidates: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        return cls(**d)


def _overlap(a1: str, a2: str, b1: str, b2: str) -> Optional[tuple]:
    s, e = max(a1, b1), min(a2, b2)
    return (s, e) if s < e else None


def _trigger_spans(trig: list) -> list:
    """Contiguous runs of trigger months as (start_iso, end_iso, first_row)."""
    spans = []
    for row in trig:
        m = date.fromisoformat(row["month"] + "-01")
        s, e = m.isoformat(), (_month_end(m) + timedelta(days=1)).isoformat()
        if spans and spans[-1][1] == s:
            spans[-1] = (spans[-1][0], e, spans[-1][2])
        else:
            spans.append((s, e, row))
    return spans


def _windows(pers: list, trig: list, lo: str, hi: str) -> list:
    """Candidate windows, narrowest/strongest first: PD ∩ transit, AD ∩ transit, then AD alone."""
    spans = [(max(s, lo), min(e, hi), row) for s, e, row in _trigger_spans(trig) if max(s, lo) < min(e, hi)]
    cands = []
    for ad in pers:
        # a weakly linked AD can only be the plain fallback window (verdict 'mixed')
        for sp in (spans if ad["link"] != "weak" else []):
            for pd in ad["pds"]:
                ov = _overlap(pd["start"], pd["end"], sp[0], sp[1])
                if ov and pd["link"] in ("strong", "medium"):
                    cands.append({"basis": "pd+transit", "start": ov[0], "end": ov[1], "ad": ad, "pd": pd,
                                  "trigger": sp[2], "rank": (3, ad["score"] + pd["score"])})
            ov = _overlap(ad["start"], ad["end"], sp[0], sp[1])
            if ov:
                cands.append({"basis": "ad+transit", "start": ov[0], "end": ov[1], "ad": ad, "pd": None,
                              "trigger": sp[2], "rank": (2, ad["score"])})
        ov = _overlap(ad["start"], ad["end"], lo, hi)
        if ov:
            cands.append({"basis": "ad", "start": ov[0], "end": ov[1], "ad": ad, "pd": None, "trigger": None,
                          "rank": (1, ad["score"])})
    cands.sort(key=lambda c: (-c["rank"][0], -c["rank"][1], c["start"]))
    return cands


def _confidence(grade: str, link: Optional[str], trigger: bool, precision: str, time_known: bool,
                varga_reliable: bool, personal_fit: Optional[str], natal: bool) -> tuple[str, int]:
    pts = {"strong": 2, "moderate": 1, "weak": 0}[grade]
    if not natal:
        pts += {"strong": 2, "medium": 1}.get(link or "", 0) + (1 if trigger else 0)
    pts += PRECISION_POINTS.get(precision, 0)
    pts += 0 if varga_reliable else -1
    pts += FIT_POINTS.get(personal_fit or "", 0)
    hi_at, mid_at = (5, 3) if not natal else (3, 1)
    level = "high" if pts >= hi_at else "medium" if pts >= mid_at else "low"
    if not time_known or personal_fit == "poor":
        level = "low"
    return level, pts


def _fmt_month(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return d.strftime("%B %Y")


def answer(facts: dict, birth, topic_id: str, *, question_tense: str = "future",
           start: Optional[date] = None, end: Optional[date] = None, today: Optional[date] = None,
           personal_fit: Optional[str] = None) -> Card:
    """The answer card for one topic. question_tense: 'future' | 'past' | 'natal'."""
    if question_tense not in ("future", "past", "natal"):
        raise ValueError("question_tense must be future, past or natal")
    t = topic(topic_id)
    today = today or date.today()
    tk = _time_known(birth)
    precision = getattr(birth, "birth_time_precision", "exact") or "exact"
    pr = promise(facts, topic_id, time_known=tk)
    v = t["varga"]
    varga_reliable = v in ("D1",) or _varga_ok(facts, v, tk)
    acts = ACTIONS.get(topic_id, ACTIONS["career"])
    rule_ids = {"promise": pr["rule_ids"], "period": [], "trigger": [], "card": ["CORE.CARD", "CORE.CONFIDENCE"]}
    why_p = [{"text": r["text"], "fact_ids": r["fact_ids"]} for r in pr["reasons"]]
    details: dict = {"promise": pr, "periods": [], "triggers": [], "window_basis": None, "notes": [],
                     "confidence_points": None}
    if not tk:
        details["notes"].append("Birth time unknown: read from the Moon sign; confidence is capped at low.")
    if varga_reliable is False:
        details["notes"].append(f"{v} chart not used: it is not reliable for this birth time.")
    natal = question_tense == "natal" or not t["timing"]
    if natal:
        if not t["timing"] and question_tense != "natal":
            details["notes"].append(f"{t['label']['en']} is read as a theme only; it is never timed.")
        conf, cp = _confidence(pr["grade"], None, False, precision, tk, varga_reliable, personal_fit, True)
        details["confidence_points"] = cp
        act = acts[{"strong": 0, "moderate": 1, "weak": 2}[pr["grade"]]]
        return Card(topic_id, t["label"]["en"], "natal", pr["grade"], None, conf, why_p[:2], act, rule_ids, tk,
                    None, [], details)

    if question_tense == "past":
        birth_day = date(birth.year, birth.month, birth.day)
        hi_d = end or today
        lo_d = start or max(birth_day, date(hi_d.year - PAST_YEARS, hi_d.month, min(hi_d.day, 28)))
    else:
        lo_d = start or today
        hi_d = end or (lo_d + timedelta(days=365))
        # elapsed portions of an asked span cannot be credited as a forecast —
        # "a promotion this year" searched from January would surface last spring
        if lo_d <= today:
            lo_d = today + timedelta(days=1)
    if hi_d <= lo_d:
        raise ValueError("end must be after start")
    rng = {"start": lo_d.isoformat(), "end": hi_d.isoformat()}

    if pr["grade"] == "weak":
        conf, cp = _confidence("weak", None, False, precision, tk, varga_reliable, personal_fit, False)
        details["confidence_points"] = cp
        details["notes"].append("The natal promise is weak, so no timing is given.")
        return Card(topic_id, t["label"]["en"], question_tense, "not_indicated", None, conf, why_p[:2],
                    acts[2], rule_ids, tk, rng, [], details)

    pers = periods(facts, birth, topic_id, lo_d, hi_d, time_known=tk)
    trig = triggers(facts, birth, topic_id, lo_d, hi_d, time_known=tk)
    details["periods"], details["triggers"] = pers, trig
    rule_ids["period"] = sorted({r for p in pers for r in p["rule_ids"]})
    rule_ids["trigger"] = ["CORE.DOUBLE_TRANSIT"] if trig else []
    cands = _windows(pers, trig, rng["start"], rng["end"])
    if question_tense == "past":
        rule_ids["card"].append("CORE.PAST_SCAN")
        timed = [c for c in cands if c["trigger"] is not None]
        pool = timed or cands
        # most recent first; keep one candidate per AD (its narrowest window)
        seen, past = set(), []
        for c in sorted(pool, key=lambda c: (-c["rank"][0], c["start"]), reverse=False):
            key = (c["ad"]["period_index"])
            if key in seen:
                continue
            seen.add(key)
            past.append(c)
        past.sort(key=lambda c: c["start"], reverse=True)
        cands = past
    if not cands:
        conf, cp = _confidence(pr["grade"], None, False, precision, tk, varga_reliable, personal_fit, False)
        details["confidence_points"] = cp
        details["notes"].append("No running period in this range links to the topic.")
        return Card(topic_id, t["label"]["en"], question_tense, "not_indicated", None, conf, why_p[:2],
                    acts[2], rule_ids, tk, rng, [], details)
    best = cands[0]
    ad = best["ad"]
    triggered = best["trigger"] is not None
    verdict = "likely" if triggered and ad["link"] in ("strong", "medium") else "mixed"
    if verdict == "likely" and pr["grade"] == "moderate" and ad["friction"]["kind"] == "friction":
        verdict = "mixed"
    details["window_basis"] = best["basis"]
    rule_ids["card"].append("CORE.WINDOW")
    conf, cp = _confidence(pr["grade"], ad["link"], triggered, precision, tk, varga_reliable, personal_fit, False)
    details["confidence_points"] = cp
    lvl = f"{best['pd']['lords'][2]} mini-period within " if best["pd"] else ""
    pr_text = ad["reasons"][0]["text"] if ad["reasons"] else ""
    why_t = {"text": f"From {_fmt_month(best['start'])} you are in the {lvl}{ad['ad']} sub-period of the "
                     f"{ad['md']} major period. {pr_text}".strip(),
             "fact_ids": sorted({f for r in ad["reasons"][:1] for f in r["fact_ids"]}
                                | {f"vimshottari.periods.{ad['period_index']}"})}
    why = why_p[:1] + [why_t]
    if triggered and len(why) < 2:
        why.append({"text": best["trigger"]["text"], "fact_ids": best["trigger"]["fact_ids"]})
    details["window_trigger"] = best["trigger"]
    candidates = []
    if question_tense == "past":
        candidates = [{"start": c["start"], "end": c["end"], "basis": c["basis"], "md": c["ad"]["md"],
                       "ad": c["ad"]["ad"], "pd": c["pd"]["lords"][2] if c["pd"] else None,
                       "link": c["ad"]["link"], "transit": bool(c["trigger"])} for c in cands]
    act = acts[0 if verdict == "likely" else 1]
    return Card(topic_id, t["label"]["en"], question_tense, verdict, {"start": best["start"], "end": best["end"]},
                conf, why[:2], act, rule_ids, tk, rng, candidates, details)


# ------------------------------------------------------------------ home screen

_VERDICT_RANK = {"likely": 2, "mixed": 1, "not_indicated": 0}
_CONF_RANK = {"high": 2, "medium": 1, "low": 0}


def overview_item(card: Card, caution: bool = False) -> dict:
    return {"topic": card.topic, "label": card.label, "verdict": card.verdict, "window": card.window,
            "confidence": card.confidence, "why": card.why, "action": card.action, "caution": caution}


# desh-kaal-paristhiti: the typical life window a topic's promise can actually
# play out in. A chart hit means nothing shown for an age where the event is
# implausible (a 5th-house promise does not mean childbirth at 55).
_TOPIC_AGE_RANGE = {
    "career": (16, 75), "job_change": (16, 70), "promotion": (18, 70), "business": (18, 75),
    "wealth": (16, None), "marriage": (18, 60), "relationship": (15, None),
    "children": (18, 48), "education": (14, 35), "foreign": (16, None), "property": (21, None),
}


def _age_plausible(topic_id: str, age: int) -> bool:
    lo, hi = _TOPIC_AGE_RANGE.get(topic_id, (0, None))
    return age >= lo and (hi is None or age <= hi)


def year_overview(facts: dict, birth, today: date, *, personal_fit: Optional[str] = None,
                  exclude: tuple = ()) -> list:
    """Top 3 topics for the next 12 months (strongest first, one per life area) plus one caution
    item last (verdict not_indicated, else a weak promise), if any."""
    age = today.year - birth.year
    cards = []
    for tid, t in load_topics().items():
        if not t["timing"] or tid in exclude or not _age_plausible(tid, age):
            continue
        c = answer(facts, birth, tid, question_tense="future", today=today, personal_fit=personal_fit)
        cards.append(c)

    def key(c):
        return (_VERDICT_RANK[c.verdict], _CONF_RANK[c.confidence], c.details["promise"]["score"])
    ranked = sorted(cards, key=key, reverse=True)
    top, domains = [], set()
    for c in ranked:                    # one card per life area so career topics do not crowd the list
        dom = load_topics()[c.topic]["safety_domain"]
        if c.verdict != "not_indicated" and dom not in domains and len(top) < 3:
            top.append(c)
            domains.add(dom)
    rest = [c for c in ranked if all(c is not x for x in top)]
    out = [overview_item(c) for c in top]
    caution = next((c for c in reversed(rest) if c.verdict == "not_indicated"), None) \
        or next((c for c in reversed(rest) if c.details["promise"]["grade"] == "weak"), None)
    if caution is not None:
        out.append(overview_item(caution, caution=True))
    return out


# desh-kaal-paristhiti on the brief itself: where a person stands in life
# (ashrama-wise age bands) read through the running period's flavour.
_LIFE_PHASES = [
    (25, "foundation", "learning, education, and finding your direction"),
    (50, "building", "career, family, and asset-building years"),
    (75, "consolidation", "harvest, stability, and mentoring others"),
    (200, "legacy", "reflection, detachment, and passing things on"),
]
_LORD_FLAVOR = {
    "Sun": "position, visibility and responsibility", "Moon": "home, mind and care for people",
    "Mars": "drive, competition and getting things done", "Mercury": "learning, skills and trade",
    "Jupiter": "growth, wisdom and expansion", "Venus": "comfort, relationships and creativity",
    "Saturn": "work, discipline and endurance", "Rahu": "ambition, change and unconventional paths",
    "Ketu": "completion, detachment and inner focus",
}


def life_phase(facts: dict, birth, today: date) -> dict:
    """{'key','label','focus','note'} — e.g. 43 + Jupiter MD →
    'Building phase' / 'career, family…' / 'Your Jupiter major period —
    growth, wisdom and expansion — runs until 2029.'."""
    age = today.year - birth.year
    key, focus = next((k, f) for limit, k, f in _LIFE_PHASES if age < limit)
    note = ""
    md, ad, _ = dasha_craft.current_rows(facts, today)
    if md is not None:
        flavor = _LORD_FLAVOR.get(md["lord"], "its own themes")
        note = f"Your {md['lord']} major period — {flavor} — runs until {md['end'][:4]}"
        if ad is not None and ad["antar"] != md["lord"]:
            note += f", with {ad['antar']} sub-period until {_fmt_month(ad['end'])}"
        note += "."
    return {"key": key, "label": f"{key.title()} phase", "focus": focus, "note": note}


def dasha_brief(facts: dict, today: date) -> Optional[str]:
    """'Jupiter major period, Saturn sub-period until March 2027'."""
    md, ad, _ = dasha_craft.current_rows(facts, today)
    if md is None:
        return None
    return f"{md['lord']} major period, {ad['antar']} sub-period until {_fmt_month(ad['end'])}"


# ------------------------------------------------------------------ text fallback

_TXT = {
    "en": {"answer": "Answer", "when": "When", "why": "Why", "confidence": "Confidence", "do": "What you can do",
           "likely": "Likely", "mixed": "Mixed signals", "not_indicated": "Not indicated in this period",
           "strong": "Strong promise in your chart", "moderate": "Moderate promise in your chart",
           "weak": "Weak promise in your chart", "high": "high", "medium": "medium", "low": "low",
           "no_window": "No specific window", "to": "to"},
    "hi": {"answer": "उत्तर", "when": "कब", "why": "क्यों", "confidence": "विश्वास", "do": "आप क्या कर सकते हैं",
           "likely": "संभावना है", "mixed": "मिले-जुले संकेत", "not_indicated": "इस अवधि में संकेत नहीं",
           "strong": "कुंडली में मज़बूत संकेत", "moderate": "कुंडली में मध्यम संकेत",
           "weak": "कुंडली में कमज़ोर संकेत", "high": "उच्च", "medium": "मध्यम", "low": "कम",
           "no_window": "कोई विशेष समय नहीं", "to": "से"},
}


def card_text(card, lang: str = "en") -> str:
    """Deterministic plain-language rendering of a card (used when no LLM is available).
    Reasons and the action line are English in both languages for now."""
    c = card if isinstance(card, dict) else card.to_dict()
    L = _TXT.get(lang, _TXT["en"])
    label = topic(c["topic"])["label"].get(lang, c["label"]) if c["topic"] in load_topics() else c["label"]
    lines = [f"{label} — {L['answer']}: {L.get(c['verdict'], c['verdict'])}."]
    if c["tense"] != "natal":
        w = c.get("window")
        last = (date.fromisoformat(w["end"]) - timedelta(days=1)).isoformat() if w else None  # end is exclusive
        when = f"{_fmt_month(w['start'])} {L['to']} {_fmt_month(last)}" if w else L["no_window"]
        lines.append(f"{L['when']}: {when}.")
    if c["why"]:
        lines.append(f"{L['why']}: " + " ".join(r["text"] for r in c["why"]))
    lines.append(f"{L['confidence']}: {L.get(c['confidence'], c['confidence'])}.")
    lines.append(f"{L['do']}: {c['action']}")
    return "\n".join(lines)
