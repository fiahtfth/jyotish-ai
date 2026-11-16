"""Factual verification of generated responses.

Checks astro claims in a reply against the locked chart facts before the
answer reaches the user. Separates: numerical correctness (planet sign /
house / degree), rule correctness (dasha lord, dasha dates, muntha), source
correctness (citations), and interpretive statements (left alone).
"""
import re

from . import constants as K

_NUM_RANGE = re.compile(r"\b(1\d\d|[2-9]\d|[1-9])\s*(?:-|to)\s*(1\d\d|[2-9]\d|[1-9])\s*%|\b(\d{1,3})\s*%")

_PLANET_PAT = "|".join(K.PLANET_NAMES.values())
_SIGN_PAT = "|".join(K.SIGN_NAMES)


def _claims_planet_sign(text: str):
    out = []
    for m in re.finditer(
            rf"({ _PLANET_PAT })\s+(?:is\s+)?(?:in|placed in|occupying|sits in|transiting)\s+({_SIGN_PAT})",
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

    # 6. Precise degree assertions — degrees are locked facts; the model is
    #    not allowed to state or compute them at all
    if re.search(r"\d+(?:\.\d+)?\s*(?:°|degrees?)", text, re.I):
        issues.append("states a precise degree value; degrees are locked facts the model may not utter")

    return {"ok": not issues, "issues": issues, "warnings": warnings}


def repair_response(text: str, issues: list[str]) -> str:
    """Strip sentences that carry unverifiable/false astro claims."""
    if not issues:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        bad = False
        for it in issues:
            # crude: if the sentence contains both nouns involved in the issue
            words = [w for w in re.findall(r"[A-Za-z]+", it) if len(w) > 2]
            if sum(1 for w in words if w.lower() in s.lower()) >= 2:
                bad = True
                break
        if not bad and s.strip():
            kept.append(s.strip())
    if kept:
        return " ".join(kept)
    return ("I'd rather not state that — the calculated chart doesn't support "
            "the claim as phrased. Let me answer from what the chart actually shows.")
