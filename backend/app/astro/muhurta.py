"""Muhurta (electional) search over real time windows at a chosen location.

Unlike `panchang.suggest_days` (one score per day at sunrise), this scans
15-minute steps between sunrise and sunset (plus the evening for vivah) and
evaluates the actual Moon/Sun/Lagna of every step at the given latitude and
longitude.

Structure per step:
  - hard exclusions (the step is rejected and counted by reason): Rahu Kaal,
    Yamaganda, Gulika, Vishti (Bhadra) karana, Rikta tithi / Amavasya,
    Vyatipata and Vaidhriti yogas, Chandrashtama and adverse Tara for the
    native, and for vivah / griha pravesh also Kharmas, combust Jupiter or
    Venus, Adhik maas (griha pravesh adds Panchaka);
  - soft factors (each passes or fails; the slot badge is "k/N"): weekday,
    tithi, nakshatra, yoga, Tara and Chandra bala, Lagna type, 8th house
    empty, benefics in kendra/trikona, malefics in 3/6/11, Moon not in
    6/8/12, Panchaka-rahita, outside Durmuhurta, good choghadiya, waxing
    Moon (where relevant).
  - Abhijit muhurta is reported as a bonus (not valid on Wednesdays).

Each rule has an id, a source tag and a `verified` flag. Only the
long-standing well-known rules are marked verified; per-event nakshatra and
tithi lists other than vivah vary between texts and are marked False.
"""
import threading
from datetime import date, datetime, timedelta

from jhora import const, utils
from jhora.panchanga import drik

from .. import geo
from . import constants as K
from . import panchang as P
from .engine import apply, calc_lock
from .precision import ADVERSE_TARAS, TARA_NAMES, tara_of

STEP_MIN = 15
MAX_DAYS = 45
SRC_MC = "Muhurta Chintamani"
SRC_BPHS = "BPHS / Brihat Samhita (general)"
SRC_LOCAL = "Common panchanga practice"

# ------------------------------------------------------------------ rule tables
# nakshatra numbers 1..27, tithi numbers 1..15 (paksha-agnostic), vaara 0=Sun..6=Sat

EVENTS = {
    "vivah": {
        "label": "Vivah (marriage)",
        "tithis": {2, 3, 5, 7, 10, 11, 13}, "nakshatras": {4, 5, 10, 12, 13, 15, 17, 19, 21, 26, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {1, 2, 3, 5, 6, 8, 11},
        "lagna_note": "Taurus, Gemini, Cancer, Virgo, Libra, Sagittarius, Pisces (common vivah lagna list)",
        "verified": True, "source": SRC_MC + " (vivaha prakarana)",
        "hard": {"kharmas", "combust", "adhik"}, "waxing": True, "night": True},
    "griha_pravesh": {
        "label": "Griha pravesh (house-warming)",
        "tithis": {2, 3, 5, 7, 10, 11, 13}, "nakshatras": {4, 5, 12, 14, 17, 21, 23, 24, 26, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {1, 4, 7, 10},
        "lagna_note": "fixed (sthira) signs Taurus, Leo, Scorpio, Aquarius",
        "verified": False, "source": SRC_MC + " (vastu / griha pravesha)",
        "hard": {"kharmas", "combust", "adhik", "panchaka"}, "waxing": True, "night": False},
    "vehicle": {
        "label": "Vehicle purchase",
        "tithis": {1, 2, 3, 5, 6, 7, 10, 11, 12, 13, 15}, "nakshatras": {1, 5, 7, 8, 13, 14, 15, 17, 22, 23, 24, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {0, 2, 3, 5, 6, 8, 9, 11},
        "lagna_note": "movable and dual signs",
        "verified": False, "source": SRC_MC + " (Kshipra/Mridu/Chara nakshatra groups)",
        "hard": set(), "waxing": False, "night": False},
    "business": {
        "label": "Business start",
        "tithis": {1, 2, 3, 5, 6, 7, 10, 11, 12, 13}, "nakshatras": {1, 4, 5, 8, 12, 13, 14, 17, 21, 22, 23, 26, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {1, 2, 4, 5, 7, 8, 10, 11},
        "lagna_note": "fixed and dual signs",
        "verified": False, "source": SRC_LOCAL,
        "hard": set(), "waxing": True, "night": False},
    "property": {
        "label": "Property purchase",
        "tithis": {2, 3, 5, 7, 10, 11, 13}, "nakshatras": {4, 5, 12, 14, 17, 21, 22, 23, 26, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {1, 4, 7, 10},
        "lagna_note": "fixed (sthira) signs",
        "verified": False, "source": SRC_LOCAL,
        "hard": set(), "waxing": True, "night": False},
    "travel": {
        "label": "Travel (yatra)",
        "tithis": {1, 2, 3, 5, 6, 7, 10, 11, 12, 13}, "nakshatras": {1, 5, 7, 8, 13, 17, 22, 23, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": {0, 3, 6, 9},
        "lagna_note": "movable (chara) signs",
        "verified": False, "source": SRC_MC + " (yatra prakarana)",
        "hard": set(), "waxing": False, "night": False},
    "namkaran": {
        "label": "Namkaran (naming ceremony)",
        "tithis": {2, 3, 5, 7, 10, 11, 12, 13},
        "nakshatras": {1, 4, 5, 8, 12, 13, 14, 15, 17, 21, 22, 23, 24, 26, 27},
        "vaaras": {1, 3, 4, 5}, "lagna_signs": None, "lagna_note": "no Lagna restriction applied",
        "verified": False, "source": SRC_LOCAL,
        "hard": set(), "waxing": False, "night": False},
}

CHANDRABALA_GOOD = {1, 3, 6, 7, 10, 11}
# Disha Shula: direction to avoid by weekday (0=Sun..6=Sat)
DISHA_SHULA = {0: "west", 1: "east", 2: "north", 3: "south", 4: "west", 5: "west", 6: "east"}

RULES = [
    {"id": "X-RAHU", "label": "Rahu Kaal avoided", "source": SRC_LOCAL, "verified": True},
    {"id": "X-YAMA", "label": "Yamaganda avoided", "source": SRC_LOCAL, "verified": True},
    {"id": "X-GULIKA", "label": "Gulika Kaal avoided", "source": SRC_LOCAL, "verified": True},
    {"id": "X-VISHTI", "label": "Vishti (Bhadra) karana avoided", "source": SRC_MC, "verified": True},
    {"id": "X-RIKTA", "label": "Rikta tithi (4/9/14) and Amavasya avoided", "source": SRC_MC, "verified": True},
    {"id": "X-YOGA", "label": "Vyatipata and Vaidhriti yogas avoided", "source": SRC_MC, "verified": True},
    {"id": "X-CHANDRASHTAMA", "label": "Moon not in the 8th from the native's Moon", "source": SRC_MC, "verified": True},
    {"id": "X-TARA", "label": "Tarabala: Vipat/Pratyak/Naidhana avoided", "source": SRC_MC, "verified": True},
    {"id": "X-KHARMAS", "label": "Kharmas (Sun in Sagittarius/Pisces) avoided for vivah and griha pravesh",
     "source": SRC_LOCAL, "verified": True},
    {"id": "X-COMBUST", "label": "Jupiter/Venus combustion (asta) avoided for vivah and griha pravesh",
     "source": SRC_MC, "verified": True},
    {"id": "X-ADHIK", "label": "Adhik maas avoided for vivah and griha pravesh", "source": SRC_LOCAL, "verified": True},
    {"id": "X-PANCHAKA", "label": "Panchaka (Mrityu/Agni/Raja/Chora/Roga) avoided for griha pravesh",
     "source": SRC_MC, "verified": True},
    {"id": "F-VARA", "label": "Favourable weekday", "source": SRC_MC, "verified": True},
    {"id": "F-TITHI", "label": "Favourable tithi for the event", "source": SRC_MC, "verified": "per event"},
    {"id": "F-NAK", "label": "Favourable nakshatra for the event", "source": SRC_MC, "verified": "per event"},
    {"id": "F-YOGA", "label": "Yoga is not Vishkambha/Atiganda/Shula/Ganda/Parigha", "source": SRC_MC, "verified": True},
    {"id": "F-TARA", "label": "Tarabala favourable", "source": SRC_MC, "verified": True},
    {"id": "F-CHANDRA", "label": "Chandrabala: Moon in 1/3/6/7/10/11 from natal Moon", "source": SRC_MC, "verified": True},
    {"id": "F-LAGNA", "label": "Muhurta Lagna of a suitable type for the event", "source": SRC_MC, "verified": "per event"},
    {"id": "F-8H", "label": "8th house from the muhurta Lagna empty", "source": SRC_MC, "verified": True},
    {"id": "F-BEN", "label": "A benefic (Jupiter/Venus/Mercury/waxing Moon) in a kendra or trikona",
     "source": SRC_MC, "verified": True},
    {"id": "F-MAL", "label": "Sun, Mars and Saturn only in the 3rd/6th/11th", "source": SRC_MC, "verified": True},
    {"id": "F-MOON", "label": "Moon not in the 6th/8th/12th from the muhurta Lagna", "source": SRC_MC, "verified": True},
    {"id": "F-PANCHAKA", "label": "Panchaka-rahita (tithi+vara+nakshatra+lagna remainder)",
     "source": SRC_MC, "verified": True},
    {"id": "F-DURM", "label": "Outside Durmuhurta", "source": SRC_LOCAL, "verified": True},
    {"id": "F-CHOG", "label": "Good choghadiya (Amrit/Shubha/Laabha/Chara)", "source": SRC_LOCAL, "verified": False},
    {"id": "F-PAKSHA", "label": "Waxing (Shukla paksha) Moon", "source": SRC_MC, "verified": True},
    {"id": "B-ABHIJIT", "label": "Abhijit muhurta (bonus; not on Wednesday)", "source": SRC_LOCAL, "verified": True},
]
_RULE = {r["id"]: r for r in RULES}


def _cat(rule_id: str, **extra) -> dict:
    return {**_RULE[rule_id], **extra}


# ------------------------------------------------------------------ location helpers

def place_for(lat: float, lon: float, name: str, on: date) -> "drik.Place":
    fallback = round(lon / 15.0 * 2) / 2
    tz = geo.historical_utc_offset(lat, lon, datetime(on.year, on.month, on.day, 12), fallback)
    return drik.Place(name or "Location", lat, lon, tz)


def _slow_retro(jd_utc: float, planet) -> bool:
    a = drik.sidereal_longitude(jd_utc, planet)
    b = drik.sidereal_longitude(jd_utc + 0.5, planet)
    return ((b - a + 180) % 360 - 180) < 0


def _hm(h: float) -> str:
    m = round(h * 60)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


# ------------------------------------------------------------------ per-day context

def _day_context(on: date, place, settings_birth=None) -> dict:
    jd = P._jd_noon(on)
    sr = drik.sunrise(jd, place)
    ss = drik.sunset(jd, place)
    vaara = drik.vaara(jd, place)

    def span(pair):
        return (P._dms_to_hours(pair[0]), P._dms_to_hours(pair[1]))
    w = {"X-RAHU": span(drik.raahu_kaalam(jd, place)),
         "X-YAMA": span(drik.yamaganda_kaalam(jd, place)),
         "X-GULIKA": span(drik.gulikai_kaalam(jd, place))}
    dm = drik.durmuhurtam(jd, place)
    durm = [(P._dms_to_hours(dm[i]), P._dms_to_hours(dm[i + 1])) for i in range(0, len(dm) - 1, 2)]
    ab = drik.abhijit_muhurta(jd, place)
    try:
        adhik = bool(drik.lunar_month(sr[2], place)[1])
    except Exception:
        adhik = False
    jd_utc = jd - place.timezone / 24
    try:
        chog = P._choghadiya(jd, place)
        chog_day = [(P._dms_to_hours(c["start"] + ":00"), P._dms_to_hours(c["end"] + ":00"), c["good"], c["name"])
                    for c in chog["day"]]
        chog_night = [(P._dms_to_hours(c["start"] + ":00"), P._dms_to_hours(c["end"] + ":00"), c["good"], c["name"])
                      for c in chog["night"]]
    except Exception:
        chog_day, chog_night = [], []
    return {"date": on, "place": place, "jd": jd, "vaara": vaara,
            "sunrise": sr[0], "sunset": ss[0], "windows": w, "durm": durm,
            "abhijit": span(ab), "adhik": adhik,
            "jup_retro": _slow_retro(jd_utc, const._JUPITER),
            "ven_retro": _slow_retro(jd_utc, const._VENUS),
            "choghadiya": chog_day + [(a if a >= 12 else a + 24, b if b > a else b + 24, g, n)
                                      for a, b, g, n in chog_night]}


def _in(t0: float, t1: float, spans) -> bool:
    return any(t0 < e and t1 > s for s, e in spans)


# ------------------------------------------------------------------ one step

_PL = [const._SUN, const._MOON, const._MARS, const._MERCURY, const._JUPITER, const._VENUS, const._SATURN]


def _step_state(day: dict, hour: float) -> dict:
    place = day["place"]
    d = day["date"]
    h = int(hour)
    mnt = int(round((hour - h) * 60))
    jd_local = utils.julian_day_number((d.year, d.month, d.day), (h % 24, mnt % 60, 0)) + (1 if h >= 24 else 0)
    jd_utc = jd_local - place.timezone / 24
    lon = [drik.sidereal_longitude(jd_utc, p) % 360 for p in _PL]
    rahu = drik.sidereal_longitude(jd_utc, const._RAHU) % 360
    lon += [rahu, (rahu + 180) % 360]
    sun, moon = lon[0], lon[1]
    elong = (moon - sun) % 360
    asc = drik.ascendant(jd_local, place)
    lagna_sign = int(asc[0])
    return {"lon": lon, "sun": sun, "moon": moon,
            "tithi": int(elong // 12) + 1, "karana": int(elong // 6) + 1,
            "nak": int(moon // K.NAK_SPAN) + 1, "pada": int((moon % K.NAK_SPAN) // (K.NAK_SPAN / 4)) + 1,
            "yoga": int(((sun + moon) % 360) // K.NAK_SPAN) + 1,
            "moon_sign": int(moon // 30), "sun_sign": int(sun // 30),
            "lagna_sign": lagna_sign, "lagna_deg": float(asc[1]),
            "houses": [((int(l // 30) - lagna_sign) % 12) + 1 for l in lon]}


def _combust(day: dict, st: dict, pid: int, retro: bool) -> bool:
    orb = K.combust_orb(pid, retro)
    if not orb:
        return False
    sep = abs(st["lon"][pid] - st["sun"])
    return min(sep, 360 - sep) < orb


def _evaluate(day: dict, hour: float, ev_key: str, native: dict | None, direction: str | None) -> dict:
    ev = EVENTS[ev_key]
    st = _step_state(day, hour)
    t1 = hour + STEP_MIN / 60
    excl: list[tuple[str, str]] = []
    vaara = day["vaara"]

    for rid, label in (("X-RAHU", "Rahu Kaal"), ("X-YAMA", "Yamaganda"), ("X-GULIKA", "Gulika Kaal")):
        if _in(hour, t1, [day["windows"][rid]]):
            excl.append((rid, label))
    if P._karana_name(st["karana"]) == P.VISHTI:
        excl.append(("X-VISHTI", "Vishti (Bhadra) karana"))
    if st["tithi"] == 30:
        excl.append(("X-RIKTA", "Amavasya"))
    elif P._tithi_class(st["tithi"]) == P.RIKTA:
        excl.append(("X-RIKTA", "Rikta tithi"))
    if st["yoga"] in (17, 27):
        excl.append(("X-YOGA", f"{P.YOGA_NAMES[st['yoga'] - 1]} yoga"))

    tara_idx = chandra_house = None
    if native:
        tara_idx, _ = tara_of(st["nak"], native["nak"])
        chandra_house = (st["moon_sign"] - native["sign"]) % 12 + 1
        if chandra_house == 8:
            excl.append(("X-CHANDRASHTAMA", "Chandrashtama (Moon 8th from natal Moon)"))
        if tara_idx in ADVERSE_TARAS:
            excl.append(("X-TARA", f"{TARA_NAMES[tara_idx - 1]} tara"))

    hard = ev["hard"]
    if "kharmas" in hard and st["sun_sign"] in (8, 11):
        excl.append(("X-KHARMAS", "Kharmas (Sun in Sagittarius/Pisces)"))
    if "combust" in hard:
        if _combust(day, st, 4, day["jup_retro"]):
            excl.append(("X-COMBUST", "Jupiter combust (Guru asta)"))
        if _combust(day, st, 5, day["ven_retro"]):
            excl.append(("X-COMBUST", "Venus combust (Shukra asta)"))
    if "adhik" in hard and day["adhik"]:
        excl.append(("X-ADHIK", "Adhik maas"))

    # Panchaka rahita: (tithi + vaara(1..7) + nakshatra + lagna(1..12)) mod 9
    pan_rem = (st["tithi"] + (vaara + 1) + st["nak"] + st["lagna_sign"] + 1) % 9
    panchaka_bad = pan_rem in (1, 2, 4, 6, 8)
    pan_name = {1: "Mrityu", 2: "Agni", 4: "Raja", 6: "Chora", 8: "Roga"}.get(pan_rem)
    if "panchaka" in hard and panchaka_bad:
        excl.append(("X-PANCHAKA", f"{pan_name} Panchaka"))

    if excl:
        return {"excluded": excl, "state": st}

    # ---- soft factors
    tithi15 = (st["tithi"] - 1) % 15 + 1
    h = st["houses"]
    factors = []

    def add(rid, ok, detail=""):
        factors.append(_cat(rid, ok=bool(ok), detail=detail))

    add("F-VARA", vaara in ev["vaaras"], P.VAARA_NAMES[vaara])
    add("F-TITHI", tithi15 in ev["tithis"], P._tithi_name(st["tithi"]))
    add("F-NAK", st["nak"] in ev["nakshatras"], K.NAKSHATRAS[st["nak"] - 1])
    add("F-YOGA", st["yoga"] not in P.HARSH_YOGAS, P.YOGA_NAMES[st["yoga"] - 1])
    if native:
        add("F-TARA", tara_idx not in ADVERSE_TARAS and tara_idx != 1,
            TARA_NAMES[tara_idx - 1])
        add("F-CHANDRA", chandra_house in CHANDRABALA_GOOD, f"Moon {chandra_house}th from natal Moon")
    if ev["lagna_signs"] is not None:
        add("F-LAGNA", st["lagna_sign"] in ev["lagna_signs"], K.SIGN_NAMES[st["lagna_sign"]])
    add("F-8H", 8 not in h[:9] and 8 not in h[9:], "")
    benef = [(i, h[i]) for i in (1, 3, 4, 5)]               # Moon, Mercury, Jupiter, Venus
    waxing = st["tithi"] <= 15
    add("F-BEN", any(hh in (1, 4, 5, 7, 9, 10) for i, hh in benef if i != 1 or waxing), "")
    add("F-MAL", all(h[i] in (3, 6, 11) for i in (0, 2, 6)), "")
    add("F-MOON", h[1] not in (6, 8, 12), f"Moon in house {h[1]}")
    add("F-PANCHAKA", not panchaka_bad, pan_name or "none")
    add("F-DURM", not _in(hour, t1, day["durm"]), "")
    cs = [g for a, b, g, n in day["choghadiya"] if a <= hour < b]
    add("F-CHOG", bool(cs and cs[0]), next((n for a, b, g, n in day["choghadiya"] if a <= hour < b), ""))
    if ev["waxing"]:
        add("F-PAKSHA", waxing, "Shukla" if waxing else "Krishna")

    bonus = []
    if vaara != 3 and day["abhijit"][0] <= hour and hour + STEP_MIN / 60 <= day["abhijit"][1] + 1e-9:
        bonus.append(_cat("B-ABHIJIT"))
    warns = []
    if direction and DISHA_SHULA[vaara] == direction.lower():
        warns.append(f"Disha Shula: avoid travelling {direction} on {P.VAARA_NAMES[vaara]}")
    return {"excluded": [], "state": st, "factors": factors, "bonus": bonus, "warnings": warns}


# ------------------------------------------------------------------ scan

_scan_lock = threading.Lock()


def scan(event: str, start: date, end: date, lat: float, lon: float, place_name: str = "",
         native_facts: dict | None = None, settings=None, direction: str | None = None,
         top: int = 8) -> dict:
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}")
    if end < start:
        raise ValueError("end must not precede start")
    days = (end - start).days + 1
    if days > MAX_DAYS:
        raise ValueError(f"date range too long (max {MAX_DAYS} days)")
    ev = EVENTS[event]
    native = None
    if native_facts:
        m = native_facts["planets"]["Moon"]
        native = {"nak": int(m["nakshatra"]["index"]), "sign": int(m["sign"]),
                  "nak_name": m["nakshatra"]["name"]}

    slots, by_reason, ex_examples, steps_total, steps_ok = [], {}, [], 0, 0
    with calc_lock:
        if settings is not None:
            apply(settings)
        for i in range(days):
            on = start + timedelta(days=i)
            place = place_for(lat, lon, place_name, on)
            day = _day_context(on, place)
            first = day["sunrise"]
            last = day["sunset"] + (4.0 if ev["night"] else 0.0)
            hour = first
            run = None
            while hour + STEP_MIN / 60 <= last + 1e-9:
                steps_total += 1
                r = _evaluate(day, hour, event, native, direction)
                if r["excluded"]:
                    for rid, label in r["excluded"]:
                        by_reason[label] = by_reason.get(label, 0) + 1
                    if len(ex_examples) < 12 and (not ex_examples or ex_examples[-1]["date"] != on.isoformat()
                                                  or ex_examples[-1]["reasons"] != [x[1] for x in r["excluded"]]):
                        ex_examples.append({"date": on.isoformat(), "time": _hm(hour),
                                            "reasons": [x[1] for x in r["excluded"]]})
                    run = None
                else:
                    steps_ok += 1
                    st = r["state"]
                    passed = sum(1 for f in r["factors"] if f["ok"])
                    key = (st["lagna_sign"], passed, st["nak"], st["tithi"])
                    if run is not None and run["key"] == key:
                        run["end"] = hour + STEP_MIN / 60
                    else:
                        run = {"key": key, "start": hour, "end": hour + STEP_MIN / 60,
                               "date": on, "r": r, "k": passed, "n": len(r["factors"])}
                        slots.append(run)
                hour += STEP_MIN / 60

    def render(s):
        r, st = s["r"], s["r"]["state"]
        return {
            "date": s["date"].isoformat(), "weekday": P.VAARA_NAMES[(s["date"].weekday() + 1) % 7],
            "start": _hm(s["start"]), "end": _hm(s["end"]),
            "lagna": K.SIGN_NAMES[st["lagna_sign"]],
            "k": s["k"], "n": s["n"], "badge": f"Muhurta factors satisfied: {s['k']}/{s['n']}",
            "tithi": P._tithi_name(st["tithi"]), "paksha": "Shukla" if st["tithi"] <= 15 else "Krishna",
            "nakshatra": K.NAKSHATRAS[st["nak"] - 1], "yoga": P.YOGA_NAMES[st["yoga"] - 1],
            "karana": P._karana_name(st["karana"]),
            "reasons": [f"{f['label']}" + (f" ({f['detail']})" if f["detail"] else "")
                        for f in r["factors"] if f["ok"]],
            "not_met": [f"{f['label']}" + (f" ({f['detail']})" if f["detail"] else "")
                        for f in r["factors"] if not f["ok"]],
            "factors": [{"id": f["id"], "label": f["label"], "ok": f["ok"], "verified": f["verified"]}
                        for f in r["factors"]],
            "bonus": [b["label"] for b in r["bonus"]], "warnings": r["warnings"],
        }

    # best by ratio then duration, at most 3 per day
    ranked = sorted(slots, key=lambda s: (-(s["k"] / max(s["n"], 1)), -(s["end"] - s["start"]), s["date"], s["start"]))
    chosen, per_day = [], {}
    for s in ranked:
        d = s["date"].isoformat()
        if per_day.get(d, 0) >= 3:
            continue
        per_day[d] = per_day.get(d, 0) + 1
        chosen.append(s)
        if len(chosen) >= top:
            break

    return {
        "event": event, "event_label": ev["label"],
        "location": {"name": place_name, "latitude": lat, "longitude": lon},
        "from": start.isoformat(), "to": end.isoformat(), "step_minutes": STEP_MIN,
        "native_moon": native["nak_name"] if native else None,
        "slots": [render(s) for s in chosen],
        "scanned_steps": steps_total, "accepted_steps": steps_ok,
        "excluded": {"steps": steps_total - steps_ok,
                     "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
                     "examples": ex_examples},
        "rules": [{**r} for r in RULES],
        "event_rules": {"lagna": ev["lagna_note"], "verified": ev["verified"], "source": ev["source"],
                        "note": ("Tithi, nakshatra and Lagna lists for this event follow one common reading "
                                 "of the texts and are marked unverified." if not ev["verified"] else
                                 "Tithi, nakshatra and weekday lists are the standard vivah lists.")},
        "disclaimer": ("Electional suggestions based on classical panchanga rules at the chosen location. "
                       "Confirm important dates with a qualified priest or astrologer."),
    }
