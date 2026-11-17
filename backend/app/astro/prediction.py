"""Versioned, frozen forecast decisions and honest outcome accounting."""
import re
import math
from datetime import date

VERSION = "2026-11-17.1"
# These definitions are prospective scoring targets, not generated event promises.
EVENTS = [
    ("career", r"promot", "promotion", "A formal promotion to a higher role takes effect"),
    ("career", r"job change|change.{0,15}job|switch.{0,15}job", "job_change", "A new job with a different employer begins"),
    ("career", r"offer|get.{0,12}job|find.{0,12}job", "job_offer", "A formal job offer is received"),
    ("career", r"start.{0,15}business|launch.{0,15}business", "business_launch", "The stated business starts trading"),
    ("relationship", r"engag", "engagement", "A mutually agreed formal engagement occurs"),
    ("relationship", r"marry|marriage|wedding|married", "marriage", "A marriage ceremony or legal marriage occurs"),
    ("education", r"pass.{0,20}exam", "exam_pass", "An official passing result for the stated exam is received"),
    ("education", r"admission|admitted", "admission", "A formal admission offer is received"),
    ("education", r"graduat|complete.{0,15}degree", "graduation", "The stated qualification is officially completed"),
    ("relocation", r"move|relocat|abroad|foreign|settle", "relocation", "A move of primary residence to the stated destination occurs"),
]


def event_spec(question, domain):
    for dom, pattern, event, definition in EVENTS:
        if dom == domain and re.search(pattern, question, re.I):
            return {"event_type": event, "definition": definition}
    return None


def decide(question, analysis):
    spec = event_spec(question, analysis["domain"])
    reasons = []
    prec, sens = analysis.get("precision", {}), analysis.get("sensitivity", {})
    if date.fromisoformat(analysis["analysis_window"]["end"]) < date.today():
        reasons.append("This is a retrospective interval, not a future event forecast.")
    if not spec:
        reasons.append("The question needs one observable event before it can be scored.")
    if analysis["unavailable_count"]:
        reasons.append("One or more core methods are unavailable.")
    if not sens.get("verdict_stable"):
        reasons.append("The conclusion changes across sampled birth times, or a sample is unavailable.")
    if not sens.get("timing_stable"):
        reasons.append("The proposed timing changes across sampled birth times, or a sample is unavailable.")
    if any(prec.get(k) == "unavailable" for k in ("yogini", "sudarshana")):
        reasons.append("A confirmation method is unavailable.")
    if prec.get("confirmation") == "Hidden friction":
        reasons.append("The secondary methods conflict with a positive event forecast.")
    disposition = "abstain"
    if not reasons and analysis["support_count"] >= 3 and analysis["conflict_count"] == 0:
        disposition = "event_indicated"
    elif not reasons:
        reasons.append("The methods do not provide sufficient conflict-free support for an event forecast.")
    return {"version": VERSION, "disposition": disposition, "event": spec,
            "window": analysis["analysis_window"], "reasons": reasons,
            "success_criteria": ((spec["definition"] + " within " + analysis["analysis_window"]["start"] +
                                  " to " + analysis["analysis_window"]["end"] + ".") if spec else None),
            "note": "Rule-based indication, not a measured probability or guarantee."}


def prospective_rows(rows):
    candidates = [r for r in rows if r.get("forecast") in ("event_indicated", "no_event_indicated")
                 and r.get("protocol") and r.get("success_criteria")
                 and r.get("created_at") and r.get("window_start")
                 and str(r["created_at"])[:10] < str(r["window_start"])[:10]]
    # Repeated wording of the same event/window must not multiply its score.
    qualified, seen = [], set()
    for r in sorted(candidates, key=lambda row: str(row["created_at"])):
        key = (r.get("profile_id"), r.get("event_type"), r["success_criteria"], str(r["window_start"]), str(r.get("window_end")))
        if key not in seen:
            qualified.append(r)
            seen.add(key)
    return qualified, len(candidates) - len(qualified)


def scorecard(rows, today=None):
    """Only frozen, prospective, explicit event forecasts enter accuracy counts.

    Missing responses, partial outcomes, abstentions, legacy rows and events
    outside the interval cannot be silently treated as successful predictions.
    """
    today = today or date.today()
    total = len(rows)
    qualified, duplicates = prospective_rows(rows)
    matured = [r for r in qualified if r.get("window_end") and date.fromisoformat(str(r["window_end"])[:10]) < today]
    hits = misses = 0
    for r in matured:
        outcome = r.get("outcome")
        if outcome not in ("happened", "did_not", "outside_window"):
            continue
        positive = outcome == "happened"
        expected = r["forecast"] == "event_indicated"
        hits += int(positive == expected)
        misses += int(positive != expected)
    n = hits + misses
    interval = None
    if n:
        # Wilson interval for the observed, self-reported subset only.
        z = 1.96
        phat, denom = hits / n, 1 + z*z/n
        centre = (phat + z*z/(2*n)) / denom
        half = z * math.sqrt(phat*(1-phat)/n + z*z/(4*n*n)) / denom
        interval = [max(0, centre-half), min(1, centre+half)]
    abstentions = sum(r.get("forecast") == "abstain" for r in rows)
    issued = sum(r.get("forecast") in ("event_indicated", "no_event_indicated") for r in rows)
    return {"total_analyses": total, "issued_forecasts": issued, "abstentions": abstentions,
            "forecast_coverage": issued / total if total else None,
            "prospective_forecasts": len(qualified), "duplicate_forecasts_excluded": duplicates, "matured": len(matured),
            "scored": hits + misses, "hits": hits, "misses": misses,
            "partial": sum(r.get("outcome") == "partly" for r in matured),
            "unresolved": sum(r.get("outcome") in (None, "unsure") for r in matured),
            "observed_hit_rate": hits / (hits + misses) if hits + misses else None,
            "observed_hit_rate_wilson95": interval,
            "note": "Self-reported outcomes; not independently validated. Partial and unanswered outcomes are not hits. Legacy and same-day/retrospective forecasts are excluded."}


def interpretation_reading(analysis, facts=None):
    """A useful computed-chart answer when no event forecast is being issued."""
    from .constants import DOMAINS
    domain = analysis.get("domain", "direction")
    focus = {
        "career": "Are you mainly thinking about your current role, a job change, or starting a business?",
        "relationship": "Are you asking about an existing relationship or finding a partner?",
        "education": "Which course, qualification, or exam are you considering?",
        "relocation": "Where are you considering moving, and what is prompting the move?",
        "finance": "Is your main concern income, savings, or a specific financial commitment?",
        "direction": "Which part of your life feels most uncertain right now?",
        "health": "What would you like to understand about the chart's traditional health indicators?",
    }
    lines = []
    if facts:
        house = DOMAINS.get(domain, DOMAINS["direction"])["houses"][0]
        houses = facts.get("houses", {})
        lord = (houses.get(house) or houses.get(str(house)) or {}).get("lord")
        rec = facts.get("planets", {}).get(lord)
        if rec:
            lines.append(f"For {domain}, a key part of this chart is {lord}, which rules house {house} "
                         f"and is placed in {rec['sign_name']} in house {rec['house']}.")
    if not lines:
        lines.append(f"We can explore {domain} through the chart's planetary placements and current periods.")
    lines.append(focus.get(domain, focus["direction"]))
    return " ".join(lines)


def constrain_reply(reply, analysis, facts=None):
    """Preserve helpful readings while rejecting unsupported event promises."""
    decision = analysis["decision"]
    abstained = decision["disposition"] == "abstain"
    allowed = set() if abstained else {decision["window"]["start"], decision["window"]["end"]}
    if not abstained:
        for w in analysis.get("precision", {}).get("timing_windows", []):
            allowed.update((w["start"], w["end"]))
    dates = set(re.findall(r"\b20\d\d-\d{2}-\d{2}\b", reply))
    certainty = re.search(r"\b(guaranteed|definitely|certainly|confirmed|will\s+(?:get|receive|marry|move|happen|occur|be promoted))\b", reply, re.I)
    prose_date = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b", reply, re.I)
    internal = re.search(r"observable event|before it can be scored|reliable event forecast|chart methods can still|\b[0-4]/4\b|rule agreement|disposition|abstention|success criteria", reply, re.I)
    if dates - allowed or certainty or prose_date or internal:
        return interpretation_reading(analysis, facts)
    return reply
