"""Whole-sign divisional charts under the versioned Jyotish AI conventions."""
from bisect import bisect_right
from collections.abc import Callable, Iterable
from functools import partial

# Use integral microarcseconds for the calculation. This preserves finer
# input precision while keeping boundaries exact at whole arcseconds.
UNITS_PER_DEGREE = 3_600_000_000
SIGN = 30 * UNITS_PER_DEGREE
VERSION = "parashari-v3-half-open"
SCHEMES = {
    1: "Rasi", 2: "Parashari Leo/Cancer Hora", 3: "Parashari trinal Drekkana",
    4: "Parashari kendra Chaturthamsha", 6: "Aries/Libra Shashthamsha",
    7: "Parashari Saptamsha", 9: "Parashari Navamsha", 10: "Parashari Dashamsha",
    12: "Parashari Dwadashamsha", 16: "Parashari Shodashamsha",
    20: "Parashari Vimshamsha", 24: "Parashari Siddhamsha", 30: "Parashari unequal Trimshamsha · linear within each part",
    40: "Parashari Khavedamsha", 45: "Parashari Akshavedamsha",
    60: "Parashari Shashtiamsha from natal sign",
}

# Each seed is a sign or an offset in zodiacal order. Signs are zero-based.
_SEEDS: dict[int, Callable[[int], int]] = {
    1: lambda s: s,
    4: lambda s: s,
    6: lambda s: 6 * (s % 2),
    7: lambda s: s + 6 * (s % 2),
    9: lambda s: 9 * s,
    10: lambda s: s + 8 * (s % 2),
    12: lambda s: s,
    16: lambda s: (0, 4, 8)[s % 3],
    20: lambda s: (0, 8, 4)[s % 3],
    24: lambda s: 4 - s % 2,
    40: lambda s: 6 * (s % 2),
    45: lambda s: (0, 4, 8)[s % 3],
    60: lambda s: s,
}
_D30 = (
    ((0, 5, 10, 18, 25, 30), (0, 10, 8, 2, 6)),
    ((0, 5, 12, 20, 25, 30), (1, 5, 11, 9, 7)),
)


def scheme_labels(d24: str = "forward") -> dict[str, str]:
    labels = {f"D{number}": name for number, name in SCHEMES.items()}
    labels["D24"] += f" · {d24} in even signs"
    return labels


def position(number: int, sign: int, degree: float, *, d24: str = "forward") -> tuple[int, float]:
    """Return the division sign and degree for a within-sign longitude."""
    if number not in SCHEMES:
        raise ValueError(f"Unsupported varga D{number}")
    carry, arc = divmod(round(degree * UNITS_PER_DEGREE), SIGN)
    sign = (sign + carry) % 12
    if number == 30:
        bounds, signs = _D30[sign % 2]
        part = bisect_right(bounds, arc / UNITS_PER_DEGREE) - 1
        lo, hi = bounds[part:part + 2]
        fraction = (arc - lo * UNITS_PER_DEGREE) / ((hi - lo) * UNITS_PER_DEGREE)
        return signs[part], 30 * fraction
    part, progress = divmod(arc * number, SIGN)
    degree_in_varga = progress / UNITS_PER_DEGREE
    if number == 2:
        return (4 if part == sign % 2 else 3), degree_in_varga
    if number == 3:
        return (sign + 4 * part) % 12, degree_in_varga
    direction = -1 if number == 24 and sign % 2 and d24 == "reverse" else 1
    return (_SEEDS[number](sign) + direction * (part if number != 4 else 3 * part)) % 12, degree_in_varga


Position = tuple[int | str, tuple[int, float]]


def chart(positions: Iterable[Position], number: int, *, d24: str = "forward") -> list[Position]:
    return [(body, position(number, sign, degree, d24=d24)) for body, (sign, degree) in positions]


def chart_functions(d24: str = "forward") -> dict[str, Callable[[Iterable[Position]], list[Position]]]:
    return {f"D{number}": partial(chart, number=number, d24=d24) for number in SCHEMES}


def signs_over_interval(number: int, low: float, high: float, *, d24: str = "forward") -> list[int]:
    """All possible signs for an input interval, including internal boundaries."""
    start = round(low * UNITS_PER_DEGREE)
    end = round(high * UNITS_PER_DEGREE)
    found = []
    for sign in range(start // SIGN, end // SIGN + 1):
        sign_start = sign * SIGN
        if number == 30:
            boundaries = [bound * UNITS_PER_DEGREE for bound in _D30[sign % 2][0][:-1]]
        else:
            boundaries = [(part * SIGN + number - 1) // number for part in range(number)]
        points = [max(start, sign_start)]
        points.extend(sign_start + arc for arc in boundaries if start <= sign_start + arc <= end)
        for point in points:
            value = position(number, sign, (point - sign_start) / UNITS_PER_DEGREE, d24=d24)[0]
            if value not in found:
                found.append(value)
    return found


def nakshatra_pada(longitude: float) -> int:
    """Zero-based pada index over the zodiac; the boundary starts a new pada."""
    return (round(longitude * UNITS_PER_DEGREE) % (12 * SIGN)) // (12_000 * 1_000_000)
