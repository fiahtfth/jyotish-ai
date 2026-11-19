"""Exact Moon-arc balance and proportional Vimshottari periods in UT."""
from collections.abc import Iterable, Iterator
from typing import Any

from .constants import NAK_LORD_SEQUENCE

YEARS = {8: 7, 5: 20, 0: 6, 1: 10, 2: 7, 7: 18, 4: 16, 6: 19, 3: 17}
Period = tuple[tuple[int, ...], float, float]


def _sequence(first: int) -> list[int]:
    order: list[int] = NAK_LORD_SEQUENCE
    i = order.index(first)
    return order[i:] + order[:i]


def birth_balance(moon_longitude: float) -> tuple[int, float, float]:
    """Return the first lord, fractional elapsed arc, and remaining dasha years."""
    nakshatra, fraction = divmod((moon_longitude % 360) * 27 / 360, 1.0)
    lord = NAK_LORD_SEQUENCE[int(nakshatra) % 9]
    return lord, fraction, YEARS[lord] * (1 - fraction)


def _children(lords: tuple[int, ...], start: float, end: float) -> Iterator[Period]:
    elapsed = 0
    first = start
    length = end - start
    for lord in _sequence(lords[-1]):
        elapsed += YEARS[lord]
        boundary = end if elapsed == 120 else start + length * elapsed / 120
        yield (*lords, lord), first, boundary
        first = boundary


def maha_periods(moon_longitude: float, birth_ut: float, year_days: float) -> Iterator[Period]:
    first, fraction, _ = birth_balance(moon_longitude)
    start = birth_ut - fraction * YEARS[first] * year_days
    cursor = start
    years = 0
    for lord in _sequence(first):
        years += YEARS[lord]
        end = start + years * year_days
        yield (lord,), cursor, end
        cursor = end


def antar_periods(moon_longitude: float, birth_ut: float, year_days: float) -> Iterator[Period]:
    for lords, start, end in maha_periods(moon_longitude, birth_ut, year_days):
        yield from _children(lords, start, end)


def active_periods(moon_longitude: float, birth_ut: float, year_days: float, when_ut: float) -> list[Period]:
    for row in maha_periods(moon_longitude, birth_ut, year_days):
        if row[1] <= when_ut < row[2]:
            periods = [row]
            for _ in range(2):
                periods.append(next(child for child in _children(*periods[-1])
                                    if child[1] <= when_ut < child[2]))
            return periods
    return []


def pd_periods(antar_rows: Iterable[dict[str, Any]], start_jd: float, end_jd: float) -> list[dict[str, Any]]:
    """Pratyantar (level-3) periods overlapping [start_jd, end_jd] (local-JD, same frame as the rows).

    `antar_rows` are facts["vimshottari"]["periods"] entries ({"lords": [names], "start_jd", "end_jd"}).
    Children are the proportional subdivision used by the engine itself (`_children`), so PDs tile
    each AD exactly. Returns [{"lords": [MD, AD, PD names], "start_jd", "end_jd"}] in time order.
    """
    from .constants import PLANET_NAMES
    pid = {name: i for i, name in PLANET_NAMES.items()}
    out = []
    for row in antar_rows:
        if row["end_jd"] <= start_jd or row["start_jd"] >= end_jd:
            continue
        lords = tuple(pid[n] for n in row["lords"][:2])
        for pl, s, e in _children(lords, row["start_jd"], row["end_jd"]):
            if e > start_jd and s < end_jd:
                out.append({"lords": [PLANET_NAMES[x] for x in pl], "start_jd": s, "end_jd": e})
    return out
