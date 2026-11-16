"""Three-event past calibration.

Generates three testable retrospective statements from the *already
computed* chart — each in a different life domain, each bounded to a past
window derived from real dasha periods. Predictions are locked before
feedback; matching rules are objective and partial matches never count
as full confirmations.
"""
from datetime import date, datetime
import itertools

from . import constants as K
from . import pillars
from .engine import BirthInput

_id_counter = itertools.count(1)

# Presentation templates per domain (no Barnum wording; window is real)
_STATEMENTS = {
    "career": "Between {start} and {end}, I see a possible development connected with your "
              "career or professional direction — beginning a new role, a noticeable shift in "
              "responsibility, or changing your work path. Did something like that happen?",
    "education": "Between {start} and {end}, the chart suggests a significant period for "
                 "education or learning — starting or completing a course of study, an important "
                 "exam, or a turn in what you were learning. Does that ring true?",
    "relationship": "Between {start} and {end}, there are indications around an important "
                    "relationship or family milestone — a significant commitment, marriage, or a "
                    "major change in a close relationship. Did anything like that take place?",
    "relocation": "Between {start} and {end}, your chart points to a possible change of residence "
                  "or a significant move — a new city, a new home, or time spent away from where "
                  "you lived before. Did that happen around then?",
    "finance": "Between {start} and {end}, the chart shows a window that could relate to money or "
               "responsibility — a first income, a significant financial step, or taking on "
               "dependents. Does that match your memory?",
    "direction": "Between {start} and {end}, there is a suggestion of a meaningful change in "
                 "personal direction — a turning point in what you wanted or how you lived. "
                 "Did that occur for you?",
}

_DOMAIN_ORDER = ["career", "education", "relocation", "relationship", "finance", "direction"]


def _age_today(birth: BirthInput) -> float:
    today = date.today()
    return (today - date(birth.year, birth.month, birth.day)).days / 365.25


def _past_ad_windows(facts, birth: BirthInput) -> list[dict]:
    """Candidate windows: completed Antardasha periods before today."""
    today = date.today()
    out = []
    for p in facts["vimshottari"]["periods"]:
        if len(p["lords"]) < 2:
            continue
        s, e = _to(p["start"]), _to(p["end"])
        if e >= today:
            if s < today:
                e = today
            else:
                continue
        if (e - s).days < 60:
            continue
        if (today - e).days < 45:   # keep windows clearly in the past
            continue
        out.append({"lords": p["lords"], "start": s, "end": e})
    return out


def _to(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_long(d: date) -> str:
    return d.strftime("%B %Y")


def _fmt_range(s: date, e: date) -> str:
    return _month_long(s), _month_long(e)


def pick_domains(age: float) -> list[str]:
    ok = [d for d in _DOMAIN_ORDER
          if age >= K.MIN_CALIBRATION_AGE_FOR_DOMAIN.get(d, 0)]
    for d in ("direction", "education"):
        if len(ok) >= 3:
            break
        if d not in ok:
            ok.append(d)
    return ok[:3]


def generate_statements(facts, birth: BirthInput, fingerprint: str) -> list[dict]:
    """Choose 3 domains, find each one's best-supported past window, and lock
    three falsifiable statements. Everything needed to evaluate a claim is
    stored *before* any feedback arrives."""
    age = _age_today(birth)
    domains = pick_domains(age)
    windows = _past_ad_windows(facts, birth)
    statements = []
    used_spans = []

    # minimum age (at window end) for a domain window to be testable
    WINDOW_MIN_AGE = {"career": 16, "education": 8, "relationship": 18,
                      "relocation": 10, "finance": 18, "direction": 12}
    MAX_WINDOW_DAYS = 550

    for i, domain in enumerate(domains):
        best = None
        min_age = WINDOW_MIN_AGE.get(domain, 10)
        for w in windows:
            # avoid overlapping windows across the three questions
            if any(not (w["end"] < u0 or w["start"] > u1) for u0, u1 in used_spans):
                continue
            age_at_end = (w["end"] - date(birth.year, birth.month, birth.day)).days / 365.25
            if age_at_end < min_age:
                continue
            ev = pillars.evaluate(facts, birth, domain, w["start"], w["end"])
            score = ev["support_count"] - ev["conflict_count"]
            if best is None or score > best[1]:
                best = (w, score, ev)
        if best is None:
            continue
        w, score, ev = best
        used_spans.append((w["start"], w["end"]))
        # bound the stated window to ~18 months max so it stays falsifiable
        if (w["end"] - w["start"]).days > MAX_WINDOW_DAYS:
            w = dict(w)
            w["end"] = w["start"].fromordinal(w["start"].toordinal() + MAX_WINDOW_DAYS)
        sm, em = _fmt_range(w["start"], w["end"])
        weak = score <= 0
        text = _STATEMENTS[domain].format(start=sm, end=em)
        if weak:
            text = ("The timing indicators here are weaker, so treat this one as tentative. " + text)
        statements.append({
            "event_id": f"calibration_{i+1:03d}",
            "domain": domain,
            "predicted_event": _STATEMENTS[domain].format(start=sm, end=em),
            "chat_text": text,
            "predicted_window": {"start": f"{w['start'].year:04d}-{w['start'].month:02d}",
                                 "end": f"{w['end'].year:04d}-{w['end'].month:02d}"},
            "user_feedback": None, "actual_date": None, "matched": False,
            "rules_evaluated": ev["traditional_rule_ids"],
            "pillars": ev["pillars"], "convergence": ev["convergence"],
            "calculation_fingerprint": fingerprint,
        })
    return statements


def evaluate_feedback(statement: dict, feedback: str, actual_date: str | None = None) -> dict:
    """Objective matching rules. partial/unknown never count as matches."""
    fb = feedback.lower().strip()
    mapping = {"yes": "confirmed", "confirmed": "confirmed",
               "partial": "partial", "similar": "partial", "close": "partial",
               "no": "rejected", "rejected": "rejected",
               "unknown": "unknown", "not sure": "unknown", "n/a": "unknown"}
    val = mapping.get(fb, "unknown")
    statement["user_feedback"] = val
    statement["actual_date"] = actual_date
    statement["matched"] = (val == "confirmed")
    return statement


def calibration_outcome(statements: list[dict]) -> dict:
    """Gate decision, per spec: 3 confirmed -> matched; 2 -> partial;
    0-1 -> locked, rectification required. Unknowns never count as matches."""
    confirmed = sum(1 for s in statements if s.get("user_feedback") == "confirmed")
    partial = sum(1 for s in statements if s.get("user_feedback") == "partial")
    unknown = sum(1 for s in statements if s.get("user_feedback") == "unknown")
    if confirmed == 3:
        state = "calibrated"
        label = "Three retrospective checks matched."
        predictions_allowed = True
    elif confirmed == 2:
        state = "partial"
        label = "Partial calibration — continuing with an uncertainty note."
        predictions_allowed = True
    else:
        state = "uncalibrated"
        label = "The past checks did not line up with the chart. Before going further "
        "we should recheck the birth details and calculation settings."
        predictions_allowed = False
    return {"state": state, "label": label, "confirmed": confirmed,
            "partial": partial, "unknown": unknown,
            "predictions_allowed": predictions_allowed}
