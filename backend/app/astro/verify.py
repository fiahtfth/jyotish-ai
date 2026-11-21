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
        # a divisional-chart claim ("in Capricorn navamsa") is checked against
        # that varga, not the D1 chart — skip it here
        if re.search(r"^\s+(?:in\s+(?:the\s+)?)?(navamsa|dasamsa|dashamsha|saptamsa|hora|"
                     r"chaturthamsa|dwadasamsa|rashi|d[- ]?\d+)\b",
                     text[m.end():], re.I):
            continue
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


_KARAKA_TITLES = ("Atmakaraka", "Amatyakaraka", "Bhratrukaraka", "Matrukaraka", "Putrakaraka",
                  "Gnatikaraka", "Darakaraka")
_TITLE_PAT = "|".join(_KARAKA_TITLES)
_PL7 = "Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu"
_GAP = r"[^.;,:!?\n()]{0,30}?"
_KARAKA_A = re.compile(rf"\b({_PL7})\b{_GAP}\b({_TITLE_PAT})\b", re.I)
_KARAKA_B = re.compile(rf"\b({_TITLE_PAT})\b\s*(?:is|=|:|being|-|as)?\s*\(?(?:the |your |planet )?\b({_PL7})\b", re.I)


def _claims_karaka(text: str):
    """[(planet, title)] where a planet is called a Jaimini chara-karaka title."""
    out = []
    for m in _KARAKA_A.finditer(text):
        out.append((m.group(1).title(), m.group(2).title()))
    for m in _KARAKA_B.finditer(text):
        out.append((m.group(2).title(), m.group(1).title()))
    return out


_RETRO_A = re.compile(r"\b(Rahu|Ketu)\b[^.;,:!?\n()]{0,40}?\b(?:retrograde|retro|vakri)\b", re.I)
_RETRO_B = re.compile(r"\b(?:retrograde|retro|vakri)\s+(Rahu|Ketu)\b", re.I)
_RETRO_OK = re.compile(r"\balways\b|\bnaturally\b|\bby nature\b|\bnot (?:meaningful|significant)\b|"
                       r"\bno (?:significance|meaning)\b|\bnever\b", re.I)


def _claims_node_retro(text: str):
    """Rahu/Ketu called retrograde as if it mattered (they are always retrograde)."""
    if _RETRO_OK.search(text):
        return []
    return [m.group(1).title() for rx in (_RETRO_A, _RETRO_B) for m in rx.finditer(text)]


_NUMS = r"\d+(?:st|nd|rd|th)?(?:\s*(?:,|and|&)\s*\d+(?:st|nd|rd|th)?)*"
_LORD_A = re.compile(rf"\b({_PL7})\b\s+(?:is\s+)?(?:the\s+)?(?:lord(?:s)? of|rules?|ruler of|owns?)\s+"
                     rf"(?:your\s+|the\s+)?({_NUMS})\s*(?:house|bhava)", re.I)
_LORD_B = re.compile(rf"\b(\d+)(?:st|nd|rd|th)?\s*(?:house\s+)?lord\s+(?:is|=|:)\s*({_PL7})\b", re.I)
_LORD_SKIP = re.compile(r"from (?:the |your )?moon|moon chart|chandra|\bD\d+\b|navamsa|varga|"
                        r"from (?:the |your )?(?:arudha|AL|UL)", re.I)


def _claims_lordship(text: str):
    """[(planet, house)] from 'X rules the Nth house' / 'Nth lord is X' (D1, from Lagna)."""
    if _LORD_SKIP.search(text):
        return []
    out = []
    for m in _LORD_A.finditer(text):
        for n in re.findall(r"\d+", m.group(2)):
            out.append((m.group(1).title(), int(n)))
    for m in _LORD_B.finditer(text):
        out.append((m.group(2).title(), int(m.group(1))))
    return out


def _house_lord(facts: dict, h: int):
    houses = facts.get("houses") or {}
    return (houses.get(h) or houses.get(str(h)) or {}).get("lord")


def _structure_issues(text: str, facts: dict) -> list[str]:
    issues = []
    kar = (facts.get("jaimini") or {}).get("karakas") or {}
    for seg, _ in split_sentences(text):
        if kar:
            for planet, title in _claims_karaka(seg):
                if title in kar and kar[title] != planet:
                    issues.append(f"claims {planet} is the {title}, chart has {kar[title]}")
                elif title not in kar:
                    issues.append(f"claims {planet} is the {title}, chart has no such karaka")
        for node in _claims_node_retro(seg):
            issues.append(f"calls {node} retrograde as an influence; the nodes are always retrograde "
                          "and this carries no meaning")
        for planet, h in _claims_lordship(seg):
            actual = _house_lord(facts, h)
            if actual and planet in K.PLANET_NAMES.values() and planet not in ("Rahu", "Ketu") \
                    and actual != planet:
                issues.append(f"claims {planet} rules the {h}th house, chart has {actual}")
    return list(dict.fromkeys(issues))


_VARGA_NAMES = {"navamsa": "D9", "d9": "D9", "dasamsa": "D10", "dashamsha": "D10",
                "d10": "D10", "d7": "D7", "saptamsa": "D7", "d2": "D2", "hora": "D2",
                "d4": "D4", "chaturthamsa": "D4", "d12": "D12", "dwadasamsa": "D12",
                "d24": "D24", "d6": "D6", "d1": "D1", "rashi": "D1"}


def _claims_varga(text: str):
    out = []
    for m in re.finditer(
            rf"({_PLANET_PAT})\s+(?:is\s+)?(?:in|placed in|occupying)\s+({_SIGN_PAT})\s+"
            rf"(?:in\s+(?:the\s+)?|of\s+(?:the\s+)?)?({'|'.join(_VARGA_NAMES)})\b",
            text, re.I):
        out.append((m.group(1).title(), m.group(2).title(),
                    _VARGA_NAMES[m.group(3).lower()]))
    return out


def _claims_transit(text: str):
    out = []
    for m in re.finditer(
            rf"({_PLANET_PAT})\s+(?:is\s+)?transit\w*\s+(?:(?:in|into|through|over)\s+)?"
            rf"(?:the\s+|your\s+)?(?:sign\s+of\s+)?({_SIGN_PAT})",
            text, re.I):
        out.append((m.group(1).title(), m.group(2).title()))
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


def house_lines(facts: dict) -> str:
    """The sign and lord of all 12 houses (empty houses included) and where
    each house lord sits, so correct statements about them are never flagged."""
    out = []
    try:
        planets = facts.get("planets") or {}
        for h, rec in sorted((facts.get("houses") or {}).items(), key=lambda kv: int(kv[0])):
            lord = rec.get("lord")
            where = planets.get(lord) or {}
            out.append(f"House {h}: {rec.get('sign_name')}, lord {lord}"
                       + (f" placed in {where.get('sign_name')} house {where.get('house')}" if where else ""))
    except (TypeError, ValueError, AttributeError):
        pass
    return "\n".join(out)


def _grounding(facts: dict, context: dict) -> str:
    """Everything the model was shown, as one string. Falls back to the facts.
    Always extended with all 12 house signs and anything the user said
    (context["user_text"], str or list) or the app noted (context["context_note"],
    context["memory"]) — the user's own dates and facts are not inventions."""
    text = context.get("grounding_text")
    if not text:
        try:
            text = json.dumps(facts, default=str)
        except (TypeError, ValueError):
            text = ""
    extra = [house_lines(facts or {})]
    for key in ("user_text", "context_note", "memory"):
        val = context.get(key)
        if isinstance(val, (list, tuple)):
            val = "\n".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
                            for v in val)
        elif val is not None and not isinstance(val, str):
            val = json.dumps(val, ensure_ascii=False, default=str)
        extra.append(val or "")
    return "\n".join([text] + [e for e in extra if e])


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

    # 2b. Lordship claims — the chart's house lords are exact
    houses = facts.get("houses") or {}
    for planet, house in _claims_lordship(text):
        actual = houses.get(str(house), houses.get(house, {})).get("lord")
        if actual and planet != actual:
            issues.append(f"claims {planet} rules the {house}th house, chart has {actual}")

    # 2c. Divisional (varga) placement claims
    vargas = facts.get("vargas") or {}
    for planet, sign, chart in _claims_varga(text):
        rec = (vargas.get(chart) or {}).get(planet)
        if rec is not None:
            actual = K.SIGN_NAMES[rec["sign"]]
            if sign != actual:
                issues.append(f"claims {planet} in {sign} in {chart}, chart has {actual}")

    # 2d. Transit claims — checked against the transits supplied for the window
    window_transits = facts.get("window_transits") or {}
    for planet, sign in _claims_transit(text):
        actual = window_transits.get(planet)
        if actual and sign not in actual:
            issues.append(
                f"claims {planet} transits {sign}, chart has {', '.join(actual)}")

    # 3. Dasha lord claims vs the running dasha used in context
    running = context.get("running_dasha") or []
    if running:
        actual_md = running[0]["lords"][0]
        for lord in _claims_dasha(text):
            if lord != actual_md and ("current" in text.lower() or "running" in text.lower()):
                issues.append(f"claims current dasha lord {lord}, chart shows {actual_md}")

    # 4. Unsupported numerical probabilities
    for m in _NUM_RANGE.finditer(text):
        if re.fullmatch(r"(?:100|0)\s*%", m.group(0).strip()):
            continue    # "100% worth it" is an idiom, not a probability
        warnings.append(f"unsupported numerical probability '{m.group(0)}'")
        issues.append(f"numerical probability '{m.group(0)}' is not permitted")

    # 5. Fabricated citation patterns — a real Sanskrit citation must come
    #    from the knowledge base, never free-generated
    if re.search(r"(BPHS|Phaladeepika|Saravali|Jaimini Sutra)\s+(chapter\s+)?\d+[:.]\d+", text, re.I):
        if not context.get("citations_provided"):
            issues.append("classical citation not backed by a retrieved source")

    # 5b. Chara-karaka titles, Rahu/Ketu "retrograde", house-lordship claims
    issues.extend(_structure_issues(text, facts))

    # 6. Degrees, signs, nakshatras, dates, durations and probability wording
    #    must all be present in what the model was given (context["grounding_text"],
    #    else the facts); a value it was never shown is invented.
    issues.extend(_unsupported_claims(text, facts, _grounding(facts, context)))

    return {"ok": not issues, "issues": issues, "warnings": warnings}


_SENT_SPLIT = re.compile(r"((?<=[.!?])(?<!\b\d\.)(?<!\b\d\d\.)[ \t]+|\n+)")


def split_sentences(text: str) -> list[list[str]]:
    """[[segment, separator], ...]; joining every pair reproduces `text`.
    Newlines (paragraphs, list items) and numbered-list markers are kept intact."""
    parts = _SENT_SPLIT.split(text)
    out = []
    for i in range(0, len(parts), 2):
        out.append([parts[i], parts[i + 1] if i + 1 < len(parts) else ""])
    return out


def strip_sentences(text: str, is_bad) -> str:
    """Remove only the sentences for which is_bad(sentence) is true, keeping the
    original paragraph breaks, list structure and spacing of everything else."""
    out, prev_sep = [], "\n"
    for seg, sep in split_sentences(text):
        if seg.strip() and is_bad(seg):
            at_line_start = "\n" in prev_sep
            at_line_end = "\n" in sep or not sep
            if at_line_start and at_line_end:
                continue                      # whole line removed, with its newline
            if "\n" in sep:
                out.append(sep)               # keep the line break after a partial line
                prev_sep = sep
            continue                          # sentence and its trailing spaces
        out.append(seg + sep)
        prev_sep = sep
    res = "".join(out)
    res = re.sub(r"[ \t]+\n", "\n", res)
    res = re.sub(r"\n{3,}", "\n\n", res)
    return res.strip()


def _issue_matcher(issue: str):
    """A predicate selecting exactly the sentences an issue is about, or None."""
    m = re.match(r"claims (\w+) in (\w+) in (\w+), chart has", issue)
    if m:
        planet, sign, chart = (g.lower() for g in m.groups())
        return lambda s: any(p.lower() == planet and g.lower() == sign and c.lower() == chart
                             for p, g, c in _claims_varga(s))
    m = re.match(r"claims (\w+) transits (\w+), chart has", issue)
    if m:
        planet, sign = (g.lower() for g in m.groups())
        return lambda s: any(p.lower() == planet and g.lower() == sign
                             for p, g in _claims_transit(s))
    m = re.match(r"claims (\w+) in (\w+), chart has", issue)
    if m:
        planet, sign = m.group(1).lower(), m.group(2).lower()
        return lambda s: any(p.lower() == planet and g.lower() == sign for p, g in _claims_planet_sign(s))
    m = re.match(r"claims (\w+) in (\d+)th house", issue)
    if m:
        planet, house = m.group(1).lower(), int(m.group(2))
        return lambda s: any(p.lower() == planet and h == house for p, h in _claims_house(s))
    m = re.match(r"claims current dasha lord (\w+)", issue)
    if m:
        lord = m.group(1).lower()
        return lambda s: any(p.lower() == lord for p in _claims_dasha(s))
    m = re.match(r"claims (\w+) is the (\w+), chart has", issue)
    if m:
        planet, title = m.group(1).lower(), m.group(2).lower()
        return lambda s: any(p.lower() == planet and t.lower() == title for p, t in _claims_karaka(s))
    m = re.match(r"calls (\w+) retrograde", issue)
    if m:
        node = m.group(1).lower()
        return lambda s: any(n.lower() == node for n in _claims_node_retro(s))
    m = re.match(r"claims (\w+) rules the (\d+)th house, chart has", issue)
    if m:
        planet, house = m.group(1).lower(), int(m.group(2))
        return lambda s: any(p.lower() == planet and h == house for p, h in _claims_lordship(s))
    if issue.startswith("classical citation"):
        pat = re.compile(r"(BPHS|Phaladeepika|Saravali|Jaimini Sutra)\s+(chapter\s+)?\d+[:.]\d+", re.I)
        return lambda s: bool(pat.search(s))
    q = re.search(r"'([^']+)'", issue)
    if q:
        needle = q.group(1).lower()
        return lambda s: needle in s.lower()
    return None


def repair_response(text: str, issues: list[str]) -> str:
    """Strip sentences that carry unverifiable/false astro claims.

    Paragraph and line structure is preserved — joining kept sentences with
    spaces once collapsed every newline in a reply into one blob."""
    if not issues:
        return text
    pairs = [(_issue_matcher(i), i) for i in issues]
    matchers = [m for m, _ in pairs if m]
    crude_issues = [i for m, i in pairs if not m]

    def bad(s: str) -> bool:
        if any(m(s) for m in matchers):
            return True
        # Issues without a typed matcher fall back to word overlap — but only
        # for those issues, so a precise match never drags in good sentences.
        for it in crude_issues:
            quoted = re.search(r"'([^']+)'", it)
            if quoted:
                if quoted.group(1).lower() in s.lower():
                    return True
                continue
            words = [w for w in re.findall(r"[A-Za-z]+", it) if len(w) > 2]
            if sum(1 for w in words if w.lower() in s.lower()) >= 2:
                return True
        return False

    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
        # Sentences may wrap across newlines; keep each sentence's original
        # trailing whitespace so kept text preserves the line structure.
        pieces = re.split(r"((?<=[.!?])\s+)", para)
        # Enumeration markers ("2.") split from their item text — glue them
        # back so a numbered item is judged (and dropped) as a unit.
        glued = []
        i = 0
        while i < len(pieces):
            if (i % 2 == 0 and i + 3 < len(pieces)
                    and re.fullmatch(r"\d{1,2}[.)]", pieces[i].strip())):
                glued += [pieces[i] + pieces[i + 1] + pieces[i + 2], pieces[i + 3]]
                i += 4
            else:
                glued.append(pieces[i])
                i += 1
        pieces = glued
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
                        # A row only wraps into an *indented* continuation.
                        nxt = rows[i + 1] if i + 1 < len(rows) else None
                        if (ln.rstrip()[-1:] not in ".!?" and nxt is not None
                                and not is_row(nxt) and bad(ln + " " + nxt)
                                and (not is_row(ln)
                                     or (nxt[:1] in (" ", "\t")
                                         and not bad(nxt)))):
                            return True
                        prv = rows[i - 1] if i else ""
                        return bool(
                            not is_row(ln) and prv and not bad(prv)
                            and fragment(i - 1, prv)
                            and bad(prv + " " + ln))
                    kept_pairs = [(i, ln) for i, ln in enumerate(rows)
                                  if ln.strip() and not bad(ln)
                                  and not fragment(i, ln)]
                    kept_lines = [ln for _, ln in kept_pairs]
                    if not any(is_row(ln) for ln in kept_lines):
                        # No rows survive: complete or substantive prose
                        # still answers, but a bare lead-in is no reply.
                        kept_pairs = [(i, ln) for i, ln in kept_pairs
                                      if ln.rstrip()[-1:] in ".!?"
                                      or (len(ln.split()) >= 4
                                          and not ln.rstrip().endswith(":"))]
                    # Deleting rows can leave two prose halves adjacent whose
                    # join rebuilds the rejected claim — drop both halves.
                    final = []
                    for i, ln in kept_pairs:
                        if (final and i > final[-1][0] + 1
                                and not is_row(final[-1][1])
                                and final[-1][1].rstrip()[-1:] not in ".!?"
                                and not is_row(ln)
                                and bad(final[-1][1] + " " + ln)):
                            final.pop()
                            continue
                        final.append((i, ln))
                    sentence = "\n".join(ln for _, ln in final)
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
