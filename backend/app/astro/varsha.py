"""Varshaphala: the Tajika annual chart at the exact sidereal solar return.

Replaces the "Muntha-only" simplification with the full Neelakanthi-style
annual chart:

- the exact solar-return instant (sidereal Sun longitude == natal, found by
  PyJHora's root-finder; the chart is cast at the birthplace as per the
  classical convention);
- Varsha Lagna, Muntha (completed years counted by solar returns, not the
  calendar birthday);
- the five office-bearers and the Varsheshwara (year lord) chosen by
  Tajika-aspect shortlist then Pancha-vargiya bala — the corrected rule set
  that previously lived in `precision._annual_lord`;
- Pancha-vargiya bala per planet at the return instant;
- Mudda dasha (Vimshottari proportions compressed into one year) via
  PyJHora's `mudda` module, labelled as its scheme;
- Tajika yogas over the annual chart with Tajika aspects and deeptamsa orbs.

Every section reports its own status; a failure degrades to `unavailable`
for that section, never a guess.
"""
import logging

from jhora import const, utils
from jhora.panchanga import drik
from jhora.horoscope.chart import charts, strength
from jhora.horoscope.dhasa.annual import mudda
from jhora.horoscope.transit import tajaka

from . import constants as K
from .engine import BirthInput, apply, birth_fingerprint, calc_lock

log = logging.getLogger(__name__)

# Muntha judged from the Varsha Lagna (Tajika reading): these houses are
# read as supportive for the year's promise.
MUNTHA_GOOD_HOUSES = {1, 2, 3, 5, 9, 10, 11}
MUNTHA_BAD_HOUSES = {6, 8, 12}

# Tajika aspect: a sign is aspected from every other sign distance except the
# 6th and 8th (0-based offsets 5 and 7); conjunction included.
def _aspects(a_sign: int, b_sign: int) -> bool:
    return (b_sign - a_sign) % 12 not in (5, 7)


_SPEED_ORDER = list(const.order_of_planets_by_speed)          # slowest -> fastest
_DEEPTAMSA = list(const.deeptaamsa_of_planets)                # degrees, by planet id
_PVB_THRESHOLD = const.pancha_vargeeya_bala_strength_threshold
_ORB_NEAR = 1.0    # "poorna" / approaching-edge allowance used by PyJHora too


def _place(birth: BirthInput):
    return drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)


def _jd_birth(birth: BirthInput) -> float:
    return utils.julian_day_number((birth.year, birth.month, birth.day),
                                   (birth.hour, birth.minute, birth.second))


def _ymd(jd_val) -> str:
    y, m, d, _ = utils.jd_to_gregorian(jd_val)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _local_stamp(jd_val) -> str:
    y, m, d, fh = utils.jd_to_gregorian(jd_val)
    total = round(fh * 3600)
    h, rem = divmod(total, 3600)
    return f"{y:04d}-{m:02d}-{d:02d} {int(h):02d}:{int(rem)//60:02d}:{int(rem)%60:02d}"


def _lagna_of(positions) -> int:
    return next(int(s) for p, (s, d) in positions if p == "L")


def return_jd(birth: BirthInput, completed_years: int) -> float:
    """Julian day of the k-th sidereal solar return (k=0 is birth itself)."""
    if completed_years < 0:
        raise ValueError("completed_years must be >= 0")
    with calc_lock:
        apply(birth.settings)
        jd0 = _jd_birth(birth)
        if completed_years == 0:
            return jd0
        return drik.next_solar_date(jd0, _place(birth), years=completed_years + 1)


def varsheshwara(annual_positions, return_jd_val, place, completed_years,
                 natal_lagna_sign: int) -> dict:
    """Year lord from the five office-bearers, per the corrected rule set.

    Candidates: lord of the Sun's sign (day return) or Moon's sign (night),
    natal lagna lord, Muntha sign lord, Varsha lagna lord, and the
    day/night Tri-rashi lord. Candidates with a benefic Tajika aspect on the
    Varsha lagna are shortlisted; if the shortlist is empty the malefic
    aspect list is used; the strongest by Pancha-vargiya bala wins (above
    the strength threshold, else the first candidate).

    This is the same selection previously inline in precision._annual_lord:
    it evaluates candidates at the actual return instant and avoids the
    node/index defects in PyJHora 5's public helper.

    Callers must hold `calc_lock` with the settings applied (all drik calls
    touch global ephemeris state).
    """
    pos = dict(annual_positions)
    asc = pos["L"][0]
    hour = utils.jd_to_gregorian(return_jd_val)[3]
    night = hour < drik.sunrise(return_jd_val, place)[0] or hour >= drik.sunset(return_jd_val, place)[0]
    muntha_sign = (natal_lagna_sign + completed_years) % 12
    roles = {
        "luminary_sign_lord": {"which": "moon" if night else "sun",
                               "planet": K.PLANET_NAMES[K.SIGN_LORD[pos[1 if night else 0][0]]]},
        "natal_lagna_lord": K.PLANET_NAMES[K.SIGN_LORD[natal_lagna_sign]],
        "muntha_lord": K.PLANET_NAMES[K.SIGN_LORD[muntha_sign]],
        "varsha_lagna_lord": K.PLANET_NAMES[K.SIGN_LORD[asc]],
        "trirasi_lord": K.PLANET_NAMES[
            (const.tri_rasi_nighttime_lords if night else const.tri_rasi_daytime_lords)[asc]],
    }
    candidates = list(dict.fromkeys([
        K.SIGN_LORD[pos[1 if night else 0][0]], K.SIGN_LORD[natal_lagna_sign],
        K.SIGN_LORD[muntha_sign], K.SIGN_LORD[asc],
        (const.tri_rasi_nighttime_lords if night else const.tri_rasi_daytime_lords)[asc],
    ]))
    candidates = [p for p in candidates if p in range(7)]
    h2p = utils.get_house_planet_list_from_planet_positions(annual_positions)
    eligible = [p for p in candidates if tajaka.planet_has_benefic_aspect_on_house(h2p, p, asc)]
    rule = "benefic_aspects"
    if not eligible:
        eligible = [p for p in candidates if tajaka.planet_has_malefic_aspect_on_house(h2p, p, asc)]
        rule = "malefic_aspects"
    if len(eligible) == 1:
        chosen, via = eligible[0], "single_" + rule
    else:
        pool = eligible or candidates
        if not pool:
            raise ValueError("no eligible annual lord")
        bala = strength.pancha_vargeeya_bala(return_jd_val, place)
        strongest = max(pool, key=lambda p: bala[p])
        chosen = strongest if bala[strongest] > _PVB_THRESHOLD else pool[0]
        via = "pancha_vargeeya_bala" if bala[strongest] > _PVB_THRESHOLD else "first_candidate"
    return {"planet": K.PLANET_NAMES[chosen], "id": chosen, "night": night,
            "office_bearers": roles, "muntha_sign": muntha_sign,
            "candidates": [K.PLANET_NAMES[p] for p in candidates],
            "shortlist": [K.PLANET_NAMES[p] for p in eligible], "rule": via}


# ------------------------------------------------------------------ Tajika yogas

def _deg(pos, p):
    return pos[p][1]


def _abs_long(pos, p):
    return pos[p][0] * 30.0 + pos[p][1]


def _speed_rank(p):
    return _SPEED_ORDER.index(p)


def _in_deeptamsa(pos, p1, p2):
    """(within, kind): kind 'poorna' | 'vartamana' | 'bhavishya' | None.

    Orb is measured on each planet's degree-within-sign, following PyJHora's
    deeptamsa convention (orb applies to the aspect distance)."""
    if p1 > 6 or p2 > 6:
        return False, None
    d1, d2 = _deg(pos, p1), _deg(pos, p2)
    if abs(d1 - d2) <= _ORB_NEAR:
        return True, "poorna"
    lo1, hi1 = d1 - _DEEPTAMSA[p1], d1 + _DEEPTAMSA[p1]
    lo2, hi2 = d2 - _DEEPTAMSA[p2], d2 + _DEEPTAMSA[p2]
    within = (lo1 <= d2 <= hi1) and (lo2 <= d1 <= hi2)
    if within:
        return True, "vartamana"
    near = (lo1 - _ORB_NEAR <= d2 <= hi1 + _ORB_NEAR) or (lo2 - _ORB_NEAR <= d1 <= hi2 + _ORB_NEAR)
    return (True, "bhavishya") if near else (False, None)


def _faster_pair(pos, speeds, p1, p2):
    """(faster, slower) using instantaneous speeds then the static speed order."""
    s1, s2 = abs(speeds.get(p1, 0.0)), abs(speeds.get(p2, 0.0))
    if s1 != s2:
        return (p1, p2) if s1 > s2 else (p2, p1)
    return (p1, p2) if _speed_rank(p1) > _speed_rank(p2) else (p2, p1)


def _applying(pos, speeds, faster, slower):
    """True when the faster planet moves toward the slower one's degree."""
    df, ds = _deg(pos, faster), _deg(pos, slower)
    vf = speeds.get(faster, 1.0)
    return (vf >= 0 and df < ds) or (vf < 0 and df > ds)


def _combust_in_chart(pos, p, retro, table="surya_siddhanta"):
    if p == 0 or p > 6:
        return False
    sep = abs(_abs_long(pos, p) - _abs_long(pos, 0))
    sep = min(sep, 360 - sep)
    orb = K.combust_orb(p, p in retro, table)
    return bool(orb and sep < orb)


def _dignity_level(p, sign):
    return const.house_strengths_of_planets[p][sign]


def tajika_yogas(positions, *, speeds=None, retro=None, pvb=None,
                 combust_table="surya_siddhanta") -> dict:
    """Tajika yogas over the annual chart (PyJHora-format positions).

    Evaluated: Ishkavala, Induvara, Ithasala (poorna/vartamana/bhavishya),
    Ishrafa, Nakta, Yamaya, Manau, Kamboola (+Gairi when the Moon is
    dignified), Radda, Duhphali-kutta, Tambira, Kuththa.
    Not evaluated (rule definitions left to a named source): Khallasar,
    Dutthottha-davira, Durapha.
    """
    speeds = speeds or {}
    retro = retro or set()
    pvb = pvb or {}
    pos = {p: (int(s), float(d)) for p, (s, d) in positions}
    lagna = pos["L"][0]
    planets = [p for p in range(7) if p in pos]
    out, not_eval = [], ["Khallasaar", "Dutthottha-Davira", "Durapha"]

    def entry(yid, planets_, detail, **extra):
        out.append({"yoga": yid, "planets": [K.PLANET_NAMES[q] for q in planets_],
                    "detail": detail, **extra})

    # --- whole-chart yogas ---
    houses_of = {p: (pos[p][0] - lagna) % 12 + 1 for p in planets}
    if planets and all(houses_of[p] in (1, 2, 4, 5, 7, 8, 10, 11) for p in planets):
        entry("Ishkavala", planets, "all planets in kendras and panapharas")
    if planets and all(houses_of[p] in (3, 6, 9, 12) for p in planets):
        entry("Induvara", planets, "all planets in apoklimas")

    ithasala_pairs, ishrafa_pairs = [], []
    for i, p1 in enumerate(planets):
        for p2 in planets[i + 1:]:
            if not _aspects(pos[p1][0], pos[p2][0]):
                continue
            within, kind = _in_deeptamsa(pos, p1, p2)
            if not within:
                continue
            faster, slower = _faster_pair(pos, speeds, p1, p2)
            if _applying(pos, speeds, faster, slower):
                ithasala_pairs.append((faster, slower, kind))
                entry("Ithasala", (faster, slower),
                      f"{kind} ithasala — faster {K.PLANET_NAMES[faster]} applying "
                      f"to {K.PLANET_NAMES[slower]}", type=kind)
            else:
                ishrafa_pairs.append((faster, slower))
                entry("Ishrafa", (faster, slower),
                      f"{K.PLANET_NAMES[faster]} separating from {K.PLANET_NAMES[slower]}")

    # --- light-carrying yogas ---
    aspect_pairs = {(a, b) for a in planets for b in planets
                    if a != b and _aspects(pos[a][0], pos[b][0])}
    for p1 in planets:
        for p2 in planets:
            if p1 >= p2 or (p1, p2) in aspect_pairs:
                continue
            for c in planets:
                if c in (p1, p2):
                    continue
                if not (_aspects(pos[c][0], pos[p1][0]) and _aspects(pos[c][0], pos[p2][0])):
                    continue
                dc, d1, d2 = _deg(pos, c), _deg(pos, p1), _deg(pos, p2)
                if _speed_rank(c) > max(_speed_rank(p1), _speed_rank(p2)) and dc < min(d1, d2):
                    entry("Nakta", (c, p1, p2),
                          f"{K.PLANET_NAMES[c]} carries light between "
                          f"{K.PLANET_NAMES[p1]} and {K.PLANET_NAMES[p2]}")
                elif _speed_rank(c) < min(_speed_rank(p1), _speed_rank(p2)) and dc > max(d1, d2):
                    entry("Yamaya", (c, p1, p2),
                          f"{K.PLANET_NAMES[c]} receives light of {K.PLANET_NAMES[p1]} "
                          f"and {K.PLANET_NAMES[p2]}")

    # --- modifiers on ithasala ---
    moon_deg = _deg(pos, 1) if 1 in pos else None
    moon_strong = bool(pos.get(1)) and _dignity_level(1, pos[1][0]) >= const._FRIEND
    for faster, slower, kind in ithasala_pairs:
        for m in (2, 6):  # Mars, Saturn
            if m in pos and pos[m][0] == pos[faster][0] \
                    and abs(_deg(pos, m) - _deg(pos, faster)) <= _DEEPTAMSA[faster]:
                entry("Manau", (faster, m, slower),
                      f"{K.PLANET_NAMES[m]} within deeptamsa of {K.PLANET_NAMES[faster]} "
                      "— ithasala vitiated")
        if moon_deg is not None and any(_aspects(pos[1][0], pos[q][0]) for q in (faster, slower)):
            entry("Gairi-Kamboola" if moon_strong else "Kamboola", (1, faster, slower),
                  "Moon aspects the ithasala pair", moon_dignified=moon_strong)
        spoiled = []
        if faster in retro:
            spoiled.append("retrograde")
        if _combust_in_chart(pos, faster, retro, combust_table):
            spoiled.append("combust")
        if _dignity_level(faster, pos[faster][0]) < const._NEUTRAL_SAMAM:
            spoiled.append("debilitated/enemy sign")
        if spoiled:
            entry("Radda", (faster, slower),
                  f"{K.PLANET_NAMES[faster]} is {', '.join(spoiled)} — ithasala frustrated")
        f_strong = _dignity_level(faster, pos[faster][0]) > const._FRIEND \
            and pvb.get(faster, 0) > _PVB_THRESHOLD
        s_weak = _dignity_level(slower, pos[slower][0]) < const._EXALTED_UCCHAM \
            and pvb.get(slower, 99) < _PVB_THRESHOLD
        if f_strong and s_weak:
            entry("Duhphali-kutta", (faster, slower),
                  f"strong {K.PLANET_NAMES[faster]} perfects the weaker {K.PLANET_NAMES[slower]}")

    # --- single-planet condition yogas ---
    for p in planets:
        aspected = any(q != p and _aspects(pos[q][0], pos[p][0]) for q in planets)
        if houses_of[p] in (1, 4, 7, 10):
            if pos[p][0] in K.OWN_SIGNS.get(p, []) and not aspected:
                entry("Tambira", (p,), f"{K.PLANET_NAMES[p]} in own sign in kendra, unaspected")
            elif _dignity_level(p, pos[p][0]) < const._NEUTRAL_SAMAM:
                entry("Kuththa", (p,), f"{K.PLANET_NAMES[p]} in weak dignity in kendra")
    return {"yogas": out, "not_evaluated": not_eval,
            "ithasala_pair_count": len(ithasala_pairs), "ishrafa_pair_count": len(ishrafa_pairs)}


# ------------------------------------------------------------------ Mudda dasha

def mudda_periods(birth: BirthInput, year_of_life: int) -> list:
    """Mudda (Varsha-Vimshottari) periods for the given year of life (1-based).

    Uses PyJHora's scheme: seed lord = natal Moon nakshatra's Vimshottari
    lord advanced by completed years through the Mudda order, the balance
    carried from the natal nakshatra fraction, periods compressed from the
    120-year cycle into the dasha year. Documented, not a claim that this is
    the only published convention.
    """
    dob = (birth.year, birth.month, birth.day)
    tob = (birth.hour, birth.minute, birth.second)
    rows = mudda.get_dhasa_antardhasa(dob, tob, _place(birth), year_of_life,
                                      dhasa_level_index=2)
    out = []
    for i, (lords, start_tuple, dur) in enumerate(rows):
        y, m, d, fh = start_tuple
        start = f"{y:04d}-{m:02d}-{d:02d}"
        end = None
        if i + 1 < len(rows):
            ny, nm, nd, _ = rows[i + 1][1]
            end = f"{ny:04d}-{nm:02d}-{nd:02d}"
        out.append({"lords": [K.PLANET_NAMES[q] for q in lords],
                    "start": start, "end": end,
                    "duration_years": round(float(dur), 4)})
    return out


# ------------------------------------------------------------------ the annual chart

_varsha_cache: dict = {}
_VARSHA_CACHE_MAX = 128


def varsha(birth: BirthInput, completed_years: int,
           natal_lagna_sign: int | None = None) -> dict:
    """Full Varshaphala for the year after `completed_years` solar returns.

    `natal_lagna_sign` is the natal lagna sign index (0-based); when omitted
    it is recomputed from the birth data. Returns a dict; each section
    degrades independently ("errors" lists what failed). Raises only if the
    return instant or the annual chart itself is unavailable.
    """
    if completed_years < 0:
        raise ValueError("completed_years must be >= 0")
    key = (birth_fingerprint(birth), completed_years, natal_lagna_sign)
    if key in _varsha_cache:
        return _varsha_cache[key]

    place = _place(birth)
    jd0 = _jd_birth(birth)
    with calc_lock:
        apply(birth.settings)
        r_jd = jd0 if completed_years == 0 else drik.next_solar_date(
            jd0, place, years=completed_years + 1)
        annual, _ = tajaka.annual_chart(jd0, place, years=completed_years + 1)
        positions = [[p, (int(s), float(d))] for p, (s, d) in annual]
        if natal_lagna_sign is None:
            natal_lagna_sign = int(drik.ascendant(jd0, place)[0])
        try:
            retro = set(drik.planets_in_retrograde(r_jd, place))
        except Exception:
            retro = set()
        try:
            speeds = {p: float(v[3]) for p, v in
                      drik.planets_speed_info(r_jd, place).items()}
        except Exception:
            speeds = {}

    lagna = _lagna_of(positions)
    errors = []

    muntha_sign = (natal_lagna_sign + completed_years) % 12
    rec = {
        "completed_years": completed_years,
        "year_of_life": completed_years + 1,
        "return": {"jd": r_jd, "local": _local_stamp(r_jd),
                   "tz_offset_hours": birth.tz_offset},
        "varsha_lagna": {"sign": lagna, "sign_name": K.SIGN_NAMES[lagna]},
        "positions": positions,
        "muntha": {
            "sign": muntha_sign, "sign_name": K.SIGN_NAMES[muntha_sign],
            "house_from_varsha_lagna": (muntha_sign - lagna) % 12 + 1,
            "house_from_natal_lagna": (muntha_sign - natal_lagna_sign) % 12 + 1,
        },
        "errors": errors,
    }

    try:
        with calc_lock:
            apply(birth.settings)
            rec["pancha_vargeeya_bala"] = {
                K.PLANET_NAMES[p]: v for p, v in
                strength.pancha_vargeeya_bala(r_jd, place).items()}
            vl = varsheshwara(positions, r_jd, place, completed_years,
                              natal_lagna_sign)
            rec["night"] = vl.pop("night")
            rec["office_bearers"] = vl.pop("office_bearers")
            rec["year_lord"] = vl
    except Exception as exc:
        errors.append({"section": "year_lord", "reason": f"{type(exc).__name__}: {exc}"})
        rec["year_lord"] = None
        rec["office_bearers"] = None
        rec["pancha_vargeeya_bala"] = None

    try:
        with calc_lock:
            apply(birth.settings)
            name_to_id = {v: k for k, v in K.PLANET_NAMES.items()}
            rec["tajika"] = tajika_yogas(
                positions, speeds=speeds, retro=retro,
                pvb={name_to_id[n]: s for n, s in
                     (rec.get("pancha_vargeeya_bala") or {}).items()},
                combust_table=birth.settings.combust_table)
    except Exception as exc:
        errors.append({"section": "tajika_yogas", "reason": f"{type(exc).__name__}: {exc}"})
        rec["tajika"] = {"yogas": [], "not_evaluated": []}

    try:
        with calc_lock:
            apply(birth.settings)
            rec["mudda"] = {"scheme": "PyJHora Varsha-Vimshottari (seed lord from natal "
                                      "nakshatra lord + completed years; natal balance carried)",
                            "periods": mudda_periods(birth, completed_years + 1)}
    except Exception as exc:
        errors.append({"section": "mudda", "reason": f"{type(exc).__name__}: {exc}"})
        rec["mudda"] = None

    rec["status"] = "applied" if not errors else "partial"
    if len(_varsha_cache) > _VARSHA_CACHE_MAX:
        _varsha_cache.clear()
    _varsha_cache[key] = rec
    return rec
