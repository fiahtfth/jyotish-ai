"""Precision layer on top of the four-pillar verdict.

Sits beside pillars.py. The pillar convergence stays the verdict; this
module adds four fixed filters:

  - Confirmation: Yogini dasha + Sudarshana Chakra (Moon/Sun frames
    always; Lagna frame only on calibrated charts).
  - Timing: slow-planet Kakshya spans (Jupiter/Saturn through bindu-
    charged 3 deg 45 min slices of domain-relevant signs) narrowed to
    2-4 week windows by fast triggers (Sun/Mars) and Tara Bala.
  - Magnitude: Shadbala + Ishta/Kashta Phala of the leading dasha lord
    (calibrated charts only) -> modest / notable / major.
  - Fast triggers: Tajika Ithasala from the year lord in the annual
    chart, and eclipses within 3 degrees of natal planets -> watch months.

Every rule and weight below was fixed before inspecting any output and
must not be tuned after results are seen. Each layer returns its own
verdict so the caller can record what every method said separately.
Lagna-dependent layers are skipped unless `calibrated` is true: the
Lagna moves ~1 deg every 4 minutes, so they are meaningless (and
misleading) without a trustworthy birth time.
"""
import json
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from jhora import utils, const
from jhora.panchanga import drik
from jhora.horoscope.chart import charts, ashtakavarga, strength
from jhora.horoscope.dhasa.graha import yogini
from jhora.horoscope.dhasa import sudharsana_chakra
from jhora.horoscope.transit import tajaka, tajaka_yoga

from . import constants as K
from . import pillars
from . import varsha
from .engine import BirthInput, apply as apply_settings, birth_fingerprint, calc_lock, engine

# ------------------------------------------------------------------ frozen rules

# Eight fixed slices per sign, 3 deg 45 min each, in the classical order.
KAKSHYA_SPAN = 30.0 / 8.0
# Contributor ids in the prastara matrix: 0..6 = Sun..Saturn, 7 = Lagna.
KAKSHYA_LORDS = [6, 4, 2, 0, 5, 3, 1, 7]   # Sat Jup Mar Sun Ven Merc Moon Lagna

TARA_NAMES = ["Janma", "Sampat", "Vipat", "Kshema", "Pratyari",
              "Sadhak", "Naidhana", "Mitra", "Parama Mitra"]
ADVERSE_TARAS = {3, 5, 7}                  # Vipat, Pratyari, Naidhana

ECLIPSE_HIT_ORB = 3.0
_MAX_ECLIPSES_PER_WINDOW = 12
_TIMING_STEP_DAYS = 7
_WINDOW_MAX_DAYS = 28
_MERGE_GAP_DAYS = 14
_TIMING_MIN_SCORE = 3        # charged slow planet (2) + fast trigger (1)
_TIMING_FALLBACK_SCORE = 2   # charged slow planet only

# magnitude thresholds (shadbala ratio x ishta phala out of 60)
_MAG_MAJOR = (1.3, 40)
_MAG_NOTABLE = (1.0, 15)

_SLOW = ("Jupiter", "Saturn")
_FAST = ("Sun", "Mars")
_DUSTHANA = (6, 8, 12)

_prastara_cache: "OrderedDict[str, list | None]" = OrderedDict()
_prastara_lock = threading.Lock()
_PRASTARA_CACHE_MAX = 64


# ------------------------------------------------------------------ small helpers

def _to_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _mid(d1: date, d2: date) -> date:
    return d1 + (d2 - d1) / 2


@contextmanager
def _frame(birth: BirthInput):
    """Hold the PyJHora global-state lock with this chart's calculation settings applied."""
    with calc_lock:
        apply_settings(birth.settings)
        yield


def _place(birth: BirthInput):
    return drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)


def _jd_birth(birth: BirthInput) -> float:
    return utils.julian_day_number((birth.year, birth.month, birth.day),
                                   (birth.hour, birth.minute, birth.second))


def _jd_noon(d: date) -> float:
    return utils.julian_day_number((d.year, d.month, d.day), (12, 0, 0))


def _ymd(jd_val) -> str:
    y, m, d, _ = utils.jd_to_gregorian(jd_val)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _tuple_ymd(t) -> str:
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


def _abs_long(rec) -> float:
    return (rec["sign"] * 30 + rec["degree"]) % 360


def _sep(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def kakshya_of(degree_in_sign: float) -> int:
    """Which of the eight fixed slices a within-sign degree falls in (0..7)."""
    return min(7, max(0, int(degree_in_sign / KAKSHYA_SPAN)))


def kakshya_lord(index: int) -> str:
    pid = KAKSHYA_LORDS[index]
    return "Lagna" if pid == 7 else K.PLANET_NAMES[pid]


def nak_index(abs_long: float) -> int:
    """Nakshatra number 1..27 for an absolute sidereal longitude."""
    return int(abs_long // K.NAK_SPAN) % 27 + 1


def tara_of(transit_nak: int, janma_nak: int) -> tuple[int, str]:
    """Nava-tara count (1..9) and name: janma nakshatra -> transit nakshatra."""
    n = (transit_nak - janma_nak) % 27 + 1
    t = (n - 1) % 9 + 1
    return t, TARA_NAMES[t - 1]


def _prastara(facts, birth: BirthInput):
    """Contributor-level ashtakavarga for the chart.

    prastara[p][c][s] == 1 when contributor c (0..6 planets, 7 Lagna)
    gave a bindu to planet p's BAV in sign s. Comes from the same
    get_ashtaka_varga call that produced facts["binnashtakavarga"], so
    summing contributors always matches the BAV; charts persisted before
    the field existed fall back to a fresh (cached) computation.
    """
    if cached := facts.get("prastara_ashtakavarga"):
        return cached
    key = birth_fingerprint(birth)
    with _prastara_lock:
        if key in _prastara_cache:
            _prastara_cache.move_to_end(key)
            return _prastara_cache[key]
    out = None
    try:
        with _frame(birth):
            rasi = charts.rasi_chart(_jd_birth(birth), _place(birth))
            h2p = utils.get_house_planet_list_from_planet_positions(rasi)
            _, _, out = ashtakavarga.get_ashtaka_varga(h2p)
    except Exception:
        out = None
    with _prastara_lock:
        _prastara_cache[key] = out
        _prastara_cache.move_to_end(key)
        while len(_prastara_cache) > _PRASTARA_CACHE_MAX:
            _prastara_cache.popitem(last=False)
    return out


def _kakshya_charged(prastara, transit_pid: int, sign: int, degree: float) -> bool:
    """The kakshya the transiting planet occupies is backed by a bindu its
    lord contributed to this sign in the transiting planet's own BAV."""
    if prastara is None:
        return False
    lord_id = KAKSHYA_LORDS[kakshya_of(degree)]
    try:
        return bool(prastara[transit_pid][lord_id][sign])
    except (IndexError, TypeError):
        return False


def _lord_houses(facts, lord: str) -> list[int]:
    return [h for h in range(1, 13) if facts["houses"][h]["lord"] == lord]


def _domain_signs(facts, domain: str, calibrated: bool) -> tuple[set, str]:
    """Signs the domain's houses fall on. Counted from Lagna when the birth
    time is trusted, else from the natal Moon (chandra lagna)."""
    ref = "lagna" if calibrated else "moon"
    ref_sign = facts["lagna"]["sign"] if calibrated else facts["planets"]["Moon"]["sign"]
    return {(ref_sign + h - 1) % 12 for h in K.DOMAINS[domain]["houses"]}, ref


# ------------------------------------------------------------------ confirmation

def _yogini_score(facts, domain: str, lords: list[str]) -> tuple[int, list[str]]:
    """Fixed scoring of yogini MD/AD lords against the domain."""
    spec_houses = set(K.DOMAINS[domain]["houses"])
    benefics = set(facts["functional"]["benefics"])
    maraka = set(facts["functional"]["maraka_lords"])
    yogakaraka = facts["functional"]["yogakaraka"]
    score, ev = 0, []
    for lord in dict.fromkeys(lords):
        owned = set(_lord_houses(facts, lord))
        rec = facts["planets"].get(lord)
        if owned & spec_houses:
            score += 1
            ev.append(f"Yogini lord {lord} rules house "
                      f"{'/'.join(str(h) for h in sorted(owned & spec_houses))}")
        if rec and rec["house"] in spec_houses:
            score += 1
            ev.append(f"Yogini lord {lord} sits in house {rec['house']}")
        if lord in benefics or lord == yogakaraka:
            score += 1
            ev.append(f"Yogini lord {lord} is a functional benefic for this lagna")
        if rec and "debilitated" in rec["dignity"]:
            score -= 1
            ev.append(f"Yogini lord {lord} debilitated in D1")
        if lord in maraka:
            score -= 1
            ev.append(f"Yogini lord {lord} is a maraka lord")
        if owned and owned <= set(_DUSTHANA):
            score -= 1
            ev.append(f"Yogini lord {lord} rules only dusthanas "
                      f"({'/'.join(str(h) for h in sorted(owned))})")
    return score, ev


def _yogini_at(facts, birth: BirthInput, domain: str, when: date) -> dict:
    with _frame(birth):
        rows = yogini.get_running_dhasa_for_given_date(
            _jd_noon(when), _jd_birth(birth), _place(birth), dhasa_level_index=2)
    if not rows:
        raise ValueError("yogini dasha unavailable")
    lords = [K.PLANET_NAMES[p] for row in rows for p in row[0]]
    score, ev = _yogini_score(facts, domain, lords)
    return {"score": score, "evidence": ev, "lords": lords}


def _sudarshana_at(facts, birth: BirthInput, domain: str, when: date,
                   calibrated: bool) -> dict:
    """Leaf triple (lagna-frame, moon-frame, sun-frame signs) at `when`.

    The activated house number is identical in the three frames (the roll
    advances them together); what differs is the actual sign activated in
    each frame, so each frame is judged by that sign's occupants and lord.
    """
    with _frame(birth):
        rows = sudharsana_chakra.get_running_dhasa_for_given_date(
            _jd_noon(when), _jd_birth(birth), _place(birth), dhasa_level_index=2)
    if not rows:
        raise ValueError("sudarshana chakra unavailable")
    leaf = rows[-1][0][-1]
    refs = [facts["lagna"]["sign"], facts["planets"]["Moon"]["sign"],
            facts["planets"]["Sun"]["sign"]]
    frame_names = ["lagna", "moon", "sun"]
    frames = frame_names if calibrated else frame_names[1:]
    frame_ids = range(3) if calibrated else (1, 2)

    activated_house = (leaf[1] - refs[1]) % 12 + 1
    spec_houses = set(K.DOMAINS[domain]["houses"])
    score, ev = 0, []
    if activated_house in spec_houses:
        score += 2
        ev.append(f"Sudarshana activates house {activated_house} — relevant to {domain}")
    elif activated_house in _DUSTHANA:
        score -= 2
        ev.append(f"Sudarshana activates dusthana house {activated_house}")
    for i in frame_ids:
        sign = leaf[i] % 12
        occupants = [p for p, rec in facts["planets"].items() if rec["sign"] == sign]
        ben = [p for p in occupants if
               {v: k for k, v in K.PLANET_NAMES.items()}[p] in K.NATURAL_BENEFICS]
        mal = [p for p in occupants if p not in ben]
        lord = K.PLANET_NAMES[K.SIGN_LORD[sign]]
        dign = facts["planets"].get(lord, {}).get("dignity", [])
        s = min(2, len(ben)) - min(2, len(mal))
        if "debilitated" in dign:
            s -= 1
        elif any(t in dign for t in ("exalted", "own sign", "moolatrikona")):
            s += 1
        score += s
        if s:
            ev.append(f"{frame_names[i].title()} frame activates {K.SIGN_NAMES[sign]} "
                      f"(lord {lord}; {'benefic' if s > 0 else 'malefic'} weight)")
    return {"score": score, "evidence": ev,
            "activated_house": activated_house, "frames": list(frames)}


def sudarshana_year_signs(birth: BirthInput, when: date) -> dict:
    """Year-level (Maha) Sudarshana Chakra signs running on `when`.

    Returns {"lagna": sign, "moon": sign, "sun": sign, "start": date, "end": date}: the sign
    progressed to in each of the three reference frames for the Sudarshana year containing
    `when` (PyJHora level 1 == one year per house). Convergence P3 asks, per reference, whether
    that sign is the event house counted from the reference. Raises ValueError if unavailable.
    """
    with _frame(birth):
        rows = sudharsana_chakra.get_running_dhasa_for_given_date(
            _jd_noon(when), _jd_birth(birth), _place(birth), dhasa_level_index=1)
    if not rows:
        raise ValueError("sudarshana chakra unavailable")
    triples, start, end = rows[-1]
    lagna_s, moon_s, sun_s = (int(x) % 12 for x in triples[-1])
    return {"lagna": lagna_s, "moon": moon_s, "sun": sun_s,
            "start": date(start[0], start[1], start[2]), "end": date(end[0], end[1], end[2])}


def confirmation(facts, birth: BirthInput, domain: str,
                 start: date, end: date, calibrated: bool) -> dict:
    """Yogini + Sudarshana agreement -> High conviction / Mixed indications /
    Hidden friction. Yogini needs no birth time; the Sudarshana lagna frame
    is only used on calibrated charts."""
    samples = [start, _mid(start, end), end]
    yog = {"score": 0, "evidence": [], "lords": []}
    sud = {"score": 0, "evidence": []}
    yog_err = sud_err = None
    try:
        for t in samples:
            r = _yogini_at(facts, birth, domain, t)
            yog["score"] += r["score"]
            yog["evidence"] += r["evidence"]
            yog["lords"] += r["lords"]
    except Exception as e:
        yog_err = str(e)
        yog = None
    try:
        for t in samples:
            r = _sudarshana_at(facts, birth, domain, t, calibrated)
            sud["score"] += r["score"]
            sud["evidence"] += r["evidence"]
            sud.setdefault("frames", r["frames"])
    except Exception as e:
        sud_err = str(e)
        sud = None

    def _verdict(layer):
        if layer is None:
            return "unavailable"
        if layer["score"] >= 3:
            return "support"
        if layer["score"] <= -2:
            return "conflict"
        return "neutral"

    yv, sv = _verdict(yog), _verdict(sud)
    votes = [v for v in (yv, sv) if v != "unavailable"]
    if not votes:
        label = "Unavailable"
    elif yv == sv == "support":
        label = "Both confirmation methods support"
    elif "conflict" in votes and "support" not in votes:
        label = "Hidden friction"
    elif "support" in votes:
        label = "Mostly aligned"
    else:
        label = "Mixed indications"
    return {"label": label,
            "yogini": {"verdict": yv, **({"error": yog_err} if yog_err else {}),
                       **(yog or {})},
            "sudarshana": {"verdict": sv,
                           **({"error": sud_err} if sud_err else {}),
                           **(sud or {})}}


# ------------------------------------------------------------------ timing

def _week_scores(facts, birth: BirthInput, domain_signs: set,
                 start: date, end: date, calibrated: bool) -> list[dict]:
    """Weekly sample of slow-kakshya + fast-trigger scores over the window."""
    prastara = _prastara(facts, birth)
    if prastara is None:
        raise ValueError("contributor-level Ashtakavarga unavailable")
    place = _place(birth)
    pid_of = {v: k for k, v in K.PLANET_NAMES.items()}
    weeks = []
    t = start
    while t <= end:
        pos = engine.transit_positions((t.year, t.month, t.day), place, birth.settings)
        score, reasons = 0, []
        for name in _SLOW:
            rec = pos.get(name)
            if not rec or rec["sign"] not in domain_signs:
                continue
            k = kakshya_of(rec["degree"])
            lord_id = KAKSHYA_LORDS[k]
            charged = lord_id != 7 and _kakshya_charged(
                prastara, pid_of[name], rec["sign"], rec["degree"])
            # the Lagna kakshya needs the lagna contributor — calibrated only
            if lord_id == 7:
                charged = calibrated and _kakshya_charged(
                    prastara, pid_of[name], rec["sign"], rec["degree"])
            sav, bav = facts.get("sarvastakavarga"), facts.get("binnashtakavarga")
            if charged and sav and bav and sav[rec["sign"]] >= 28 and bav[pid_of[name]][rec["sign"]] >= 5:
                score += 2
                reasons.append(f"{name} in bindu-charged kakshya of "
                               f"{kakshya_lord(k)} in {K.SIGN_NAMES[rec['sign']]}")
        for name in _FAST:
            rec = pos.get(name)
            if rec and rec["sign"] in domain_signs:
                score += 1
                reasons.append(f"{name} transiting {K.SIGN_NAMES[rec['sign']]} "
                               f"— fast trigger")
        weeks.append({"date": t, "score": score, "reasons": reasons})
        t += timedelta(days=_TIMING_STEP_DAYS)
    return weeks


def _adverse_tara_days(facts, birth: BirthInput, start: date, end: date) -> dict:
    """Daily adverse-Tara count inside a candidate window."""
    janma = facts["planets"]["Moon"]["nakshatra"]["index"]
    place = _place(birth)
    bad, seen = 0, {}
    t = start
    while t <= end:
        pos = engine.transit_positions((t.year, t.month, t.day), place, birth.settings)
        moon = pos.get("Moon")
        if moon:
            ti, tn = tara_of(nak_index(_abs_long(moon)), janma)
            if ti in ADVERSE_TARAS:
                bad += 1
                seen[tn] = seen.get(tn, 0) + 1
        t += timedelta(days=1)
    return {"adverse_days": bad, "by_tara": seen}


def _cluster_weeks(weeks: list[dict], threshold: int) -> list[dict]:
    """Merge consecutive qualifying weeks into spans (allowing small gaps)."""
    clusters, cur = [], None
    for w in weeks:
        if w["score"] >= threshold:
            if cur is None or (w["date"] - cur["end"]).days > _MERGE_GAP_DAYS:
                cur = {"start": w["date"], "end": w["date"],
                       "peak": w["score"], "peak_date": w["date"],
                       "reasons": list(w["reasons"])}
                clusters.append(cur)
            else:
                cur["end"] = w["date"]
                if w["score"] > cur["peak"]:
                    cur["peak"], cur["peak_date"] = w["score"], w["date"]
                cur["reasons"] += w["reasons"]
    return clusters


def _trim(cluster: dict, max_days: int) -> dict:
    """Bound a cluster to max_days centred on its peak week."""
    if (cluster["end"] - cluster["start"]).days <= max_days:
        return cluster
    half = timedelta(days=max_days // 2)
    s, e = cluster["peak_date"] - half, cluster["peak_date"] + half
    if s < cluster["start"]:
        e += cluster["start"] - s
        s = cluster["start"]
    if e > cluster["end"]:
        s -= e - cluster["end"]
        e = cluster["end"]
    return {**cluster, "start": s, "end": e}


def timing_windows(facts, birth: BirthInput, domain: str,
                   start: date, end: date, calibrated: bool,
                   max_windows: int = 3) -> dict:
    """Top week-windows where traditional indicators concentrate.

    Step 1: Jupiter/Saturn in a domain-relevant sign while passing a kakshya
    its lord backed with a bindu (narrows the period to months).
    Step 2: Sun or Mars in the same signs (narrows to weeks).
    Weeks where adverse Tara days (Vipat/Pratyari/Naidhana) dominate are
    excluded, not hidden: they are reported under excluded.
    """
    domain_signs, ref = _domain_signs(facts, domain, calibrated)
    weeks = _week_scores(facts, birth, domain_signs, start, end, calibrated)
    clusters = _cluster_weeks(weeks, _TIMING_MIN_SCORE)
    fallback = False
    if not clusters:
        clusters = _cluster_weeks(weeks, _TIMING_FALLBACK_SCORE)
        fallback = bool(clusters)

    windows, excluded = [], []
    for c in sorted(clusters, key=lambda c: (-c["peak"], c["start"])):
        if len(windows) >= max_windows:
            break
        c = _trim(c, _WINDOW_MAX_DAYS)
        c["start"] = max(start, c["start"])
        c["end"] = min(end, c["end"])
        tara = _adverse_tara_days(facts, birth, c["start"], c["end"])
        span_days = max(1, (c["end"] - c["start"]).days + 1)
        if tara["adverse_days"] * 2 > span_days:
            excluded.append({"start": c["start"].isoformat(),
                             "end": c["end"].isoformat(),
                             "reason": f"adverse Tara ({', '.join(tara['by_tara'])}) "
                                       f"on {tara['adverse_days']} of {span_days} days"})
            continue
        reasons = list(dict.fromkeys(c["reasons"]))
        if tara["adverse_days"]:
            reasons.append(f"{tara['adverse_days']} adverse-Tara day(s) inside — "
                           "the clearer days carry the indication")
        windows.append({"start": c["start"].isoformat(), "end": c["end"].isoformat(),
                        "why": reasons,
                        "peak_date": c["peak_date"].isoformat(), "fast_trigger": not fallback})
    return {"status": "applied", "reference": ref, "windows": windows, "excluded": excluded,
            "note": ("top weeks where traditional indicators concentrate — "
                     "not a claim the event must occur then")}


# ------------------------------------------------------------------ magnitude

def magnitude(facts, birth: BirthInput, mid: date, calibrated: bool) -> dict:
    """modest / notable / major from the leading Vimshottari lord's
    Shadbala and Ishta/Kashta Phala. Calibrated charts only — both inputs
    shift with birth time."""
    if not calibrated:
        return {"label": None, "applied": False,
                "reason": "needs a calibrated birth time"}
    run = engine.running_vimshottari(birth, (mid.year, mid.month, mid.day))
    if not run:
        return {"label": None, "applied": False, "reason": "no running dasha"}
    lord = run[0]["lords"][0]
    pid = {v: k for k, v in K.PLANET_NAMES.items()}.get(lord)
    shad = facts.get("shadbala")
    if pid is None or not shad or len(shad) <= 7 or pid >= len(shad[7]):
        return {"label": None, "applied": False,
                "reason": "shadbala unavailable for this dasha lord"}
    rupas = shad[7][pid]
    req = pillars._SHADBALA_MIN.get(lord, 6.0)
    ratio = rupas / req if req else 0.0
    try:
        with _frame(birth):
            ishta = strength._ishta_phala(_jd_birth(birth), _place(birth))[pid]
    except Exception:
        ishta = None
    basis = [f"{lord} shadbala {rupas:.2f} rupas vs required {req}"]
    if ishta is not None:
        basis.append(f"{lord} ishta phala {ishta}/60, kashta {60 - ishta}/60")
    if ishta is None:
        label = "notable" if ratio >= 1.0 else "modest"
    elif ratio >= _MAG_MAJOR[0] and ishta >= _MAG_MAJOR[1]:
        label = "major"
    elif ratio >= _MAG_NOTABLE[0] and ishta >= _MAG_NOTABLE[1]:
        label = "notable"
    else:
        label = "modest"
    return {"label": label, "applied": True, "dasha_lord": lord, "basis": basis}


# ------------------------------------------------------------------ fast triggers

def _eclipse_hits(facts, birth: BirthInput, start: date, end: date,
                  calibrated: bool) -> list[dict]:
    """Eclipses in the window within 3 deg of a natal planet (or natal Lagna
    on calibrated charts)."""
    place = _place(birth)
    # swe.*_eclipse_when_loc expects UT JDs and returns UT JDs; _jd_noon is local-style
    tz_h = place.timezone
    jd0, jd1 = _jd_noon(start) - tz_h / 24.0, _jd_noon(end) - tz_h / 24.0
    natal = {p: rec["abs_longitude"] for p, rec in facts["planets"].items()}
    if calibrated:
        natal["Lagna"] = facts["lagna"]["sign"] * 30 + facts["lagna"]["degree"]
    hits = []
    for kind, fn, body in (("solar", drik.next_solar_eclipse, const._SUN),
                           ("lunar", drik.next_lunar_eclipse, const._MOON)):
        jd, found = jd0, 0
        while found < _MAX_ECLIPSES_PER_WINDOW:
            try:
                with _frame(birth):
                    ret = fn(jd, place)
            except Exception as exc:
                raise ValueError(f"{kind} eclipse calculation unavailable") from exc
            if not ret or ret[0] == -1:
                raise ValueError(f"{kind} eclipse search failed")
            ecl_jd = ret[1][0]
            if ecl_jd > jd1:
                break
            jd = ecl_jd + 1
            found += 1
            try:
                with _frame(birth):
                    # sidereal_longitude takes a UTC JD — ecl_jd already is one
                    ecl_long = drik.sidereal_longitude(ecl_jd, body)
            except Exception as exc:
                raise ValueError("eclipse longitude unavailable") from exc
            touches = []
            for name, along in natal.items():
                if _sep(ecl_long, along) <= ECLIPSE_HIT_ORB:
                    touches.append(name)
            hits.append({"date": _ymd(ecl_jd + tz_h / 24.0), "kind": kind,
                         "touches": touches})
    return hits


_return_cache: dict = {}


def solar_return_date(birth: BirthInput, k: int) -> date:
    """Local date of the k-th solar return (k=0 is the birth date itself).

    The instant is the Sun returning to its natal sidereal longitude, not the
    calendar birthday, so it can fall a day either side of it.
    """
    if k <= 0:
        return date(birth.year, birth.month, birth.day)
    key = (birth_fingerprint(birth), k)
    if key not in _return_cache:
        with _frame(birth):
            jd = drik.next_solar_date(_jd_birth(birth), _place(birth), years=k + 1)
        if len(_return_cache) > 2048:
            _return_cache.clear()
        _return_cache[key] = _to_date(_ymd(jd))
    return _return_cache[key]


def completed_solar_years(birth: BirthInput, when: date) -> int:
    """Completed years counted by solar returns: the k with return(k) <= when < return(k+1).

    Negative (-1) before birth. Muntha and annual progressions advance on this count.
    """
    if when < date(birth.year, birth.month, birth.day):
        return -1
    k = max(0, when.year - birth.year - 1)
    while solar_return_date(birth, k + 1) <= when:
        k += 1
    while k > 0 and solar_return_date(birth, k) > when:
        k -= 1
    return k


def _annual_lord(annual, return_jd, birth, completed_years, natal_lagna):
    """Traditional seven-planet candidates, evaluated at the actual solar return.

    Implementation lives in `varsha.varsheshwara` (five office-bearers +
    Pancha-vargiya bala) so the pillar and the ithasala watch share one rule
    set. PyJHora 5's public helper uses a mean-year instant, can nominate
    nodes, and can return a list index instead of the candidate planet.
    """
    with _frame(birth):
        return varsha.varsheshwara(annual, return_jd, _place(birth),
                                   completed_years, natal_lagna)["id"]


def _ithasala_triggers(facts, birth: BirthInput, start: date, end: date) -> dict:
    jd_birth, place = _jd_birth(birth), _place(birth)
    out, errors = [], []
    # Include the annual chart beginning before the requested window.
    for age in range(max(0, start.year - birth.year - 1), end.year - birth.year + 1):
        try:
            # PyJHora's years=1 is the natal year, not the first birthday.
            with _frame(birth):
                ret = drik.next_solar_date(jd_birth, place, years=age + 1)
                nxt = drik.next_solar_date(jd_birth, place, years=age + 2)
            vd, until = _to_date(_ymd(ret)), _to_date(_ymd(nxt))
            if vd > end or until <= start:
                continue
            with _frame(birth):
                annual, _ = tajaka.annual_chart(jd_birth, place, years=age + 1)
            lord = _annual_lord(annual, ret, birth, age, facts["lagna"]["sign"])
            asc_lord = K.SIGN_LORD[annual[0][1][0]]
            pairs = []
            if asc_lord != lord:
                with _frame(birth):
                    ok, kind = tajaka_yoga.ithasala_yoga(annual, lord, asc_lord)
                if ok:
                    pairs.append({"between": K.PLANET_NAMES[lord], "and": K.PLANET_NAMES[asc_lord],
                                  "role": "varsha lagna lord", "type": int(kind)})
            out.append({"varsha_year": age, "completed_years": age, "label": pillars.varsha_label(age),
                        "varsha_start": vd.isoformat(),
                        "varsha_end_exclusive": until.isoformat(),
                        "year_lord": K.PLANET_NAMES[lord], "ithasala": pairs})
        except Exception as exc:
            errors.append({"varsha_year": age, "reason": f"{type(exc).__name__}: {exc}"})
    status = "unavailable" if not out else ("partial" if errors else "applied")
    return {"applied": status == "applied", "status": status, "year_lords": out,
            "errors": errors, **({"reason": "annual calculations incomplete"} if status != "applied" else {})}


def fast_triggers(facts, birth: BirthInput, start: date, end: date,
                  calibrated: bool) -> dict:
    try:
        eclipses = _eclipse_hits(facts, birth, start, end, calibrated)
        eclipse_status, eclipse_error = "applied", None
    except Exception as exc:
        eclipses, eclipse_status, eclipse_error = [], "unavailable", str(exc)
    ith = {"applied": False, "status": "skipped", "reason": "needs a calibrated birth time", "year_lords": []}
    if calibrated:
        ith = _ithasala_triggers(facts, birth, start, end)
    watch = sorted({h["date"][:7] for h in eclipses if h["touches"]})
    return {"ithasala": ith, "eclipses": eclipses, "eclipse_status": eclipse_status,
            "eclipse_error": eclipse_error, "watch_months": watch}


def gochara_now(facts, birth: BirthInput, today: date) -> dict:
    """Slow-planet transit snapshot for `today` against the Lagna and the natal Moon.

    Positions are the sidereal signs at local noon (engine.transit_positions, birth
    calc settings applied under the calculation lock). Returns, per Saturn / Jupiter /
    Rahu / Ketu: sign, house from Lagna and house from Moon, plus Saturn flags
    sade_sati (12th/1st/2nd from Moon), kantaka (4th) and ashtama (8th).
    """
    pos = engine.transit_positions((today.year, today.month, today.day), _place(birth), birth.settings)
    lagna, moon = facts["lagna"]["sign"], facts["planets"]["Moon"]["sign"]
    out = {"date": today.isoformat(), "planets": {}}
    for name in ("Saturn", "Jupiter", "Rahu", "Ketu"):
        if name not in pos:
            continue
        sign = pos[name]["sign"]
        out["planets"][name] = {"sign": sign, "sign_name": K.SIGN_NAMES[sign],
                                "degree": pos[name]["degree"],
                                "house_from_lagna": (sign - lagna) % 12 + 1,
                                "house_from_moon": (sign - moon) % 12 + 1}
    sat = out["planets"].get("Saturn")
    flags = pillars.saturn_moon_states(moon, sat["sign"]) if sat else []
    out["sade_sati"] = "sade_sati" in flags
    out["kantaka"] = "kantaka" in flags
    out["ashtama"] = "ashtama" in flags
    return out


# ------------------------------------------------------------------ entry point

def evaluate(facts, birth: BirthInput, domain: str,
             start: date, end: date, calibrated: bool | None = None) -> dict:
    """Verdict + precision filters for one (domain, window) prediction.

    `calibrated` defaults to the stated birth-time precision; callers that
    know the app's calibration outcome may pass it explicitly.
    """
    if calibrated is None:
        calibrated = birth.birth_time_precision == "exact"
    core = pillars.evaluate(facts, birth, domain, start, end)
    conf = confirmation(facts, birth, domain, start, end, calibrated)
    try:
        tim = timing_windows(facts, birth, domain, start, end, calibrated)
    except Exception as exc:
        tim = {"status": "unavailable", "reference": "lagna" if calibrated else "moon",
               "windows": [], "excluded": [], "reason": str(exc)}
    mag = magnitude(facts, birth, _mid(start, end), calibrated)
    trig = fast_triggers(facts, birth, start, end, calibrated)
    return {
        "domain": domain,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "calibrated": calibrated,
        "verdict": core,
        "confirmation": conf,
        "timing": tim,
        "magnitude": mag,
        "fast_triggers": trig,
        "layer_verdicts": {
            "core_pillars": core["convergence"],
            "yogini": conf["yogini"]["verdict"],
            "sudarshana": conf["sudarshana"]["verdict"],
            "confirmation": conf["label"],
            "kakshya_timing": tim["status"],
            "magnitude": mag["label"] if mag["applied"] else "skipped",
            "ithasala": trig["ithasala"]["status"],
            "eclipse": trig["eclipse_status"],
        },
    }
