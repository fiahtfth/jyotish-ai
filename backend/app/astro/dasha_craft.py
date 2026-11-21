"""Vimshottari dasha craft: how the running MD / AD / PD lords combine.

`analyze(facts, birth=None, today=None)` reads the locked facts' MD-AD table
(and, with `birth`, the running pratyantar and Dasha Pravesh charts).

Rules
- DC.LORD_ROLE: houses owned and occupied from Lagna and from the Moon.
- DC.AD_FROM_MD.<n>: house of the AD lord counted from the MD lord's sign.
  6/8/12 = friction (BPHS antardasha chapters: AD lord in 6/8/12 from the
  dasha lord gives mixed/adverse results); 1/4/7/10 and 5/9 = harmonious;
  11 = supportive (BPHS). 2nd (the 2/12 axis read as friction) and 3rd are
  modern-practice readings, marked verified=False.
- DC.SANDHI.MD / DC.SANDHI.AD: within ~6 months of an MD change or ~1 month of
  an AD change (dasha sandhi; the span is an app convention).
- DC.MD_LORD_DUSTHANA: MD lord placed in 6/8/12 from Lagna.
- DC.PRAVESH: chart cast for the start moment of the current MD and AD.
"""
from __future__ import annotations

import logging
from datetime import date

from . import constants as K

log = logging.getLogger(__name__)

MD_SANDHI_DAYS = 183
AD_SANDHI_DAYS = 30
SRC_BPHS_AD = "BPHS antardasha chapters (position of AD lord from the dasha lord)"
SRC_MODERN = "modern practice (2/12 and 3/11 relationships)"


def relation(ad_house_from_md: int) -> dict:
    h = int(ad_house_from_md)
    if h in (6, 8, 12):
        kind, verified, src = "friction", True, SRC_BPHS_AD
    elif h in (1, 4, 7, 10, 5, 9):
        kind, verified, src = "harmonious", True, SRC_BPHS_AD
    elif h == 11:
        kind, verified, src = "supportive", True, SRC_BPHS_AD
    elif h == 2:
        kind, verified, src = "friction", False, SRC_MODERN
    else:
        kind, verified, src = "neutral", False, SRC_MODERN
    axis = {6: "6/8", 8: "6/8", 2: "2/12", 12: "2/12"}.get(h)
    return {"id": f"DC.AD_FROM_MD.{h}", "house": h, "kind": kind, "axis": axis,
            "verified": verified, "source": src}


def _house_keys(facts, h):
    hs = facts["houses"]
    return hs[h] if h in hs else hs[str(h)]


def lord_role(facts: dict, lord: str) -> dict:
    p = facts["planets"]
    rec = p[lord]
    moon = int(p["Moon"]["sign"])
    owned = [h for h in range(1, 13) if _house_keys(facts, h)["lord"] == lord]
    owned_moon = [h for h in range(1, 13) if K.PLANET_NAMES[K.SIGN_LORD[(moon + h - 1) % 12]] == lord]
    out = {"lord": lord, "sign": rec["sign_name"], "house_from_lagna": rec["house"],
           "house_from_moon": K.house_from(rec["sign"], moon),
           "owns_from_lagna": owned, "owns_from_moon": owned_moon,
           "dignity": list(rec.get("dignity") or []), "rule": "DC.LORD_ROLE"}
    if lord in ("Rahu", "Ketu"):
        disp = K.PLANET_NAMES[K.SIGN_LORD[int(rec["sign"])]]
        out["dispositor"] = {"planet": disp, "house_from_lagna": p[disp]["house"]}
    st = (facts.get("strength") or {}).get(lord)
    if st:
        out["strength"] = {k: st.get(k) for k in ("summary", "shadbala_ratio", "baaladi", "jagradadi")}
    if rec["house"] in K.DUSTHANA_HOUSES:
        out["dusthana"] = True
    return out


def _periods(facts):
    return (facts.get("vimshottari") or {}).get("periods") or []


def current_rows(facts, today: date):
    iso = today.isoformat()
    rows = _periods(facts)
    cur = next((r for r in rows if r["start"] <= iso < r["end"]), None)
    if cur is None:
        return None, None, []
    i = rows.index(cur)
    # the MD rows that contain cur (an MD lord recurs after 120 years)
    j = i
    while j > 0 and rows[j - 1]["maha"] == cur["maha"]:
        j -= 1
    k = i
    while k + 1 < len(rows) and rows[k + 1]["maha"] == cur["maha"]:
        k += 1
    md = {"lord": cur["maha"], "start": rows[j]["start"], "end": rows[k]["end"],
          "start_jd": rows[j].get("start_jd"), "end_jd": rows[k].get("end_jd")}
    return md, cur, rows[i + 1:i + 4]


def sandhi(md: dict, ad: dict, today: date) -> dict:
    def near(day_iso, days):
        d = date.fromisoformat(day_iso)
        return abs((d - today).days) <= days
    md_flag = near(md["start"], MD_SANDHI_DAYS) or near(md["end"], MD_SANDHI_DAYS)
    ad_flag = near(ad["start"], AD_SANDHI_DAYS) or near(ad["end"], AD_SANDHI_DAYS)
    return {"md_sandhi": md_flag, "ad_sandhi": ad_flag, "flag": md_flag or ad_flag,
            "rule": "DC.SANDHI", "spans_days": {"md": MD_SANDHI_DAYS, "ad": AD_SANDHI_DAYS},
            "source": "Dasha sandhi (junction) — span is an app convention"}


def pravesh_chart(facts: dict, birth, start_jd_local: float, lord: str) -> dict | None:
    """Lagna and key houses for the chart cast at a dasha's start moment."""
    if birth is None or start_jd_local is None:
        return None
    try:
        from jhora.panchanga import drik
        from .engine import _rasi_positions, apply, calc_lock
        place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
        with calc_lock:
            apply(birth.settings)
            rasi, _, _ = _rasi_positions(start_jd_local - birth.tz_offset / 24.0, place, birth.settings)
    except Exception:
        log.exception("dasha pravesh chart unavailable")
        return None
    lag = int(rasi[0][1][0])
    planets = {K.PLANET_NAMES[pid]: int(s) for pid, (s, _d) in rasi[1:]}
    houses = {n: K.house_from(s, lag) for n, s in planets.items()}
    return {"lagna": K.SIGN_NAMES[lag],
            "lagna_house_from_natal_lagna": K.house_from(lag, facts["lagna"]["sign"]),
            "lord": lord, "lord_house": houses.get(lord),
            "kendra_occupants": sorted(n for n, h in houses.items() if h in K.KENDRA_HOUSES),
            "dusthana_occupants": sorted(n for n, h in houses.items() if h in K.DUSTHANA_HOUSES),
            "houses": houses, "rule": "DC.PRAVESH",
            "source": "Dasha Pravesh chart (chart for the dasha's start moment)"}


def analyze(facts: dict, birth=None, today: date | None = None, pravesh: bool = True) -> dict:
    today = today or date.today()
    md, ad, nxt = current_rows(facts, today)
    if md is None:
        return {"available": False}
    p = facts["planets"]
    md_lord, ad_lord = md["lord"], ad["antar"]
    out = {"available": True, "date": today.isoformat(),
           "md": {**lord_role(facts, md_lord), "start": md["start"], "end": md["end"]},
           "ad": {**lord_role(facts, ad_lord), "start": ad["start"], "end": ad["end"]},
           "ad_from_md": relation(K.house_from(p[ad_lord]["sign"], p[md_lord]["sign"])),
           "sandhi": sandhi(md, ad, today),
           "md_lord_dusthana": p[md_lord]["house"] in K.DUSTHANA_HOUSES,
           "next_ads": [{"lord": r["antar"], "start": r["start"], "end": r["end"],
                         "maha": r["maha"],
                         "from_md": relation(K.house_from(p[r["antar"]]["sign"], p[r["maha"]]["sign"]))}
                        for r in nxt]}
    if birth is not None:
        try:
            from .engine import engine
            run = engine.running_vimshottari(birth, (today.year, today.month, today.day))
        except Exception:
            run = []
        if len(run) >= 3:
            pd_lord = run[2]["lords"][-1]
            out["pd"] = {**lord_role(facts, pd_lord), "start": run[2]["start"], "end": run[2]["end"],
                         "from_ad": relation(K.house_from(p[pd_lord]["sign"], p[ad_lord]["sign"]))}
        if pravesh:
            out["pravesh"] = {"md": pravesh_chart(facts, birth, md.get("start_jd"), md_lord),
                              "ad": pravesh_chart(facts, birth, ad.get("start_jd"), ad_lord)}
    return out
