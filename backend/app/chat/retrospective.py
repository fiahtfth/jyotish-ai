"""Retrospective data bundle for past-tense questions ("when did I switch
careers, and in which direction?").

A past question is never a forecast: the model is given the Antardasha table
for the last ~15 years, the user's own reported events and the Saturn/Jupiter
transits over the domain's key houses, and matches the event to a period
itself. Nothing here writes the answer."""
from datetime import date, timedelta

from ..astro import constants as K
from ..astro import transits

HORIZON_YEARS = 15
_MAX_ROWS = 40


def _d(value) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _house(sign, lagna_sign) -> int:
    return (int(sign) - int(lagna_sign)) % 12 + 1


def lord_links(facts, lord, domain) -> dict:
    """How a dasha lord connects to the domain's houses and its varga."""
    spec = K.DOMAINS[domain]
    houses = spec["houses"]
    owned = [h for h in range(1, 13) if facts["houses"][h]["lord"] == lord]
    placed = (facts["planets"].get(lord) or {}).get("house")
    varga = facts.get("vargas", {}).get(spec["varga"]) or {}
    varga_house = None
    if lord in varga and "Lagna" in varga:
        varga_house = _house(varga[lord]["sign"], varga["Lagna"]["sign"])
    return {"lord": lord, "owns": owned, "house": placed, "varga": spec["varga"],
            "varga_house": varga_house,
            "links": sorted(set(owned) & set(houses)) + ([placed] if placed in houses else []),
            "varga_links": varga_house in houses if varga_house else False}


def antardasha_table(facts, today: date, years=HORIZON_YEARS, born: date | None = None) -> list[dict]:
    """Antardashas overlapping [today - years, today] with their dates."""
    start = today - timedelta(days=int(365.25 * years))
    rows = []
    for p in facts["vimshottari"]["periods"]:
        if len(p["lords"]) != 2:
            continue
        s, e = _d(p["start"]), _d(p["end"])
        if e < start or s > today:
            continue
        rows.append({"maha": p["lords"][0], "antar": p["lords"][1], "start": s.isoformat(),
                     "end": e.isoformat(), "running": s <= today <= e})
    return rows[-_MAX_ROWS:]


def transit_years(birth, facts, domain, today: date, years=HORIZON_YEARS) -> list[dict]:
    """Saturn/Jupiter stays over the domain's two key houses."""
    houses = K.DOMAINS[domain]["houses"][:2]
    lagna = facts["lagna"]["sign"]
    start = today - timedelta(days=int(365.25 * years))
    out = []
    for planet in ("Saturn", "Jupiter"):
        try:
            intervals = transits.sign_intervals(birth, planet, start, today)
        except Exception:
            continue
        for sign, first, last in intervals:
            h = _house(sign, lagna)
            if h in houses:
                out.append({"planet": planet, "house": h, "start": first.isoformat(), "end": last.isoformat()})
    return out


def reported_events(profile, remembered=()) -> list[str]:
    """What the user has said happened: dated milestones and remembered quotes."""
    lines = []
    for m in getattr(profile, "milestones", []) or []:
        when = f"{m.year}-{m.month:02d}" if m.month else str(m.year)
        lines.append(f"{when}: {m.description or m.domain}")
    for item in remembered:
        quote = item.get("quote") if isinstance(item, dict) else None
        if quote and quote not in lines:
            lines.append(quote[:200])
    return lines[:10]


def likely_periods(table, facts, domain, limit=2) -> list[dict]:
    """The Antardashas whose lords best link to the domain, for use when the
    user has not said when the event happened."""
    scored = []
    for row in table:
        score = 0
        for lord in (row["maha"], row["antar"]):
            info = lord_links(facts, lord, domain)
            score += (1 if info["links"] else 0) + (1 if info["varga_links"] else 0)
        if score:
            scored.append((score, row["end"], row))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r for _, _, r in scored[:limit]]


def build(facts, birth, profile, domain, today: date, remembered=()) -> dict:
    """Return {'data': {...}, 'note': str} for the model."""
    spec = K.DOMAINS[domain]
    table = antardasha_table(facts, today)
    for row in table:
        row["antar_links"] = lord_links(facts, row["antar"], domain)
        row["maha_links"] = lord_links(facts, row["maha"], domain)
    events = reported_events(profile, remembered)
    transit = transit_years(birth, facts, domain, today)
    likely = [] if events else likely_periods(table, facts, domain)
    lines = []
    for r in table:
        a = r["antar_links"]
        lines.append(f"{r['maha']}/{r['antar']} {r['start']} to {r['end']}"
                     f"{' (running)' if r['running'] else ''}; {r['antar']} owns {a['owns']}, in house {a['house']}, "
                     f"{a['varga']} house {a['varga_house']}")
    note = [
        f"PAST-TENSE QUESTION about {domain}. Do not forecast and do not give a future window. "
        f"Antardasha periods of the last {HORIZON_YEARS} years (key houses {spec['houses']}, "
        f"varga {spec['varga']}): " + " | ".join(lines) + ".",
    ]
    if events:
        note.append("The user has reported these events: " + "; ".join(events) + ". Match the event they ask "
                    "about to the Antardasha running at that date and name the Antardasha change dates.")
    else:
        names = "; ".join(f"{r['maha']}/{r['antar']} ({r['start']} to {r['end']})" for r in likely)
        note.append("The user has not said when it happened. Offer the 1-2 most likely periods from the chart"
                    + (f" ({names})" if names else "") + " and ask ONE short natural question to confirm which "
                    "fits what they remember.")
    if transit:
        note.append("Saturn/Jupiter transits over the key houses: " + "; ".join(
            f"{t['planet']} in house {t['house']} {t['start']} to {t['end']}" for t in transit) + ".")
    note.append("For 'in which direction' or 'what changed', compare the old and new Antardasha lords' links to "
                f"the key houses and their {spec['varga']} placement. Keep the answer concise.")
    return {"data": {"domain": domain, "antardasha": table, "reported_events": events,
                     "likely_periods": likely, "transits": transit},
            "note": " ".join(note)}
