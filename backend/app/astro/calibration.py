"""Three-event past calibration.

Generates three testable retrospective statements from the *already
computed* chart — each in a different life domain, each bounded to a past
window derived from real dasha periods. Predictions are locked before
feedback; matching rules are objective and partial matches never count
as full confirmations.
"""
from datetime import date, datetime, timedelta
import re
import itertools

from . import constants as K
from . import pillars
from .engine import BirthInput

_id_counter = itertools.count(1)
OPENING_EVENT_PREFIX = "recent_calibration_v3_"

# Presentation templates per domain (no Barnum wording; window is real).
# {poss}/{subj}/{were}/{memory} adapt to the person: "you" for the account
# owner, otherwise the family member's name (see subject_words).
_STATEMENTS = {
    "career": "Between {start} and {end}, {poss} work responsibilities or professional direction "
              "appear to have changed. Does that fit {memory}?",
    "education": "Between {start} and {end}, education or learning appears to have been an important "
                 "focus for {obj}. Does that fit {memory}?",
    "relationship": "Between {start} and {end}, a close relationship or family commitment "
                    "appears to have become an important focus for {obj}. Does that fit {memory}?",
    "relocation": "Between {start} and {end}, {poss} living situation appears to have changed. "
                  "Does that fit {memory}?",
    "finance": "Between {start} and {end}, {poss} financial responsibilities appear to have changed. "
               "Does that fit {memory}?",
    "direction": "Between {start} and {end}, {poss} personal goals appear to have changed. "
                 "Does that fit {memory}?",
}


def subject_words(name: str | None = None) -> dict:
    """Wording for the person a chart is about. name=None means the account
    owner ("you"); otherwise the family member's name."""
    if not name:
        return {"subj": "you", "obj": "you", "poss": "your", "were": "were",
                "memory": "your memory"}
    poss = name + ("'" if name.endswith("s") else "'s")
    return {"subj": name, "obj": name, "poss": poss, "were": "was",
            "memory": f"what you know of {poss} life"}

_DOMAIN_ORDER = ["career", "education", "relocation", "relationship", "finance", "direction"]


def _age_today(birth: BirthInput) -> float:
    today = date.today()
    return (today - date(birth.year, birth.month, birth.day)).days / 365.25


def _past_ad_windows(facts, birth: BirthInput) -> list[dict]:
    """Past windows across the person's life, bounded to dates after birth."""
    today = date.today()
    earliest = date(birth.year, birth.month, birth.day)
    latest = today - timedelta(days=45)
    out = []
    for p in facts["vimshottari"]["periods"]:
        if len(p["lords"]) != 2:
            continue
        start, end = max(_to(p["start"]), earliest), min(_to(p["end"]), latest)
        # Each candidate is scored over the same months shown in the question.
        if start.day != 1:
            start = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = end.replace(day=1) - timedelta(days=1)
        while (end - start).days >= 60:
            window_start = max(start, end.replace(year=end.year - 1, day=1))
            out.append({"lords": p["lords"], "start": window_start, "end": end})
            end = window_start - timedelta(days=1)
    return sorted(out, key=lambda window: window["end"], reverse=True)


def _to(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_long(d: date) -> str:
    return d.strftime("%B %Y")


def _fmt_range(s: date, e: date) -> str:
    return _month_long(s), _month_long(e)


def pick_domains(age: float) -> list[str]:
    ok = [d for d in _DOMAIN_ORDER
          if age >= K.MIN_CALIBRATION_AGE_FOR_DOMAIN.get(d, 0)]
    return ok


def generate_statements(facts, birth: BirthInput, fingerprint: str,
                        subject: str | None = None) -> list[dict]:
    """Rank past domain windows, select up to three broad indications, and lock
    three falsifiable statements. Everything needed to evaluate a claim is
    stored *before* any feedback arrives."""
    words = subject_words(subject)
    age = _age_today(birth)
    domains = pick_domains(age)
    windows = _past_ad_windows(facts, birth)
    statements = []
    candidates = []
    minimum_ages = {"career": 16, "education": 8, "relationship": 18,
                    "relocation": 10, "finance": 18, "direction": 12}
    for domain in domains:
        for window in windows:
            age_at_start = (window["start"] - date(birth.year, birth.month, birth.day)).days / 365.25
            if age_at_start < minimum_ages[domain]:
                continue
            evidence = pillars.evaluate(facts, birth, domain, window["start"], window["end"])
            score = evidence["support_count"] - evidence["conflict_count"]
            candidates.append((score, window["end"], domain, window, evidence))
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
    used_domains, used_spans = set(), []
    for score, _, domain, w, ev in candidates:
        if domain in used_domains or any(
                w["start"] <= end and start <= w["end"] for start, end in used_spans):
            continue
        used_domains.add(domain)
        used_spans.append((w["start"], w["end"]))
        i = len(statements)
        sm, em = _fmt_range(w["start"], w["end"])
        weak = score <= 0
        text = _STATEMENTS[domain].format(start=sm, end=em, **words)
        if weak:
            text = ("The timing indicators here are weaker, so treat this one as tentative. " + text)
        statements.append({
            "event_id": f"{OPENING_EVENT_PREFIX}{i+1:03d}",
            "domain": domain,
            "predicted_event": _STATEMENTS[domain].format(start=sm, end=em, **words),
            "chat_text": text,
            "predicted_window": {"start": f"{w['start'].year:04d}-{w['start'].month:02d}",
                                 "end": f"{w['end'].year:04d}-{w['end'].month:02d}"},
            "user_feedback": None, "actual_date": None, "matched": False,
            "rules_evaluated": ev["traditional_rule_ids"],
            "pillars": ev["pillars"], "convergence": ev["convergence"],
            "calculation_fingerprint": fingerprint,
        })
        if len(statements) == 3:
            break
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
    """Record the strength of the past-event match for the reading."""
    confirmed = sum(1 for s in statements if s.get("user_feedback") == "confirmed")
    partial = sum(1 for s in statements if s.get("user_feedback") == "partial")
    unknown = sum(1 for s in statements if s.get("user_feedback") == "unknown")
    if len(statements) >= 2 and confirmed == len(statements):
        state = "calibrated"
        label = "These indications fit the events you remember."
    elif confirmed == 2:
        state = "partial"
        label = "Some indications fit the events you remember. I'll treat dates in the reading as approximate."
    else:
        state = "uncalibrated"
        label = "The past-event checks didn't establish a consistent match."
    return {"state": state, "label": label, "confirmed": confirmed,
            "partial": partial, "unknown": unknown,
            "predictions_allowed": True}


def _win_date(s: str, end=False) -> date:
    y, m = int(s[:4]), int(s[5:7])
    return date(y, m, 28 if end else 1)


def _actual_year(actual: str | None) -> int | None:
    if not actual:
        return None
    m = re.search(r"(19|20)\d\d", actual)
    return int(m.group(0)) if m else None


def _score_candidate(birth: BirthInput, facts: dict, events: list) -> float:
    """Score a candidate birth against recorded feedback: events the user
    confirmed should gain pillar support; rejected ones should not."""
    total = 0.0
    for e in events:
        fb = e.user_feedback
        if fb not in ("confirmed", "rejected", "partial"):
            continue
        r = pillars.evaluate(facts, birth, e.domain,
                             _win_date(e.predicted_window_start),
                             _win_date(e.predicted_window_end, end=True))
        s = r["support_count"] - r["conflict_count"]
        if fb == "confirmed":
            total += s
        elif fb == "rejected":
            total -= s
        else:
            yr = _actual_year(e.actual_date)
            if yr and int(e.predicted_window_start[:4]) - 1 <= yr <= int(e.predicted_window_end[:4]) + 1:
                total += 0.5 * s
    return total


# candidate window per stated precision: how far the stated time may be off
_RECTIFY_SPAN = {"exact": 30, "approximate": 60, "unknown": 120}
_RECTIFY_MAX_CANDIDATES = 5


def try_rectify(birth: BirthInput, stated_facts: dict, events: list,
                engine) -> dict | None:
    """Search birth times around the stated time for a better fit to the
    recorded calibration feedback. Returns {'birth', 'facts', 'delta_minutes',
    'stated_score', 'best_score'} or None when nothing clearly improves."""
    span = _RECTIFY_SPAN.get(birth.birth_time_precision, 30)
    step = max(10, (2 * span) // (_RECTIFY_MAX_CANDIDATES - 1))
    base = datetime(birth.year, birth.month, birth.day,
                    birth.hour, birth.minute, birth.second)
    stated_score = _score_candidate(birth, stated_facts, events)
    best = {"score": stated_score, "delta": 0, "birth": birth, "facts": stated_facts}
    for off in range(-span, span + 1, step):
        if off == 0:
            continue
        t = base + timedelta(minutes=off)
        cand = BirthInput(
            name=birth.name, year=t.year, month=t.month, day=t.day,
            hour=t.hour, minute=t.minute, second=t.second,
            lat=birth.lat, lon=birth.lon, tz_offset=birth.tz_offset,
            place_label=birth.place_label,
            birth_time_precision=birth.birth_time_precision,
            settings=birth.settings)
        try:
            cf = engine.compute(cand)
            s = _score_candidate(cand, cf, events)
        except Exception:
            continue
        if s > best["score"]:
            best = {"score": s, "delta": off, "birth": cand, "facts": cf}
    # adopt only on a clearly better fit — noise shouldn't move the clock
    if best["delta"] == 0 or best["score"] < stated_score + 3:
        return None
    return {"birth": best["birth"], "facts": best["facts"],
            "delta_minutes": best["delta"],
            "stated_score": stated_score, "best_score": best["score"]}


def _milestone_window(m) -> tuple[date, date]:
    """A month ±2 months, or the whole year when no month was given."""
    if m.month:
        start = date(m.year, m.month, 1)
        s_ord = start.toordinal() - 61
        e_ord = start.toordinal() + 30 + 61
        return date.fromordinal(s_ord), date.fromordinal(e_ord)
    return date(m.year, 1, 1), date(m.year, 12, 31)


def _score_milestones(birth: BirthInput, facts: dict, milestones: list) -> float:
    """Pillar support minus conflict over each reported event's window: a
    birth time that 'sees' the events the user actually lived scores higher."""
    total = 0.0
    for m in milestones:
        start, end = _milestone_window(m)
        r = pillars.evaluate(facts, birth, m.domain, start, end)
        total += r["support_count"] - r["conflict_count"]
    return total


def search_with_milestones(birth: BirthInput, stated_facts: dict, milestones: list,
                           engine) -> dict | None:
    """Like try_rectify, but scored against dated life events the user reported
    (objects with .domain/.year/.month). Same candidate span and the same
    'clearly better' (+3) margin. Returns None when nothing clearly improves."""
    usable = [m for m in milestones if m.domain and m.year]
    if len(usable) < 2:
        return None
    span = _RECTIFY_SPAN.get(birth.birth_time_precision, 30)
    step = max(10, (2 * span) // (_RECTIFY_MAX_CANDIDATES - 1))
    base = datetime(birth.year, birth.month, birth.day,
                    birth.hour, birth.minute, birth.second)
    stated_score = _score_milestones(birth, stated_facts, usable)
    best = {"score": stated_score, "delta": 0, "birth": birth}
    for off in range(-span, span + 1, step):
        if off == 0:
            continue
        t = base + timedelta(minutes=off)
        cand = BirthInput(
            name=birth.name, year=t.year, month=t.month, day=t.day,
            hour=t.hour, minute=t.minute, second=t.second,
            lat=birth.lat, lon=birth.lon, tz_offset=birth.tz_offset,
            place_label=birth.place_label,
            birth_time_precision=birth.birth_time_precision,
            settings=birth.settings)
        try:
            s = _score_milestones(cand, engine.compute(cand), usable)
        except Exception:
            continue
        if s > best["score"]:
            best = {"score": s, "delta": off, "birth": cand}
    if best["delta"] == 0 or best["score"] < stated_score + 3:
        return None
    return {"birth": best["birth"], "delta_minutes": best["delta"],
            "stated_score": stated_score, "best_score": best["score"]}
