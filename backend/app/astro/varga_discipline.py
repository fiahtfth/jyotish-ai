"""Varga discipline: which divisional charts the birth time can support.

`reliability(birth)` classifies each key varga's Lagna with
stability.lagna_windows against the profile's birth-time uncertainty:

- VARGA.RELIABLE: no Lagna change inside +/- uncertainty.
- VARGA.CUSP_SENSITIVE: exactly one change inside the window (two candidate Lagnas).
- VARGA.UNUSABLE: two or more changes inside the window, or D60 when the
  stated accuracy is worse than one minute (its Lagna moves every ~2 minutes).

`analysis(facts)` is pure: per varga the Lagna, its lord's placement, the D1
lord of the relevant house placed in a kendra/trikona/dusthana of that varga,
and the vargottama planets.
"""
from __future__ import annotations

import logging

from . import constants as K

log = logging.getLogger(__name__)

KEY_VARGAS = ("D1", "D2", "D3", "D4", "D7", "D9", "D10", "D12", "D16", "D20", "D24", "D30", "D60")
RELEVANT_HOUSE = {"D2": 2, "D3": 3, "D4": 4, "D7": 5, "D9": 7, "D10": 10, "D12": 9,
                  "D16": 4, "D20": 9, "D24": 4, "D30": 6, "D60": 1}
D60_MAX_UNCERTAINTY_S = 60.0
SOURCE = "BPHS ch.6-7 (shodasha vargas); time-sensitivity is an app rule"


def classify(window: dict, uncertainty_s: float, varga: str) -> str:
    """reliable | cusp_sensitive | unusable from one lagna_windows record."""
    if varga == "D60" and uncertainty_s > D60_MAX_UNCERTAINTY_S:
        return "unusable"
    inside = [t for t in window.get("changes_s", []) if abs(t) <= uncertainty_s]
    if not inside:
        return "reliable"
    return "cusp_sensitive" if len(inside) == 1 else "unusable"


def reliability(birth, vargas=KEY_VARGAS) -> dict:
    """{varga: reliable|cusp_sensitive|unusable}; {} when the scan fails."""
    from . import stability    # lazy: stability imports engine
    try:
        unc = stability.uncertainty_for(birth)
        wins = stability.lagna_windows(birth, vargas=vargas)
    except Exception:
        log.exception("varga reliability unavailable")
        return {}
    return {v: classify(w, unc, v) for v, w in wins.items()}


def _house(sign, ref):
    return K.house_from(sign, ref)


def _band(h: int) -> list[str]:
    out = []
    if h in K.KENDRA_HOUSES:
        out.append("kendra")
    if h in K.TRIKONA_HOUSES:
        out.append("trikona")
    if h in K.DUSTHANA_HOUSES:
        out.append("dusthana")
    return out


def _dig(pid, sign):
    tags = []
    if K.EXALTATION.get(pid, (None,))[0] == sign:
        tags.append("exalted")
    if K.DEBILITATION.get(pid, (None,))[0] == sign:
        tags.append("debilitated")
    if sign in K.OWN_SIGNS.get(pid, []):
        tags.append("own sign")
    return tags


def analysis(facts: dict, reliability_map: dict | None = None) -> dict:
    vargas = facts.get("vargas") or {}
    d1 = vargas.get("D1") or {}
    lag1 = facts["lagna"]["sign"]
    pid = {n: i for i, n in K.PLANET_NAMES.items()}
    out = {}
    for v in KEY_VARGAS:
        chart = vargas.get(v)
        if v == "D1" or not chart or "Lagna" not in chart:
            continue
        lag = int(chart["Lagna"]["sign"])
        lord = K.PLANET_NAMES[K.SIGN_LORD[lag]]
        rec = {"lagna": K.SIGN_NAMES[lag], "lagna_lord": lord,
               "reliability": (reliability_map or {}).get(v)}
        if lord in chart:
            ls = int(chart[lord]["sign"])
            h = _house(ls, lag)
            rec["lagna_lord_placement"] = {"sign": K.SIGN_NAMES[ls], "house": h, "band": _band(h),
                                           "dignity": _dig(pid[lord], ls)}
        rh = RELEVANT_HOUSE.get(v)
        if rh:
            hl = K.PLANET_NAMES[K.SIGN_LORD[(lag1 + rh - 1) % 12]]
            if hl in chart:
                s = int(chart[hl]["sign"])
                h = _house(s, lag)
                rec["d1_house_lord"] = {"house": rh, "lord": hl, "sign": K.SIGN_NAMES[s],
                                        "house_in_varga": h, "band": _band(h),
                                        "dignity": _dig(pid[hl], s)}
        rec["vargottama"] = sorted(n for n in K.PLANET_NAMES.values()
                                   if n in chart and n in d1 and chart[n]["sign"] == d1[n]["sign"])
        rec["lagna_vargottama"] = lag == lag1
        rec["source"] = SOURCE
        out[v] = rec
    return out
