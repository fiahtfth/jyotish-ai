"""Opening birth-time calibration.

The strongest check is the client's own dated major events (see the
orchestrator's milestone search). When they have none, this module generates
up to three single-event retrospective questions from the *already computed*
chart plus one negative-control question about a window the chart does not
indicate. Questions are ranked by how much plausible birth-time variants
disagree about the window (pillar support is only a filter), predictions are
locked before feedback and partial matches never count as confirmations.
"""
from datetime import date, datetime, timedelta
import re
import itertools

from . import constants as K
from . import pillars
from .engine import BirthInput

_id_counter = itertools.count(1)
OPENING_EVENT_PREFIX = "recent_calibration_v5_"
CONTROL_EVENT_ID = OPENING_EVENT_PREFIX + "ctl"

# One definite, memorable event per question - never "A or B". The event is
# chosen from the Antardasha lord's house links (see lord_event_domain).
# {poss}/{subj}/{obj} adapt to the person: "you" for the account owner,
# otherwise the family member's name (see subject_words).
_STATEMENTS = {
    "career": "Between {start} and {end}, did {subj} start a new job?",
    "education": "Between {start} and {end}, did {subj} begin a new course of study, such as a degree?",
    "relationship": "Between {start} and {end}, did {subj} get married?",
    "relocation": "Between {start} and {end}, did {subj} move to live in a different city?",
}
# houses that make an Antardasha lord point to each event type
_EVENT_HOUSES = {"relationship": (7,), "career": (10, 6), "relocation": (4, 12), "education": (4, 5, 9)}
_TIE_ORDER = ["relationship", "career", "relocation", "education"]
_DEFAULT_MIN_AGES = {"career": 16, "education": 15, "relationship": 21, "relocation": 10}
_SENSITIVITY_SHORTLIST = 4      # per domain, before the (costly) variant comparison


def min_ages() -> dict:
    """Minimum age at the start of an opening window; shared constants win."""
    return {**_DEFAULT_MIN_AGES, **{d: a for d, a in K.MIN_CALIBRATION_AGE_FOR_DOMAIN.items()
                                    if d in _DEFAULT_MIN_AGES}}


def is_control(event_id: str | None) -> bool:
    return bool(event_id) and event_id == CONTROL_EVENT_ID


def subject_words(name: str | None = None) -> dict:
    """Wording for the person a chart is about. name=None means the account
    owner ("you"); otherwise the family member's name."""
    if not name:
        return {"subj": "you", "obj": "you", "poss": "your", "were": "were",
                "memory": "your memory"}
    poss = name + ("'" if name.endswith("s") else "'s")
    return {"subj": name, "obj": name, "poss": poss, "were": "was",
            "memory": f"what you know of {poss} life"}

_DOMAIN_ORDER = ["career", "education", "relocation", "relationship"]  # opening domains only


def _age_today(birth: BirthInput, today: date | None = None) -> float:
    today = today or date.today()
    return (today - date(birth.year, birth.month, birth.day)).days / 365.25


def _past_ad_windows(facts, birth: BirthInput, today: date | None = None) -> list[dict]:
    """Past windows across the person's life, bounded to dates after birth."""
    today = today or date.today()
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
    ages = min_ages()
    return [d for d in _DOMAIN_ORDER if age >= ages.get(d, 0)]


def _lord_link_score(facts, lord, domain) -> int:
    houses = _EVENT_HOUSES[domain]
    owned = {h for h in range(1, 13) if facts["houses"][h]["lord"] == lord}
    placed = (facts["planets"].get(lord) or {}).get("house")
    return 2 * len(owned & set(houses)) + (1 if placed in houses else 0)


def lord_event_domain(facts, lord) -> str | None:
    """The event type an Antardasha lord most points to: marriage (7th),
    job start (10th/6th), relocation (4th/12th) or education (4th/5th/9th);
    None when the lord has no such link."""
    best, best_score = None, 0
    for domain in _TIE_ORDER:
        score = _lord_link_score(facts, lord, domain)
        if score > best_score:
            best, best_score = domain, score
    return best


# (min support, min net) tiers: strict first, relaxed only to reach three.
_THRESHOLD_TIERS = [(2, 1), (1, 0)]


def _shifted(birth: BirthInput, minutes: int) -> BirthInput:
    from dataclasses import replace
    t = datetime(birth.year, birth.month, birth.day, birth.hour, birth.minute,
                 birth.second) + timedelta(minutes=minutes)
    return replace(birth, year=t.year, month=t.month, day=t.day,
                   hour=t.hour, minute=t.minute, second=t.second)


def _ad_at(facts, day: date):
    for p in facts["vimshottari"]["periods"]:
        if len(p["lords"]) == 2 and _to(p["start"]) <= day <= _to(p["end"]):
            return p
    return None


def variant_sensitivity(facts, birth: BirthInput):
    """Build sensitivity(domain, window, evidence) -> float: how much the
    chart read at the edges of the birth-time uncertainty disagrees with the
    stated-time chart about a window (verdicts, the Antardasha running in it,
    and the D1/D9/domain-varga Lagna). Lagna-insensitive windows score 0."""
    from . import stability
    from .engine import engine
    unc = max(2, min(120, int(stability.uncertainty_for(birth) // 60)))
    variants = []
    for minutes in (-unc, unc):
        try:
            vb = _shifted(birth, minutes)
            variants.append((vb, engine.compute(vb)))
        except Exception:
            continue

    def lagna_signs(f, varga):
        return ((f.get("vargas", {}).get(varga) or {}).get("Lagna") or {}).get("sign")

    def sensitivity(domain, window, evidence):
        mid = window["start"] + (window["end"] - window["start"]) / 2
        base_ad = _ad_at(facts, mid)
        base_net = evidence["support_count"] - evidence["conflict_count"]
        total = 0.0
        for vb, vf in variants:
            try:
                r = pillars.evaluate(vf, vb, domain, window["start"], window["end"])
            except Exception:
                continue
            total += abs(r["support_count"] - r["conflict_count"] - base_net)
            total += sum(1 for k, v in evidence["pillars"].items() if r["pillars"].get(k) != v)
            ad = _ad_at(vf, mid)
            if base_ad and ad:
                if ad["lords"] != base_ad["lords"]:
                    total += 2
                elif abs((_to(ad["start"]) - _to(base_ad["start"])).days) > 30:
                    total += 1
            for varga in ("D1", "D9", K.DOMAINS[domain]["varga"]):
                if lagna_signs(vf, varga) != lagna_signs(facts, varga):
                    total += 1
        return total

    return sensitivity


def generate_statements(facts, birth: BirthInput, fingerprint: str,
                        subject: str | None = None, today: date | None = None,
                        sensitivity_fn=None) -> list[dict]:
    """Select up to three single-event questions plus one negative control.

    Pillar support/conflict is only a filter; windows are ranked by how much
    birth-time variants disagree about them (`sensitivity_fn(domain, window,
    evidence)`, default `variant_sensitivity`). Each question asks the one
    event type the window's Antardasha lord most points to. The control is a
    window the chart does not indicate (no pillar support, conflicting
    pillars) and is flagged `control`. Everything needed to evaluate a claim
    is stored before any feedback arrives. May return fewer than three real
    questions when evidence is thin."""
    today = today or date.today()
    words = subject_words(subject)
    born = date(birth.year, birth.month, birth.day)
    domains = pick_domains(_age_today(birth, today))
    windows = _past_ad_windows(facts, birth, today)
    ages = min_ages()
    candidates, pool = [], []
    for domain in domains:
        for window in windows:
            if (window["start"] - born).days / 365.25 < ages[domain]:
                continue
            evidence = pillars.evaluate(facts, birth, domain, window["start"], window["end"])
            support, conflict = evidence["support_count"], evidence["conflict_count"]
            pool.append((domain, window, evidence))
            if conflict > support:
                continue
            activates = 1 if (evidence.get("pillars") or {}).get("parashari") == "support" else 0
            span = (window["end"] - window["start"]).days
            lord_match = lord_event_domain(facts, window["lords"][1]) == domain
            base_key = (support - conflict, activates, -span, window["end"])
            candidates.append({"base": base_key, "support": support, "domain": domain,
                               "window": window, "evidence": evidence, "lord_match": lord_match})
    # rank by Lagna/AD sensitivity; support only filters and breaks ties
    if sensitivity_fn is None:
        shortlist = []
        for domain in domains:
            own = sorted((c for c in candidates if c["domain"] == domain),
                         key=lambda c: c["base"], reverse=True)
            shortlist += own[:_SENSITIVITY_SHORTLIST]
        candidates = shortlist
        try:
            sensitivity_fn = variant_sensitivity(facts, birth) if candidates else None
        except Exception:
            sensitivity_fn = None
    for c in candidates:
        c["sensitivity"] = float(sensitivity_fn(c["domain"], c["window"], c["evidence"])) if sensitivity_fn else 0.0
        c["key"] = (c["sensitivity"], *c["base"])
    candidates.sort(key=lambda c: c["key"], reverse=True)

    chosen, used_domains, used_spans = [], set(), []
    passes = [(tier, True) for tier in _THRESHOLD_TIERS] + [(tier, False) for tier in _THRESHOLD_TIERS]
    for (min_support, min_net), need_lord in passes:
        for c in candidates:
            if len(chosen) == 3:
                break
            w = c["window"]
            if c["support"] < min_support or c["base"][0] < min_net or (need_lord and not c["lord_match"]):
                continue
            if c["domain"] in used_domains or any(
                    w["start"] <= end and start <= w["end"] for start, end in used_spans):
                continue
            used_domains.add(c["domain"])
            used_spans.append((w["start"], w["end"]))
            chosen.append(c)

    def record(c, event_id, control=False):
        w, ev = c["window"], c["evidence"]
        sm, em = _fmt_range(w["start"], w["end"])
        text = _STATEMENTS[c["domain"]].format(start=sm, end=em, **words)
        return {
            "event_id": event_id, "domain": c["domain"],
            "predicted_event": text, "chat_text": text, "control": control,
            "predicted_window": {"start": f"{w['start'].year:04d}-{w['start'].month:02d}",
                                 "end": f"{w['end'].year:04d}-{w['end'].month:02d}"},
            "user_feedback": None, "actual_date": None, "matched": False,
            "rules_evaluated": ev["traditional_rule_ids"],
            "pillars": ev["pillars"], "convergence": ev["convergence"],
            "calculation_fingerprint": fingerprint,
            "sensitivity": c.get("sensitivity", 0.0),
        }

    statements = [record(c, f"{OPENING_EVENT_PREFIX}{i+1:03d}") for i, c in enumerate(chosen)]
    if len(statements) >= 2:
        control = _pick_control(pool, used_spans, facts)
        if control:
            statements.insert(1, record(control, CONTROL_EVENT_ID, control=True))
    return statements


def _pick_control(pool, used_spans, facts):
    """A window in which the chart does not indicate the asked event: neither
    the Mahadasha nor the Antardasha lord links to that event's houses and
    pillar support is low. Away from the real questions: a 'yes' here
    suggests acquiescence, not recall."""
    best = None
    for domain, w, ev in pool:
        if ev["support_count"] > 1 or any(w["start"] <= end and start <= w["end"] for start, end in used_spans):
            continue
        linked = any(_lord_link_score(facts, lord, domain) for lord in w["lords"])
        if linked and ev["support_count"]:
            continue
        key = (not linked, -ev["support_count"], ev["conflict_count"], w["end"])
        if best is None or key > best[0]:
            best = (key, {"domain": domain, "window": w, "evidence": ev})
    return best[1] if best else None


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
    """Record the strength of the past-event match for the reading.

    The negative control (if asked) is not a specific confirmation: a 'yes'
    to it means the user says yes to anything, so it cancels one real
    confirmation and blocks the 'calibrated' state."""
    real = [s for s in statements if not is_control(s.get("event_id"))]
    control = [s for s in statements if is_control(s.get("event_id"))]
    confirmed = sum(1 for s in real if s.get("user_feedback") == "confirmed")
    partial = sum(1 for s in real if s.get("user_feedback") == "partial")
    unknown = sum(1 for s in real if s.get("user_feedback") == "unknown")
    control_confirmed = any(s.get("user_feedback") == "confirmed" for s in control)
    total = len(real)
    effective = confirmed - (1 if control_confirmed else 0)
    # Calibrated needs at least two specific confirmations, all asked
    # questions confirmed and the control not confirmed; two of three (or
    # a confirmed control) is partial; a lone confirmation is only partial.
    if total >= 2 and confirmed == total and not control_confirmed:
        state = "calibrated"
        label = "These indications fit the events you remember."
    elif effective == 2 or (total == 1 and effective == 1):
        state = "partial"
        label = "Some indications fit the events you remember. I'll treat dates in the reading as approximate."
    else:
        state = "uncalibrated"
        label = "The past-event checks didn't establish a consistent match."
    return {"state": state, "label": label, "confirmed": confirmed,
            "partial": partial, "unknown": unknown, "control_confirmed": control_confirmed,
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
        if is_control(getattr(e, "event_id", None)):
            continue
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


# ------------------------------------------------------- core-engine chart check

# Milestone domains -> core topic ids. Unmapped domains are skipped: the core
# engine has no opinion on them, so they can't support or hurt the fit.
_FIT_DOMAIN_TOPIC = {
    "career": "job_change",
    "education": "education",
    "relationship": "marriage",
    "relocation": "foreign",
    "property": "property",
    "children": "children",
    "finance": "wealth",
    "health": "wellbeing",
}


def chart_check(facts, birth: BirthInput, events: list,
                today: date | None = None) -> dict:
    """One chart check: do the user's dated events sit inside what the core
    method would have indicated? `events` are {domain, year, month?} dicts.

    An event is 'explained' when the topic's natal promise is at least
    moderate AND a linked antardasha was running at the event AND a
    Saturn+Jupiter double transit touched the topic within ±6 months.
    A linked period alone is 'partially explained'; anything else is a miss.

    Returns {"fit": "good"|"partial"|"poor"|None, "checked": n, "events": [...]}.
    fit is None when fewer than two usable events exist."""
    from . import core

    usable = []
    for e in events:
        dom, year = e.get("domain"), e.get("year")
        topic_id = _FIT_DOMAIN_TOPIC.get(dom or "")
        if topic_id and year:
            usable.append((e, topic_id))
    if len(usable) < 2:
        return {"fit": None, "checked": 0, "events": []}

    results = []
    for e, topic_id in usable:
        year, month = int(e["year"]), int(e.get("month") or 6)
        center = date(year, min(max(month, 1), 12), 15)
        lo = center - timedelta(days=183)
        hi = center + timedelta(days=183)
        pr = core.promise(facts, topic_id)
        promise_ok = pr["grade"] in ("strong", "moderate")
        try:
            pers = core.periods(facts, birth, topic_id, lo, hi)
        except Exception:
            pers = []
        try:
            trig = core.triggers(facts, birth, topic_id, lo, hi)
        except Exception:
            trig = []
        linked = any(p.get("link") in ("strong", "medium") for p in pers)
        triggered = any(t.get("from_lagna") or t.get("from_moon") for t in trig)
        if promise_ok and linked and triggered:
            outcome = "explained"
        elif linked:
            outcome = "partially_explained"
        else:
            outcome = "not_explained"
        results.append({"domain": e.get("domain"), "topic": topic_id,
                        "year": year, "month": e.get("month"),
                        "promise": pr["grade"], "period_link": linked,
                        "double_transit": triggered, "outcome": outcome})

    full = sum(r["outcome"] == "explained" for r in results)
    partial = sum(r["outcome"] == "partially_explained" for r in results)
    n = len(results)
    if full * 2 >= n:
        fit = "good"
    elif (full + partial) * 2 >= n:
        fit = "partial"
    else:
        fit = "poor"
    return {"fit": fit, "checked": n, "explained": full, "partial": partial,
            "events": results}


def update_personal_fit(db, profile, facts, birth: BirthInput) -> str | None:
    """Recompute the profile's chart-check fit from its recorded milestones
    and store it on the profile. Returns the fit, or None when there aren't
    enough usable events. Safe to call on every milestone change."""
    events = [{"domain": m.domain, "year": m.year, "month": m.month}
              for m in (profile.milestones or []) if m.domain and m.year]
    result = chart_check(facts, birth, events)
    if result["fit"] is not None:
        profile.personal_fit = result["fit"]
        db.flush()
    return result["fit"]
