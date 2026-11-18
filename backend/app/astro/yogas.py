"""Classical yoga detection from locked chart facts.

`detect(facts)` returns [{id, name, level, conditions_fired, source}] where
level is "basic" (the bare textbook condition) or "classical" (the bare
condition plus the usual qualifying checks). Each fired condition has a stable
ID so a reading can say exactly which test passed.

Source strings name the text and topic only; verse/chapter numbers are
intentionally not asserted because they vary between editions and have not
been verified against a printed copy.
"""
from . import constants as K

KENDRA = {1, 4, 7, 10}
DUSTHANA = {6, 8, 12}
PID = {n: i for i, n in K.PLANET_NAMES.items()}

SRC_BPHS = "BPHS"
SRC_PHALADEEPIKA = "Phaladeepika"


def _house(sign, ref):
    return (sign - ref) % 12 + 1


def _lord(sign):
    return K.PLANET_NAMES[K.SIGN_LORD[sign]]


def _entry(yid, name, level, fired, source, **extra):
    return {"id": yid, "name": name, "level": level, "conditions_fired": fired,
            "source": source, **extra}


def gajakesari(facts):
    p = facts["planets"]
    jup, moon = p["Jupiter"], p["Moon"]
    if _house(jup["sign"], moon["sign"]) not in KENDRA:
        return []
    fired = ["GAJAKESARI.JUPITER_KENDRA_FROM_MOON"]
    if "debilitated" not in jup["dignity"]:
        fired.append("GAJAKESARI.JUPITER_NOT_DEBILITATED")
    if not jup["combust"]:
        fired.append("GAJAKESARI.JUPITER_NOT_COMBUST")
    if K.SIGN_LORD[jup["sign"]] not in K.NATURAL_ENEMIES[PID["Jupiter"]]:
        fired.append("GAJAKESARI.JUPITER_NOT_IN_ENEMY_SIGN")
    level = "classical" if len(fired) == 4 else "basic"
    return [_entry("GAJAKESARI", "Gajakesari", level, fired, SRC_PHALADEEPIKA + ", Gajakesari yoga")]


def budhaditya(facts):
    p = facts["planets"]
    if p["Sun"]["sign"] != p["Mercury"]["sign"]:
        return []
    return [_entry("BUDHADITYA", "Budhaditya", "basic", ["BUDHADITYA.SUN_MERCURY_CONJUNCT"],
                   SRC_PHALADEEPIKA + ", Budhaditya yoga", common=True,
                   mercury_combust=bool(p["Mercury"]["combust"]),
                   note="Mercury is always near the Sun, so this conjunction is common; "
                        "combust Mercury weakens it.")]


def neecha_bhanga(facts):
    p, lagna = facts["planets"], facts["lagna"]["sign"]
    moon = p["Moon"]["sign"]
    out = []
    for name, rec in p.items():
        if "debilitated" not in rec["dignity"] or PID[name] > 6:
            continue
        pid = PID[name]
        deb_sign = K.DEBILITATION[pid][0]
        exalt_sign = K.EXALTATION[pid][0]
        deb_lord, ex_lord = _lord(deb_sign), _lord(exalt_sign)
        fired = []

        def kendra(planet, ref):
            return _house(p[planet]["sign"], ref) in KENDRA

        if kendra(deb_lord, lagna):
            fired.append("NB.DEB_LORD_KENDRA_FROM_LAGNA")
        if kendra(deb_lord, moon):
            fired.append("NB.DEB_LORD_KENDRA_FROM_MOON")
        if kendra(ex_lord, lagna):
            fired.append("NB.EXALT_LORD_KENDRA_FROM_LAGNA")
        if kendra(ex_lord, moon):
            fired.append("NB.EXALT_LORD_KENDRA_FROM_MOON")
        disp = _lord(rec["sign"])
        if disp != name and rec["sign"] in K.reaches(disp, p[disp]["sign"]) \
                and p[disp]["sign"] != rec["sign"]:
            fired.append("NB.ASPECTED_BY_DISPOSITOR")
        if disp != name and p[disp]["sign"] == rec["sign"]:
            fired.append("NB.CONJUNCT_DISPOSITOR")
        if ex_lord != name and p[ex_lord]["sign"] == rec["sign"]:
            fired.append("NB.CONJUNCT_EXALTATION_LORD")
        if fired:
            out.append(_entry(f"NEECHA_BHANGA.{name.upper()}", f"Neecha Bhanga of {name}",
                              "classical", fired,
                              f"{SRC_BPHS}, Neecha Bhanga Raja Yoga; {SRC_PHALADEEPIKA}",
                              planet=name, debilitation_sign=K.SIGN_NAMES[deb_sign],
                              cancelled=True))
    return out


def parivartana(facts):
    p, lagna = facts["planets"], facts["lagna"]["sign"]
    seen, out = set(), []
    for a in range(7):
        an = K.PLANET_NAMES[a]
        for sign_a in K.OWN_SIGNS[a]:
            sb = p[an]["sign"]                       # sign A occupies
            b = K.SIGN_LORD[sb]
            if b == a or b > 6:
                continue
            bn = K.PLANET_NAMES[b]
            if p[bn]["sign"] != sign_a:              # B must occupy a sign owned by A
                continue
            key = frozenset((sign_a, sb))
            if key in seen:
                continue
            seen.add(key)
            houses = sorted((_house(sign_a, lagna), _house(sb, lagna)))
            if DUSTHANA.intersection(houses):
                kind, fired = "Dainya", "PARIVARTANA.DAINYA_6_8_12"
            elif 3 in houses:
                kind, fired = "Kahala", "PARIVARTANA.KAHALA_3"
            else:
                kind, fired = "Maha", "PARIVARTANA.MAHA_1_2_4_5_7_9_10_11"
            out.append(_entry(f"PARIVARTANA.{an.upper()}_{bn.upper()}",
                              f"{kind} Parivartana ({an} and {bn})", "basic", [fired],
                              SRC_BPHS + ", Parivartana yoga", kind=kind, houses=houses))
    return out


def viparita_raja(facts):
    p, houses = facts["planets"], facts["houses"]
    names = {6: "Harsha", 8: "Sarala", 12: "Vimala"}
    out = []
    for h, yname in names.items():
        lord = houses[h]["lord"]
        if p[lord]["house"] in DUSTHANA:
            out.append(_entry(f"VIPARITA_RAJA.{yname.upper()}", f"{yname} Viparita Raja Yoga", "basic",
                              [f"VIPARITA.LORD_{h}_IN_{p[lord]['house']}"],
                              SRC_BPHS + ", Viparita Raja yoga", lord=lord))
    return out


def detect(facts) -> list[dict]:
    out = []
    for fn in (gajakesari, budhaditya, neecha_bhanga, parivartana, viparita_raja):
        out.extend(fn(facts))
    return out
