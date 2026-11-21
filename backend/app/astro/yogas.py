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


BUDHADITYA_TIGHT_ORB = 3.0   # Mercury this close to the Sun: deeply combust, yoga not counted


def budhaditya(facts):
    p = facts["planets"]
    if p["Sun"]["sign"] != p["Mercury"]["sign"]:
        return []
    extra, fired = {}, ["BUDHADITYA.SUN_MERCURY_CONJUNCT"]
    sun_l, mer_l = p["Sun"].get("abs_longitude"), p["Mercury"].get("abs_longitude")
    if sun_l is not None and mer_l is not None:
        sep = abs(sun_l - mer_l) % 360
        sep = min(sep, 360 - sep)
        extra["separation_deg"] = round(sep, 2)
        if sep < BUDHADITYA_TIGHT_ORB:
            extra["cancelled_by"] = ["BUDHADITYA.MERCURY_DEEP_COMBUST"]
            extra["grade"] = "not formed (Mercury deeply combust)"
        else:
            fired.append("BUDHADITYA.MERCURY_OUTSIDE_TIGHT_ORB")
            extra["grade"] = "weakened (combust)" if p["Mercury"]["combust"] else "formed"
    return [_entry("BUDHADITYA", "Budhaditya", "basic", fired,
                   SRC_PHALADEEPIKA + ", Budhaditya yoga", common=True,
                   mercury_combust=bool(p["Mercury"]["combust"]),
                   participants=["Sun", "Mercury"],
                   note="Mercury is always near the Sun, so this conjunction is common; "
                        "combust Mercury weakens it, and within 3 degrees it is not counted.",
                   **extra)]


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


# ----------------------------------------------------------------- Raja / Dhana / others

TRIKONA = {1, 5, 9}
STRONG_DIGNITY = {"exalted", "own sign", "moolatrikona"}


def _hl(facts, h):
    """Lord of house h (tolerates int or str house keys after a JSON round trip)."""
    hs = facts["houses"]
    return (hs[h] if h in hs else hs[str(h)])["lord"]


def _owned(facts, name):
    return [h for h in range(1, 13) if _hl(facts, h) == name]


def _link(facts, a, b, one_way=False):
    """Parashari links between two planets: conjunction, sign exchange, mutual aspect
    and (one_way=True) one planet aspecting the other — the fourth, weaker
    sambandha (BPHS)."""
    p = facts["planets"]
    sa, sb = p[a]["sign"], p[b]["sign"]
    out = []
    if sa == sb:
        out.append("CONJUNCTION")
    if _lord(sa) == b and _lord(sb) == a:
        out.append("EXCHANGE")
    if sa != sb and sb in K.reaches(a, sa) and sa in K.reaches(b, sb):
        out.append("MUTUAL_ASPECT")
    elif one_way and sa != sb and "EXCHANGE" not in out:
        if sb in K.parashari_reaches(a, sa):
            out.append(f"ASPECT_BY_{a.upper()}")
        elif sa in K.parashari_reaches(b, sb):
            out.append(f"ASPECT_BY_{b.upper()}")
    return out


def _quality(facts, names, prefix):
    """Qualifying checks shared by the classical level."""
    p, fired, ok = facts["planets"], [], True
    for tag, test in (("NOT_DEBILITATED", lambda r: "debilitated" not in r["dignity"]),
                      ("NOT_COMBUST", lambda r: not r["combust"]),
                      ("NOT_IN_DUSTHANA", lambda r: r["house"] not in DUSTHANA)):
        if all(test(p[n]) for n in names):
            fired.append(f"{prefix}.{tag}")
        else:
            ok = False
    return fired, ok


def raja_yoga(facts):
    """Kendra-lord x trikona-lord link, and the yogakaraka placed in kendra/trikona."""
    p, out, seen = facts["planets"], [], set()
    # Lagna (house 1) is a kendra too, but iterated last: when a pair also
    # qualifies via a 4/7/10 kendra, that framing keeps the established
    # RAJA_YOGA.<KENDRA>_<TRIKONA> id; lagna combos add the new detections.
    kendra_lords = {h: _hl(facts, h) for h in (4, 7, 10, 1)}
    trikona_lords = {h: _hl(facts, h) for h in (1, 5, 9)}
    for kh, kl in kendra_lords.items():
        for th, tl in trikona_lords.items():
            if kl == tl or kl not in p or tl not in p or frozenset((kl, tl)) in seen:
                continue
            kinds = _link(facts, kl, tl, one_way=True)
            if not kinds:
                continue
            seen.add(frozenset((kl, tl)))
            one_way_only = all(k.startswith("ASPECT_BY_") for k in kinds)
            fired = [f"RAJA.KENDRA_TRIKONA_{k}" for k in kinds]
            extra, ok = _quality(facts, (kl, tl), "RAJA")
            out.append(_entry(f"RAJA_YOGA.{kl.upper()}_{tl.upper()}",
                              f"Raja Yoga ({kl} lord of {kh}, {tl} lord of {th})",
                              "classical" if ok else "basic", fired + extra,
                              SRC_BPHS + ", Raja yoga (kendra and trikona lords)",
                              kendra_lord=kl, trikona_lord=tl, houses=[kh, th], links=kinds,
                              participants=[kl, tl],
                              **({"link_strength": "one-way aspect (weaker sambandha)"}
                                 if one_way_only else {})))
    yk = (facts.get("functional") or {}).get("yogakaraka")
    if yk and yk in p:
        rec = p[yk]
        own = _owned(facts, yk)
        in_place = rec["house"] in KENDRA | TRIKONA
        if in_place and any(h in KENDRA for h in own) and any(h in TRIKONA for h in own):
            fired = [f"RAJA.YOGAKARAKA_IN_{'TRIKONA' if rec['house'] in TRIKONA else 'KENDRA'}_{rec['house']}"]
            if STRONG_DIGNITY & set(rec["dignity"]):
                fired.append("RAJA.YOGAKARAKA_OWN_OR_EXALTED")
            if rec.get("vargottama"):
                fired.append("RAJA.YOGAKARAKA_VARGOTTAMA")
            extra, ok = _quality(facts, (yk,), "RAJA.YOGAKARAKA")
            out.append(_entry(f"RAJA_YOGA.YOGAKARAKA.{yk.upper()}", f"Yogakaraka Raja Yoga ({yk})",
                              "classical" if ok else "basic", fired + extra,
                              SRC_BPHS + ", Yogakaraka (ch. on functional roles)",
                              planet=yk, houses_owned=own, placed_in=rec["house"], participants=[yk]))
    return out


def dhana_yoga(facts):
    """Links among the lords of 1/2/5/9/11; 2L-11L is the primary wealth link."""
    p, out, seen = facts["planets"], [], set()
    hs = (1, 2, 5, 9, 11)
    for i, a in enumerate(hs):
        for b in hs[i + 1:]:
            la, lb = _hl(facts, a), _hl(facts, b)
            if la == lb or la not in p or lb not in p or frozenset((la, lb)) in seen:
                continue
            kinds = _link(facts, la, lb)
            if not kinds:
                continue
            seen.add(frozenset((la, lb)))
            fired = [f"DHANA.LORD_{a}_LORD_{b}_{k}" for k in kinds]
            extra, ok = _quality(facts, (la, lb), "DHANA")
            wealth = bool({a, b} & {2, 11})
            out.append(_entry(f"DHANA_YOGA.L{a}_L{b}", f"Dhana Yoga ({la} lord of {a}, {lb} lord of {b})",
                              "classical" if (ok and wealth) else "basic", fired + extra,
                              SRC_BPHS + ", Dhana yoga",
                              lords=[la, lb], houses=[a, b], links=kinds, participants=[la, lb],
                              primary_link=(a, b) == (2, 11)))
    return out


def chandra_mangala(facts):
    p = facts["planets"]
    if p["Moon"]["sign"] != p["Mars"]["sign"]:
        return []
    fired = ["CHANDRA_MANGALA.MOON_MARS_CONJUNCT"]
    extra, ok = _quality(facts, ("Moon", "Mars"), "CHANDRA_MANGALA")
    return [_entry("CHANDRA_MANGALA", "Chandra-Mangala", "classical" if ok else "basic",
                   fired + extra, "Classical Jyotish compilations, Chandra-Mangala yoga",
                   houses=[p["Moon"]["house"]], participants=["Moon", "Mars"])]


PANCHA_MAHAPURUSHA = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa",
                      "Venus": "Malavya", "Saturn": "Sasa"}


def pancha_mahapurusha(facts):
    p, out = facts["planets"], []
    for name, yname in PANCHA_MAHAPURUSHA.items():
        rec = p[name]
        strong = {"own sign", "exalted"} & set(rec["dignity"])
        if not strong or rec["house"] not in KENDRA:
            continue
        fired = [f"PMP.{yname.upper()}.{'EXALTED' if 'exalted' in strong else 'OWN_SIGN'}",
                 f"PMP.{yname.upper()}.KENDRA_{rec['house']}_FROM_LAGNA"]
        if not rec["combust"]:
            fired.append(f"PMP.{yname.upper()}.NOT_COMBUST")
        if rec.get("vargottama"):
            fired.append(f"PMP.{yname.upper()}.VARGOTTAMA")
        out.append(_entry(f"PANCHA_MAHAPURUSHA.{yname.upper()}", f"{yname} Mahapurusha Yoga ({name})",
                          "classical" if not rec["combust"] else "basic", fired,
                          SRC_BPHS + ", Pancha-Mahapurusha yoga", planet=name, participants=[name]))
    return out


# Lakshmi yoga: the classical statement (9th lord in own/exalted sign in a kendra/trikona
# with a strong Lagna lord) is reproduced in several editions with different definitions of
# "strong"; the exact source wording has not been checked here, so it is disabled.
LAKSHMI_ENABLED = False


def lakshmi(facts):
    p = facts["planets"]
    l9, l1 = _hl(facts, 9), _hl(facts, 1)
    r9 = p[l9]
    if not (STRONG_DIGNITY & set(r9["dignity"]) and r9["house"] in KENDRA | TRIKONA):
        return []
    if not (STRONG_DIGNITY & set(p[l1]["dignity"]) or p[l1]["house"] in KENDRA | TRIKONA):
        return []
    return [_entry("LAKSHMI", "Lakshmi Yoga", "basic",
                   ["LAKSHMI.LORD_9_STRONG_IN_KENDRA_TRIKONA", "LAKSHMI.LAGNA_LORD_STRONG"],
                   SRC_BPHS + ", Lakshmi yoga (unverified wording)", verified=False)]


# ----------------------------------------------------------------- lunar / solar / others
# BPHS ch.37 (Chandra and Surya yogas), Phaladeepika ch.6. Moon yogas exclude the
# Sun and the nodes; Sun yogas exclude the Moon and the nodes.

SRC_BPHS_LUNAR = "BPHS ch.37 (yogas from the Moon); Phaladeepika ch.6"
SRC_BPHS_SOLAR = "BPHS ch.37 (yogas from the Sun); Phaladeepika ch.6"
_TRUE_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")


def _in_house_from(facts, ref_name, h, exclude):
    p = facts["planets"]
    ref = p[ref_name]["sign"]
    return sorted(n for n in _TRUE_PLANETS
                  if n not in exclude and n != ref_name and _house(p[n]["sign"], ref) == h)


def lunar_yogas(facts):
    p, out = facts["planets"], []
    ex = ("Sun",)
    second, twelfth = _in_house_from(facts, "Moon", 2, ex), _in_house_from(facts, "Moon", 12, ex)
    if second and twelfth:
        out.append(_entry("DURUDHARA", "Durudhara", "classical",
                          ["DURUDHARA.PLANETS_2ND_AND_12TH_FROM_MOON"], SRC_BPHS_LUNAR,
                          planets_2nd=second, planets_12th=twelfth))
    elif second:
        out.append(_entry("SUNAPHA", "Sunapha", "classical", ["SUNAPHA.PLANET_2ND_FROM_MOON"],
                          SRC_BPHS_LUNAR, planets=second))
    elif twelfth:
        out.append(_entry("ANAPHA", "Anapha", "classical", ["ANAPHA.PLANET_12TH_FROM_MOON"],
                          SRC_BPHS_LUNAR, planets=twelfth))
    else:
        out.append(kemadruma(facts))
    return out


def kemadruma(facts):
    """No planet (Sun and nodes excluded) 2nd or 12th from the Moon. Cancellations are
    listed individually; only verified ones set status 'cancelled'. Wording is
    deliberately non-fatal: a traditional pattern of needing self-reliance."""
    p, lagna = facts["planets"], facts["lagna"]["sign"]
    moon = p["Moon"]["sign"]
    others = [n for n in _TRUE_PLANETS if n not in ("Sun", "Moon")]
    cx = []
    k_moon = sorted(n for n in others if _house(p[n]["sign"], moon) in KENDRA)
    if k_moon:
        cx.append({"id": "KEMA.CX.PLANET_KENDRA_FROM_MOON", "planets": k_moon, "verified": True,
                   "source": "BPHS ch.37 (Kemadruma bhanga)"})
    k_lag = sorted(n for n in others if _house(p[n]["sign"], lagna) in KENDRA)
    if k_lag:
        cx.append({"id": "KEMA.CX.PLANET_KENDRA_FROM_LAGNA", "planets": k_lag, "verified": True,
                   "source": "BPHS ch.37 (Kemadruma bhanga)"})
    conj = sorted(n for n in others if p[n]["sign"] == moon)
    if conj:
        cx.append({"id": "KEMA.CX.MOON_CONJUNCT_PLANET", "planets": conj, "verified": False,
                   "source": "popular compilations (Moon joined by a planet)"})
    if moon in K.parashari_reaches("Jupiter", p["Jupiter"]["sign"]) and p["Jupiter"]["sign"] != moon:
        cx.append({"id": "KEMA.CX.JUPITER_ASPECTS_MOON", "verified": False,
                   "source": "popular compilations (Jupiter's aspect on the Moon)"})
    e = _entry("KEMADRUMA", "Kemadruma", "basic", ["KEMADRUMA.NO_PLANET_2ND_12TH_FROM_MOON"],
               SRC_BPHS_LUNAR, arishta_type=True, cancellations=cx,
               wording="A traditional pattern that asks for self-reliance and steady routines; "
                       "it is not a prediction of hardship.")
    verified = [c["id"] for c in cx if c["verified"]]
    if verified:
        e["cancelled_by"] = verified
    return e


def solar_yogas(facts):
    ex = ("Moon",)
    second, twelfth = _in_house_from(facts, "Sun", 2, ex), _in_house_from(facts, "Sun", 12, ex)
    if second and twelfth:
        return [_entry("UBHAYACHARI", "Ubhayachari", "classical",
                       ["UBHAYACHARI.PLANETS_2ND_AND_12TH_FROM_SUN"], SRC_BPHS_SOLAR,
                       planets_2nd=second, planets_12th=twelfth)]
    if second:
        return [_entry("VESI", "Vesi", "classical", ["VESI.PLANET_2ND_FROM_SUN"], SRC_BPHS_SOLAR,
                       planets=second)]
    if twelfth:
        return [_entry("VASI", "Vasi", "classical", ["VASI.PLANET_12TH_FROM_SUN"], SRC_BPHS_SOLAR,
                       planets=twelfth)]
    return []


def adhi(facts):
    """Benefics (Mercury, Jupiter, Venus) in the 6th, 7th, 8th from the Moon."""
    p = facts["planets"]
    moon = p["Moon"]["sign"]
    there = {n: _house(p[n]["sign"], moon) for n in ("Mercury", "Jupiter", "Venus")}
    placed = sorted(n for n, h in there.items() if h in (6, 7, 8))
    if len(placed) < 2:
        return []
    houses_hit = sorted({there[n] for n in placed})
    level = "classical" if len(placed) == 3 else "basic"
    return [_entry("ADHI", "Adhi Yoga", level,
                   [f"ADHI.{n.upper()}_IN_{there[n]}_FROM_MOON" for n in placed],
                   "BPHS ch.37; Phaladeepika ch.6 (Adhi yoga)", planets=placed, houses=houses_hit,
                   participants=placed)]


def amala(facts):
    p = facts["planets"]
    out, fired, planets = [], [], set()
    for ref_name, ref in (("LAGNA", facts["lagna"]["sign"]), ("MOON", p["Moon"]["sign"])):
        for n in ("Mercury", "Jupiter", "Venus") + (("Moon",) if ref_name == "LAGNA" else ()):
            if _house(p[n]["sign"], ref) == 10:
                fired.append(f"AMALA.{n.upper()}_10TH_FROM_{ref_name}")
                planets.add(n)
    if fired:
        out.append(_entry("AMALA", "Amala Yoga", "basic", fired,
                          SRC_PHALADEEPIKA + " ch.6 (Amala yoga)", planets=sorted(planets),
                          participants=sorted(planets)))
    return out


def parvata(facts):
    """Benefics in kendras; 6th and 8th empty or occupied only by benefics (BPHS ch.36)."""
    p = facts["planets"]
    ben = ("Mercury", "Jupiter", "Venus", "Moon")
    in_kendra = sorted(n for n in ben if p[n]["house"] in KENDRA)
    if not in_kendra:
        return []
    bad = sorted(n for n, r in p.items() if r["house"] in (6, 8) and n not in ben)
    if bad:
        return []
    return [_entry("PARVATA", "Parvata Yoga", "basic",
                   ["PARVATA.BENEFIC_IN_KENDRA", "PARVATA.6TH_8TH_FREE_OF_MALEFICS"],
                   SRC_BPHS + " ch.36 (Parvata yoga)", planets=in_kendra)]


def saraswati(facts):
    """Jupiter, Venus, Mercury in kendra/trikona/2nd; Jupiter in own, exalted or friendly sign
    (Phaladeepika ch.6)."""
    p = facts["planets"]
    good = KENDRA | TRIKONA | {2}
    if not all(p[n]["house"] in good for n in ("Jupiter", "Venus", "Mercury")):
        return []
    jup = p["Jupiter"]
    jl = K.SIGN_LORD[jup["sign"]]
    jup_ok = bool(STRONG_DIGNITY & set(jup["dignity"])) or K.natural_relation(4, jl) == "friend"
    if not jup_ok:
        return []
    return [_entry("SARASWATI", "Saraswati Yoga", "classical",
                   ["SARASWATI.JUP_VEN_MER_KENDRA_TRIKONA_2", "SARASWATI.JUPITER_DIGNIFIED"],
                   SRC_PHALADEEPIKA + " ch.6 (Saraswati yoga)",
                   participants=["Jupiter", "Venus", "Mercury"])]


def shakata(facts):
    """Arishta-type: Moon in 6/8/12 from Jupiter. Cancelled when the Moon is in a kendra
    from the Lagna (Phaladeepika ch.6). Non-fatal wording."""
    p = facts["planets"]
    h = _house(p["Moon"]["sign"], p["Jupiter"]["sign"])
    if h not in DUSTHANA:
        return []
    e = _entry("SHAKATA", "Shakata", "basic", [f"SHAKATA.MOON_{h}_FROM_JUPITER"],
               SRC_PHALADEEPIKA + " ch.6 (Shakata yoga and its cancellation)", arishta_type=True,
               wording="A traditional pattern of fortunes that rise and dip in cycles; "
                       "not a prediction of loss.")
    if p["Moon"]["house"] in KENDRA:
        e["cancelled_by"] = ["SHAKATA.CX.MOON_KENDRA_FROM_LAGNA"]
    return [e]


def _status(entries, facts):
    """status: 'active' (classical conditions met), 'conditional' (basic only) or
    'cancelled' (a participant is debilitated and no Neecha Bhanga rescues it)."""
    rescued = {e.get("planet") for e in entries if e["id"].startswith("NEECHA_BHANGA.")}
    for e in entries:
        if e.get("cancelled_by"):
            e["status"] = "cancelled"
            continue
        cancel = [n for n in e.get("participants", [])
                  if "debilitated" in (facts["planets"].get(n, {}).get("dignity") or []) and n not in rescued]
        if cancel:
            e["status"] = "cancelled"
            e["cancelled_by"] = [f"DEBILITATED_{n.upper()}_NO_NEECHA_BHANGA" for n in cancel]
        else:
            e["status"] = "active" if e["level"] == "classical" else "conditional"
    return entries


def detect(facts, include_unverified: bool = False) -> list[dict]:
    """All detectors; a detector whose required facts are absent is skipped, never raised."""
    out = []
    fns = [gajakesari, budhaditya, neecha_bhanga, parivartana, viparita_raja,
           raja_yoga, dhana_yoga, chandra_mangala, pancha_mahapurusha,
           lunar_yogas, solar_yogas, adhi, amala, parvata, saraswati, shakata]
    if include_unverified or LAKSHMI_ENABLED:
        fns.append(lakshmi)
    for fn in fns:
        try:
            out.extend(fn(facts))
        except (KeyError, TypeError, IndexError, AttributeError):
            continue
    try:
        return _status(out, facts)
    except (KeyError, TypeError, AttributeError):
        return out
