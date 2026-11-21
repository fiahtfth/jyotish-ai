"""Desha-Kala-Patra (place, time, circumstances) context for the model.

Traditional practice reads a chart in light of WHERE (desha), WHEN (kala) and
FOR WHOM / under what circumstances (patra). This builds that frame from what
the app actually knows, so the model resolves ambiguous questions from the
profile instead of asking the user things the profile already answers.
Only recorded facts are stated; anything unknown is marked unknown.
"""
from __future__ import annotations

from datetime import date

# Country-level education framing; only India is spelled out because it is the
# main audience. Everything else gets a neutral description.
_EDU_INDIA = ("After Class 10 students choose a stream (Science/PCM/PCB, Commerce, Arts/Humanities); "
              "after Class 12 they choose a degree and specialisation (engineering branch, B.Com, BA subjects, "
              "medicine, law, design etc.); then postgraduate study or entrance exams.")
_EDU_GENERIC = ("Secondary school subject tracks, then a university major/degree, then postgraduate study "
                "or professional training.")


def age_on(profile, today: date) -> int | None:
    try:
        y, m, d = int(profile.year), int(profile.month), int(profile.day)
    except (TypeError, ValueError):
        return None
    return today.year - y - ((today.month, today.day) < (m, d))


def life_stage(age: int | None) -> str:
    if age is None:
        return "unknown"
    if age < 12:
        return "child (primary school age)"
    if age < 15:
        return "early adolescent (middle school; stream/subject choice is approaching)"
    if age < 18:
        return "school student (senior secondary: stream/subject and college-entrance decisions)"
    if age < 23:
        return "undergraduate / early higher-education years"
    if age < 30:
        return "early career / postgraduate / marriage-consideration years"
    if age < 45:
        return "established career and family-building years"
    if age < 60:
        return "peak responsibility, children's education, career consolidation"
    return "senior years (retirement, health, legacy, spiritual focus)"


def residence_label(profile) -> str:
    parts = [getattr(profile, "residence_name", None), getattr(profile, "residence_state", None),
             getattr(profile, "residence_country", None)]
    return ", ".join(x.strip() for x in parts if isinstance(x, str) and x.strip())


def time_note(profile, facts: dict | None = None) -> str:
    """How far the birth time can be trusted; empty when it is recorded as exact."""
    precision = getattr(profile, "birth_time_precision", "exact")
    if precision == "unknown":
        mm = (facts or {}).get("moon_mode") or {}
        extra = ""
        if mm.get("sign_changes"):
            extra = (" The Moon changes sign on the birth date, so give both Moon-sign possibilities and say "
                     "which readings are uncertain.")
        elif mm.get("nakshatra_changes"):
            extra = " The Moon changes nakshatra on the birth date, so dasha timing is uncertain; say so."
        return ("- Birth time: UNKNOWN. Read from the Moon sign as Lagna (Chandra Lagna) and say so briefly once. "
                "Never state a Lagna, houses from Lagna, divisional-chart Lagnas, arudhas, KP or bhava data. "
                "Sun, Moon, planets-in-signs, nakshatras and Vimshottari periods can be used." + extra)
    if precision == "approximate":
        return ("- Birth time: approximate (about plus or minus 30 minutes). Label Lagna-dependent statements "
                "(Lagna, houses, divisional-chart Lagnas, arudhas) as provisional; Moon-sign and planet-in-sign "
                "readings are solid.")
    return ""


def build(profile, today: date, facts: dict | None = None, milestones=None, stated_facts=()) -> str:
    age = age_on(profile, today)
    country = (getattr(profile, "place_country", "") or "").strip()
    is_india = country.lower() in ("india", "in", "bharat")
    run = (facts or {}).get("current_vimshottari") or []
    # engine.running_vimshottari returns rows of {"lords": [MD, AD, PD...], start, end}
    lords = (run[-1].get("lords") if run and isinstance(run, list) else None) or []
    md = lords[0] if len(lords) > 0 else None
    ad = lords[1] if len(lords) > 1 else None
    lines = [
        "CONTEXT (Desha-Kala-Patra — use it to interpret the question before asking anything):",
        f"- Kala (time): today is {today.isoformat()}; "
        + (f"the native is {age} years old — {life_stage(age)}." if age is not None else "age unknown.")
        + (f" Running Vimshottari period: {md}{'/' + str(ad) if ad else ''}." if md else ""),
        f"- Desha (place): born in {profile.place_name or 'unknown place'}"
        + (f", {profile.place_state}" if getattr(profile, "place_state", "") else "")
        + (f", {country}" if country else "")
        + ". Treat the birthplace as the chart anchor; never ask where they live. "
        + (f"The native currently lives in {residence_label(profile)}: use that for transits, panchang and "
           "practical timing advice. " if residence_label(profile) else "")
        + "Education system assumed: " + (_EDU_INDIA if is_india else _EDU_GENERIC),
    ]
    note = time_note(profile, facts)
    if note:
        lines.append(note)
    if age is not None and age < 18:
        lines.append("- Minor: the native is under 18. Frame career and education only as natural aptitude and "
                     "interests, never as predicted outcomes. No marriage, romance, health or longevity topics.")
    rel = getattr(profile, "relation", "self") or "self"
    patra = (f"- Patra (person/circumstances): chart is for the user themselves."
             if rel == "self" else
             f"- Patra (person/circumstances): chart is for the user's {rel}, not the user.")
    lines.append(patra)
    events = [m for m in (milestones or []) if getattr(m, "description", "")]
    if events:
        lines.append("  Life events the user reported: " + "; ".join(
            f"{m.description} ({m.year}{'-%02d' % m.month if m.month else ''})" for m in events[:6]))
    stated = [s.strip() for s in stated_facts if isinstance(s, str) and s.strip()]
    if stated:
        # Most recent first; a later statement corrects an earlier one.
        lines.append("  Facts the user has stated about their life (most recent first; accept as true): "
                     + "; ".join(f'"{s[:200]}"' for s in stated[:5]))
    lines.append(
        "RULES: (1) Resolve ambiguous words from this context — e.g. 'graduation stream' for a school-age native "
        "means the school stream/subject track, for a college-age native it means degree specialisation; "
        "do not ask which. (2) Never ask for information this context already provides (age, birthplace, "
        "relation). (3) If the question is implausible for the age or stage (e.g. retirement at 15), say so "
        "gently and answer the nearest sensible question. (4) Frame advice for the stage and country; "
        "do not ask for location details. "
        "(5) For 'which/what suits me' questions give 2–3 ranked options with the chart reasons, "
        "not a timing window. (6) When the user states a fact about their life (a degree, job, move, "
        "marriage, with a year), accept it as true, acknowledge it in one short clause, and respond with what "
        "the chart indicates for their NEXT step given their age and that history. Do not repeat it back "
        "with a chart justification, and do not ask what they want next. (7) NEVER ask the user for a time "
        "frame. If timing matters and none was given, use the running Vimshottari period and the coming "
        "12 months by default and name that period.")
    return "\n".join(lines)
