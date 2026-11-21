"""Kundli matching (Ashtakoota / Guna Milan) with classical exceptions.

Deterministic and LLM-free. Everything is derived from the two natal Moons
(sign, degree, nakshatra, pada) plus, for the supplementary sections, the
locked chart facts.

Tables below are the standard North-Indian Ashtakoota tables. Where PyJHora
5.0 (`jhora.horoscope.match.compatibility.Ashtakoota`) was cross-checked:

  - Yoni animals, Gana classes, Nadi classes, Bhakoot (2/12, 5/9, 6/8) and
    the Tara count agree with the standard tables.
  - PyJHora's Varna sign map swaps Vaishya and Shudra (Taurus/Virgo/Capricorn
    are Vaishya, Gemini/Libra/Aquarius Shudra in the standard table), so the
    Varna koota here uses its own table, not PyJHora's.
  - PyJHora's Tara koota awards 1.5 points when the remainder is 3, 5 or 7
    (Vipat, Pratyak, Vadha) which inverts the classical rule; and its Bhakoot
    matrix has at least one wrong cell (Cancer groom / Aquarius bride, a 6/8
    pair, scores 7). Both are computed from the rule here instead.
  - PyJHora approximates the Vashya half-signs of Sagittarius/Capricorn from
    the nakshatra pada; here the exact Moon degree is used.
  - Score matrices (Vashya, Gana, Yoni) are PyJHora's Saravali tabulation;
    regional sources print slightly different values for a few cells, so
    those koota carry `verified: False` below.

Every rule carries an id, a source tag and a `verified` flag. A rule whose
wording varies between traditions is implemented but marked verified=False
and is never presented as established fact.
"""
from datetime import date

from jhora.horoscope.match import compatibility as _pj

from . import constants as K

MAX_SCORE = 36

SRC_BPHS = "Brihat Parashara Hora Shastra / Muhurta Chintamani (Ashtakoota)"
SRC_TABLE = "Standard Ashtakoota tables (North-Indian); matrix as tabulated in PyJHora 5.0 (Saravali)"
SRC_REGIONAL = "Regional / commentarial rule set — wording varies between traditions"

# ------------------------------------------------------------------ tables

VARNA_NAMES = ["Brahmin", "Kshatriya", "Vaishya", "Shudra"]       # rank 0 (highest)..3
# Moon sign -> varna (water=Brahmin, fire=Kshatriya, earth=Vaishya, air=Shudra)


def _varna_of(sign: int) -> int:
    # Aries Kshatriya, Taurus Vaishya, Gemini Shudra, Cancer Brahmin, ...
    return {0: 1, 1: 2, 2: 3, 3: 0}[sign % 4]


VASHYA_NAMES = ["Chatushpada", "Manava", "Jalachara", "Vanachara", "Keeta"]


def vashya_of(sign: int, degree: float) -> int:
    if sign in (0, 1):
        return 0
    if sign in (2, 5, 6, 10):
        return 1
    if sign in (3, 11):
        return 2
    if sign == 4:
        return 3
    if sign == 7:
        return 4
    if sign == 8:                       # Sagittarius: first half human, second quadruped
        return 1 if degree < 15 else 0
    return 0 if degree < 15 else 2      # Capricorn: first half quadruped, second aquatic


YONI_NAMES = ["Horse", "Elephant", "Sheep", "Serpent", "Dog", "Cat", "Rat", "Cow",
              "Buffalo", "Tiger", "Deer", "Monkey", "Mongoose", "Lion"]
# nakshatra 1..27 -> yoni animal index (PyJHora table verified against the standard list)
NAK_YONI = [0, 1, 2, 3, 3, 4, 5, 2, 5, 6, 6, 7, 8, 9, 8, 9, 10, 10, 4, 11, 12, 11, 13, 0, 13, 7, 1]
YONI_ENEMY_PAIRS = {frozenset(p) for p in [(7, 9), (1, 13), (0, 8), (4, 10), (3, 12), (11, 2), (5, 6)]}

GANA_NAMES = ["Deva", "Manushya", "Rakshasa"]
NAK_GANA = [0, 1, 2, 1, 0, 1, 0, 0, 2, 2, 1, 1, 0, 2, 0, 2, 0, 2, 2, 1, 1, 0, 2, 2, 1, 1, 0]

NADI_NAMES = ["Adi (Vata)", "Madhya (Pitta)", "Antya (Kapha)"]
NAK_NADI = [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2]

# Natural friendship (BPHS), ids 0 Sun .. 6 Saturn
_FRIENDS = {0: {1, 2, 4}, 1: {0, 3}, 2: {0, 1, 4}, 3: {0, 5}, 4: {0, 1, 2}, 5: {3, 6}, 6: {3, 5}}
_ENEMIES = {0: {5, 6}, 1: set(), 2: {3}, 3: {1}, 4: {3, 5}, 5: {0, 1}, 6: {0, 1, 2}}

# Name syllables (Namakshara) by nakshatra, 4 padas. Regional variants exist
# (notably Shravana), so these are labelled as one common convention.
NAME_SYLLABLES = [
    "Chu Che Cho La", "Li Lu Le Lo", "A I U E", "O Va Vi Vu", "Ve Vo Ka Ki", "Ku Gha Ng Chha",
    "Ke Ko Ha Hi", "Hu He Ho Da", "Di Du De Do", "Ma Mi Mu Me", "Mo Ta Ti Tu", "Te To Pa Pi",
    "Pu Sha Na Tha", "Pe Po Ra Ri", "Ru Re Ro Ta", "Ti Tu Te To", "Na Ni Nu Ne", "No Ya Yi Yu",
    "Ye Yo Bha Bhi", "Bhu Dha Pha Dha", "Bhe Bho Ja Ji", "Khi Khu Khe Kho", "Ga Gi Gu Ge",
    "Go Sa Si Su", "Se So Da Di", "Du Tha Jha Na", "De Do Cha Chi"]


def _rel(a: int, b: int) -> str:
    if b in _FRIENDS[a]:
        return "friend"
    if b in _ENEMIES[a]:
        return "enemy"
    return "neutral"


def lords_friendly(a: int, b: int) -> bool:
    """Same lord, or each regards the other as a friend / neutral-and-friend (>=4 pts)."""
    return maitri_points(a, b) >= 4


def maitri_points(a: int, b: int) -> float:
    if a == b:
        return 5.0
    ra, rb = _rel(a, b), _rel(b, a)
    pair = {ra, rb}
    if ra == rb == "friend":
        return 5.0
    if pair == {"friend", "neutral"}:
        return 4.0
    if ra == rb == "neutral":
        return 3.0
    if pair == {"friend", "enemy"}:
        return 1.0
    if pair == {"neutral", "enemy"}:
        return 0.5
    return 0.0


# ------------------------------------------------------------------ moon summary

def moon_of(facts: dict) -> dict:
    m = facts["planets"]["Moon"]
    nak = m["nakshatra"]
    sign = int(m["sign"])
    return {"sign": sign, "sign_name": K.SIGN_NAMES[sign], "degree": float(m["degree"]),
            "nak": int(nak["index"]), "nak_name": nak["name"], "pada": int(nak["pada"]),
            "sign_lord": K.SIGN_LORD[sign]}


def avakahada(facts: dict) -> dict:
    """Avakahada chakra from the natal Moon (standard tables)."""
    m = moon_of(facts)
    nak = m["nak"]
    items = {
        "varna": VARNA_NAMES[_varna_of(m["sign"])],
        "vashya": VASHYA_NAMES[vashya_of(m["sign"], m["degree"])],
        "yoni": YONI_NAMES[NAK_YONI[nak - 1]],
        "gana": GANA_NAMES[NAK_GANA[nak - 1]],
        "nadi": NADI_NAMES[NAK_NADI[nak - 1]],
        "nakshatra": m["nak_name"], "pada": m["pada"],
        "nakshatra_lord": K.PLANET_NAMES[K.NAK_LORD_SEQUENCE[(nak - 1) % 9]],
        "rashi": m["sign_name"], "rashi_lord": K.PLANET_NAMES[m["sign_lord"]],
        "name_syllable": NAME_SYLLABLES[nak - 1].split()[m["pada"] - 1],
    }
    return {"items": items,
            "notes": ["Computed from the natal Moon. Name syllables follow one common "
                      "convention; regional lists differ (e.g. for Shravana)."],
            "rule_id": "AVAK-1", "source": SRC_TABLE, "verified": True}


# ------------------------------------------------------------------ koota scoring

def _tara_count(from_nak: int, to_nak: int) -> int:
    n = (to_nak - from_nak) % 27 + 1
    return (n - 1) % 9 + 1


TARA_NAMES9 = ["Janma", "Sampat", "Vipat", "Kshema", "Pratyak", "Sadhana", "Vadha", "Mitra", "Ati-Mitra"]
_BAD_TARA = {3, 5, 7}


def koota_scores(groom: dict, bride: dict) -> list[dict]:
    """The eight kootas. `groom`/`bride` are moon_of() dicts."""
    out = []

    # 1. Varna -----------------------------------------------------------
    gv, bv = _varna_of(groom["sign"]), _varna_of(bride["sign"])
    out.append({
        "id": "varna", "name": "Varna", "max": 1, "score": 1 if gv <= bv else 0,
        "groom": VARNA_NAMES[gv], "bride": VARNA_NAMES[bv],
        "explanation": "Groom's varna must be equal to or higher than the bride's (Brahmin > "
                       "Kshatriya > Vaishya > Shudra), from the Moon signs. Indicates ego/temperament fit.",
        "rule_id": "MATCH-VARNA", "source": SRC_BPHS, "verified": True})

    # 2. Vashya ----------------------------------------------------------
    gs, bs = vashya_of(groom["sign"], groom["degree"]), vashya_of(bride["sign"], bride["degree"])
    out.append({
        "id": "vashya", "name": "Vashya", "max": 2, "score": float(_pj.VasiyaArray[bs][gs]),
        "groom": VASHYA_NAMES[gs], "bride": VASHYA_NAMES[bs],
        "explanation": "Mutual influence / dominance, from the Moon sign group "
                       "(Sagittarius and Capricorn split at 15 degrees).",
        "rule_id": "MATCH-VASHYA", "source": SRC_TABLE, "verified": False})

    # 3. Tara ------------------------------------------------------------
    t_gb = _tara_count(bride["nak"], groom["nak"])     # counted from the bride's star
    t_bg = _tara_count(groom["nak"], bride["nak"])
    pts = (0 if t_gb in _BAD_TARA else 1.5) + (0 if t_bg in _BAD_TARA else 1.5)
    out.append({
        "id": "tara", "name": "Tara (Dina)", "max": 3, "score": pts,
        "groom": f"{TARA_NAMES9[t_bg - 1]} ({t_bg}) from groom's star",
        "bride": f"{TARA_NAMES9[t_gb - 1]} ({t_gb}) from bride's star",
        "explanation": "Count each nakshatra from the other, divide by 9. Remainders 3, 5, 7 "
                       "(Vipat, Pratyak, Vadha) are unfavourable; 1.5 points for each favourable direction.",
        "rule_id": "MATCH-TARA", "source": SRC_BPHS, "verified": True})

    # 4. Yoni ------------------------------------------------------------
    gy, by = NAK_YONI[groom["nak"] - 1], NAK_YONI[bride["nak"] - 1]
    out.append({
        "id": "yoni", "name": "Yoni", "max": 4, "score": float(_pj.YoniArray[by][gy]),
        "groom": YONI_NAMES[gy], "bride": YONI_NAMES[by],
        "explanation": "Instinctive/physical compatibility by the nakshatra animal. Same animal 4; "
                       "the seven natural-enemy pairs score 0; other cells 1-3 per the Saravali matrix.",
        "rule_id": "MATCH-YONI", "source": SRC_TABLE, "verified": False,
        "verified_note": "Same-animal (4) and enemy-pair (0) cells are standard; intermediate cells vary by source."})

    # 5. Graha Maitri ----------------------------------------------------
    gl, bl = groom["sign_lord"], bride["sign_lord"]
    out.append({
        "id": "maitri", "name": "Graha Maitri", "max": 5, "score": maitri_points(gl, bl),
        "groom": f"{K.PLANET_NAMES[gl]} (lord of {groom['sign_name']})",
        "bride": f"{K.PLANET_NAMES[bl]} (lord of {bride['sign_name']})",
        "explanation": "Friendship between the two Moon-sign lords (natural friendship). Same lord or "
                       "mutual friends 5; friend+neutral 4; neutral+neutral 3; friend+enemy 1; "
                       "neutral+enemy 0.5; mutual enemies 0.",
        "rule_id": "MATCH-MAITRI", "source": SRC_BPHS, "verified": True})

    # 6. Gana ------------------------------------------------------------
    gg, bg = NAK_GANA[groom["nak"] - 1], NAK_GANA[bride["nak"] - 1]
    out.append({
        "id": "gana", "name": "Gana", "max": 6, "score": float(_pj.gana_array[bg][gg]),
        "groom": GANA_NAMES[gg], "bride": GANA_NAMES[bg],
        "explanation": "Temperament class of the nakshatra (Deva/Manushya/Rakshasa). Same gana 6; "
                       "Rakshasa with a different gana scores 0-1.",
        "rule_id": "MATCH-GANA", "source": SRC_TABLE, "verified": False,
        "verified_note": "Same-gana (6) and Rakshasa-mismatch cells are standard; the Deva/Manushya "
                         "asymmetry (5 vs 6) differs between sources."})

    # 7. Bhakoot ---------------------------------------------------------
    dist = (bride["sign"] - groom["sign"]) % 12 + 1          # bride's sign counted from groom's
    pair = tuple(sorted((dist, (groom["sign"] - bride["sign"]) % 12 + 1)))
    bad = pair in {(2, 12), (5, 9), (6, 8)}
    out.append({
        "id": "bhakoot", "name": "Bhakoot (Rashi)", "max": 7, "score": 0 if bad else 7,
        "groom": groom["sign_name"], "bride": bride["sign_name"],
        "explanation": f"Moon signs are {pair[0]}/{pair[1]} from each other. 2/12, 5/9 and 6/8 "
                       "relationships score 0 (Bhakoot dosha); all others 7.",
        "relationship": f"{pair[0]}/{pair[1]}",
        "rule_id": "MATCH-BHAKOOT", "source": SRC_BPHS, "verified": True})

    # 8. Nadi ------------------------------------------------------------
    gn, bn = NAK_NADI[groom["nak"] - 1], NAK_NADI[bride["nak"] - 1]
    out.append({
        "id": "nadi", "name": "Nadi", "max": 8, "score": 0 if gn == bn else 8,
        "groom": NADI_NAMES[gn], "bride": NADI_NAMES[bn],
        "explanation": "Same Nadi scores 0 (Nadi dosha, traditionally linked to constitution/progeny "
                       "concerns); different Nadis 8.",
        "rule_id": "MATCH-NADI", "source": SRC_BPHS, "verified": True})
    return out


# ------------------------------------------------------------------ exceptions

def _exc(id_, text, applies, verified=False, source=SRC_REGIONAL):
    return {"id": id_, "text": text, "applies": bool(applies), "verified": verified, "source": source}


def nadi_exceptions(g: dict, b: dict) -> dict:
    present = NAK_NADI[g["nak"] - 1] == NAK_NADI[b["nak"] - 1]
    excs = []
    if present:
        excs = [
            _exc("NADI-EX-1", "Same Moon sign but different nakshatras", g["sign"] == b["sign"] and g["nak"] != b["nak"]),
            _exc("NADI-EX-2", "Same nakshatra but different Moon signs", g["nak"] == b["nak"] and g["sign"] != b["sign"]),
            _exc("NADI-EX-3", "Same nakshatra but different padas", g["nak"] == b["nak"] and g["pada"] != b["pada"]),
            _exc("NADI-EX-4", "Moon-sign lords are the same planet or friends",
                 lords_friendly(g["sign_lord"], b["sign_lord"])),
        ]
    return {"present": present, "exceptions": excs,
            "cancelled": present and any(e["applies"] for e in excs)}


def bhakoot_exceptions(g: dict, b: dict, score: float) -> dict:
    present = score == 0
    excs = []
    if present:
        excs = [
            _exc("BHAK-EX-1", "Moon-sign lords are the same planet", g["sign_lord"] == b["sign_lord"]),
            _exc("BHAK-EX-2", "Moon-sign lords are mutual friends", g["sign_lord"] != b["sign_lord"] and
                 _rel(g["sign_lord"], b["sign_lord"]) == "friend" and _rel(b["sign_lord"], g["sign_lord"]) == "friend"),
        ]
    return {"present": present, "exceptions": excs,
            "cancelled": present and any(e["applies"] for e in excs)}


def gana_mitigation(g: dict, b: dict, kootas: dict) -> dict:
    present = kootas["gana"]["score"] <= 1
    excs = []
    if present:
        excs = [
            _exc("GANA-EX-1", "Moon-sign lords are the same planet or friends",
                 lords_friendly(g["sign_lord"], b["sign_lord"])),
            _exc("GANA-EX-2", "Bhakoot scores 7 and Graha Maitri is 4 or more",
                 kootas["bhakoot"]["score"] == 7 and kootas["maitri"]["score"] >= 4),
        ]
    return {"present": present, "exceptions": excs,
            "mitigated": present and any(e["applies"] for e in excs)}


# ------------------------------------------------------------------ mangal dosha

MANGAL_HOUSES = {1, 2, 4, 7, 8, 12}


def _house_from(sign_a: int, sign_b: int) -> int:
    return (sign_a - sign_b) % 12 + 1


def mangal_fallback(facts: dict) -> dict:
    """Simple Kuja dosha: Mars in 1/2/4/7/8/12 from Lagna, Moon or Venus,
    with the commonly listed cancellations. Labelled fallback."""
    p = facts["planets"]
    mars = p["Mars"]
    refs = {"lagna": facts["lagna"]["sign"], "moon": p["Moon"]["sign"], "venus": p["Venus"]["sign"]}
    houses = {k: _house_from(mars["sign"], s) for k, s in refs.items()}
    flags = {k: h in MANGAL_HOUSES for k, h in houses.items()}
    present = flags["lagna"] or flags["moon"]
    if flags["lagna"] and flags["moon"]:
        severity = "strong"
    elif present:
        severity = "moderate"
    elif flags["venus"]:
        severity = "mild"
    else:
        severity = "none"
    cancels = []
    if present or flags["venus"]:
        jup = p["Jupiter"]
        cancels = [
            _exc("MANGAL-CX-1", "Mars is in its own sign or exalted (Aries, Scorpio, Capricorn)",
                 mars["sign"] in (0, 7, 9)),
            _exc("MANGAL-CX-2", "Jupiter conjoins or aspects Mars (same sign or 5th/7th/9th from it)",
                 _house_from(jup["sign"], mars["sign"]) in (1, 5, 7, 9)),
            _exc("MANGAL-CX-3", "Mars is combust (weakened; some rule sets)",
                 bool(mars.get("combust"))),
            _exc("MANGAL-CX-4", "Mars is in Leo or Aquarius while placed in the 7th/8th (some rule sets)",
                 mars["sign"] in (4, 10) and houses["lagna"] in (7, 8)),
        ]
    return {"source": "fallback", "present": present, "severity": severity,
            "houses_from": houses, "flags": flags, "mars_sign": mars["sign_name"],
            "cancellations": cancels,
            "cancelled": present and any(c["applies"] for c in cancels),
            "rule_id": "MANGAL-1",
            "basis": "Simple fallback: Mars in 1/2/4/7/8/12 from Lagna or Moon (Venus = mild). "
                     "Some schools omit the 2nd house.",
            "verified": False}


def mangal_for(facts: dict, partner_facts: dict | None = None) -> dict:
    """Use P2's dosha.mangal_dosha when available, else the fallback.

    The fallback verdict always drives the summary fields; a P2 result is
    attached untouched as `engine_result` for transparency.
    """
    base = mangal_fallback(facts)
    try:
        from . import dosha
        fn = getattr(dosha, "mangal_dosha", None)
        if fn is not None:
            res = fn(facts, partner_facts) if partner_facts is not None else fn(facts)
            base["engine_result"] = res
            base["source"] = "dosha.mangal_dosha + fallback summary"
    except Exception as exc:       # never let an optional module break matching
        base["engine_error"] = f"{type(exc).__name__}: {exc}"
    return base


def mangal_pair(a: dict, b: dict) -> dict:
    ap = a["present"] and not a["cancelled"]
    bp = b["present"] and not b["cancelled"]
    if not a["present"] and not b["present"]:
        verdict, text = "none", "Neither chart shows Mangal dosha by the simple rule."
    elif a["present"] and b["present"]:
        verdict, text = "balanced", ("Both charts carry Mangal dosha, which traditional texts "
                                     "treat as mutually cancelling (MANGAL-PAIR-1).")
    elif ap or bp:
        verdict, text = "one_sided", ("Only one chart carries Mangal dosha. Traditionally this is "
                                      "weighed with the cancellations listed and the rest of the chart; "
                                      "it is a factor to discuss, not a verdict.")
    else:
        verdict, text = "cancelled", "Mangal dosha appears in one chart but a cancellation applies."
    return {"verdict": verdict, "text": text, "rule_id": "MANGAL-PAIR-1",
            "source": SRC_REGIONAL, "verified": False}


# ------------------------------------------------------------------ supplementary

def _d9_lagna(facts: dict) -> int | None:
    d9 = (facts.get("vargas") or {}).get("D9") or {}
    return d9.get("Lagna", {}).get("sign")


def d9_relation(gf: dict, bf: dict) -> dict:
    gl, bl = _d9_lagna(gf), _d9_lagna(bf)
    if gl is None or bl is None:
        return {"available": False}
    d = _house_from(bl, gl)
    harmonious = {1, 3, 5, 7, 9, 11}
    seventh_g = (gl + 6) % 12
    seventh_b = (bl + 6) % 12
    return {"available": True,
            "groom_d9_lagna": K.SIGN_NAMES[gl], "bride_d9_lagna": K.SIGN_NAMES[bl],
            "bride_from_groom": d,
            "groom_d9_7th": {"sign": K.SIGN_NAMES[seventh_g], "lord": K.PLANET_NAMES[K.SIGN_LORD[seventh_g]]},
            "bride_d9_7th": {"sign": K.SIGN_NAMES[seventh_b], "lord": K.PLANET_NAMES[K.SIGN_LORD[seventh_b]]},
            "bride_lagna_is_groom_7th": bl == seventh_g,
            "harmonious": d in harmonious,
            "text": (f"The two Navamsa Lagnas are {d} signs apart "
                     f"({'a supportive' if d in harmonious else 'a more demanding'} relationship in this "
                     "heuristic)."),
            "rule_id": "MATCH-D9", "source": SRC_REGIONAL, "verified": False}


def seventh_house(facts: dict, karaka: str) -> dict:
    h7 = facts["houses"][7]
    lord = facts["planets"][h7["lord"]]
    occupants = [n for n, p in facts["planets"].items() if p["house"] == 7]
    kar = facts["planets"][karaka]
    return {"sign": h7["sign_name"], "lord": h7["lord"],
            "lord_house": lord["house"], "lord_sign": lord["sign_name"],
            "occupants": occupants, "karaka": karaka, "karaka_house": kar["house"],
            "karaka_dignity": kar.get("dignity", []),
            "lord_in_dusthana": lord["house"] in (6, 8, 12)}


def dasha_context(facts: dict, today: date | None = None) -> dict:
    today = today or date.today()
    iso = today.isoformat()
    row = next((r for r in facts.get("vimshottari", {}).get("periods", [])
                if r["start"] <= iso < r["end"]), None)
    if not row:
        return {"available": False}
    maha, antar = row["maha"], row["antar"]
    owned = [h for h, v in facts["houses"].items() if v["lord"] == maha]
    in_dusthana = facts["planets"][maha]["house"] in (6, 8, 12)
    adverse = bool(set(owned) & {6, 8, 12}) and in_dusthana
    return {"available": True, "maha": maha, "antar": antar, "until": row["end"],
            "maha_lord_owns_houses": sorted(int(h) for h in owned),
            "maha_lord_in_dusthana": in_dusthana, "strongly_adverse": adverse,
            "rule_id": "MATCH-DASHA", "source": SRC_REGIONAL, "verified": False}


# ------------------------------------------------------------------ interpretation

BANDS = [
    (0, 17.5, "below_traditional_minimum",
     "Below the traditional 18-point threshold on this scheme. Many couples score here and do well; "
     "look at which kootas lost points and at the wider chart before drawing conclusions."),
    (17.5, 24.5, "acceptable", "Acceptable: meets the traditional minimum with room for the other factors to decide."),
    (24.5, 32.5, "good", "Good compatibility on this scheme."),
    (32.5, 36.1, "very_good", "Very high agreement on this scheme."),
]


def band_for(total: float) -> dict:
    for lo, hi, key, text in BANDS:
        if lo <= total < hi:
            return {"key": key, "text": text}
    return {"key": "very_good", "text": BANDS[-1][3]}


def match(groom_facts: dict, bride_facts: dict, *, today: date | None = None) -> dict:
    g, b = moon_of(groom_facts), moon_of(bride_facts)
    kootas = koota_scores(g, b)
    by_id = {k["id"]: k for k in kootas}
    total = sum(k["score"] for k in kootas)

    nadi = nadi_exceptions(g, b)
    bhak = bhakoot_exceptions(g, b, by_id["bhakoot"]["score"])
    gana = gana_mitigation(g, b, by_id)
    restored = (8 if nadi["cancelled"] else 0) + (7 if bhak["cancelled"] else 0)
    adjusted = min(MAX_SCORE, total + restored)

    known = (groom_facts["meta"].get("birth_time_precision") != "unknown",
             bride_facts["meta"].get("birth_time_precision") != "unknown")
    mg = mangal_for(groom_facts, bride_facts)
    mb = mangal_for(bride_facts, groom_facts)
    for flag, m in zip(known, (mg, mb)):
        if not flag:      # no trustworthy Lagna: judge from the Moon and Venus only
            m["flags"]["lagna"] = False
            m["houses_from"]["lagna"] = None
            m["present"] = m["flags"]["moon"]
            m["severity"] = "moderate" if m["present"] else ("mild" if m["flags"]["venus"] else "none")
            m["basis"] += " Birth time unknown: Lagna reference omitted."
    both_known = all(known)
    return {
        "time_known": {"groom": known[0], "bride": known[1]},
        "kootas": kootas,
        "total": total, "max": MAX_SCORE,
        "adjusted_total": adjusted,
        "adjusted_note": ("Adds back Nadi/Bhakoot points where a listed exception applies. "
                          "These exceptions are not universally accepted (verified: false)."
                          if restored else None),
        "band": band_for(total),
        "doshas": {"nadi": nadi, "bhakoot": bhak, "gana": gana},
        "mangal": {"groom": mg, "bride": mb, "pair": mangal_pair(mg, mb)},
        "navamsa": d9_relation(groom_facts, bride_facts) if both_known else {"available": False},
        "seventh_house": ({"groom": seventh_house(groom_facts, "Venus"),
                           "bride": seventh_house(bride_facts, "Jupiter")} if both_known else None),
        "dasha": {"groom": dasha_context(groom_facts, today), "bride": dasha_context(bride_facts, today)},
        "avakahada": {"groom": avakahada(groom_facts)["items"], "bride": avakahada(bride_facts)["items"]},
        "disclaimer": ("The Ashtakoota score is one traditional lens on Moon-based compatibility. "
                       "It is not decisive on its own: the full charts, the 7th houses, dasha periods "
                       "and the people's own circumstances matter more. Nothing here predicts that a "
                       "relationship will or will not succeed."),
    }
