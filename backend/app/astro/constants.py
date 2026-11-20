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

# Functional benefics / malefics / yogakaraka per lagna sign (Parashari)
FUNCTIONAL = {
    0: {"benefics": {0, 1, 4}, "malefics": {3, 5, 6}, "yogakaraka": None},          # Aries (Jup also yogakaraka-ish via 9/12)
    1: {"benefics": {3, 6}, "malefics": {4, 5, 1}, "yogakaraka": 6},                 # Taurus
    2: {"benefics": {5}, "malefics": {2, 4, 6, 0}, "yogakaraka": None},              # Gemini
    3: {"benefics": {2, 4}, "malefics": {5, 3, 6}, "yogakaraka": 2},                 # Cancer
    4: {"benefics": {2, 0}, "malefics": {5, 3, 6, 1}, "yogakaraka": 2},              # Leo
    5: {"benefics": {5}, "malefics": {2, 4, 1}, "yogakaraka": None},                 # Virgo
    6: {"benefics": {6, 3}, "malefics": {0, 4, 2}, "yogakaraka": 6},                 # Libra
    7: {"benefics": {4, 1, 0}, "malefics": {3, 5, 6}, "yogakaraka": None},           # Scorpio
    8: {"benefics": {0, 2, 4}, "malefics": {5, 6, 3}, "yogakaraka": None},           # Sagittarius
    9: {"benefics": {5, 3, 6}, "malefics": {2, 4, 1}, "yogakaraka": 5},              # Capricorn
    10: {"benefics": {5, 0, 2}, "malefics": {4, 1, 3}, "yogakaraka": 5},             # Aquarius
    11: {"benefics": {1, 2, 4}, "malefics": {0, 5, 6, 3}, "yogakaraka": None},       # Pisces
}

# Per-row source tag of the functional role table above.
FUNCTIONAL_SOURCE = "BPHS ch.34"
for _row in FUNCTIONAL.values():
    _row["source"] = FUNCTIONAL_SOURCE

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
