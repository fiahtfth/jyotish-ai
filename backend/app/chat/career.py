"""Compare user-supplied roles or explore a local occupation catalog."""
from dataclasses import asdict, dataclass, field
from fractions import Fraction
import json
from pathlib import Path
import re

from ..astro import classical, constants

CATALOG = json.loads((Path(__file__).resolve().parents[2] / "data/career_catalog.json").read_text())
ROLES = {role["title"]: role for role in CATALOG["roles"]}
ALIASES = {
    name.casefold(): title
    for title, role in ROLES.items() for name in (title, *role["aliases"])
}
MATCH_REQUEST = re.compile(
    r"\b(?:career (?:fit|options?|recommendations?|matching)|"
    r"what (?:kind of )?(?:job|career|profession|role)(?: profile)? (?:suits?|fits?|should)|"
    r"which (?:job|career|profession|role|offer)(?: profile)? (?:suits?|fits?|should|is best|is better|would|to choose)|"
    r"(?:suggest|recommend|find|help me choose) (?:a |some |my |the right )?(?:careers?|roles?|career paths?|job profiles?|jobs?)|"
    r"(?:best|suitable|right) (?:career|job profile|profession) for|"
    r"which (?:job|career|profession|role)(?: profile)? (?:will I (?:get|do|have)|am I (?:suited|best suited) for)|"
    r"what should I do for work|help me (?:find|choose|pick) (?:a|my) career)\b"
    r"|कौन\s*सी\s*(?:नौकरी|भूमिका)|(?:kaunsi|kaun si) (?:naukri|job)", re.I)
COMPARE = re.compile(r"\b(?:compar(?:e|ing)|choose(?: between)?|deciding between|versus|vs\.?|between)\b", re.I)
TIMING = re.compile(r"\b(?:when|timing|forecast|outlook|will I (?:get|receive|land|start|be promoted))\b", re.I)
CHART = re.compile(r"\b(?:chart|jyotish|astrolog\w*|kundli|d-?10)\b", re.I)
FIT = re.compile(r"\b(?:suits?|suited|fits?|right for me|best for me|cut out for|meant (?:to|for))\b", re.I)
PERIOD = re.compile(r"\b(?:19|20)\d\d\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
                    r"|\b(?:next|this|last|coming) (?:year|month|week)\b|\b(?:years?|months?|weeks?)\b", re.I)
STOP = {"skip", "none", "no preference", "no constraints", "not sure", "no shortlist", "suggest options"}
WORK_MODES = {"remote": "remote", "work from home": "remote", "hybrid": "hybrid",
              "on-site": "on-site", "onsite": "on-site", "in office": "on-site"}
ACTIVITIES = {
    "sql": r"sql|mysql|postgres(?:ql)?",
    "dashboards": r"dashboards?|power bi|tableau",
    "data analysis": r"data analy(?:sis|tics)|analy[sz](?:e|ed|ing) data|clean(?:ed|ing)? data",
    "spreadsheets": r"spreadsheets?|excel|google sheets",
    "reporting": r"reports?|reporting|kpis?",
    "machine learning": r"machine learning|train(?:ed|ing)? models?",
    "statistics": r"statistic\w*|regression models?",
    "programming": r"(?:programming|coding|python|javascript|typescript|java|c\+\+)",
    "apis": r"apis?|backend systems",
    "databases": r"databases?|database design",
    "web development": r"web development|react|html|css|(?:build|built|building) websites?",
    "software testing": r"test(?:ing)? software|test cases?|regression testing|quality assurance|qa",
    "security": r"cyber.?security|security audits?|vulnerability management",
    "troubleshooting": r"troubleshoot\w*|technical support",
    "interface design": r"interface design|ux design|ui design",
    "prototyping": r"prototyp\w*|wirefram\w*",
    "design tools": r"figma|photoshop|illustrator",
    "customer support": r"customer (?:support|service)|support tickets?",
    "coordination": r"coordina\w*|scheduling",
    "stakeholders": r"stakeholders?|gather(?:ed|ing)? requirements",
    "project planning": r"project plan\w*|project management|milestones",
    "process improvement": r"process improvement|process mapping|workflow design",
    "training delivery": r"training delivery|deliver\w* training|train(?:ed|ing)? (?:staff|employees)|workshops?",
    "instructional design": r"instructional design|design\w* (?:courses|training|curricula)|curriculum design",
    "course materials": r"course materials|e.learning|lesson materials",
    "education": r"teaching|education|teach(?:es|ing)?|taught",
    "evaluation": r"evaluat\w*(?: (?:training|learning|courses))?|learning outcomes",
    "classroom teaching": r"classroom teaching|taught (?:children|students)|teach(?:ing)? (?:children|students)",
    "financial modeling": r"financial model\w*|valuation",
    "accounting": r"accounting|bookkeeping|ledgers?",
    "budgets": r"budget\w*",
    "recruiting": r"recruit\w*|talent acquisition",
    "visual design": r"visual design|graphic design",
    "client coordination": r"client coordination|client.facing|client meetings",
    "client-facing work": r"client.facing(?: work)?|client meetings",
    "bachelor’s degree": r"bachelor(?:[’']s)?(?: degree)?|undergraduate degree|b[.]?tech|b[.]?sc|b[.]?com",
    "master’s degree": r"master(?:[’']s)? degree|m[.]?tech|m[.]?sc|mba",
    "nursing registration": r"(?:active |valid )?nurs(?:e|ing) licen[cs]e|nursing registration",
    "teaching credential": r"teaching licen[cs]e|teacher certification|b[.]?ed|teaching credential",
    "electrical qualification": r"electrician licen[cs]e|electrical certification|iti electrician",

}
DUTY_PATTERNS = {
    duty: re.compile(r"(?<!\w)(?:" + re.escape(duty) + "|" + ACTIVITIES.get(duty, re.escape(duty)) + r")(?!\w)", re.I)
    for duty in {duty for role in ROLES.values() for duty in role["duties"]} | ACTIVITIES.keys()
}
REGULATED = {"Registered nurse": "nursing registration", "Primary school teacher": "teaching credential",
             "Electrician": "electrical qualification"}
CLAUSE = re.compile(
    r"[.;!?]|\bbut\b|,?\s+and\s+(?=(?:I|they|he|she|we)\s)|"
    r",\s*(?=(?:no|without|must|only)\b)", re.I)
INLINE_FIELD = re.compile(r"(?<=[.!?;])\s+(?=(?:skills|experience|education|preferences|constraints)\s*:)", re.I)
INDIA = re.compile(r"\bIndia\b", re.I)
ATTEST = re.compile(r"\b(?:I|they|he|she|we)(?:[’']ve|[’']m| (?:have|know|use|used|work|built|build|worked|"
                    r"design|designed|managed|taught|teach|study|studied|am|help|helped|can|do))\b"
                    r"|\b(?:my|their) (?:background|experience|skills|education)\b", re.I)
PREFERENCE = re.compile(r"\b(?:prefer|enjoy|like|want|interested in|priority|would love|looking for)\b", re.I)
AVOID = re.compile(r"\b(?:avoid|less|dislike|don't like|do not like|no interest in)\b", re.I)
NEGATION = re.compile(r"\b(?:not|no|never|without|lack|cannot|can't|don't|do not|haven't|have not)\b", re.I)
FIELD = re.compile(r"^\s*(?P<label>option(?:\s+[\w-]+)?|offer(?:\s+[\w-]+)?|"
                   r"job title|title|current role|responsibilities|duties|requirements|must have|"
                   r"work mode|location|terms|options|skills|experience|education|preferences|constraints|market)\s*:\s*(?P<value>.*)$", re.I)
SPECIAL = {"main job", "current role", "stay in my current role", "current job", "stay in my current job"}


@dataclass
class Option:
    title: str
    catalog_title: str = ""
    duties: str = ""
    requirements: str = ""
    mode: str = ""
    location: str = ""
    terms: str = ""


@dataclass
class CareerState:
    options: list[Option] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    named_skills: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    background: str = ""
    mode: str = ""
    location: str = ""
    market: str = ""
    other_constraints: list[str] = field(default_factory=list)
    asked: str = ""
    clarify_title: str = ""
    chart: bool = False
    status: str = "collecting"

    @classmethod
    def restore(cls, data):
        return cls(**{**data, "options": [Option(**option) for option in data["options"]]})


def activities(text):
    return {name for name, pattern in DUTY_PATTERNS.items() if pattern.search(text)}


def resolve(title):
    clean = title.strip(" .?!\"'“”")
    key = re.sub(r"^(?:my|the) ", "", clean.casefold())
    return Option("Current role" if key in SPECIAL else clean, ALIASES.get(key, ""))


def _items(text):
    return [x.strip(" .?!\"'“”") for x in re.split(r",|\s+(?:or|and|vs\.?|versus)\s+", text, flags=re.I)
            if x.strip()]


def _known_roles(text):
    hits = []
    for alias, title in ALIASES.items():
        match = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I)
        if match:
            hits.append((match.start(), -len(alias), match.end(), title))
    result, end = [], 0
    for start, _, stop, title in sorted(hits):
        if start >= end and title not in result:
            result.append(title)
            end = stop
    return result


def _comparison(text):
    # Read candidate names from the comparison clause, never from the
    # experience or preference clauses elsewhere in the same message.
    line = text.splitlines()[0] if text.splitlines() else ""
    match = re.search(r"\b(?:compare|choose(?: between)?|deciding between|between)\s+(.+)", line, re.I)
    versus = re.match(r"(.+?)\s+(?:vs\.?|versus)\s+(.+)", line, re.I)
    if not (match or versus):
        return []
    clause = re.split(r"[.?!;]|\s+(?:I|we)\s+|\s+(?:my|their)\s+(?:skills|background|experience)\b|"
                      r"[, ]+(?:based on|for me|for my|which (?:one|role|job)|what (?:fits|suits))\b",
                      match[1] if match else line, maxsplit=1, flags=re.I)[0]
    known = _known_roles(clause)
    # Years, months and durations are periods, never roles ("compare 2026 and 2028").
    names = [n for n in _items(clause) if not PERIOD.search(n)]
    if len(names) >= 2 and all(1 <= len(n.split()) <= 8 for n in names):
        return [resolve(n) for n in names[:8]]
    return [resolve(n) for n in known[:8]] if len(known) >= 2 else []


def fit_question(text):
    """'Which career suits me' — a natal what-fits question answered by the
    model from the 10th house and D10, not by the role matcher."""
    return bool(MATCH_REQUEST.search(text) or FIT.search(text))


def starts_match(text):
    """The matcher runs only when the user lists concrete roles or offers."""
    if re.search(r"^\s*(?:options|option [\w-]+|offer [\w-]+|job title)\s*:", text, re.I | re.M):
        return True
    if not COMPARE.search(text):
        return False
    choices = _comparison(text)
    return len(choices) >= 2 and (
        any(option.catalog_title or option.title == "Current role" for option in choices)
        or bool(re.search(r"\b(?:jobs?|roles?|careers?|offers?|profession)\b", text, re.I))
    )


def continues_match(text, state):
    if starts_match(text):
        return True
    if re.search(r"\b(?:cancel career|stop comparing|start (?:the )?career matching over)\b", text, re.I):
        return True
    if FIELD.match(text):
        return True
    # Experience or likes continue the comparison only while it is waiting
    # for that answer; otherwise they are ordinary conversation.
    if state.asked and state.options and (ATTEST.search(text) or PREFERENCE.search(text) or AVOID.search(text)):
        return True
    if re.search(r"\b(?:which (?:one|option|role) (?:should|would)|which one fits|why did you rank|why this role)\b", text, re.I):
        return True
    if state.asked and text.strip().casefold().rstrip(".!?") in STOP:
        return True
    if state.asked == "option_detail" and "?" not in text and len(text) <= 400:
        return True
    if state.asked == "options" and (
            _known_roles(text) or len(_items(text)) > 1
            or re.search(r"\b(?:no options|no shortlist|open to suggestions)\b", text, re.I)):
        return True
    return (state.status == "collecting" and bool(state.asked) and "?" not in text
            and len(text) <= 300 and bool(activities(text) or _mode(text)))


def _mode(text):
    return next((value for key, value in WORK_MODES.items()
                 if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", text, re.I)), "")


def _add_signals(state, value, *, preference=False, negative=False):
    tags = activities(value)
    if preference:
        add, remove = ("avoid", "preferences") if negative else ("preferences", "avoid")
    else:
        add, remove = ("gaps", "evidence") if negative else ("evidence", "gaps")
    setattr(state, add, sorted(set(getattr(state, add)) | tags))
    setattr(state, remove, sorted(set(getattr(state, remove)) - tags))


def _intake(state, text, new_comparison):
    if new_comparison:
        state.options = new_comparison
    reply = text.strip().casefold().rstrip(".!?")
    if state.asked == "options" and (reply in STOP or re.search(r"\b(?:no (?:options|shortlist)|open to suggestions)\b", reply)):
        state.options = []
        state.asked = "evidence"
        return
    if state.asked == "option_detail" and not new_comparison and not FIELD.match(text):
        option = next((o for o in state.options if o.title == state.clarify_title), None)
        if option:
            if activities(text):
                if not ATTEST.search(text) and not PREFERENCE.search(text) and not option.duties:
                    option.duties = text[:1500]
                if ATTEST.search(text):
                    _add_signals(state, text, negative=bool(NEGATION.search(text)))
            if mode := _mode(text):
                if text.strip().casefold() in WORK_MODES or re.search(r"\b(?:option|it|role|job)\b", text, re.I):
                    option.mode = mode
    explicitly_listed = False
    option = None
    section = ""
    for line in INLINE_FIELD.sub("\n", text).splitlines():
        match = FIELD.match(line)
        if match:
            label, value = match["label"].casefold(), match["value"].strip()
            section = ""
            if not value and not (option and label in ("duties", "responsibilities", "requirements", "must have")):
                continue
            if label == "options":
                state.options = [resolve(title) for title in _items(value)[:8]]
                explicitly_listed = True
                option = None
            elif label.startswith(("option", "offer")) or label in ("job title", "title"):
                if not explicitly_listed:
                    state.options = []
                    explicitly_listed = True
                option = resolve(value)
                if label not in ("title", "job title", "option", "offer"):
                    option.title = f"{label.capitalize()} · {option.title}"
                if len(state.options) < 8:
                    state.options.append(option)
            elif option and label in ("duties", "responsibilities", "requirements", "must have", "work mode", "location", "terms"):
                section = {"responsibilities": "duties", "must have": "requirements",
                           "work mode": "mode"}.get(label, label)
                setattr(option, section, _mode(value) if section == "mode" else value[:1500])
            elif label == "current role":
                option = None
                state.background = value[:300]
                current = next((o for o in state.options if o.title == "Current role"), None)
                if current:
                    current.catalog_title = ALIASES.get(value.casefold(), "")
                    if not current.catalog_title and activities(value):
                        current.duties = value[:1500]
            elif label in ("skills", "experience", "education"):
                option = None
                negative = bool(NEGATION.search(value))
                _add_signals(state, value, negative=negative)
                if label == "skills" and not negative:
                    named = {item for item in _listed_items(value)
                             if 1 <= len(item.split()) <= 6 and len(item) >= 3 and not activities(item)}
                    state.named_skills = sorted(set(state.named_skills) | named)[:24]
                if label in ("education", "experience"):
                    state.background = value[:300]
            elif label == "preferences":
                option = None
                _add_signals(state, value, preference=True, negative=bool(AVOID.search(value)))
            elif label == "constraints":
                option = None
                state.mode = _mode(value)
                location = re.search(r"\b(?:based in|must be in|only in|location)\s+([\w .-]+?)(?:[,;]|$)", value, re.I)
                if location:
                    state.location = location[1].strip()
                if INDIA.search(value):
                    state.market = "India"
                state.other_constraints = [
                    item for item in sorted(_listed_items(value))
                    if item not in STOP and not _mode(item) and not re.search(
                        r"^(?:based in|must be in|only in|location)\b", item, re.I)
                ][:6]
            elif label == "location":
                state.location = value[:100]
            elif label == "market":
                state.market = value[:100]
            continue
        if option and section in ("duties", "requirements", "terms"):
            setattr(option, section, (getattr(option, section) + "\n" + line.strip())[:1500])
            continue
        if COMPARE.search(line) and new_comparison:
            clauses = CLAUSE.split(line)
            clauses = clauses[1:]
        else:
            clauses = CLAUSE.split(line)
        for clause in clauses:
            if INDIA.search(clause):
                state.market = "India"
            if re.search(r"\b(?:must|only|need)\b", clause, re.I) and _mode(clause) and not NEGATION.search(clause):
                state.mode = _mode(clause)
            if re.search(r"\b(?:must|need|at least|minimum|only|cannot|can't)\b", clause, re.I) and re.search(
                    r"\b(?:travel|salary|pay|lpa|shift|relocat\w*|hours)\b", clause, re.I):
                term = clause.strip().casefold()[:120]
                if term not in state.other_constraints:
                    state.other_constraints = (state.other_constraints + [term])[-6:]
            if re.search(r"\bany work mode|no (?:work mode|location) constraints?\b", clause, re.I):
                state.mode = ""
                if "location" in clause.casefold():
                    state.location = ""
            negative = bool(NEGATION.search(clause))
            if PREFERENCE.search(clause) or AVOID.search(clause):
                _add_signals(state, clause, preference=True, negative=negative or bool(AVOID.search(clause)))
            elif ATTEST.search(clause) or (state.asked == "evidence" and not starts_match(clause)):
                _add_signals(state, clause, negative=negative)
                if ATTEST.search(clause) and not negative:
                    state.background = clause.strip()[:300]
    if not state.options and state.asked == "options" and not new_comparison:
        names = _items(text)
        if len(names) > 1 and all(len(name.split()) <= 8 for name in names):
            state.options = [resolve(ALIASES.get(name.casefold(), name)) for name in names[:8]]
        else:
            state.options = [resolve(name) for name in _known_roles(text)[:8]]


def _listed_items(text):
    return {item.strip(" .-•").lower() for item in re.split(r"[,;\n]", text) if item.strip(" .-•")}


def _rank(option, state):
    role = ROLES.get(option.catalog_title, {})
    # A real job's duties take precedence. If the catalog cannot identify
    # their wording, keep the role unscored and ask for clarification.
    duties = activities(option.duties) if option.duties else set(role.get("duties", []))
    named = {item for item in state.named_skills
             if re.search(r"(?<!\w)" + re.escape(item) + r"(?!\w)", option.duties, re.I)}
    duties |= named
    evidence, preferences = set(state.evidence) | named, set(state.preferences)
    avoid, gaps = set(state.avoid), set(state.gaps)
    required = activities(option.requirements)
    unknown_requirements = [
        item for item in _listed_items(option.requirements)
        if not activities(item) or not activities(item).issubset(evidence)
    ]
    credential = REGULATED.get(option.catalog_title)
    if credential:
        required.add(credential)
        if credential not in evidence:
            unknown_requirements.append(f"local eligibility and {credential}")
    blockers, unknown = [], []
    if state.mode:
        if option.mode and option.mode != state.mode:
            blockers.append(f"{option.mode} work conflicts with your {state.mode} requirement")
        elif not option.mode:
            unknown.append(f"whether {state.mode} work is available")
    if state.location:
        location = option.location.casefold()
        if location and option.mode != "remote" and state.location.casefold() not in location:
            blockers.append(f"the stated location is {option.location}")
        elif not location and option.mode != "remote":
            unknown.append("work location")
    unverified_terms = set(state.other_constraints) - _listed_items(option.terms)
    if unverified_terms:
        unknown.append("whether the offer meets your other constraints")
    if required & gaps:
        blockers.append("requires " + ", ".join(sorted(required & gaps)))
    if unknown_requirements:
        unknown.append("requirements to verify: " + ", ".join(sorted(unknown_requirements))[:200])
    if not duties:
        unknown.append("day-to-day duties")
    matched, preferred, dislikes = duties & evidence, duties & preferences, duties & avoid
    return {
        "title": option.title, "code": role.get("code"), "india": role.get("india"),
        "duties_source": "job description" if option.duties else "occupation catalog" if role else "unknown",
        "matched": sorted(matched), "preferred": sorted(preferred), "avoid": sorted(dislikes),
        "gaps": sorted(duties & gaps), "unconfirmed": sorted(duties - evidence - gaps),
        "blockers": blockers, "unknown": unknown,
        "score": (Fraction(len(matched), len(duties) or 1),
                  len(preferred) - len(dislikes), -len(duties & gaps)),
    }


def _join(names):
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]


def _chart_reading(facts, birth, calibrated):
    grade, table = classical.promise(facts, "career")
    ruler = facts["houses"][10]["lord"]
    planet = facts["planets"][ruler]
    amk = facts["jaimini"]["karakas"].get("Amatyakaraka")
    varga = facts["vargas"].get("D10", {})
    flips, cusp = classical.cusp_audit(birth)
    themes = {"Sun": "taking responsibility and working with authority",
              "Moon": "responding to people’s changing needs",
              "Mars": "hands-on problem solving and executing under pressure",
              "Mercury": "analysis and communication", "Jupiter": "teaching and advising",
              "Venus": "design and relationship building", "Saturn": "organising and sustaining work"}
    text = (f"In a traditional career reading, {ruler}, the chart’s 10th-house ruler, is in "
            f"{planet['sign_name']} in house {planet['house']}. A theme to reflect on is {themes[ruler]}.")
    if amk and amk != ruler:
        text += f" {amk}, the Amatyakaraka, adds a theme of {themes.get(amk, 'professional responsibilities')}."
    tenth = sorted(n for n, rec in facts["planets"].items() if rec["house"] == 10)
    if tenth:
        text += (f" {_join(tenth)} sit{'s' if len(tenth) == 1 else ''} in the 10th house itself"
                 + (f", the Amatyakaraka {amk} among them" if amk in tenth else "") + ".")
    moon_sign = facts["planets"]["Moon"]["sign"]
    moon10 = (moon_sign + 9) % 12
    moon10_lord = constants.PLANET_NAMES[constants.SIGN_LORD[moon10]]
    ml = facts["planets"][moon10_lord]
    text += (f" Counted from the Moon, the 10th is {constants.SIGN_NAMES[moon10]}, ruled by {moon10_lord}, "
             f"which is in {ml['sign_name']} (house {ml['house']} from the Lagna)")
    from_moon = sorted(n for n, rec in facts["planets"].items() if (rec["sign"] - moon10) % 12 == 0)
    text += (f"; {_join(from_moon)} {'occupies' if len(from_moon) == 1 else 'occupy'} that sign." if from_moon else ".")
    d10 = {}
    if varga and "Lagna" in varga:
        d10_lagna = varga["Lagna"]["sign"]
        d10 = {"lagna": constants.SIGN_NAMES[d10_lagna]}
        text += f" In D10, the career divisional chart, the Lagna is {d10['lagna']}."
        if ruler in varga:
            vsign = varga[ruler]["sign"]
            d10["tenth_lord_sign"] = constants.SIGN_NAMES[vsign]
            d10["tenth_lord_house"] = (vsign - d10_lagna) % 12 + 1
            text += (f" The D1 10th-house ruler {ruler} is in {d10['tenth_lord_sign']} there, "
                     f"the {d10['tenth_lord_house']}th house of D10.")
    elif varga and ruler in varga:
        text += f" In D10, the career divisional chart, {ruler} is in {constants.SIGN_NAMES[varga[ruler]['sign']]}."
    if not calibrated or flips.get("D10"):
        text += " The D10 details depend on the recorded birth time."
    return text, {"tables": [table, cusp], "note": f"Traditional career indicators · {grade.lower()} support.",
                  "reading_facts": {"tenth_house_planets": tenth,
                                    "tenth_from_moon": {"sign": constants.SIGN_NAMES[moon10], "lord": moon10_lord,
                                                        "lord_sign": ml["sign_name"], "lord_house": ml["house"],
                                                        "occupants": from_moon},
                                    "d10": d10}}


def turn(text, state, facts, birth, calibrated, remembered=()):
    raw = text.casefold()
    if "cancel career" in raw or "stop comparing" in raw:
        return "We can move on. What would you like to explore?", {"career_match": None}
    restart = "career matching over" in raw
    if state is None or restart:
        state = CareerState()
        if not restart:
            for detail in reversed(remembered):
                _intake(state, detail, new_comparison=False)
    if not restart:
        _intake(state, text, _comparison(text))
    state.clarify_title = ""
    state.status = "collecting"
    state.chart |= bool(CHART.search(text))

    result = {"version": CATALOG["version"], "leader": None, "roles": []}
    options = state.options or [resolve(title) for title in ROLES]
    ranked = sorted((_rank(option, state) for option in options), key=lambda r: r["score"], reverse=True)
    eligible = [r for r in ranked if not r["blockers"] and (r["matched"] or r["preferred"])]
    if state.options:
        result["roles"] = [{k: v for k, v in r.items() if k != "score"} for r in ranked]
    else:
        result["roles"] = [{k: v for k, v in r.items() if k != "score"} for r in eligible[:3]]
    audit = None
    if not (state.evidence or state.preferences or state.options or state.asked or restart):
        state.asked = "options"
        reply = "Which roles are you considering? You can share job titles or offers, or say “suggest options” and I’ll help build a shortlist."
    elif not eligible:
        state.asked = "evidence"
        listed = [r["title"] for r in ranked if r["blockers"]]
        intro = f"{', '.join(listed)} conflict with the requirements you gave. " if listed else ""
        details = " If the job titles are broad, you can paste the duties for each option." if state.options else ""
        reply = intro + "What work have you done or enjoyed that you’d like to do more of?" + details
    else:
        lead = eligible[0]
        tied = [r for r in eligible if r["score"] == lead["score"]]
        unresolved = [r for r in ranked if not r["blockers"] and r not in eligible and "day-to-day duties" in r["unknown"]]
        if len(tied) > 1 or unresolved or lead["unknown"]:
            state.asked = "evidence"
            if unresolved:
                state.asked = "option_detail"
                state.clarify_title = unresolved[0]["title"]
                reply = f"{lead['title']} looks promising. What would you actually do in {unresolved[0]['title']}?"
            elif lead["unknown"]:
                state.asked = "option_detail"
                state.clarify_title = lead["title"]
                condition = lead["unknown"][0]
                reply = f"{lead['title']} looks promising. Can you confirm {condition.rstrip('.')} before we put it first?"
            else:
                first, second = tied[:2]
                diff = [v for v in first["unconfirmed"] + first["preferred"] if v not in second["unconfirmed"] + second["preferred"]]
                other = [v for v in second["unconfirmed"] + second["preferred"] if v not in first["unconfirmed"] + first["preferred"]]
                question = (f"Which would you rather spend more of your day doing, {diff[0]} or {other[0]}?"
                            if diff and other else "Which of these roles gives you more of the work you want to do?")
                reply = f"{first['title']} and {second['title']} are close on what you’ve shared. {question}"
        else:
            state.status = "ranked"
            state.asked = ""
            result["leader"] = lead["title"]
            reason = ("you mentioned experience with " + ", ".join(lead["matched"]) if lead["matched"]
                      else "its day-to-day work includes " + ", ".join(lead["preferred"]) + ", which you said you enjoy")
            reply = f"{lead['title']} is the strongest fit from the options we looked at. It stands out because {reason}."
            gap = next(iter(lead["gaps"] or lead["unconfirmed"]), None)
            if gap:
                reply += f" Check how much {gap} the role involves and what level the employer expects."
            else:
                reply += " Compare a typical week in the role with the work you want to do more of."
            alternatives = [r for r in eligible[1:] if r["matched"] or len(r["preferred"]) >= 2][:2]
            if alternatives:
                reply += "\n\n" + " ".join(
                    f"{r['title']} is also worth exploring for {', '.join(r['matched'] or r['preferred'])}."
                    for r in alternatives
                )
            blocked = [r for r in ranked if r["blockers"]]
            if blocked:
                example = blocked[0]
                reply += f"\n\nI’d set {example['title']} aside for now because {example['blockers'][0]}."
            if state.market == "India" and lead["india"]:
                result["india_reference"] = lead["india"]
    if state.chart and (result["leader"] or CHART.search(text)):
        reading, audit = _chart_reading(facts, birth, calibrated)
        reply += "\n\n" + reading
        state.chart = False
    return reply, {"career_match": asdict(state), "career_result": result,
                   "career_sources": {"attribution": CATALOG["attribution"], "database": CATALOG["database"],
                                      "license": CATALOG["license"]} if result["roles"] else {},
                   "pending_domain": "career",
                   **({"classical": audit} if audit else {})}
