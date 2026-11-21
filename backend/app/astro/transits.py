"""Sidereal UT transit transitions in the natal chart's calculation frame."""
from datetime import datetime, timedelta, timezone
import logging

from jhora.panchanga import drik
import swisseph as swe

from .constants import NAKSHATRAS, PLANET_NAMES, SIGN_NAMES
from .engine import apply, calc_lock
from .precision import kakshya_lord, _kakshya_charged
from .vargas import nakshatra_pada

log = logging.getLogger(__name__)
BODIES = {"Sun": swe.SUN, "Mars": swe.MARS, "Jupiter": swe.JUPITER, "Saturn": swe.SATURN,
          "Mercury": swe.MERCURY, "Venus": swe.VENUS, "Rahu": swe.MEAN_NODE, "Ketu": swe.MEAN_NODE}
_KETU_OFFSET = {"Ketu": 180.0}   # Ketu = Rahu + 180 deg (same speed); node type follows birth.settings.node
RULE_VERSION = "sidereal-transits-v1"
_PHASES = {11: "first", 0: "second", 1: "third"}


def _timestamp(jd):
    year, month, day, hours = swe.revjul(jd)
    instant = datetime(year, month, day, tzinfo=timezone.utc) + timedelta(seconds=round(hours * 3600))
    return instant.isoformat().replace("+00:00", "Z")


def _changes(read, start, end, grid=0.5):
    left, before = start, read(start)
    while left < end:
        right = min(end, left + grid)
        after = read(right)
        if after != before:
            lo, hi = left, right
            while hi - lo > 1 / 86400:
                mid = (lo + hi) / 2
                if read(mid) == before:
                    lo = mid
                else:
                    hi = mid
            yield hi, before, after
        left, before = right, after


def scan(birth, start, end, planet):
    """Scan a bounded date range. The dates mark UTC midnights."""
    if planet not in BODIES or not 0 < (end - start).days <= 366 * 15:
        raise ValueError("Choose a supported planet and a date range of up to 15 years.")
    a = swe.julday(start.year, start.month, start.day, 0)
    b = swe.julday(end.year, end.month, end.day, 0)
    samples = {}
    flags_seen = set()
    with calc_lock:
        apply(birth.settings)
        body = BODIES[planet]
        if planet in ("Rahu", "Ketu") and birth.settings.node == "true":
            body = swe.TRUE_NODE
        topo = birth.settings.center == "topocentric"
        if topo:
            swe.set_topo(birth.lon, birth.lat, 0)
        try:
            def at(jd):
                if jd not in samples:
                    values, flags = swe.calc_ut(jd, body, drik.PLANET_FLAGS | swe.FLG_SPEED)
                    flags_seen.add(flags)
                    log.debug("Transit %s jd_ut=%.8f Swiss flags=%s", planet, jd, flags)
                    samples[jd] = (values[0] + _KETU_OFFSET.get(planet, 0.0)) % 360, values[3]
                return samples[jd]

            def sign(jd):
                return int(at(jd)[0] // 30)

            def nakshatra(jd):
                return nakshatra_pada(at(jd)[0]) // 4

            def retrograde(jd):
                return at(jd)[1] < 0

            def kakshya(jd):
                return int(at(jd)[0] * 8 // 30)

            stations = list(_changes(retrograde, a, b))
            # Split at stations so even a short retrograde re-entry near an
            # extremum can be found on both sides of the station.
            limits = [a, *(jd for jd, _, _ in stations), b]
            events = []
            for kind, read, names in (("sign_ingress", sign, SIGN_NAMES),
                                      ("nakshatra_ingress", nakshatra, NAKSHATRAS)):
                for left, right in zip(limits, limits[1:]):
                    events.extend({"kind": kind, "at": _timestamp(jd), "sign_index": after if kind == "sign_ingress" else None,
                                   "from": names[before], "to": names[after]}
                                  for jd, before, after in _changes(read, left, right))
            crossings = [row for left, right in zip(limits, limits[1:]) for row in _changes(kakshya, left, right)]
            divisions = [_timestamp(a), *(_timestamp(jd) for jd, _, _ in crossings), _timestamp(b)]
            kakshya_changes = [kakshya(a), *(value for _, _, value in crossings)]
            events.extend({"kind": "station", "at": _timestamp(jd), "to": "retrograde" if after else "direct"}
                          for jd, _, after in stations)
            initial_sign = sign(a)
        finally:
            if topo:
                swe.set_topo(0, 0, 0)
    return {"planet": planet, "start": _timestamp(a), "end": _timestamp(b), "initial_sign": initial_sign,
            "events": sorted(events, key=lambda event: (event["at"], event["kind"])),
            "time_zone": "UTC", "rule_version": RULE_VERSION, "settings": birth.settings.to_dict(),
            "reduced_precision": any(flag & swe.FLG_MOSEPH for flag in flags_seen),
            "kakshya_slices": [{"start": left, "end": right, "sign_index": value // 8, "index": value % 8}
                               for left, right, value in zip(divisions, divisions[1:], kakshya_changes)
                               if left < right]}


def kakshya_bindus(transit, facts):
    prastara = facts.get("prastara_ashtakavarga")
    if not prastara:
        return []
    pid = next(pid for pid, name in PLANET_NAMES.items() if transit["planet"] == name)
    return [{**row, "sign": SIGN_NAMES[row["sign_index"]], "lord": kakshya_lord(row["index"]),
             "bindu_active": _kakshya_charged(prastara, pid, row["sign_index"], row["index"] * 3.75 + 1)}
            for row in transit["kakshya_slices"]]


def sade_sati(transits, moon_sign):
    """Preserve each phase and its retrograde repetitions in the scanned interval."""
    rows = []
    entered, sign, clipped = transits["start"], transits["initial_sign"], True
    ingresses = [e for e in transits["events"] if e["kind"] == "sign_ingress"]
    end = {"at": transits["end"], "sign_index": None}
    for event in [*ingresses, end]:
        if (phase := _PHASES.get((sign - moon_sign) % 12)) and event["at"] > entered:
            rows.append({"phase": phase, "sign": SIGN_NAMES[sign], "start": entered, "end": event["at"],
                         "start_clipped": clipped, "end_clipped": event is end})
        entered, sign, clipped = event["at"], event["sign_index"], False
    return rows


def sign_intervals(birth, planet, start, end):
    """Sign-occupancy intervals of `planet` over [start, end] (inclusive UTC dates).

    Returns [(sign_index, first_day, last_day)] with datetime.date bounds, in time order.
    Retrograde re-entries appear as separate intervals (they are ordinary ingress events).
    Ranges longer than the scan limit are chunked; Rahu/Ketu/Venus/Mercury are supported."""
    from datetime import date as _date
    step = timedelta(days=366 * 14)
    out, cursor = [], start
    while cursor <= end:
        chunk_end = min(end, cursor + step)
        scanned = scan(birth, cursor, chunk_end + timedelta(days=1), planet)
        sign, first = scanned["initial_sign"], cursor
        for event in scanned["events"]:
            if event["kind"] != "sign_ingress":
                continue
            day = _date.fromisoformat(event["at"][:10])
            if day > chunk_end:
                break
            if day >= first:
                out.append((sign, first, day))
                first = day
            sign = event["sign_index"]
        out.append((sign, first, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    merged = []
    for row in out:
        if merged and merged[-1][0] == row[0] and row[1] <= merged[-1][2] + timedelta(days=1):
            merged[-1] = (row[0], merged[-1][1], max(merged[-1][2], row[2]))
        else:
            merged.append(row)
    return merged
