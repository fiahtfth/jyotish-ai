"""#61 CURRENT_DASHA: running MD/AD/PD with per-lord roles, Yogini cross-check and Chara signs.

Delegates to dasha_craft.analyze (MD-AD relation, sandhi, PD); adds strength from
facts['strength'], D9/D10 placement, houses each lord links to (links.py L1-L6), the Yogini
lords (same Moon-nakshatra factor -- cross-check only) and the running Chara MD/AD signs."""
from __future__ import annotations

from datetime import date

from ... import constants as K
from ... import dasha_craft
from .. import _ivl, links, rulepack, timing_p1, timing_p2
from .._facts import unknown_time

R = "HOOK_CURRENT_DASHA"


def lord_profile(facts: dict, lord: str) -> dict:
    p = facts["planets"][lord]
    vargas = facts.get("vargas") or {}
    place = {}
    for v in ("D9", "D10"):
        ch = vargas.get(v) or {}
        if lord in ch and "Lagna" in ch:
            place[v] = {"sign": K.SIGN_NAMES[ch[lord]["sign"]],
                        "house": (ch[lord]["sign"] - ch["Lagna"]["sign"]) % 12 + 1,
                        "reliability": (facts.get("varga_reliability") or {}).get(v)}
    st = (facts.get("strength") or {}).get(lord) or {}
    linked = sorted({h for h in range(1, 13) if links.link_evidence(lord, h, facts, "lagna")})
    return {"lord": lord, "rules_houses": [h for h in range(1, 13) if links.lord_of(facts, h) == lord],
            "occupies_house": p.get("house"), "sign": K.SIGN_NAMES[p["sign"]], "dignity": p.get("dignity", []),
            "nakshatra_lord": (p.get("nakshatra") or {}).get("lord"),
            "strength": {k: st.get(k) for k in ("shadbala_ratio", "vimshopaka", "summary", "baaladi")} if st else None,
            "vargas": place, "links_to_houses": linked}


def current(facts: dict, birth, today=None) -> dict:
    today = _ivl.to_date(today) if today else date.today()
    base = dasha_craft.analyze(facts, birth, today, pravesh=False)
    if not base.get("available"):
        return {"available": False, "reason": "no running Vimshottari period"}
    out = {"available": True, "date": today.isoformat(), "rule_id": R, "rule_version": rulepack.version(R),
           "vimshottari": base, "lords": {}}
    names = {k: (base.get(k.lower()) or {}).get("lord") for k in ("MD", "AD", "PD")}
    for k, lord in names.items():
        if lord:
            out["lords"][k] = lord_profile(facts, lord)
    counts = {}
    for prof in out["lords"].values():
        for h in prof["links_to_houses"]:
            counts[h] = counts.get(h, 0) + 1
    out["most_activated_houses"] = sorted(counts, key=lambda h: (-counts[h], h))[:4]
    ylords = timing_p1._yogini_lords(birth, today)
    out["yogini"] = {"lords": ylords, "note": "Yogini shares the Moon-nakshatra factor with Vimshottari: "
                                              "cross-check only, never a separate method"}
    if unknown_time(facts, birth):
        out["chara"] = {"available": False, "reason": "Chara Dasha needs the birth time (Lagna)"}
    else:
        try:
            jd = timing_p1.date_to_jd(today)
            for md_row in timing_p2._chara_rows(facts, birth):
                if md_row["start_jd"] <= jd < md_row["end_jd"]:
                    ad = next((a for a in md_row["antardashas"] if a["start_jd"] <= jd < a["end_jd"]), None)
                    out["chara"] = {"available": True, "school": birth.settings.chara_school,
                                    "md_sign": K.SIGN_NAMES[md_row["sign"]],
                                    "md_house": links.house_of_sign(md_row["sign"], facts),
                                    "ad_sign": K.SIGN_NAMES[ad["sign"]] if ad else None,
                                    "ad_house": links.house_of_sign(ad["sign"], facts) if ad else None,
                                    "end": timing_p1.jd_to_date(md_row["end_jd"]).isoformat()}
                    break
        except Exception as exc:
            out["chara"] = {"available": False, "reason": f"chara dasha unavailable: {exc}"}
    return out
