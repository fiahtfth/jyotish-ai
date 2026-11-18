"""Offline geocoding + historical timezone resolution.

Uses PyJHora's bundled GeoNames CSV (~68k cities) for place lookup and
zoneinfo + timezonefinder for the *historical* UTC offset at the birth
datetime (the CSV only stores the current offset).
"""
import csv
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

_CSV = os.path.join(
    os.path.dirname(__file__), "..", "data", "geonames_places_5k.csv",
)
if not os.path.exists(_CSV):
    _CSV = os.path.join(
        os.path.dirname(__file__), "..", "..",
        ".venv-libs", "jhora-data", "geonames_places_5k.csv",
    )

def _package_csv() -> str:
    """Locate the CSV inside the installed jhora package (any Python version)."""
    import importlib.util
    spec = importlib.util.find_spec("jhora")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            cand = os.path.join(loc, "data", "geonames_places_5k.csv")
            if os.path.exists(cand):
                return cand
    return ""


# Fall back to the installed package location
if not os.path.exists(_CSV):
    _CSV = _package_csv() or _CSV

_tf = TimezoneFinder()
_places: list[dict] = []


def _load() -> list[dict]:
    global _places
    if _places:
        return _places
    with open(_CSV, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row or row[0] == "place_name":
                continue
            try:
                _places.append({
                    "name": row[0],
                    "alt": row[1].lower(),
                    "state": row[2],
                    "country": row[3],
                    "lat": float(row[4]),
                    "lon": float(row[5]),
                    "tz": float(row[6]),
                })
            except (ValueError, IndexError):
                continue
    return _places


def _score(place: dict, q: str) -> float:
    name = place["name"].lower()
    if name == q:
        return 0
    if name.startswith(q):
        return 1
    if q in name:
        return 2
    for alias in place["alt"].split("|"):
        if alias.startswith(q) or q in alias:
            return 3
    return 99


def search_places(query: str, limit: int = 8) -> list[dict]:
    """Substring search over name + alternates, best matches first."""
    q = query.strip().lower().split(",")[0]
    if len(q) < 2:
        return []
    results = []
    for p in _load():
        if q in p["name"].lower() or q in p["alt"]:
            results.append((_score(p, q), p))
    results.sort(key=lambda t: t[0])
    out = []
    for _, p in results[:limit]:
        out.append({
            "name": p["name"], "state": p["state"], "country": p["country"],
            "latitude": p["lat"], "longitude": p["lon"],
            "label": ", ".join(x for x in [p["name"], p["state"], p["country"]] if x),
        })
    return out


def historical_utc_offset(lat: float, lon: float, when: datetime, fallback: float) -> float:
    """UTC offset (hours) at lat/lon for the local datetime `when`."""
    tzname = _tf.timezone_at(lat=lat, lng=lon)
    if not tzname:
        return fallback
    try:
        tz = ZoneInfo(tzname)
    except ZoneInfoNotFoundError:
        return fallback
    naive = when.replace(tzinfo=None)
    offset = naive.replace(tzinfo=tz).utcoffset()
    return offset.total_seconds() / 3600.0


class NonexistentTime(ValueError):
    """The local wall time falls in a DST gap (it never occurred)."""

    def __init__(self, local_dt: datetime, before: float, after: float, tz_name: str):
        self.local_dt, self.before, self.after, self.tz_name = local_dt, before, after, tz_name
        super().__init__(f"{local_dt:%Y-%m-%d %H:%M:%S} did not exist in {tz_name} "
                         f"(clocks jumped from UTC{before:+g} to UTC{after:+g})")


class AmbiguousTime(ValueError):
    """The local wall time occurred twice (DST overlap); `offsets` = [fold 0, fold 1]."""

    def __init__(self, local_dt: datetime, offsets: list[float], tz_name: str):
        self.local_dt, self.offsets, self.tz_name = local_dt, offsets, tz_name
        super().__init__(f"{local_dt:%Y-%m-%d %H:%M:%S} occurred twice in {tz_name} "
                         f"(UTC{offsets[0]:+g} and UTC{offsets[1]:+g}); choose which")


def tzdb_version() -> str:
    try:
        from importlib.metadata import version
        return version("tzdata")
    except Exception:
        pass
    import zoneinfo
    for base in zoneinfo.TZPATH:
        try:
            with open(os.path.join(base, "tzdata.zi"), encoding="utf-8") as f:
                head = f.readline().strip()
            if head.startswith("# version"):
                return head.split()[-1]
        except OSError:
            continue
    return "unknown"


_KOLKATA = (22.5726, 88.3639)
_MUMBAI = (18.9388, 72.8354)


def _is_india(country: Optional[str], tz_name: str) -> bool:
    return (country or "").strip().lower() == "india" or tz_name in ("Asia/Kolkata", "Asia/Calcutta")


def _fmt_off(h: float) -> str:
    sign = "-" if h < 0 else "+"
    secs = round(abs(h) * 3600)
    return f"{sign}{secs // 3600}:{secs % 3600 // 60:02d}" + (f":{secs % 60:02d}" if secs % 60 else "")


def _historical_warnings(lat, lon, local_dt, country, state, tz_name, offset) -> list[str]:
    out = []
    day = local_dt.date()
    if not _is_india(country, tz_name):
        return out
    if day < datetime(1906, 1, 1).date():
        out.append("Before 1906 India had no standard time; places kept their own local mean "
                   "time, so the offset used is uncertain. Consider the local-mean-time basis.")
    st = (state or "").strip().lower()
    if day < datetime(1948, 1, 1).date() and (
            st == "west bengal" or haversine_km(lat, lon, *_KOLKATA) <= 150):
        out.append("Calcutta used Calcutta Time (GMT+5:53:20) until 1948, about 23 minutes from "
                   f"IST; the offset used is {_fmt_off(offset)}. Check which clock your record used.")
    if day < datetime(1955, 1, 1).date() and (
            st in ("maharashtra", "gujarat") or haversine_km(lat, lon, *_MUMBAI) <= 150):
        out.append("Bombay Time (GMT+4:51) was used in the Bombay region until 1955, about 39 "
                   f"minutes from IST; the offset used is {_fmt_off(offset)}. Check which clock "
                   "your record used.")
    if datetime(1941, 10, 1).date() <= day <= datetime(1945, 10, 15).date():
        out.append("India observed wartime clocks (1941-10-01 to 1945-10-15, often IST+1 = +6:30). "
                   "Was the birth time recorded in war time or in standard time?")
    return out


def _offset_at_utc(tz: ZoneInfo, utc_naive: datetime) -> float:
    aware = utc_naive.replace(tzinfo=timezone.utc).astimezone(tz)
    return aware.utcoffset().total_seconds() / 3600.0


def resolve_offset(lat: float, lon: float, local_dt: datetime, *, country: Optional[str] = None,
                   state: Optional[str] = None, basis: str = "zone",
                   manual_offset: Optional[float] = None, fold: Optional[int] = None) -> dict:
    """UTC offset for a local birth time.

    basis: "zone" (historical tz database), "lmt" (local mean time = lon/15 h) or
    "manual" (`manual_offset` hours). Zone basis raises NonexistentTime in a DST gap and
    AmbiguousTime in an overlap unless `fold` (0 = first occurrence, 1 = second) is given.
    """
    naive = local_dt.replace(tzinfo=None)
    version = tzdb_version()
    warnings: list[str] = []
    ambiguity = None
    if basis == "manual":
        if manual_offset is None or not -14 <= float(manual_offset) <= 14:
            raise ValueError("a manual UTC offset between -14 and +14 hours is required")
        offset, tz_name, source = float(manual_offset), "manual", "manual"
    elif basis == "lmt":
        offset, tz_name, source = lon / 15.0, "LMT", "lmt"
    elif basis == "zone":
        tz_name = _tf.timezone_at(lat=lat, lng=lon) or ""
        tz = None
        if tz_name:
            try:
                tz = ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                tz = None
        if tz is None:
            offset = 5.5 if (country or "").lower() == "india" else round(lon / 15.0 * 2) / 2
            source = "fallback"
            warnings.append("No time zone was found for this place; an estimated offset "
                            f"({_fmt_off(offset)}) was used. Pick a time basis explicitly.")
        else:
            a0, a1 = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
            o0, o1 = a0.utcoffset().total_seconds() / 3600.0, a1.utcoffset().total_seconds() / 3600.0
            source = "tzdb"
            if o0 != o1:
                def exists(a):
                    return a.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive
                if not exists(a0) and not exists(a1):
                    raise NonexistentTime(naive, o0, o1, tz_name)
                if fold is None:
                    raise AmbiguousTime(naive, [o0, o1], tz_name)
                offset = o1 if int(fold) == 1 else o0
                ambiguity = {"fold": int(fold), "offsets": [o0, o1]}
                warnings.append(f"This local time occurred twice; the {'second' if fold else 'first'} "
                                f"occurrence (UTC{_fmt_off(offset)}) was used.")
            else:
                offset = o0
            utc0 = naive - timedelta(hours=offset)
            if _offset_at_utc(tz, utc0 - timedelta(hours=1)) != _offset_at_utc(tz, utc0 + timedelta(hours=1)):
                warnings.append("The UTC offset changes within an hour of this time (a DST or zone "
                                "transition); confirm the recorded clock time.")
    else:
        raise ValueError(f"unknown time basis {basis!r}")
    warnings.extend(_historical_warnings(lat, lon, naive, country, state,
                                         tz_name if basis == "zone" else "", offset))
    return {"offset_hours": offset, "tz_name": tz_name, "source": source,
            "tzdb_version": version, "ambiguity": ambiguity, "warnings": warnings}


def resolve_place(label_or_name: str, state: str = "", country: str = "",
                  lat: Optional[float] = None, lon: Optional[float] = None,
                  birth_dt: Optional[datetime] = None, basis: str = "zone",
                  manual_offset: Optional[float] = None, fold: Optional[int] = None) -> dict:
    """Resolve a confirmed place selection into {name, lat, lon, tz_name, offset_hours, ...}."""
    if lat is None or lon is None:
        hits = search_places(label_or_name, limit=1)
        if not hits:
            raise ValueError(f"place not found: {label_or_name}")
        h = hits[0]
        name, lat, lon, state, country = h["name"], h["latitude"], h["longitude"], h["state"], h["country"]
    else:
        name = label_or_name
    tz_name = _tf.timezone_at(lat=lat, lng=lon) or ""
    info = {"offset_source": "default", "tz_warnings": [], "tzdb_version": tzdb_version()}
    if birth_dt is not None:
        r = resolve_offset(lat, lon, birth_dt, country=country, state=state, basis=basis,
                           manual_offset=manual_offset, fold=fold)
        offset = r["offset_hours"]
        info = {"offset_source": r["source"], "tz_warnings": r["warnings"],
                "tzdb_version": r["tzdb_version"]}
        if basis != "zone":
            tz_name = r["tz_name"]
    else:
        offset = 5.5 if country == "India" else 0.0
    return {
        "name": name, "state": state, "country": country,
        "latitude": lat, "longitude": lon,
        "timezone_name": tz_name, "utc_offset_hours": offset, **info,
    }


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
