"""Gochara (transit) reading against the natal Lagna and Moon.

`gochara(facts, birth, today, months=12)` extends precision.gochara_now with:
house from Lagna / Moon, BAV bindus of the transited sign for that planet and
SAV, the current kakshya and whether its lord gave a bindu, Gochara vedha from
the Moon, Tarabala / Chandrabala for today, Murti Nirnaya at slow-planet
ingresses, Dhaiya / Kantaka / Ashtama Shani and the Sade Sati phase.

Rules (all from the natal Moon unless stated)
- GO.GOOD_HOUSES / GO.VEDHA (Phaladeepika ch.26, Gochara): favourable houses and
  their vedha (obstruction) houses per planet; the Sun-Saturn and Moon-Mercury
  pairs do not obstruct each other. Rahu/Ketu follow Saturn's table — a common
  extension, marked verified=False.
- GO.TARABALA (Muhurta Chintamani): nava-tara from the janma nakshatra;
  Vipat (3), Pratyari (5), Naidhana (7) adverse.
- GO.CHANDRABALA (Muhurta Chintamani): transit Moon in 1/3/6/7/10/11 from the
  natal Moon is favourable.
- GO.KAKSHYA (BPHS Ashtakavarga chapters): eight 3deg45' slices, lords
  Saturn, Jupiter, Mars, Sun, Venus, Mercury, Moon, Lagna.
- GO.MURTI (traditional panchanga practice): Moon's house from the natal Moon
  at an ingress — 1/6/11 gold, 2/5/9 silver, 3/7/10 copper, 4/8/12 iron;
  verified=False (source wording not checked).
- GO.SADE_SATI / GO.DHAIYA / GO.KANTAKA / GO.ASHTAMA: Saturn 12/1/2 from Moon;
  4th or 8th (dhaiya, "small panoti"); 4th (kantaka); 8th (ashtama).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from . import constants as K

log = logging.getLogger(__name__)

SLOW = ("Saturn", "Jupiter", "Rahu", "Ketu")
FAST = ("Mars", "Sun", "Venus", "Mercury")
PID = {n: i for i, n in K.PLANET_NAMES.items()}

# Phaladeepika ch.26: {favourable house from Moon: vedha house}
VEDHA = {
    "Sun": {3: 9, 6: 12, 10: 4, 11: 5},
    "Moon": {1: 5, 3: 9, 6: 12, 7: 2, 10: 4, 11: 8},
    "Mars": {3: 12, 6: 9, 11: 5},
    "Mercury": {2: 5, 4: 3, 6: 9, 8: 1, 10: 8, 11: 12},
    "Jupiter": {2: 12, 5: 4, 7: 3, 9: 10, 11: 8},
    "Venus": {1: 8, 2: 7, 3: 1, 4: 10, 5: 9, 8: 5, 9: 11, 11: 3, 12: 6},
    "Saturn": {3: 12, 6: 9, 11: 5},
    "Rahu": {3: 12, 6: 9, 11: 5},
    "Ketu": {3: 12, 6: 9, 11: 5},
}
VEDHA_VERIFIED = {n: n not in ("Rahu", "Ketu") for n in VEDHA}
VEDHA_EXEMPT = {frozenset(("Sun", "Saturn")), frozenset(("Moon", "Mercury"))}
SRC_VEDHA = "Phaladeepika ch.26 (Gochara vedha)"
CHANDRABALA_GOOD = {1, 3, 6, 7, 10, 11}
MURTI = {1: "gold", 6: "gold", 11: "gold", 2: "silver", 5: "silver", 9: "silver",
         3: "copper", 7: "copper", 10: "copper", 4: "iron", 8: "iron", 12: "iron"}


def murti(moon_house_from_natal_moon: int) -> str:
    return MURTI[int(moon_house_from_natal_moon)]


def vedha_for(planet: str, house_from_moon: int, others: dict) -> dict:
    """Vedha check for one transiting planet. `others` = {planet: house from Moon}."""
    table = VEDHA.get(planet, {})
    good = house_from_moon in table
    out = {"favourable_house": good, "vedha_house": table.get(house_from_moon),
           "obstructed_by": [], "verified": VEDHA_VERIFIED.get(planet, False), "source": SRC_VEDHA}
    if good:
        vh = table[house_from_moon]
        out["obstructed_by"] = sorted(o for o, h in others.items()
                                      if o != planet and h == vh
                                      and frozenset((o, planet)) not in VEDHA_EXEMPT)
    out["result"] = ("not favourable house" if not good else
                     "obstructed (vedha)" if out["obstructed_by"] else "favourable, no vedha")
    return out


def saturn_states(sat_house_from_moon: int) -> dict:
    h = int(sat_house_from_moon)
    phase = {12: "rising (first)", 1: "peak (second)", 2: "setting (third)"}.get(h)
    return {"house_from_moon": h, "sade_sati": phase is not None, "sade_sati_phase": phase,
            "dhaiya": h in (4, 8), "kantaka": h == 4, "ashtama": h == 8,
            "rules": ["GO.SADE_SATI", "GO.DHAIYA", "GO.KANTAKA", "GO.ASHTAMA"]}


def chandrabala(transit_moon_sign: int, natal_moon_sign: int) -> dict:
    h = K.house_from(transit_moon_sign, natal_moon_sign)
    return {"house_from_natal_moon": h, "favourable": h in CHANDRABALA_GOOD,
            "rule": "GO.CHANDRABALA", "source": "Muhurta Chintamani (Chandrabala)"}


def tarabala(transit_moon_long: float, janma_nak_index: int) -> dict:
    from .precision import ADVERSE_TARAS, nak_index, tara_of
    n, name = tara_of(nak_index(transit_moon_long), int(janma_nak_index))
    return {"tara": n, "name": name, "favourable": n not in ADVERSE_TARAS,
            "rule": "GO.TARABALA", "source": "Muhurta Chintamani (Tarabala)"}


def planet_row(facts, name: str, sign: int, degree: float, prastara=None) -> dict:
    from .precision import KAKSHYA_LORDS, kakshya_lord, kakshya_of
    lag, moon = int(facts["lagna"]["sign"]), int(facts["planets"]["Moon"]["sign"])
    sav = facts.get("sarvastakavarga")
    bav = facts.get("binnashtakavarga")
    pid = PID[name]
    row = {"sign": K.SIGN_NAMES[sign], "sign_index": sign, "degree": round(float(degree), 2),
           "house_from_lagna": K.house_from(sign, lag), "house_from_moon": K.house_from(sign, moon),
           "sav": int(sav[sign]) if sav and len(sav) == 12 else None}
    if pid <= 6 and bav and len(bav) > pid:
        row["bav"] = int(bav[pid][sign])
        k = kakshya_of(float(degree))
        row["kakshya"] = {"index": k + 1, "lord": kakshya_lord(k), "rule": "GO.KAKSHYA"}
        if prastara:
            try:
                row["kakshya"]["bindu"] = bool(prastara[pid][KAKSHYA_LORDS[k]][sign])
            except (IndexError, TypeError):
                pass
    return row


def _moon_long_at(jd_utc, birth):
    import swisseph as swe
    from jhora.panchanga import drik
    from .engine import apply, calc_lock
    with calc_lock:
        apply(birth.settings)
        return swe.calc_ut(jd_utc, swe.MOON, drik.PLANET_FLAGS)[0][0] % 360


def _ingresses(facts, birth, planet, start: date, end: date) -> list[dict]:
    import swisseph as swe
    from . import transits
    try:
        sc = transits.scan(birth, start, end, planet)
    except Exception:
        log.exception("transit scan failed for %s", planet)
        return []
    moon = int(facts["planets"]["Moon"]["sign"])
    lag = int(facts["lagna"]["sign"])
    out = []
    for ev in sc.get("events", []):
        if ev.get("kind") != "sign_ingress":
            continue
        at = ev["at"]
        y, m, d = int(at[:4]), int(at[5:7]), int(at[8:10])
        hh, mm, ss = int(at[11:13]), int(at[14:16]), int(at[17:19])
        jd = swe.julday(y, m, d, hh + mm / 60 + ss / 3600)
        try:
            mh = K.house_from(int(_moon_long_at(jd, birth) // 30), moon)
            mt = {"moon_house": mh, "murti": murti(mh), "rule": "GO.MURTI", "verified": False,
                  "source": "traditional panchanga practice (Murti Nirnaya)"}
        except Exception:
            mt = None
        s = int(ev["sign_index"])
        out.append({"planet": planet, "date": at[:10], "sign": K.SIGN_NAMES[s],
                    "house_from_lagna": K.house_from(s, lag), "house_from_moon": K.house_from(s, moon),
                    "murti_nirnaya": mt})
    return out


def gochara(facts: dict, birth, today: date | None = None, months: int = 12,
            ingresses: bool = True) -> dict:
    from . import precision
    from .engine import engine
    today = today or date.today()
    place = precision._place(birth)
    pos = engine.transit_positions((today.year, today.month, today.day), place, birth.settings)
    try:
        prastara = precision._prastara(facts, birth)
    except Exception:
        prastara = None
    natal_moon = facts["planets"]["Moon"]
    moon_sign = int(natal_moon["sign"])
    planets = {}
    for name in (*SLOW, *FAST):
        if name in pos:
            planets[name] = planet_row(facts, name, pos[name]["sign"], pos[name]["degree"], prastara)
    from_moon = {n: r["house_from_moon"] for n, r in planets.items()}
    if "Moon" in pos:
        from_moon["Moon"] = K.house_from(pos["Moon"]["sign"], moon_sign)
    for n, r in planets.items():
        r["vedha"] = vedha_for(n, r["house_from_moon"], from_moon)
    out = {"date": today.isoformat(), "planets": planets}
    if "Saturn" in planets:
        out["saturn"] = saturn_states(planets["Saturn"]["house_from_moon"])
    if "Moon" in pos:
        tm_long = pos["Moon"]["sign"] * 30 + pos["Moon"]["degree"]
        out["tarabala"] = tarabala(tm_long, natal_moon["nakshatra"]["index"])
        out["chandrabala"] = chandrabala(pos["Moon"]["sign"], moon_sign)
    end = today + timedelta(days=int(months * 30.44))
    if ingresses:
        ing = []
        for name in ("Saturn", "Jupiter", "Rahu"):
            ing.extend(_ingresses(facts, birth, name, today, end))
        for r in [r for r in ing if r["planet"] == "Rahu"]:
            ks = (K.SIGN_NAMES.index(r["sign"]) + 6) % 12
            ing.append({**r, "planet": "Ketu", "sign": K.SIGN_NAMES[ks],
                        "house_from_lagna": K.house_from(ks, facts["lagna"]["sign"]),
                        "house_from_moon": K.house_from(ks, moon_sign)})
        out[f"ingresses_{months}m"] = sorted(ing, key=lambda r: (r["date"], r["planet"]))
    monthly = []
    d = date(today.year, today.month, 1)
    for _ in range(months):
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        try:
            mp = engine.transit_positions((d.year, d.month, d.day), place, birth.settings)
        except Exception:
            break
        monthly.append({"month": d.isoformat()[:7],
                        **{n: {"sign": K.SIGN_NAMES[mp[n]["sign"]],
                               "house_from_lagna": K.house_from(mp[n]["sign"], facts["lagna"]["sign"]),
                               "house_from_moon": K.house_from(mp[n]["sign"], moon_sign)}
                           for n in FAST if n in mp}})
    out["monthly_fast"] = monthly
    out["sources"] = {"vedha": SRC_VEDHA, "tarabala": "Muhurta Chintamani",
                      "chandrabala": "Muhurta Chintamani",
                      "murti": "traditional panchanga practice (verified=False)"}
    return out
