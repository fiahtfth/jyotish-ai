"""Offline geocoding + historical timezone resolution.

Uses PyJHora's bundled GeoNames CSV (~68k cities) for place lookup and
zoneinfo + timezonefinder for the *historical* UTC offset at the birth
datetime (the CSV only stores the current offset).
"""
import csv
import math
import os
from datetime import datetime
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


def resolve_place(label_or_name: str, state: str = "", country: str = "",
                  lat: Optional[float] = None, lon: Optional[float] = None,
                  birth_dt: Optional[datetime] = None) -> dict:
    """Resolve a confirmed place selection into {name, lat, lon, tz_name, offset_hours}."""
    if lat is None or lon is None:
        hits = search_places(label_or_name, limit=1)
        if not hits:
            raise ValueError(f"place not found: {label_or_name}")
        h = hits[0]
        name, lat, lon, state, country = h["name"], h["latitude"], h["longitude"], h["state"], h["country"]
    else:
        name = label_or_name
    tz_name = _tf.timezone_at(lat=lat, lng=lon) or ""
    if birth_dt is not None:
        offset = historical_utc_offset(lat, lon, birth_dt, fallback=5.5 if country == "India" else 0.0)
    else:
        offset = 5.5 if country == "India" else 0.0
    return {
        "name": name, "state": state, "country": country,
        "latitude": lat, "longitude": lon,
        "timezone_name": tz_name, "utc_offset_hours": offset,
    }


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
