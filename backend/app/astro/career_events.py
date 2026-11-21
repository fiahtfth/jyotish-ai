"""Versioned career event rules layered on top of the classical timing check."""
from datetime import date
import re

from . import constants as K
from .classical import house
from .engine import engine

VERSION = "1.0"

# Work, event-specific activation, and the houses that confirm it in D10.
# These are declared interpretation rules for the prospective evaluation.
RULES = {
    "promotion": ((10,), (11,), (10, 11)),
    "job_change": ((6, 10), (3, 12), (6, 10, 12)),
    "job_offer": ((6,), (7, 11), (6, 10, 11)),
}

_SEARCH_STAGES = {
    "not_searching": r"i(?: am|'m) not (?:applying|looking for (?:a )?(?:new )?job)|i stopped (?:applying|my job search)",
    "applying": r"i(?: am|'m| have been|'ve been) (?:actively )?applying (?:for|to) (?:new )?(?:jobs?|roles?)",
    "interviewing": r"i(?: am|'m) (?:currently )?interviewing for (?:a |new )?(?:job|role)|i have (?:an?|a job) interview (?:scheduled|booked)",
}
_STAGES = {
    "promotion": {
        "no_review_scheduled": r"i (?:have no|don.t have a) (?:performance )?review scheduled",
        "review_scheduled": r"i have a (?:performance )?review scheduled|my (?:performance )?review is (?:scheduled|booked)",
        "promotion_discussed": r"my (?:manager|boss) (?:has )?(?:discussed|raised) (?:a |my )?promotion",
    },
    "job_change": {**_SEARCH_STAGES, "offer_received": r"i(?: have|'ve) received a (?:written|formal) (?:job )?offer"},
    "job_offer": _SEARCH_STAGES,
}


def reported_stage(event_type, user_messages):
    """Recognize explicit current statements. Unknown facts stay unspecified."""
    rules = _STAGES.get(event_type, {})
    for message in reversed(user_messages[-6:]):
        clauses = re.split(r"(?<=[.!?])\s+|[;\n]", message.replace("’", "'"))
        for clause in reversed(clauses):
            if clause.rstrip().endswith("?") or re.search(r"\b(?:if|might|maybe|suppose|example)\b", clause, re.I):
                continue
            for stage, pattern in rules.items():
                if re.match(pattern, clause.strip(), re.I):
                    return stage
    return None


def house_contacts(facts, planets, houses, varga):
    """Direct rulership/occupancy. Two links to the same house count once."""
    chart = facts.get("vargas", {}).get(varga, {})
    if "Lagna" not in chart:
        return []
    asc = chart["Lagna"]["sign"]
    contacts = []
    for planet in dict.fromkeys(planets):
        if planet not in chart:
            continue
        placement = house(chart[planet]["sign"], asc)
        for number in houses:
            ruler = K.PLANET_NAMES[K.SIGN_LORD[(asc + number - 1) % 12]]
            relations = [label for label, linked in (("rules", ruler == planet),
                                                     ("occupies", placement == number)) if linked]
            if relations:
                contacts.append({"planet": planet, "chart": varga, "house": number,
                                 "relations": relations, "factor": f"{varga}:{planet}:H{number}"})
    return contacts


def signals(facts, lords, event_type):
    work, event, divisional = RULES[event_type]
    # The major lord sets the background. The two shorter clocks must carry
    # the event; repeating the same planet at both clocks adds no evidence.
    active = lords[1:]
    work_links = house_contacts(facts, active, work, "D1")
    event_links = house_contacts(facts, active, event, "D1")
    divisional_links = house_contacts(facts, active, divisional, "D10")
    missing = [label for label, group in (("work-house contact in D1", work_links),
                                          ("event-house contact in D1", event_links),
                                          ("corroboration in D10", divisional_links)) if not group]
    return {"qualifies": len(lords) == 3 and not missing, "missing": missing,
            "contacts": work_links + event_links + divisional_links, "active_lords": list(lords)}


def qualify_windows(facts, birth, event_type, windows, reference_day):
    def at(day):
        periods = engine.running_vimshottari(birth, (day.year, day.month, day.day))
        lords = periods[-1]["lords"] if periods else ()
        return {"sample": day.isoformat(), **signals(facts, lords, event_type)}

    checked = []
    for window in windows:
        day = date.fromisoformat(window.get("peak_date", window["start"]))
        checked.append({"start": window["start"], "end": window["end"], **at(day)})
    return {"rule_version": VERSION, "event_type": event_type, "windows": checked,
            "background_sample": at(reference_day)}
