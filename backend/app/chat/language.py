"""Resolve the parts of a conversational question that select chart calculations."""
import calendar
import re
from datetime import date, timedelta

from ..astro.constants import SIGN_NAMES


_MONTHS = {name.lower(): i for names in (calendar.month_name, calendar.month_abbr)
           for i, name in enumerate(names) if name}
_MONTHS["sept"] = 9
_MONTHS.update({name: month for month, name in enumerate(
    "जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर".split(), 1)})
_MONTHS.update({"फरवरी": 2, "सितम्बर": 9, "दिसंबर": 12})
_MONTH = re.compile(r"(?<!\w)(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?!\w)\.?", re.I)

# Topic corrections often name the discarded subject as well as its replacement.
def focus_text(text):
    text = re.split(r"\b(?:actually[, ]+|I (?:meant|mean)\s+|instead I mean\s+)", text, flags=re.I)[-1]
    text = re.sub(r"\bnot\s+[^,;]+?\s+but\s+", "", text, flags=re.I)
    text = re.sub(r"\bnot\s+[^,;]+[,;]\s*", "", text, flags=re.I)
    return re.split(r",\s*not\b|\s+rather than\b|\s+instead of\b", text, flags=re.I)[0].strip()


def topic_correction(text):
    return bool(re.search(
        r"\b(?:actually|instead|i (?:meant|mean)|rather than|not|nahi|nahin|ki baat|"
        r"separately|(?:new|different|separate|unrelated) (?:question|topic)|(?:alag|naya) sawaal)\b"
        r"|नहीं|बल्कि|मेरा मतलब|अलग सवाल",
        text, re.I))


def prior_period_request(text):
    """Recognize an explicit instruction to keep or drop the previous window."""
    if re.search(r"\b(?:not|no longer) (?:the )?same (?:period|time)\b|\b(?:use|choose) (?:a )?different period\b",
                 text, re.I):
        return False
    if re.search(r"\b(?:same (?:period|time)|usi (?:period|samay))\b|उसी अवधि|उसी समय", text, re.I):
        return True
    return None


def _month_window(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def requested_window(text, today, prior=None):
    """None means the user supplied no time period. Resolve a bare month against
    the last stated year, or its next occurrence when no year is in scope."""
    result = _parse_window(text.casefold(), today, prior)
    # The precision engine samples each interval at several possible birth times.
    # Keep the existing one-year calculation horizon when accepting explicit ranges.
    if result and (result[1] - result[0]).days > 365:
        raise ValueError("choose a period of up to one year")
    return result


def _shift_months(day, count):
    year, month = divmod(day.year * 12 + day.month - 1 + count, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _parse_window(t, today, prior):
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
               "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
    duration = re.search(
        r"\b(?:(next|coming|past|last|for|over|within)\s+)?"
        r"(\d{1,3}|" + "|".join(numbers) + r")\s+(days?|weeks?|months?|years?)\b", t)
    if duration:
        raw = duration[2]
        count = int(raw) if raw.isdigit() else numbers[raw]
        if count < 1:
            raise ValueError("choose a positive duration")
        past = duration[1] in ("past", "last")
        unit = duration[3].rstrip("s")
        if unit in ("month", "year"):
            boundary = _shift_months(today, count * (12 if unit == "year" else 1) * (-1 if past else 1))
        else:
            boundary = today + timedelta(days=count * (7 if unit == "week" else 1) * (-1 if past else 1))
        return (boundary, today - timedelta(days=1)) if past else (today, boundary - timedelta(days=1))
    relative_year = None
    if any(word in t for word in ("next year", "agle saal", "अगले साल")):
        relative_year = today.year + 1
    elif any(word in t for word in ("this year", "is saal", "इस साल")):
        relative_year = today.year
    iso = re.findall(r"\b20\d\d-\d\d-\d\d\b", t)
    if iso:
        start, end = date.fromisoformat(iso[0]), date.fromisoformat(iso[-1])
        if end < start:
            raise ValueError("reversed dates")
        return start, end
    months = []
    for match in _MONTH.finditer(t):
        before, after = t[:match.start()], t[match.end():]
        day_before = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?(?: of)?\s+$", before)
        day_after = re.match(r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", after)
        day = day_before or day_after
        suffix = after[day_after.end():] if day_after else after
        year = re.match(r"[\s,]*(?:of )?(20\d\d)\b", suffix)
        name = match[1]
        if name in ("may", "march") and not (day or year):
            if not (re.search(r"\b(in|during|about|for|to|through|until|and|next|this|of|by)\s*$", before)
                    or re.fullmatch(r"[?.!\s]*", after)):
                continue
        months.append((_MONTHS[name], int(day[1]) if day else None, int(year[1]) if year else None))
    year_match = re.search(r"\b(20\d\d)\b", t)
    if months:
        if len(months) > 2 or (len(months) == 2 and re.search(r"\b(?:or|versus|vs)\b", t)):
            raise ValueError("multiple candidate periods")
        first, first_day, first_year = months[0]
        last, last_day, last_year = months[-1]
        anchor = today.year + (first < today.month)
        if prior and prior[0].year == prior[1].year:
            anchor = prior[0].year
        if last_year and not first_year:
            anchor = last_year - (last < first)
        elif year_match:
            anchor = int(year_match[1])
        year = first_year or relative_year or anchor
        end_year = last_year or year + (last < first)
        start = date(year, first, first_day or 1)
        end = date(end_year, last, last_day or calendar.monthrange(end_year, last)[1])
        if end < start:
            raise ValueError("reversed interval")
        return start, end
    if len(set(re.findall(r"\b20\d\d\b", t))) > 1:
        raise ValueError("choose one year")
    if year_match or relative_year:
        year = int(year_match[1]) if year_match else relative_year
        first = 7 if re.search(r"second half|late\b", t) else 1
        last = 6 if re.search(r"first half|early\b", t) else 12
        return date(year, first, 1), _month_window(year, last)[1]
    if prior and re.search(r"following month|month after (?:that|this)|month after$", t):
        following = _month_window(prior[1].year, prior[1].month)[1] + timedelta(days=1)
        return _month_window(following.year, following.month)
    if re.search(r"next month|agle mahine|अगले महीने", t):
        start = _month_window(today.year, today.month)[1] + timedelta(days=1)
        return _month_window(start.year, start.month)
    if "this month" in t:
        return _month_window(today.year, today.month)
    if re.search(r"\b(?:next|this) week\b", t):
        start = today - timedelta(days=today.weekday()) + timedelta(days=7 if "next week" in t else 0)
        return start, start + timedelta(days=6)
    return None


def window_label(window):
    start, end = window
    if _month_window(start.year, start.month) == window:
        return start.strftime("%B %Y")
    if start == date(start.year, 1, 1) and end == date(start.year, 12, 31):
        return str(start.year)
    if start == end:
        return f"{start:%d %B %Y}"
    return f"{start:%d %b %Y} to {end:%d %b %Y}"


def show_chart(text, varga):
    t = text.strip().casefold().rstrip("?.! ")
    if re.search(r"\b(?:mean|means|explain|interpret|signif\w*|suggest\w*|indicat\w*|tell|read|why|about|report|analysis|say)\b", t):
        return False
    if not varga and not re.search(r"\b(?:chart|kundli)\b", t):
        return False
    return bool(re.search(r"^(?:(?:can|could|would) (?:you|i) |i(?:'d like| want) to |please )*"
                          r"(?:show|display|draw|see|view|open|pull up)\b", t)
                or re.fullmatch(r"(?:(?:my|the|please) )?(?:d-?\d+|\w+ chart|kundli|chart)(?: chart)?", t))


def chart_details(facts, varga, text):
    chart = facts["vargas"].get(varga)
    if not chart:
        return None
    lagna = chart["Lagna"]["sign"]
    placements = {name: {"sign": SIGN_NAMES[p["sign"]], "house": (p["sign"] - lagna) % 12 + 1}
                  for name, p in chart.items()}
    planet = next((name for name in placements if re.search(r"\b" + name + r"\b", text, re.I)), None)
    planet = planet or ("Sun" if varga == "D10" else "Lagna")
    return {"name": varga, "placements": placements, "focus": planet}
