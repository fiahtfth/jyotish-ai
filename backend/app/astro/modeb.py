"""Mode B: pasted degree tables from other programs (JH, Drik, AstroSage).

A user who cannot supply an exact birth instant can still paste a planet
table produced elsewhere. This module parses the common layouts, records
the *precision of each pasted value*, and propagates that precision into
ambiguity flags instead of pretending the numbers are exact:

- sign-level vargas (D9, D60…) are pure functions of longitude, so they can
  be evaluated at both ends of the pasted interval — a planet whose
  divisional sign changes across its own error bar is marked ambiguous;
- Chara-karaka ranks compare degree-within-sign between planets, so ranks
  whose intervals overlap are marked ambiguous rather than guessed;
- features that need the birth instant (Lagna, houses, dashas, transits)
  are reported as unavailable, never estimated.
"""
import re

from . import constants as K
from .engine import VARGA_FUNCS
from .settings import AYANAMSAS

# ------------------------------------------------------------------ lexicon

PLANET_ALIASES = {
    "sun": 0, "su": 0, "surya": 0,
    "moon": 1, "mo": 1, "chandra": 1,
    "mars": 2, "ma": 2, "mangal": 2, "mangala": 2, "kuja": 2,
    "mercury": 3, "me": 3, "budha": 3, "budh": 3,
    "jupiter": 4, "ju": 4, "guru": 4, "brihaspati": 4,
    "venus": 5, "ve": 5, "shukra": 5, "sukra": 5,
    "saturn": 6, "sa": 6, "shani": 6, "sani": 6,
    "rahu": 7, "ra": 7,
    "ketu": 8, "ke": 8,
    "uranus": 9, "neptune": 10, "pluto": 11,
    "lagna": "L", "asc": "L", "ascendant": "L", "as": "L", "l": "L",
}

SIGN_ALIASES = {
    "aries": 0, "ari": 0, "ar": 0, "mesha": 0,
    "taurus": 1, "tau": 1, "ta": 1, "vrishabha": 1, "rishaba": 1, "rishabha": 1,
    "gemini": 2, "gem": 2, "ge": 2, "mithuna": 2, "mithun": 2,
    "cancer": 3, "can": 3, "cn": 3, "karka": 3, "kataka": 3,
    "leo": 4, "le": 4, "simha": 4, "sinh": 4, "sinha": 4,
    "virgo": 5, "vir": 5, "vi": 5, "kanya": 5,
    "libra": 6, "lib": 6, "li": 6, "tula": 6,
    "scorpio": 7, "sco": 7, "sc": 7, "vrishchika": 7, "vrischika": 7,
    "sagittarius": 8, "sag": 8, "sg": 8, "dhanu": 8, "dhanus": 8,
    "capricorn": 9, "cap": 9, "cp": 9, "makara": 9, "makar": 9,
    "aquarius": 10, "aqu": 10, "aq": 10, "kumbha": 10, "kumbh": 10,
    "pisces": 11, "pis": 11, "pi": 11, "meena": 11, "meen": 11,
}

DEG_RE = re.compile(r"(\d{1,2})")
DEG_SYM_RE = re.compile(
    r"(?P<deg>\d{1,2})\s*[°:]\s*(?P<min>\d{1,2})?"
    r"(?:\s*['′:]\s*(?P<sec>\d{1,2}(?:\.\d+)?)\s*[\"″]?)?")
DECIMAL_RE = re.compile(r"(?P<deg>\d{1,2}\.\d+)")
RETRO_RE = re.compile(r"(?:\(\s*[R℞]\s*\)|\b[R℞]\b)", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z]+")

PRECISION_ARCSEC = {"arcsec": 0.5, "arcmin": 30.0, "deg_2dp": 18.0,
                    "deg_1dp": 180.0, "deg": 1800.0}


def _word_tokens(line: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(line)]


def _parse_degrees(line: str):
    """(deg_in_sign, precision, error_deg) from the first plausible number(s)."""
    m = DEG_SYM_RE.search(line)
    if m:
        deg = int(m.group("deg"))
        minutes = int(m.group("min") or 0)
        sec = float(m.group("sec") or 0)
        if deg > 29 or minutes > 59 or sec >= 60:
            pass  # implausible — fall through to other formats
        else:
            total = deg + minutes / 60 + sec / 3600
            if m.group("sec") is not None:
                return total, "arcsec", 0.5 / 3600
            if m.group("min") is not None:
                return total, "arcmin", 30.0 / 3600
            return total, "deg", 0.5
    m = DECIMAL_RE.search(line)
    if m:
        digits = len(m.group("deg").split(".")[1])
        err = (0.5 * 10 ** -digits)
        return float(m.group("deg")), f"deg_{min(digits, 2)}dp", err
    m = DEG_RE.search(line)
    if m:
        return float(m.group(1)), "deg", 0.5
    return None, None, None


def _varga_sign_of(fn, abs_long: float, pid) -> int:
    sign, deg = divmod(abs_long, 30.0)
    return int(fn([[pid, (int(sign), deg)]])[0][1][0])


def _edge_ambiguity(abs_long: float, err_deg: float, pid) -> dict:
    """Divisional signs at the ends of the pasted interval; flag if they differ."""
    flips = {}
    lo, hi = abs_long - err_deg, abs_long + err_deg
    for name in ("D9", "D60"):
        fn = VARGA_FUNCS[name]
        s_lo = _varga_sign_of(fn, lo, pid)
        s_hi = _varga_sign_of(fn, hi, pid)
        if s_lo != s_hi:
            flips[name] = [s_lo, _varga_sign_of(fn, abs_long, pid), s_hi]
    return flips


SOURCE_PROGRAMS = ("jagannatha_hora", "drik_panchang", "astrosage", "other")


def parse_degree_table(text: str, source_program: str, ayanamsa_id: str = "LAHIRI") -> dict:
    """Parse a pasted planet-degree table.

    `source_program` and `ayanamsa_id` are required metadata: a longitude is
    meaningless without the frame it was computed in. Unknown lines are
    skipped with a warning rather than guessed.
    """
    if not (text or "").strip():
        raise ValueError("empty degree table")
    if ayanamsa_id not in AYANAMSAS:
        raise ValueError(f"ayanamsa_id must be one of: {', '.join(AYANAMSAS)}")
    sp = (source_program or "").strip().lower()
    if not sp:
        raise ValueError("source_program is required — the table's provenance matters")

    planets, warnings, skipped = {}, [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        tokens = _word_tokens(line)
        pid = next((PLANET_ALIASES[t] for t in tokens if t in PLANET_ALIASES), None)
        if pid is None:
            skipped.append(line)
            continue
        sign = next((SIGN_ALIASES[t] for t in tokens if t in SIGN_ALIASES), None)
        deg, prec, err = _parse_degrees(line)
        if deg is None:
            warnings.append(f"{line!r}: no parseable degree — skipped")
            continue
        if sign is None:
            # "deg min" without a sign: some tables print "lon = 87°17'" as
            # absolute longitude; treat >29 totals or explicit 'lon' as absolute.
            warnings.append(f"{line!r}: no sign found — skipped")
            continue
        if deg >= 30:
            warnings.append(f"{line!r}: degree {deg} out of range — skipped")
            continue
        name = "Lagna" if pid == "L" else (K.PLANET_NAMES.get(pid) or f"P{pid}")
        if name in planets:
            warnings.append(f"{name}: duplicate row — keeping the first")
            continue
        planets[name] = {
            "id": pid, "sign": sign, "sign_name": K.SIGN_NAMES[sign],
            "degree": round(deg, 6),
            "abs_longitude": round(sign * 30 + deg, 6),
            "retrograde": bool(RETRO_RE.search(line)),
            "precision": prec, "error_arcsec": round(err * 3600, 3),
            "source_text": line[:80],
        }
    if not planets:
        raise ValueError("no planet rows parsed")

    ambiguous, d60_suspect = {}, []
    for name, rec in planets.items():
        err_deg = rec["error_arcsec"] / 3600.0
        flips = _edge_ambiguity(rec["abs_longitude"], err_deg, rec["id"])
        if flips:
            ambiguous[name] = flips
        if err_deg >= 0.25:   # half a D60 part
            d60_suspect.append(name)

    # Chara-karaka rank ambiguity under the default 7-karaka scheme:
    # adjacent degree intervals that overlap cannot be ordered.
    seven = [n for n, r in planets.items() if isinstance(r["id"], int) and r["id"] < 7]
    ordered = sorted(seven, key=lambda n: planets[n]["degree"], reverse=True)
    karaka_ties = []
    for a, b in zip(ordered, ordered[1:]):
        ra, rb = planets[a], planets[b]
        if ra["degree"] - ra["error_arcsec"] / 3600 <= rb["degree"] + rb["error_arcsec"] / 3600:
            karaka_ties.append([a, b])

    if skipped:
        warnings.append(f"{len(skipped)} line(s) unrecognised: "
                        + "; ".join(skipped[:5]) + ("…" if len(skipped) > 5 else ""))
    if d60_suspect:
        warnings.append("D60 is unreliable for "
                        + ", ".join(d60_suspect)
                        + " — pasted precision is coarser than half a D60 part (15′)")
    if ambiguous:
        warnings.append("varga signs ambiguous at pasted precision for: "
                        + ", ".join(sorted(ambiguous)))
    if karaka_ties:
        warnings.append("karaka rank ambiguous between: "
                        + "; ".join(f"{a}/{b}" for a, b in karaka_ties))

    return {
        "source_program": sp, "ayanamsa_id": ayanamsa_id,
        "planets": planets,
        "ambiguity": {"varga_flips": ambiguous, "karaka_ties": karaka_ties},
        "warnings": warnings,
        "unavailable": [
            "Lagna/houses", "Vimshottari and all dashas", "Chara dasha",
            "Ashtakavarga", "transits and timing windows",
            "anything requiring the birth instant"],
        "note": "Pasted longitudes carry the pasted precision; ambiguities are "
                "flagged, never resolved by guessing.",
    }
