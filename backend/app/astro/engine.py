"""Deterministic PyJHora adapter.

Every astrological "fact" the system uses is produced here, by code —
never by a language model. `compute_chart` returns the locked facts dict
that the orchestrator, the four-pillar engine and the verifier all read.
"""
import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

import swisseph as swe

from jhora import const, utils
from jhora.panchanga import drik
from jhora.horoscope.chart import charts, arudhas, ashtakavarga, strength
from jhora.horoscope.chart import house as house_mod
from jhora.horoscope.dhasa.graha import vimsottari
from jhora.horoscope.dhasa.raasi import chara as chara_dhasa
from jhora.horoscope import main as hmain

from . import constants as K
from ..config import settings

_lock = threading.Lock()
_configured = False
PYJHORA_VERSION = "5.0.0"

VARGA_FUNCS = {
    "D1": charts.rasi_chart, "D2": charts.hora_chart, "D4": charts.chaturthamsa_chart,
    "D7": charts.saptamsa_chart, "D9": charts.navamsa_chart, "D10": charts.dasamsa_chart,
    "D12": charts.dwadasamsa_chart, "D16": charts.shodasamsa_chart,
    "D20": charts.vimsamsa_chart, "D24": charts.chaturvimsamsa_chart,
    "D30": charts.trimshamsa_chart if hasattr(charts, "trimshamsa_chart") else None,
    "D40": charts.khavedamsa_chart, "D60": charts.shashtyamsa_chart,
}
TIME_SENSITIVE_VARGAS = {"D10", "D12", "D16", "D20", "D24", "D30", "D40", "D60"}


def configure():
    """Pin PyJHora into the configuration recorded in every calc fingerprint."""
    global _configured
    with _lock:
        if _configured:
            return
        const._use_true_nodes_for_rahu_ketu = False      # mean nodes
        drik.set_planet_list(set_rahu_ketu_as_true_nodes=False)
        drik.set_ayanamsa_mode("LAHIRI")                  # Lahiri ayanamsa
        _configured = True


def fingerprint(settings: dict) -> str:
    base = {
        "pyjhora": PYJHORA_VERSION, "pyswisseph": swe.version,
        "ayanamsa": "LAHIRI", "houses": "whole-sign (sripati bhava for cusps)",
        "nodes": "mean", "vargas": "parashari counting, method=1",
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
        "tz_offset": b.tz_offset,
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


def _gandanta(sign: int, degree: float) -> bool:
    span = K.GANDANTA_PADA_SPAN
    for water, fire in K.GANDANTA_JUNCTIONS:
        if sign == water and degree >= 30 - span:
            return True
        if sign == fire and degree < span:
            return True
    return False


def _date_tuple(dt):
    return (dt.year, dt.month, dt.day)


def _ymd(jd_val) -> str:
    y, m, d, h = utils.jd_to_gregorian(jd_val)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _chara_karakas_7(rasi) -> dict:
    """Seven-karaka scheme from exact within-sign degrees (Rahu/Ketu excluded).

    Rank the 7 real grahas by their longitude inside the sign; Atmakaraka is
    the most advanced, Darakaraka the least. Documented simplification: ties
    are broken by planetary order, as in most textbook implementations.
    """
    names = ["Atmakaraka", "Amatyakaraka", "Bhratrukaraka", "Matrukaraka",
             "Putrakaraka", "Gnatikaraka", "Darakaraka"]
    ranked = sorted(
        [(pid, rec[1]) for pid, rec in rasi if isinstance(pid, int) and pid <= 6],
        key=lambda t: -t[1],
    )
    return {names[i]: K.PLANET_NAMES[pid] for i, (pid, _) in enumerate(ranked)}


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
               b.birth_time_precision)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

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
        for name, fn in VARGA_FUNCS.items():
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
                orb = K.COMBUST_ORB.get(pid)
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
                "gandanta": _gandanta(rec["sign"], rec["degree"]),
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
        jaimini = self._jaimini(rasi, place, dob, tob)

        # ashtakavarga SAV
        try:
            h2p = utils.get_house_planet_list_from_planet_positions(rasi)
            bav, sav, _ = ashtakavarga.get_ashtaka_varga(h2p)
        except Exception:
            sav = None
            bav = None

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

        facts = {
            "meta": {
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
                "maraka_lords": maraka,
                "badhaka": {"house": badhaka_house, "lord": houses[badhaka_house]["lord"]},
            },
            "vimshottari": {"periods": md},
            "jaimini": jaimini,
            "sarvastakavarga": sav,
            "binnashtakavarga": bav,
            "shadbala": shad,
            "bhava": bhava,
            "vargas": vargas,
        }
        with self._cache_lock:
            self._cache[key] = facts
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return facts

    # ---------- jaimini ----------

    def _jaimini(self, rasi, place, dob, tob) -> dict:
        out = {"karakas": _chara_karakas_7(rasi),
               "arudha_lagna": None, "upapada_lagna": None}
        try:
            ar = arudhas.bhava_arudhas_from_planet_positions(rasi)
            # ar: list of 12 arudha sign indices (A1..A12), 0-based signs
            if ar:
                def _s(v):
                    return {"sign": int(v), "sign_name": K.SIGN_NAMES[int(v)]}
                out["arudhas"] = {f"A{i+1}": int(a) for i, a in enumerate(ar)}
                out["arudha_lagna"] = {**_s(ar[0]), "note": "A1 (Arudha Lagna)"}
                out["A10"] = {**_s(ar[9]), "note": "A10 (career arudha)"}
                out["upapada_lagna"] = {**_s(ar[11]), "note": "A12 (Upapada Lagna)"}
        except Exception:
            pass
        return out

    # ---------- dasha / transit helpers ----------

    def running_vimshottari(self, b: BirthInput, when) -> list:
        """Running MD/AD/PD for a target date. `when` = (y,m,d) tuple."""
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
        place = drik.Place(b.place_label, b.lat, b.lon, b.tz_offset)
        jd_birth = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
        jd_now = utils.julian_day_number(when, (12, 0, 0))
        try:
            rows = chara_dhasa.get_running_dhasa_for_given_date(jd_now, jd_birth, place, dhasa_level_index=2)
            out = []
            for lords, start, end in rows:
                out.append({
                    "signs": [K.SIGN_NAMES[s] if isinstance(s, int) else s for s in lords],
                    "start": f"{start[0]:04d}-{start[1]:02d}-{start[2]:02d}",
                    "end": f"{end[0]:04d}-{end[1]:02d}-{end[2]:02d}",
                })
            return out
        except Exception:
            return []

    def transit_positions(self, when, place_tuple) -> dict:
        """Sidereal planet positions on a given (y,m,d) for a place."""
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
        return ((lagna_sign - 1 + completed_years) % 12) + 1


engine = ChartEngine()
