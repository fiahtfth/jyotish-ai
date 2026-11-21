"""Domain constants: names, lordship, dignity, nakshatra tables.

Planet ids follow PyJHora convention: 0=Sun .. 6=Saturn, 7=Rahu, 8=Ketu,
'L'=Lagna. Sign ids are 0=Aries .. 11=Pisces.
"""

PLANET_NAMES = {
    0: "Sun", 1: "Moon", 2: "Mars", 3: "Mercury", 4: "Jupiter",
    5: "Venus", 6: "Saturn", 7: "Rahu", 8: "Ketu",
}
GRAHA_IDS = list(range(9))          # real grahas only (no Lagna)
LUMINARIES = {0, 1}
NATURAL_BENEFICS = {1, 3, 4, 5}
NATURAL_MALEFICS = {0, 2, 6, 7, 8}

SIGN_NAMES = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
SIGN_SANSKRIT = [
    "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
    "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena",
]
SIGN_ELEMENT = ["fire", "earth", "air", "water"] * 3
SIGN_MODALITY = ["movable", "fixed", "dual"] * 4   # Aries movable, Taurus fixed, ...

# Ruler of each sign (planet id)
SIGN_LORD = {
    0: 2, 1: 5, 2: 3, 3: 1, 4: 0, 5: 3,
    6: 5, 7: 2, 8: 4, 9: 6, 10: 6, 11: 4,
}

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha",
    "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana",
    "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada",
    "Revati",
]
# Vimshottari lord sequence repeating through nakshatras
NAK_LORD_SEQUENCE = [8, 5, 0, 1, 2, 7, 4, 6, 3]  # Ketu,Venus,Sun,Moon,Mars,Rahu,Jup,Sat,Mer
NAK_SPAN = 360.0 / 27.0

# Dignity tables (longitude range in absolute degrees)
EXALTATION = {0: (0, 10.0), 1: (1, 3.0), 2: (9, 28.0), 3: (5, 15.0),
              4: (3, 5.0), 5: (11, 27.0), 6: (6, 20.0)}
DEBILITATION = {p: ((s + 6) % 12, d) for p, (s, d) in EXALTATION.items()}
OWN_SIGNS = {0: [4], 1: [3], 2: [0, 7], 3: [2, 5], 4: [8, 11],
             5: [1, 6], 6: [9, 10]}
MOOLATRIKONA = {0: [(4, 0.0, 20.0)], 1: [(1, 3.0, 30.0)], 2: [(0, 0.0, 12.0)],
                3: [(5, 16.0, 20.0)], 4: [(8, 0.0, 10.0)], 5: [(6, 0.0, 15.0)],
                6: [(10, 0.0, 20.0)]}

# Gandanta junctions (water->fire): last pada of water sign + first pada of fire sign.
GANDANTA_JUNCTIONS = [(3, 4), (7, 8), (11, 0)]  # Cancer->Leo, Scorpio->Sag, Pisces->Aries
GANDANTA_PADA_SPAN = 10.0 / 3.0  # one nakshatra pada = 3.33 deg

# Functional benefics / malefics / yogakaraka per lagna sign (Parashari).
# Role sets follow BPHS ch.34 (lordship-based). The Lagna lord is always a
# benefic by role, so it is added to "benefics" and removed from "malefics"
# below even where a lordship-only reading would call it malefic (e.g. Venus
# for Taurus, who also owns the 6th). "notes" records where schools differ;
# the default listed here is kept in those cases.
FUNCTIONAL = {
    0: {"benefics": {0, 1, 4}, "malefics": {3, 5, 6}, "yogakaraka": None,           # Aries (Jup also yogakaraka-ish via 9/12)
        "notes": ["Moon (4L) is treated as benefic by default; BPHS lists only Saturn, Mercury, Venus as malefic."]},
    1: {"benefics": {0, 3, 6}, "malefics": {4, 5, 1}, "yogakaraka": 6,              # Taurus
        "notes": ["BPHS ch.34 names Saturn and the Sun as auspicious; Mercury (2L/5L) is kept benefic as most schools do.",
                  "Saturn is also the 9th lord, hence the badhaka for a fixed sign: yogakaraka and badhaka together."]},
    2: {"benefics": {5}, "malefics": {2, 4, 6, 0}, "yogakaraka": None,              # Gemini
        "notes": ["Saturn (8L/9L) is mixed; kept malefic by default although several schools treat it as benefic via the 9th."]},
    3: {"benefics": {2, 4}, "malefics": {5, 3, 6}, "yogakaraka": 2,                  # Cancer
        "notes": []},
    4: {"benefics": {2, 0, 4}, "malefics": {5, 3, 6, 1}, "yogakaraka": 2,            # Leo
        "notes": ["Jupiter (5L/8L) is added as benefic through its trikona lordship; the 8th lordship tempers it."]},
    5: {"benefics": {3, 5}, "malefics": {2, 4, 1}, "yogakaraka": None,              # Virgo
        "notes": ["Venus (2L/9L) is added as benefic through its 9th lordship."]},
    6: {"benefics": {6, 3}, "malefics": {0, 4, 2}, "yogakaraka": 6,                  # Libra
        "notes": []},
    7: {"benefics": {4, 1, 0}, "malefics": {3, 5, 6}, "yogakaraka": None,            # Scorpio
        "notes": []},
    8: {"benefics": {0, 2, 4}, "malefics": {5, 6, 3}, "yogakaraka": None,            # Sagittarius
        "notes": []},
    9: {"benefics": {5, 3, 6}, "malefics": {2, 4, 1}, "yogakaraka": 5,               # Capricorn
        "notes": []},
    10: {"benefics": {5, 0, 2}, "malefics": {4, 1, 3}, "yogakaraka": 5,              # Aquarius
         "notes": ["Sun/Mars/Mercury roles for Aquarius differ between schools; default retained, not verified here."]},
    11: {"benefics": {1, 2, 4}, "malefics": {0, 5, 6, 3}, "yogakaraka": None,        # Pisces
         "notes": ["Mars and Jupiter are sometimes read together as a yogakaraka pair; no single yogakaraka is set."]},
}

# Per-row source tag of the functional role table above.
FUNCTIONAL_SOURCE = "BPHS ch.34"
for _sign, _row in FUNCTIONAL.items():
    _row["source"] = FUNCTIONAL_SOURCE
    _ll = SIGN_LORD[_sign]
    _row["lordship_malefics"] = set(_row["malefics"])      # BPHS lordship reading, before the Lagna-lord override
    _row["benefics"] = set(_row["benefics"]) | {_ll}
    _row["malefics"] = set(_row["malefics"]) - {_ll}


def functional_roles(lagna_sign: int) -> dict:
    """Per-planet role tags for a Lagna, e.g. Taurus: Saturn -> yogakaraka + badhaka,
    Venus -> lagna_lord + malefic_by_lordship (a planet can hold several roles)."""
    row = FUNCTIONAL[lagna_sign]
    sign_of_house = lambda h: (lagna_sign + h - 1) % 12
    lord_of_house = lambda h: SIGN_LORD[sign_of_house(h)]
    owned = {p: sorted(h for h in range(1, 13) if lord_of_house(h) == p) for p in range(7)}
    badhaka = lord_of_house({"movable": 11, "fixed": 9, "dual": 7}[SIGN_MODALITY[lagna_sign]])
    roles = {}
    for pid in range(7):
        r = []
        if pid == SIGN_LORD[lagna_sign]:
            r.append("lagna_lord")
        if pid == row["yogakaraka"]:
            r.append("yogakaraka")
        if pid == badhaka:
            r.append("badhaka")
        if pid in (lord_of_house(2), lord_of_house(7)):
            r.append("maraka")
        if pid in row["benefics"] and pid != SIGN_LORD[lagna_sign]:
            r.append("benefic_by_lordship")
        if pid in row["lordship_malefics"]:
            r.append("malefic_by_lordship")
        roles[PLANET_NAMES[pid]] = r
    return roles


# Combustion orbs (degrees from Sun) — Surya Siddhanta defaults.
COMBUST_ORB = {1: 12.0, 2: 17.0, 3: 14.0, 4: 11.0, 5: 10.0, 6: 15.0}
# Retrograde Mercury / Venus are combust within a narrower orb.
COMBUST_ORB_RETROGRADE = {3: 12.0, 5: 8.0}
# Named tables selected by CalcSettings.combust_table. "wide_variant" is a
# secondary-source variant (Jupiter 12°, Saturn 16°), not a second siddhanta.
COMBUST_TABLES = {
    "surya_siddhanta": (COMBUST_ORB, COMBUST_ORB_RETROGRADE),
    "wide_variant": ({**COMBUST_ORB, 4: 12.0, 6: 16.0}, COMBUST_ORB_RETROGRADE),
}


def combust_orb(pid, retro=False, table="surya_siddhanta"):
    """Orb (degrees from the Sun) inside which `pid` is combust; None if it cannot be."""
    orbs, retro_orbs = COMBUST_TABLES[table]
    if retro and pid in retro_orbs:
        return retro_orbs[pid]
    return orbs.get(pid)


# Natural enemies (BPHS ch.3), used for enemy-sign tests.
NATURAL_ENEMIES = {0: {5, 6}, 1: set(), 2: {3}, 3: {1}, 4: {3, 5}, 5: {0, 1}, 6: {0, 1, 2}}
# Natural friends (BPHS ch.3, Naisargika maitri); planets in neither set are neutral.
NATURAL_FRIENDS = {0: {1, 2, 4}, 1: {0, 3}, 2: {0, 1, 4}, 3: {0, 5}, 4: {0, 1, 2},
                   5: {3, 6}, 6: {3, 5}}


def natural_relation(pid: int, other: int) -> str:
    """'friend' | 'neutral' | 'enemy' (BPHS ch.3 natural relationship of pid towards other)."""
    if other in NATURAL_FRIENDS.get(pid, set()):
        return "friend"
    if other in NATURAL_ENEMIES.get(pid, set()):
        return "enemy"
    return "neutral"


# Graha drishti per BPHS ch.26: every graha aspects the 7th; Mars 4/8, Jupiter 5/9,
# Saturn 3/10. Rahu/Ketu 5/9 (and 2/12 in some texts) are a school variant, kept
# out of this table; `ASPECTS` above still carries the legacy node 5/9 entries.
PARASHARI_ASPECTS = {"Mars": (4, 7, 8), "Jupiter": (5, 7, 9), "Saturn": (3, 7, 10)}
NODE_ASPECT_VARIANT = (5, 7, 9)


def parashari_reaches(name, sign, include_node_variant=False):
    """Signs aspected (incl. occupied) by `name` from `sign`; nodes get only the 7th
    unless include_node_variant (5/9) is requested."""
    if name in ("Rahu", "Ketu") and include_node_variant:
        houses = NODE_ASPECT_VARIANT
    else:
        houses = PARASHARI_ASPECTS.get(name, (7,))
    return {sign, *((sign + h - 1) % 12 for h in houses)}


KENDRA_HOUSES = {1, 4, 7, 10}
TRIKONA_HOUSES = {1, 5, 9}
DUSTHANA_HOUSES = {6, 8, 12}
UPACHAYA_HOUSES = {3, 6, 10, 11}


def house_from(sign: int, ref_sign: int) -> int:
    """1-based house of `sign` counted from `ref_sign` (whole sign)."""
    return (int(sign) - int(ref_sign)) % 12 + 1

HEALTH_DISCLAIMER = ("This is a traditional astrological interpretation. "
                     "Please follow your clinician’s advice for health concerns.")

# Domain -> (relevant natal houses, primary varga, jaimini significator key)
DOMAINS = {
    "career":     {"houses": [10, 6, 2, 11], "varga": "D10", "karaka": "Amatyakaraka", "arudhas": ["A10"], "label": "career or professional direction"},
    "education":  {"houses": [4, 5, 9], "varga": "D24", "karaka": "Matrukaraka", "arudhas": ["A5"], "label": "education or studies"},
    "relationship": {"houses": [7, 5, 8], "varga": "D9", "karaka": "Darakaraka", "arudhas": ["A7", "A12"], "label": "an important relationship or family milestone"},
    "relocation": {"houses": [4, 3, 9, 12], "varga": "D4", "karaka": "Matrukaraka", "arudhas": ["A4"], "label": "a change of residence or relocation"},
    "finance":    {"houses": [2, 11, 5, 9], "varga": "D2", "karaka": "Amatyakaraka", "arudhas": ["A2", "A11"], "label": "a significant financial or professional responsibility"},
    "direction":  {"houses": [1, 5, 9], "varga": "D1", "karaka": "Atmakaraka", "arudhas": ["A1"], "label": "a major change in personal direction"},
    "children": {"houses": [5, 9], "varga": "D7", "karaka": "Putrakaraka", "arudhas": ["A5"], "label": "children and creative legacy"},
    "parents": {"houses": [9, 4], "varga": "D12", "karaka": "Matrukaraka", "arudhas": ["A9", "A4"], "label": "parents and lineage"},
    "debt": {"houses": [6, 2], "varga": "D6", "karaka": "Gnatikaraka", "arudhas": ["A6"], "label": "debt"},
    "litigation": {"houses": [6, 7], "varga": "D6", "karaka": "Gnatikaraka", "arudhas": ["A6"], "label": "litigation"},
    "health":     {"houses": [1, 6, 8, 12], "varga": "D6", "karaka": "Gnatikaraka", "arudhas": ["A6", "A8"], "label": "health or physical resilience", "disclaimer": HEALTH_DISCLAIMER},
    "property":   {"houses": [4, 2, 11], "varga": "D4", "karaka": "Matrukaraka", "arudhas": ["A4"], "label": "property, home or vehicles"},
}
MIN_CALIBRATION_AGE_FOR_DOMAIN = {"relationship": 21, "career": 16, "finance": 16}


def min_age_for_domain(domain: str) -> int:
    """Youngest age (years) at which a domain is read in calibration (0 = no floor)."""
    return MIN_CALIBRATION_AGE_FOR_DOMAIN.get(domain, 0)


# Secondary natal-promise houses read beside the primary house (DOMAINS[d]["houses"][0]).
PROMISE_SECONDARY_HOUSES = {"finance": [11], "education": [5, 9]}

# Traditional remedial significators per domain — upaya is always attributed
# to tradition, never presented as a guaranteed fix.
DOMAIN_REMEDIES = {
    "career": ("Saturn", "Saturday observance — service to workers, sesame oil lamp at sunset"),
    "education": ("Mercury", "Wednesday observance — study of a shastra, gift of books or green items"),
    "relationship": ("Venus", "Friday observance — white flowers at a Devi shrine, sweets shared with women"),
    "marriage": ("Venus", "Friday observance — white flowers at a Devi shrine, sweets shared with women"),
    "relocation": ("Rahu", "Saturday observance — coconut donation, feeding the poor"),
    "finance": ("Jupiter", "Thursday observance — yellow items donated to a teacher or temple"),
    "direction": ("Jupiter", "Thursday observance — yellow items donated to a teacher or temple"),
    "children": ("Jupiter", "Thursday observance — feeding children, turmeric donation"),
    "parents": ("Sun", "Sunday observance — water offering (arghya) to the rising Sun"),
    "debt": ("Mars", "Tuesday observance — Hanuman Chalisa, jaggery donation"),
    "litigation": ("Mars", "Tuesday observance — Hanuman Chalisa, jaggery donation"),
    "health": ("Sun", "Sunday observance — arghya to the Sun, Aditya Hridaya Stotra"),
    "property": ("Mars", "Tuesday observance — Hanuman worship, donation of red items"),
}

VARGA_FUNCTIONS = {}  # filled lazily in engine to avoid importing jhora at module import time

ASPECTS = {"Mars": (4, 7, 8), "Jupiter": (5, 7, 9), "Saturn": (3, 7, 10),
           "Rahu": (5, 7, 9), "Ketu": (5, 7, 9)}


def reaches(name, sign):
    return {sign, *((sign + h - 1) % 12 for h in ASPECTS.get(name, (7,)))}
