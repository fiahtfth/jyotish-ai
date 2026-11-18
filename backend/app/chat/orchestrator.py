"""Conversation orchestrator.

Past-event checks and birth-time refinement are optional parts of a reading.
"""
from dataclasses import asdict
import json
import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..astro import calibration, panchang, precision, report, sensitivity, prediction
from ..astro.constants import DOMAINS
from .. import geo
from ..policy import TERMS_VERSION
from ..astro.engine import BirthInput, birth_fingerprint, engine
from ..db import (
    BirthProfile, CalibrationEvent, Conversation, Message, PredictionRecord, UserMilestone,
    _utcnow,
)
from ..llm import providers
from . import language

RECTIFY_STATES = ("rectify", "rectify_collect", "rectify_domain", "rectify_confirm")


# ------------------------------------------------------------------ helpers

def birth_input(profile: BirthProfile) -> BirthInput:
    return BirthInput(
        name=profile.display_name or "", year=profile.year, month=profile.month,
        day=profile.day, hour=profile.hour, minute=profile.minute,
        second=profile.second or 0, lat=profile.latitude, lon=profile.longitude,
        tz_offset=profile.utc_offset_hours, place_label=profile.place_name,
        birth_time_precision=profile.birth_time_precision,
    )


def _subject(profile: BirthProfile) -> str | None:
    """None when the chart is the account owner's own ("you"), otherwise the
    family member's name — used to word calibration questions and messages."""
    if (profile.relation or "self") == "self":
        return None
    return (profile.display_name or "").strip() or "this person"


def _words(profile: BirthProfile) -> dict:
    return calibration.subject_words(_subject(profile))


def _is_other(profile: BirthProfile) -> bool:
    return _subject(profile) is not None


def _context_prefix(profile: BirthProfile) -> str:
    """Extra LLM context when the chart belongs to someone other than the user."""
    if not _is_other(profile):
        return ""
    return (f"This chart belongs to {_subject(profile)} (the user's {profile.relation}), "
            f"not to the user. Address the user as 'you' and refer to {_subject(profile)} "
            "in the third person. ")


def _external_ok(profile: BirthProfile) -> bool:
    """External AI is included after accepting the current service terms."""
    return bool(profile.user is not None and profile.user.terms_version == TERMS_VERSION)


def _calibrated(profile: BirthProfile) -> bool:
    """Lagna-sensitive layers (Shadbala, varsha chart, Lagna Sudarshana,
    Lagna-degree eclipse hits) apply only when the chart passed the
    three-check calibration — an unverified time moves the Lagna ~1 deg
    every 4 minutes."""
    return profile.calibration_state == "calibrated"


def _precision_analysis(facts, birth, domain, start, end, profile, question="", event=None):
    """Run the four pillars plus the precision filters; returns
    (analysis_for_llm, precision_result). The merged analysis keeps every
    key the existing consumers read (pillars/convergence/evidence) and
    adds a compact 'precision' block for the model."""
    # Elapsed portions of a year cannot be credited as prospective forecasts.
    today = _today_at(birth)
    if start <= today <= end:
        start = min(end, today + timedelta(days=1))
    prec = precision.evaluate(facts, birth, domain, start, end,
                              calibrated=_calibrated(profile))
    analysis = dict(prec["verdict"])
    analysis["precision"] = {
        "calibrated": prec["calibrated"],
        "confirmation": prec["confirmation"]["label"],
        "yogini": prec["confirmation"]["yogini"]["verdict"],
        "sudarshana": prec["confirmation"]["sudarshana"]["verdict"],
        "timing_windows": prec["timing"]["windows"],
        "excluded_windows": prec["timing"]["excluded"],
        "magnitude": prec["magnitude"]["label"],
        "ithasala": prec["fast_triggers"]["ithasala"],
        "eclipse_watch_months": prec["fast_triggers"]["watch_months"],
        "layer_verdicts": prec["layer_verdicts"],
    }
    analysis["sensitivity"] = sensitivity.evaluate(facts, birth, domain, start, end, _calibrated(profile), base=prec)
    if not analysis["sensitivity"]["timing_stable"]:
        analysis["precision"]["timing_windows"] = []
    analysis["decision"] = prediction.decide(question, analysis, event)
    return analysis, prec


def _save_prediction(db, profile, question, analysis, reply):
    decision = analysis["decision"]
    event = decision.get("event") or {}
    db.add(PredictionRecord(
        profile_id=profile.id, domain=analysis["domain"], question=question,
        window_start=date.fromisoformat(analysis["analysis_window"]["start"]),
        window_end=date.fromisoformat(analysis["analysis_window"]["end"]),
        convergence=analysis["convergence"], layer_verdicts=json.dumps(analysis["precision"]["layer_verdicts"]),
        protocol=prediction.VERSION, forecast=decision["disposition"], event_type=event.get("event_type"),
        success_criteria=decision["success_criteria"],
        snapshot_json=json.dumps({"analysis": analysis, "reply": reply, "fingerprint": profile.calc_fingerprint,
                                  "birth_input": asdict(birth_input(profile))})))



def chart_facts(profile: BirthProfile) -> dict:
    if profile.chart_json:
        facts = json.loads(profile.chart_json)
        facts["houses"] = {int(k): v for k, v in facts["houses"].items()}
        return facts
    facts = engine.compute(birth_input(profile))
    profile.chart_json = json.dumps(facts)
    return facts


def _add_msg(db: Session, conv: Conversation, role: str, content: str,
             kind="text", meta=None) -> Message:
    m = Message(role=role, content=content, kind=kind,
                meta_json=json.dumps(meta or {}))
    m.conversation = conv          # appends to conv.messages collection
    db.add(m)
    return m


DOMAIN_KEYWORDS = {
    "career": ["job", "career", "promotion", "work", "business", "profession", "salary", "boss", "interview", "transfer", "employer", "leadership", "manager", "colleague", "naukri", "नौकरी", "काम", "company", "companies", "lead a team", "manage a team", "managing people", "line of work", "role at work"],
    "education": ["study", "studies", "exam", "education", "degree", "college", "course", "learn", "admission", "padhai", "पढ़ाई"],
    "relationship": ["marriage", "marry", "married", "wedding", "relationship", "partner", "wife", "husband", "love", "spouse", "engagement", "tie the knot", "dating", "shaadi", "शादी"],
    "relocation": ["move", "relocate", "relocating", "abroad", "foreign", "city", "house shift", "settle"],
    "finance": ["money", "wealth", "finance", "financial", "income", "loan", "debt", "invest"],
    "direction": ["direction", "purpose", "path in life", "meaning"],
    "health": ["health", "illness", "sick", "disease", "hospital", "surgery", "recovery", "wellbeing", "wellness", "medical"],
}

# panchang: the day's limbs — factual almanac, not a prediction
PANCHANG_PAT = re.compile(
    r"\b(panchang|panchanga|"
    r"(today|tomorrow|day after)'?s?\s+(tithi|nakshatra|yoga|karana|vaara)|"
    r"(tithi|nakshatra|yoga|karana)\s+(today|tomorrow|of today|of tomorrow|on)\b|"
    r"what('?s| is)( the)? (tithi|nakshatra|yoga|karana))\b", re.I)
# electional timing: "best/suitable/good time or day TO do X" — the
# trailing connector keeps "have a good day"/"the right time" out
TIMING_PAT = re.compile(
    r"(best|suitable|good|right|auspicious|favou?rable|ideal)\s+"
    r"(time|day|date|moment|days)\s+(to|for|of|in)\b|"
    r"when\s+(should|shall)\s+i\b|muhurt|shubh|auspicious\s+(day|time)|"
    r"which\s+(day|date)\s+(is\s+)?(best|suitable|good|right|auspicious|favou?rable)\b", re.I)
REPORT_PAT = re.compile(
    r"\b((my|full|detailed|complete|chart|birth|astro\w*|jyotish)\s+report|"
    r"report\s+(on|of|about)\s+(my|the|this)\s+(chart|kundli|horoscope)|"
    r"full reading|complete reading|whole chart|chart summary|"
    r"summary of (my |the )?(chart|kundli))\b", re.I)
# "how is today for me" — the daily view is the personalised panchang
DAILY_PAT = re.compile(
    r"\bhow('?s| is| will be| was)\b[^?]{0,25}\b(today|tomorrow|the day|my day)\b|"
    r"\b(daily|today'?s|tomorrow'?s)\s+(reading|forecast|rashifal|horoscope)\b|"
    r"\baaj ka\b", re.I)

ANSWER_MAP = {"yes": "yes", "confirmed": "yes", "that happened": "yes",
              "partial": "partial", "similar": "partial", "close": "partial",
              "something similar": "partial", "yes but different time": "partial",
              "no": "no", "didn't": "no", "not really": "no", "doesn't match": "no", "didn't happen": "no", "nope": "no",
              "not sure": "unknown", "unknown": "unknown", "don't know": "unknown",
              "don't remember": "unknown", "n/a": "unknown"}


_DOMAIN_RES = {
    dom: re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")(?:s|es|ing|ed)?\b")
    for dom, kws in DOMAIN_KEYWORDS.items()
}


def _apply_disclaimer(reply: str, domain: str | None) -> str:
    note = DOMAINS.get(domain or "", {}).get("disclaimer")
    if note and note not in reply:
        return reply.rstrip() + "\n\n" + note
    return reply


def detect_domain(text: str) -> str | None:
    # "of course" is a figure of speech, not the education keyword "course"
    t = re.sub(r"\bof course\b", " ", text.lower())
    for dom, rx in _DOMAIN_RES.items():
        if rx.search(t):
            return dom
    return None


def detect_varga(text: str) -> str | None:
    t = text.lower()
    explicit = re.search(r"\bd-?(\d{1,2})\b", t)
    if explicit:
        return f"D{int(explicit.group(1))}"
    for v, keys in {"D9": ["navamsa", "navamsha"],
                    "D10": ["dasamsa", "dashamsha"],
                    "D1": ["rasi", "birth chart", "kundli", "natal chart"],
                    "D7": ["saptamsa"], "D2": ["hora"],
                    "D24": ["chaturvimshamsa"], "D60": ["shashtiamsa"]}.items():
        if any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in keys):
            return v
    return None


def _conversation_history(conv: Conversation) -> list[dict]:
    # Structured replies still contain conversational text. Dropping them left
    # the model unable to understand follow-ups to charts, timing and reports.
    # A turn can add a timing notice before generating its answer. The provider
    # (including the offline responder) must still receive the actual question last.
    end = next((i for i in range(len(conv.messages), 0, -1)
                if conv.messages[i - 1].role == "user"), 0)
    return [{"role": m.role, "content": m.content}
            for m in conv.messages[max(0, end - 16):end] if m.role in ("user", "assistant")]


def _previous_reading(conv, profile):
    # A structured explanation or an outcome prompt can follow the reading.
    # Other intervening replies start their own conversational context.
    for m in reversed(conv.messages):
        if m.role != "assistant":
            continue
        meta = json.loads(m.meta_json or "{}")
        if m.kind == "analysis" or meta.get("followup_id"):
            continue
        if meta.get("fingerprint", profile.calc_fingerprint) != profile.calc_fingerprint:
            break
        return meta
    return {}


def _today_at(birth: BirthInput) -> date:
    """'Today' in the chart's own timezone (DST-aware)."""
    now = _utcnow()
    approx_local = now + timedelta(hours=birth.tz_offset)
    tz = geo.historical_utc_offset(birth.lat, birth.lon, approx_local,
                                 birth.tz_offset)
    return (now + timedelta(hours=tz)).date()


def _panchang_day(t: str, today: date) -> date:
    if "day after" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", t)
    if m:
        return date.fromisoformat(m.group(1))
    return today


def _timing_horizon(t: str) -> tuple[int, int]:
    """(start offset, days to scan) for a timing question."""
    m = re.search(r"next (\d{1,3}) days", t)
    if m:
        return 0, max(1, min(180, int(m.group(1))))
    if "next week" in t:
        return 7, 7
    if "this week" in t:
        return 0, 7
    if "this month" in t:
        return 0, 30
    if "next month" in t:
        return 30, 30
    return 0, 60


def _format_panchang(pan: dict, place_label: str) -> str:
    t, n, y, k, v = (pan["tithi"], pan["nakshatra"], pan["yoga"],
                     pan["karana"], pan["vaara"])
    lines = [
        f"Here is the panchang for {pan['date']} ({place_label}):",
        f"{v['name']} ({v['lord']}'s day) · {t['name']} tithi, {t['paksha']} "
        f"paksha · {n['name']} nakshatra pada {n['pada']} · {y['name']} yoga · "
        f"{k['name']} karana.",
        f"Sunrise {pan['sunrise']['time']}, sunset {pan['sunset']['time']}.",
    ]
    per = pan.get("personal")
    if per:
        day = f"Your day: {per['tara']['name']} tara"
        if per["tara"]["adverse"]:
            day += " (a tara to be careful with)"
        if per["chandrashtama"]:
            day += " · chandrashtama — the Moon is 8th from your natal Moon"
        elif per.get("moon_house_from_janma"):
            day += (f" · Moon in the {_ordinal(per['moon_house_from_janma'])} "
                    "from your natal Moon")
        sfm = per.get("saturn_from_moon") or {}
        if sfm.get("sade_sati"):
            day += (f" · Saturn in the {_ordinal(sfm['house'])} from your Moon "
                    "— sade sati period")
        elif sfm.get("ashtama"):
            day += " · ashtama shani"
        elif sfm.get("kantaka"):
            day += " · kantaka shani"
        lines.append(day + ".")
    w = pan["windows"]
    avoid = [f"Rahu Kaalam {w['rahu_kaalam'][0][:5]}–{w['rahu_kaalam'][1][:5]}",
             f"Yamaganda {w['yamaganda'][0][:5]}–{w['yamaganda'][1][:5]}",
             f"Gulika {w['gulika'][0][:5]}–{w['gulika'][1][:5]}"]
    dm = w["durmuhurta"]
    for i in range(0, len(dm) - 1, 2):
        avoid.append(f"Durmuhurta {dm[i][:5]}–{dm[i + 1][:5]}")
    lines.append("Avoid: " + "; ".join(avoid) + ".")
    lines.append(f"Abhijit muhurta {w['abhijit'][0][:5]}–{w['abhijit'][1][:5]} — "
                 "the day's clean midday window.")
    good = [c for c in (pan.get("choghadiya") or {}).get("day", [])
            if c["good"]]
    if good:
        lines.append("Good choghadiya (day): " + "; ".join(
            f"{c['name']} {c['start']}–{c['end']}" for c in good) + ".")
    return "\n".join(lines)


def _ordinal(n: int) -> str:
    return f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"


def _panchang_reply(db, conv, profile, facts, birth, t) -> Message:
    try:
        pan = panchang.daily_panchang(_panchang_day(t, _today_at(birth)),
                                      panchang.place_of(birth), facts)
    except Exception:
        return _add_msg(db, conv, "assistant",
                        "I couldn't compute the panchang for that day — "
                        "try a nearby date.")
    return _add_msg(db, conv, "assistant",
                    _format_panchang(pan, birth.place_label),
                    kind="panchang", meta={"panchang": pan})


def _format_timing(sug: dict, horizon: int, who: str = "you") -> str:
    act = sug["activity"].replace("_", " ")
    head = (f"For {('your' if who == 'you' else who + chr(0x2019) + 's')} "
            f"{act}, I scanned the next {horizon} days — these are the "
            "dates where the traditional indications gather best. Days carrying "
            "a classical exclusion — adverse tara, chandrashtama, Vishti karana, "
            f"a harsh yoga, Amavasya or a Rikta tithi — were screened out "
            f"({sug['excluded_days']} dropped"
            + (f", {sug['failed_days']} couldn't be computed"
               if sug.get("failed_days") else "") + ").")
    if not sug["days"]:
        return (head + "\n\nEvery day in that span carries an exclusion — "
                "widen the range (try 'best time in the next 90 days') or treat "
                "it as a stretch for extra care rather than new beginnings.")
    lines = [head]
    for d in sug["days"]:
        limb = d["limbs"]
        line = (f"- {d['date']} — {limb['vaara']}, "
                f"{limb['tithi']} tithi, {limb['nakshatra']} nakshatra: "
                + "; ".join(d["reasons"]))
        win = d.get("suggested_window")
        if win:
            line += f". Suggested window ~{win['start']}–{win['end']}"
            if win["kind"] == "abhijit":
                line += " (abhijit)"
            elif win["kind"].startswith("choghadiya"):
                line += f" ({win['kind'].split(':')[1]} choghadiya)"
            else:
                line += " (open daylight)"
        rk = d["avoid"]["rahu_kaalam"]
        line += f". Keep clear of Rahu Kaalam {rk[0][:5]}–{rk[1][:5]}."
        lines.append(line)
    return "\n".join(lines)


def _next_pending_event(db: Session, conv: Conversation, profile: BirthProfile) -> CalibrationEvent | None:
    evs = (db.query(CalibrationEvent)
           .filter(CalibrationEvent.profile_id == profile.id)
           .order_by(CalibrationEvent.id).all())
    for e in evs:
        if not e.user_feedback:
            return e
    return None


def _ask_event(db: Session, conv: Conversation, ev: CalibrationEvent, first=False):
    prefix = ""
    if first:
        poss = _words(ev.profile)["poss"]
        prefix = (f"I’ll start with a few broad indications from {poss} chart and see what fits. "
                  "You can answer the checks or ask your own question at any point.\n\n")
    _add_msg(db, conv, "assistant", prefix + ev.chat_text,
             kind="options",
             meta={"options": CHECK_OPTIONS,
                   "event_id": ev.event_id})
    ev.asked = True
    conv.pending_event_id = ev.event_id
    conv.state = "cal_ask"


# ------------------------------------------------------------------ entry

CONTINUE = "Continue with the reading"
CHECK_OPTIONS = ["Yes, that happened", "Something similar, different time",
                 "No, that didn't happen", "Not sure / doesn't apply", CONTINUE]


def reading_note(profile: BirthProfile) -> str:
    poss = _words(profile)["poss"]
    reason = {
        "uncalibrated": "The past-event checks didn't establish a consistent match.",
        "insufficient_history": "There isn't enough past history to check the birth time.",
        "skipped": "We've left the birth-time checks incomplete.",
    }[profile.calibration_state]
    return (f"{reason} I'll use {poss} recorded birth time. "
            "If that time is off, predictions may be less accurate, especially dates.")


def _notice_meta(profile):
    return {"birth_time_notice": profile.calc_fingerprint}


def invite_reading(db, conv, profile):
    conv.state = "open"
    conv.pending_event_id = ""
    if profile.calibration_state == "uncalibrated":
        _enter_rectify(db, conv, profile)
    else:
        _add_msg(db, conv, "assistant", reading_note(profile) + " What would you like to explore?",
                 meta=_notice_meta(profile))


def needs_reading_notice(conv, profile):
    if profile.calibration_state not in ("uncalibrated", "skipped", "insufficient_history"):
        return False
    return not any(json.loads(m.meta_json or "{}").get("birth_time_notice") == profile.calc_fingerprint
                   for m in reversed(conv.messages) if m.role == "assistant")


def _mark_insufficient(db: Session, conv: Conversation, profile: BirthProfile):
    profile.calibration_state = "insufficient_history"
    profile.predictions_allowed = True
    invite_reading(db, conv, profile)


def _ensure_events(db: Session, profile: BirthProfile, facts: dict) -> int:
    """Seed calibration events when none exist or the fingerprint changed
    (e.g. after the birth details were edited mid-conversation).
    Returns the number of events available; fewer than 2 means the chart
    cannot be calibrated (no events are stored in that case)."""
    existing = (db.query(CalibrationEvent)
                .filter(CalibrationEvent.profile_id == profile.id).all())
    if existing and existing[0].calc_fingerprint == profile.calc_fingerprint:
        if any(e.user_feedback for e in existing) or all(
                e.event_id.startswith(calibration.OPENING_EVENT_PREFIX) for e in existing):
            return len(existing)
    for e in existing:
        db.delete(e)
    db.flush()
    stmts = calibration.generate_statements(facts, birth_input(profile),
                                            profile.calc_fingerprint,
                                            subject=_subject(profile))
    if len(stmts) < 2:
        return 0
    for s in stmts:
        db.add(CalibrationEvent(
            profile_id=profile.id, event_id=s["event_id"], domain=s["domain"],
            predicted_event=s["predicted_event"],
            predicted_window_start=s["predicted_window"]["start"],
            predicted_window_end=s["predicted_window"]["end"],
            rules_evaluated=json.dumps(s["rules_evaluated"]),
            pillars_json=json.dumps(s["pillars"]),
            chat_text=s["chat_text"],
            calc_fingerprint=s["calculation_fingerprint"]))
    db.flush()
    return len(stmts)


def refresh_initial_checks(db, conv, profile):
    """Refresh an untouched opening questionnaire after the date policy changes."""
    if conv.state != "cal_ask" or conv.pending_event_id.startswith(calibration.OPENING_EVENT_PREFIX):
        return
    events = db.query(CalibrationEvent).filter(CalibrationEvent.profile_id == profile.id).all()
    if not events or any(e.user_feedback for e in events):
        return
    if _ensure_events(db, profile, chart_facts(profile)) < 2:
        _mark_insufficient(db, conv, profile)
    else:
        _ask_event(db, conv, _next_pending_event(db, conv, profile), first=True)
    db.commit()


def refresh_event_wording(db: Session, profile: BirthProfile):
    """After the name/relation changed without a material birth edit, re-word
    the not-yet-answered calibration questions for the new subject."""
    pending = [e for e in db.query(CalibrationEvent)
               .filter(CalibrationEvent.profile_id == profile.id).all()
               if not e.user_feedback]
    if not pending:
        return
    stmts = {s["event_id"]: s for s in calibration.generate_statements(
        chart_facts(profile), birth_input(profile), profile.calc_fingerprint,
        subject=_subject(profile))}
    for e in pending:
        s = stmts.get(e.event_id)
        if s and s["domain"] == e.domain:
            e.chat_text = s["chat_text"]
            e.predicted_event = s["predicted_event"]


def start_conversation(db: Session, conv: Conversation, profile: BirthProfile) -> list[Message]:
    """Called once when the chat opens for a fresh profile."""
    facts = chart_facts(profile)
    lagna = facts["lagna"]
    if _is_other(profile):
        hello = (f"Namaste. This is {_words(profile)['poss']} kundli ({profile.relation}) — "
                 f"{lagna['sign_name']} lagna rising, Moon in "
                 f"{facts['planets']['Moon']['sign_name']} "
                 f"({facts['planets']['Moon']['nakshatra']['name']} nakshatra).")
    else:
        hello = (f"Namaste{', ' + profile.display_name if profile.display_name else ''}. "
                 f"I've drawn up your kundli — {lagna['sign_name']} lagna rising, Moon in "
                 f"{facts['planets']['Moon']['sign_name']} "
                 f"({facts['planets']['Moon']['nakshatra']['name']} nakshatra).")
    _add_msg(db, conv, "assistant", hello)

    n = _ensure_events(db, profile, facts)
    ev = _next_pending_event(db, conv, profile)
    if n < 2:
        _mark_insufficient(db, conv, profile)
    elif ev is None:
        conv.state = "open"
    else:
        _ask_event(db, conv, ev, first=True)
    db.commit()
    return conv.messages


# ------------------------------------------------------------------ main turn

def handle_message(db: Session, conv: Conversation, profile: BirthProfile,
                   text: str, on_delta=None) -> list[Message]:
    """`on_delta(str)` receives LLM text chunks as they stream (optional)."""
    start_len = len(conv.messages)
    _add_msg(db, conv, "user", text)
    facts = chart_facts(profile)
    birth = birth_input(profile)

    # ---------- reply to a pending "did it happen?" follow-up ----------
    if conv.state == "open" and _record_followup_reply(db, conv, profile, text):
        db.commit()
        return conv.messages[start_len:]

    # ---------- calibration phase ----------
    if conv.state in ("cal_intro", "cal_ask", "cal_followup"):
        _calibration_turn(db, conv, profile, facts, text, on_delta)
        db.commit()
        return conv.messages[start_len:]

    # A user may return to the optional time check from an open conversation.
    if conv.state in RECTIFY_STATES or (profile.calibration_state == "uncalibrated"
                                        and _norm_reply(text) == _norm_reply(SHARE_EVENTS)):
        _rectify_turn(db, conv, profile, facts, birth, text, on_delta)
        db.commit()
        return conv.messages[start_len:]

    # ---------- open chat ----------
    _open_turn(db, conv, profile, facts, birth, text, on_delta)
    if conv.state == "open":
        _maybe_ask_followup(db, conv, profile)
    db.commit()
    return conv.messages[start_len:]


# anything question- or intent-shaped is never a calibration answer
_QUESTIONISH = re.compile(
    r"(tell me|what|when|why|how|show|will|would|future|chart|kundli|ignore|"
    r"predict|read my|\?)", re.I)


def _classify_answer(text: str) -> str | None:
    t = _norm_reply(text)
    if t in ANSWER_MAP:
        return ANSWER_MAP[t]
    if _QUESTIONISH.search(t) or len(t) >= 60 or (
            detect_domain(t) and re.search(r"\b(?:actually|instead|let.s discuss|i meant|talk about)\b", t)):
        return None
    # word-boundary matching, longest keys first — substring matching once
    # misread "...future now" as the answer "no"
    for k in sorted(ANSWER_MAP, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", t):
            return ANSWER_MAP[k]
    return None


def _calibration_turn(db, conv, profile, facts, text, on_delta):
    ev = (db.query(CalibrationEvent)
          .filter(CalibrationEvent.event_id == conv.pending_event_id,
                  CalibrationEvent.profile_id == profile.id).first())

    norm = _norm_reply(text)
    skip = norm in (_norm_reply(CONTINUE), "skip checks", "skip the checks", "skip calibration",
                    "continue", "skip for now") or (norm == "skip" and conv.state != "cal_followup")
    asks_about_check = re.fullmatch(r"(why|why (?:this question|are you asking(?: this)?)|"
                                    r"how do you know|show me the calculation)[?!. ]*", norm)
    if ev and asks_about_check:
        _add_msg(db, conv, "assistant",
                 f"The chart points to {ev.domain} between {ev.predicted_window_start} and "
                 f"{ev.predicted_window_end}. Does that period fit what you remember?",
                 kind="options", meta={"options": CHECK_OPTIONS, "event_id": ev.event_id})
        return

    # Keep factual lookups available without interrupting the check (or its date follow-up).
    if ev and (PANCHANG_PAT.search(text) or DAILY_PAT.search(text)):
        _panchang_reply(db, conv, profile, facts, birth_input(profile), text.lower())
        if conv.state == "cal_ask":
            _ask_event(db, conv, ev)
        return

    # chart requests are factual — answer them without losing the pending check
    if ev and conv.state == "cal_ask" and language.show_chart(text, detect_varga(text)):
        varga = detect_varga(text.lower()) or "D1"
        data = facts["vargas"].get(varga)
        if data:
            _add_msg(db, conv, "assistant",
                     f"Here's {_words(profile)['poss']} {varga} chart.",
                     kind="chart", meta={"varga": varga, "chart": data})
            _ask_event(db, conv, ev, first=False)
            return

    feedback = _classify_answer(text)
    year_match = _YEAR_RE.search(text)
    date_reply = conv.state == "cal_followup" and (
        norm in ("not sure", "don't know", "skip", "don't remember")
        or (year_match and not _QUESTIONISH.search(text)
            and (int(year_match[1]) <= date.today().year or norm == year_match[1])))
    if skip or (feedback is None and not date_reply):
        profile.calibration_state = "skipped"
        profile.predictions_allowed = True
        conv.state = "open"
        conv.pending_event_id = ""
        if skip:
            invite_reading(db, conv, profile)
        else:
            _open_turn(db, conv, profile, facts, birth_input(profile), text, on_delta)
        return

    if conv.state == "cal_followup" and ev:
        # expect a month/year
        m = re.search(r"(20\d\d|19\d\d)", text)
        mon = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", text, re.I)
        if not m:
            if _norm_reply(text) in ("not sure", "don't know", "skip", "don't remember"):
                _advance_calibration(db, conv, profile,
                                     note="That's okay — I'll leave the actual date unknown.")
                return
            _add_msg(db, conv, "assistant",
                     "Roughly which year did it happen? You can also say 'not sure'.")
            return
        year = int(m.group(1))
        if year < profile.year or year > date.today().year:
            _add_msg(db, conv, "assistant", "Please give a year between the birth year and today.")
            return
        ev.actual_date = f"{year}-{mon.group(1)[:3] if mon else ''}".strip("-")
        _advance_calibration(db, conv, profile,
                             note="Noted — the timing was different. I'll remember the actual period.")
        return

    if conv.state == "cal_intro":
        if _ensure_events(db, profile, facts) < 2:
            _mark_insufficient(db, conv, profile)
            return
        ev = _next_pending_event(db, conv, profile)
        if ev:
            _ask_event(db, conv, ev, first=True)
            return

    if ev is None:
        conv.state = "open"
        _add_msg(db, conv, "assistant", "What would you like to explore?")
        return

    if feedback == "partial":
        ev.user_feedback = "partial"
        ev.matched = False
        conv.state = "cal_followup"
        _add_msg(db, conv, "assistant",
                 "When do you remember it happening? "
                 "A month and year is enough, or just the year.")
        return

    _CANON = {"yes": "confirmed", "partial": "partial",
              "no": "rejected", "unknown": "unknown"}
    ev.user_feedback = _CANON[feedback]
    ev.matched = (feedback == "yes")
    _advance_calibration(db, conv, profile)


def _advance_calibration(db, conv, profile, note=None):
    if note:
        _add_msg(db, conv, "assistant", note)
    ev = _next_pending_event(db, conv, profile)
    if ev is not None:
        _ask_event(db, conv, ev, first=False)
        return
    # done — outcome
    evs = (db.query(CalibrationEvent)
           .filter(CalibrationEvent.profile_id == profile.id).all())
    outcome = calibration.calibration_outcome([
        {"user_feedback": e.user_feedback, "matched": e.matched} for e in evs])
    profile.calibration_state = outcome["state"]
    profile.predictions_allowed = outcome["predictions_allowed"]
    if outcome["state"] == "uncalibrated":
        if profile.rectified_from:
            # the checks at an ADJUSTED time failed too — never leave the user
            # on a time that matched neither their input nor their history
            _restore_original_time(db, profile)
            _add_msg(
                db, conv, "assistant",
                f"The adjusted time didn't match {_words(profile)['poss']} past either, so I've "
                "gone back to the time you entered.")
        _enter_rectify(db, conv, profile)
        return
    conv.state = "open"
    conv.pending_event_id = ""
    _add_msg(db, conv, "assistant", outcome["label"] + " What would you like to explore?")


# ------------------------------------------------------------------ rectification

EDIT_BIRTH = "Edit birth details"
SHARE_EVENTS = "Share life events"
CHECK_NOW = "That's all, check my time"
_ACTIONS = {EDIT_BIRTH: "edit_birth"}
MAX_MILESTONES = 5


def _stamp(profile: BirthProfile) -> str:
    return (f"{profile.year:04d}-{profile.month:02d}-{profile.day:02d} "
            f"{profile.hour:02d}:{profile.minute:02d}:{(profile.second or 0):02d}")


def _set_time(profile: BirthProfile, dt: datetime):
    profile.year, profile.month, profile.day = dt.year, dt.month, dt.day
    profile.hour, profile.minute, profile.second = dt.hour, dt.minute, dt.second
    # the date may have shifted, so re-derive the historical UTC offset
    profile.utc_offset_hours = geo.historical_utc_offset(
        profile.latitude, profile.longitude, dt, profile.utc_offset_hours)
    profile.chart_json = None
    profile.calc_fingerprint = birth_fingerprint(birth_input(profile))


def _apply_birth_time(db: Session, profile: BirthProfile, nb: BirthInput):
    """Adopt a rectified time, remembering the user's original once."""
    if not profile.rectified_from:
        profile.rectified_from = _stamp(profile)
    _set_time(profile, datetime(nb.year, nb.month, nb.day, nb.hour, nb.minute, nb.second))


def _restore_original_time(db: Session, profile: BirthProfile):
    _set_time(profile, datetime.strptime(profile.rectified_from, "%Y-%m-%d %H:%M:%S"))
    profile.rectified_from = None
    profile.rectification_attempted = True
    profile.calibration_state = "uncalibrated"
    profile.predictions_allowed = True
    # the rejected checks belonged to the adjusted chart
    db.query(CalibrationEvent).filter(CalibrationEvent.profile_id == profile.id).delete()
    db.flush()


def _start_fresh_checks(db: Session, conv: Conversation, profile: BirthProfile):
    """Three NEW checks for the (re)timed chart."""
    conv.state = "cal_intro"
    conv.pending_event_id = ""
    profile.calibration_state = "pending"
    profile.predictions_allowed = False
    if _ensure_events(db, profile, chart_facts(profile)) < 2:
        _mark_insufficient(db, conv, profile)
        return
    ev = _next_pending_event(db, conv, profile)
    if ev:
        _ask_event(db, conv, ev, first=False)


def _complete_milestones(db: Session, profile: BirthProfile) -> list:
    return [m for m in profile.milestones if m.domain]


def rectify_invite(profile: BirthProfile) -> tuple[str, list[str]]:
    options = [CONTINUE]
    if not profile.milestone_search_done:
        options.append(SHARE_EVENTS)
    options.append(EDIT_BIRTH)
    text = reading_note(profile)
    if not profile.milestone_search_done:
        text += (f" Could you share two or three significant events from {_words(profile)['poss']} life "
                 "after age 15, with an approximate year? A month helps if you remember it. "
                 "You can send them together or one at a time, or continue with the reading.")
    else:
        text += " What would you like to explore?"
    return text, options


def _enter_rectify(db: Session, conv: Conversation, profile: BirthProfile):
    conv.state = "rectify" if profile.milestone_search_done else "rectify_collect"
    conv.pending_event_id = ""
    text, options = rectify_invite(profile)
    _add_msg(db, conv, "assistant", text, kind="options",
             meta={"options": options, "actions": _ACTIONS, **_notice_meta(profile)})


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONTH_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
_YEAR_RE = re.compile(r"\b(19\d\d|20\d\d)\b")
_NUM_MONTH_RE = re.compile(r"\b(\d{1,2})[/-](?:19|20)\d\d\b|\b(?:19|20)\d\d[/-](\d{1,2})\b")
# a first-person past event, not a question about a year
_EVENT_CUE = re.compile(
    r"\b(started|start|joined|married|marriage|wedding|engaged|divorced|separated|moved|"
    r"relocated|shifted|graduated|graduation|passed|cleared|enrolled|admitted|finished|"
    r"completed|began|got|had|lost|left|quit|resigned|promoted|hired|fired|retired|"
    r"bought|sold|inherited|became|born|died|passed away|surgery|accident|launched|founded)\b",
    re.I)
_EVENT_DOMAIN = [
    ("relationship", r"marri|wedding|engag|divorc|separated|spouse|\bwife\b|husband|"
                     r"\bchild\b|\bbaby\b|\bson\b|daughter"),
    ("education", r"graduat|degree|college|school|universit|\bexams?\b|\bcourse\b|enrol|"
                  r"admitted|studies|\bstudy|\bmba\b|\bphd\b|masters|bachelor"),
    ("career", r"\bjobs?\b|joined|hired|fired|promot|resign|\bquit\b|retire|career|"
               r"business|company|\bwork|office|launched|founded"),
    ("relocation", r"\bmoved\b|\bmove\b|relocat|shifted|abroad|new city|emigrat|immigrat|settled"),
    ("finance", r"bought|\bsold\b|\bloan\b|\bdebt\b|inherit|invest|\bhouse\b|\bflat\b|"
                r"property|money|salary"),
    ("health", r"surgery|hospital|\bill\b|illness|\bsick\b|accident|diagnos|injur|health"),
]
_DOMAIN_WORDS = {"career": "career", "job": "career", "work": "career",
                 "education": "education", "study": "education", "studies": "education",
                 "relationship": "relationship", "marriage": "relationship", "family": "relationship",
                 "relocation": "relocation", "move": "relocation", "moving": "relocation",
                 "finance": "finance", "money": "finance", "health": "health"}


def _event_domain(text: str) -> str | None:
    t = text.lower()
    for dom, pat in _EVENT_DOMAIN:
        if re.search(pat, t):
            return dom
    return detect_domain(text)


def looks_like_event(text: str) -> bool:
    t = text.lower()
    if "?" in t or re.search(r"\b(will|would|when|what|which|how|should|shall)\b", t):
        return False
    return bool(_YEAR_RE.search(t) and _EVENT_CUE.search(t))


def parse_milestones(text: str, born: date, today: date) -> tuple[list[dict], list[str]]:
    """Split a message into dated events. Returns (events, problems); each
    event is {year, month, domain, description}."""
    events, problems = [], []
    clauses = re.split(r"[;\n]|\.\s+|\.$|,\s*(?=[a-z])|\band then\b|\band\b(?=[^0-9]*\b(?:19|20)\d\d)",
                       text, flags=re.I)
    # a clause without a year belongs with its neighbour ("In 2012, I joined X")
    merged, carry = [], ""
    for raw in clauses:
        c = (raw or "").strip()
        if not c:
            continue
        if _YEAR_RE.search(c):
            merged.append((carry + " " + c).strip())
            carry = ""
        elif merged:
            merged[-1] += " " + c
        else:
            carry = (carry + " " + c).strip()
    for c in merged:
        ym = _YEAR_RE.search(c)
        year = int(ym.group(1))
        month = None
        nm = _NUM_MONTH_RE.search(c)
        if nm:
            month = int(nm.group(1) or nm.group(2))
        else:
            mm = _MONTH_RE.search(c)
            if mm:
                month = _MONTHS[mm.group(1).lower()[:3]]
        if month is not None and not 1 <= month <= 12:
            month = None
        when = f"{date(2000, month, 1):%B} {year}" if month else str(year)
        if (year, month or 12) < (born.year, born.month):
            problems.append(f"{when} is before you were born, so I've left it out.")
            continue
        if (year, month or 1) > (today.year, today.month):
            problems.append(f"{when} is in the future, so I can't use it as a past event.")
            continue
        events.append({"year": year, "month": month, "domain": _event_domain(c),
                       "description": c[:300]})
    return events, problems


def _describe(m) -> str:
    when = f"{date(2000, m.month, 1):%B} {m.year}" if m.month else str(m.year)
    return f"{m.domain}, {when}" if m.domain else when


def _rectify_options(profile: BirthProfile) -> list[str]:
    done = len(_complete_milestones(None, profile))
    return [CHECK_NOW, CONTINUE, EDIT_BIRTH] if done >= 2 else [CONTINUE, EDIT_BIRTH]


def _ack_milestones(db, conv, profile, added: list, problems: list[str]):
    parts = []
    if added:
        parts.append("Got it — " + "; ".join(_describe(m) for m in added) + ".")
    parts.extend(problems)
    pending = [m for m in profile.milestones if not m.domain]
    if pending:
        conv.state = "rectify_domain"
        conv.pending_event_id = f"m:{pending[0].id}"
        parts.append(f"What kind of event was \"{pending[0].description[:80]}\" — career, "
                     "education, relationship, relocation, finance or health?")
        _add_msg(db, conv, "assistant", " ".join(parts), kind="options",
                 meta={"options": ["Career", "Education", "Relationship", "Relocation",
                                   "Finance", "Health"]})
        return
    done = len(_complete_milestones(db, profile))
    if done >= 3 or done >= MAX_MILESTONES:
        _add_msg(db, conv, "assistant", " ".join(parts) if parts else "Thanks.")
        _run_milestone_search(db, conv, profile)
        return
    conv.state = "rectify_collect"
    if done == 2:
        parts.append(f"One more would make the check stronger — or choose \"{CHECK_NOW}\".")
    elif done == 1:
        parts.append("One or two more, please — each with a month and year if you can.")
    else:
        parts.append("Please include the month and year, e.g. \"joined my first job in July 2012\".")
    _add_msg(db, conv, "assistant", " ".join(parts), kind="options",
             meta={"options": _rectify_options(profile), "actions": _ACTIONS})


def _run_milestone_search(db, conv, profile):
    ms = _complete_milestones(db, profile)
    profile.milestone_search_done = True
    res = calibration.search_with_milestones(birth_input(profile), chart_facts(profile),
                                             ms, engine)
    if res is None:
        conv.state = "rectify"
        conv.pending_event_id = ""
        _add_msg(db, conv, "assistant",
                 "The nearby times I checked didn't fit those events more closely. "
                 "I'll keep the recorded time and treat dates as approximate. What would you like to explore?",
                 kind="options", meta={"options": [CONTINUE, EDIT_BIRTH], "actions": _ACTIONS})
        return
    nb = res["birth"]
    sign = "+" if res["delta_minutes"] > 0 else ""
    hhmm = f"{nb.hour:02d}:{nb.minute:02d}"
    conv.state = "rectify_confirm"
    conv.pending_event_id = (f"t:{nb.year:04d}-{nb.month:02d}-{nb.day:02d} "
                             f"{nb.hour:02d}:{nb.minute:02d}:{nb.second:02d}")
    _add_msg(db, conv, "assistant",
             f"Your events line up noticeably better with a birth time of {hhmm} "
             f"({sign}{res['delta_minutes']} min from what you entered). If you'd like, I'll "
             "use that time for the chart and offer three new checks.",
             kind="options", meta={"options": [f"Yes, use {hhmm}", "No, keep my time"]})


def _rectify_turn(db, conv, profile, facts, birth, text, on_delta=None):
    """Turn handler for a chart that failed calibration. Collects dated
    milestones for an optional birth-time check."""
    norm = _norm_reply(text)

    if norm in (_norm_reply(CONTINUE), "continue", "skip", "skip for now"):
        conv.state = "open"
        conv.pending_event_id = ""
        _add_msg(db, conv, "assistant", "What would you like to explore in the chart?")
        return

    if conv.state == "rectify_confirm":
        proposed_time = conv.pending_event_id.split(" ")[-1][:5]
        if norm in ("yes", f"yes, use {proposed_time}"):
            stamp = conv.pending_event_id[2:]
            nb = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            _apply_birth_time(db, profile, BirthInput(
                name="", year=nb.year, month=nb.month, day=nb.day, hour=nb.hour,
                minute=nb.minute, second=nb.second, lat=0, lon=0, tz_offset=0,
                place_label=""))
            db.query(CalibrationEvent).filter(
                CalibrationEvent.profile_id == profile.id).delete()
            db.flush()
            _add_msg(db, conv, "assistant", f"The chart now uses {nb:%H:%M}.")
            _start_fresh_checks(db, conv, profile)
            return
        if norm in ("no", "no, keep my time"):
            conv.state = "rectify"
            conv.pending_event_id = ""
            _add_msg(db, conv, "assistant",
                     "I'll keep the time you entered. What would you like to explore?",
                     kind="options", meta={"options": [EDIT_BIRTH], "actions": _ACTIONS})
            return
        # Other questions continue with the current birth time.

    if norm == _norm_reply(EDIT_BIRTH):
        _add_msg(db, conv, "assistant",
                 f"Open the menu (top right) and choose \"{EDIT_BIRTH}\".")
        return

    if norm == _norm_reply(SHARE_EVENTS) and not profile.milestone_search_done:
        conv.state = "rectify_collect"
        _add_msg(db, conv, "assistant",
                 f"Tell me 2–3 significant events from {_words(profile)['poss']} life with the "
                 "month and year — for example "
                 "\"started my first job in July 2012\", \"got married March 2016\", "
                 "\"moved to Pune in 2019\". You can send them together or one at a time.")
        return

    if norm == _norm_reply(CHECK_NOW) and not profile.milestone_search_done:
        if len(_complete_milestones(db, profile)) >= 2:
            _run_milestone_search(db, conv, profile)
        else:
            _add_msg(db, conv, "assistant", "I need at least two dated events first.")
        return

    # panchang is factual — answer before the milestone parse so a dated
    # panchang question can't be swallowed as a life-event entry
    if PANCHANG_PAT.search(text.lower()) or DAILY_PAT.search(text.lower()):
        _panchang_reply(db, conv, profile, facts, birth, text.lower())
        return

    if conv.state == "rectify_domain":
        mid = conv.pending_event_id[2:] if conv.pending_event_id.startswith("m:") else ""
        m = next((x for x in profile.milestones if str(x.id) == mid), None)
        dom = _DOMAIN_WORDS.get(norm)
        if m is not None and dom:
            m.domain = dom
            conv.pending_event_id = ""
            _ack_milestones(db, conv, profile, [m], [])
            return
        conv.state = "rectify_collect"   # they moved on to a new event

    year = _YEAR_RE.search(text)
    dated_reply = (conv.state == "rectify_collect" and year and int(year[1]) <= date.today().year
                   and not _QUESTIONISH.search(text))
    if not profile.milestone_search_done and (looks_like_event(text) or dated_reply):
        born = date(profile.year, profile.month, profile.day)
        events, problems = parse_milestones(text, born, date.today())
        room = MAX_MILESTONES - len(profile.milestones)
        added = []
        for e in events[:max(room, 0)]:
            m = UserMilestone(profile_id=profile.id, **e)
            profile.milestones.append(m)
            added.append(m)
        db.flush()
        if added or problems:
            _ack_milestones(db, conv, profile, [m for m in added if m.domain], problems)
            return

    conv.state = "open"
    conv.pending_event_id = ""
    _open_turn(db, conv, profile, facts, birth, text, on_delta)


def _open_turn(db, conv, profile, facts, birth, text, on_delta=None) -> list[Message]:
    t = text.lower()
    # Conversations created before advisory checks may end in an old refusal.
    if profile.calibration_state == "pending":
        profile.calibration_state = "skipped"
        profile.predictions_allowed = True
    if needs_reading_notice(conv, profile):
        _add_msg(db, conv, "assistant", reading_note(profile), meta=_notice_meta(profile))

    # chart request — always allowed
    varga = detect_varga(t)
    if language.show_chart(text, varga):
        varga = varga or "D1"
        data = facts["vargas"].get(varga)
        if not data:
            _add_msg(db, conv, "assistant", f"I couldn't compute the {varga} chart for this birth data.")
            return conv.messages[-2:]
        _add_msg(db, conv, "assistant",
                 f"Here's {_words(profile)['poss']} {varga} chart — {facts['lagna']['sign_name']} lagna in D1. "
                 f"Anything you'd like me to read into it?",
                 kind="chart", meta={"varga": varga, "chart": data})
        return conv.messages[-2:]

    # panchang — the day's limbs; factual almanac, allowed at any gate
    if PANCHANG_PAT.search(t) or DAILY_PAT.search(t):
        _panchang_reply(db, conv, profile, facts, birth, t)
        return conv.messages[-2:]

    wants_report = bool(REPORT_PAT.search(t))
    wants_timing = bool(TIMING_PAT.search(t))
    if re.search(r"when (?:should|shall) i", t) and detect_domain(t) and panchang.detect_activity(t) == "general":
        wants_timing = False
    if (re.fullmatch(r"\s*(why|why is that|tell me why|explain( that)?|details|"
                     r"(show me( the)? )?(reasoning|evidence|calculation)|how do you know)[?.! ]*", t)
            and len(conv.messages) >= 2):
        for m in reversed(conv.messages[:-1]):
            if m.role == "assistant" and m.meta_json:
                meta = json.loads(m.meta_json)
                if m.kind == "analysis" or meta.get("followup_id"):
                    continue
                if "analysis" in meta:
                    a = meta["analysis"]
                    pillar_line = ", ".join(
                        f"{k.replace('_', ' ')}: {v}" for k, v in a["pillars"].items())
                    ev = list(dict.fromkeys(a["calculation_evidence_ids"]))
                    pretty = (f"Pillars — {pillar_line}.\n{a['convergence']}.\n\n"
                              "Evidence:\n- " + "\n- ".join(ev[:12]))
                    prec = a.get("precision")
                    if prec:
                        extra = [f"Confirmation: {prec['confirmation']}"]
                        if prec.get("timing_windows"):
                            extra.append("Strongest weeks: " + "; ".join(
                                f"{w['start']} → {w['end']}" for w in prec["timing_windows"]))
                        if prec.get("magnitude"):
                            extra.append(f"Indicated magnitude: {prec['magnitude']}")
                        if prec.get("eclipse_watch_months"):
                            extra.append("Watch months (eclipse near a natal planet): "
                                         + ", ".join(prec["eclipse_watch_months"]))
                        pretty += "\n\n" + "\n".join(extra)
                    _add_msg(db, conv, "assistant", pretty, kind="analysis", meta=a)
                    return conv.messages[-2:]
                if "timing" in meta:
                    sug = meta["timing"]
                    parts = [
                        f"How the days were ranked for "
                        f"{sug['activity'].replace('_', ' ')} — the tara is "
                        "personal; the rest are classical day-quality rules.",
                        "Scored: favourable tara +2, favourable tithi class +1, "
                        "preferred weekday +1, preferred nakshatra +1. Excluded "
                        "outright: adverse tara, chandrashtama, Vishti karana, "
                        "a harsh yoga, Amavasya, Rikta tithi.",
                    ]
                    for d in sug["days"]:
                        parts.append(f"- {d['date']} (score {d['score']}): "
                                     + "; ".join(d["reasons"]))
                    _add_msg(db, conv, "assistant", "\n".join(parts),
                             kind="analysis", meta=meta)
                    return conv.messages[-2:]
                break  # Evidence from an older, unrelated reading does not answer this question.
        # Without a computed trail, answer conversationally using the history.

    # report — computed chart + 12-month outlook, deterministic text.
    # Domain outlooks are abstaining "general outlook" verdicts, not
    # predictions made to the user — they stay in meta, not PredictionRecord,
    # so they don't dilute the forecast scorecard.
    if wants_report:
        rep = report.build_report(facts, birth, calibrated=_calibrated(profile),
                                  predictions_allowed=True,
                                  subject=_subject(profile),
                                  today=_today_at(birth))
        reply = "\n\n".join(rep["reading"])
        if any(d["domain"] == "health" for d in rep["domains"]):
            reply = _apply_disclaimer(reply, "health")
        _add_msg(db, conv, "assistant", reply, kind="report",
                 meta={"report": rep})
        return conv.messages[-2:]

    # electional timing — rank upcoming days for the asked activity
    if wants_timing:
        today = _today_at(birth)
        offset, horizon = _timing_horizon(t)
        activity = panchang.detect_activity(t)
        try:
            sug = panchang.suggest_days(facts, birth,
                                        today + timedelta(days=offset),
                                        days=horizon, activity=activity)
        except Exception:
            _add_msg(db, conv, "assistant",
                     "I couldn't compute the day ranking — try a shorter range.")
            return conv.messages[-2:]
        _add_msg(db, conv, "assistant",
                 _format_timing(sug, horizon, _subject(profile) or "you"),
                 kind="timing", meta={"timing": sug})
        return conv.messages[-2:]

    return _answer_reading(db, conv, profile, facts, birth, text, varga, on_delta)


def _answer_reading(db, conv, profile, facts, birth, text, varga, on_delta):
    t = text.lower()
    history = _conversation_history(conv)
    prior = _previous_reading(conv, profile)
    previous = prior.get("analysis", {})
    old_window = previous.get("analysis_window", {})
    dates = prior.get("requested_window") or ([old_window["start"], old_window["end"]] if old_window else None)
    prior_window = tuple(date.fromisoformat(d) for d in dates) if dates else None
    focus = language.focus_text(text)
    domain = detect_domain(focus)
    today = _today_at(birth)
    try:
        period = language.requested_window(focus, today, prior_window)
    except ValueError:
        _add_msg(db, conv, "assistant", "Which period would you like me to read? You can give a month and year.",
                 meta={"pending_domain": domain or previous.get("domain"),
                       "pending_event": prediction.event_spec(focus, domain) or (
                           previous.get("decision", {}).get("event") if domain in (None, previous.get("domain")) else None)})
        return conv.messages[-2:]

    event = prediction.event_spec(focus, domain)
    # A bare event label can answer a previous question, e.g. "an offer".
    if not domain and previous.get("domain"):
        event = prediction.event_spec(focus, previous["domain"])
        if event and not re.search(r"\b(?:can you offer|move on|offer advice)\b", focus, re.I):
            domain = previous["domain"]
        else:
            event = None

    references_reading = bool(re.search(
        r"\b(and if|in that case|what does (?:this|that|it)|tell me more|go on|and my|"
        r"elaborate|same (?:period|time)|what then|what do you mean|my current (?:role|company)|please continue|"
        r"explain (?:it|that|this)|how so|aur batao|(?:it|that|this) (?:happen|happening|likely)|"
        r"likely is (?:it|that)|within (?:my|the) same (?:team|company))\b", t))
    references_reading = references_reading or bool(re.fullmatch(r"(why|explain|yes please|go ahead|and then|and me|and why)[.?! ]*", t))
    factual = bool(re.search(r"\b(moon|sun|mars|mercury|venus|jupiter|saturn|rahu|ketu|lagna|"
                             r"ascendant|dasha|nakshatra|rashi|chart|kundli)\b", t))
    routing_seconds = 0
    social = re.fullmatch(r"(hi|hello|hey|namaste|thanks|thank you|ok|okay)[.! ]*", t)
    unclear_topic = not domain and not (previous and (period or references_reading))
    possible_event = domain and not event and re.search(r"\b(will|might|chance|likely|could i)\b", t)
    if (unclear_topic or possible_event) and not (varga or factual or social):
        routing_started = time.monotonic()
        topic = providers.conversation_topic(history, allow_external=_external_ok(profile))
        routing_seconds = time.monotonic() - routing_started
        if topic == "continue":
            references_reading = True
        elif topic in DOMAIN_KEYWORDS:
            domain = domain or topic
        else:
            for candidate, _, event_type, definition in prediction.EVENTS:
                if topic == event_type and domain in (None, candidate):
                    domain = candidate
                    event = {"event_type": event_type, "definition": definition}
                    break

    continuing = bool(period or references_reading)
    if not domain and continuing and not factual and not varga:
        domain = previous.get("domain") or prior.get("pending_domain")
        if not event and domain == prior.get("pending_domain"):
            event = prior.get("pending_event")
    prior_chart = prior.get("varga")
    chart_domain = {"D10": "career", "D9": "relationship", "D24": "education"}.get(prior_chart)
    if not varga and (continuing or t.startswith("what about")) and (not domain or domain == chart_domain):
        varga = prior_chart
        if varga and period and not domain:
            domain = chart_domain
    selected = language.chart_details(facts, varga, text) if varga else None
    if varga and not selected:
        _add_msg(db, conv, "assistant", f"The {varga} chart is unavailable for these birth details.")
        return conv.messages[-2:]
    if period and not domain and not selected and not factual:
        _add_msg(db, conv, "assistant",
                 f"What would you like to explore for {language.window_label(period)}?",
                 meta={"requested_window": [d.isoformat() for d in period]})
        return conv.messages[-2:]
    same_topic = domain and domain == previous.get("domain")
    if not event and same_topic and continuing and not re.search(r"\b(?:instead|actually|not|generally)\b", t):
        event = previous.get("decision", {}).get("event")
    keep_period = same_topic or references_reading or (not previous and prior.get("requested_window"))
    window = period or (prior_window if keep_period else None) or (today, today + timedelta(days=365))
    analysis = None
    if domain and (not selected or event or period):
        analysis, _prec = _precision_analysis(facts, birth, domain, *window, profile, question=focus, event=event)
        analysis["period_requested"] = bool(period or (keep_period and (
            previous.get("period_requested") or (not previous and prior_window))))
    if selected:
        facts = {**facts, "selected_chart": selected}
    run = engine.running_vimshottari(birth, (date.today().year, date.today().month, date.today().day))
    periods = "/".join("/".join(period["lords"]) for period in run[:2])
    reply, provider = providers.generate(
        history, facts=facts, analysis=analysis,
        context_note=(_context_prefix(profile) + f"Calibration state: {profile.calibration_state}. "
                      f"Current Vimshottari: {periods}. Use the resolved event and analysis window when supplied. "
                      "Name the period when timing was requested. Answer using the selected divisional chart when present."),
        allow_external=_external_ok(profile), on_delta=None if analysis else on_delta, routing_seconds=routing_seconds)
    reply = _apply_disclaimer(reply, domain)
    if analysis:
        _save_prediction(db, profile, text, analysis, reply)
    _add_msg(db, conv, "assistant", reply,
             meta={"provider": provider, "fingerprint": profile.calc_fingerprint,
                   **({"analysis": analysis, "requested_window": [d.isoformat() for d in window]} if analysis else {}),
                   **({"varga": varga} if selected else {})})
    return conv.messages[-2:]


# ------------------------------------------------------------ prediction follow-ups

FOLLOWUP_OPTIONS = ["It happened", "Partly", "It didn't happen", "Outside the window", "Not sure"]
_FOLLOWUP_OUTCOME = {"it happened": "happened", "partly": "partly",
                     "it didn't happen": "did_not", "outside the window": "outside_window", "not sure": "unsure"}


def _norm_reply(text: str) -> str:
    return text.strip().lower().replace("\u2019", "'").strip(".! ")


def _maybe_ask_followup(db: Session, conv: Conversation, profile: BirthProfile):
    """Ask about the oldest prediction whose window has passed, once."""
    rec = (db.query(PredictionRecord)
           .filter(PredictionRecord.profile_id == profile.id,
                   PredictionRecord.outcome.is_(None),
                   PredictionRecord.forecast == "event_indicated",
                   PredictionRecord.followup_asked_at.is_(None),
                   PredictionRecord.window_end < date.today())
           .order_by(PredictionRecord.id).first())
    if rec is None:
        return
    q = rec.question if len(rec.question) <= 140 else rec.question[:137] + "..."
    _add_msg(db, conv, "assistant",
             f"A while back you asked me about {rec.domain}"
             f"{' for ' + _subject(profile) if _is_other(profile) else ''}: \"{q}\" "
             f"The recorded event was: {rec.success_criteria or rec.question}. "
             f"The window we looked at ({rec.window_start} to {rec.window_end}) has now "
             "passed. Did it happen? Your answer helps me see how well the chart is doing "
             "for you.",
             kind="options",
             meta={"followup_id": rec.id, "options": list(FOLLOWUP_OPTIONS)})
    rec.followup_asked_at = _utcnow()


def _record_followup_reply(db: Session, conv: Conversation, profile: BirthProfile,
                           text: str) -> bool:
    outcome = _FOLLOWUP_OUTCOME.get(_norm_reply(text))
    if outcome is None:
        return False
    rec = (db.query(PredictionRecord)
           .filter(PredictionRecord.profile_id == profile.id,
                   PredictionRecord.outcome.is_(None),
                   PredictionRecord.followup_asked_at.isnot(None))
           .order_by(PredictionRecord.followup_asked_at.desc(), PredictionRecord.id.desc())
           .first())
    if rec is None:
        return False
    rec.outcome = outcome
    rec.outcome_at = _utcnow()
    thanks = {"happened": "Thank you — I've noted that it did happen.",
              "partly": "Thank you — noted as partly right.",
              "did_not": "Thank you — I've recorded that honestly as a miss.",
              "unsure": "No problem — noted as unsure.",
              "outside_window": "Recorded as outside the forecast window; it does not count as a hit."}[outcome]
    _add_msg(db, conv, "assistant", thanks)
    return True
