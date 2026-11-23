"""Conversation orchestrator.

Past-event checks and birth-time refinement are optional parts of a reading.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import inspect
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..astro import career_events, classical, calibration, core, inspection, panchang, pillars, precision, preregistration, prediction, registry, report, sensitivity, transits, verify, vimshottari
from ..astro.constants import DOMAINS, DOMAIN_REMEDIES, SIGN_NAMES
from .. import geo, moonmode
from ..config import settings
from ..policy import TERMS_VERSION
from ..astro.engine import BirthInput, birth_fingerprint, engine, _ymd
from ..astro.settings import CalcSettings
from ..db import (
    BirthProfile, CalibrationEvent, Conversation, Message, PredictionRecord, UserMilestone,
    _utcnow,
)
from ..llm import decider, providers
from . import career, language, memory, retrospective, safety
from . import context as dkp_context

log = logging.getLogger(__name__)

# Timing work runs alongside the topic-routing call when a domain+window guess
# is already on the table.
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jyotish-timing")

RECTIFY_STATES = ("rectify", "rectify_collect", "rectify_domain", "rectify_confirm")


# ------------------------------------------------------------------ helpers

def birth_input(profile: BirthProfile) -> BirthInput:
    try:
        calc = CalcSettings.from_preset(profile.calc_preset or "default")
    except ValueError:
        calc = CalcSettings()
    return BirthInput(
        name=profile.display_name or "", year=profile.year, month=profile.month,
        day=profile.day, hour=profile.hour, minute=profile.minute,
        second=profile.second or 0, lat=profile.latitude, lon=profile.longitude,
        tz_offset=profile.utc_offset_hours, place_label=profile.place_name,
        birth_time_precision=profile.birth_time_precision, settings=calc,
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
    """External AI is included after accepting the current service terms, unless the user
    withdrew consent for AI processing (then replies are computed-only)."""
    user = profile.user
    return bool(user is not None and user.terms_version == TERMS_VERSION and user.ai_withdrawn_at is None)


def is_minor(profile: BirthProfile, today: date | None = None) -> bool:
    age = dkp_context.age_on(profile, today or _utcnow().date())
    return age is not None and age < 18


def residence_birth(profile: BirthProfile) -> BirthInput:
    """BirthInput with the current residence as the place (for panchang and 'today'); the birthplace
    when no residence is set. Never used for the chart itself."""
    b = birth_input(profile)
    if profile.residence_lat is None or profile.residence_lon is None or not profile.residence_name:
        return b
    now = _utcnow()
    tz = geo.historical_utc_offset(profile.residence_lat, profile.residence_lon,
                                   now + timedelta(hours=b.tz_offset), b.tz_offset)
    return replace(b, lat=profile.residence_lat, lon=profile.residence_lon, tz_offset=tz,
                   place_label=profile.residence_name)


def _calibrated(profile: BirthProfile) -> bool:
    """Lagna-sensitive layers (Shadbala, varsha chart, Lagna Sudarshana,
    Lagna-degree eclipse hits) apply only when the chart passed the
    three-check calibration — an unverified time moves the Lagna ~1 deg
    every 4 minutes."""
    return (profile.calibration_state == "calibrated"
            or (profile.calibration_state not in ("uncalibrated", "insufficient_history")
                and getattr(profile, "personal_fit", None) == "good"))


def _precision_analysis(facts, birth, domain, start, end, profile, question="", event=None, *, as_of=None):
    """Run the four pillars plus the precision filters; returns
    (analysis_for_llm, precision_result). The merged analysis keeps every
    key the existing consumers read (pillars/convergence/evidence) and
    adds a compact 'precision' block for the model."""
    # Elapsed portions of a year cannot be credited as prospective forecasts.
    today = as_of or _today_at(birth)
    if start <= today <= end:
        start = min(end, today + timedelta(days=1))
    analysis, prec = None, None
    if settings.CONVERGENCE_V2:
        analysis = _convergence_analysis(facts, birth, domain, start, end, profile,
                                         question, event)
    if analysis is None:
        natal = classical.promise(facts, domain)
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
        classical.apply(analysis, facts, birth, domain, start, end, _calibrated(profile), prec, natal)
    audit = analysis["classical"]
    spec = event or prediction.event_spec(question, domain) or {}
    event_type = spec.get("event_type")
    if event_type in career_events.RULES:
        method = career_events.qualify_windows(facts, birth, event_type, analysis["precision"]["timing_windows"],
                                               start + (end - start) // 2)
        analysis["career_event_method"] = method
        for item in [method["background_sample"], *method["windows"]]:
            rows = [[c["planet"], c["chart"], str(c["house"]), ", ".join(c["relations"])]
                    for c in item["contacts"]]
            rows += [["", "", "", "Missing " + missing] for missing in item["missing"]]
            audit["tables"].append(classical.table(
                f"{event_type.replace('_', ' ').capitalize()} checks at {item['sample']}",
                ["Active lord", "Chart", "House", "Contact"], rows))
    opening_checks = [e for e in profile.calibrations if e.calc_fingerprint == profile.calc_fingerprint]
    classical.birth_checks(audit, facts, birth, opening_checks[:3])
    if profile.milestone_search_done:
        rows = [[m.domain, str(m.year) + (f"-{m.month:02d}" if m.month else "")]
                for m in profile.milestones if m.domain and m.year]
        if rows:
            audit["tables"].append(classical.table("Reported milestones used in the birth-time search",
                                                  ["Life area", "Reported period"], rows))
    analysis["decision"] = prediction.decide(question, analysis, event, as_of=today)
    stopped = next((g for g in analysis.get("gates", []) if g["status"] == "stopped"), None)
    if stopped and stopped["detail"] not in analysis["decision"].get("reasons", []):
        analysis["decision"].setdefault("reasons", []).append(stopped["detail"])
    intent = registry.forecast_intent((analysis["decision"].get("event") or {}).get("event_type"))
    if intent:
        analysis["intent"] = {"id": intent["intent_id"], "version": intent["version"],
                              "specificity": intent["specificity"]["status"]}
        for finding in analysis["evidence"]:
            finding["intent_id"] = intent["intent_id"]
    return analysis, prec


def _convergence_analysis(facts, birth, domain, start, end, profile, question, event):
    """The gated 61-topic timing engine (CONVERGENCE_V2). Returns None when the
    question maps to no spec intent or the run fails — the legacy path then
    takes over."""
    from ..astro.convergence import backtest, runner, select
    cfg = select.for_event((event or {}).get("event_type")) or select.for_domain(domain, question)
    if cfg is None or cfg.template == "special":
        return None
    try:
        if cfg.template == "N":
            run = runner.natal_run(facts, birth, cfg)
        else:
            events = [{"year": m.year, "month": m.month, "label": m.description}
                      for m in profile.milestones if m.domain == domain and m.year]
            run = runner.timing_run(facts, birth, cfg, start, end,
                                    rule_weights=backtest.rule_weights(profile.predictions),
                                    lookback_events=events)
            from dataclasses import replace as _replace
            run = _replace(run, track_record=backtest.track_record(
                profile.predictions, domain, cfg.intent_id))
    except Exception:
        log.exception("convergence v2 run failed for %s", cfg.intent_id)
        return None
    analysis = runner.analysis_from_run(run, domain, start, end,
                                        calibrated=_calibrated(profile))
    if cfg.template != "N":
        # Finite birth-time perturbation check, kept identical to the legacy
        # path; its stability verdicts are AND-ed with the varga reliability
        # the V2 engine already computed.
        try:
            sens = sensitivity.evaluate(facts, birth, domain, start, end,
                                        _calibrated(profile))
            sens["verdict_stable"] = (sens["verdict_stable"]
                                      and analysis["sensitivity"]["verdict_stable"])
            sens["timing_stable"] = (sens["timing_stable"]
                                     and analysis["sensitivity"]["timing_stable"])
            if not sens["timing_stable"]:
                analysis["precision"]["timing_windows"] = []
            analysis["sensitivity"] = sens
        except Exception:
            log.exception("sensitivity check failed")
    return analysis


def _save_prediction(db, profile, question, analysis, reply):
    decision = analysis["decision"]
    event = decision.get("event") or {}
    birth = birth_input(profile)
    rec = PredictionRecord(
        profile_id=profile.id, domain=analysis["domain"], question=question,
        window_start=date.fromisoformat(decision["window"]["start"]),
        window_end=date.fromisoformat(decision["window"]["end"]),
        convergence=analysis["convergence"], layer_verdicts=json.dumps(analysis["precision"]["layer_verdicts"]),
        protocol=prediction.VERSION, forecast=decision["disposition"], event_type=event.get("event_type"),
        success_criteria=decision["success_criteria"],
        snapshot_json=json.dumps({"analysis": analysis, "reply": reply, "fingerprint": profile.calc_fingerprint,
                                  "birth_input": asdict(birth)}))
    rec.registration = preregistration.make_registration(preregistration.build(
        analysis, question=question, settings_dict=birth.settings.fingerprint_dict(),
        calc_fingerprint=profile.calc_fingerprint, protocol=prediction.VERSION))
    db.add(rec)



def reading_facts(profile: BirthProfile) -> dict:
    """Chart facts for reading and display: the Moon chart (Chandra Lagna) when the birth time is unknown."""
    facts = chart_facts(profile)
    if moonmode.is_unknown(profile):
        return moonmode.chandra_facts(facts, birth_input(profile), _today_at(birth_input(profile)))
    return facts


def chart_facts(profile: BirthProfile) -> dict:
    if profile.chart_json and profile.calc_fingerprint == birth_fingerprint(birth_input(profile)):
        facts = json.loads(profile.chart_json)
        facts["houses"] = {int(k): v for k, v in facts["houses"].items()}
        return facts
    facts = engine.compute(birth_input(profile))
    profile.chart_json = json.dumps(facts)
    profile.calc_fingerprint = birth_fingerprint(birth_input(profile))
    return facts


def _add_msg(db: Session, conv: Conversation, role: str, content: str,
             kind="text", meta=None) -> Message:
    m = Message(role=role, content=content, kind=kind,
                meta_json=json.dumps(meta or {}))
    m.conversation = conv          # appends to conv.messages collection
    db.add(m)
    return m


DOMAIN_KEYWORDS = {
    "career": ["job", "career", "promotion", "promoted", "promoting", "work", "business", "profession", "salary", "boss", "interview", "transfer", "transferred", "employer", "leadership", "manager", "colleague", "naukri", "नौकरी", "काम", "company", "companies", "lead a team", "manage a team", "managing people", "line of work", "role at work", "startup", "entrepreneur", "self-employed", "office", "vyapar", "व्यापार", "hired", "fired", "resigned", "sacked", "laid off", "laid-off", "jobless"],
    "education": ["study", "studies", "studied", "exam", "education", "degree", "college", "university", "course", "admission", "graduate", "graduation", "graduating", "stream", "subject", "field of study", "padhai", "पढ़ाई", "engineering", "commerce", "science stream", "arts stream", "humanities", "mba", "phd", "masters", "bachelors", "b.tech", "btech", "neet", "jee", "upsc", "entrance"],
    "relationship": ["marriage", "marry", "married", "wedding", "relationship", "partner", "wife", "husband", "love life", "love marriage", "in love", "spouse", "engagement", "engaged", "tie the knot", "dating", "girlfriend", "boyfriend", "shaadi", "shadi", "vivah", "शादी", "विवाह", "divorce", "divorced", "separated", "separation", "breakup", "broke up", "remarried"],
    "relocation": ["move", "moved", "city", "settle", "settled", "relocate", "relocated", "relocating", "abroad", "foreign", "house shift", "shift house", "shifted", "settle abroad", "settle in", "travel", "travelled", "traveled", "videsh", "विदेश", "buy a house", "buy a home", "buy a flat", "buy property", "bought a house", "bought a home", "bought a flat", "bought property", "house purchase", "own house", "own home", "new house", "new home", "property", "moving to", "move to", "move abroad", "move out"],
    "children": ["children", "child", "childbirth", "baby", "kids", "son", "daughter", "parenthood", "creative legacy", "santan", "संतान", "pregnant", "pregnancy", "expecting", "conceive", "conception"],
    "parents": ["my parents", "my father", "my mother", "my lineage"],
    "debt": ["debt", "debts", "repay a loan", "borrowed", "lent"],
    "litigation": ["litigation", "lawsuit", "court case"],
    "finance": ["money", "wealth", "finance", "financial", "income", "loan", "debt", "invest", "investment", "savings", "stock market", "shares", "borrowed", "lent"],
    "direction": ["direction", "purpose", "path in life", "meaning of life", "meaning in life", "life purpose"],
    "health": ["health", "illness", "sick", "disease", "hospital", "hospitalised", "hospitalized", "diagnosed", "fracture", "surgery", "recovery", "wellbeing", "wellness", "medical", "accident", "injury", "injur"],
    "property": ["property", "real estate", "buy a house", "buy a home", "buy a flat", "buy a plot", "bought a house", "bought a home", "bought a flat", "bought a plot", "bought a car", "makaan", "vehicle", "a car"],
}
# Figures of speech that contain a topic keyword but are not about that topic.
_IDIOMS = re.compile(
    r"\bof course\b|\bhow does (?:this|it|that) work\b|\b(?:does|will|would|did) (?:this|it|that) work\b|"
    r"\bwork(?:s|ed)? out\b|\bmov(?:e|ing) on\b|\blet'?s move\b|\blearn about\b|\bthe meaning of\b|"
    r"\bwhat does .{0,30} mean\b|\bmeaning of (?:rahu|ketu|sun|moon|mars|mercury|jupiter|venus|saturn)\b|"
    r"\bmoved (?:me|us|him|her|them|you)\b|\bmoved by\b|\b(?:deeply|really|very|so) moved\b|"
    r"\bsettle (?:the |your |my )?(?:bill|bills|tab|account|dues|score|scores)\b|"
    r"\bfired? (?:up|questions?)\b|\bfire (?:a |the )?(?:gun|shot|missile)\b", re.I)

# panchang: the day's limbs — factual almanac, not a prediction
PANCHANG_PAT = re.compile(
    r"\b(panchang|panchanga|"
    r"(today|tomorrow|day after)'?s?\s+(tithi|nakshatra|yoga|karana|vaara)|"
    r"(tithi|nakshatra|yoga|karana)\s+(today|tomorrow|of today|of tomorrow|on)\b|"
    r"what('?s| is)( the)? (tithi|nakshatra|yoga|karana))\b", re.I)
# electional timing: a ranked list of DAYS is given only when the user asks
# for a day, a date or a muhurat ("best day to", "auspicious date for").
# "When should I marry" / "is it a good time to invest" are life-timing
# questions and go to a reading. The trailing connector keeps "have a good
# day" out.
TIMING_PAT = re.compile(
    r"(best|suitable|good|right|auspicious|favou?rable|ideal|lucky)\s+"
    r"(day|date|days|dates|muhurt\w*|muhurat\w*|mahurat\w*)\s+(to|for|of|in)\b|"
    r"muhurt|muhurat|mahurat|shubh\s+(din|tithi|date|day|samay)|auspicious\s+(day|date|time)|"
    r"which\s+(day|date)\s+(is\s+)?(best|suitable|good|right|auspicious|favou?rable)\b|"
    r"\b(on which|what|which)\s+(day|date)\s+(should|shall|can)\s+i\b", re.I)
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


def _disclaimer_shown(conv, domain) -> bool:
    note = DOMAINS.get(domain or "", {}).get("disclaimer")
    return bool(note) and any(m.role == "assistant" and note in (m.content or "") for m in conv.messages)


def _apply_disclaimer(reply: str, domain: str | None, already_shown: bool = False) -> str:
    """Strip generated boilerplate and append the domain note — once per
    conversation when `already_shown` reports an earlier reply carried it."""
    note = DOMAINS.get(domain or "", {}).get("disclaimer")
    if note:
        reply = reply.replace(note, "").strip()
        boilerplate = re.compile(
            r"preventive traditional|not (?:a substitute|medical diagnos)|"
            r"continue (?:any )?treatment prescribed", re.I)
        paragraphs = []
        for paragraph in re.split(r"\n\s*\n", reply):
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            cleaned = " ".join(s for s in sentences if not boilerplate.search(s)).strip()
            if cleaned:
                paragraphs.append(cleaned)
        reply = "\n\n".join(paragraphs)
        if already_shown:
            return reply
        return (reply + "\n\n" if reply else "") + note
    return reply


def detect_domain(text: str) -> str | None:
    """Keyword fallback for topic routing (used when the model router is
    unavailable). Figures of speech are removed first: "of course" is not the
    education keyword "course", "how does this work" is not about a job,
    "let's move on" is not a relocation."""
    t = _IDIOMS.sub(" ", text.lower().replace("’", "'"))
    # a pregnancy mention is about children even when a relative is named first
    # ("my wife is pregnant") — unless a medical anchor makes it a health
    # question, which stays out of astrological verdicts entirely
    if re.search(r"\bpregnan\w*|\bconceiv\w*|\bexpecting (?:a |our )?(?:baby|child)\b", t):
        if re.search(
                r"\b(?:surger\w+|operation|hospital\w*|diagnos\w+|disease|illness|treatment|"
                r"tumou?r|cancer|fracture|injur\w*|accident|medicin\w*|medical|complication\w*)\b", t):
            return "health"
        return "children"
    # a legal matter being transferred is litigation — either the matter is
    # the subject ("the hearing was transferred") or the object ("transferred
    # the case to another court"). A person posted somewhere ("I was
    # transferred to the district court", "transferred to the hearing team",
    # "during my trial shift") is a job change.
    obj = r"(?:case|suit|petition|hearing|matter|lawsuit)s?"
    dest = r"(?:court|bench|tribunal)"
    if (re.search(r"\b(?:suit|petition|hearing|court case|lawsuit)s?\s+"
                  r"(?:was|were|got|is|has been|had been|being)?\s*transfers?\w*\b", t)
            or re.search(rf"\b{obj}\s+(?:was|were|got|is|has been|had been|being)?\s*"
                         rf"transfers?\w*.{{0,20}}?\b{dest}\b", t)
            or re.search(rf"\btransfers?\w*.{{0,20}}?\b{obj}\b.{{0,20}}?\b{dest}\b", t)):
        return "litigation"
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
                    "D6": ["shashthamsa", "shashthamsha"], "D7": ["saptamsa"], "D2": ["hora"],
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
    out = []
    for m in conv.messages[max(0, end - 16):end]:
        if m.role not in ("user", "assistant"):
            continue
        if m.kind == "private":
            # Safety replies stay in context so "yes, I'm safe now" makes sense;
            # the user's sensitive words themselves are not forwarded.
            out.append({"role": m.role, "content": m.content if m.role == "assistant" else
                        "[The user shared something sensitive; the safety response below was given.]"})
            continue
        if m.kind == "analysis" and not json.loads(m.meta_json or "{}").get("explained"):
            continue                      # raw calculation tables from older replies
        out.append({"role": m.role, "content": m.content})
    return out


def _previous_reading(conv, profile):
    # A structured explanation or an outcome prompt can follow the reading.
    # Other intervening replies start their own conversational context.
    for m in reversed(conv.messages):
        if m.role != "assistant":
            continue
        meta = json.loads(m.meta_json or "{}")
        if m.kind in ("analysis", "private") or meta.get("followup_id"):
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
        birth = residence_birth(profile)     # today's panchang is for where the person lives
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
    conv.pending_event_id = ev.event_id
    conv.state = "cal_ask"
    # Factual lookups and repeated initialization must not append the same
    # question again. The original question remains available in history.
    for message in reversed(conv.messages):
        meta = json.loads(message.meta_json or "{}")
        if (message.role == "assistant" and meta.get("event_id") == ev.event_id
                and meta.get("fingerprint", ev.calc_fingerprint) == ev.calc_fingerprint):
            return
    prefix = ""
    if first:
        poss = _words(ev.profile)["poss"]
        prefix = (f"I’ll start with a few broad indications from {poss} chart and see what fits. "
                  "You can answer the checks or ask your own question at any point.\n\n")
    _add_msg(db, conv, "assistant", prefix + ev.chat_text,
             kind="options",
             meta={"options": CHECK_OPTIONS,
                   "event_id": ev.event_id, "fingerprint": ev.calc_fingerprint})
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
    if profile.birth_time_precision == "unknown":
        # Generated checks would be computed from a placeholder time; an
        # unknown-time chart is read from the Moon instead (moonmode).
        return 0
    existing = (db.query(CalibrationEvent)
                .filter(CalibrationEvent.profile_id == profile.id).all())
    if existing and existing[0].calc_fingerprint == profile.calc_fingerprint:
        if any(e.user_feedback for e in existing) or all(
                e.event_id.startswith(calibration.OPENING_EVENT_PREFIX) for e in existing):
            return len(existing)
    for e in existing:
        db.delete(e)
    db.flush()
    birth = birth_input(profile)
    stmts = calibration.generate_statements(facts, birth, profile.calc_fingerprint,
                                            subject=_subject(profile), today=_today_at(birth))
    if sum(1 for s in stmts if not s.get("control")) < 2:
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
    birth = birth_input(profile)
    stmts = {s["event_id"]: s for s in calibration.generate_statements(
        chart_facts(profile), birth, profile.calc_fingerprint,
        subject=_subject(profile), today=_today_at(birth))}
    for e in pending:
        s = stmts.get(e.event_id)
        if s and s["domain"] == e.domain:
            e.chat_text = s["chat_text"]
            e.predicted_event = s["predicted_event"]


QUESTIONS_INSTEAD = "Ask me a few questions instead"
_NO_EVENTS = {"none", "no", "no events", "nothing", "i don't have any", "i dont have any", "don't remember",
              "dont remember", "i don't remember", "i dont remember", "not sure", "no dates", "no idea"}


def _offer_own_events(db: Session, profile: BirthProfile) -> bool:
    """The client's own dated events are the primary opening check; offered
    once, before any generated question was answered or any event reported."""
    if profile.milestone_search_done or _complete_milestones(db, profile):
        return False
    answered = (db.query(CalibrationEvent)
                .filter(CalibrationEvent.profile_id == profile.id,
                        CalibrationEvent.user_feedback.isnot(None),
                        CalibrationEvent.user_feedback != "").count())
    return answered == 0


def _ask_own_events(db: Session, conv: Conversation, profile: BirthProfile):
    conv.state = "cal_events"
    conv.pending_event_id = ""
    poss = _words(profile)["poss"]
    _add_msg(db, conv, "assistant",
             f"To check {poss} birth time, the best way is {poss} own life events. Could you share 3–5 major "
             "events with the month and year, such as a marriage, a first job, a child's birth, a move abroad "
             "or a major education milestone? You can send them together or one at a time. "
             "If you don't have dates handy, I'll ask a few short questions instead.",
             kind="options", meta={"options": [QUESTIONS_INSTEAD, CONTINUE], "actions": _ACTIONS})


def _start_generated_checks(db: Session, conv: Conversation, profile: BirthProfile, facts: dict):
    """Fall back to the generated single-event questions, one at a time."""
    if _ensure_events(db, profile, facts) < 2:
        _mark_insufficient(db, conv, profile)
        return
    ev = _next_pending_event(db, conv, profile)
    if ev is None:
        conv.state = "open"
        _add_msg(db, conv, "assistant", "What would you like to explore?")
        return
    _ask_event(db, conv, ev, first=True)


def _settle_pending(profile: BirthProfile):
    """The opening ended without calibrating the chart."""
    if profile.calibration_state == "pending":
        profile.calibration_state = "skipped"
        profile.predictions_allowed = True


def _collect_milestones(db, conv, profile, text) -> bool:
    """Record dated events from `text`; True when the message was handled."""
    born = date(profile.year, profile.month, profile.day)
    events, problems = parse_milestones(text, born, date.today())
    room = MAX_MILESTONES - len(profile.milestones)
    added = []
    for e in events[:max(room, 0)]:
        m = UserMilestone(profile_id=profile.id, **e)
        profile.milestones.append(m)
        added.append(m)
    db.flush()
    if added:
        calibration.update_personal_fit(db, profile, chart_facts(profile), birth_input(profile))
    if added or problems:
        _ack_milestones(db, conv, profile, [m for m in added if m.domain], problems)
        return True
    return False


def _own_events_turn(db, conv, profile, facts, text, on_delta):
    """Opening state: waiting for the client's own dated events."""
    norm = _norm_reply(text)
    birth = birth_input(profile)
    if norm == _norm_reply(QUESTIONS_INSTEAD) or norm in _NO_EVENTS:
        _start_generated_checks(db, conv, profile, facts)
        return
    if norm in (_norm_reply(CONTINUE), "continue", "skip", "skip for now"):
        _settle_pending(profile)
        invite_reading(db, conv, profile)
        return
    if PANCHANG_PAT.search(text.lower()) or DAILY_PAT.search(text.lower()):
        _panchang_reply(db, conv, profile, facts, birth, text.lower())
        return
    if norm == _norm_reply(EDIT_BIRTH):
        _add_msg(db, conv, "assistant", f"Open the menu (top right) and choose \"{EDIT_BIRTH}\".")
        return
    year = _YEAR_RE.search(text)
    if (looks_like_event(text) or (year and int(year[1]) <= date.today().year
                                   and not _QUESTIONISH.search(text))) and _collect_milestones(db, conv, profile, text):
        return
    # anything else is the client's own question
    _settle_pending(profile)
    conv.state = "open"
    conv.pending_event_id = ""
    _open_turn(db, conv, profile, facts, birth, text, on_delta)


def start_conversation(db: Session, conv: Conversation, profile: BirthProfile) -> list[Message]:
    """Called once when the chat opens for a fresh profile."""
    facts = reading_facts(profile)
    lagna = facts["lagna"]
    if moonmode.is_unknown(profile):
        who = f"{_words(profile)['poss']} kundli ({profile.relation})" if _is_other(profile) else "your kundli"
        hello = (f"Namaste{'' if _is_other(profile) or not profile.display_name else ', ' + profile.display_name}. "
                 f"I've drawn up {who} as a Moon chart, because the birth time is unknown: Moon in "
                 f"{facts['planets']['Moon']['sign_name']} "
                 f"({facts['planets']['Moon']['nakshatra']['name']} nakshatra), read as Chandra Lagna. "
                 "Lagna-based details need a birth time.")
    elif _is_other(profile):
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

    if profile.calibration_state != "pending":
        conv.state = "open"
        conv.pending_event_id = ""
        if needs_reading_notice(conv, profile):
            invite_reading(db, conv, profile)
        db.commit()
        return conv.messages

    if _offer_own_events(db, profile):
        _ask_own_events(db, conv, profile)
        db.commit()
        return conv.messages

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

def _vimshottari_lookup(db, conv, profile, facts, birth, text):
    focus = language.focus_text(text)
    lord = language.named_mahadasha(focus)
    accident = language.specific_accident(focus)
    dates_requested = language.asks_dasha_dates(focus)
    sequence = not lord and language.asks_mahadasha_sequence(focus)
    reported = None
    continued = False
    if not (lord or sequence):
        previous = _previous_reading(conv, profile)
        prior = previous.get("vimshottari_lookup", {})
        followup = language.follows_dasha_lookup(focus)
        if not prior and followup and previous.get("fingerprint") == profile.calc_fingerprint:
            # Conversations from before this lookup used the model for the
            # same question. Recover the named period from that exchange.
            exchange = _conversation_history(conv)[-3:-1]
            if [m["role"] for m in exchange] == ["user", "assistant"]:
                question = exchange[0]["content"]
                if language.specific_accident(question) and (previous_lord := language.named_mahadasha(question)):
                    prior = {"lord": previous_lord, "accident": True}
        if prior.get("accident") and not followup:
            reported = language.reported_accident_window(focus, _today_at(birth))
        if (prior.get("lord") or prior.get("accident")) and (reported or followup):
            lord, accident = prior["lord"], prior["accident"]
            continued = True
    if not (sequence or continued or dates_requested and (lord or accident) or lord and accident):
        return False

    periods = inspection.vimshottari_mahadashas(facts)
    matching = [p for p in periods if p["lord"] == lord] if lord else periods
    if sequence and periods:
        rows = "\n".join(f"- {p['lord']} from {p['start']} to {p['end']}" for p in periods)
        lines = [f"Here are the Vimshottari mahādashas for the saved chart.\n\n{rows}"]
    elif lord and matching:
        lines = [f"The saved chart places the {lord} mahādasha from {p['start']} to {p['end']}."
                 for p in matching]
    elif lord or sequence:
        lines = ["I couldn’t find that period in the saved Vimshottari timeline."]
    else:
        lines = []
    if accident:
        if reported is None and not continued:
            reported = language.reported_accident_window(focus, _today_at(birth))
        if reported:
            start, end = (day.isoformat() for day in reported)
            rows = [p for p in facts.get("vimshottari", {}).get("periods", [])
                    if p["start"] <= end and start <= p["end"]]
            label = language.window_label(reported)
            if rows:
                clocks = ", ".join(f"{p['maha']}–{p['antar']}" for p in rows)
                lines.append(f"During {label}, the saved timeline shows {clocks} at the mahādasha and antardasha levels.")
            else:
                lines.append(f"{label} falls outside the saved Vimshottari timeline.")
            # Retrospective causation: a pandit also weighs what Saturn, Rahu
            # and Mars were transiting at the time.
            transit_bits = []
            moon_sign = facts["planets"]["Moon"]["sign"]
            for name in ("Saturn", "Mars", "Rahu"):
                try:
                    signs = {s for s, _, _ in transits.sign_intervals(birth, name, *reported)}
                except Exception:
                    continue
                for s in sorted(signs):
                    if s == moon_sign:
                        transit_bits.append(f"{name} was transiting the natal Moon sign ({SIGN_NAMES[s]})")
                    elif s == facts["lagna"]["sign"]:
                        transit_bits.append(f"{name} was transiting the lagna sign ({SIGN_NAMES[s]})")
                    elif (s - moon_sign) % 12 + 1 in (8, 12):
                        transit_bits.append(
                            f"{name} was in the {(s - moon_sign) % 12 + 1}th from the Moon ({SIGN_NAMES[s]})")
            if transit_bits:
                lines.append("Transits then: " + "; ".join(transit_bits) + ".")
        else:
            lines.append("The chart can’t establish the month of an accident. If you remember the approximate year or month and year, I can check which dasha was active.")
    _add_msg(db, conv, "assistant", "\n\n".join(lines),
             meta={"fingerprint": profile.calc_fingerprint,
                   "vimshottari_lookup": {"lord": lord, "accident": accident}})
    return True


def handle_message(db: Session, conv: Conversation, profile: BirthProfile,
                   text: str, on_delta=None) -> list[Message]:
    """`on_delta(str)` receives LLM text chunks as they stream (optional)."""
    start_len = len(conv.messages)
    msg = _add_msg(db, conv, "user", text)
    if private := safety.private_reply(text, minor=is_minor(profile)):
        msg.kind = "private"
        _add_msg(db, conv, "assistant", private, kind="private")
        db.commit()
        return conv.messages[start_len:]
    facts = reading_facts(profile)
    birth = birth_input(profile)

    if memory.is_recall(text):
        entries = memory.saved(conv.messages, profile.calc_fingerprint)
        subject = _subject(profile)
        label = f"the consultation for {subject}" if subject else "your consultation"
        lines = []
        for entry in entries[:12]:
            if entry["kind"] == "feedback":
                topic = (entry["event"] or entry["domain"]).replace("_", " ")
                status = {"agreed": "matched what you experienced", "disagreed": "didn't match your experience",
                          "mixed": "only partly matched your experience"}[entry["status"]]
                lines.append(f"- You said the reading about {topic} {status}.")
            else:
                lines.append(f"- {entry['quote']}")
        reply = (f"Here's what you've shared in {label}.\n\n" + "\n".join(lines)
                 if lines else f"I haven't picked up any key personal details in {label} yet.")
        _add_msg(db, conv, "assistant", reply)
        db.commit()
        return conv.messages[start_len:]

    # ---------- reply to a pending "did it happen?" follow-up ----------
    if conv.state == "open" and _record_followup_reply(db, conv, profile, text):
        db.commit()
        return conv.messages[start_len:]

    entries = memory.capture(text, relation=profile.relation or "self", allow_external=_external_ok(profile))
    feedback = _consultation_feedback(conv, profile, text) if conv.state == "open" else None
    if feedback:
        entries.append(feedback)
    if entries:
        msg.meta_json = json.dumps({memory.KEY: entries}, ensure_ascii=False)
        if conv.state == "open":
            added_ms = list(_milestones_from_entries(db, profile, entries))
            for milestone in added_ms:
                db.add(milestone)
            if added_ms:
                db.flush()
                calibration.update_personal_fit(db, profile, facts, birth)
    if _vimshottari_lookup(db, conv, profile, facts, birth, text):
        db.commit()
        return conv.messages[start_len:]
    # Feedback on a reading is recorded above; the model still answers it,
    # with the correction in context (see _answer_reading).

    # ---------- calibration phase ----------
    # "Please check my birth time" from Home (or open chat) re-enters the
    # optional checks after they were skipped.
    if (conv.state == "open" and profile.calibration_state in ("skipped", "uncalibrated", "pending")
            and re.search(r"check\s+(?:my\s+|the\s+|your\s+)?(?:birth\s+)?time|janm\s+samay|जन्म\s*समय", text, re.I)):
        conv.state = "cal_intro"
    if conv.state in ("cal_intro", "cal_events", "cal_ask", "cal_followup"):
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
        _maybe_ask_followup(db, conv, profile, conv.messages[start_len:])
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


_ANSWER_LEAD = re.compile(
    r"^\s*(yes|yeah|yep|haan|ha|no|nope|nahi|nahin|not really|partly|partially|not sure|"
    r"i don'?t know|don'?t remember)\b[\s,.;:!—–-]*(?:(?:but|and|though|also|actually)\b[\s,]*)?(.*)$",
    re.I | re.S)
_LEAD_MAP = {"yeah": "yes", "yep": "yes", "haan": "yes", "ha": "yes", "nope": "no", "nahi": "no",
             "nahin": "no", "not really": "no", "partly": "partial", "partially": "partial",
             "i don't know": "unknown", "i dont know": "unknown", "don't remember": "unknown",
             "dont remember": "unknown", "not sure": "unknown"}


def _split_answer(text: str) -> tuple[str | None, str]:
    """A check answer followed by free text ("yes but I want to ask about my
    marriage", "no, I was in college then") -> (answer, remainder). The
    remainder is '' when the message is only an answer (including the button
    labels and their usual wording)."""
    norm = _norm_reply(text)
    if norm in ANSWER_MAP or norm in {_norm_reply(o) for o in CHECK_OPTIONS}:
        return _classify_answer(text), ""
    m = _ANSWER_LEAD.match(text.strip().replace("’", "'"))
    if not m:
        return None, ""
    rest = m.group(2).strip()
    # what is left after removing answer phrases ("that happened", "different time")
    residue = re.sub(r"\b(?:that|it|this)?\s*(?:" + "|".join(
        re.escape(k) for k in sorted(ANSWER_MAP, key=len, reverse=True)) + r"|different time|happened)\b",
        " ", rest.lower())
    if len(re.findall(r"\w+", residue)) < 3:
        return None, ""
    word = m.group(1).lower()
    return _LEAD_MAP.get(word, ANSWER_MAP.get(word, "yes" if word == "yes" else "no")), rest


def _finish_checks_quietly(db, conv, profile):
    """Settle the calibration state without posting the outcome message
    (the user moved on to their own question)."""
    evs = db.query(CalibrationEvent).filter(CalibrationEvent.profile_id == profile.id).all()
    outcome = calibration.calibration_outcome([
        {"user_feedback": e.user_feedback, "matched": e.matched, "event_id": e.event_id} for e in evs])
    if outcome["state"] == "uncalibrated" and profile.rectified_from:
        _restore_original_time(db, profile)
        return
    profile.calibration_state = outcome["state"]
    profile.predictions_allowed = outcome["predictions_allowed"]


_MILESTONE_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_MONTH_WORDS = {m: i for i, m in enumerate(
    ("january february march april may june july august september "
     "october november december").split(), 1)}


def _milestones_from_entries(db, profile, entries) -> list:
    """Confirmed life events the user mentions become structured facts
    (UserMilestone): they feed the look-back bundle and the birth-time check,
    and are never re-asked. A correction ("actually, it was 2018") replaces the
    earlier date for that domain instead of adding a second event."""
    existing = db.query(UserMilestone).filter_by(profile_id=profile.id).all()
    # only persisted rows may be deleted — rows created in this same call are
    # still transient and db.delete() would raise InvalidRequestError
    persisted = list(existing)
    known = {(m.domain, m.year, m.month) for m in existing}
    out = []
    for e in entries:
        if e.get("kind") != "milestone" or not e.get("domain"):
            continue
        quote = e.get("quote") or ""
        ym = _MILESTONE_YEAR.search(quote)
        if not ym:
            continue
        month = next((n for name, n in _MONTH_WORDS.items() if name in quote.lower()), None)
        key = (e["domain"], int(ym.group(1)), month)
        if e.get("correction"):
            # a correction replaces the latest stated date for that domain —
            # other confirmed events there (an earlier job change, a promotion)
            # are real history and stay
            target = next((m for m in reversed(persisted)
                           if m.domain == e["domain"] and (m.year, m.month) != (key[1], key[2])),
                          None)
            if target is not None:
                db.delete(target)
                persisted.remove(target)
                existing.remove(target)
                known.discard((target.domain, target.year, target.month))
            # rows added earlier in this same call are still transient — drop
            # the latest pending one rather than db.delete()ing it
            pending = next((r for r in reversed(out)
                            if r.domain == e["domain"] and (r.year, r.month) != (key[1], key[2])),
                           None)
            if pending is not None:
                out.remove(pending)
                existing.remove(pending)
                known.discard((pending.domain, pending.year, pending.month))
        if key in known or (e["domain"], key[1], None) in known:
            continue
        known.add(key)
        row = UserMilestone(profile_id=profile.id, domain=e["domain"],
                            description=quote[:200], year=key[1], month=month)
        existing.append(row)
        out.append(row)
    return out


def _reply_chunks(reply, size=140):
    """Emit the verified reply in sentence-sized pieces so the stream reads live
    without ever showing unchecked text."""
    start = 0
    for m in re.finditer(r"(?<=[.!?।])\s+|\n+", reply):
        if m.end() - start >= size:
            yield reply[start:m.end()]
            start = m.end()
    if start < len(reply):
        yield reply[start:]


def _calibration_turn(db, conv, profile, facts, text, on_delta):
    if conv.state == "cal_events":
        _own_events_turn(db, conv, profile, facts, text, on_delta)
        return
    ev = (db.query(CalibrationEvent)
          .filter(CalibrationEvent.event_id == conv.pending_event_id,
                  CalibrationEvent.profile_id == profile.id).first())

    # An answer that carries a question or a remark: record the answer word,
    # then let the conversation handle the rest of the message.
    if ev and conv.state == "cal_ask":
        answer, remainder = _split_answer(text)
        if answer and remainder:
            ev.user_feedback = {"yes": "confirmed", "partial": "partial",
                                "no": "rejected", "unknown": "unknown"}[answer]
            ev.matched = answer == "yes"
            db.flush()
            if _next_pending_event(db, conv, profile) is None:
                _finish_checks_quietly(db, conv, profile)
            else:
                profile.calibration_state = "skipped"
                profile.predictions_allowed = True
            conv.state = "open"
            conv.pending_event_id = ""
            _open_turn(db, conv, profile, reading_facts(profile), birth_input(profile), remainder, on_delta)
            return

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
                     kind="chart", meta={"varga": varga, "chart": moonmode.merge_markers(facts, data, varga),
                                         **({"chandra_lagna": True} if moonmode.is_unknown(profile) else {})})
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
        mon = _MONTH_RE.search(text)
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
        {"user_feedback": e.user_feedback, "matched": e.matched, "event_id": e.event_id} for e in evs])
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


def _refresh_offset(profile: BirthProfile, dt: datetime):
    """Re-derive the UTC offset for `dt` using the profile's stored time basis."""
    basis = profile.time_basis or "zone"
    if basis == "manual" and profile.utc_offset_manual is not None:
        profile.utc_offset_hours = profile.utc_offset_manual
        return
    try:
        r = geo.resolve_offset(
            profile.latitude, profile.longitude, dt, country=profile.place_country,
            state=profile.place_state, basis=basis, manual_offset=profile.utc_offset_manual,
            fold=profile.dst_fold if profile.dst_fold is not None else 0)
    except geo.NonexistentTime:
        return                      # a rectified time inside a DST gap keeps the old offset
    profile.utc_offset_hours = r["offset_hours"]
    profile.offset_source = r["source"]
    profile.tz_warnings = json.dumps(r["warnings"])
    profile.tzdb_version = r["tzdb_version"]


def _set_time(profile: BirthProfile, dt: datetime):
    profile.year, profile.month, profile.day = dt.year, dt.month, dt.day
    profile.hour, profile.minute, profile.second = dt.hour, dt.minute, dt.second
    # the date may have shifted, so re-derive the UTC offset on the stored time basis
    _refresh_offset(profile, dt)
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
                 "with an approximate year? A month helps if you remember it. "
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
_MONTH_NAME = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
               r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_MONTH_RE = re.compile(r"\b(" + _MONTH_NAME + r")\b", re.I)
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
    if "?" in t or re.search(r"\b(will|would|when|what|which|how|should|shall|want|wish|hope|plan|planning|"
                             r"thinking|tell|ask|know|help|suggest|advice|advise|explain)\b", t):
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
    options = [CHECK_NOW, CONTINUE, EDIT_BIRTH] if done >= 2 else [CONTINUE, EDIT_BIRTH]
    if profile.calibration_state == "pending":
        options.insert(0, QUESTIONS_INSTEAD)
    return options


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
        _settle_pending(profile)
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


def _asked_for_events(conv) -> bool:
    """True when the latest assistant message explicitly asked for dated
    events (after "Share life events", or a follow-up asking for more)."""
    last = next((m for m in reversed(conv.messages[:-1]) if m.role == "assistant"), None)
    return bool(last and re.search(r"Tell me 2–3 significant events|3–5 major events|One or two more|One more would make|"
                                   r"Please include the month and year|What kind of event", last.content or ""))


def _rectify_turn(db, conv, profile, facts, birth, text, on_delta=None):
    """Turn handler for a chart that failed calibration. Collects dated
    milestones for an optional birth-time check."""
    norm = _norm_reply(text)

    if norm == _norm_reply(QUESTIONS_INSTEAD) and profile.calibration_state == "pending":
        _start_generated_checks(db, conv, profile, facts)
        return

    if norm in (_norm_reply(CONTINUE), "continue", "skip", "skip for now"):
        conv.state = "open"
        conv.pending_event_id = ""
        _settle_pending(profile)
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
            _settle_pending(profile)
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

    # Parse life events only when the user is clearly answering the request
    # for them: a first-person dated event, or any dated line right after the
    # explicit "tell me 2-3 events" / "one more, please" prompt. Other free
    # text (including dated statements made in passing) goes to the
    # conversation.
    year = _YEAR_RE.search(text)
    dated_reply = (conv.state == "rectify_collect" and year and int(year[1]) <= date.today().year
                   and not _QUESTIONISH.search(text) and _asked_for_events(conv))
    if not profile.milestone_search_done and (looks_like_event(text) or dated_reply):
        if _collect_milestones(db, conv, profile, text):
            return

    conv.state = "open"
    conv.pending_event_id = ""
    _open_turn(db, conv, profile, facts, birth, text, on_delta)


def _grounding(facts, analysis, history, context_note, remembered, domain=None, birth=None, today=None):
    # Newer providers accept the user's own messages and the context note so
    # that dates the user stated are not treated as inventions.
    try:
        return providers.grounding_text(facts, analysis, messages=history,
                                        context_note=context_note, memory=list(remembered or ()),
                                        domain=domain, birth=birth, today=today)
    except TypeError:
        return providers.grounding_text(facts, analysis)


def _stated_facts(conv, profile) -> list[str]:
    return [e["quote"] for e in memory.saved(conv.messages, profile.calc_fingerprint)
            if e.get("kind") in ("personal", "milestone", "family") and e.get("quote")][:5]


_WANTS_DETAIL = re.compile(
    r"\b(detail(?:ed|s)?|in[- ]depth|elaborate|explain|reasoning|reason|why|how come|step[- ]by[- ]step|"
    r"full (?:analysis|reading|report)|complete (?:analysis|reading|report)|breakdown|calculations?|evidence|"
    r"thoroughly|everything about|show your work|how did you (?:get|arrive|calculate|compute)|proof)\b", re.I)
MAX_DEFAULT_WORDS = 130


def _last_user_text(history) -> str:
    for m in reversed(history or []):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _shorten_if_needed(reply, provider, history, facts, analysis, context_note, remembered, allow_external):
    """Replies are concise unless the user asked for detail: one rewrite pass
    when the model ran long anyway."""
    if provider == "offline" or _WANTS_DETAIL.search(_last_user_text(history)):
        return reply
    if len(reply.split()) <= MAX_DEFAULT_WORDS:
        return reply
    try:
        shorter, prov = providers.regenerate_with_issues(
            history, facts, analysis, reply,
            ["Too long. The user did not ask for detail. Rewrite in about 70 words: the direct answer first, "
             "plain everyday wording, no headings, no planet-by-planet or house-by-house walkthrough, "
             "no jargon definitions, no bullet breakdown unless they asked for options."],
            allow_external=allow_external, context_note=context_note)
    except Exception:
        log.exception("shorten pass failed")
        return reply
    if prov != "offline" and shorter and 0 < len(shorter.split()) < len(reply.split()):
        return shorter
    return reply


# Mechanical detail a gist reply should never show: counts, degrees, internal
# method/check names and karaka titles. Calculation stays in the backend; the
# client hears only the conclusion unless they ask for the reasoning.
_JARGON_SEARCH = re.compile(
    r"\b\d+\s*(?:bindus?|points?)\b|\b\d+(?:\.\d+)?\s*(?:°|degrees?)\b|"
    r"\b(?:yogakaraka|atmakaraka|amatyakaraka|darakaraka|gnatikaraka|putrakaraka|"
    r"matrukaraka|pitrukaraka|bhratrukaraka)\b|"
    r"\b(?:shadbala|ashtakavarga|sarvashtakavarga|kakshya)\b|"
    r"\b(?:vimshottari|yogini|sudarshana|ashtottari|jaimini|parashari?|varshaphal\w*)\b|"
    r"\b(?:P[1-4]|gate\s*\d+)\b", re.I)
_ORDINAL_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
                  7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh",
                  12: "twelfth"}
# A reply declining or hedging a forecast must keep that stance word for word;
# a paraphrase can flip it into a promise.
_ABSTENTION = re.compile(
    r"\bdoesn'?t (?:strongly |clearly )?promise\b|\bdoes not (?:strongly |clearly )?promise\b|"
    r"\bnot (?:clearly )?indicated\b|\bno (?:clear |strong )?indication\b|\bcannot promise\b|"
    r"\bnot (?:favou?rable|supported|promised)\b|\bunlikely\b|\bdon'?t see\b|\bdoes not see\b", re.I)


def _scrub_calc_detail(reply: str) -> str:
    """Deterministic jargon fallback when no model can rewrite: drop the
    sentences carrying counts/degrees/system names and write remaining
    ordinals as words ("10th house" -> "tenth house")."""
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", reply):
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        cleaned = " ".join(s for s in sentences if not _JARGON_SEARCH.search(s)).strip()
        if cleaned:
            paragraphs.append(cleaned)
    text = "\n\n".join(paragraphs)
    return re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b",
                  lambda m: _ORDINAL_WORDS.get(int(m.group(1)), m.group(0)), text)


def _dejargon_if_needed(reply, provider, history, facts, analysis, context_note, remembered,
                        allow_external):
    """A gist reply shows no calculation detail. One rewrite pass when the
    model leaks it anyway; sentence-drop scrub when no model is reachable."""
    if provider == "offline" or _WANTS_DETAIL.search(_last_user_text(history)):
        return reply
    if not _JARGON_SEARCH.search(reply):
        return reply
    if _ABSTENTION.search(reply):
        # a rewrite could turn "the chart doesn't promise this" into a promise;
        # scrub verbatim instead so the refusal survives word for word —
        # and if the refusal itself carried jargon, keep it rather than blank
        return _scrub_calc_detail(reply) or reply
    try:
        cleaner, prov = providers.regenerate_with_issues(
            history, facts, analysis, reply,
            ["The reply shows backend calculation detail the user never asked for. Rewrite keeping the "
             "same answer in everyday words: no bindu or point counts, no degrees, no house numbers, no "
             "method names (Vimshottari, Ashtakavarga, Sudarshana), no karaka titles (yogakaraka and the "
             "rest), no gate or pillar labels. A human astrologer would say 'Saturn is strong in your "
             "chart', not cite the measurement."],
            allow_external=allow_external, context_note=context_note,
            consultation_memory=remembered)
        if prov != "offline" and cleaner and cleaner.strip():
            return cleaner
    except Exception:
        log.exception("dejargon pass failed")
    # never blank the reply: if every sentence carried jargon, keep the original
    return _scrub_calc_detail(reply) or reply


def _generate_extras(**wanted) -> dict:
    """Optional kwargs (domain/birth/today) passed only when providers.generate accepts them."""
    try:
        params = inspect.signature(providers.generate).parameters
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in wanted.items() if k in params and v is not None}


def _generate_reply(conv, profile, facts, birth, today, history, *, analysis=None, note="",
                    routing_seconds=0, remembered=(), constrain=True, domain=None):
    """The model writes the reply; deterministic code supplies the computed
    facts and analysis and checks the result. Returns (reply, provider)."""
    if "current_vimshottari" not in facts:
        facts = {**facts, "current_vimshottari": engine.running_vimshottari(
            birth, (today.year, today.month, today.day))}
    if moonmode.is_unknown(profile):
        # Lagna, Lagna houses, Lagna vargas, arudhas, KP and bhava never reach the model.
        facts = moonmode.chandra_facts(facts, birth, today, strict=True)
        analysis, constrain = None, False
    context_note = (_context_prefix(profile)
                    + dkp_context.build(profile, today, facts, profile.milestones,
                                        stated_facts=_stated_facts(conv, profile)) + "\n"
                    + f"Calibration state: {profile.calibration_state}. "
                    "Use the supplied Vimshottari dates for period boundaries. Use the resolved event and "
                    "analysis window when supplied. Answer using the selected divisional chart when present. "
                    + note + " " + safety.context_note(_last_user_text(history), minor=is_minor(profile)))
    extra = _generate_extras(domain=domain, birth=birth, today=today)
    reply, provider = providers.generate(
        history, facts=facts, analysis=analysis, context_note=context_note,
        # Wait for verification before sending any part of a reading to the client.
        allow_external=_external_ok(profile), on_delta=None,
        routing_seconds=routing_seconds, consultation_memory=remembered, **extra)
    if constrain and analysis and analysis.get("decision") and provider != "offline":
        reply = prediction.constrain_reply(reply, analysis, facts, history)
    reply = _shorten_if_needed(reply, provider, history, facts, analysis, context_note, remembered,
                               _external_ok(profile))
    reply = _dejargon_if_needed(reply, provider, history, facts, analysis, context_note, remembered,
                                _external_ok(profile))
    if provider != "offline":
        # reject/strip degrees, signs, nakshatras, dates, durations and
        # probability wording the model was never given
        check = verify.verify_response(
            reply, facts, {"grounding_text": _grounding(facts, analysis, history, context_note, remembered,
                                                           domain, birth, today),
                           "citations_provided": False})
        if not check["ok"]:
            log.warning("verifier stripped unsupported claims: %s", check["issues"][:5])
            reply = verify.repair_response(reply, check["issues"])
    return reply, provider


def _period_outlook(db, conv, profile, facts, birth, window, *, domain=None, event=None, for_report=False,
                    narrate=True, history=None, routing_seconds=0):
    """Dasha-period outlook over a window. The computed overview always runs;
    the model narrates it as a natural gist when available, otherwise the
    computed reading is shown directly (offline mode or explicit report)."""
    result = report.period_outlook(facts, window, born=date(birth.year, birth.month, birth.day), domain=domain)
    audit = result["audit"]
    reply = result["reading"]
    if audit and not _calibrated(profile):
        reply += "\n\nThe birth-time check is inconclusive, so treat the house themes as provisional."
    if narrate and not for_report:
        today = _today_at(birth)
        label = language.window_label(window)
        long_span = language.is_long_window(window)
        gist = ("Keep it to two or three sentences — the gist of the whole span, not a period-by-period "
                "list. Name only the broadest period or timeframe in plain words." if long_span else
                "Write a natural, specific reading of the period, naming it. Two or three sentences is "
                "enough; add a little more only if it genuinely helps.")
        note = (f"The user asked about {label} ({window[0].isoformat()} to {window[1].isoformat()}). "
                f"COMPUTED OUTLOOK (the dasha periods running in that window): {result['reading']} "
                f"{gist} Do not ask the user for a time frame or what they want to explore.")
        written, provider = _generate_reply(conv, profile, facts, birth, today,
                                            history if history is not None else _conversation_history(conv),
                                            note=note, routing_seconds=routing_seconds, constrain=False,
                                            domain=domain)
        if provider != "offline" and written.strip():
            reply = written
    reply = _apply_disclaimer(reply, domain, _disclaimer_shown(conv, domain))
    meta = {
        "fingerprint": profile.calc_fingerprint,
        "requested_window": [day.isoformat() for day in window],
        **({"classical": audit} if audit else {}),
    }
    if for_report:
        meta["pending_report"] = True
    elif domain:
        meta.update(pending_domain=domain, pending_event=event)
    else:
        meta["pending_outlook"] = True
    _add_msg(db, conv, "assistant", reply, meta=meta)
    return conv.messages[-2:]


_SADE_SATI = re.compile(r"\bsa{1,2}dh?e\s+sati\b|साढ़े साती|साढ़े साती", re.I)
_SOCIAL = re.compile(r"(hi|hello|hey|namaste|thanks|thank you|ok|okay)[.! ]*", re.I)
_DETAIL = re.compile(r"\s*(why|why is that|tell me why|explain( that)?|how do you know|"
                     r"((show|give) me( the)? |more )?(details|reasoning|evidence|calculations?))[?.! ]*", re.I)
_EXPAND = re.compile(r"\b(details|reasoning|evidence|calculations?|workings?|proof|math)\b", re.I)
_EXPLAIN_NOTE = (
    "The user is asking why, or for the reasoning behind your previous answer. The ANALYSIS holds the stored "
    "computation for that answer. Explain in plain words which chart factors and checks drove the answer, "
    "what supports it and what pulls against it, and how confident the reading is. Keep it conversational — "
    "name life areas and periods, not method names or point scores. No tables, no internal "
    "IDs, no new predictions.")


def _open_turn(db, conv, profile, facts, birth, text, on_delta=None) -> list[Message]:
    # Conversations created before advisory checks may end in an old refusal.
    if profile.calibration_state == "pending":
        profile.calibration_state = "skipped"
        profile.predictions_allowed = True
    # The unverified-birth-time notice travels as message metadata (for a UI
    # banner), never as a reply of its own in front of the user's answer.
    notice = reading_note(profile) if needs_reading_notice(conv, profile) else None
    before = len(conv.messages)
    result = _open_turn_body(db, conv, profile, facts, birth, text, on_delta)
    if notice:
        reply = next((m for m in reversed(conv.messages[before:]) if m.role == "assistant"), None)
        if reply is not None:
            meta = json.loads(reply.meta_json or "{}")
            meta.update(notice=notice, **_notice_meta(profile))
            reply.meta_json = json.dumps(meta)
    return result


def _explain_previous(db, conv, profile, facts, birth, text, history, routing_seconds=0) -> bool:
    """Explain the stored computation behind the previous answer. The model
    writes the explanation; tables stay in meta.classical (shown by the UI
    only when meta.expanded, which is set for explicit detail requests)."""
    expanded = bool(_EXPAND.search(text))
    for m in reversed(conv.messages[:-1]):
        if m.role != "assistant" or not m.meta_json:
            continue
        meta = json.loads(m.meta_json)
        if m.kind == "analysis" or meta.get("followup_id"):
            continue
        if meta.get("classical") and "analysis" not in meta:
            audit = meta["classical"]
            fallback = classical.markdown(audit)
            model_analysis = {"classical": audit}
            out_meta = {"classical": audit}
        elif "analysis" in meta:
            a = meta["analysis"]
            model_analysis = a
            if a.get("classical"):
                fallback = (classical.markdown(a["classical"]) +
                            f"\n\nConfirmation: {a['precision']['confirmation']}.")
                out_meta = {"classical": a["classical"]}
            else:
                pillar_line = ", ".join(
                    f"{k.replace('_', ' ')}: {v}" for k, v in a["pillars"].items())
                ev = list(dict.fromkeys(a["calculation_evidence_ids"]))
                fallback = (f"Pillars — {pillar_line}.\n{a['convergence']}.\n"
                            f"{a.get('convergence_disclaimer') or pillars.CONVERGENCE_DISCLAIMER}\n\n"
                            "Evidence:\n- " + "\n- ".join(ev[:12]))
                settings_text = providers.settings_summary(facts)
                if settings_text:
                    fallback += "\n\n" + settings_text
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
                    fallback += "\n\n" + "\n".join(extra)
                out_meta = dict(a)
        elif "timing" in meta:
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
                parts.append(f"- {d['date']} (score {d['score']}): " + "; ".join(d["reasons"]))
            fallback = "\n".join(parts)
            model_analysis = {"timing": sug}
            out_meta = dict(meta)
        else:
            return False  # Evidence from an older, unrelated reading does not answer this question.
        reply, provider = _generate_reply(conv, profile, facts, birth, _today_at(birth), history,
                                          analysis=model_analysis, note=_EXPLAIN_NOTE,
                                          routing_seconds=routing_seconds, constrain=False)
        if provider == "offline" or not reply.strip():
            reply = fallback          # no model: the computed trail itself
        else:
            out_meta["explained"] = True
        if expanded:
            out_meta["expanded"] = True
        _add_msg(db, conv, "assistant", reply, kind="analysis", meta=out_meta)
        return True
    return False


def _open_turn_body(db, conv, profile, facts, birth, text, on_delta=None) -> list[Message]:
    t = text.lower()
    today = _today_at(birth)
    prior = _previous_reading(conv, profile)

    # Sade Sati is a transit lookup. A pending "which dates?" applies only to a
    # bare date reply or a message without another topic.
    named_sade_sati = bool(_SADE_SATI.search(t))
    pending_sade_sati = bool(prior.get("pending_sade_sati")) and not (
        detect_domain(language.focus_text(text)) or REPORT_PAT.search(t) or TIMING_PAT.search(t)
        or re.search(r"\b(?:forget|never ?mind|instead|something else|skip|leave it)\b", t))
    if named_sade_sati or pending_sade_sati:
        try:
            period = language.requested_window(t, today)
        except ValueError:
            period = None
        if not period and re.search(r"\b(?:currently|now|today|am i in|abhi)\b|अभी", t):
            period = (today, today)
        if not period and named_sade_sati:
            period = language.default_window(today)
        if period and language.is_long_window(period):
            _add_msg(db, conv, "assistant",
                     "For Sade Sati, I can check up to one year at a time. Which year should I check first?",
                     meta={"pending_sade_sati": True})
            return conv.messages[-2:]
        if period:
            start, end = period
            result = transits.scan(birth, start, end + timedelta(days=1), "Saturn")
            phases = transits.sade_sati(result, facts["planets"]["Moon"]["sign"])
            if phases:
                lines = [f"Saturn is in a traditional Sade Sati phase during {language.window_label(period)}."]
                if end != start:
                    lines.extend(f"- {row['phase'].capitalize()} phase in {row['sign']}, "
                                 f"{row['start'][:10]} to {row['end'][:10]} UTC." for row in phases)
                lines.append("This describes Saturn’s transit relative to the natal Moon.")
            else:
                lines = [f"Saturn is outside the three traditional Sade Sati signs during {language.window_label(period)}."]
            _add_msg(db, conv, "assistant", "\n\n".join(lines), meta={"sade_sati": phases, "settings": result["settings"]})
            return conv.messages[-2:]
        # a pending question without a usable date: continue as conversation

    # prashna — a yes/no question ("will i …", "kya hoga") cast for the moment
    # of asking, the classical horary instrument for questions the natal chart
    # cannot time.
    prashna = bool(re.search(
        r"\b(will i|will it|is it (?:going|possible)|kya hoga|hoga kya|kabhi hoga|"
        r"shall i|should i go|will my)\b", t))
    if prashna and detect_domain(t):
        domain = detect_domain(t)
        spec = DOMAINS.get(domain)
        # A timed question or a forecastable event still goes through the
        # normal flow; prashna covers the untimed yes/no ask.
        has_period = bool(re.search(
            r"\b(?:19|20)\d{2}\b|this (?:year|month|week)|next (?:year|month|week)|"
            r"in \d+ (?:years?|months?)|january|february|march|april|may|june|july|"
            r"august|september|october|november|december|kab\b", t))
        # Medical outcomes are never given an astrological verdict.
        if (spec and domain != "health" and not has_period
                and not prediction.event_spec(language.focus_text(text), domain)):
            now = _utcnow()
            tz = birth.tz_offset
            local = now + timedelta(hours=tz)
            pb = BirthInput(name="prashna", year=local.year, month=local.month,
                            day=local.day, hour=local.hour, minute=local.minute,
                            second=local.second, lat=birth.lat, lon=birth.lon,
                            tz_offset=tz, place_label=birth.place_label,
                            settings=birth.settings)
            pf = engine.compute(pb)
            lagna = pf["lagna"]["sign"]
            lagna_lord = pf["houses"]["1"]["lord"] if "1" in pf["houses"] else pf["houses"][1]["lord"]
            moon = pf["planets"]["Moon"]
            house = spec["houses"][0]
            lord = pf["houses"][house]["lord"]
            lord_rec = pf["planets"][lord]
            lord_house = lord_rec["house"]
            kendra = {1, 4, 7, 10}
            trikona = {1, 5, 9}
            score = 0
            notes = []
            if lord_house in kendra | trikona:
                score += 1
                notes.append(f"{lord} (lord of your {domain} house) sits in a strong "
                             f"{lord_house}th prashna house")
            elif lord_house in (6, 8, 12):
                score -= 1
                notes.append(f"{lord} (lord of your {domain} house) sits in the "
                             f"{lord_house}th prashna house, a dusthana")
            tags = lord_rec.get("dignity") or []
            if any(d in ("exalted", "own sign", "moolatrikona") for d in tags):
                score += 1
                notes.append(f"{lord} is {tags[0]} in {lord_rec['sign_name']}")
            elif "debilitated" in tags:
                score -= 1
                notes.append(f"{lord} is debilitated in {lord_rec['sign_name']}")
            if moon["house"] in kendra | trikona | {11}:
                score += 1
                notes.append(f"the prashna Moon is in the {moon['house']}th, a favourable house")
            elif moon["house"] in (6, 8, 12):
                score -= 1
                notes.append(f"the prashna Moon is in the {moon['house']}th")
            lagna_lord_rec = pf["planets"][lagna_lord]
            if lagna_lord_rec["house"] in kendra | trikona:
                score += 1
            verdict = ("leans favourable" if score >= 2
                       else "leans unfavourable" if score <= -1
                       else "is mixed — the outcome depends on effort and timing")
            lines = [f"Prashna cast for {local:%Y-%m-%d %H:%M} local ({birth.place_label}) — "
                     f"lagna {pf['lagna']['sign_name']}, Moon in {moon['sign_name']} "
                     f"(house {moon['house']}).",
                     f"The chart for this moment {verdict} on the {domain} question."]
            if notes:
                lines.append("- " + "\n- ".join(n.capitalize() for n in notes))
            lines.append("Prashna is a snapshot of the moment of asking, not a guarantee; "
                         "for a timed forecast, name a period.")
            _add_msg(db, conv, "assistant", "\n\n".join(lines),
                     meta={"prashna": {"domain": domain, "score": score,
                                       "lagna": pf["lagna"]["sign_name"]}})
            return conv.messages[-2:]

    # transit lookup — "when does Jupiter enter my 7th", "Jupiter gochar kab"
    tm = re.search(
        r"when (?:does|will|is|do)\s+(\w+)\s+(?:enter|come|move|transit|reach|go\s+into)|"
        r"(\w+)\s+(?:gochar|transit)\s+(?:kab|kab hoga|when)",
        t)
    if tm:
        pname = (tm.group(1) or tm.group(2)).title()
        if pname in ("Jupiter", "Saturn", "Rahu", "Ketu", "Mars", "Venus"):
            house_m = re.search(r"(\d+)(?:st|nd|rd|th)?\s*(?:house|bhav|bhava|from (?:the )?lagna|from (?:the )?moon)", t)
            sign_m = re.search(
                rf"\b({'|'.join(k.lower() for k in SIGN_NAMES)})\b", t)
            today = _today_at(birth)
            horizon = today + timedelta(days=366 * 15)
            rows = transits.sign_intervals(birth, pname, today, horizon)
            lines = []
            if house_m:
                h = int(house_m.group(1))
                base = facts["planets"]["Moon"]["sign"] if "moon" in house_m.group(0) else facts["lagna"]["sign"]
                wanted = (base + h - 1) % 12
                hits = [r for r in rows if r[0] == wanted]
                src = "Moon" if "moon" in house_m.group(0) else "lagna"
                for s, first, last in hits[:3]:
                    lines.append(f"{pname} is in {SIGN_NAMES[s]} (your {h}th from {src}) "
                                 f"from {first} to {last}.")
                if not lines:
                    lines.append(f"{pname} does not reach your {h}th house from {src} before {horizon}.")
            elif sign_m:
                wanted = [i for i, n in enumerate(SIGN_NAMES) if n.lower() == sign_m.group(1)]
                hits = [r for r in rows if r[0] in wanted]
                for s, first, last in hits[:3]:
                    lines.append(f"{pname} enters {SIGN_NAMES[s]} on {first} and stays until {last}.")
                if not lines:
                    lines.append(f"{pname} does not reach {sign_m.group(1).title()} before {horizon}.")
            else:
                for s, first, last in rows[:4]:
                    lines.append(f"{pname} is in {SIGN_NAMES[s]} (house "
                                 f"{(s - facts['lagna']['sign']) % 12 + 1} from lagna) "
                                 f"from {first} to {last}.")
            _add_msg(db, conv, "assistant", "\n".join(lines),
                     meta={"transit_lookup": pname})
            return conv.messages[-2:]

    if re.search(r"\b(?:current dasha|(?:which|what) dasha (?:am i in|is running)|dasha (?:am i in|kya hai)|"
                 r"meri (?:kaunsi )?dasha)\b|वर्तमान दशा|कौन सी दशा", t):
        when = today
        clock = inspection.active_dashas(birth, when)
        lines = []
        for system in ("vimshottari", "yogini", "chara"):
            rows = clock[system]
            if rows:
                latest = rows[-1]
                lords = " → ".join(latest.get("lords") or latest.get("signs") or [])
                lines.append(f"{system.capitalize()} is {lords}, from {latest['start']} to {latest['end']}.")
        reply = "\n\n".join(lines) or "The active dasha periods could not be determined for this date."
        _add_msg(db, conv, "assistant", reply, meta={"dashas": clock, "settings": birth.settings.to_dict()})
        return conv.messages[-2:]

    # chart request — always allowed
    varga = detect_varga(t)
    if language.show_chart(text, varga):
        return _show_chart(db, conv, profile, facts, varga or "D1")

    # panchang — the day's limbs; factual almanac, allowed at any gate
    if PANCHANG_PAT.search(t) or DAILY_PAT.search(t):
        _panchang_reply(db, conv, profile, facts, birth, t)
        return conv.messages[-2:]

    # One structured routing call reads the turn in context; keyword rules
    # are the fallback when no model is available.
    history = _conversation_history(conv)
    route, routing_seconds = None, 0.0
    if not _SOCIAL.fullmatch(t):
        started = time.monotonic()
        route = decider.route_turn(history, allow_external=_external_ok(profile), today=today,
                                   profile_context=_profile_brief(conv, profile, today))
        routing_seconds = time.monotonic() - started
    if route is not None and not route.understood and route.clarifying_question:
        return _clarify(db, conv, profile, facts, birth, today, history, route, routing_seconds)
    if route is not None and route.needs_chart_image and (varga or re.search(r"\b(?:chart|kundli)\b", t)):
        return _show_chart(db, conv, profile, facts, varga or "D1")

    wants_detail = bool(_DETAIL.fullmatch(t)) or bool(route is not None and route.wants_detail and len(t) <= 80)
    if wants_detail and len(conv.messages) >= 2:
        if _explain_previous(db, conv, profile, facts, birth, text, history, routing_seconds):
            return conv.messages[-2:]
        # Without a computed trail, answer conversationally using the history.

    # report — computed chart and outlook for the period selected in chat
    # (the coming twelve months when none is named). Domain outlooks are
    # abstaining "general outlook" verdicts, not predictions made to the
    # user — they stay in meta, not PredictionRecord.
    wants_report = bool(REPORT_PAT.search(t))
    pending_report = prior.get("pending_report") and not detect_domain(t)
    report_window = None
    if wants_report or pending_report:
        report_window, _note = language.resolve_window(text, today)
    if wants_report or (pending_report and report_window):
        report_window = report_window or language.default_window(today)
        if language.is_long_window(report_window):
            return _period_outlook(db, conv, profile, facts, birth, report_window, for_report=True)
        rep = report.build_report(facts, birth, calibrated=_calibrated(profile),
                                  predictions_allowed=True,
                                  subject=_subject(profile),
                                  today=today, window=report_window)
        reply = "\n\n".join(rep["reading"])
        if any(d["domain"] == "health" for d in rep["domains"]):
            reply = _apply_disclaimer(reply, "health", _disclaimer_shown(conv, "health"))
        _add_msg(db, conv, "assistant", reply, kind="report",
                 meta={"report": rep})
        return conv.messages[-2:]

    # electional timing — rank upcoming days only when a day/date/muhurat is asked for
    wants_timing = bool(TIMING_PAT.search(t)) or bool(route is not None and route.needs_muhurta)
    if wants_timing:
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
        body = _format_timing(sug, horizon, _subject(profile) or "you")
        # Auspicious-day suggestions for medical events still need the
        # disclaimer — the chart ranks days, it cannot judge the outcome.
        if activity == "health" or detect_domain(t) == "health":
            note = DOMAINS["health"].get("disclaimer")
            if note:
                body += "\n\n" + note
        _add_msg(db, conv, "assistant", body,
                 kind="timing", meta={"timing": sug})
        return conv.messages[-2:]

    domain = detect_domain(t)
    if route is not None and route.topic in DOMAINS:
        domain = route.topic
    # The role matcher runs only for explicitly listed roles or offers, or
    # while a comparison it started is waiting for an answer.
    career_reply = career.starts_match(text)
    career_data = prior.get("career_match")
    if career_reply and "career_match" not in prior:
        # Explicitly returning to career matching can resume a shortlist
        # after an unrelated topic, within this profile's conversation.
        for message in reversed(conv.messages):
            if message.role != "assistant":
                continue
            meta = json.loads(message.meta_json or "{}")
            if meta.get("fingerprint", profile.calc_fingerprint) != profile.calc_fingerprint:
                break
            if "career_match" in meta:
                career_data = meta["career_match"]
                break
    career_state = career.CareerState.restore(career_data) if career_data else None
    if career_state and not career.TIMING.search(text) and not career.fit_question(text):
        if domain in (None, "career") or (career_state.asked and "?" not in text and career.ATTEST.search(text)):
            career_reply |= career.continues_match(text, career_state)
            career_reply |= career.CHART.search(text) is not None and not varga
    if career_reply:
        context = []
        if not career_state:
            notes = memory.saved(conv.messages, profile.calc_fingerprint)
            context = [entry["quote"] for entry in notes if entry["kind"] == "personal"
                       and entry["domain"] == "career" and entry["quote"] not in text][:4]
        reply, meta = career.turn(text, career_state, facts, birth, _calibrated(profile), remembered=context)
        _add_msg(db, conv, "assistant", reply, meta={**meta, "fingerprint": profile.calc_fingerprint})
        if meta.get("career_match") and career.TIMING.search(text) and prediction.event_spec(text, "career"):
            return _answer_reading(db, conv, profile, facts, birth, text, varga, None)
        return conv.messages[-2:]

    return _answer_reading(db, conv, profile, facts, birth, text, varga, on_delta,
                           route=route, routing_seconds=routing_seconds)


def _show_chart(db, conv, profile, facts, varga):
    data = facts["vargas"].get(varga)
    if not data:
        if moonmode.is_unknown(profile):
            _add_msg(db, conv, "assistant", f"The {varga} chart needs a birth time, which isn't recorded. "
                     "I can show the Moon chart (D1 read from the Moon sign) instead.")
        else:
            _add_msg(db, conv, "assistant", f"I couldn't compute the {varga} chart for this birth data.")
        return conv.messages[-2:]
    if moonmode.is_unknown(profile):
        text = f"Here's {_words(profile)['poss']} Moon chart (Chandra Lagna {facts['lagna']['sign_name']}); the birth time is unknown."
    else:
        text = f"Here's {_words(profile)['poss']} {varga} chart — {facts['lagna']['sign_name']} lagna in D1."
    _add_msg(db, conv, "assistant", text,
             kind="chart", meta={"varga": varga, "chart": moonmode.merge_markers(facts, data, varga),
                                 **({"chandra_lagna": True} if moonmode.is_unknown(profile) else {})})
    return conv.messages[-2:]


def _profile_brief(conv, profile, today) -> str:
    age = dkp_context.age_on(profile, today)
    parts = [f"age {age} ({dkp_context.life_stage(age)})" if age is not None else "age unknown",
             f"born in {profile.place_name or 'an unknown place'}"]
    if _is_other(profile):
        parts.append(f"the chart is the user's {profile.relation}'s, not the user's")
    stated = _stated_facts(conv, profile)
    if stated:
        parts.append("stated facts: " + "; ".join(s[:120] for s in stated))
    return ", ".join(parts)


def _clarify(db, conv, profile, facts, birth, today, history, route, routing_seconds):
    """The router could not tell what the user means. The model asks one
    short question (with its best guess); no canned menu."""
    note = ("You could not tell what the user means by their latest message. Ask ONE short, natural "
            "clarifying question that names exactly what is unclear and offers your best guess when you have "
            f"one. A suggested question: \"{route.clarifying_question}\". Do not give a reading yet and do not "
            "offer a menu of topics.")
    reply, provider = _generate_reply(conv, profile, facts, birth, today, history, note=note,
                                      routing_seconds=routing_seconds, constrain=False)
    if provider == "offline" or not reply.strip():
        reply = route.clarifying_question      # written by the routing model
    _add_msg(db, conv, "assistant", reply,
             meta={"provider": provider, "fingerprint": profile.calc_fingerprint, "clarifying": True})
    return conv.messages[-2:]


_INTEREST = re.compile(r"\b(?:love|like|enjoy|passion\w*|hobby|hobbies|good at|interested in)\b", re.I)


def _turn_feedback(conv) -> list[dict]:
    last = next((m for m in reversed(conv.messages) if m.role == "user"), None)
    if last is None:
        return []
    return [e for e in json.loads(last.meta_json or "{}").get(memory.KEY, []) if e.get("kind") == "feedback"]


def _answer_reading(db, conv, profile, facts, birth, text, varga, on_delta, route=None, routing_seconds=0.0):
    t = text.lower()
    history = _conversation_history(conv)
    prior = _previous_reading(conv, profile)
    previous = prior.get("analysis", {})
    old_window = previous.get("analysis_window", {})
    dates = prior.get("requested_window") or ([old_window["start"], old_window["end"]] if old_window else None)
    prior_window = tuple(date.fromisoformat(d) for d in dates) if dates else None
    selected_prior_window = bool(prior_window and (
        previous.get("period_requested") or (not previous and prior.get("requested_window"))))
    today = _today_at(birth)
    focus = language.focus_text(text)
    # A past year inside a statement ("I married in 2015 and moved in 2019")
    # is a fact, not the period asked about.
    question = language.strip_past_statements(focus, today)
    statement_only = not question
    topic_text = question or focus
    domain = detect_domain(topic_text)
    if route is not None:
        domain = route.topic if route.topic in DOMAINS else (domain if route.topic == "continue" else None)
    general = not (domain or varga) and language.general_outlook(topic_text)
    period, window_note = (language.resolve_window(question, today, prior_window) if question else (None, None))
    if period is None and route is not None and route.window and not statement_only:
        period, window_note = route.window, None
    if general:
        window = period or language.default_window(today)
        return _period_outlook(db, conv, profile, facts, birth, window,
                               history=history, routing_seconds=routing_seconds)

    event = prediction.event_spec(topic_text, domain)
    if route is not None and route.event and domain:
        event = next(({"event_type": name, "definition": definition}
                      for dom, _, name, definition in prediction.EVENTS
                      if name == route.event and dom == domain), event)
    # A bare event label can answer a previous question, e.g. "an offer".
    if not domain and previous.get("domain"):
        event = prediction.event_spec(topic_text, previous["domain"])
        if event and not re.search(r"\b(?:can you offer|move on|offer advice)\b", focus, re.I):
            domain = previous["domain"]
        else:
            event = None

    references_reading = bool(re.search(
        r"\b(and if|in that case|what does (?:this|that|it)|tell me more|go on|and my|"
        r"elaborate|same (?:period|time)|what then|what do you mean|my current (?:role|company)|please continue|"
        r"explain (?:it|that|this)|how so|aur batao|(?:it|that|this) (?:happen|happening|likely)|"
        r"likely is (?:it|that)|within (?:my|the) same (?:team|company))\b", t))
    references_reading = references_reading or bool(re.fullmatch(
        r"(why|explain|yes please|go ahead|and then|and me|and why|yes|yeah|yep|sure|"
        r"ok(?:ay)?|please|please do|go for it|assess it|do it|start|"
        r"(?:the )?(?:first|earliest|next) (?:year|one)|haan(?: ji)?|ha)[.?! ]*", t))
    if route is not None and route.topic == "continue":
        references_reading = True
    explicit_reuse = language.prior_period_request(t)
    references_reading |= explicit_reuse is True
    factual = bool(re.search(r"\b(moon|sun|mars|mercury|venus|jupiter|saturn|rahu|ketu|lagna|"
                             r"ascendant|dasha|nakshatra|rashi|chart|kundli)\b", t))
    social = _SOCIAL.fullmatch(t)
    unclear_topic = not domain and not ((previous or prior.get("pending_domain")) and (period or references_reading))
    possible_event = domain and not event and re.search(r"\b(will|might|chance|likely|could i)\b", t)
    active_domain = previous.get("domain") or prior.get("pending_domain") or prior.get("reading_domain")
    if period and not (domain or varga or factual) and (
            prior.get("pending_outlook") or language.is_long_window(period) and not active_domain):
        return _period_outlook(db, conv, profile, facts, birth, period,
                               history=history, routing_seconds=routing_seconds)
    active_event = previous.get("decision", {}).get("event") or prior.get("pending_event") or {}
    correction = bool(settings.DECIDER_ENABLED and active_domain and language.topic_correction(t))
    reuse_period = None
    domain_only = False
    pending = None
    # Older two-stage router, used only when the structured turn router
    # was unavailable.
    if route is None and (unclear_topic or possible_event or correction) and not (
            varga or social or statement_only or (factual and not correction)):
        routing_started = time.monotonic()
        # When a domain guess and a window already exist, run the timing engine
        # while the understanding call is on the wire; the result is used only
        # if routing keeps that domain+window.
        guess_domain = domain or active_domain
        guess_window = period or (prior_window if selected_prior_window else None)
        guess_event = event or active_event or None
        if guess_domain and guess_window:
            try:
                profile.milestones; profile.predictions; profile.calibrations
                pending = (guess_domain, guess_window, guess_event,
                           _POOL.submit(_precision_analysis, facts, birth, guess_domain,
                                        *guess_window, profile, question=focus,
                                        event=guess_event))
            except Exception:
                pending = None
        legacy = providers.route_topic(history, allow_external=_external_ok(profile),
                                       prior_domain=active_domain, prior_event=active_event.get("event_type"),
                                       has_period=selected_prior_window, use_fallback=bool(unclear_topic or possible_event))
        routing_seconds += time.monotonic() - routing_started
        structured = isinstance(legacy, decider.Route)
        topic = legacy.topic if structured else legacy
        if structured:
            reuse_period = legacy.reuse_period
            references_reading |= reuse_period is True
        if topic == "continue":
            references_reading = True
        elif topic in DOMAIN_KEYWORDS:
            if structured and correction:
                domain, event = topic, None
                domain_only = True
            else:
                domain = domain or topic
        else:
            for candidate, _, event_type, definition in prediction.EVENTS:
                if topic == event_type and (domain in (None, candidate) or (structured and correction)):
                    domain = candidate
                    event = {"event_type": event_type, "definition": definition}
                    break

    # The topic router or a carried-over pending event may still have attached a
    # timing event (e.g. "graduation") to a "which stream/field suits me" question.
    if event and domain == "education" and prediction.is_field_question(focus):
        event = None
        prior = {**prior, "pending_event": None}
    # "Which career suits me" is a natal what-fits question: 10th house, its
    # lord, D10 and the Amatyakaraka — answered by the model, not the matcher.
    career_fit = (career.fit_question(topic_text) and not career.TIMING.search(text)
                  and (domain == "career" or (not domain and _INTEREST.search(t))))
    if career_fit:
        domain, event = "career", None
        varga = varga or "D10"

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
    if period and not domain and not selected and not factual and period[1] >= today:
        # A future period with no topic: an outlook of that period.
        return _period_outlook(db, conv, profile, facts, birth, period,
                               history=history, routing_seconds=routing_seconds)
    same_topic = domain and domain == previous.get("domain")
    if not event and not domain_only and same_topic and continuing and not prediction.is_field_question(focus) and not re.search(r"\b(?:instead|actually|not|generally)\b", t):
        event = previous.get("decision", {}).get("event")
    keep_period = same_topic or references_reading or (not previous and prior.get("requested_window"))
    if explicit_reuse is not None:
        keep_period = explicit_reuse
    elif reuse_period is False:
        keep_period = False
    inherited_period = prior_window if keep_period and selected_prior_window else None
    window = period or inherited_period
    if domain and window and language.is_long_window(window):
        return _period_outlook(db, conv, profile, facts, birth, window, domain=domain, event=event)
    analysis = None
    wants_forecast = bool(re.search(
        r"\b(will|when|predict|prediction|forecast|outlook|future|coming|next|likely|soon|chances?|kab)\b",
        topic_text, re.I)
        or (event and not re.search(r"\b(considering|thinking about|discuss|explore)\b", focus, re.I)))
    if statement_only or (route is not None and route.is_statement and not event):
        wants_forecast = False
    if career_fit or (domain == "education" and prediction.is_field_question(focus)):
        wants_forecast = False
    tense = (route.tense if route is not None and route.tense else decider.detect_tense(topic_text))
    # A past question is matched to periods already lived; an untimed one is
    # a natal reading. Neither gets a forecast window.
    if tense == "past" and domain and period is None:
        wants_forecast = False
    elif tense == "natal" and period is None and not event:
        wants_forecast = False
    # A past statement or question can still name when it happened — that date
    # is grounding for the reading, not a forecast window.
    ground_window_only = False
    if domain and period is None and (tense == "past" or statement_only):
        ground_window_only = True
        window = language.resolve_window(focus, today, prior_window)[0] or window
    # No period named: read the coming twelve months and say so, instead of
    # asking the user for a time frame.
    default_used = bool(domain and window is None and wants_forecast)
    if default_used:
        window = language.default_window(today)
    moon_mode = moonmode.is_unknown(profile)
    # The core engine answers fresh forecast questions with a card. Follow-ups
    # ("why", clarifications, feedback, statements) and "second opinion" stay on
    # the legacy path. Moon mode is fine: core reads from the Moon sign itself.
    if (settings.ENGINE == "core" and domain and not is_minor(profile)
            and (wants_forecast or (event and tense == "future"))
            and not references_reading and not statement_only
            and not (route and (route.is_feedback or route.clarifying_question))
            and not re.search(r"second opinion", t)):
        card_msgs = _core_card_turn(db, conv, profile, facts, birth, domain, event,
                                    window, tense, focus, history, today, on_delta,
                                    routing_seconds=routing_seconds, asked_window=period)
        if card_msgs is not None:
            return card_msgs
    if (domain and window is not None and not moon_mode and not ground_window_only
            and (not selected or event or period or default_used)):
        # An accepted domain-only correction must survive the engine's event
        # inference even if the original message names the rejected event.
        question_text = f"{domain} outlook" if domain_only else focus
        if (pending is not None and domain == pending[0] and window == pending[1]
                and (event or {}).get("event_type") == (pending[2] or {}).get("event_type")):
            try:
                analysis, _prec = pending[3].result()
            except Exception:
                log.exception("speculative analysis failed; recomputing")
                analysis, _prec = _precision_analysis(facts, birth, domain, *window, profile, question=question_text, event=event)
        else:
            analysis, _prec = _precision_analysis(facts, birth, domain, *window, profile, question=question_text, event=event)
        analysis["period_requested"] = not default_used
        if default_used:
            analysis["default_window"] = True
        career_event = (analysis["decision"].get("event") or {}).get("event_type")
        if career_event in career_events.RULES and not _is_other(profile):
            user_messages = [m["content"] for m in history if m["role"] == "user"]
            if stage := career_events.reported_stage(career_event, user_messages):
                analysis["career_context"] = {"stage": stage, "source": "user_reported"}
    career_audit = None
    notes = []
    if career_fit and not moon_mode:
        reading, career_audit = career._chart_reading(facts, birth, _calibrated(profile))
        notes.append("The user asks which kind of work suits them. COMPUTED CAREER INDICATORS: " + reading +
                     " Give the gist — the top direction or two with a short plain reason each, tied to "
                     "anything they said about their interests or background. "
                     "Do not give a timing window and do not ask which roles they are considering.")
    if selected:
        facts = {**facts, "selected_chart": selected}
    run = engine.running_vimshottari(birth, (today.year, today.month, today.day))
    lord = language.named_mahadasha(focus)
    referenced = [p for p in inspection.vimshottari_mahadashas(facts) if p["lord"] == lord] if lord else []
    # The model must ground dasha claims in the period the user asked about,
    # not in whatever is running today ("my accident in Jan 2014" ≠ current MD).
    window_periods = []
    pratyantar = []
    window_transits = {}
    domain_chart = None
    if window:
        ws, we = (d.isoformat() for d in window)
        window_periods = [p for p in facts.get("vimshottari", {}).get("periods", [])
                          if p["start"] <= we and ws <= p["end"]]
        if window_periods:
            # Pratyantar subdivisions are how a reader narrows a year to months.
            try:
                pds = vimshottari.pd_periods(
                    window_periods, window_periods[0]["start_jd"],
                    window_periods[-1]["end_jd"])
                pratyantar = [
                    {**r, "start": _ymd(r["start_jd"]),
                     "end": _ymd(r["end_jd"])}
                    for r in pds
                    if _ymd(r["start_jd"]) <= we
                    and ws <= _ymd(r["end_jd"])]
            except Exception:
                log.exception("pratyantar expansion unavailable")
        for planet in ("Jupiter", "Saturn", "Rahu", "Ketu", "Mars"):
            try:
                ivs = transits.sign_intervals(birth, planet, *window)
                window_transits[planet] = list(dict.fromkeys(
                    SIGN_NAMES[s] for s, _, _ in ivs))
            except Exception:
                log.exception("transit intervals unavailable for %s", planet)
    if domain and not selected:
        spec = DOMAINS.get(domain)
        chart = facts["vargas"].get(spec["varga"]) if spec else None
        if chart:
            vlag = chart["Lagna"]["sign"]
            domain_chart = {
                "name": spec["varga"], "lagna": SIGN_NAMES[vlag],
                "placements": {name: {"sign": SIGN_NAMES[p["sign"]],
                                      "house": (p["sign"] - vlag) % 12 + 1}
                               for name, p in chart.items()}}
    facts = {**facts, "current_vimshottari": run, "referenced_mahadashas": referenced,
             "window_vimshottari": window_periods, "window_pratyantar": pratyantar,
             "window_transits": window_transits, "domain_chart": domain_chart,
             "domain_remedy": DOMAIN_REMEDIES.get(domain or ""),
             "window_label": language.window_label(window) if window else None}
    recent_user_text = [m["content"] for m in providers._prompt_history(history) if m["role"] == "user"]
    remembered = memory.relevant(memory.saved(conv.messages, profile.calc_fingerprint), domain, focus, recent_user_text)
    # Official outcomes stay attached to their original forecasts and are
    # available for context only when the current question is about that topic.
    if domain and len(remembered) < 4:
        outcomes = (db.query(PredictionRecord)
                    .filter(PredictionRecord.profile_id == profile.id, PredictionRecord.domain == domain,
                            PredictionRecord.forecast == "event_indicated", PredictionRecord.outcome.isnot(None))
                    .order_by(PredictionRecord.outcome_at.desc()).limit(4).all())
        for rec in outcomes:
            if len(remembered) >= 4:
                break
            snapshot = json.loads(rec.snapshot_json or "{}")
            if snapshot.get("fingerprint") == profile.calc_fingerprint:
                remembered.append({"kind": "reported_forecast_outcome", "domain": domain,
                                   "event": rec.event_type, "status": rec.outcome,
                                   "event_date": rec.event_date.isoformat() if rec.event_date else None})
    about_future = wants_forecast or bool(period and period[1] >= today)
    if default_used:
        notes.append(f"No period was named, so the analysis covers the coming twelve months "
                     f"({window[0].isoformat()} to {window[1].isoformat()}). You may mention the rough "
                     "timeframe naturally. Do not ask the user for a time frame.")
    elif analysis:
        notes.append("If timing matters, you may mention the rough timeframe in plain words.")
    elif window is None and about_future:
        notes.append("No prediction period was given. Anchor the answer to the running dasha and the coming "
                     "12 months; you may mention the rough timeframe in plain words and never ask the user "
                     "to supply a time frame.")
    elif period and not analysis:
        notes.append(f"The user refers to {language.window_label(period)} "
                     f"({period[0].isoformat()} to {period[1].isoformat()}).")
    retro = None
    if tense == "past" and domain and not selected:
        retro = retrospective.build(facts, birth, profile, domain, today, remembered)
        notes.append(retro["note"])
    elif tense == "natal" and not analysis:
        notes.append("The user asks for an untimed interpretation of the chart. Do not give dates, periods or "
                     "forecast windows.")
    if window_note:
        notes.append(window_note)
    if route is not None and route.interpretation:
        notes.append(f"Understanding of the latest message (from the routing step): {route.interpretation}")
    feedback = _turn_feedback(conv)
    if feedback or (route is not None and route.is_feedback):
        status = feedback[0]["status"] if feedback else "reaction"
        notes.append(f"The user is reacting to an earlier reading ({status}). Acknowledge it briefly and honestly, "
                     "accept any fact they state about their own life as true, and revise the interpretation in "
                     "that light. Do not defend the earlier reading and do not reply with a formula like "
                     "'thanks for the feedback'.")
    if statement_only or (route is not None and route.is_statement):
        notes.append("The latest message states a fact about the user's life; take it as true and respond to it "
                     "naturally.")
    if analysis and (analysis.get("decision") or {}).get("disposition") == "event_indicated":
        reply, provider = prediction.issued_reading(analysis), "computed"
    else:
        reply, provider = _generate_reply(conv, profile, facts, birth, today, history, analysis=analysis,
                                          note=" ".join(notes), routing_seconds=routing_seconds,
                                          remembered=remembered, domain=domain)
    reply = _apply_disclaimer(reply, domain, _disclaimer_shown(conv, domain))
    if on_delta and provider != "computed":
        for chunk in _reply_chunks(reply):
            on_delta(chunk)
    if analysis:
        _save_prediction(db, profile, text, analysis, reply)
    _add_msg(db, conv, "assistant", reply,
             meta={"provider": provider, "fingerprint": profile.calc_fingerprint,
                   **({"vimshottari_lookup": {"lord": lord, "accident": False}} if referenced else {}),
                   **({"reading_domain": domain} if domain else {}),
                   **({"retrospective": retro["data"]} if retro else {}),
                   **({"analysis": analysis, "requested_window": [d.isoformat() for d in window]} if analysis else {}),
                   **({"classical": career_audit} if career_audit else {}),
                   **({"career_match": prior["career_match"], "pending_domain": "career"}
                      if domain == "career" and prior.get("career_match") else {}),
                   **({"varga": varga} if selected else {})})
    return conv.messages[-2:]


_LONG_RANGE_HOUSES = (
    "personal direction", "resources and family responsibilities", "skills and communication",
    "home and family", "learning and creative work", "daily work and practical obligations",
    "partnerships", "shared obligations and change", "higher study and travel",
    "professional responsibility", "networks and longer-term goals", "work behind the scenes and distant ties",
)


# DOMAIN/event -> core topic (backend/data/topics.json). Events that the core
# engine has no opinion on stay unmapped and fall through to the LLM path.
_CORE_EVENT_TOPIC = {
    "promotion": "promotion", "job_change": "job_change", "job_offer": "job_change",
    "business_launch": "business", "marriage": "marriage", "engagement": "marriage",
    "foreign_travel": "foreign", "foreign_settlement": "foreign",
    "property_purchase": "property", "childbirth": "children",
    "education_start": "education", "exam_result": "education",
    "debt_clearance": "wealth",
}
_CORE_DOMAIN_TOPIC = {
    "career": "career", "finance": "wealth", "relationship": "relationship",
    "education": "education", "relocation": "foreign", "property": "property",
    "children": "children", "health": "wellbeing",
}


def _core_topic_id(domain: str | None, event) -> str | None:
    etype = (event or {}).get("event_type") if isinstance(event, dict) else event
    return _CORE_EVENT_TOPIC.get(etype or "") or _CORE_DOMAIN_TOPIC.get(domain or "")


def _profile_fit(profile) -> str | None:
    return profile.personal_fit or {"calibrated": "good", "partial": "partial",
                                    "uncalibrated": "poor"}.get(profile.calibration_state or "")


def _card_consistent(reply: str, card) -> bool:
    """The phrased reply must keep the card's verdict and stay inside its dates."""
    low = reply.lower()
    if card.verdict == "not_indicated" and re.search(r"\blikely\b|\byes\b|will (?:happen|occur|be)", low):
        return False
    if card.verdict == "likely" and re.search(r"not indicated|unlikely|no strong", low):
        return False
    years = set(int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", reply))
    if years:
        allowed = set()
        for key in ("start", "end"):
            if card.range and card.range.get(key):
                allowed.update(int(card.range[key][:4]) + d for d in (-1, 0, 1))
        for c in card.candidates:
            for key in ("start", "end"):
                if c.get(key):
                    allowed.update(int(c[key][:4]) + d for d in (-1, 0, 1))
        if allowed and any(y not in allowed for y in years):
            return False
    # a month the model named must sit inside the card's range/candidates —
    # same-year drift still contradicts the card shown beside the reply
    months = {m[:3].lower() for m in _MONTH_RE.findall(reply)}
    if months:
        def _span_ok(mn: int) -> bool:
            spans = ([(card.range["start"], card.range["end"])] if card.range else []
                     ) + [(c["start"], c["end"]) for c in card.candidates
                          if c.get("start") and c.get("end")]
            for s, e in spans:
                if int(s[5:7]) <= mn <= int(e[5:7]):
                    return True
            return False
        if any(not _span_ok(_MONTHS[m]) for m in months if m in _MONTHS):
            return False
    return True


def _core_card_turn(db, conv, profile, facts, birth, domain, event, window,
                    tense, focus, history, today, on_delta, routing_seconds=0,
                    asked_window=None):
    topic_id = _core_topic_id(domain, event)
    if not topic_id:
        return None
    try:
        qt = tense if tense in ("future", "past", "natal") else "future"
        # chat windows end on the last day asked for; core.answer takes an
        # exclusive end, so a one-day span ("tomorrow") would otherwise raise
        card = core.answer(facts, birth, topic_id, question_tense=qt,
                           start=window[0] if window else None,
                           end=(window[1] + timedelta(days=1)) if window else None,
                           today=today, personal_fit=_profile_fit(profile))
    except (core.TopicError, ValueError):
        return None
    fallback = core.card_text(card)
    note = ("The analysis produced the answer card below. Phrase it in plain, warm words "
            "for the user: keep the verdict and the dates exactly as given, at most 100 words, "
            "no planet names, house numbers, jargon or new timings.\n\n" + fallback)
    reply = None
    try:
        reply, provider = providers.generate(history, facts=facts, analysis=None,
                                             context_note=note, on_delta=on_delta,
                                             allow_external=_external_ok(profile),
                                             routing_seconds=routing_seconds)
    except Exception:
        provider = "offline"
    if not reply or not _card_consistent(reply, card):
        try:
            retry, provider2 = providers.regenerate_with_issues(
                history, facts, None, reply or "",
                ["Keep the card's verdict and dates exactly; do not add new timings or jargon."],
                context_note=note, allow_external=_external_ok(profile),
                routing_seconds=routing_seconds)
            if retry and _card_consistent(retry, card):
                reply, provider = retry, provider2
        except Exception:
            pass
    if not reply or not _card_consistent(reply, card):
        reply, provider = fallback, "core"
    notes = card.details.get("notes") if isinstance(card.details, dict) else None
    meta = {"provider": provider, "fingerprint": profile.calc_fingerprint,
            "card": {"topic": card.label, "verdict": card.verdict, "window": card.window,
                     "confidence": card.confidence, "why": card.why, "action": card.action,
                     "details": "\n".join(notes) if notes else None},
            "reading_domain": domain,
            # keys follow-up turns read via _previous_reading: domain reuse,
            # period inheritance and the previous event
            "domain": domain, "decision": {"event": event}}
    # Only a window the user asked for is reused later; an inherited or
    # default span must not pull an unrelated follow-up into the old dates.
    if asked_window:
        meta["period_requested"] = True
        meta["requested_window"] = [asked_window[0].isoformat(), asked_window[1].isoformat()]
    _add_msg(db, conv, "assistant", reply, meta=meta)
    return conv.messages[-2:]


def _dasha_overview(facts: dict, span: tuple, domain=None) -> list[str]:
    """Describe the themes and show their chart contacts across the requested span."""
    periods = facts.get("vimshottari", {}).get("periods", [])
    ws, we = (d.isoformat() for d in span)
    rows = [p for p in periods if p["start"] <= we and ws <= p["end"]]
    if not rows:
        return []
    spec = DOMAINS.get(domain)
    if len(rows) > 14:
        # Use the major periods to cover the full span in a readable reply.
        rows = [{**p, "lords": [p["lord"]]} for p in inspection.vimshottari_mahadashas(facts)
                if p["start"] <= we and ws <= p["end"]]
    lines = []
    for p in rows:
        lords = p["lords"]
        planet = lords[-1]
        natal_house = facts["planets"][planet]["house"]
        theme = f"{planet} is in natal house {natal_house}, linked to {_LONG_RANGE_HOUSES[natal_house - 1]}."
        if spec:
            varga = spec["varga"]
            natal = career_events.house_contacts(facts, lords, spec["houses"], "D1")
            divisional = career_events.house_contacts(facts, lords, spec["houses"], varga)
            if natal:
                contact = natal[0]
                theme = (f"{contact['planet']} links to natal house {contact['house']}, associated with "
                         f"{_LONG_RANGE_HOUSES[contact['house'] - 1]}.")
            if divisional:
                contact = divisional[0]
                theme += f" {varga} adds a link from {contact['planet']} to house {contact['house']}."
            elif natal:
                theme += f" The corresponding house contacts in {varga} are limited."
        window = tuple(date.fromisoformat(d) for d in (max(ws, p["start"]), min(we, p["end"])))
        lines.append(f"• {'–'.join(lords)} ({language.window_label(window)}). {theme}")
    return lines


# ------------------------------------------------------------ prediction follow-ups

FOLLOWUP_OPTIONS = ["It happened", "Partly", "It didn't happen", "Outside the window", "Not sure"]
_FOLLOWUP_OUTCOME = {"it happened": "happened", "partly": "partly",
                     "it didn't happen": "did_not", "outside the window": "outside_window", "not sure": "unsure"}


def _norm_reply(text: str) -> str:
    return text.strip().lower().replace("\u2019", "'").strip(".! ")


def _consultation_feedback(conv, profile, text):
    """Associate explicit reactions with the last reading or a named event."""
    for clause, status in memory.reactions(text):
        domain = detect_domain(clause)
        event = prediction.event_spec(clause, domain) if domain else None
        for msg in reversed(conv.messages):
            if msg.role != "assistant" or msg.kind == "analysis":
                continue
            meta = memory.reading_meta(msg)
            if meta.get("fingerprint") not in (None, profile.calc_fingerprint):
                break
            analysis = meta.get("analysis") or {}
            reading_domain = analysis.get("domain") or meta.get("reading_domain")
            reading_event = (analysis.get("decision") or {}).get("event") or {}
            if reading_domain and (not domain or domain == reading_domain) and (
                    not event or event["event_type"] == reading_event.get("event_type")):
                return memory.reading_feedback(status, msg, reading_domain, reading_event.get("event_type"))
            if not event:
                break
    return None


def _session_start(conv) -> bool:
    """The current user message opens a session: no earlier user message, or
    the previous one is more than six hours old."""
    users = [m for m in conv.messages if m.role == "user"]
    if len(users) < 2:
        return True
    previous = users[-2].created_at
    return previous is not None and _utcnow() - previous > timedelta(hours=6)


def _maybe_ask_followup(db: Session, conv: Conversation, profile: BirthProfile, turn_messages=()):
    """Ask about the oldest prediction whose window has passed, once — as
    one short sentence on the reply plus meta.followup (id and answer
    options), and only when the reply is on that topic or a session starts."""
    if not profile.user or not profile.user.prediction_followups:
        return
    reply = next((m for m in reversed(list(turn_messages)) if m.role == "assistant"), None)
    if reply is None or reply.kind != "text":
        return
    rec = (db.query(PredictionRecord)
           .filter(PredictionRecord.profile_id == profile.id,
                   PredictionRecord.outcome.is_(None),
                   PredictionRecord.forecast == "event_indicated",
                   PredictionRecord.followup_asked_at.is_(None),
                   PredictionRecord.window_end < date.today())
           .order_by(PredictionRecord.id).first())
    if rec is None:
        return
    meta = json.loads(reply.meta_json or "{}")
    topic = (meta.get("reading_domain") or (meta.get("analysis") or {}).get("domain")
             or meta.get("pending_domain"))
    if topic != rec.domain and not _session_start(conv):
        return
    about = (rec.event_type or rec.domain).replace("_", " ")
    whose = f" for {_subject(profile)}" if _is_other(profile) else ""
    reply.content = (reply.content.rstrip() + "\n\n"
                     + f"One quick check: the window for your earlier {about} question{whose} "
                       f"({rec.window_start} to {rec.window_end}) has passed — did it happen?")
    meta["followup"] = {"id": rec.id, "options": list(FOLLOWUP_OPTIONS),
                        "question": rec.question[:140], "success_criteria": rec.success_criteria}
    reply.meta_json = json.dumps(meta)
    rec.followup_asked_at = _utcnow()


_FOLLOWUP_SHORT = {"yes": "happened", "yes it did": "happened", "it did": "happened", "yes it happened": "happened",
                   "no": "did_not", "nope": "did_not", "no it didn't": "did_not", "it didn't": "did_not",
                   "partly": "partly", "partially": "partly", "not sure": "unsure", "don't know": "unsure"}


def _record_followup_reply(db: Session, conv: Conversation, profile: BirthProfile,
                           text: str) -> bool:
    if not profile.user or not profile.user.prediction_followups:
        return False
    norm = _norm_reply(text)
    outcome = _FOLLOWUP_OUTCOME.get(norm)
    previous = next((m for m in reversed(conv.messages) if m.role == "assistant"), None)
    awaiting = json.loads(previous.meta_json or "{}").get("followup_date_for") if previous else None
    if outcome is None:
        # A short "yes"/"no" counts only right after the follow-up sentence.
        last = next((m for m in reversed(conv.messages[:-1]) if m.role == "assistant"), None)
        if last is not None and json.loads(last.meta_json or "{}").get("followup"):
            outcome = _FOLLOWUP_SHORT.get(norm.replace(",", ""))
    if outcome is None and not awaiting:
        return False
    query = db.query(PredictionRecord).filter(
        PredictionRecord.profile_id == profile.id, PredictionRecord.outcome.is_(None),
        PredictionRecord.followup_asked_at.isnot(None))
    if awaiting:
        query = query.filter(PredictionRecord.id == awaiting)
    rec = query.order_by(PredictionRecord.followup_asked_at.desc(), PredictionRecord.id.desc()).first()
    if rec is None:
        return False
    if awaiting and outcome is None:
        if not re.search(r"\b(?:19|20)\d{2}\b", text) or _QUESTIONISH.search(text):
            return False
        today = _today_at(birth_input(profile))
        try:
            supplied = language.requested_window(text, today)
        except ValueError:
            supplied = None
        if not supplied or supplied[0] != supplied[1] or supplied[0] > today:
            _add_msg(db, conv, "assistant", "What was the exact date? For example, 15 July 2027.",
                     meta={"followup_id": rec.id, "followup_date_for": rec.id})
            return True
        rec.event_date = supplied[0]
        outcome = "happened" if rec.window_start <= rec.event_date <= rec.window_end else "outside_window"
    elif outcome == "happened" and rec.protocol == prediction.VERSION:
        _add_msg(db, conv, "assistant", "What date did it happen? I’ll check it against the forecast window.",
                 meta={"followup_id": rec.id, "followup_date_for": rec.id})
        return True
    rec.outcome = outcome
    rec.outcome_at = _utcnow()
    thanks = {"happened": "Thank you — I've noted that it did happen.",
              "partly": "Thank you — noted as partly right.",
              "did_not": "Thank you — I've recorded that honestly as a miss.",
              "unsure": "No problem — noted as unsure.",
              "outside_window": "Recorded as outside the forecast window; it does not count as a hit."}[outcome]
    _add_msg(db, conv, "assistant", thanks)
    return True
