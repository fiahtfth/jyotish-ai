"""Jaimini calculations: Chara dasha, co-lord strength, arudhas, chara karakas.

Pure functions over PyJHora-style rasi positions
    [['L', (sign, degree)], [pid, (sign, degree)], ...]
(sign 0=Aries..11=Pisces, pid 0=Sun..8=Ketu). Nothing here touches PyJHora
globals, so every branch can be tested with synthetic positions.

Every co-lord comparison step is a small function with a rule ID; the ID of
the step that decided is returned so the reading can show its reasoning.

Documented choices
- Dasha direction: forward when the 9th sign from the seed sign is one of
  Ar/Ta/Ge/Li/Sc/Sg, otherwise backward (applied to the Lagna for the order of
  periods and to each period sign for its antardasha order).
- Years: count from the sign to its lord (same direction rule: forward from
  those six signs, backward from the other six) minus 1; lord in own sign = 12.
- KNRao: no +/-1 for exaltation/debilitation (K.N. Rao rejects it); cycle 2
  repeats cycle 1; antardashas start from the sign after the period sign.
- PVR / Rath: +/-1 for an exalted / debilitated lord, capped at 12; floor is 1
  for PVR and 0 for Rath. Cycle 2 = 12 - cycle-1 years. Antardashas start from
  the period's own sign.
"""
from . import constants as K

SAVYA = {0, 1, 2, 6, 7, 8}          # Ar Ta Ge Li Sc Sg: counted forward
SCHOOLS = ("KNRao", "PVR", "Rath")
KARAKA_NAMES_7 = ["Atmakaraka", "Amatyakaraka", "Bhratrukaraka", "Matrukaraka",
                  "Putrakaraka", "Gnatikaraka", "Darakaraka"]
KARAKA_NAMES_8 = ["Atmakaraka", "Amatyakaraka", "Bhratrukaraka", "Matrukaraka",
                  "Pitrukaraka", "Putrakaraka", "Gnatikaraka", "Darakaraka"]
TIE_ARCSEC = 60.0
RAHU, KETU = 7, 8
COLORDS = {7: (2, KETU), 10: (6, RAHU)}   # Scorpio: Mars/Ketu, Aquarius: Saturn/Rahu
BOTH_IN_SIGN = "COLORD.BOTH_IN_SIGN"
ONE_IN_SIGN = "COLORD.ONE_IN_SIGN"
FALLBACK = "COLORD.FALLBACK_FIRST_LORD"


# ---------- helpers ----------

def positions(rasi) -> dict:
    """{pid_or_'L': (sign, degree)} from PyJHora position rows."""
    return {pid: (int(rec[0]), float(rec[1])) for pid, rec in rasi}


def forward_from(sign: int) -> bool:
    """Direction of counting seeded at `sign`: 9th from it in a savya sign -> forward."""
    return (sign + 8) % 12 in SAVYA


def counts_forward(sign: int) -> bool:
    return sign in SAVYA


def _rashi_aspects(a: int, b: int) -> bool:
    ma, mb = K.SIGN_MODALITY[a], K.SIGN_MODALITY[b]
    if a == b:
        return False
    if ma == mb == "dual":
        return True
    return {ma, mb} == {"movable", "fixed"} and (a - b) % 12 not in (1, 11)


def _conjuncts(pos, pid):
    sign = pos[pid][0]
    return [q for q, (s, _) in pos.items() if q != pid and q != "L" and s == sign]


def _strong_dignity(pid, sign, deg):
    ex = K.EXALTATION.get(pid)
    if ex and ex[0] == sign:
        return True
    if sign in K.OWN_SIGNS.get(pid, []):
        return True
    return any(s == sign and lo <= deg < hi for s, lo, hi in K.MOOLATRIKONA.get(pid, []))


def _modality_rank(sign):
    return {"dual": 2, "fixed": 1, "movable": 0}[K.SIGN_MODALITY[sign]]


def _simple_years(pos, sign, school):
    """Years of `sign` using the plain lord (no co-lord resolution): used only as
    a tie-break input so co-lord comparison cannot recurse."""
    lord = K.SIGN_LORD[sign]
    return _years_for_lord(pos, sign, lord, school)


# ---------- co-lord comparison steps ----------
# Each step takes (pos, a, b) with a, b the two co-lord planet ids and returns the
# winning planet id, or None when the step does not separate them.

def _by_count(vals, a, b):
    if vals[a] == vals[b]:
        return None
    return a if vals[a] > vals[b] else b


def _together_elsewhere(pos, a, b):
    # handled specially in _run (the sign is shared, so either lord counts there)
    return None


def _more_planets(pos, a, b):
    return _by_count({a: len(_conjuncts(pos, a)), b: len(_conjuncts(pos, b))}, a, b)


def _benefic_contact(pos, a, b):
    def score(x):
        sx = pos[x][0]
        disp = K.SIGN_LORD[sx]
        n = 0
        for helper in dict.fromkeys((4, 3, disp)):
            if helper == x or helper not in pos:
                continue
            hs = pos[helper][0]
            if hs == sx or _rashi_aspects(hs, sx):
                n += 1
        return n
    return _by_count({a: score(a), b: score(b)}, a, b)


def _dignity_step(pos, a, b):
    return _by_count({x: int(_strong_dignity(x, *pos[x])) for x in (a, b)}, a, b)


def _exalted_step(pos, a, b):
    return _by_count({x: int(K.EXALTATION.get(x, (None,))[0] == pos[x][0]) for x in (a, b)}, a, b)


def _modality_step(pos, a, b):
    return _by_count({x: _modality_rank(pos[x][0]) for x in (a, b)}, a, b)


def _int_degree_step(pos, a, b):
    return _by_count({x: int(pos[x][1]) for x in (a, b)}, a, b)


def _full_degree_step(pos, a, b):
    return _by_count({x: pos[x][1] for x in (a, b)}, a, b)


def _years_step(school):
    def step(pos, a, b):
        return _by_count({x: _simple_years(pos, pos[x][0], school) for x in (a, b)}, a, b)
    return step


STEPS = {
    "KNRao": [("KNRAO.COLORD.ASSOC", _more_planets),
              ("KNRAO.COLORD.DEGREE", _int_degree_step),
              ("KNRAO.COLORD.SECONDS", _full_degree_step)],
    "Rath": [("RATH.COLORD.TOGETHER", _together_elsewhere),
             ("RATH.COLORD.MORE_PLANETS", _more_planets),
             ("RATH.COLORD.JUP_MER_DISPOSITOR", _benefic_contact),
             ("RATH.COLORD.DIGNITY", _dignity_step),
             ("RATH.COLORD.MODALITY", _modality_step),
             ("RATH.COLORD.DEGREE", _full_degree_step),
             ("RATH.COLORD.DASA_YEARS", _years_step("Rath"))],
    "PVR": [("PVR.COLORD.CONJUNCTION", _more_planets),
            ("PVR.COLORD.EXALTED", _exalted_step),
            ("PVR.COLORD.MODALITY", _modality_step),
            ("PVR.COLORD.DASA_YEARS", _years_step("PVR"))],
}
PVR_ARUDHA_STEPS = [("PVR.COLORD.ARUDHA_DEGREE", _full_degree_step)]
RULE_ALIASES = {"KNRao": "KNRao", "Rath": "Rath", "PVR": "PVR"}


def stronger_colord(rasi, sign, rule, purpose="dasha"):
    """Stronger lord of Scorpio (Mars/Ketu) or Aquarius (Saturn/Rahu).

    Returns (planet_id, rule_id_fired). rule_id == "COLORD.BOTH_IN_SIGN" means
    both lords sit in `sign` itself: for the dasha the sign then gets 12 years.
    """
    if sign not in COLORDS:
        return K.SIGN_LORD[sign], "COLORD.SINGLE_LORD"
    if rule not in RULE_ALIASES:
        raise ValueError(f"Unknown co-lord rule {rule!r}; allowed: {', '.join(RULE_ALIASES)}")
    if purpose not in ("dasha", "arudha"):
        raise ValueError("purpose must be 'dasha' or 'arudha'")
    pos = rasi if isinstance(rasi, dict) else positions(rasi)
    a, b = COLORDS[sign]
    in_a, in_b = pos[a][0] == sign, pos[b][0] == sign
    if in_a and in_b:
        return a, BOTH_IN_SIGN
    if in_a:
        return b, ONE_IN_SIGN
    if in_b:
        return a, ONE_IN_SIGN
    steps = list(STEPS[rule])
    if rule == "PVR" and purpose == "arudha":
        steps = steps + PVR_ARUDHA_STEPS
    for rule_id, step in steps:
        if rule_id == "RATH.COLORD.TOGETHER":
            if pos[a][0] == pos[b][0]:
                return a, rule_id      # both together elsewhere: count to that sign
            continue
        winner = step(pos, a, b)
        if winner is not None:
            return winner, rule_id
    return a, FALLBACK


# ---------- Chara dasha ----------

def _years_for_lord(pos, sign, lord, school):
    lsign = pos[lord][0]
    if lsign == sign:
        return 12
    count = (lsign - sign) % 12 + 1 if counts_forward(sign) else (sign - lsign) % 12 + 1
    years = count - 1
    if school in ("PVR", "Rath"):
        ex = K.EXALTATION.get(lord)
        db = K.DEBILITATION.get(lord)
        if ex and ex[0] == lsign:
            years += 1
        elif db and db[0] == lsign:
            years -= 1
        years = min(12, max(0 if school == "Rath" else 1, years))
    return years


def sign_years(rasi, sign, school, colord_rule="school"):
    """(years, lord_pid, rule_id|None) for one sign's Chara dasha."""
    if school not in SCHOOLS:
        raise ValueError(f"Unknown chara school {school!r}; allowed: {', '.join(SCHOOLS)}")
    pos = rasi if isinstance(rasi, dict) else positions(rasi)
    rid = None
    if sign in COLORDS:
        rule = school if colord_rule == "school" else colord_rule
        lord, rid = stronger_colord(pos, sign, rule, "dasha")
        if rid == BOTH_IN_SIGN:
            return 12, lord, rid
    else:
        lord = K.SIGN_LORD[sign]
    return _years_for_lord(pos, sign, lord, school), lord, rid


def mahadasha_order(lagna_sign: int) -> list[int]:
    step = 1 if forward_from(lagna_sign) else -1
    return [(lagna_sign + step * i) % 12 for i in range(12)]


def antardasha_order(sign: int, school: str) -> list[int]:
    step = 1 if forward_from(sign) else -1
    first = sign + step if school == "KNRao" else sign
    return [(first + step * i) % 12 for i in range(12)]


def chara_periods(rasi_positions, birth_jd, school, year_days, cycles=2, colord_rule="school"):
    """Chara dasha periods from birth.

    Each period: {sign, start_jd, years, end_jd, cycle, lord, colord_rule_id,
    antardashas: [{sign, start_jd, end_jd, years}]}.
    """
    pos = positions(rasi_positions) if not isinstance(rasi_positions, dict) else rasi_positions
    lagna = pos["L"][0]
    order = mahadasha_order(lagna)
    first = {s: sign_years(pos, s, school, colord_rule) for s in order}
    out, t = [], float(birth_jd)
    for cycle in range(1, cycles + 1):
        for s in order:
            y, lord, rid = first[s]
            if school != "KNRao" and cycle % 2 == 0:
                y = 12 - y
            end = t + y * year_days
            sub, st = [], t
            for sub_sign in antardasha_order(s, school):
                e = st + (y / 12.0) * year_days
                sub.append({"sign": sub_sign, "start_jd": st, "end_jd": e, "years": y / 12.0})
                st = e
            out.append({"sign": s, "start_jd": t, "years": y, "end_jd": end, "cycle": cycle,
                        "lord": lord, "colord_rule_id": rid, "antardashas": sub})
            t = end
    return out


# ---------- arudhas ----------

def arudhas(rasi, exception="standard", colord_rule="KNRao"):
    """Bhava arudhas A1..A12 as sign indices.

    Count from the house to its lord, then the same count again from the lord.
    If the result is the house itself or its 7th, take the 10th from the result
    (exception="standard"); exception="none" skips that rule.
    """
    pos = rasi if isinstance(rasi, dict) else positions(rasi)
    lagna = pos["L"][0]
    out = []
    for h in range(12):
        house_sign = (lagna + h) % 12
        if house_sign in COLORDS:
            lord, _ = stronger_colord(pos, house_sign, colord_rule, "arudha")
        else:
            lord = K.SIGN_LORD[house_sign]
        lsign = pos[lord][0]
        result = (lsign + (lsign - house_sign) % 12) % 12
        if exception == "standard" and result in (house_sign, (house_sign + 6) % 12):
            result = (result + 9) % 12
        out.append(result)
    return out


# ---------- chara karakas ----------

def karakas(rasi, scheme="7_KNRao"):
    """Chara karakas by full-precision degree in sign.

    Returns {"scheme", "names", "karakas": {name: planet}, "ranking":
    [(planet, degree)], "ties": [{pair, margin_arcsec}]}; ties list adjacent
    ranks that are within 60 arcseconds of each other.
    """
    if scheme not in ("7_KNRao", "7or8_PVR", "8_Rath"):
        raise ValueError(f"Unknown karaka scheme {scheme!r}")
    pos = rasi if isinstance(rasi, dict) else positions(rasi)
    seven = [(p, pos[p][1]) for p in range(7)]
    use_rahu = scheme == "8_Rath"
    if scheme == "7or8_PVR":
        degs = [int(d) for _, d in seven]
        use_rahu = len(set(degs)) < len(degs)
    cands = list(seven)
    if use_rahu:
        cands.append((RAHU, 30.0 - pos[RAHU][1]))
    ranked = sorted(cands, key=lambda t: -t[1])
    names = KARAKA_NAMES_8 if use_rahu else KARAKA_NAMES_7
    ties = []
    for (p1, d1), (p2, d2) in zip(ranked, ranked[1:]):
        margin = (d1 - d2) * 3600.0
        if margin <= TIE_ARCSEC:
            ties.append({"pair": [K.PLANET_NAMES[p1], K.PLANET_NAMES[p2]],
                         "margin_arcsec": round(margin, 3)})
    return {"scheme": scheme, "names": names, "uses_rahu": use_rahu,
            "karakas": {names[i]: K.PLANET_NAMES[p] for i, (p, _) in enumerate(ranked)},
            "ranking": ranked, "ties": ties}


# ---------- depth: karakamsha, arudha lagna houses, raja yogas, Narayana ----------
# Pure functions over locked facts (sign 0=Aries). IDs: JM.KARAKAMSHA,
# JM.ISHTA_DEVATA (12th from karakamsha; verified=False), JM.AL_HOUSES,
# JM.RAJA.AK_AMK / JM.RAJA.AK_L5 (Jaimini Upadesa Sutras, raja yoga; the
# association test — conjunction, rasi drishti or exchange — follows common
# teaching and is marked verified=False), JM.NARAYANA (PyJHora Narayana dasa).

SRC_JAIMINI = "Jaimini Upadesa Sutras"


def _occupants(chart: dict, sign: int) -> list[str]:
    return sorted(n for n, r in chart.items() if n != "Lagna" and int(r["sign"]) == sign)


def karakamsha(facts) -> dict | None:
    ak = ((facts.get("jaimini") or {}).get("karakas") or {}).get("Atmakaraka")
    d9 = (facts.get("vargas") or {}).get("D9") or {}
    d1 = (facts.get("vargas") or {}).get("D1") or {}
    if not ak or ak not in d9:
        return None
    ks = int(d9[ak]["sign"])
    twelfth = (ks + 11) % 12
    out = {"atmakaraka": ak, "sign": ks, "sign_name": K.SIGN_NAMES[ks],
           "d9_occupants": _occupants(d9, ks), "d1_occupants": _occupants(d1, ks),
           "house_from_d1_lagna": (ks - int(facts["lagna"]["sign"])) % 12 + 1,
           "rule": "JM.KARAKAMSHA", "source": SRC_JAIMINI + " (karakamsha)", "verified": True,
           "twelfth": {"sign": twelfth, "sign_name": K.SIGN_NAMES[twelfth],
                       "d9_occupants": _occupants(d9, twelfth),
                       "lord": K.PLANET_NAMES[K.SIGN_LORD[twelfth]],
                       "rule": "JM.ISHTA_DEVATA", "verified": False,
                       "note": "12th from karakamsha as ishta devata indicator — reading varies by school"}}
    if "Lagna" in d9:
        out["house_from_d9_lagna"] = (ks - int(d9["Lagna"]["sign"])) % 12 + 1
    return out


def al_houses(facts) -> dict | None:
    jk = facts.get("jaimini") or {}
    al = jk.get("arudha_lagna")
    d1 = (facts.get("vargas") or {}).get("D1") or {}
    if not al:
        return None
    s = int(al["sign"])
    out = {"sign": s, "sign_name": K.SIGN_NAMES[s], "occupants": _occupants(d1, s),
           "house_from_lagna": (s - int(facts["lagna"]["sign"])) % 12 + 1, "rule": "JM.AL_HOUSES"}
    for h in (2, 7, 11, 12):
        hs = (s + h - 1) % 12
        out[f"h{h}"] = {"sign_name": K.SIGN_NAMES[hs], "occupants": _occupants(d1, hs),
                        "lord": K.PLANET_NAMES[K.SIGN_LORD[hs]]}
    return out


def _association(pos_a: int, pos_b: int, a: int, b: int) -> list[str]:
    kinds = []
    if pos_a == pos_b:
        kinds.append("conjunction")
    elif _rashi_aspects(pos_a, pos_b):
        kinds.append("rasi_drishti")
    if K.SIGN_LORD[pos_a] == b and K.SIGN_LORD[pos_b] == a:
        kinds.append("exchange")
    return kinds


def raja_yogas(facts) -> list[dict]:
    kar = (facts.get("jaimini") or {}).get("karakas") or {}
    p = facts["planets"]
    pid = {v: k for k, v in K.PLANET_NAMES.items()}
    ak, amk = kar.get("Atmakaraka"), kar.get("Amatyakaraka")
    out = []
    if not ak or ak not in p:
        return out
    hs = facts["houses"]
    l5 = (hs[5] if 5 in hs else hs["5"])["lord"]
    for other, rid, label in ((amk, "JM.RAJA.AK_AMK", "Atmakaraka–Amatyakaraka"),
                              (l5, "JM.RAJA.AK_L5", "Atmakaraka–5th lord")):
        if not other or other == ak or other not in p:
            continue
        kinds = _association(int(p[ak]["sign"]), int(p[other]["sign"]), pid[ak], pid[other])
        if kinds:
            out.append({"id": rid, "name": f"Jaimini Raja Yoga ({label}: {ak} and {other})",
                        "participants": [ak, other], "links": kinds,
                        "source": SRC_JAIMINI + " (raja yoga)", "verified": False})
    return out


def narayana_rows(rows) -> dict:
    """Group PyJHora Narayana rows [((md, ad), (y, m, d, fh), years)] into MD periods."""
    from datetime import date, timedelta

    def iso(t):
        return f"{int(t[0]):04d}-{int(t[1]):02d}-{int(t[2]):02d}"
    mds = []
    for lords, start, _years in rows:
        md = int(lords[0])
        if not mds or mds[-1]["sign"] != md:
            mds.append({"sign": md, "sign_name": K.SIGN_NAMES[md], "start": iso(start), "ads": []})
        if len(lords) > 1:
            mds[-1]["ads"].append([int(lords[1]), iso(start)])
    for a, b in zip(mds, mds[1:]):
        a["end"] = b["start"]
    if mds:
        _, start, years = rows[-1]
        end = date(int(start[0]), int(start[1]), int(start[2])) + timedelta(days=float(years) * 365.2425)
        mds[-1]["end"] = end.isoformat()
    return {"periods": mds, "source": "PyJHora Narayana dasa (rasi chart, default method)",
            "rule": "JM.NARAYANA"}


def running_narayana(narayana: dict | None, today_iso: str) -> dict | None:
    for md in (narayana or {}).get("periods", []):
        if md["start"] <= today_iso < md.get("end", "9999"):
            ad = None
            for i, (s, st) in enumerate(md["ads"]):
                nxt = md["ads"][i + 1][1] if i + 1 < len(md["ads"]) else md.get("end", "9999")
                if st <= today_iso < nxt:
                    ad = {"sign": s, "sign_name": K.SIGN_NAMES[s], "start": st, "end": nxt}
            return {"md": {"sign": md["sign"], "sign_name": md["sign_name"],
                           "start": md["start"], "end": md.get("end")}, "ad": ad}
    return None
