"""Conversation orchestrator.

State machine:
    cal_intro -> cal_ask -> (cal_followup) -> cal_ask -> ... -> open | rectify
The prediction gate is enforced HERE — server-side — never by the LLM.
"""
import json
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from ..astro import calibration, pillars, verify
from ..astro.constants import DOMAINS
from .. import geo
from ..astro.engine import BirthInput, birth_fingerprint, engine
from ..db import BirthProfile, CalibrationEvent, Conversation, Message
from ..llm import providers


# ------------------------------------------------------------------ helpers

def birth_input(profile: BirthProfile) -> BirthInput:
    return BirthInput(
        name=profile.display_name or "", year=profile.year, month=profile.month,
        day=profile.day, hour=profile.hour, minute=profile.minute,
        second=profile.second or 0, lat=profile.latitude, lon=profile.longitude,
        tz_offset=profile.utc_offset_hours, place_label=profile.place_name,
        birth_time_precision=profile.birth_time_precision,
    )


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
    "career": ["job", "career", "promotion", "work", "business", "profession", "salary", "boss", "interview", "transfer"],
    "education": ["study", "studies", "exam", "education", "degree", "college", "course", "learn"],
    "relationship": ["marriage", "marry", "married", "wedding", "relationship", "partner", "wife", "husband", "love", "spouse", "engagement"],
    "relocation": ["move", "relocate", "relocating", "abroad", "foreign", "city", "house shift", "settle"],
    "finance": ["money", "wealth", "finance", "financial", "income", "loan", "debt", "invest"],
    "direction": ["direction", "purpose", "path in life", "meaning"],
    "health": ["health", "illness", "sick", "disease", "hospital", "surgery", "recovery", "wellbeing", "wellness", "medical"],
}

FUTURE_PAT = re.compile(
    r"(will i|will it|next year|next month|in 20\d\d|this year|future|"
    r"promot\w+|marry|marriage|job change|switch|get a job|abroad|"
    r"predict|forecast|when will|shall i)", re.I)
WHY_PAT = re.compile(r"\b(why|reason|reasoning|evidence|explain|show me the calculation|how do you know|details)\b", re.I)
# an explicit request to SEE a chart — bare mentions of "chart" don't count
CHART_PAT = re.compile(
    r"(navamsa|navamsha|dasamsa|dashamsha|saptamsa|chaturvimshamsa|shashtiamsa|"
    r"hora\s+chart|d-?\d{1,2}\s+chart|kundli|birth chart|rasi chart|natal chart|"
    r"show\s+(me\s+)?(my\s+)?(d\d+|chart|kundli)|see\s+my\s+(d\d+|chart|kundli))", re.I)
GREET_PAT = re.compile(r"^\s*(hi|hello|hey|namaste|good (morning|evening|afternoon)|hare krishna)\b", re.I)

ANSWER_MAP = {"yes": "yes", "confirmed": "yes", "that happened": "yes",
              "partial": "partial", "similar": "partial", "close": "partial",
              "something similar": "partial", "yes but different time": "partial",
              "no": "no", "didn't": "no", "not really": "no", "nope": "no",
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
    for v, keys in {"D9": ["navamsa", "navamsha", "d9", "d-9"],
                    "D10": ["dasamsa", "dashamsha", "d10", "d-10"],
                    "D1": ["rasi", "d1", "birth chart", "kundli", "natal chart"],
                    "D7": ["saptamsa", "d7"], "D2": ["hora", "d2"],
                    "D24": ["chaturvimshamsa", "d24"], "D60": ["shashtiamsa", "d60"]}.items():
        if any(k in t for k in keys):
            return v
    return None


def _target_window(text: str) -> tuple[date, date]:
    """Parse a future window from the question, default next 12 months."""
    t = text.lower()
    today = date.today()
    m = re.search(r"\b(20\d\d)\b", t)
    if m:
        y = int(m.group(1))
        if "first half" in t or "early" in t:
            return date(y, 1, 1), date(y, 6, 30)
        if "second half" in t or "late" in t or "end of" in t:
            return date(y, 7, 1), date(y, 12, 31)
        return date(y, 1, 1), date(y, 12, 31)
    if "next year" in t:
        return date(today.year + 1, 1, 1), date(today.year + 1, 12, 31)
    if "this year" in t:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if "next month" in t:
        nm = today.replace(day=28)
        nm = (nm.fromordinal(nm.toordinal() + 7)).replace(day=1)
        end = nm.replace(day=28)
        return nm, end
    end = today.fromordinal(today.toordinal() + 365)
    return today, end


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
        prefix = ("Before we get into what's ahead, I'd like to check three periods from your "
                  "past against your birth chart. It helps me see whether the birth details "
                  "and the timing methods we're using are consistent — and it keeps me honest. "
                  "Can we start with the first?\n\n")
    _add_msg(db, conv, "assistant", prefix + ev.chat_text,
             kind="options",
             meta={"options": ["Yes, that happened", "Something similar, different time",
                               "No, that didn't happen", "Not sure / doesn't apply"],
                   "event_id": ev.event_id})
    ev.asked = True
    conv.pending_event_id = ev.event_id
    conv.state = "cal_ask"


# ------------------------------------------------------------------ entry

INSUFFICIENT_MSG = (
    "I can't verify your chart yet — there isn't enough past timeline for me to form "
    "three reliable checks against it. Until I can, I won't make predictions. I'm happy "
    "to answer factual questions about your chart, and if you update your birth details "
    "I'll try again.")


def _mark_insufficient(db: Session, conv: Conversation, profile: BirthProfile) -> Message:
    profile.calibration_state = "insufficient_history"
    profile.predictions_allowed = False
    conv.state = "open"
    conv.pending_event_id = ""
    return _add_msg(db, conv, "assistant", INSUFFICIENT_MSG)


def _ensure_events(db: Session, profile: BirthProfile, facts: dict) -> int:
    """Seed calibration events when none exist or the fingerprint changed
    (e.g. after the birth details were edited mid-conversation).
    Returns the number of events available; fewer than 3 means the chart
    cannot be calibrated (no events are stored in that case)."""
    existing = (db.query(CalibrationEvent)
                .filter(CalibrationEvent.profile_id == profile.id).all())
    if existing and existing[0].calc_fingerprint == profile.calc_fingerprint:
        return len(existing)
    for e in existing:
        db.delete(e)
    db.flush()
    stmts = calibration.generate_statements(facts, birth_input(profile),
                                            profile.calc_fingerprint)
    if len(stmts) < 3:
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


def start_conversation(db: Session, conv: Conversation, profile: BirthProfile) -> list[Message]:
    """Called once when the chat opens for a fresh profile."""
    facts = chart_facts(profile)
    lagna = facts["lagna"]
    hello = (f"Hello{', ' + profile.display_name if profile.display_name else ''}. "
             f"I've cast your chart — {lagna['sign_name']} rising, Moon in "
             f"{facts['planets']['Moon']['sign_name']} "
             f"({facts['planets']['Moon']['nakshatra']['name']} nakshatra).")
    _add_msg(db, conv, "assistant", hello)

    n = _ensure_events(db, profile, facts)
    ev = _next_pending_event(db, conv, profile)
    if n < 3:
        _mark_insufficient(db, conv, profile)
    elif ev is None:
        conv.state = "open"
    else:
        _ask_event(db, conv, ev, first=True)
    db.commit()
    return conv.messages


# ------------------------------------------------------------------ main turn

def handle_message(db: Session, conv: Conversation, profile: BirthProfile,
                   text: str) -> list[Message]:
    start_len = len(conv.messages)
    _add_msg(db, conv, "user", text)
    facts = chart_facts(profile)
    birth = birth_input(profile)

    # ---------- calibration phase ----------
    if conv.state in ("cal_intro", "cal_ask", "cal_followup"):
        _calibration_turn(db, conv, profile, facts, text)
        db.commit()
        return conv.messages[start_len:]

    # ---------- rectify: factual answers still allowed, future gated ----------
    if conv.state == "rectify":
        if CHART_PAT.search(text.lower()) and detect_varga(text.lower()):
            varga = detect_varga(text.lower()) or "D1"
            data = facts["vargas"].get(varga)
            if data:
                _add_msg(db, conv, "assistant",
                         f"Here's your {varga} chart. Note: we still haven't confirmed "
                         "your birth time is exact — keep that in mind.",
                         kind="chart", meta={"varga": varga, "chart": data})
        elif FUTURE_PAT.search(text):
            _add_msg(db, conv, "assistant",
                     "Since the past checks didn't match, the honest thing is to recheck the "
                     "inputs before I say anything about the future. You can update your birth "
                     "details in Profile, or tell me a couple of dated milestones from your own "
                     "life and we can look at them together.")
        else:
            run = engine.running_vimshottari(birth, (date.today().year, date.today().month, date.today().day))
            history = [{"role": m.role, "content": m.content}
                       for m in conv.messages[-8:] if m.kind == "text"]
            reply, provider = providers.generate(
                history, facts=facts,
                context_note="Calibration failed; explain chart facts only, no predictions.")
            vr = verify.verify_response(reply, facts, {"running_dasha": run})
            if not vr["ok"]:
                reply = verify.repair_response(reply, vr["issues"])
            _add_msg(db, conv, "assistant", reply, meta={"provider": provider})
        db.commit()
        return conv.messages[start_len:]

    # ---------- open chat ----------
    _open_turn(db, conv, profile, facts, birth, text)
    db.commit()
    return conv.messages[start_len:]


# anything question- or intent-shaped is never a calibration answer
_QUESTIONISH = re.compile(
    r"(tell me|what|when|why|how|show|will|would|future|chart|kundli|ignore|"
    r"predict|read my|\?)", re.I)


def _classify_answer(text: str) -> str | None:
    t = text.strip().lower().strip(".!")
    if t in ANSWER_MAP:
        return ANSWER_MAP[t]
    if _QUESTIONISH.search(t) or len(t) >= 60:
        return None
    # word-boundary matching, longest keys first — substring matching once
    # misread "...future now" as the answer "no"
    for k in sorted(ANSWER_MAP, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", t):
            return ANSWER_MAP[k]
    return None


def _calibration_turn(db, conv, profile, facts, text) -> list[Message]:
    new_msgs = []
    ev = (db.query(CalibrationEvent)
          .filter(CalibrationEvent.event_id == conv.pending_event_id,
                  CalibrationEvent.profile_id == profile.id).first())

    if conv.state == "cal_followup" and ev:
        # expect a month/year
        m = re.search(r"(20\d\d|19\d\d)", text)
        mon = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", text, re.I)
        ev.actual_date = f"{m.group(1) if m else ''}-{mon.group(1)[:3] if mon else ''}".strip("-")
        _advance_calibration(db, conv, profile, new_msgs,
                             note="Noted — the timing was different. I'll remember the actual period.")
        return new_msgs

    if conv.state == "cal_intro":
        if _ensure_events(db, profile, facts) < 3:
            new_msgs.append(_mark_insufficient(db, conv, profile))
            return new_msgs
        ev = _next_pending_event(db, conv, profile)
        if ev:
            _ask_event(db, conv, ev, first=True)
            return new_msgs

    if ev is None:
        conv.state = "open"
        new_msgs.append(_add_msg(db, conv, "assistant", "Let's talk — what's on your mind?"))
        return new_msgs

    # chart requests are factual — answer them without losing the pending check
    if CHART_PAT.search(text.lower()) and detect_varga(text.lower()):
        varga = detect_varga(text.lower()) or "D1"
        data = facts["vargas"].get(varga)
        if data:
            _add_msg(db, conv, "assistant",
                     f"Here's your {varga} chart.",
                     kind="chart", meta={"varga": varga, "chart": data})
            _ask_event(db, conv, ev, first=False)
            return conv.messages[-3:]

    # free-text intent overrides: a real question, not an answer
    feedback = _classify_answer(text)
    if feedback is None:
        if WHY_PAT.search(text):
            _add_msg(db, conv, "assistant",
                     f"This question comes from your actual chart — here's the reasoning behind it: "
                     f"{ev.predicted_event} "
                     f"(window {ev.predicted_window_start} → {ev.predicted_window_end}). "
                     f"Convergence: {json.loads(ev.pillars_json)}. "
                     "Does the event ring true?")
            return conv.messages[-2:]
        # keep the quick-reply buttons alive on the re-ask
        _add_msg(db, conv, "assistant",
                 "Take your time — was anything like that happening for you in that period? "
                 "A rough 'yes', 'something similar', 'no' or 'not sure' is all I need.",
                 kind="options",
                 meta={"options": ["Yes, that happened", "Something similar, different time",
                                   "No, that didn't happen", "Not sure / doesn't apply"],
                       "event_id": ev.event_id})
        return conv.messages[-2:]

    if feedback == "partial":
        ev.user_feedback = "partial"
        ev.matched = False
        conv.state = "cal_followup"
        _add_msg(db, conv, "assistant",
                 "Close but not exact — that's useful. Roughly when did it happen? "
                 "A month and year is enough, or just the year.")
        return conv.messages[-2:]

    _CANON = {"yes": "confirmed", "partial": "partial",
              "no": "rejected", "unknown": "unknown"}
    ev.user_feedback = _CANON[feedback]
    ev.matched = (feedback == "yes")
    note = None
    if feedback == "yes":
        note = "That matches. Good — the chart is speaking consistently."
    elif feedback == "no":
        note = "Understood — I'll record that honestly as a miss."
    else:
        note = "No problem, that's recorded as unknown."
    _advance_calibration(db, conv, profile, new_msgs, note=note)
    return conv.messages[-(len(new_msgs) + 2):]


def _advance_calibration(db, conv, profile, new_msgs, note=None):
    if note:
        new_msgs.append(_add_msg(db, conv, "assistant", note))
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
        # try rectification: a slightly different birth time may fit the
        # recorded feedback better — only adopt on a clearly better score.
        # At most ONE rectification per profile, so repeated attempts can't
        # drift the birth time away from what the user entered.
        rect = None
        if not profile.rectified_from:
            rect = calibration.try_rectify(birth_input(profile), chart_facts(profile), evs, engine)
        if rect:
            nb = rect["birth"]
            profile.rectified_from = (
                f"{profile.year:04d}-{profile.month:02d}-{profile.day:02d} "
                f"{profile.hour:02d}:{profile.minute:02d}:{(profile.second or 0):02d}")
            profile.year, profile.month, profile.day = nb.year, nb.month, nb.day
            profile.hour, profile.minute, profile.second = nb.hour, nb.minute, nb.second
            # the date may have shifted, so re-derive the historical UTC offset
            profile.utc_offset_hours = geo.historical_utc_offset(
                profile.latitude, profile.longitude,
                datetime(nb.year, nb.month, nb.day, nb.hour, nb.minute, nb.second),
                profile.utc_offset_hours)
            profile.chart_json = None
            profile.calc_fingerprint = birth_fingerprint(birth_input(profile))
            for e in evs:
                db.delete(e)
            db.flush()
            conv.state = "cal_intro"
            conv.pending_event_id = ""
            profile.calibration_state = "pending"
            sign = "+" if rect["delta_minutes"] > 0 else ""
            new_msgs.append(_add_msg(
                db, conv, "assistant",
                f"The past checks didn't line up, so I re-ran them against slightly "
                f"different birth times — {nb.hour:02d}:{nb.minute:02d} "
                f"({sign}{rect['delta_minutes']} min) fits your history much better. "
                "I've adjusted the chart to that time. Let's re-verify quickly."))
            if _ensure_events(db, profile, chart_facts(profile)) < 3:
                new_msgs.append(_mark_insufficient(db, conv, profile))
                return
            ev = _next_pending_event(db, conv, profile)
            if ev:
                _ask_event(db, conv, ev, first=False)
            return
        conv.state = "rectify"
    else:
        conv.state = "open"
    closing = outcome["label"]
    if outcome["state"] == "calibrated":
        closing += " With that grounding done — what's on your mind?"
    elif outcome["state"] == "partial":
        closing += (" Two out of three lined up, which is a reasonable working basis. "
                    "I'll keep a light caution flag on timing — what would you like to look at?")
    new_msgs.append(_add_msg(db, conv, "assistant", closing))


def _open_turn(db, conv, profile, facts, birth, text) -> list[Message]:
    t = text.lower()

    # chart request — always allowed
    if CHART_PAT.search(t) and ("show" in t or "chart" in t or "kundli" in t or "see" in t or detect_varga(t)):
        varga = detect_varga(t) or "D1"
        data = facts["vargas"].get(varga)
        if not data:
            _add_msg(db, conv, "assistant", f"I couldn't compute the {varga} chart for this birth data.")
            return conv.messages[-2:]
        _add_msg(db, conv, "assistant",
                 f"Here's your {varga} chart — {facts['lagna']['sign_name']} lagna in D1. "
                 f"Anything you'd like me to read into it?",
                 kind="chart", meta={"varga": varga, "chart": data})
        return conv.messages[-2:]

    # why / reasoning
    if WHY_PAT.search(t) and conv.messages and len(conv.messages) >= 2:
        for m in reversed(conv.messages[:-1]):
            if m.role == "assistant" and m.meta_json:
                meta = json.loads(m.meta_json)
                if "analysis" in meta:
                    a = meta["analysis"]
                    pillar_line = ", ".join(
                        f"{k.replace('_', ' ')}: {v}" for k, v in a["pillars"].items())
                    ev = list(dict.fromkeys(a["calculation_evidence_ids"]))
                    pretty = (f"Pillars — {pillar_line}.\n{a['convergence']}.\n\n"
                              "Evidence:\n- " + "\n- ".join(ev[:12]))
                    _add_msg(db, conv, "assistant", pretty, kind="analysis", meta=a)
                    return conv.messages[-2:]
        _add_msg(db, conv, "assistant",
                 "There's nothing recent with a reasoning trail attached. Ask me something "
                 "about your chart and then ask me why.")
        return conv.messages[-2:]

    is_future = bool(FUTURE_PAT.search(text))
    domain = detect_domain(text)

    # ---- prediction gate: enforced in code, not the prompt ----
    if is_future and not profile.predictions_allowed:
        if profile.calibration_state == "pending":
            if _ensure_events(db, profile, facts) < 3:
                _mark_insufficient(db, conv, profile)
                return conv.messages[-2:]
            conv.state = "cal_ask"
            ev = _next_pending_event(db, conv, profile)
            if ev:
                _add_msg(db, conv, "assistant",
                         "I want to answer that properly, so let's finish checking your "
                         "chart against your past first — it takes three quick questions.")
                _ask_event(db, conv, ev, first=False)
                return conv.messages[-3:]
        if profile.calibration_state == "insufficient_history":
            _add_msg(db, conv, "assistant", INSUFFICIENT_MSG)
            return conv.messages[-2:]
        _add_msg(db, conv, "assistant",
                 "I don't want to guess at your future before the chart has earned some "
                 "trust. The earlier checks didn't line up — let's fix the birth data "
                 "first, then I'll happily look ahead with you.")
        return conv.messages[-2:]

    # future-domain question with permission → four-pillar analysis
    if is_future and domain:
        start, end = _target_window(text)
        analysis = pillars.evaluate(facts, birth, domain, start, end)
        run = engine.running_vimshottari(birth, (date.today().year, date.today().month, date.today().day))
        messages = [{"role": "user", "content": text}]
        reply, provider = providers.generate(
            messages, facts=facts, analysis=analysis,
            context_note=f"The user's calibration is '{profile.calibration_state}'. "
                         f"Current Vimshottari: {'/'.join('/'.join(r['lords']) for r in run[:2])}.")
        vr = verify.verify_response(reply, facts, {"running_dasha": run})
        if not vr["ok"]:
            reply = verify.repair_response(reply, vr["issues"])
        reply = _apply_disclaimer(reply, domain)
        _add_msg(db, conv, "assistant", reply,
                 meta={"analysis": analysis, "provider": provider})
        return conv.messages[-2:]

    # general / factual chat — allowed regardless of gate
    # a domain-flavoured analysis is itself predictive content, so it is only
    # computed when predictions are allowed (phrasing like "how's my career
    # looking?" is not caught by FUTURE_PAT)
    if domain and profile.predictions_allowed:
        start, end = _target_window(text)
        analysis = pillars.evaluate(facts, birth, domain, start, end)
    else:
        analysis = None
    run = engine.running_vimshottari(birth, (date.today().year, date.today().month, date.today().day))
    history = [{"role": m.role, "content": m.content}
               for m in conv.messages[-8:] if m.kind == "text"]
    reply, provider = providers.generate(history, facts=facts, analysis=analysis,
                                         context_note=f"Calibration state: {profile.calibration_state}. "
                                         f"Current Vimshottari: {'/'.join('/'.join(r['lords']) for r in run[:2])}.")
    vr = verify.verify_response(reply, facts, {"running_dasha": run})
    if not vr["ok"]:
        reply = verify.repair_response(reply, vr["issues"])
    reply = _apply_disclaimer(reply, domain)
    _add_msg(db, conv, "assistant", reply,
             meta={"provider": provider, **({"analysis": analysis} if analysis else {})})
    return conv.messages[-2:]
