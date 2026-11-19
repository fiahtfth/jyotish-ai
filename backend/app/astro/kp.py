"""Krishnamurti frame, kept separate from the four traditional pillars."""
from bisect import bisect_right
from datetime import date, timedelta
from functools import lru_cache
import logging

from jhora.panchanga import drik
import swisseph as swe

from .constants import NAK_LORD_SEQUENCE, NAKSHATRAS, PLANET_NAMES, SIGN_LORD, SIGN_NAMES
from .engine import _dms, _CLASSICAL_BODIES, BirthInput, apply, calc_lock
from .vargas import UNITS_PER_DEGREE
from .vimshottari import YEARS

log = logging.getLogger(__name__)
VERSION = "kp-placidus-v1"


@lru_cache(maxsize=1)
def _segments() -> tuple[tuple[int, int, int, int], ...]:
    data = []
    for star in range(27):
        cursor = star * 48000
        for index in range(9):
            lord = NAK_LORD_SEQUENCE[(star + index) % 9]
            end = cursor + 400 * YEARS[lord]
            boundary = (cursor // 108000 + 1) * 108000
            if cursor < boundary < end:
                data.append((cursor, boundary, star, lord))
                cursor = boundary
            data.append((cursor, end, star, lord))
            cursor = end
    return tuple(data)


def _point(longitude: float) -> dict[str, int | float | str]:
    arc = (round(longitude * UNITS_PER_DEGREE) % (360 * UNITS_PER_DEGREE)) / 1_000_000
    index = bisect_right(_segments(), arc, key=lambda row: row[0]) - 1
    _, _, star, sub = _segments()[index]
    sign = int(arc // 108000)
    return {"longitude": round(arc / 3600, 8), "sign": SIGN_NAMES[sign], "sign_index": sign,
            "degree": round((arc % 108000) / 3600, 8), "sign_lord": PLANET_NAMES[SIGN_LORD[sign]],
            "nakshatra": NAKSHATRAS[star], "star_lord": PLANET_NAMES[NAK_LORD_SEQUENCE[star % 9]],
            "sub_lord": PLANET_NAMES[sub], "segment": index + 1}


def _house(longitude, cusps):
    for i, cusp in enumerate(cusps):
        if (longitude - cusp) % 360 < (cusps[(i + 1) % 12] - cusp) % 360:
            return i + 1
    raise ValueError("The Placidus cusps do not form twelve usable houses.")


def calculate(birth: BirthInput) -> dict:
    jd_local = swe.julday(birth.year, birth.month, birth.day,
                         birth.hour + birth.minute / 60 + birth.second / 3600)
    offset = birth.tz_offset / 24
    jd_ut = jd_local - offset
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    flags_seen = {}
    with calc_lock:
        apply(birth.settings)
        try:
            swe.set_sid_mode(swe.SIDM_KRISHNAMURTI)
            cusps, _ = swe.houses_ex(jd_ut, birth.lat, birth.lon, b"P", swe.FLG_SIDEREAL)
            ayanamsa = swe.get_ayanamsa_ut(jd_ut)
            longitudes = {}
            for pid, body in enumerate((*_CLASSICAL_BODIES, swe.MEAN_NODE)):
                values, used = swe.calc_ut(jd_ut, body, flags)
                name = PLANET_NAMES[pid]
                longitudes[name] = values[0] % 360
                flags_seen[name] = used
                log.debug("KP body=%s jd_ut=%.8f Swiss flags=%s", name, jd_ut, used)
            longitudes["Ketu"] = (longitudes["Rahu"] + 180) % 360
            midnight = swe.julday(birth.year, birth.month, birth.day, 0) - offset
            rise_status, rise = swe.rise_trans(midnight, swe.SUN, swe.CALC_RISE | swe.BIT_HINDU_RISING,
                                               (birth.lon, birth.lat, 0), flags=swe.FLG_SWIEPH)
        except swe.Error as exc:
            raise ValueError("The requested location or time does not permit a KP Placidus chart.") from exc
        finally:
            drik.set_ayanamsa_mode(birth.settings.ayanamsa)
    planets = {name: {**_point(lon), "house": _house(lon, cusps)} for name, lon in longitudes.items()}
    houses = [{"house": i, **_point(lon)} for i, lon in enumerate(cusps, 1)]
    indicators = []
    for house in houses:
        occupants = [name for name, point in planets.items() if point["house"] == house["house"]]
        indicators.append({"house": house["house"], "stars_of_occupants": [name for name, point in planets.items()
                           if point["star_lord"] in occupants], "occupants": occupants,
                           "stars_of_owner": [name for name, point in planets.items() if point["star_lord"] == house["sign_lord"]],
                           "owner": house["sign_lord"]})
    day = date(birth.year, birth.month, birth.day)
    weekday_lord = None
    if rise_status == 0:
        if jd_ut < rise[0]:
            day -= timedelta(days=1)
        weekday_lord = ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"][day.weekday()]
    rulers = {"weekday_lord": weekday_lord, "lagna_sign_lord": houses[0]["sign_lord"],
              "lagna_star_lord": houses[0]["star_lord"], "moon_sign_lord": planets["Moon"]["sign_lord"],
              "moon_star_lord": planets["Moon"]["star_lord"]}
    return {"frame": {"ayanamsa": "Swiss Krishnamurti", "dms": _dms(ayanamsa), "houses": "Placidus",
                      "node": "mean", "positions": "apparent geocentric", "rule_version": VERSION,
                      "ephemeris_flags": flags_seen, "source": "K. S. Krishnamurti, KP Readers III and VI"},
            "cusps": houses, "planets": planets, "significators": indicators, "ruling_planets": rulers,
            "segments": [{"number": i, "start_arcsec": a, "end_arcsec": b, "nakshatra": NAKSHATRAS[s],
                          "sub_lord": PLANET_NAMES[lord]} for i, (a, b, s, lord) in enumerate(_segments(), 1)],
            "limitations": ["Ruling planets are shown for the chart instant using a sunrise-based weekday.",
                            "Node proxy significations and KP event timing are unavailable."]}
