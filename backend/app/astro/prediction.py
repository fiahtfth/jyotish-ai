"""Versioned, frozen forecast decisions and honest outcome accounting."""
import re
import math
from datetime import date

VERSION = "2026-11-19.1"
# These definitions are prospective scoring targets, not generated event promises.
EVENTS = [
    ("career", r"promot|move up (?:at work|the ladder)|higher role|पदोन्नति", "promotion", "A formal promotion to a higher role takes effect"),
    ("career", r"job (?:change|switch)|chang(?:e|ing).{0,15}jobs?|switch.{0,15}(?:jobs?|companies|employers?)|different employer|(?:new role|new job) at (?:a different|another) company|leave my (?:job|company)|naukri badal", "job_change", "A new job with a different employer begins"),
    ("career", r"offer|get.{0,12}job|find.{0,12}job", "job_offer", "A formal job offer is received"),
    ("career", r"start.{0,15}business|launch.{0,15}business", "business_launch", "The stated business starts trading"),
    ("relationship", r"engag", "engagement", "A mutually agreed formal engagement occurs"),
    ("relationship", r"marry|marriage|wedding|married|tie the knot|shaadi|shadi|शादी", "marriage", "A marriage ceremony or legal marriage occurs"),
    ("education", r"pass.{0,20}exam", "exam_pass", "An official passing result for the stated exam is received"),
    ("education", r"admission|admitted", "admission", "A formal admission offer is received"),
    ("education", r"graduat|complete.{0,15}degree", "graduation", "The stated qualification is officially completed"),
    ("relocation", r"\b(?:move|moving|relocat\w*|settle|settling|change of residence)\b",
     "relocation", "A move of primary residence to the stated destination occurs"),
]


def event_spec(question, domain):
    for dom, pattern, event, definition in EVENTS:
        if dom == domain and re.search(pattern, question, re.I):
            return {"event_type": event, "definition": definition}
    return None


def decide(question, analysis, event=None, *, as_of=None):
    spec = event or event_spec(question, analysis["domain"])
    reasons = []
    prec, sens = analysis.get("precision", {}), analysis.get("sensitivity", {})
    if date.fromisoformat(analysis["analysis_window"]["end"]) < (as_of or date.today()):
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
    audit = analysis.get("classical")
    if audit:
        if audit["promise"] not in ("Strong", "Moderate"):
            reasons.append("The natal and divisional checks give limited or unavailable support.")
        if audit["timing_sensitive"]:
            reasons.append("The relevant divisional ascendant changes within five minutes.")
        if not any(s["complete"] and s["count"] >= 3 for s in audit["scores"]):
            reasons.append("Fewer than three classical gates align on a fully evaluated sample.")
    disposition = "abstain"
    if not reasons and (audit or (analysis["support_count"] >= 3 and analysis["conflict_count"] == 0)):
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


def reading_subject(analysis):
    from ..chat.language import window_label
    window = analysis["analysis_window"]
    period = window_label((date.fromisoformat(window["start"]), date.fromisoformat(window["end"])))
    event = (analysis.get("decision", {}).get("event") or {}).get("event_type")
    labels = {"job_change": "a job change", "job_offer": "a job offer", "promotion": "a promotion",
              "business_launch": "starting a business", "exam_pass": "passing the exam",
              "relocation": "a move", "engagement": "an engagement"}
    subject = labels.get(event, (event or analysis["domain"]).replace("_", " "))
    return f"For {subject} in {period}"


def interpretation_reading(analysis, facts=None, messages=None):
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
    history = [m["content"] for m in (messages or []) if m["role"] == "assistant"]
    user_text = next((m["content"].lower() for m in reversed(messages or []) if m["role"] == "user"), "")
    question = focus.get(domain, focus["direction"])
    repeated = any(question in old or lines[0] in old for old in history)
    decision = analysis.get("decision", {})
    if repeated or decision.get("event") or analysis.get("period_requested"):
        subject = reading_subject(analysis)
        signals = analysis.get("support_count", 0)
        conflicts = analysis.get("conflict_count", 0)
        if conflicts:
            reading = "The timing methods give mixed indications for this period."
        elif signals:
            reading = f"Some indicators support activity in {domain} during this period."
        else:
            reading = f"The timing methods show little support for a change in {domain} during this period."
        audit = analysis.get("classical") or {}
        if audit.get("promise") == "Weak":
            reading = "The natal and divisional checks give limited support for a major change."
        if decision.get("event"):
            reading += " The chart gives no clear basis for saying that event will happen then."
        evidence = analysis.get("calculation_evidence_ids") or []
        details = [item.split(": ", 1)[-1].rstrip(".") for item in evidence if "error:" not in item]
        detail = next((item for item in details if all(item not in old for old in history)), "")
        if audit and facts and decision.get("event"):
            h = DOMAINS[domain]["houses"][0]
            n = facts["houses"][h]["lord"]
            rec = facts["planets"][n]
            detail = (f"The ruler of house {h}, {n}, is at {rec['degree']:.4f}° "
                      f"in {rec['sign_name']}, in house {rec['house']}")
        if detail:
            reading += " " + detail[0].upper() + detail[1:] + "."
        return f"{subject}, {reading[0].lower()}{reading[1:]}"
    if domain == "career":
        if "business" in user_text:
            question = "What kind of business are you considering, and are you starting it alongside your current work?"
        elif "promotion" in user_text or "current role" in user_text:
            question = "What role are you in now, and what change are you hoping for?"
        elif "change" in user_text or "switch" in user_text:
            question = "What is prompting the job change, and what kind of role are you considering?"
    lines.append(question)
    return " ".join(lines)


def constrain_reply(reply, analysis, facts=None, messages=None):
    """Preserve helpful readings while rejecting unsupported event promises."""
    decision = analysis["decision"]
    abstained = decision["disposition"] == "abstain"
    audit = analysis.get("classical")
    if audit and (re.search(r"\b(?:KP sub[- ]?lord|sub[- ]?lord|bindus?)\b|\d\s*%", reply, re.I)
                  or (decision.get("event") and audit["promise"] in ("Weak", "Unavailable"))):
        return interpretation_reading(analysis, facts, messages)
    allowed = set() if abstained else {decision["window"]["start"], decision["window"]["end"]}
    if not abstained:
        for w in analysis.get("precision", {}).get("timing_windows", []):
            allowed.update((w["start"], w["end"]))
    dates = set(re.findall(r"\b20\d\d-\d{2}-\d{2}\b", reply))
    certainty = re.search(r"\b(guaranteed|definitely|certainly|confirmed|will\s+(?:get|receive|marry|move|happen|occur|be promoted))\b", reply, re.I)
    prose_date = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d{2})?|20\d{2})\b", reply, re.I)
    internal = re.search(r"observable event|before it can be scored|reliable event forecast|chart methods can still|\b[0-4]/4\b|rule agreement|disposition|abstention|success criteria", reply, re.I)
    if dates - allowed or certainty or prose_date or internal:
        # Remove only the offending sentences, preserving the reply's line
        # structure. A single unsupported claim must not erase the rest of an
        # otherwise useful answer — or collapse every newline into one blob.
        def bad(sentence: str) -> bool:
            bad_dates = set(re.findall(r"\b20\d\d-\d{2}-\d{2}\b", sentence)) - allowed
            if bad_dates or re.search(r"\b(guaranteed|definitely|certainly|confirmed|will\s+(?:get|receive|marry|move|happen|occur|be promoted))\b", sentence, re.I):
                return True
            if re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d", sentence, re.I):
                return True
            return bool(re.search(r"observable event|before it can be scored|reliable event forecast|chart methods can still|\b[0-4]/4\b|rule agreement|disposition|abstention|success criteria", sentence, re.I))
        paragraphs = []
        for para in re.split(r"\n\s*\n", reply):
            kept_lines = []
            for line in para.split("\n"):
                kept = [s.strip() for s in re.split(r"(?<=[.!?])[ \t]+", line)
                        if s.strip() and not bad(s)]
                if kept:
                    kept_lines.append(" ".join(kept))
            if kept_lines:
                paragraphs.append("\n".join(kept_lines))
        if paragraphs:
            return "\n\n".join(paragraphs)
        return interpretation_reading(analysis, facts, messages)
    return reply
