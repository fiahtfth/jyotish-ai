"""Classical chart audit. Each gate is evaluated on the same civil date and target."""
from calendar import monthrange
from datetime import date
import logging

from . import constants as K, precision, stability, yogas
from .engine import _dignity, engine

log = logging.getLogger(__name__)

NATURAL = {"career": "Sun", "relationship": "Venus", "finance": "Jupiter",
           "education": "Mercury", "relocation": "Moon", "health": "Sun", "direction": "Sun",
           "children": "Jupiter", "parents": "Sun", "debt": "Mars", "litigation": "Saturn"}
KENDRA = {1, 4, 7, 10}
STRONG = {"exalted", "own sign", "moolatrikona"}
PID = {name: i for i, name in K.PLANET_NAMES.items()}


def house(sign, reference):
    return (sign - reference) % 12 + 1


def lord(sign):
    return K.PLANET_NAMES[K.SIGN_LORD[sign]]


def position(rec):
    return f"{K.SIGN_NAMES[rec['sign']]} {rec['degree']:.4f}°"


def rashi_reaches(source, target):
    mode, other = K.SIGN_MODALITY[source], K.SIGN_MODALITY[target]
    return (source == target or mode == other == "dual" or
            ({mode, other} == {"movable", "fixed"} and (source-target) % 12 not in (1, 11)))


def table(title, columns, rows):
    return {"title": title, "columns": columns, "rows": rows}


AUDIT_VARGAS = tuple(f"D{n}" for n in (1, 2, 3, 4, 6, 7, 9, 10, 12, 16, 20, 24, 30, 40, 45, 60))


def cusp_audit(birth):
    """Stability window of every divisional Lagna around the stated birth time.

    Returns ({varga: True when its Lagna sign changes within the birth-time
    uncertainty}, table). Windows come from a fine scan with bisection, so a
    change anywhere inside the span is found, not just at three samples.
    """
    wins = stability.lagna_windows(birth, vargas=AUDIT_VARGAS)
    unc = stability.uncertainty_for(birth)
    flips = {v: w["status"] == "cusp_sensitive" for v, w in wins.items()}
    rows = []
    for v, w in wins.items():
        lo = f"{w['start_s']:.1f}" if any(c <= 0 for c in w["changes_s"]) else f"before {w['start_s']:.0f}"
        hi = f"{w['end_s']:.1f}" if any(c > 0 for c in w["changes_s"]) else f"beyond {w['end_s']:.0f}"
        rows.append([v, K.SIGN_NAMES[w["sign"]], lo, hi, "Cusp-sensitive" if flips[v] else "Stable"])
    # the Moon's nakshatra-pada window drives Vimshottari balance at birth
    try:
        mp = stability.moon_pada_window(birth)
        nak = K.NAKSHATRAS[mp["nakshatra"]]
        lo = f"{mp['start_s']:.1f}" if any(c <= 0 for c in mp["changes_s"]) else f"before {mp['start_s']:.0f}"
        hi = f"{mp['end_s']:.1f}" if any(c > 0 for c in mp["changes_s"]) else f"beyond {mp['end_s']:.0f}"
        sensitive = mp["status"] == "cusp_sensitive"
        rows.append(["Moon nakshatra pada", f"{nak} pada {mp['pada']}", lo, hi,
                     "Cusp-sensitive" if sensitive else "Stable"])
        flips["Moon pada"] = sensitive
    except Exception:
        pass
    # planets sitting on a D9/D60 sign edge inside the clock uncertainty
    try:
        edges = stability.planet_edge_windows(birth)
        for planet, per_varga in edges["flips"].items():
            for vname, rec in per_varga.items():
                nearest = min((abs(c) for c in rec["changes_s"]), default=0.0)
                trans = ", ".join(f"{a}→{b}" for a, b in rec["transitions"])
                rows.append([f"{planet} @ {vname}", f"{trans} (±{nearest:.0f} s)",
                             "-", "-", "Sign flips within uncertainty"])
                flips[f"{planet}@{vname}"] = True
    except Exception:
        pass
    changed = [v for v, f in flips.items() if f]
    label = (", ".join(changed) + f" change sign within ±{unc:.0f} s" if changed
             else f"no divisional Lagna changes within ±{unc:.0f} s")
    return flips, table("Birth-time sensitivity · " + label,
                        ["Varga", "Lagna sign", "Window from (s)", "Window to (s)", "Status"], rows)


def matrix(facts):
    vargas = facts["vargas"]
    required = {"D1", "D2", "D6", "D7", "D9", "D10", "D12", "D24", "D60"}
    names = sorted(required.union(vargas), key=lambda v: int(v[1:]))
    rows = []
    for name in ["Lagna", *facts["planets"]]:
        cells = []
        for v in names:
            chart = vargas.get(v, {})
            if name not in chart or "Lagna" not in chart:
                cells.append("Unavailable")
                continue
            rec = chart[name]
            cells.append(f"{position(rec)} · H{house(rec['sign'], chart['Lagna']['sign'])}")
        rows.append([name, *cells])
    ay = facts.get("meta", {}).get("ayanamsa") or {}
    label = (ay.get("id") or "Lahiri").replace("_", " ").title()
    degrees = f" ({ay['dms']})" if ay.get("dms") else ""
    return table(f"Sidereal planetary and divisional positions · {label} ayanamsa{degrees}", ["Point", *names], rows)


def natal_patterns(facts):
    planets, rows = facts["planets"], []
    mahapurusha = {"Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa",
                   "Venus": "Malavya", "Saturn": "Sasa"}
    for name, p in planets.items():
        flags = list(p["dignity"]) + [tag for tag in ("retrograde", "combust", "gandanta") if p[tag]]
        if facts["vargas"].get("D9", {}).get(name, {}).get("sign") == p["sign"]:
            flags.append("D9 vargottama")
        if name in mahapurusha and STRONG.intersection(flags) and p["house"] in KENDRA:
            flags.append(mahapurusha[name] + " Mahapurusha")
        if "debilitated" in flags and any(house(planets[lord(p["sign"])]["sign"], ref) in KENDRA
                                          for ref in (facts["lagna"]["sign"], planets["Moon"]["sign"])):
            flags.append("Neecha Bhanga condition (dispositor in kendra)")
        if p["house"] in (6, 8, 12) and any(facts["houses"][h]["lord"] == name for h in (6, 8, 12)):
            flags.append("Viparita Raja condition")
        if name == "Jupiter" and house(p["sign"], planets["Moon"]["sign"]) in KENDRA:
            flags.append("Gajakesari angular condition")
        dispositor = lord(p["sign"])
        if dispositor != name and lord(planets[dispositor]["sign"]) == name:
            flags.append(f"Parivartana with {dispositor}")
        aspects = sorted(house((p["sign"]+n-1) % 12, facts["lagna"]["sign"])
                         for n in K.ASPECTS.get(name, (7,)))
        rows.append([name, position(p), ", ".join(flags) or "—", ", ".join(map(str, aspects))])
    found = yogas.detect(facts)
    for y in found:
        rows.append([y["name"], f"yoga ({y['level']})", ", ".join(y["conditions_fired"]), "—"])
    result = table("Natal dignity, yogas and graha drishti", ["Planet", "D1", "Conditions", "Houses aspected"], rows)
    result["yogas"] = found
    return result


def promise(facts, domain):
    spec, planets = K.DOMAINS[domain], facts["planets"]
    h = spec["houses"][0]
    chart = facts["vargas"].get(spec["varga"], {})
    karakas = [NATURAL[domain], facts["jaimini"]["karakas"].get(spec["karaka"])]
    rows, votes = [], []
    for ref in ("Lagna", "Moon", "Sun"):
        sign = facts["vargas"]["D1"][ref]["sign"]
        target = (sign + h - 1) % 12
        ruler = lord(target)
        rec = planets[ruler]
        links = [p for p in dict.fromkeys(karakas) if p and target in K.reaches(p, planets[p]["sign"])]
        placed = house(rec["sign"], sign)
        support = ("debilitated" not in rec["dignity"] and
                   (bool(STRONG.intersection(rec["dignity"])) or bool(links) or placed in (1, 4, 5, 7, 9, 10)))
        votes.append(support)
        rows.append([ref, f"H{h} {K.SIGN_NAMES[target]}", f"{ruler} · {position(rec)} · H{placed}",
                     ", ".join(links) or "None", "Support" if support else "Limited"])
    d1lord = facts["houses"][h]["lord"]
    confirmed = False
    if d1lord in chart and "Lagna" in chart:
        rec = chart[d1lord]
        vh = house(rec["sign"], chart["Lagna"]["sign"])
        dignity = _dignity(PID[d1lord], rec["sign"], rec["degree"])
        confirmed = "debilitated" not in dignity and (vh in (1, 4, 5, 7, 9, 10) or bool(STRONG.intersection(dignity)))
        rows.append([spec["varga"], f"D1 H{h} lord", f"{d1lord} · {position(rec)} · H{vh}", "—",
                     "Support" if confirmed else "Limited"])
    grade = ("Unavailable" if not chart or not all(karakas) else "Strong" if sum(votes) >= 2 and confirmed
             else "Moderate" if any(votes) or confirmed else "Weak")
    return grade, table(f"Static promise · {grade}", ["Frame", "Target", "Lord", "Karaka contacts", "Reading"], rows)


def window_audit(facts, birth, domain, when, calibrated):
    spec, planets = K.DOMAINS[domain], facts["planets"]
    h = spec["houses"][0]
    target = facts["houses"][h]["sign"]
    ruler = lord(target)
    targets = {target, planets[ruler]["sign"]}
    stamp = (when.year, when.month, when.day)
    transits = engine.transit_positions(stamp, precision._place(birth))
    vim = engine.running_vimshottari(birth, stamp)
    chara = engine.running_chara(birth, stamp)
    try:
        with precision._frame(birth):
            yog = precision.yogini.get_running_dhasa_for_given_date(
                precision._jd_noon(when), precision._jd_birth(birth), precision._place(birth), dhasa_level_index=2)
    except (ValueError, ArithmeticError, RuntimeError):
        yog = []
    timeline = [[label, " / ".join(row[key]), row["start"], row["end"]]
                for label, rows, key in (("Vimshottari", vim, "lords"), ("Chara", chara, "signs")) for row in rows]
    for lords, begin, finish in yog or []:
        timeline.append(["Yogini", " / ".join(K.PLANET_NAMES[i] for i in lords),
                         precision._tuple_ymd(begin), precision._tuple_ymd(finish)])
    gates = []
    def gate(name, available, supports, evidence):
        gates.append([name, "Unavailable" if not available else "Aligned" if supports else "Limited", evidence])
    active = vim[-1]["lords"] if vim else []
    varga = facts["vargas"].get(spec["varga"], {})
    def relevant(name):
        return name == ruler or target in K.reaches(name, planets[name]["sign"])
    if len(active) == 3 and yog and chara and varga and all(n in varga for n in active):
        md, ad, pd = active
        yl = K.PLANET_NAMES[yog[0][0][0]]
        angle = house(planets[ad]["sign"], planets[md]["sign"])
        ya = house(planets[yl]["sign"], planets[ad]["sign"])
        cs = K.SIGN_NAMES.index(chara[0]["signs"][0])
        karaka = facts["jaimini"]["karakas"].get(spec["karaka"])
        arudhas = facts["jaimini"].get("arudhas", {})
        significators = {p: arudhas[p] for p in spec["arudhas"] if p in arudhas}
        if karaka:
            significators[karaka] = planets[karaka]["sign"]
        touched = [name for name, sign in significators.items() if rashi_reaches(cs, sign)]
        known = karaka and all(p in arudhas for p in spec["arudhas"])
        placements = []
        for n in dict.fromkeys(active):
            owned = [str(i) for i, rec in facts["houses"].items() if rec["lord"] == n]
            vowned = [str(i+1) for i in range(12) if lord((varga["Lagna"]["sign"]+i)%12) == n]
            placements.append(f"{n} D1 H{planets[n]['house']} (owns {','.join(owned) or '—'}), "
                              f"{spec['varga']} H{house(varga[n]['sign'], varga['Lagna']['sign'])} (owns {','.join(vowned) or '—'})")
        gate("Multi-dasha", known, any(relevant(n) for n in active[:2]) and angle not in (2, 6, 8, 12)
             and ya not in (2, 6, 8, 12) and relevant(yl) and touched,
             ". ".join(placements) + f". AD from MD H{angle}. Yogini {yl} from AD H{ya}. "
             f"Chara {K.SIGN_NAMES[cs]} contacts {', '.join(touched) or 'none'}.")
    else:
        gate("Multi-dasha", False, False, "An active timeline or divisional chart is unavailable.")
    # Muntha advances at each solar return (the Sun's return instant), not on the calendar birthday
    age = precision.completed_solar_years(birth, when)
    refs = facts["vargas"]["D1"]
    ms = (refs["Lagna"]["sign"] + age) % 12
    ml = lord(ms)
    mh = house(ms, refs["Lagna"]["sign"])
    annual, annual_hits = [], 0
    for ref in ("Lagna", "Moon", "Sun"):
        s = (refs[ref]["sign"] + age) % 12
        contacts = [n for n, p in planets.items() if s in K.reaches(n, p["sign"])]
        annual_hits += int(s in targets or ruler in contacts)
        annual.append(f"{ref} {K.SIGN_NAMES[s]} ({', '.join(contacts) or 'no contacts'})")
    td = _dignity(PID[ml], transits[ml]["sign"], transits[ml]["degree"]) if ml in transits else []
    blocked = []
    if "debilitated" in planets[ml]["dignity"] + td:
        blocked.append("debilitated")
    if planets[ml].get("combust"):
        blocked.append("natal combustion")
    if planets[ml]["house"] in (6, 8, 12):
        blocked.append(f"natal H{planets[ml]['house']}")
    if ml in transits:
        transit_house = house(transits[ml]["sign"], refs["Lagna"]["sign"])
        if transit_house in (6, 8, 12):
            blocked.append(f"transit H{transit_house}")
        with precision._frame(birth):
            retro = precision.drik.planets_in_retrograde(precision._jd_noon(when), precision._place(birth))
        orb = K.combust_orb(PID[ml], PID[ml] in retro, birth.settings.combust_table)
        if orb and "Sun" in transits and precision._sep(
                precision._abs_long(transits[ml]), precision._abs_long(transits["Sun"])) < orb:
            blocked.append("transit combustion")
    gate("Annual progression", age >= 0 and ml in transits, mh in (1, 2, 3, 5, 9, 10, 11)
         and not blocked and annual_hits >= 2,
         f"Muntha {K.SIGN_NAMES[ms]} H{mh}. {ml} natal {position(planets[ml])} "
         f"({', '.join(planets[ml]['dignity']) or 'ordinary'}), transit "
         f"{position(transits[ml]) if ml in transits else 'unavailable'} ({', '.join(td) or 'ordinary'}). "
         + ". ".join(annual) + (". Muntha lord moderates the year due to " + ", ".join(blocked) if blocked else ""))
    shared = set(targets)
    trans = []
    for name in ("Jupiter", "Saturn"):
        if name in transits:
            shared &= K.reaches(name, transits[name]["sign"])
            trans.append(f"{name} {position(transits[name])}")
    for name in ("Rahu", "Ketu"):
        if name in transits:
            rec = transits[name]
            hits = [f"{p} ({sep:.2f}°)" for p, n in refs.items()
                    if (sep := precision._sep(precision._abs_long(rec), n["abs_longitude"])) <= 3]
            trans.append(f"{name} {position(rec)} H{house(rec['sign'], refs['Lagna']['sign'])}"
                         + (" near " + ", ".join(hits) if hits else ""))
    gate("Slow transits", all(n in transits for n in ("Jupiter", "Saturn", "Rahu", "Ketu")), shared,
         ". ".join(trans) + ". Shared targets: " + (", ".join(K.SIGN_NAMES[s] for s in sorted(shared)) or "none"))
    pd = active[2] if len(active) == 3 else None
    nak = planets[pd]["nakshatra"] if pd else {}
    sav, bav, pr = facts.get("sarvastakavarga"), facts.get("binnashtakavarga"), facts.get("prastara_ashtakavarga")
    available = bool(pd and sav and bav and pr and all(n in transits for n in ("Jupiter", "Saturn", "Sun", "Mars")))
    triggers, eligible = [], False
    fast = [n for n in ("Sun", "Mars") if n in transits and transits[n]["sign"] in targets]
    if available:
        for n in ("Jupiter", "Saturn"):
            rec = transits[n]
            s, d = rec["sign"], rec["degree"]
            k = precision.kakshya_lord(precision.kakshya_of(d))
            charged = precision._kakshya_charged(pr, PID[n], s, d)
            eligible |= (s in targets and sav[s] >= 28 and bav[PID[n]][s] >= 5 and charged and (k != "Lagna" or calibrated))
            triggers.append(f"{n} SAV {sav[s]}, BAV {bav[PID[n]][s]}, {k} kakshya ({int(charged)} bindu)")
    gate("Micro-timing", available, eligible and fast and pd and (relevant(pd) or relevant(nak["lord"])),
         (f"{pd} in {nak['name']} pada {nak['pada']}, ruled by {nak['lord']}. " if pd else "") +
         ". ".join(triggers) + ". Fast contact: " + (", ".join(fast) or "none"))
    count = sum(row[1] == "Aligned" for row in gates)
    return count, table(f"Multi-dasha timeline · {when}", ["System", "Active period", "From", "Until"], timeline), gates


def evaluate(facts, birth, domain, start, end, candidates, calibrated, natal=None):
    grade, static = natal or promise(facts, domain)
    flips, cusp = cusp_audit(birth)
    tables = [matrix(facts), static, natal_patterns(facts), cusp]
    timing_sensitive = flips.get(K.DOMAINS[domain]["varga"], False)
    spans = [(start, end, start + (end-start)//2)] + [
        (date.fromisoformat(w["start"]), date.fromisoformat(w["end"]),
         date.fromisoformat(w.get("peak_date", w["start"]))) for w in candidates]
    scores = []
    for a, b, sample in dict.fromkeys(spans):
        count, timeline, gates = window_audit(facts, birth, domain, sample, calibrated)
        tables.extend([timeline, table(f"{a} to {b} · {count}/4 traditional gates aligned",
                                      ["Gate", "At " + str(sample), "Evidence"], gates)])
        scores.append({"start": str(a), "end": str(b), "sample": str(sample), "count": count,
                       "complete": all(g[1] != "Unavailable" for g in gates),
                       "micro_aligned": gates[-1][1] == "Aligned"})
    return {"promise": grade, "cusp_flips": flips, "timing_sensitive": timing_sensitive, "scores": scores,
            "calibrated": calibrated, "tables": tables, "note": "Each score describes the listed sample date. D60 houses are conditional "
            "because birth-time accuracy within one minute has not been established. Gate counts measure "
            "agreement among traditional rules. A probability of the event has not been established."}


def apply(analysis, facts, birth, domain, start, end, calibrated, prec, natal):
    candidates = prec["timing"]["windows"] if analysis["sensitivity"]["timing_stable"] else []
    try:
        audit = evaluate(facts, birth, domain, start, end, candidates, calibrated, natal)
    except (ValueError, IndexError, KeyError, TypeError, ArithmeticError, RuntimeError):
        log.exception("Classical chart audit unavailable for %s", domain)
        audit = {"promise": "Unavailable", "timing_sensitive": True, "scores": [], "tables": [],
                 "note": "The classical calculations are unavailable for this reading."}
    analysis["classical"] = audit
    eclipses = prec["fast_triggers"]
    if eclipses.get("eclipses"):
        audit["tables"].append(table("Eclipses in the requested interval", ["Date", "Kind", "Natal points within 3°"],
                                     [[e["date"], e["kind"], ", ".join(e["touches"]) or "None"]
                                      for e in eclipses["eclipses"]]))
    qualified = {(s["start"], s["end"]) for s in audit["scores"]
                 if s["complete"] and s["count"] >= 3 and s["micro_aligned"]}
    analysis["precision"]["timing_windows"] = [
        w for w in candidates if (w["start"], w["end"]) in qualified and calibrated
        and not audit["timing_sensitive"] and audit["promise"] in ("Strong", "Moderate")]


def markdown(audit):
    def row(cells):
        return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |"

    blocks = []
    for t in audit["tables"]:
        blocks.append("\n".join([t["title"], "", row(t["columns"]), row(["---"] * len(t["columns"])),
                                 *(row(cells) for cells in t["rows"])]))
    return "\n\n".join([*blocks, audit["note"]])


def birth_checks(audit, facts, birth, checks):
    """Audit only the selected, frozen opening indications, on dates inside their stored bounds."""
    rows = []
    details = []
    for check in checks:
        rows.append([check.predicted_event, check.predicted_window_start, check.predicted_window_end,
                     check.user_feedback or "Pending"])
        try:
            first = date.fromisoformat(check.predicted_window_start + "-01")
            last = date.fromisoformat(check.predicted_window_end + "-01")
            last = last.replace(day=monthrange(last.year, last.month)[1])
            sample = first + (last - first) // 2
            count, timeline, gates = window_audit(facts, birth, check.domain, sample, False)
        except (TypeError, KeyError, ValueError, IndexError, ArithmeticError, RuntimeError):
            continue
        details.extend([timeline, table(f"Past {check.domain} check · {first} to {last} · {count}/4",
                                                ["Gate", "At " + str(sample), "Evidence"], gates)])
    if rows:
        audit["tables"].append(table("Birth-time checks", ["Indication", "From", "Until", "Response"], rows))
        audit["tables"].extend(details)
