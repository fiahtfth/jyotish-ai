"""Daily panchang and activity-timing suggestions (electional layer).

Two entry points, both deterministic and LLM-free:

  - daily_panchang(when, place, facts=None): the five limbs for a date at
    a place (tithi, nakshatra, yoga, karana, vaara — computed at local
    sunrise, the traditional convention) plus the classical day windows
    (rahu kaalam, yamaganda, gulika, durmuhurta, abhijit muhurta) and,
    when a natal chart is supplied, the personal layer: nava-tara of the
    day and chandrashtama. Needs only the natal Moon, so it is safe for
    uncalibrated charts.

  - suggest_days(facts, birth, activity, start, days): ranks the coming
    days for an activity. All scoring rules below are frozen — fixed
    before inspecting output, never tuned after.
"""
from datetime import date, timedelta

from jhora import utils
from jhora.panchanga import drik

from . import constants as K
from .engine import BirthInput, engine
from .precision import ADVERSE_TARAS, TARA_NAMES, nak_index, tara_of

# ------------------------------------------------------------------ name tables

TITHI_NAMES = ["Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
               "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
               "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi"]
# tithi 15 = Purnima, 30 = Amavasya

YOGA_NAMES = ["Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana",
              "Atiganda", "Sukarma", "Dhriti", "Shula", "Ganda", "Vriddhi",
              "Dhruva", "Vyaghata", "Harshana", "Vajra", "Siddhi",
              "Vyatipata", "Variyana", "Parigha", "Shiva", "Siddha",
              "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti"]

KARANA_MOVABLE = ["Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija",
                  "Vishti"]
KARANA_FIXED = {1: "Kimstughna", 58: "Shakuni", 59: "Chatushpada",
                60: "Naga"}           # Naga = Kinstugna in some tables

VAARA_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
               "Friday", "Saturday"]
VAARA_LORDS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus",
               "Saturn"]

# ------------------------------------------------------------------ frozen rules
# Weights and exclusions were fixed before seeing any results — do not
# retune them after comparing outcomes.

# Tithi classes by (tithi - 1) % 15: Nanda 1/6/11, Bhadra 2/7/12,
# Jaya 3/8/13, Rikta 4/9/14, Purna 5/10/15 (classical grouping).
_TITHI_CLASS = {0: "Nanda", 5: "Nanda", 10: "Nanda",
                1: "Bhadra", 6: "Bhadra", 11: "Bhadra",
                2: "Jaya", 7: "Jaya", 12: "Jaya",
                3: "Rikta", 8: "Rikta", 13: "Rikta",
                4: "Purna", 9: "Purna"}
FAVOURABLE_TITHIS = {"Nanda", "Bhadra", "Jaya", "Purna"}
RIKTA = "Rikta"                       # "empty" tithis — no new undertakings
HARSH_YOGAS = {6, 9, 10, 17, 19, 27}  # Atiganda, Shula, Ganda, Vyatipata,
                                      # Parigha, Vaidhriti
VISHTI = "Vishti"                     # Bhadra karana — new work is avoided

_FAVOURABLE_TARAS = {2, 4, 6, 8, 9}   # Sampat, Kshema, Sadhak, Mitra,
                                      # Parama Mitra

# activity -> preferred vaara (0=Sun..6=Sat) and nakshatra indices (1..27).
# Compact classical lists; a hit adds weight, a miss is not a fault.
ACTIVITY_PREFERENCES = {
    "general":      {"vaara": {1, 3, 4, 5},
                     "nakshatra": {4, 5, 8, 13, 15, 17, 22, 27}},
    "new_work":     {"vaara": {3, 4, 5},
                     "nakshatra": {1, 4, 5, 8, 13, 14, 17, 22, 27}},
    "finance":      {"vaara": {4, 5},
                     "nakshatra": {4, 7, 10, 12, 13, 15, 17, 22}},
    "travel":       {"vaara": {1, 3, 5},
                     "nakshatra": {1, 5, 7, 13, 17, 18, 22, 27}},
    "education":    {"vaara": {3, 4},
                     "nakshatra": {1, 5, 6, 7, 8, 13, 14, 15, 22}},
    "home":         {"vaara": {4, 5},
                     "nakshatra": {4, 5, 12, 17, 21, 24, 26, 27}},
    "relationship": {"vaara": {1, 3, 4, 5},
                     "nakshatra": {4, 5, 10, 12, 13, 15, 17, 21, 26, 27}},
    "health":       {"vaara": {1, 3, 4},
                     "nakshatra": {1, 4, 13, 14, 22, 23, 24, 27}},
}

# keyword -> activity bucket (first match wins; specific contexts like
# house/vehicle/health come before the generic finance verb "buy")
ACTIVITY_KEYWORDS = [
    ("home", ["house", "home", "property", "construct", "vehicle", "car",
              "flat", "griha", "renovat"]),
    ("relationship", ["marriage", "wedding", "engag", "propose", "partner",
                      "relationship", "spouse", "marry"]),
    ("health", ["surgery", "medical", "treatment", "doctor", "health",
                "operation", "therapy"]),
    ("education", ["exam", "study", "admission", "interview", "course",
                   "learn", "college", "school", "degree"]),
    ("travel", ["travel", "journey", "trip", "flight", "abroad", "relocat",
                "move", "shift"]),
    ("new_work", ["start", "new job", "join", "launch", "begin", "venture",
                  "business", "found", "open a", "inaugurat"]),
    ("finance", ["invest", "money", "loan", "contract", "sign a", "deal",
                 "buy", "purchase", "sell", "financ", "bank", "payment"]),
]

_TOP_DAYS = 3
_WINDOW_MINUTES = 60
_SCAN_STEP_MIN = 15


# ------------------------------------------------------------------ helpers

def _jd_noon(d: date) -> float:
    return utils.julian_day_number((d.year, d.month, d.day), (12, 0, 0))


def place_of(birth: BirthInput):
    return drik.Place(birth.place_label, birth.lat, birth.lon,
                      birth.tz_offset)


def _hhmm(hours: float) -> str:
    """Float hours from local midnight -> 'HH:MM' (mod 24)."""
    h = hours % 24
    return f"{int(h):02d}:{round((h % 1) * 60):02d}"


def _dms_to_hours(s: str) -> float:
    h, m, sec = s.split(":")
    return int(h) + int(m) / 60 + int(sec) / 3600


def _slot(hours: float) -> dict:
    """Float-hours value -> display time + which civil day it lands on."""
    return {"time": _hhmm(hours),
            "day_offset": -1 if hours < 0 else (1 if hours >= 24 else 0)}


def _tithi_name(idx: int) -> str:
    if idx == 15:
        return "Purnima"
    if idx == 30:
        return "Amavasya"
    return TITHI_NAMES[(idx - 1) % 15]


def _tithi_class(idx: int) -> str:
    if idx in (15, 30):
        return "Purna"
    return _TITHI_CLASS[(idx - 1) % 15]


def _karana_name(idx: int) -> str:
    if idx in KARANA_FIXED:
        return KARANA_FIXED[idx]
    return KARANA_MOVABLE[(idx - 2) % 7]


def _moon_abs_at(when: date, place) -> float | None:
    pos = engine.transit_positions((when.year, when.month, when.day), place)
    rec = pos.get("Moon")
    return (rec["sign"] * 30 + rec["degree"]) % 360 if rec else None


# ------------------------------------------------------------------ panchang

def daily_panchang(when: date, place, facts=None) -> dict:
    """Five limbs at local sunrise + day windows; personalized if `facts`."""
    jd = _jd_noon(when)
    sr = drik.sunrise(jd, place)
    ss = drik.sunset(jd, place)
    sr_jd = sr[2]

    t_res = drik.tithi(sr_jd, place)
    nak_res = drik.nakshatra(sr_jd, place)
    yg_res = drik.yogam(sr_jd, place)
    k_idx, k_start, k_end = drik.karana(sr_jd, place)
    vaara = drik.vaara(sr_jd, place)

    moon_abs = _moon_abs_at(when, place)

    out = {
        "date": when.isoformat(),
        "vaara": {"index": vaara, "name": VAARA_NAMES[vaara],
                  "lord": VAARA_LORDS[vaara]},
        "tithi": {"index": t_res[0], "name": _tithi_name(t_res[0]),
                  "paksha": "Shukla" if t_res[0] <= 15 else "Krishna",
                  "class": _tithi_class(t_res[0]),
                  "start": _slot(t_res[1]), "end": _slot(t_res[2])},
        "nakshatra": {"index": nak_res[0], "name": K.NAKSHATRAS[nak_res[0] - 1],
                      "pada": nak_res[1],
                      "start": _slot(nak_res[2]), "end": _slot(nak_res[3])},
        "yoga": {"index": yg_res[0], "name": YOGA_NAMES[yg_res[0] - 1],
                 "start": _slot(yg_res[1]), "end": _slot(yg_res[2])},
        "karana": {"index": k_idx, "name": _karana_name(k_idx),
                   "start": _slot(k_start), "end": _slot(k_end)},
        "sunrise": _slot(sr[0]), "sunset": _slot(ss[0]),
        "windows": {
            "rahu_kaalam": drik.raahu_kaalam(jd, place),
            "yamaganda": drik.yamaganda_kaalam(jd, place),
            "gulika": drik.gulikai_kaalam(jd, place),
            "durmuhurta": drik.durmuhurtam(jd, place),
            "abhijit": drik.abhijit_muhurta(jd, place),
        },
        "moon": ({"sign": int(moon_abs // 30),
                  "sign_name": K.SIGN_NAMES[int(moon_abs // 30)]}
                 if moon_abs is not None else None),
    }

    if facts:
        janma = facts["planets"]["Moon"]["nakshatra"]["index"]
        natal_sign = facts["planets"]["Moon"]["sign"]
        day_nak = nak_res[0]
        ti, tn = tara_of(day_nak, janma)
        out["personal"] = {
            "janma_nakshatra": facts["planets"]["Moon"]["nakshatra"]["name"],
            "tara": {"index": ti, "name": tn, "adverse": ti in ADVERSE_TARAS},
            "chandrashtama": (moon_abs is not None and
                              (int(moon_abs // 30) - natal_sign) % 12 == 7),
        }
    return out


def detect_activity(text: str) -> str:
    t = text.lower()
    for activity, keys in ACTIVITY_KEYWORDS:
        if any(k in t for k in keys):
            return activity
    return "general"


# ------------------------------------------------------------------ day scoring

def _avoid_intervals(pan: dict) -> list[tuple[float, float]]:
    """Daylight hours to avoid, in decimal local hours."""
    out = []
    for key in ("rahu_kaalam", "yamaganda", "gulika"):
        s, e = pan["windows"][key]
        out.append((_dms_to_hours(s), _dms_to_hours(e)))
    dm = pan["windows"]["durmuhurta"]
    for i in range(0, len(dm), 2):
        out.append((_dms_to_hours(dm[i]), _dms_to_hours(dm[i + 1])))
    return out


def _clean_window(pan: dict) -> dict | None:
    """Earliest _WINDOW_MINUTES daylight block clear of all avoid slots —
    the abhijit muhurta itself when it happens to be clean."""
    avoid = _avoid_intervals(pan)
    ab = pan["windows"]["abhijit"]
    ab_s, ab_e = _dms_to_hours(ab[0]), _dms_to_hours(ab[1])

    def overlaps(s: float, e: float) -> bool:
        return any(s < ae and e > as_ for as_, ae in avoid)

    if not overlaps(ab_s, ab_e):
        return {"start": _hhmm(ab_s), "end": _hhmm(ab_e), "kind": "abhijit"}

    rise = pan["sunrise"]["time"]; rise_h = _dms_to_hours(rise + ":00" if len(rise) == 5 else rise)
    set_h = _dms_to_hours(pan["sunset"]["time"] + ":00"
                          if len(pan["sunset"]["time"]) == 5
                          else pan["sunset"]["time"])
    step = _SCAN_STEP_MIN / 60
    span = _WINDOW_MINUTES / 60
    s = rise_h
    while s + span <= set_h:
        if not overlaps(s, s + span):
            return {"start": _hhmm(s), "end": _hhmm(s + span), "kind": "open"}
        s += step
    return None


def _score_day(facts, birth: BirthInput, place, when: date,
               activity: str) -> dict | None:
    """One day's score for the activity; None when classically excluded."""
    pan = daily_panchang(when, place, facts)
    reasons, excluded = [], []

    tara = pan["personal"]["tara"]
    if tara["adverse"]:
        excluded.append(f"{tara['name']} tara")
    if pan["personal"]["chandrashtama"]:
        excluded.append("Moon in the 8th from the natal Moon (chandrashtama)")
    if pan["karana"]["name"] == VISHTI:
        excluded.append("Vishti (Bhadra) karana at sunrise")
    if pan["yoga"]["index"] in HARSH_YOGAS:
        excluded.append(f"{pan['yoga']['name']} yoga")
    if pan["tithi"]["index"] == 30:
        excluded.append("Amavasya")
    elif pan["tithi"]["class"] == RIKTA:
        excluded.append("Rikta tithi")
    if excluded:
        return {"date": when.isoformat(), "excluded": excluded}

    score = 0
    if tara["index"] in _FAVOURABLE_TARAS:
        score += 2
        reasons.append(f"{tara['name']} tara")
    if pan["tithi"]["class"] in FAVOURABLE_TITHIS:
        score += 1
        reasons.append(f"{pan['tithi']['class']} tithi "
                       f"({pan['tithi']['name']}, {pan['tithi']['paksha']})")
    pref = ACTIVITY_PREFERENCES[activity]
    if pan["vaara"]["index"] in pref["vaara"]:
        score += 1
        reasons.append(f"{pan['vaara']['name']} — {pan['vaara']['lord']}'s day")
    if pan["nakshatra"]["index"] in pref["nakshatra"]:
        score += 1
        reasons.append(f"{pan['nakshatra']['name']} nakshatra")

    return {"date": when.isoformat(), "score": score, "reasons": reasons,
            "suggested_window": _clean_window(pan),
            "avoid": {k: v for k, v in pan["windows"].items()
                      if k != "abhijit"},
            "limbs": {"tithi": pan["tithi"]["name"],
                      "nakshatra": pan["nakshatra"]["name"],
                      "yoga": pan["yoga"]["name"],
                      "karana": pan["karana"]["name"],
                      "vaara": pan["vaara"]["name"]}}


def suggest_days(facts, birth: BirthInput, start: date, days: int = 60,
                 activity: str = "general") -> dict:
    """Rank the next `days` days for `activity`.

    Days carrying a classical exclusion (adverse tara, chandrashtama,
    Vishti karana, harsh yoga, Amavasya/Rikta tithi) are reported as
    excluded rather than silently dropped. The rest are scored with the
    frozen weights: favourable tara +2, favourable tithi class +1,
    preferred weekday +1, preferred nakshatra +1.
    """
    place = place_of(birth)
    scored, excluded = [], []
    for i in range(days):
        r = _score_day(facts, birth, place, start + timedelta(days=i),
                       activity)
        (excluded if "excluded" in r else scored).append(r)
    scored.sort(key=lambda r: (-r["score"], r["date"]))
    return {"activity": activity, "scanned_days": days,
            "from": start.isoformat(),
            "days": scored[:_TOP_DAYS],
            "excluded_days": len(excluded)}
