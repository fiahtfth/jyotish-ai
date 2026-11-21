"""Versioned, frozen forecast decisions and honest outcome accounting."""
import re
import math
from datetime import date

VERSION = "2026-11-21.1"
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
    ("relocation", r"settle abroad|move abroad", "foreign_settlement",
     "The stated party establishes primary residence in a foreign country"),
    ("relocation", r"going abroad|travel(?:l?ing)? abroad|trip abroad|"
                   r"foreign (?:posting|assignment|job|travel|trip)|"
                   r"videsh|overseas", "foreign_travel",
     "Travel to a foreign country occurs"),
    ("relocation", r"\b(?:move|moving|relocat\w*|settle|settling|change of residence)\b",
     "relocation", "A move of primary residence to the stated destination occurs"),
    # Conception/childbirth asks are declined by safety.private_reply before
    # any event is scored, so no childbirth event is defined here.
    ("property", r"buy.{0,25}(?:car|vehicle|bike|scooter|motorcycle)|"
                 r"purchas\w*.{0,20}(?:car|vehicle|bike|scooter|motorcycle)|"
                 r"own (?:a )?(?:car|vehicle|bike)|gaadi",
     "vehicle_purchase", "Purchase of the stated vehicle completes"),
    ("property", r"buy.{0,25}(?:house|home|flat|property|plot|land)|"
                 r"purchas\w*.{0,20}(?:house|home|flat|property)|"
                 r"own (?:a )?(?:house|home|flat)|makaan",
     "property_purchase", "Purchase of the stated property completes"),
    ("litigation", r"win.{0,15}(?:case|lawsuit|litigation)|favou?r",
     "litigation_win", "A ruling in favour of the stated party is delivered"),
    ("litigation", r"court|lawsuit|legal|resolve|settle", "litigation_resolution",
     "A final ruling in the stated litigation is delivered"),
    ("debt", r"clear.{0,15}(?:debt|loan)|debt.{0,10}free|repay|pay off",
     "debt_cleared", "The stated debt or loan is fully repaid"),
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
    today = (as_of or date.today()).isoformat()
    requested = analysis["analysis_window"]
    if requested["end"] <= today:
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
    window = requested
    if audit is not None:
        if audit["promise"] not in ("Strong", "Moderate"):
            reasons.append("The natal and divisional checks give limited or unavailable support.")
        if audit["timing_sensitive"]:
            reasons.append("The relevant divisional ascendant changes within five minutes.")
        candidates = [w for w in prec.get("timing_windows", [])
                      if today < w["start"] and requested["start"] <= w["start"] <= w["end"] <= requested["end"]]
        if not candidates:
            reasons.append("No prospective window passed the aligned dasha and micro-timing checks.")
        elif method := analysis.get("career_event_method"):
            qualifying = {(w["start"], w["end"]) for w in method["windows"] if w["qualifies"]}
            candidates = [w for w in candidates if (w["start"], w["end"]) in qualifying]
            if not candidates:
                reasons.append("No window also met the rules for this specific career event.")
        if candidates:
            window = {key: candidates[0][key] for key in ("start", "end")}
    disposition = "abstain"
    if not reasons and (audit or (analysis["support_count"] >= 3 and analysis["conflict_count"] == 0)):
        disposition = "event_indicated"
    elif not reasons:
        reasons.append("The methods do not provide sufficient conflict-free support for an event forecast.")
    if disposition == "abstain":
        window = requested
    return {"version": VERSION, "disposition": disposition, "event": spec,
            "window": window, "reasons": reasons,
            "success_criteria": (f"{spec['definition']} within {window['start']} to {window['end']}." if spec else None),
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
    window = (analysis.get("decision") or {}).get("window", analysis["analysis_window"])
    period = window_label((date.fromisoformat(window["start"]), date.fromisoformat(window["end"])))
    event = (analysis.get("decision", {}).get("event") or {}).get("event_type")
    labels = {"job_change": "a job change", "job_offer": "a job offer", "promotion": "a promotion",
              "business_launch": "starting a business", "exam_pass": "passing the exam",
              "relocation": "a move", "engagement": "an engagement"}
    subject = labels.get(event, (event or analysis["domain"]).replace("_", " "))
    return f"For {subject} in {period}"


def issued_reading(analysis):
    """Render the frozen event and single window without model substitutions."""
    decision = analysis["decision"]
    start, end = (date.fromisoformat(decision["window"][key]).strftime("%d %b %Y") for key in ("start", "end"))
    event = decision["event"]["definition"]
    labels = {"promotion": "a formal promotion taking effect",
              "job_change": "starting a job with a different employer",
              "job_offer": "receiving a formal job offer"}
    label = labels.get(decision["event"]["event_type"])
    period = f"on {start}" if start == end else f"from {start} through {end}"
    lead = (f"The traditional chart indicators for {label} overlap {period}." if label else
            f"The traditional timing rules point to {period.removeprefix('from ').removeprefix('on ')}. "
            f"The event being assessed is whether {event[0].lower()}{event[1:]}.")
    return f"{lead} The actual outcome remains uncertain."


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
        background = analysis.get("career_event_method", {}).get("background_sample", {})
        contacts = background.get("contacts", [])
        if contacts:
            contact = next((c for c in contacts if c["chart"] == "D10"), contacts[0])
            chart_name = "the career chart (D10)" if contact["chart"] == "D10" else "the natal chart"
            detail = (f"At the midpoint of this period, the active lord {contact['planet']} "
                      f"{' and '.join(contact['relations'])} house {contact['house']} in {chart_name}")
        elif audit and facts and decision.get("event"):
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
            # Sentences may wrap across newlines; keep each sentence's original
            # trailing whitespace so kept text preserves the line structure.
            pieces = re.split(r"((?<=[.!?])\s+)", para)
            kept_parts = []
            for i in range(0, len(pieces), 2):
                sentence = pieces[i]
                sep = pieces[i + 1] if i + 1 < len(pieces) else ""
                if not sentence.strip():
                    continue
                if bad(sentence):
                    # A run of list/table rows reads as one sentence: drop only
                    # the offending rows, not the whole table. Wrapped prose must
                    # still drop whole so a claim's leading fragment can't survive.
                    rows = sentence.split("\n")

                    def is_row(ln: str) -> bool:
                        # "·" lines are table rows already flattened by _plain_reply.
                        return bool(re.match(r"\s*(?:[-*•|>]|\d+[.)])\s*\S", ln)
                                    or "·" in ln)

                    rowish = sum(1 for ln in rows if is_row(ln))
                    if sentence.count("\n") >= 2 and rowish * 2 > len(rows):
                        def fragment(i: int, ln: str) -> bool:
                            # A line that wraps into another line forming a bad
                            # claim goes too — but a caveat before a bad *row*
                            # stays, and so does a row before a bad prose line.
                            # A row only wraps into an *indented* continuation.
                            nxt = rows[i + 1] if i + 1 < len(rows) else None
                            if (ln.rstrip()[-1:] not in ".!?" and nxt is not None
                                    and not is_row(nxt) and bad(ln + " " + nxt)
                                    and (not is_row(ln)
                                         or (nxt[:1] in (" ", "\t")
                                             and not bad(nxt)))):
                                return True
                            prv = rows[i - 1] if i else ""
                            return bool(
                                not is_row(ln) and prv and not bad(prv)
                                and fragment(i - 1, prv)
                                and bad(prv + " " + ln))
                        kept_pairs = [(i, ln) for i, ln in enumerate(rows)
                                      if ln.strip() and not bad(ln)
                                      and not fragment(i, ln)]
                        kept_lines = [ln for _, ln in kept_pairs]
                        if not any(is_row(ln) for ln in kept_lines):
                            # No rows survive: complete or substantive prose
                            # still answers, but a bare lead-in is no reply.
                            kept_pairs = [(i, ln) for i, ln in kept_pairs
                                          if ln.rstrip()[-1:] in ".!?"
                                          or (len(ln.split()) >= 4
                                              and not ln.rstrip().endswith(":"))]
                        # Deleting rows can leave two prose halves adjacent whose
                        # join rebuilds the rejected claim — drop both halves.
                        final = []
                        for i, ln in kept_pairs:
                            if (final and i > final[-1][0] + 1
                                    and not is_row(final[-1][1])
                                    and final[-1][1].rstrip()[-1:] not in ".!?"
                                    and not is_row(ln)
                                    and bad(final[-1][1] + " " + ln)):
                                final.pop()
                                continue
                            final.append((i, ln))
                        sentence = "\n".join(ln for _, ln in final)
                    else:
                        continue
                if sentence.strip():
                    kept_parts.append(sentence + sep)
            kept = "".join(kept_parts)
            if kept.strip():
                paragraphs.append(kept.strip())
        if paragraphs:
            return "\n\n".join(paragraphs)
        return interpretation_reading(analysis, facts, messages)
    return reply
