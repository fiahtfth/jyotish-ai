"""Deterministic PyJHora adapter.

Every astrological "fact" the system uses is produced here, by code —
never by a language model. `compute_chart` returns the locked facts dict
that the orchestrator, the four-pillar engine and the verifier all read.
"""
import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace

from functools import partial

import swisseph as swe

from jhora import const, utils
from jhora.panchanga import drik
from jhora.horoscope.chart import charts, arudhas, ashtakavarga, strength
from jhora.horoscope.chart import house as house_mod
from jhora.horoscope.dhasa.graha import vimsottari
from jhora.horoscope.dhasa.raasi import chara as chara_dhasa
from jhora.horoscope import main as hmain

from . import constants as K
from . import jaimini as J
from .settings import CalcSettings, DASHA_YEAR_DAYS, DEFAULT as DEFAULT_SETTINGS, as_settings
from ..config import settings

log = logging.getLogger(__name__)

# PyJHora/Swiss Ephemeris keep calculation state in process globals (sidereal
# mode, node mode, flags, dasha year). Every public entry point that reads that
# state holds this re-entrant lock; settings are re-applied only on change.
_lock = threading.RLock()
calc_lock = _lock
_configured = False
_applied: CalcSettings | None = None
_custom_year_days: float | None = None
_orig_dhasa_year_duration = None
_orig_end_jd = None
_orig_start_jd = None

EPHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "ephe"))
PYJHORA_VERSION = "5.0.0"

def navamsa_chart(planet_positions_in_rasi, chart_method=None):
    """D9 with half-open parts [k*10/3, (k+1)*10/3) degrees.

    PyJHora floors `long // (30/9)`, and 30/9 is a hair above 10/3, so a point
    exactly on a part boundary (e.g. 10 deg) lands in the previous part. Such
    points are nudged by 1e-7 deg before the call; the reported degree is the
    exact boundary value (0.0), not the nudged one.
    """
    out = []
    for pid, (sign, deg) in planet_positions_in_rasi:
        x = float(deg) * 9 / 30
        n = round(x)
        on_boundary = abs(x - n) < 1e-9 and n < 9
        probe = [[pid, (sign, float(deg) + 1e-7 if on_boundary else deg)]]
        res = charts.navamsa_chart(probe, chart_method)[0]
        new_sign, new_deg = res[1]
        out.append([res[0], (new_sign, 0.0 if on_boundary else new_deg)])
    return out


VARGA_FUNCS = {
    "D1": charts.rasi_chart, "D2": partial(charts.hora_chart, chart_method=2), "D4": charts.chaturthamsa_chart,
    "D6": partial(charts.shashthamsa_chart, chart_method=1), "D7": charts.saptamsa_chart, "D9": navamsa_chart, "D10": charts.dasamsa_chart,
    "D12": charts.dwadasamsa_chart, "D16": charts.shodasamsa_chart,
    "D20": charts.vimsamsa_chart, "D24": partial(charts.chaturvimsamsa_chart, chart_method=1),
    "D30": charts.trimsamsa_chart, "D3": charts.drekkana_chart, "D45": charts.akshavedamsa_chart,
    "D40": charts.khavedamsa_chart, "D60": charts.shashtyamsa_chart,
}
TIME_SENSITIVE_VARGAS = {"D10", "D12", "D16", "D20", "D24", "D30", "D40", "D45", "D60"}


_EXTRA_AYANAMSAS = {"LAHIRI_1940": swe.SIDM_LAHIRI_1940, "LAHIRI_VP285": swe.SIDM_LAHIRI_VP285,
                    "LAHIRI_ICRC": swe.SIDM_LAHIRI_ICRC}
# PyJHora derives true_tropical / true_sidereal dasha dates from solar-arc
# searches (native). Constant-length modes are applied by wrapping its
# start/end-date helpers with plain arithmetic: days = years * constant.
_YEAR_TYPES = {"true_tropical": const.DHASA_YEAR_DURATION.TRUE_TROPICAL_YEAR,
               "true_sidereal": const.DHASA_YEAR_DURATION.TRUE_SIDEREAL_YEAR}
_CUSTOM_YEARS = {"julian": 365.25, "gregorian": const.average_gregorian_year,
                 "sidereal": const.sidereal_year, "savana_360": 360.0}
_true_node_ok: bool | None = None


def _dhasa_year_duration(dhasa_duration_type=None, *a, **kw):
    if _custom_year_days is not None and dhasa_duration_type is None:
        return _custom_year_days
    return _orig_dhasa_year_duration(dhasa_duration_type, *a, **kw)


def _dhasa_end_jd(start_jd, place, total_dasa_years):
    if _custom_year_days is not None:
        return start_jd + total_dasa_years * _custom_year_days
    return _orig_end_jd(start_jd, place, total_dasa_years)


def _dhasa_start_jd(jd_birth, place, fraction_elapsed, total_dasa_years, dasha_sesham_method=None):
    if _custom_year_days is None:
        return _orig_start_jd(jd_birth, place, fraction_elapsed, total_dasa_years, dasha_sesham_method)
    if dasha_sesham_method is None:
        dasha_sesham_method = const.default_dasha_sesham_method
    if dasha_sesham_method == const.DASHA_SESHAM_METHOD.REVERSE:
        fraction_elapsed = 1.0 - fraction_elapsed
    elif dasha_sesham_method == const.DASHA_SESHAM_METHOD.NONE:
        fraction_elapsed = 0.0
    return jd_birth - fraction_elapsed * total_dasa_years * _custom_year_days


def ephemeris_in_use(jd_utc: float) -> str:
    """'swiss' when .se1 files serve this date, else 'moshier'."""
    _, flag = swe.calc_ut(jd_utc, swe.MOON, swe.FLG_SWIEPH)
    return "moshier" if flag & swe.FLG_MOSEPH else "swiss"


def _drik_globals() -> dict:
    """The namespace drik's own functions resolve module globals in.

    PyJHora loads `drik` into a private globals dict and re-exports a module
    object whose __dict__ is a copy: `drik.X = v` updates only the copy, so
    names read *inside* drik functions (PLANET_FLAGS, dhasa_year_duration)
    would keep the stale value. Patch this dict — and the module attribute
    too, for callers that read `drik.X` as an attribute.
    """
    return drik.sidereal_longitude.__globals__


def configure():
    """One-time process setup: ephemeris path, extra ayanamsa ids, dasha-year hook."""
    global _configured, _orig_dhasa_year_duration, _orig_end_jd, _orig_start_jd
    with _lock:
        if _configured:
            return
        swe.set_ephe_path(os.pathsep.join([EPHE_DIR, const._ephe_path]))
        for k, v in _EXTRA_AYANAMSAS.items():
            const.available_ayanamsa_modes[k] = v
        dg = _drik_globals()
        _orig_dhasa_year_duration = dg["dhasa_year_duration"]
        dg["dhasa_year_duration"] = drik.dhasa_year_duration = _dhasa_year_duration
        _orig_end_jd, _orig_start_jd = dg["_get_dhasa_end_jd"], dg["_get_dhasa_start_jd"]
        dg["_get_dhasa_end_jd"], dg["_get_dhasa_start_jd"] = _dhasa_end_jd, _dhasa_start_jd
        drik._get_dhasa_end_jd, drik._get_dhasa_start_jd = _dhasa_end_jd, _dhasa_start_jd
        _configured = True
        if ephemeris_in_use(2459580.5) != "swiss":
            log.warning("Swiss Ephemeris files not found in %s; falling back to the "
                        "Moshier ephemeris (lower precision).", EPHE_DIR)


def _true_node_supported() -> bool:
    """Smoke test: PyJHora true-node mode returns Rahu equal to swe TRUE_NODE."""
    global _true_node_ok
    if _true_node_ok is None:
        prev = const._use_true_nodes_for_rahu_ketu
        try:
            drik.set_planet_list(set_rahu_ketu_as_true_nodes=True)
            jd = 2459580.5
            smoke = drik.Place("smoke", 25.4, 82.57, 5.5)
            swe.set_topo(82.57, 25.4, 0.0)   # safe; needed only if TOPOCTR flag is on
            rasi = charts.rasi_chart(jd, smoke)
            rahu = next(p for p in rasi if p[0] == 7)[1]
            got = rahu[0] * 30 + rahu[1]
            want = swe.calc_ut(jd - 5.5 / 24, swe.TRUE_NODE, drik.PLANET_FLAGS)[0][0] % 360
            d = abs(got - want) % 360
            _true_node_ok = min(d, 360 - d) < 0.01
        except Exception:
            _true_node_ok = False
        finally:
            drik.set_planet_list(set_rahu_ketu_as_true_nodes=prev)
    return _true_node_ok


def apply(cs: CalcSettings) -> None:
    """Push `cs` into PyJHora / swisseph globals (no-op when unchanged)."""
    global _applied, _custom_year_days
    configure()
    with _lock:
        if _applied == cs:
            return
        if cs.node == "true" and not _true_node_supported():
            raise ValueError("node='true' is not supported: PyJHora's true-node mode failed "
                             "its smoke test in this environment; use node='mean'.")
        drik.set_ayanamsa_mode(cs.ayanamsa)
        const._use_true_nodes_for_rahu_ketu = cs.node == "true"
        drik.set_planet_list(set_rahu_ketu_as_true_nodes=cs.node == "true")
        const.PLANET_POSITIONS_TRUE = cs.positions == "true"
        # topocentric adds swe.FLG_TOPOCTR; drik._set_observer then feeds the
        # chart's lat/lon to swe.set_topo before every place-aware call.
        const.PLANET_POSITIONS_GEOCENTRIC = cs.center == "geocentric"
        drik.refresh_planet_flags()
        drik.PLANET_FLAGS = _drik_globals()["PLANET_FLAGS"]   # keep the copied module attr in sync
        if cs.dasha_year in _CUSTOM_YEARS:
            _custom_year_days = _CUSTOM_YEARS[cs.dasha_year]
            const.dhasa_year_duration_default = const.DHASA_YEAR_DURATION.MEAN_SIDEREAL_YEAR
        else:
            _custom_year_days = None
            const.dhasa_year_duration_default = _YEAR_TYPES[cs.dasha_year]
        _applied = cs


def dasha_year_days(cs: CalcSettings, jd, place) -> float:
    with _lock:
        apply(cs)
        return float(drik.dhasa_year_duration(jd=jd, place=place))


def _dms(deg: float) -> str:
    total = round(abs(deg) * 3600, 2)
    d, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{'-' if deg < 0 else ''}{int(d)}°{int(m):02d}′{s:05.2f}″"


def _lagna_speed_deg_per_min(jd, place) -> float:
    try:
        return float(drik.ascendant_speed(jd, place)) / (24 * 60)
    except Exception:
        _, lat, lon, tz = place
        jd_utc = jd - tz / 24.0
        a = swe.houses_ex(jd_utc, lat, lon, b"W", swe.FLG_SIDEREAL)[1][0]
        b = swe.houses_ex(jd_utc + 1 / 1440, lat, lon, b"W", swe.FLG_SIDEREAL)[1][0]
        return ((b - a + 180) % 360) - 180


def node_sensitivity(jd_utc: float, cs: CalcSettings = DEFAULT_SETTINGS, place=None) -> dict:
    """Compare mean vs true node (sidereal, current ayanamsa): D1 / D9 sign differences."""
    with _lock:
        apply(cs)
        if cs.center == "topocentric" and place is not None:
            swe.set_topo(place.longitude, place.latitude, 0.0)
        out = {}
        for key, body in (("mean", swe.MEAN_NODE), ("true", swe.TRUE_NODE)):
            lon = swe.calc_ut(jd_utc, body, drik.PLANET_FLAGS)[0][0] % 360
            out[key] = {"longitude": round(lon, 4), "sign": int(lon // 30),
                        "d9_sign": int(lon * 9 // 30) % 12}
        sep = abs(out["mean"]["longitude"] - out["true"]["longitude"])
        out["separation_deg"] = round(min(sep, 360 - sep), 4)
        out["d1_differs"] = out["mean"]["sign"] != out["true"]["sign"]
        out["d9_differs"] = out["mean"]["d9_sign"] != out["true"]["d9_sign"]
        out["flag"] = out["d1_differs"] or out["d9_differs"]
        return out


def node_chart_sensitivity(jd, place, rasi, cs: CalcSettings, year_days: float) -> dict:
    """Mean-vs-true node effects beyond raw position.

    Recomputes the rasi with the other node kind and compares what actually
    changes downstream: the co-lord Chara year counts for Scorpio and
    Aquarius, the whole first-cycle year sequence, and the Chara Karaka
    assignments. Callers must hold `calc_lock`; the configured settings are
    restored before returning.
    """
    out = {}
    alt = replace(cs, node="true" if cs.node == "mean" else "mean")
    try:
        apply(alt)
        alt_rasi = charts.rasi_chart(jd, place)
    finally:
        apply(cs)
    diffs = {}
    for s in (7, 10):                        # Scorpio, Aquarius — co-lord signs
        try:
            y_a = J.sign_years(rasi, s, cs.chara_school, cs.colord_rule)[0]
            y_b = J.sign_years(alt_rasi, s, cs.chara_school, cs.colord_rule)[0]
            if y_a != y_b:
                diffs[K.SIGN_NAMES[s]] = [y_a, y_b]
        except Exception:
            pass
    out["chara_years_differ"] = bool(diffs)
    if diffs:
        out["chara_year_diffs"] = diffs
    try:
        seq_a = [p["years"] for p in J.chara_periods(
            rasi, jd, cs.chara_school, year_days, cycles=1, colord_rule=cs.colord_rule)]
        seq_b = [p["years"] for p in J.chara_periods(
            alt_rasi, jd, cs.chara_school, year_days, cycles=1, colord_rule=cs.colord_rule)]
        out["chara_sequence_differs"] = seq_a != seq_b
    except Exception:
        out["chara_sequence_differs"] = None
    try:
        ka = J.karakas(rasi, cs.karaka_scheme)["karakas"]
        kb = J.karakas(alt_rasi, cs.karaka_scheme)["karakas"]
        kdiff = {k: [ka.get(k), kb.get(k)] for k in set(ka) | set(kb)
                 if ka.get(k) != kb.get(k)}
        out["karaka_rank_differs"] = bool(kdiff)
        if kdiff:
            out["karaka_diffs"] = kdiff
    except Exception:
        out["karaka_rank_differs"] = None
    return out


def fingerprint(settings: dict) -> str:
    base = {
        "pyjhora": PYJHORA_VERSION, "pyswisseph": swe.version,
        "calc_settings": settings.get("calc_settings") or DEFAULT_SETTINGS.fingerprint_dict(),
        "houses": "whole-sign (sripati bhava for cusps)",
        "vargas": "classical-v2: Leo/Cancer Hora, Parashari D6",
        "dasha": "vimshottari, moon-star, tribhagi=false",
        "birth_time_precision": settings.get("birth_time_precision", "exact"),
        # birth inputs: a different birth time/place is a different chart
        "birth": [settings.get(k) for k in ("year", "month", "day", "hour", "minute", "second")]
                 + [None if settings.get(k) is None else round(float(settings[k]), 4)
                    for k in ("lat", "lon")]
                 + [None if settings.get("tz_offset") is None
                    else round(float(settings["tz_offset"]), 3)],
    }
    raw = json.dumps(base, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def birth_fingerprint(b: "BirthInput") -> str:
    """Calc fingerprint including the birth inputs themselves."""
    return fingerprint({
        "birth_time_precision": b.birth_time_precision,
        "year": b.year, "month": b.month, "day": b.day, "hour": b.hour,
        "minute": b.minute, "second": b.second, "lat": b.lat, "lon": b.lon,
        "tz_offset": b.tz_offset, "calc_settings": b.settings.fingerprint_dict(),
    })


def _pos_list_to_dict(positions) -> dict:
    """PyJHora [['L',(sign,deg)],[pid,(sign,deg)],...] -> normalized records."""
    out = {}
    for pid, (sign, deg) in positions:
        key = "Lagna" if pid == "L" else K.PLANET_NAMES[pid]
        out[key] = {"sign": int(sign), "degree": round(float(deg), 5),
                    "abs_longitude": round((int(sign) * 30 + float(deg)) % 360, 5)}
    return out


def _nakshatra(abs_long: float):
    idx = int(abs_long // K.NAK_SPAN) % 27
    pada = int((abs_long % K.NAK_SPAN) / (K.NAK_SPAN / 4)) + 1
    return {"name": K.NAKSHATRAS[idx], "index": idx + 1, "pada": pada,
            "lord": K.PLANET_NAMES[K.NAK_LORD_SEQUENCE[idx % 9]]}


def _house(sign: int, lagna_sign: int) -> int:
    return (sign - lagna_sign) % 12 + 1


def _dignity(planet: int, sign: int, degree: float) -> list[str]:
    tags = []
    ex = K.EXALTATION.get(planet)
    if ex and ex[0] == sign:
        tags.append("exalted")
    db = K.DEBILITATION.get(planet)
    if db and db[0] == sign:
        tags.append("debilitated")
    if sign in K.OWN_SIGNS.get(planet, []):
        tags.append("own sign")
    for s, lo, hi in K.MOOLATRIKONA.get(planet, []):
        if s == sign and lo <= degree < hi:
            tags.append("moolatrikona")
    return tags


def _gandanta(sign: int, degree: float, span: float = K.GANDANTA_PADA_SPAN) -> bool:
    for water, fire in K.GANDANTA_JUNCTIONS:
        if sign == water and degree >= 30 - span:
            return True
        if sign == fire and degree < span:
            return True
    return False


def _ashtakavarga_extras(bav, sav, h2p) -> dict:
    """Lagna BAV and shodhana as separate facts; SAV is labelled as excluding Lagna."""
    out = {"sav_includes_lagna": False,
           "sav_total": sum(sav) if sav else None,
           "sav_label": "Sarvashtakavarga = Sun..Saturn only, Lagna excluded (total 337)",
           "lagna_bav": None, "shodhana": None}
    if not bav or len(bav) < 8:
        return out
    out["lagna_bav"] = {"values": [int(v) for v in bav[7]], "total": int(sum(bav[7]))}
    try:
        planets7 = [[int(v) for v in row] for row in bav[:7]]
        tri = ashtakavarga._trikona_sodhana([r[:] for r in planets7])
        eka = ashtakavarga._ekadhipatya_sodhana([r[:] for r in tri], h2p)
        raasi, graha, sodhya = ashtakavarga.sodhaya_pindas([r[:] for r in planets7], h2p)
        out["shodhana"] = {
            "trikona": {K.PLANET_NAMES[i]: tri[i] for i in range(7)},
            "ekadhipatya": {K.PLANET_NAMES[i]: eka[i] for i in range(7)},
            "raasi_pinda": {K.PLANET_NAMES[i]: raasi[i] for i in range(7)},
            "graha_pinda": {K.PLANET_NAMES[i]: graha[i] for i in range(7)},
            "shodhya_pinda": {K.PLANET_NAMES[i]: sodhya[i] for i in range(7)},
            "source": "PyJHora trikona/ekadhipatya shodhana (PVR rasimana multipliers)",
        }
    except Exception:
        log.exception("ashtakavarga shodhana unavailable")
    return out


def _date_tuple(dt):
    return (dt.year, dt.month, dt.day)


def _ymd(jd_val) -> str:
    y, m, d, h = utils.jd_to_gregorian(jd_val)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _chara_karakas_7(rasi, scheme: str = "7_KNRao") -> dict:
    """Chara karakas from full-precision degrees within the sign.

    Default scheme is the seven-karaka K.N. Rao scheme (Sun..Saturn); 8_Rath
    adds Rahu (30 - degree) and 7or8_PVR adds it only when two of the seven
    share an integer degree. Ties within 60 arcseconds are reported by
    `jaimini.karakas`, not hidden here.
    """
    return J.karakas(rasi, scheme)["karakas"]


@dataclass
class BirthInput:
    name: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    lat: float
    lon: float
    tz_offset: float
    place_label: str
    birth_time_precision: str = "exact"   # exact | approximate | unknown
    settings: CalcSettings = DEFAULT_SETTINGS


class ChartEngine:
    """Computes and caches locked chart facts per birth input."""

    def __init__(self, cache_size: int | None = None):
        configure()
        self._cache: OrderedDict = OrderedDict()
        self._cache_size = max(1, cache_size or settings.CHART_CACHE_SIZE)
        self._cache_lock = threading.Lock()

    # ---------- core ----------

    def compute(self, b: BirthInput) -> dict:
        key = (b.year, b.month, b.day, b.hour, b.minute, b.second,
               round(b.lat, 4), round(b.lon, 4), round(b.tz_offset, 3),
               b.birth_time_precision,
               json.dumps(b.settings.fingerprint_dict(), sort_keys=True))
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        with _lock:
            apply(b.settings)
            facts = self._compute_locked(b)
        with self._cache_lock:
            self._cache[key] = facts
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return facts

    def _compute_locked(self, b: BirthInput) -> dict:
        place = drik.Place(b.place_label, b.lat, b.lon, b.tz_offset)
        jd = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
        dob = drik.Date(b.year, b.month, b.day)
        tob = (b.hour, b.minute, b.second)

        rasi = charts.rasi_chart(jd, place)
        d1 = _pos_list_to_dict(rasi)
        lagna_sign = d1["Lagna"]["sign"]
        lagna_lord = K.SIGN_LORD[lagna_sign]

        # divisional charts
        vargas = {"D1": d1}
        varga_funcs = dict(VARGA_FUNCS)
        if b.settings.d24 == "reverse":
            varga_funcs["D24"] = partial(charts.chaturvimsamsa_chart, chart_method=2)
        for name, fn in varga_funcs.items():
            if fn is None or name == "D1":
                continue
            try:
                vargas[name] = _pos_list_to_dict(fn(rasi))
            except Exception:
                pass  # unavailable varga is recorded as absent, never guessed

        retro = set(drik.planets_in_retrograde(jd, place))
        try:
            retro = {r for r in retro if isinstance(r, int)}
        except TypeError:
            retro = set()

        planets = {}
        sun_long = d1["Sun"]["abs_longitude"]
        for pid in K.GRAHA_IDS:
            pname = K.PLANET_NAMES[pid]
            rec = d1[pname]
            nak = _nakshatra(rec["abs_longitude"])
            comb = False
            if pid not in (0, 7, 8):
                sep = abs(rec["abs_longitude"] - sun_long)
                sep = min(sep, 360 - sep)
                orb = K.combust_orb(pid, pid in retro, b.settings.combust_table)
                comb = bool(orb and sep < orb)
            boundary_flags = []
            if rec["degree"] <= 2.0 or rec["degree"] >= 28.0:
                boundary_flags.append("within 2° of a sign boundary — treat position with care")
            planets[pname] = {
                **rec,
                "sign_name": K.SIGN_NAMES[rec["sign"]],
                "house": _house(rec["sign"], lagna_sign),
                "nakshatra": nak,
                "retrograde": pid in retro,
                "combust": comb,
                "gandanta": _gandanta(rec["sign"], rec["degree"], b.settings.gandanta_arc),
                "sandhi": (rec["degree"] < b.settings.sandhi_arc
                           or rec["degree"] >= 30 - b.settings.sandhi_arc),
                "dignity": _dignity(pid, rec["sign"], rec["degree"]),
                "boundary_flags": boundary_flags,
            }

        # houses / lords
        houses = {}
        for h in range(1, 13):
            s = (lagna_sign + h - 1) % 12
            houses[h] = {"sign": s, "sign_name": K.SIGN_NAMES[s],
                         "lord": K.PLANET_NAMES[K.SIGN_LORD[s]]}

        func = K.FUNCTIONAL[lagna_sign]
        maraka = sorted({houses[2]["lord"], houses[7]["lord"]})
        modality = K.SIGN_MODALITY[lagna_sign]
        badhaka_house = {"movable": 11, "fixed": 9, "dual": 7}[modality]

        lagna_deg = d1["Lagna"]["degree"]
        lagna_flags = []
        if lagna_deg <= 2.0 or lagna_deg >= 28.0:
            lagna_flags.append("Lagna within 2° of a sign boundary — birth-time accuracy matters here")

        # nakshatra vimshottari
        _, periods = vimsottari.get_dhasa_antardhasa(
            dob, tob, place, dhasa_level_index=2, return_exact_bounds=True)
        md = []
        seen_md = set()
        for lords, start_jd, end_jd, dur in periods:
            if lords[0] not in seen_md:
                seen_md.add(lords[0])
            md.append({
                "lords": [K.PLANET_NAMES[l] for l in lords],
                "maha": K.PLANET_NAMES[lords[0]],
                "antar": K.PLANET_NAMES[lords[1]] if len(lords) > 1 else None,
                "start": _ymd(start_jd), "end": _ymd(end_jd),
                "start_jd": start_jd, "end_jd": end_jd,
            })

        # jaimini
        jaimini = self._jaimini(rasi, place, dob, tob, b.settings)

        # ashtakavarga SAV
        try:
            h2p = utils.get_house_planet_list_from_planet_positions(rasi)
            bav, sav, prav = ashtakavarga.get_ashtaka_varga(h2p)
        except Exception:
            sav = None
            bav = None
            prav = None
            h2p = None
        ashtaka = _ashtakavarga_extras(bav, sav, h2p)

        # shadbala (planetary strength) + bhava chalit houses — best effort
        try:
            shad = strength.shad_bala(jd, place)
        except Exception:
            shad = None
        try:
            # rows: [bhava_start_sign, (start, mid, end) longitudes, planet ids]
            # entries are ordered from the lagna bhava — index+1 is the chalit house
            bhava = {}
            for i, entry in enumerate(charts.bhava_chart(jd, place)):
                for pid in entry[2]:
                    if isinstance(pid, int) and pid in K.PLANET_NAMES:
                        bhava[K.PLANET_NAMES[pid]] = i + 1
        except Exception:
            bhava = None

        jd_utc = jd - b.tz_offset / 24.0
        cs = b.settings
        warnings = []
        eph = ephemeris_in_use(jd_utc)
        if eph != "swiss":
            warnings.append("Swiss Ephemeris files unavailable for this date; Moshier "
                            "ephemeris used (slightly lower precision).")
        if abs(b.lat) > 60:
            speed = _lagna_speed_deg_per_min(jd, place)
            warnings.append(
                f"High latitude ({b.lat:.2f}°): the Lagna moves ~{abs(speed):.2f}°/min, so a "
                "few minutes of birth-time error can change the Lagna sign or degree; "
                "house systems are also less reliable here.")
        ay = swe.get_ayanamsa_ut(jd_utc)
        node_check = node_sensitivity(jd_utc, cs, place)
        try:
            node_check.update(node_chart_sensitivity(
                jd, place, rasi, cs,
                float(drik.dhasa_year_duration(jd=jd, place=place))))
        except Exception:
            node_check["chart_flags_unavailable"] = True

        facts = {
            "meta": {
                "ayanamsa": {"id": cs.ayanamsa, "degrees": round(ay, 6), "dms": _dms(ay)},
                "ephemeris": eph, "node": cs.node, "positions": cs.positions,
                "center": cs.center,
                "dasha_year": {"mode": cs.dasha_year,
                               "days": round(float(drik.dhasa_year_duration(jd=jd, place=place)), 6)},
                "warnings": warnings,
                "calc_settings": cs.fingerprint_dict(),
                "arcs": {"gandanta_deg": cs.gandanta_arc, "sandhi_deg": cs.sandhi_arc,
                         "combust_table": cs.combust_table},
                "place": b.place_label, "lat": b.lat, "lon": b.lon,
                "utc_offset_hours": b.tz_offset,
                "birth_datetime_local": f"{b.year:04d}-{b.month:02d}-{b.day:02d} {b.hour:02d}:{b.minute:02d}:{b.second:02d}",
                "julian_day": jd,
                "birth_time_precision": b.birth_time_precision,
            },
            "lagna": {"sign": lagna_sign, "sign_name": K.SIGN_NAMES[lagna_sign],
                      "degree": lagna_deg, "lord": K.PLANET_NAMES[lagna_lord],
                      "nakshatra": _nakshatra(d1["Lagna"]["abs_longitude"]),
                      "boundary_flags": lagna_flags},
            "planets": planets,
            "houses": houses,
            "functional": {
                "benefics": sorted(K.PLANET_NAMES[p] for p in func["benefics"]),
                "malefics": sorted(K.PLANET_NAMES[p] for p in func["malefics"]),
                "yogakaraka": K.PLANET_NAMES[func["yogakaraka"]] if func["yogakaraka"] is not None else None,
                "source": K.FUNCTIONAL_SOURCE,
                "maraka_lords": maraka,
                "badhaka": {"house": badhaka_house, "lord": houses[badhaka_house]["lord"]},
            },
            "vimshottari": {"periods": md},
            "jaimini": jaimini,
            "sarvastakavarga": sav,
            "ashtakavarga": ashtaka,
            "binnashtakavarga": bav,
            "prastara_ashtakavarga": prav,
            "shadbala": shad,
            "bhava": bhava,
            "vargas": vargas,
            "node_check": node_check,
        }
        return facts

    # ---------- jaimini ----------

    def _jaimini(self, rasi, place, dob, tob, cs: CalcSettings = DEFAULT_SETTINGS) -> dict:
        kar = J.karakas(rasi, cs.karaka_scheme)
        out = {"karakas": kar["karakas"], "karaka_scheme": cs.karaka_scheme,
               "karaka_ties": kar["ties"],
               "arudha_lagna": None, "upapada_lagna": None}
        try:
            colord = cs.chara_school if cs.colord_rule == "school" else cs.colord_rule
            ar = J.arudhas(rasi, cs.arudha_exception, colord)
            # ar: list of 12 arudha sign indices (A1..A12), 0-based signs
            def _s(v):
                return {"sign": int(v), "sign_name": K.SIGN_NAMES[int(v)]}
            out["arudhas"] = {f"A{i+1}": int(a) for i, a in enumerate(ar)}
            out["arudha_lagna"] = {**_s(ar[0]), "note": "A1 (Arudha Lagna)"}
            out["A10"] = {**_s(ar[9]), "note": "A10 (career arudha)"}
            out["upapada_lagna"] = {**_s(ar[11]), "note": "A12 (Upapada Lagna)"}
            out["arudha_rules"] = {"exception": cs.arudha_exception, "colord_rule": colord}
        except Exception:
            log.exception("arudha computation failed")
        return out

    # ---------- dasha / transit helpers ----------

    def running_vimshottari(self, b: BirthInput, when) -> list:
        """Running MD/AD/PD for a target date. `when` = (y,m,d) tuple."""
        with _lock:
            apply(b.settings)
            return self._running_vimshottari(b, when)

    def _running_vimshottari(self, b: BirthInput, when) -> list:
        place = drik.Place(b.place_label, b.lat, b.lon, b.tz_offset)
        jd_birth = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
        jd_now = utils.julian_day_number(when, (12, 0, 0))
        rows = vimsottari.get_running_dhasa_for_given_date(jd_now, jd_birth, place, dhasa_level_index=3)
        out = []
        for lords, start, end in rows:
            out.append({
                "lords": [K.PLANET_NAMES[l] for l in lords],
                "start": f"{start[0]:04d}-{start[1]:02d}-{start[2]:02d}",
                "end": f"{end[0]:04d}-{end[1]:02d}-{end[2]:02d}",
            })
        return out

    def running_chara(self, b: BirthInput, when) -> list:
        """Running Jaimini Chara dasha signs for a target date."""
        with _lock:
            apply(b.settings)
            return self._running_chara(b, when)

    def _running_chara(self, b: BirthInput, when) -> list:
        """Running Chara MD and AD for `when`, from jaimini.chara_periods."""
        place = drik.Place(b.place_label, b.lat, b.lon, b.tz_offset)
        jd_birth = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
        jd_now = utils.julian_day_number(when, (12, 0, 0))
        try:
            rasi = charts.rasi_chart(jd_birth, place)
            year_days = float(drik.dhasa_year_duration(jd=jd_birth, place=place))
            cs = b.settings
            periods = J.chara_periods(rasi, jd_birth, cs.chara_school, year_days,
                                      colord_rule=cs.colord_rule)
        except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
            log.exception("chara dasha unavailable")
            return []
        for md in periods:
            if md["start_jd"] <= jd_now < md["end_jd"]:
                ad = next((a for a in md["antardashas"] if a["start_jd"] <= jd_now < a["end_jd"]), None)
                rows = [(["{}".format(K.SIGN_NAMES[md["sign"]])], md["start_jd"], md["end_jd"])]
                if ad:
                    rows.append(([K.SIGN_NAMES[md["sign"]], K.SIGN_NAMES[ad["sign"]]],
                                 ad["start_jd"], ad["end_jd"]))
                return [{"signs": signs, "start": _ymd(a), "end": _ymd(z)} for signs, a, z in rows]
        return []

    def transit_positions(self, when, place_tuple, calc: CalcSettings | None = None) -> dict:
        """Sidereal planet positions on a given (y,m,d) for a place.

        With calc=None the currently applied settings are used."""
        with _lock:
            if calc is not None:
                apply(calc)
            return self._transit_positions(when, place_tuple)

    def _transit_positions(self, when, place_tuple) -> dict:
        jd_t = utils.julian_day_number(when, (12, 0, 0))
        pos = drik.dhasavarga(jd_t, place_tuple, divisional_chart_factor=1)
        out = {}
        for pid, (sign, deg) in pos:
            key = "Lagna" if pid == "L" else K.PLANET_NAMES.get(pid)
            if key:
                out[key] = {"sign": int(sign), "degree": round(float(deg), 4)}
        return out

    def muntha_sign(self, lagna_sign: int, completed_years: int) -> int:
        """Annual Muntha sign progression (documented simplification)."""
        return ((lagna_sign + completed_years) % 12) + 1


engine = ChartEngine()
