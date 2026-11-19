"""Factual verification of generated responses.

Checks astro claims in a reply against the locked chart facts before the
answer reaches the user. Separates: numerical correctness (planet sign /
house / degree), rule correctness (dasha lord, dasha dates, muntha), source
correctness (citations), and interpretive statements (left alone).
"""
import json
import re

from . import constants as K

_NUM_RANGE = re.compile(r"\b(1\d\d|[2-9]\d|[1-9])\s*(?:-|to)\s*(1\d\d|[2-9]\d|[1-9])\s*%|\b(\d{1,3})\s*%")

_PLANET_PAT = "|".join(K.PLANET_NAMES.values())
_SIGN_PAT = "|".join(K.SIGN_NAMES)


def _claims_planet_sign(text: str):
    # natal-position claims only — transit claims are time-dependent and
    # cannot be checked against the natal chart, so 'transiting' is excluded
    out = []
    for m in re.finditer(
            rf"({ _PLANET_PAT })\s+(?:is\s+)?(?:in|placed in|occupying|sits in)\s+({_SIGN_PAT})",
            text, re.I):
        out.append((m.group(1).title(), m.group(2).title()))
    return out


def _claims_dasha(text: str):
    out = []
    for m in re.finditer(rf"({_PLANET_PAT})\s+(?:maha\s?)?dasha", text, re.I):
        out.append(m.group(1).title())
    for m in re.finditer(rf"dasha\s+of\s+({_PLANET_PAT})", text, re.I):
        out.append(m.group(1).title())
    return out


def _claims_house(text: str):
    out = []
    for m in re.finditer(rf"({_PLANET_PAT})\s+(?:is\s+)?(?:in|in the)\s+(\d+)(?:st|nd|rd|th)?\s+house", text, re.I):
        out.append((m.group(1).title(), int(m.group(2))))
    return out


_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_MONTH_PAT = "|".join(_MONTHS)
_NAK_PAT = "|".join(sorted(K.NAKSHATRAS, key=len, reverse=True))
_DEGREE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°|degrees?\b)", re.I)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_YEAR_RE = re.compile(rf"\b({_MONTH_PAT})\s+(\d{{4}})\b", re.I)
_DURATION_RE = re.compile(r"\b(\d+(?:\.\d+)?)[\s-]*(?:years?|yrs?)\b(?!\s*old)", re.I)
_DASHA_CONTEXT = re.compile(r"dasha|bhukti|antar|period|mahadasha", re.I)
# Vimshottari maha-dasha lengths and the 120-year cycle are fixed classical constants
_CLASSICAL_YEARS = {6, 7, 10, 16, 17, 18, 19, 20, 120}
_PROBABILITY_RE = re.compile(
    r"\b(?:chances?\s+of|probability\s+of|probabilit(?:y|ies)|odds\s+of|\d+\s*(?:in|out of)\s*\d+\s+chance)\b"
    r"|\blikel(?:y|ihood)\b[^.!?\n]{0,30}\d\s*%", re.I)


def _grounding(facts: dict, context: dict) -> str:
    """Everything the model was shown, as one string. Falls back to the facts."""
    text = context.get("grounding_text")
    if text:
        return text
    try:
        return json.dumps(facts, default=str)
    except (TypeError, ValueError):
        return ""


def _degree_values(facts: dict, grounding: str) -> list[float]:
    vals = [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*°", grounding)]
    vals += [float(m.group(1)) for m in re.finditer(
        r'"(?:degree|abs_longitude)"\s*:\s*(\d+(?:\.\d+)?)', grounding)]
    recs = [facts.get("lagna")] + list((facts.get("planets") or {}).values())
    for rec in recs:
        if isinstance(rec, dict) and isinstance(rec.get("degree"), (int, float)):
            vals.append(float(rec["degree"]))
    return vals


def _degree_supported(claim: str, vals: list[float]) -> bool:
    decimals = len(claim.split(".")[1]) if "." in claim else 0
    v = float(claim)
    step = 10 ** -decimals
    for n in vals:
        # the model may round or truncate a locked value, never alter it
        if abs(round(n, decimals) - v) < step / 2 or abs(int(n * 10 ** decimals) / 10 ** decimals - v) < step / 2:
            return True
    return False


def _unsupported_claims(text: str, facts: dict, grounding: str) -> list[str]:
    """Degrees, signs, nakshatras, dates, durations and probability wording
    the model produced that are absent from what it was given."""
    issues, low = [], grounding.lower()

    vals = _degree_values(facts, grounding)
    for m in _DEGREE_RE.finditer(text):
        if not _degree_supported(m.group(1), vals):
            issues.append(f"unsupported degree value '{m.group(0)}' is not in the chart facts")

    for m in re.finditer(rf"\b({_SIGN_PAT})\b", text, re.I):
        if not re.search(rf"\b{m.group(1).lower()}\b", low):
            issues.append(f"sign '{m.group(1)}' is not in the supplied facts")
    for m in re.finditer(rf"\b({_NAK_PAT})\b", text, re.I):
        if not re.search(rf"\b{re.escape(m.group(1).lower())}\b", low):
            issues.append(f"nakshatra '{m.group(1)}' is not in the supplied facts")

    for m in _ISO_RE.finditer(text):
        if m.group(0) not in grounding:
            issues.append(f"date '{m.group(0)}' is not in the supplied facts")
    for m in _MONTH_YEAR_RE.finditer(text):
        month = _MONTHS.index(m.group(1).title()) + 1
        if (f"{m.group(2)}-{month:02d}" not in grounding
                and m.group(0).lower() not in low):
            issues.append(f"date '{m.group(0)}' is not in the supplied facts")

    tokens = set(re.findall(r"\d+(?:\.\d+)?", grounding))
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not _DASHA_CONTEXT.search(sentence):
            continue
        for m in _DURATION_RE.finditer(sentence):
            raw = m.group(1)
            if raw not in tokens and float(raw) not in {float(t) for t in tokens} \
                    and float(raw) not in _CLASSICAL_YEARS:
                issues.append(f"duration '{m.group(0)}' is not in the supplied facts")

    for m in _PROBABILITY_RE.finditer(text):
        if m.group(0).lower() not in low:
            issues.append(f"probability wording '{m.group(0)}' is not permitted")
    return issues


def verify_response(text: str, facts: dict, context: dict) -> dict:
    """Return {ok, issues, warnings}. issues = factual errors to repair."""
    issues, warnings = [], []

    # 1. Planet-in-sign claims
    for planet, sign in _claims_planet_sign(text):
        if planet in ("Lagna", "Ascendant"):
            actual = facts["lagna"]["sign_name"]
        elif planet in facts["planets"]:
            actual = facts["planets"][planet]["sign_name"]
        else:
            continue
        if sign != actual:
            issues.append(f"claims {planet} in {sign}, chart has {actual}")

    # 2. Planet-in-house claims
    for planet, house in _claims_house(text):
        if planet in facts["planets"]:
            actual = facts["planets"][planet]["house"]
            if house != actual:
                issues.append(f"claims {planet} in {house}th house, chart has {actual}th")

    # 3. Dasha lord claims vs the running dasha used in context
    running = context.get("running_dasha") or []
    if running:
        actual_md = running[0]["lords"][0]
        for lord in _claims_dasha(text):
            if lord != actual_md and ("current" in text.lower() or "running" in text.lower()):
                issues.append(f"claims current dasha lord {lord}, chart shows {actual_md}")

    # 4. Unsupported numerical probabilities
    for m in _NUM_RANGE.finditer(text):
        warnings.append(f"unsupported numerical probability '{m.group(0)}'")
        issues.append(f"numerical probability '{m.group(0)}' is not permitted")

    # 5. Fabricated citation patterns — a real Sanskrit citation must come
    #    from the knowledge base, never free-generated
    if re.search(r"(BPHS|Phaladeepika|Saravali|Jaimini Sutra)\s+(chapter\s+)?\d+[:.]\d+", text, re.I):
        if not context.get("citations_provided"):
            issues.append("classical citation not backed by a retrieved source")

    # 6. Degrees, signs, nakshatras, dates, durations and probability wording
    #    must all be present in what the model was given (context["grounding_text"],
    #    else the facts); a value it was never shown is invented.
    issues.extend(_unsupported_claims(text, facts, _grounding(facts, context)))

    return {"ok": not issues, "issues": issues, "warnings": warnings}


def repair_response(text: str, issues: list[str]) -> str:
    """Strip sentences that carry unverifiable/false astro claims.

    Paragraph and line structure is preserved — joining kept sentences with
    spaces once collapsed every newline in a reply into one blob."""
    if not issues:
        return text

    def bad(s: str) -> bool:
        for it in issues:
            quoted = re.search(r"'([^']+)'", it)
            if quoted:
                if quoted.group(1).lower() in s.lower():
                    return True
                continue
            # crude: if the sentence contains both nouns involved in the issue
            words = [w for w in re.findall(r"[A-Za-z]+", it) if len(w) > 2]
            if sum(1 for w in words if w.lower() in s.lower()) >= 2:
                return True
        return False

    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
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
                        nxt = rows[i + 1] if i + 1 < len(rows) else None
                        if (ln.rstrip()[-1:] not in ".!?" and nxt is not None
                                and not is_row(nxt) and bad(ln + " " + nxt)
                                and (not is_row(ln) or not bad(nxt))):
                            return True
                        prv = rows[i - 1] if i else ""
                        if (not is_row(ln) and prv
                                and prv.rstrip()[-1:] not in ".!?"
                                and not bad(prv) and bad(prv + " " + ln)):
                            return True
                        return False
                    kept_lines = [ln for i, ln in enumerate(rows)
                                  if ln.strip() and not bad(ln)
                                  and not fragment(i, ln)]
                    if not any(is_row(ln) for ln in kept_lines):
                        # No rows survive: complete or substantive prose
                        # still answers, but a bare lead-in is no reply.
                        kept_lines = [ln for ln in kept_lines
                                      if ln.rstrip()[-1:] in ".!?"
                                      or len(ln.split()) >= 4]
                    sentence = "\n".join(kept_lines)
                else:
                    continue
            if sentence.strip():
                kept_parts.append(sentence + sep)
        kept = "".join(kept_parts)
        if kept.strip():
            paragraphs.append(kept.strip())
    if paragraphs:
        return "\n\n".join(paragraphs)
    return ("I'd rather not state that — the calculated chart doesn't support "
            "the claim as phrased. Let me answer from what the chart actually shows.")
