"""Small date-interval helpers shared by P3, P4 and template T.

Intervals are (start, end) tuples of datetime.date, both inclusive. Pillars written
by different modules may carry ISO strings/datetimes/Julian days; `norm` converts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import swisseph as swe


def to_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        return date.fromisoformat(x[:10])
    if isinstance(x, (int, float)):
        y, m, d, _ = swe.revjul(float(x))
        return date(y, m, d)
    if isinstance(x, (tuple, list)) and len(x) >= 3:
        return date(int(x[0]), int(x[1]), int(x[2]))
    raise TypeError(f"cannot read a date from {x!r}")


def norm(iv) -> Optional[tuple]:
    if iv is None:
        return None
    a, b = to_date(iv[0]), to_date(iv[1])
    return (a, b) if a <= b else (b, a)


def overlap(a: Optional[tuple], b: Optional[tuple]) -> Optional[tuple]:
    if a is None or b is None:
        return None
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


def hull(ivs) -> Optional[tuple]:
    ivs = [i for i in ivs if i]
    if not ivs:
        return None
    return (min(i[0] for i in ivs), max(i[1] for i in ivs))


def fmt(iv) -> str:
    return "n/a" if not iv else f"{iv[0].isoformat()} to {iv[1].isoformat()}"


def day_before(d: date) -> date:
    return d - timedelta(days=1)
