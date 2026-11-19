"""Capture user-reported context on its source message and recall it by topic."""
import json
import re

from ..astro.constants import DOMAINS
from ..llm import providers

KEY = "consultation_memory"
_DECLARATION = re.compile(r"\b(?:i|my|we|our|he|she|they|his|her|their)\b|मैं|मेरा|मेरी|हम|मेरे|वह|उन्होंने|\b(?:mera|meri|maine|mere)\b", re.I)
_QUESTION = re.compile(
    r"^(?:[\s\"'“]*(?:can|could|will|would|should|might|did|do|does|is|are|am|was|were|"
    r"have|has|had|what|when|where|why|how|if|suppose|imagine)\b|क्या|अगर)", re.I)
_SENSITIVE = re.compile(
    r"\b(?:password|passcode|otp|one.time code|api.key|aadhaar|pan number|passport number|"
    r"bank account number|credit card number|phone number|street address)\b|"
    r"[\w.+-]+@[\w.-]+\.\w+|(?:\d[ -]?){9}\d", re.I)
_CORRECTION = re.compile(r"\b(?:actually|correction|i meant|rather|instead of|not in)\b", re.I)
_OUTCOME = re.compile(r"\b(?:prediction|forecast|reading|you (?:said|predicted|were right|were wrong)|"
                      r"that (?:happened|didn't happen|was right|was wrong|doesn't match|matched)|"
                      r"you got (?:it|that) (?:right|wrong)|that's (?:right|correct|wrong|not (?:right|correct))|"
                      r"i (?:agree|disagree))\b|आपकी भविष्यवाणी|आपने सही कहा|आपने गलत कहा|"
                      r"\baapne (?:sahi|galat) kaha\b", re.I)
_DISAGREE = re.compile(r"\b(?:wrong|incorrect|off the mark|miss(?:ed)?|did not happen|didn't happen|"
                       r"does not match|doesn't match|didn't match|i disagree|not (?:correct|right|accurate))\b"
                       r"|गलत|सही नहीं|नहीं हुआ|\bgalat\b", re.I)
_AGREE = re.compile(r"\b(?:right|correct|accurate|matched|that happened|it happened|i agree|confirmed|spot on)\b"
                    r"|सही|सच हुआ|\bsahi\b", re.I)
_MIXED = re.compile(r"\b(?:partly|partially|outside the window|different date|timing was off)\b", re.I)
_PAST = re.compile(
    r"\b(?:i|we)\s+(?:got married|married|got divorced|got engaged|separated|had (?:a baby|surgery)|"
    r"moved|relocated|graduated|finished my degree|retired|resigned|joined|"
    r"(?:got|received|accepted|lost|left|started|changed) (?:a |an |my |the )?(?:first )?"
    r"(?:job|job offer|promotion|company|business)|was promoted|bought (?:a |my |our )?(?:house|home))\b", re.I)
_CURRENT = re.compile(
    r"^\s*(?:(?:actually|correction)[:,]?\s+)?(?:i\s+(?:currently\s+)?"
    r"(?:work as|work in|live in|am based in|have experience in|have worked with|prefer "
    r"(?:remote|hybrid|on.site)|(?:am|am now) (?:a |an )?(?:student|unemployed|retired)\b)"
    r"|my (?:current role|current job|profession|work background) is)\s*\S*", re.I)
_FAMILY = re.compile(
    r"\bmy (?:mother|father|parents|sister|brother|wife|husband|spouse|partner|son|daughter|child)"
    r"(?:'s)? (?:is|are|was|were|has|have|had|works|lives|moved|retired|died|passed away|"
    r"graduated|got married|was born|started|joined)\b|"
    r"\bi have (?:one|two|three|four|\d+) (?:children|child|sons?|daughters?|siblings?)\b", re.I)
_FAMILY_MEMBER = re.compile(r"\b(?:mother|father|parents|sister|brother|wife|husband|spouse|partner|son|daughter|child|family)\b", re.I)
_HYPOTHETICAL = re.compile(r"\b(?:if i|what if|suppose|hypothetical|for example|will i|might i|planning to)\b", re.I)
KINDS = {"milestone", "personal", "family"}
MEMORY_DOMAINS = {*DOMAINS, "general", "property"}
SLOTS = {
    "role", "employer", "location", "education", "skills", "work_mode", "preference",
    "relationship", "family", "marriage", "childbirth", "relocation", "graduation",
    "job_change", "retirement", "property", "health_event", "other",
}
_CURRENT_SLOTS = {"role", "employer", "location", "work_mode", "relationship"}
_RELATIONS = {
    "mother": "mother|mom|mum|mummy|माँ|मां|माता", "father": "father|dad|papa|पिता|पापा",
    "spouse": "wife|husband|spouse|partner|पति|पत्नी",
    "son": "son|beta|बेटा", "daughter": "daughter|beti|बेटी", "brother": "brother|bhai|भाई",
    "sister": "sister|behen|बहन", "friend": "friend|dost|दोस्त",
}
_KEYWORDS = {
    "career": r"\b(?:work|job|career|skills|offer|company|employer|industry|role|promoted|promotion|retired|resigned|remote|hybrid|business)\b",
    "relationship": r"\b(?:married|marriage|engaged|divorced|separated|spouse|partner|wife|husband|wedding)\b",
    "relocation": r"\b(?:moved|relocated|live in|based in|relocation)\b",
    "children": r"\b(?:baby|son|daughter|child|children|pregnan\w*|parenthood)\b",
    "parents": r"\b(?:mother|father|parents)\b",
    "education": r"\b(?:graduat\w*|school|college|degree|student|study|exam)\b",
    "property": r"\b(?:house|home|property)\b",
    "health": r"\b(?:surgery|hospital|illness|health)\b",
}
_SLOT_PATTERNS = {
    "marriage": r"\b(?:married|engaged|divorced|separated)\b",
    "childbirth": r"\b(?:had a baby|was born)\b",
    "relocation": r"\b(?:moved|relocated)\b",
    "graduation": r"\b(?:graduated|finished my degree)\b",
    "retirement": r"\bretired\b",
    "property": r"\bbought\b",
    "health_event": r"\bsurgery\b",
    "location": r"\b(?:live in|based in)\b",
    "work_mode": r"\b(?:remote|hybrid|on.site)\b",
    "skills": r"\b(?:experience in|worked with)\b",
}
_RECALL = re.compile(r"^(?:what do you (?:remember|know) about me|what have i told you(?: about myself)?|show (?:me )?(?:my|your) (?:saved )?memor(?:y|ies))[.?! ]*$", re.I)


def is_recall(text):
    return bool(_RECALL.fullmatch(text.strip()))


def _clauses(text):
    return [part.strip() for part in re.split(
        r"[;\n]|(?<=[.!?।])\s+|,?\s+and\s+(?=(?:I|my|we|our)\s)",
        text, flags=re.I) if part.strip()]


def _declaration(clause):
    return (_DECLARATION.search(clause) and not _QUESTION.match(clause)
            and not clause.endswith("?") and not _HYPOTHETICAL.search(clause)
            and not _SENSITIVE.search(clause))


def _rule_entry(clause):
    if _FAMILY.search(clause):
        kind = "family"
    elif _PAST.search(clause):
        kind = "milestone"
    elif _CURRENT.search(clause):
        kind = "personal"
    else:
        return None
    default = {"milestone": "job_change", "personal": "role", "family": "family"}[kind]
    slot = next((s for s, pattern in _SLOT_PATTERNS.items() if re.search(pattern, clause, re.I)), default)
    fallback_domain = "career" if kind == "personal" else "general"
    domain = next((d for d, pattern in _KEYWORDS.items() if re.search(pattern, clause, re.I)), fallback_domain)
    return {"kind": kind, "domain": domain, "slot": slot, "quote": clause}


def _validated_entries(raw, clauses, relation):
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        kind, domain, slot, quote = (item.get(key) for key in ("kind", "domain", "slot", "quote"))
        if not all(isinstance(value, str) for value in (kind, domain, slot, quote)):
            continue
        quote = quote.strip()
        # Only exact excerpts from eligible user statements may become memories.
        # The model can label a fact but cannot write or rewrite it.
        if (kind not in KINDS or domain not in MEMORY_DOMAINS
                or slot not in SLOTS or not 5 <= len(quote) <= 320 or quote not in clauses):
            continue
        if relation != "self":
            subject = _RELATIONS.get(relation)
            if not subject or not re.match(
                rf"\s*(?:(?:actually|correction)[:,]?\s+)?(?:my|meri|mere|mera|मेरी|मेरे|मेरा)"
                rf"\s+(?:{subject})(?=\s|[.,!?।]|$)", quote, re.I
            ):
                continue
        elif _FAMILY.search(quote):
            kind = "family"
        entry = {"kind": kind, "domain": domain, "slot": slot, "quote": quote}
        if _CORRECTION.search(quote):
            entry["correction"] = True
        entries.append(entry)
    return entries


def capture(text, *, relation, allow_external):
    clauses = [clause for clause in _clauses(text) if _declaration(clause)
               and not (_OUTCOME.search(clause) and feedback_status(clause))]
    if not clauses:
        return []
    local = [entry for clause in clauses if (entry := _rule_entry(clause))]
    remaining = [clause for clause in clauses if not any(entry["quote"] == clause for entry in local)]
    remote = providers.consultation_memories("\n".join(remaining)[:1800], relation=relation,
                                             allow_external=allow_external) if remaining else []
    return _validated_entries(local + remote, clauses, relation)


def feedback_status(text):
    text = text.replace("’", "'")
    if not _OUTCOME.search(text):
        return None
    if _QUESTION.match(text) or text.rstrip().endswith("?") or _HYPOTHETICAL.search(text):
        return None
    agreed, disagreed = _AGREE.search(text), _DISAGREE.search(text)
    if _MIXED.search(text) or (agreed and disagreed and re.search(r"\bbut\b", text, re.I)):
        return "mixed"
    return "disagreed" if disagreed else "agreed" if agreed else None


def reactions(text):
    for clause in _clauses(text):
        if status := feedback_status(clause):
            yield clause, status


def reading_feedback(status, reading, domain, event_label=None):
    """Casual feedback is a reported reaction to a specific reading."""
    if status is None:
        return None
    return {"kind": "feedback", "domain": domain, "status": status, "reading_id": reading.id,
            "event": event_label or "", "fingerprint": reading_meta(reading).get("fingerprint")}


def reading_meta(message):
    return json.loads(message.meta_json or "{}")


def saved(messages, fingerprint):
    """Most recent first, with current facts and explicit corrections winning."""
    found, seen, superseded = [], set(), set()
    for message in reversed(messages):
        if message.role != "user" or message.meta_json in (None, "", "{}"):
            continue
        for item in reversed(reading_meta(message).get(KEY, [])):
            kind = item["kind"]
            if kind == "feedback" and item.get("fingerprint") != fingerprint:
                continue
            quote = item.get("quote", "")
            identity = (kind, quote.casefold()) if quote else (kind, item["reading_id"])
            subject = _FAMILY_MEMBER.search(quote) if kind == "family" else None
            slot = (kind, item.get("slot"), subject[0].casefold() if subject else "")
            if identity in seen or slot in superseded:
                continue
            seen.add(identity)
            if item.get("correction") or (kind == "personal" and item.get("slot") in _CURRENT_SLOTS):
                superseded.add(slot)
            found.append(item)
    return found


def relevant(entries, domain, text, recent_user_text):
    words = set(re.findall(r"[^\W\d_]{4,}", text.casefold()))
    stop = {"about", "should", "would", "could", "what", "that", "this", "tell", "will", "please", "chart", "reading"}
    ranked = []
    for entry in entries:
        quote = entry.get("quote")
        if quote and any(quote in message for message in recent_user_text):
            continue
        overlap = (words - stop) & set(re.findall(r"[^\W\d_]{4,}", (quote or "").casefold()))
        score = 3 * (entry["domain"] == domain) + min(3, len(overlap))
        if score:
            ranked.append((score, entry))
    return [entry for _, entry in sorted(ranked, key=lambda row: row[0], reverse=True)[:4]]
