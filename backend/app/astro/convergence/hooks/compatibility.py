"""#12 COMPATIBILITY (consent required): badge "Compatibility methods agreeing: n/4".

M1 Ashtakoota (astro/matching.py, documented exceptions; Nadi/Bhakoot cancellations stay
VERIFY -> reported, not used to raise the verdict); M2 Mangal dosha both charts with mutual
cancellation; M3 cross-chart links (Moon-Moon and Lagna-Lagna not 6/8, 7th lord/Venus to the
partner's Lagna/Moon, D9 Lagna relation, DK on partner's Lagna/UL); M4 dasha alignment (neither
in a strongly adverse period now). Never a 'doomed' verdict."""
from __future__ import annotations

from ... import constants as K
from ... import matching
from .. import links, rulepack
from .._facts import unknown_time

R = "HOOK_COMPATIBILITY"
SIX_EIGHT = {6, 8}


class ConsentRequired(PermissionError):
    pass


def _m(name, value, reasons, reason_ne=None):
    return {"method": name, "value": value, "reasons": reasons, "ne_reason": reason_ne}


def _cross(a: dict, b: dict) -> dict:
    reasons, good, bad = [], 0, 0
    mm = K.house_from(b["planets"]["Moon"]["sign"], a["planets"]["Moon"]["sign"])
    if mm in SIX_EIGHT or (14 - mm) % 12 in SIX_EIGHT:
        bad += 1
        reasons.append(f"Moon signs are {mm}/{(14 - mm) % 12 or 12} from each other (6/8)")
    else:
        good += 1
        reasons.append("Moon signs are not in a 6/8 relation")
    timed = not unknown_time(a) and not unknown_time(b)
    if timed:
        ll = K.house_from(b["lagna"]["sign"], a["lagna"]["sign"])
        if ll in SIX_EIGHT or (14 - ll) % 12 in SIX_EIGHT:
            bad += 1
            reasons.append("Lagnas are in a 6/8 relation")
        else:
            good += 1
            reasons.append("Lagnas are not in a 6/8 relation")
        for x, y, who in ((a, b, "first"), (b, a, "second")):
            l7 = links.lord_of(x, 7)
            for pl in dict.fromkeys((l7, "Venus")):
                s = x["planets"][pl]["sign"]
                if s in (y["lagna"]["sign"], y["planets"]["Moon"]["sign"]):
                    good += 1
                    reasons.append(f"{who} person's {pl} falls on the partner's Lagna/Moon sign")
            dk = ((x.get("jaimini") or {}).get("karakas") or {}).get("Darakaraka")
            ul = ((y.get("jaimini") or {}).get("upapada_lagna") or {}).get("sign")
            if dk and x["planets"][dk]["sign"] in (y["lagna"]["sign"], ul):
                good += 1
                reasons.append(f"{who} person's Darakaraka {dk} falls on the partner's Lagna/UL")
        d9 = matching.d9_relation(a, b)
        if d9.get("available"):
            good += bool(d9.get("harmonious"))
            bad += not d9.get("harmonious")
            reasons.append(d9.get("text", "D9 Lagna relation"))
    else:
        reasons.append("Lagna-based cross-links not evaluated (a birth time is unknown)")
    value = "S" if good >= 2 and good > bad else ("A" if bad > good else "W")
    return _m("M3_cross_links", value, reasons)


def compatibility(facts_a: dict, facts_b: dict, consent: bool) -> dict:
    if not consent:
        raise ConsentRequired("Confirm you have the other person's permission to use their birth details.")
    m = matching.match(facts_a, facts_b)
    # Verdict uses the unadjusted total: Nadi/Bhakoot cancellations are
    # disabled_verify rules — reported below, never used to raise the verdict.
    total = m["total"]
    adjusted = m.get("adjusted_total", total)
    m1 = _m("M1_ashtakoota", "S" if total >= 18 else "W",
            [f"Ashtakoota {total}/36"
             + (f" (unverified exceptions would give {adjusted}/36)" if adjusted != total else ""),
             m["band"]["text"]])
    mg = m.get("mangal") or {}
    pair = mg.get("pair") or mg.get("mutual") or {}
    ga, gb = mg.get("groom") or {}, mg.get("bride") or {}
    present = [bool(ga.get("present")), bool(gb.get("present"))]
    if not any(present) or (all(present)):
        m2 = _m("M2_mangal_dosha", "S", ["no net Mangal dosha" if not any(present)
                                        else "Mangal dosha in both charts (mutual cancellation)"])
    else:
        m2 = _m("M2_mangal_dosha", "W", ["Mangal dosha in one chart only after cancellations; see details"])
    m3 = _cross(facts_a, facts_b)
    da, db = (m.get("dasha") or {}).get("groom") or {}, (m.get("dasha") or {}).get("bride") or {}
    if not (da.get("available") and db.get("available")):
        m4 = _m("M4_dasha_alignment", "NE", [], "dasha context unavailable")
    elif da.get("strongly_adverse") or db.get("strongly_adverse"):
        m4 = _m("M4_dasha_alignment", "W", ["one person is in a period strongly linked to 7th-house ADV"])
    else:
        m4 = _m("M4_dasha_alignment", "S", ["neither person is in a strongly adverse 7th-house period now"])
    methods = [m1, m2, m3, m4]
    n = sum(x["value"] == "S" for x in methods)
    k = sum(x["value"] != "NE" for x in methods)
    badge = f"Compatibility methods agreeing: {n}/4" + ("" if k == 4 else f" ({k} of 4 methods evaluated)")
    return {"badge": badge, "n": n, "k_evaluated": k, "methods": methods, "matching": m,
            "rule_id": R, "rule_version": rulepack.version(R),
            "verify_pending": ["NADI_BHAKOOT_CANCELLATION", "MANGAL_DOSHA_CANCELLATIONS"],
            "note": "Per-method traditional indications only; nothing here predicts whether a relationship succeeds."}
