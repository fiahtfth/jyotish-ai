"""Special points: Bhrigu Bindu, Gulika / Mandi, Yogi / Avayogi, the nodal axis.

Pure helpers take longitudes; `compute(facts, jd, place, dob, tob)` adds the
PyJHora-derived Gulika/Mandi and is called by the engine under `calc_lock`.

Rules
- SP.BHRIGU_BINDU: Rahu + ((Moon - Rahu) mod 360) / 2 — the zodiacal midpoint
  from Rahu to Moon. A modern, Nadi-derived technique (not in BPHS).
- SP.GULIKA / SP.MANDI: Saturn's portion of the day/night (start / middle),
  via PyJHora drik.gulika_longitude / maandi_longitude (BPHS ch.3 upagrahas;
  Phaladeepika ch.25).
- SP.YOGI: Sun + Moon + 93deg20'; Yogi planet = nakshatra lord of that point,
  Duplicate Yogi = its sign lord; Avayogi point = Yogi + 186deg40', Avayogi
  planet = that nakshatra's lord (Sanjay Rath / PVR Narasimha Rao tradition).
- SP.NODE_AXIS: houses of Rahu and Ketu from the Lagna.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import constants as K

log = logging.getLogger(__name__)

YOGI_OFFSET = 93.0 + 20.0 / 60.0
AVAYOGI_OFFSET = 186.0 + 40.0 / 60.0


def bhrigu_bindu(moon_long: float, rahu_long: float) -> float:
    return (rahu_long + ((moon_long - rahu_long) % 360.0) / 2.0) % 360.0


def nak_lord(abs_long: float) -> str:
    idx = int((abs_long % 360.0) // K.NAK_SPAN)
    return K.PLANET_NAMES[K.NAK_LORD_SEQUENCE[idx % 9]]


def _pt(abs_long: float, lagna_sign: int | None = None) -> dict:
    s = int((abs_long % 360) // 30)
    rec = {"abs_longitude": round(abs_long % 360, 4), "sign": K.SIGN_NAMES[s], "sign_index": s,
           "degree": round(abs_long % 30, 4),
           "nakshatra": K.NAKSHATRAS[int((abs_long % 360) // K.NAK_SPAN)]}
    if lagna_sign is not None:
        rec["house"] = K.house_from(s, lagna_sign)
    return rec


def yogi(sun_long: float, moon_long: float, lagna_sign: int | None = None) -> dict:
    y = (sun_long + moon_long + YOGI_OFFSET) % 360.0
    a = (y + AVAYOGI_OFFSET) % 360.0
    return {"yogi_point": _pt(y, lagna_sign), "yogi_planet": nak_lord(y),
            "duplicate_yogi": K.PLANET_NAMES[K.SIGN_LORD[int(y // 30)]],
            "avayogi_point": _pt(a, lagna_sign), "avayogi_planet": nak_lord(a),
            "rule": "SP.YOGI", "verified": True,
            "source": "Yogi/Avayogi (Sanjay Rath / PVR Narasimha Rao tradition)"}


def compute(facts: dict, jd=None, place=None, dob=None, tob=None) -> dict:
    p = facts["planets"]
    lag = int(facts["lagna"]["sign"])
    bb = bhrigu_bindu(p["Moon"]["abs_longitude"], p["Rahu"]["abs_longitude"])
    out = {"bhrigu_bindu": {**_pt(bb, lag), "rule": "SP.BHRIGU_BINDU", "verified": True,
                            "source": "Bhrigu Bindu (modern Nadi-derived technique; not in BPHS)"},
           "yogi": yogi(p["Sun"]["abs_longitude"], p["Moon"]["abs_longitude"], lag),
           "node_axis": {"rahu_house": p["Rahu"]["house"], "ketu_house": p["Ketu"]["house"],
                         "axis": f"{p['Rahu']['house']}/{p['Ketu']['house']}", "rule": "SP.NODE_AXIS"}}
    if dob is not None and place is not None:
        try:
            from jhora.panchanga import drik
            for key, fn in (("gulika", drik.gulika_longitude), ("mandi", drik.maandi_longitude)):
                s, d = fn(dob, tob, place)
                out[key] = {**_pt(int(s) * 30 + float(d), lag), "rule": f"SP.{key.upper()}",
                            "source": "BPHS ch.3 upagrahas via PyJHora"}
        except Exception:
            log.exception("gulika/mandi unavailable")
    return out


def bhrigu_bindu_transits(facts: dict, birth, today: date | None = None, days: int = 365,
                          orb: float = 3.0) -> dict:
    """Saturn / Jupiter against the Bhrigu Bindu: today's separation, same-sign /
    Parashari aspect, and exact crossings in the next `days`."""
    import swisseph as swe
    from jhora.panchanga import drik
    from .engine import apply, calc_lock
    today = today or date.today()
    p = facts["planets"]
    bb = bhrigu_bindu(p["Moon"]["abs_longitude"], p["Rahu"]["abs_longitude"])
    bb_sign = int(bb // 30)
    bodies = {"Saturn": swe.SATURN, "Jupiter": swe.JUPITER}
    out = {"bhrigu_bindu": _pt(bb, facts["lagna"]["sign"]), "planets": {}}
    jd0 = swe.julday(today.year, today.month, today.day, 12.0)
    with calc_lock:
        apply(birth.settings)
        for name, body in bodies.items():
            def lon(jd):
                return swe.calc_ut(jd, body, drik.PLANET_FLAGS)[0][0] % 360
            now = lon(jd0)
            diff = ((now - bb + 180) % 360) - 180
            s = int(now // 30)
            crossings, prev = [], diff
            for i in range(2, days + 1, 2):
                cur = ((lon(jd0 + i) - bb + 180) % 360) - 180
                if (prev < 0 <= cur or prev > 0 >= cur) and abs(prev - cur) < 30:
                    crossings.append((today + timedelta(days=i)).isoformat())
                prev = cur
            out["planets"][name] = {"sign": K.SIGN_NAMES[s], "separation_deg": round(abs(diff), 2),
                                    "within_orb": abs(diff) <= orb, "same_sign": s == bb_sign,
                                    "aspects_bb_sign": bb_sign in K.parashari_reaches(name, s) and s != bb_sign,
                                    "exact_crossings": crossings}
    return out
