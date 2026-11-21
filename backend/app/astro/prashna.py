"""Prashna (horary): a chart cast for the moment a question is asked.

The chart is cast at the question moment for the place where the question
is asked (current location), through the same engine as a natal chart. The
result lists the Prashna Lagna and its lord, the Moon, the house that
governs the question, and a handful of traditional yes/no *indicators*.

Everything below is labelled traditional, not predictive: indicators are
reported as "favourable / unfavourable / informational" with an id, a
source tag and `verified: False` (horary rule wording and weighting differ
between Prashna Marga, Tajika Neelakanthi and KP). No indicator is
presented as a certain answer.
"""
from datetime import date, datetime, timedelta, timezone

from jhora import const, utils
from jhora.panchanga import drik

from . import constants as K
from . import kp, muhurta, varsha
from .engine import BirthInput, apply, calc_lock, engine

SRC_PM = "Prashna Marga (traditional)"
SRC_TN = "Tajika Neelakanthi (traditional)"
SRC_KP = "KP horary (simplified, KP-lite)"

QUESTIONS = {
    "general":   {"label": "General question", "house": 1, "karakas": ["Moon"], "support": {1, 5, 9, 11}, "oppose": {6, 8, 12}},
    "marriage":  {"label": "Marriage / relationship", "house": 7, "karakas": ["Venus", "Jupiter"], "support": {2, 7, 11}, "oppose": {1, 6, 10}},
    "career":    {"label": "Career / job", "house": 10, "karakas": ["Sun", "Saturn", "Mercury"], "support": {2, 6, 10, 11}, "oppose": {5, 8, 12}},
    "money":     {"label": "Money / gains", "house": 11, "karakas": ["Jupiter"], "support": {2, 6, 11}, "oppose": {5, 8, 12}},
    "education": {"label": "Education / exams", "house": 5, "karakas": ["Mercury", "Jupiter"], "support": {4, 9, 11}, "oppose": {3, 8, 12}},
    "health":    {"label": "Health / recovery", "house": 6, "karakas": ["Sun", "Moon"], "support": {1, 5, 11}, "oppose": {6, 8, 12}},
    "children":  {"label": "Children", "house": 5, "karakas": ["Jupiter"], "support": {2, 5, 11}, "oppose": {1, 4, 10}},
    "property":  {"label": "Property / home", "house": 4, "karakas": ["Mars", "Saturn"], "support": {4, 11, 12}, "oppose": {3, 5, 10}},
    "travel":    {"label": "Travel / relocation", "house": 3, "karakas": ["Moon", "Rahu"], "support": {3, 9, 12}, "oppose": {2, 4, 11}},
    "legal":     {"label": "Legal matter / dispute", "house": 6, "karakas": ["Mars", "Saturn"], "support": {6, 11}, "oppose": {5, 8, 12}},
}

_GOOD_HOUSES = {1, 2, 4, 5, 7, 9, 10, 11}
_PID = {v: k for k, v in K.PLANET_NAMES.items()}
_MODALITY_NOTE = {
    "movable": "Movable Lagna: traditionally associated with quicker developments and change.",
    "fixed": "Fixed Lagna: traditionally associated with delay, stability or persistence.",
    "dual": "Dual Lagna: traditionally associated with mixed or wavering outcomes.",
}


def _local_now(lat: float, lon: float, name: str) -> datetime:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    tz = muhurta.place_for(lat, lon, name, now.date()).timezone
    return now + timedelta(hours=tz)


def moment_input(lat: float, lon: float, name: str, when_local: datetime | None, settings=None) -> BirthInput:
    when = (when_local or _local_now(lat, lon, name)).replace(microsecond=0)
    place = muhurta.place_for(lat, lon, name, when.date())
    # re-derive the offset for the exact local time (DST edges)
    tz = place.timezone
    kwargs = {"settings": settings} if settings is not None else {}
    return BirthInput(name="Prashna", year=when.year, month=when.month, day=when.day,
                      hour=when.hour, minute=when.minute, second=when.second,
                      lat=lat, lon=lon, tz_offset=tz, place_label=name or "Location",
                      birth_time_precision="exact", **kwargs)


def _pos(facts: dict) -> dict:
    return {K.PLANET_NAMES and _PID[n]: (p["sign"], p["degree"]) for n, p in facts["planets"].items()}


def _speeds(b: BirthInput) -> dict:
    try:
        with calc_lock:
            apply(b.settings)
            jd = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
            place = drik.Place(b.place_label, b.lat, b.lon, b.tz_offset)
            return {p: float(v[3]) for p, v in drik.planets_speed_info(jd, place).items()}
    except Exception:
        return {}


def _ind(id_, label, fav, detail, source=SRC_PM):
    return {"id": id_, "label": label, "favourable": fav, "detail": detail,
            "source": source, "verified": False}


def _significators(kp_chart: dict, house: int) -> set:
    row = next((s for s in kp_chart["significators"] if s["house"] == house), None)
    if not row:
        return set()
    return set(row["occupants"]) | set(row["stars_of_occupants"]) | {row["owner"]} | set(row["stars_of_owner"])


def _kp_lite(b: BirthInput, facts: dict, q: dict) -> dict:
    try:
        chart = kp.calculate(b)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    cusp = next(c for c in chart["cusps"] if c["house"] == q["house"])
    sub = cusp["sub_lord"]
    # houses signified by the sub-lord: own/occupied houses + houses where it is a significator
    sig_houses = {h for h in range(1, 13) if sub in _significators(chart, h)}
    sup = sorted(sig_houses & q["support"])
    opp = sorted(sig_houses & q["oppose"])
    tendency = ("supports" if len(sup) > len(opp) else "against" if len(opp) > len(sup) else "mixed")
    return {"available": True, "cusp": q["house"], "sub_lord": sub, "star_lord": cusp["star_lord"],
            "signified_houses": sorted(sig_houses), "supporting_houses": sup, "opposing_houses": opp,
            "tendency": tendency, "source": SRC_KP, "verified": False,
            "note": "KP-lite: the sub-lord of the relevant cusp judged by the houses it signifies. "
                    "Full KP horary uses a 1-249 number given by the querent; not used here."}


def analyse(b: BirthInput, qtype: str = "general") -> dict:
    q = QUESTIONS[qtype]
    facts = engine.compute(b)
    pl, houses = facts["planets"], facts["houses"]
    lagna_sign = facts["lagna"]["sign"]
    lagna_lord = facts["lagna"]["lord"]
    ll = pl[lagna_lord]
    rel_house = q["house"]
    karyesha_name = houses[rel_house]["lord"]
    ky = pl[karyesha_name]
    moon = pl["Moon"]
    waxing = ((moon["abs_longitude"] - pl["Sun"]["abs_longitude"]) % 360) < 180
    modality = K.SIGN_MODALITY[lagna_sign]
    pos = _pos(facts)
    speeds = _speeds(b)

    inds = [_ind("P-PACE", "Lagna type", None, _MODALITY_NOTE[modality])]

    def strength_text(p):
        bits = list(p.get("dignity", []))
        if p.get("combust"):
            bits.append("combust")
        if p.get("retrograde"):
            bits.append("retrograde")
        return ", ".join(bits) or "no special dignity"

    ll_weak = ll["house"] in (6, 8, 12) or "debilitated" in " ".join(ll.get("dignity", [])).lower() or ll.get("combust")
    inds.append(_ind("P-LL", f"Lagna lord {lagna_lord} well placed", not ll_weak,
                     f"in {ll['sign_name']}, house {ll['house']} ({strength_text(ll)})"))
    inds.append(_ind("P-KARYESHA", f"{karyesha_name} (lord of house {rel_house}) well placed",
                     ky["house"] in _GOOD_HOUSES and not ky.get("combust"),
                     f"in {ky['sign_name']}, house {ky['house']} ({strength_text(ky)})"))

    # Ithasala between Lagna lord and Karyesha
    ithasala = {"relation": "none"}
    if lagna_lord != karyesha_name:
        a, c = _PID[lagna_lord], _PID[karyesha_name]
        try:
            if varsha._aspects(pos[a][0], pos[c][0]):
                within, kind = varsha._in_deeptamsa(pos, a, c)
                if within:
                    fast, slow = varsha._faster_pair(pos, speeds, a, c)
                    if varsha._applying(pos, speeds, fast, slow):
                        ithasala = {"relation": "ithasala", "kind": kind,
                                    "text": f"{K.PLANET_NAMES[fast]} applying to {K.PLANET_NAMES[slow]} ({kind})"}
                    else:
                        ithasala = {"relation": "ishrafa",
                                    "text": f"{K.PLANET_NAMES[fast]} separating from {K.PLANET_NAMES[slow]}"}
        except Exception:
            ithasala = {"relation": "unknown"}
        fav = {"ithasala": True, "ishrafa": False}.get(ithasala["relation"])
        inds.append(_ind("P-ITHASALA", "Ithasala between Lagna lord and house lord", fav,
                         ithasala.get("text") or "No applying Tajika aspect between them", SRC_TN))
    else:
        inds.append(_ind("P-ITHASALA", "Lagna lord is also the house lord", True,
                         f"{lagna_lord} rules both Lagna and house {rel_house}: querent and matter are linked", SRC_TN))

    # Moon
    moon_ithasala = None
    try:
        for name in {lagna_lord, karyesha_name}:
            if name == "Moon":
                continue
            p2 = _PID[name]
            if varsha._aspects(pos[1][0], pos[p2][0]):
                within, kind = varsha._in_deeptamsa(pos, 1, p2)
                if within:
                    fast, slow = varsha._faster_pair(pos, speeds, 1, p2)
                    if fast == 1 and varsha._applying(pos, speeds, fast, slow):
                        moon_ithasala = name
                        break
    except Exception:
        pass
    inds.append(_ind("P-MOON-LINK", "Moon applying to the Lagna lord or house lord",
                     True if moon_ithasala else None,
                     f"Moon in ithasala with {moon_ithasala}" if moon_ithasala else "No close applying aspect from the Moon",
                     SRC_TN))
    inds.append(_ind("P-MOON-HOUSE", "Moon placement", moon["house"] not in (6, 8, 12) and waxing,
                     f"Moon in {moon['sign_name']}, house {moon['house']}, {'waxing' if waxing else 'waning'}"))
    occupants = [n for n, p in pl.items() if p["house"] == rel_house]
    benef = [n for n in occupants if K.PLANET_NAMES and _PID[n] in K.NATURAL_BENEFICS]
    malef = [n for n in occupants if _PID[n] in K.NATURAL_MALEFICS]
    inds.append(_ind("P-HOUSE-OCC", f"House {rel_house} occupants",
                     True if benef and not malef else False if malef and not benef else None,
                     ", ".join(occupants) if occupants else "empty"))
    kpl = _kp_lite(b, facts, q)
    if kpl.get("available"):
        inds.append(_ind("P-KP", f"KP-lite: sub-lord of cusp {rel_house} ({kpl['sub_lord']})",
                         {"supports": True, "against": False}.get(kpl["tendency"]),
                         f"signifies houses {kpl['signified_houses']}", SRC_KP))

    fav = sum(1 for i in inds if i["favourable"] is True)
    unf = sum(1 for i in inds if i["favourable"] is False)
    scored = fav + unf
    lean = "mixed" if scored == 0 or abs(fav - unf) <= 1 else ("favourable" if fav > unf else "unfavourable")
    return {
        "question_type": qtype, "question_label": q["label"], "relevant_house": rel_house,
        "karakas": q["karakas"],
        "cast": {"local": facts["meta"]["birth_datetime_local"], "place": b.place_label,
                 "latitude": b.lat, "longitude": b.lon, "utc_offset_hours": b.tz_offset},
        "lagna": {"sign": facts["lagna"]["sign_name"], "degree": round(facts["lagna"]["degree"], 2),
                  "lord": lagna_lord, "lord_house": ll["house"], "lord_sign": ll["sign_name"],
                  "modality": modality, "nakshatra": facts["lagna"]["nakshatra"]["name"]},
        "moon": {"sign": moon["sign_name"], "house": moon["house"], "nakshatra": moon["nakshatra"]["name"],
                 "pada": moon["nakshatra"]["pada"], "waxing": waxing},
        "relevant": {"house": rel_house, "sign": houses[rel_house]["sign_name"], "lord": karyesha_name,
                     "lord_house": ky["house"], "lord_sign": ky["sign_name"], "occupants": occupants},
        "planets": {n: {"sign": p["sign_name"], "degree": round(p["degree"], 2), "house": p["house"],
                        "retrograde": p["retrograde"], "combust": p["combust"]} for n, p in pl.items()},
        "ithasala": ithasala,
        "kp_lite": kpl,
        "indicators": inds,
        "summary": {"favourable": fav, "unfavourable": unf, "scored": scored, "leaning": lean,
                    "text": (f"{fav} of {scored} scored traditional indicators lean favourable, "
                             f"{unf} unfavourable ({lean}).") if scored else "No scored indicators.",
                    "label": "Traditional indications only; not a prediction or a certain yes/no."},
        "_facts": facts,
    }


def rectification_hint(prashna: dict, birth: BirthInput, settings=None) -> dict:
    """Guided hint for users who do not know their birth time.

    Lists the Lagna windows through the birth day and flags those whose
    sign falls in the trines of the Prashna Lagna (a traditional heuristic
    that is NOT a derivation of birth time). Intended only to help choose
    which time-of-day questions to ask next.
    """
    precision = birth.birth_time_precision
    if precision == "exact":
        return {"applicable": False}
    p_sign = K.SIGN_NAMES.index(prashna["lagna"]["sign"])
    trines = {p_sign, (p_sign + 4) % 12, (p_sign + 8) % 12}
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    if precision == "approximate":
        lo = max(0.0, birth.hour + birth.minute / 60 - 2)
        hi = min(24.0, birth.hour + birth.minute / 60 + 2)
    else:
        lo, hi = 0.0, 24.0
    windows, cur = [], None
    step = 5 / 60
    with calc_lock:
        apply(birth.settings if settings is None else settings)
        t = lo
        while t < hi - 1e-9:
            h, m = int(t), int(round((t - int(t)) * 60)) % 60
            jd = utils.julian_day_number((birth.year, birth.month, birth.day), (h, m, 0))
            sign = int(drik.ascendant(jd, place)[0])
            if cur and cur["sign"] == sign:
                cur["end"] = t + step
            else:
                cur = {"sign": sign, "start": t, "end": t + step}
                windows.append(cur)
            t += step
    hm = muhurta._hm
    return {
        "applicable": True, "birth_time_precision": precision,
        "windows": [{"lagna": K.SIGN_NAMES[w["sign"]], "start": hm(w["start"]), "end": hm(min(w["end"], 24.0)),
                     "in_prashna_trine": w["sign"] in trines} for w in windows],
        "heuristic": {"text": ("Traditional heuristic: the natal Lagna is often sought in the Prashna Lagna "
                               f"sign ({K.SIGN_NAMES[p_sign]}) or its trines. Windows marked below fit that "
                               "pattern. This only prioritises which time ranges to examine; it does not "
                               "determine the birth time."),
                      "source": SRC_PM, "verified": False},
        "guidance": [
            "Ask family about the circumstances of birth (before or after sunrise, day or night, hospital records).",
            "Use the chat's life-event questions to narrow the Lagna windows; each Lagna sign above "
            "describes a different body type and temperament.",
            "Treat any Lagna-dependent reading as provisional until the time is confirmed.",
        ],
    }
