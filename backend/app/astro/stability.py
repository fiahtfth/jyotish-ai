"""Birth-time stability windows.

For a birth time T the Lagna (and so every divisional Lagna) is a step function
of the clock time. `lagna_windows` finds, for each varga, the interval around T
over which that varga's Lagna sign stays the same, by scanning a fine grid and
bisecting every change to sub-second precision. A varga whose nearest change
lies within the birth-time uncertainty is `cusp_sensitive`. This describes
sensitivity to the stated time; it says nothing about whether the time is right.
"""
from datetime import datetime
from functools import partial

from jhora import utils
from jhora.panchanga import drik
import swisseph as swe

from . import constants as K
from .engine import BirthInput, VARGA_FUNCS, apply, calc_lock

DEFAULT_VARGAS = (1, 2, 3, 7, 9, 10, 12, 16, 20, 24, 30, 40, 45, 60)
UNCERTAINTY_S = {"exact": 120.0, "approximate": 1800.0, "unknown": 7200.0}


def uncertainty_for(birth: BirthInput) -> float:
    return UNCERTAINTY_S.get(birth.birth_time_precision, UNCERTAINTY_S["unknown"])


# ------------------------------------------------------------------ generic scanner

def scan_changes(fn, span_s: float, grid_s: float, tol_s: float) -> tuple[list, list, list]:
    """Sample fn(t) on [-span_s, span_s] every grid_s seconds; bisect each change.

    Returns (times, values, changes): `changes` = [(t_change, before, after)] with t_change
    accurate to tol_s. Values only need to support ==.
    """
    n = int(round(2 * span_s / grid_s))
    ts = [-span_s + i * grid_s for i in range(n + 1)]
    if ts[-1] < span_s:
        ts.append(span_s)
    vals = [fn(t) for t in ts]
    changes = []
    for i in range(1, len(ts)):
        if vals[i] == vals[i - 1]:
            continue
        lo, hi, vlo = ts[i - 1], ts[i], vals[i - 1]
        while hi - lo > tol_s:
            mid = (lo + hi) / 2
            if fn(mid) == vlo:
                lo = mid
            else:
                hi = mid
        changes.append(((lo + hi) / 2, vals[i - 1], vals[i]))
    return ts, vals, changes


def _window_record(value, changes, span_s, uncertainty_s, extra=None) -> dict:
    before = [c for c in changes if c[0] <= 0]
    after = [c for c in changes if c[0] > 0]
    start = before[-1][0] if before else -span_s
    end = after[0][0] if after else span_s
    rec = {**(extra or {}), "sign": value, "start_s": round(start, 2), "end_s": round(end, 2),
           "margin_before_s": round(-start, 2), "margin_after_s": round(end, 2),
           "open_ended": not before or not after,
           "changes_s": [round(c[0], 2) for c in changes]}
    rec["status"] = ("cusp_sensitive" if min(rec["margin_before_s"], rec["margin_after_s"]) < uncertainty_s
                     else "stable")
    return rec


def windows_from_functions(fns: dict, span_s=900, grid_s=10, tol_s=0.5, uncertainty_s=120) -> dict:
    """Window record per named function t -> value (test seam for synthetic cases)."""
    out = {}
    for name, fn in fns.items():
        _, vals, changes = scan_changes(fn, span_s, grid_s, tol_s)
        out[name] = _window_record(fn(0.0), changes, span_s, uncertainty_s)
    return out


# ------------------------------------------------------------------ Lagna

def _varga_funcs(birth: BirthInput):
    from functools import partial
    from jhora.horoscope.chart import charts
    funcs = dict(VARGA_FUNCS)
    if birth.settings.d24 == "reverse":
        funcs["D24"] = partial(charts.chaturvimsamsa_chart, chart_method=2)
    return funcs


def lagna_windows(birth: BirthInput, vargas=DEFAULT_VARGAS, span_s=900, grid_s=10, tol_s=0.5,
                  uncertainty_s=None) -> dict:
    """Per varga {sign,start_s,end_s,margin_before_s,margin_after_s,open_ended,status,changes_s}.

    `vargas` accepts ints (9) or names ("D9"). Times are seconds relative to the stated birth time.
    """
    unc = uncertainty_for(birth) if uncertainty_s is None else uncertainty_s
    span_s = max(span_s, unc)       # a margin can only be judged against the uncertainty if scanned that far
    names = [v if isinstance(v, str) else f"D{v}" for v in vargas]
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    jd0 = utils.julian_day_number((birth.year, birth.month, birth.day),
                                  (birth.hour, birth.minute, birth.second))
    with calc_lock:
        apply(birth.settings)
        funcs = _varga_funcs(birth)
        missing = [n for n in names if n not in funcs]
        if missing:
            raise ValueError(f"unsupported varga(s): {', '.join(missing)}")
        asc_cache: dict[float, tuple] = {}

        def asc(t):
            if t not in asc_cache:
                sign, deg = drik.ascendant(jd0 + t / 86400.0, place)[:2]
                asc_cache[t] = (sign, deg)
            return asc_cache[t]

        def sign_fn(name):
            fn = funcs[name]
            memo: dict[float, int] = {}

            def f(t):
                if t not in memo:
                    memo[t] = asc(t)[0] if name == "D1" else int(fn([["L", asc(t)]])[0][1][0])
                return memo[t]
            return f

        out = {}
        for name in names:
            f = sign_fn(name)
            _, _, changes = scan_changes(f, span_s, grid_s, tol_s)
            out[name] = _window_record(f(0.0), changes, span_s, unc)
    return out


def cusp_sensitive(windows: dict) -> list[str]:
    return [v for v, w in windows.items() if w["status"] == "cusp_sensitive"]


# ------------------------------------------------------------------ Moon pada

def moon_pada_window(birth: BirthInput, span_s=86400, grid_s=600, tol_s=0.5,
                     uncertainty_s=None) -> dict:
    """Window around the birth time over which the Moon stays in one nakshatra pada."""
    unc = uncertainty_for(birth) if uncertainty_s is None else uncertainty_s
    jd_utc0 = utils.julian_day_number((birth.year, birth.month, birth.day),
                                      (birth.hour, birth.minute, birth.second)) - birth.tz_offset / 24.0
    width = 360.0 / 108

    with calc_lock:
        apply(birth.settings)
        _observer(birth)

        def pada(t):
            lon = swe.calc_ut(jd_utc0 + t / 86400.0, swe.MOON, drik.PLANET_FLAGS)[0][0] % 360
            return int(lon // width)

        _, _, changes = scan_changes(pada, span_s, grid_s, tol_s)
        idx = pada(0.0)
    rec = _window_record(idx, changes, span_s, unc)
    rec.pop("sign")
    rec.update(pada_index=idx, nakshatra=idx // 4, pada=idx % 4 + 1)
    return rec


# ------------------------------------------------------------------ planet varga edges

_SWE_BODIES = [swe.SUN, swe.MOON, swe.MARS, swe.MERCURY, swe.JUPITER,
               swe.VENUS, swe.SATURN]


def _observer(birth: BirthInput):
    """swe.set_topo for direct calc_ut callers when the centre is topocentric."""
    if birth.settings.center == "topocentric":
        swe.set_topo(birth.lon, birth.lat, 0.0)


def planet_edge_windows(birth: BirthInput, vargas=("D9", "D60"), uncertainty_s=None,
                        tol_s=0.5) -> dict:
    """Planets whose divisional sign flips inside the birth-time uncertainty.

    A planet at 29°59′ of a D60 part changes its D60 sign when the clock
    moves it a few arcseconds; slow planets essentially never flip over a
    few minutes, the Moon can. Each planet's sidereal longitude is scanned
    over ±uncertainty on a coarse grid sized to the span and every change
    bisected to `tol_s`; the varga rule applied is the exact same chart
    function the engine uses (half-open parts, configured D24/D60 schemes).
    Reports *which* boundary a planet sits on — it says nothing about which
    side is correct.
    """
    unc = uncertainty_for(birth) if uncertainty_s is None else uncertainty_s
    if unc <= 0:
        return {"uncertainty_s": 0.0, "flips": {}, "flipping_planets": [],
                "note": "no stated uncertainty window"}
    jd_utc0 = utils.julian_day_number((birth.year, birth.month, birth.day),
                                      (birth.hour, birth.minute, birth.second)) \
        - birth.tz_offset / 24.0
    node_body = swe.TRUE_NODE if birth.settings.node == "true" else swe.MEAN_NODE
    grid = max(10.0, unc / 60.0)
    flips: dict = {}
    with calc_lock:
        apply(birth.settings)
        _observer(birth)
        funcs = _varga_funcs(birth)
        missing = [v for v in vargas if v not in funcs]
        if missing:
            raise ValueError(f"unsupported varga(s): {', '.join(missing)}")

        def lon(pid, t):
            ju = jd_utc0 + t / 86400.0
            if pid == 7:
                return swe.calc_ut(ju, node_body, drik.PLANET_FLAGS)[0][0] % 360
            if pid == 8:
                return (swe.calc_ut(ju, node_body, drik.PLANET_FLAGS)[0][0] + 180) % 360
            return swe.calc_ut(ju, _SWE_BODIES[pid], drik.PLANET_FLAGS)[0][0] % 360

        def varga_sign(fn, pid, t):
            L = lon(pid, t)
            return int(fn([[pid, (int(L // 30), L % 30)]])[0][1][0])

        for name in vargas:
            fn = funcs[name]
            for pid in range(9):
                _, _, changes = scan_changes(partial(varga_sign, fn, pid),
                                             unc, grid, tol_s)
                if changes:
                    flips.setdefault(K.PLANET_NAMES[pid], {})[name] = {
                        "sign_at_birth": varga_sign(fn, pid, 0.0),
                        "changes_s": [round(c[0], 2) for c in changes],
                        "transitions": [[K.SIGN_NAMES[c[1]], K.SIGN_NAMES[c[2]]]
                                        for c in changes]}
    return {"uncertainty_s": unc, "vargas": list(vargas), "flips": flips,
            "flipping_planets": sorted(flips),
            "note": "Planet sign flips inside the stated birth-time uncertainty; "
                    "not a claim about which side is correct."}
