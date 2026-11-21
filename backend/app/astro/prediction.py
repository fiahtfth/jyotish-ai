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


# Questions about WHICH field/stream/subject suits someone are natal (what-fits)
# questions, not "when will X happen" events, even if they mention graduation.
_FIELD_QUESTION = re.compile(
    r"\b(?:stream|streams|field|fields|subject|subjects|branch|branches|major|specializ\w+|"
    r"course|courses|degree|discipline)\b", re.I)
_WHEN_WORDS = re.compile(r"\b(?:when|will i|date|month|year|time|timing|soon)\b", re.I)


def is_field_question(question):
    """'Which stream/field/subject suits me' — a natal what-fits question, not a timing one."""
    return bool(_FIELD_QUESTION.search(question) and not _WHEN_WORDS.search(question))


def event_spec(question, domain):
    if domain == "education" and is_field_question(question):
        return None
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


def interpretation_reading(analysis, facts=None, messages=None, ask_followup=True):
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
            detail = (f"The ruler of house {h}, {n}, is in {rec['sign_name']}, "
                      f"in house {rec['house']}")
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
    if ask_followup:
        lines.append(question)
    return " ".join(lines)


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
# capitalised month only, so modal "may" / verb "march" never match
_PROSE_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\b(?:\s+(\d{1,2})(?:st|nd|rd|th)?)?(?:,?\s+(20\d\d))?(?!\d)")
_NEG = r"(?<!not )(?<!never )(?<!n't )(?<!no )"
# A definitive outcome promise: "guaranteed", "will definitely ...", "will get the promotion",
# "your promotion is confirmed". "you confirmed ..." and ordinary "definitely" stay.
_CERTAINTY = re.compile(
    _NEG + r"\b(?:guaranteed|assured\s+(?:of|to)|for\s+sure|without\s+(?:a\s+)?doubt)\b"
    r"|\bwill\s+(?:definitely|certainly|surely|absolutely)\b"
    r"|\b(?:definitely|certainly|surely)\s+will\b"
    r"|\b(?:is|are|been|be)\s+(?:definitely\s+)?confirmed\b"
    r"|\bwill\s+(?:get|receive)\s+(?:the|a|an|your)?\s*(?:promotion|job|offer|visa|admission|raise|hike|transfer)\b"
    r"|\bwill\s+(?:marry|be\s+promoted|relocate|move\s+abroad)\b"
    r"|\bwill\s+(?:happen|occur)\s+(?:on|in|by)\b", re.I)
_PROBABILITY = re.compile(
    r"\b\d{1,3}\s*(?:-|to)\s*\d{1,3}\s*%|\b(?:chances?|probabilit\w*|odds|likel\w+)\b[^.!?\n]{0,40}\d\s*%"
    r"|\d\s*%[^.!?\n]{0,25}\b(?:chances?|probabilit\w*|likel\w+)\b", re.I)
_INTERNAL = re.compile(
    r"observable event|before it can be scored|reliable event forecast|chart methods can still|\b[0-4]/4\b|"
    r"rule agreement|disposition|abstention|success criteria", re.I)
_KP = re.compile(r"\b(?:KP sub[- ]?lord|sub[- ]?lord|bindus?)\b", re.I)


def _window_range(analysis):
    decision_window = (analysis.get("decision") or {}).get("window")
    # Once a window is issued it is the only period the reply may date;
    # precision.timing_windows are candidates the decision did not issue.
    if decision_window is not None:
        windows = [decision_window]
    else:
        windows = [analysis.get("analysis_window"),
                   *((analysis.get("precision") or {}).get("timing_windows") or [])]
    spans = []
    for w in windows:
        try:
            spans.append((date.fromisoformat(w["start"]), date.fromisoformat(w["end"])))
        except (TypeError, KeyError, ValueError):
            continue
    return spans


def _reply_context(analysis, facts, messages):
    user_text = "\n".join(m["content"] for m in (messages or []) if m.get("role") == "user")
    try:
        import json
        blob = json.dumps(analysis, default=str)
    except (TypeError, ValueError):
        blob = ""
    # Candidate windows the decision did not issue: their dates appear in the
    # analysis blob, so they need an explicit rejection check.
    rejected = []
    decision_window = (analysis.get("decision") or {}).get("window")
    if decision_window:
        issued = (decision_window.get("start"), decision_window.get("end"))
        for w in (analysis.get("precision") or {}).get("timing_windows") or []:
            if (w.get("start"), w.get("end")) == issued:
                continue
            try:
                rejected.append((date.fromisoformat(w["start"]), date.fromisoformat(w["end"])))
            except (TypeError, KeyError, ValueError):
                continue
    return {"spans": _window_range(analysis), "rejected": rejected,
            "user": user_text, "blob": blob}


def _in_spans(y, m, d, spans):
    """True if the date (day optional) falls inside any analysis window."""
    for start, end in spans:
        if d:
            try:
                if start <= date(y, m, d) <= end:
                    return True
            except ValueError:
                pass
        elif (start.year, start.month) <= (y, m) <= (end.year, end.month):
            return True
    return False


def _sentence_issues(sentence, ctx):
    issues = []
    for m in _ISO.finditer(sentence):
        y, mo, d = (int(g) for g in m.groups())
        if _in_spans(y, mo, d, ctx["rejected"]):
            issues.append(f"the date {m.group(0)} falls in a candidate window the forecast did not issue")
            continue
        if m.group(0) in ctx["user"] or m.group(0) in ctx["blob"] or _in_spans(y, mo, d, ctx["spans"]):
            continue
        issues.append(f"the date {m.group(0)} is outside the analysis window and was not supplied")
    for m in _PROSE_DATE.finditer(sentence):
        month = _MONTHS.index(m.group(1)) + 1
        day = int(m.group(2)) if m.group(2) else None
        year = int(m.group(3)) if m.group(3) else None
        if day is None and year is None:
            continue                                  # bare month name: not a date claim
        if year is None and day is not None and not (1 <= day <= 31):
            continue
        if m.group(0).lower() in ctx["user"].lower():
            continue                                  # the user wrote it themselves
        if year is not None and _in_spans(year, month, day, ctx["rejected"]):
            issues.append(f"the date '{m.group(0)}' falls in a candidate window the forecast did not issue")
            continue
        if year is None:
            # month/day without a year: fine when any window covers that month
            if any(_in_spans(s.year + k, month, None, [(s, e)]) for s, e in ctx["spans"] for k in (0, 1)):
                continue
        elif _in_spans(year, month, day, ctx["spans"]) or f"{year}-{month:02d}" in ctx["blob"]:
            continue
        issues.append(f"the date '{m.group(0)}' is outside the analysis window and was not supplied")
    if _CERTAINTY.search(sentence):
        issues.append("states a definite outcome as certain; the chart only shows indications")
    if _PROBABILITY.search(sentence):
        issues.append("gives a numerical probability, which the chart cannot support")
    if _INTERNAL.search(sentence):
        issues.append("exposes internal scoring or protocol wording")
    if _KP.search(sentence) and not re.search(r"sub_?lord|bindu", ctx["blob"], re.I):
        issues.append("mentions KP sub-lords or bindus that were not supplied")
    return issues


def find_reply_issues(reply, analysis, facts=None, messages=None):
    """Structured problems in a model reply: [{"sentence", "message"}].
    Empty list means the reply may be shown as it is. The caller should
    regenerate once (providers.regenerate_with_issues) with these messages
    and only then fall back to strip_reply_issues."""
    ctx = _reply_context(analysis, facts, messages)
    from .verify import split_sentences
    found = []
    for seg, _ in split_sentences(reply):
        if seg.strip():
            found += [{"sentence": seg.strip(), "message": m} for m in _sentence_issues(seg, ctx)]
    return found


def strip_reply_issues(reply, analysis, facts=None, messages=None):
    """Remove only the offending sentences; paragraphs and lists are preserved."""
    from .verify import strip_sentences
    ctx = _reply_context(analysis, facts, messages)
    return strip_sentences(reply, lambda s: bool(_sentence_issues(s, ctx)))


def constrain_reply(reply, analysis, facts=None, messages=None, return_issues=False):
    """Reject unsupported event promises without damaging the rest of the reply.

    Default: returns the reply with only offending sentences removed (never a
    canned replacement). With return_issues=True returns (stripped_reply, issues)
    so the caller can regenerate once with the issues listed instead."""
    issues = find_reply_issues(reply, analysis, facts, messages)
    stripped = strip_reply_issues(reply, analysis, facts, messages) if issues else reply
    return (stripped, issues) if return_issues else stripped
