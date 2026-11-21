"""#58 MUHURTA (and the optional Muhurta step of #19/#40/#41): delegates to astro/muhurta.py.

Groups each slot's factors into the spec's four categories and adds the badge
"Muhurta factors satisfied: k/4". Slots returned by muhurta.scan have already passed the
exclusions (Rahu Kaal, Yamaganda, Gulika, Vishti/Bhadra...), so category 4 also checks Durmuhurta."""
from __future__ import annotations

from ... import muhurta as muhurta_mod
from .. import rulepack

R = "HOOK_MUHURTA_FACTORS"
GROUPS = {
    "panchanga_shuddhi": ("F-VARA", "F-TITHI", "F-NAK", "F-YOGA"),
    "tarabala_chandrabala": ("F-TARA", "F-CHANDRA"),
    "lagna_shuddhi": ("F-LAGNA", "F-8H", "F-BEN", "F-MOON"),
    "avoid_periods": ("F-DURM",),
}
EVENT_FOR_INTENT = {"BUSINESS_START": "business", "HOUSE_CONSTRUCTION": "property",
                    "VEHICLE_PURCHASE": "vehicle", "MUHURTA": None}


def group_slot(slot: dict) -> dict:
    ok = {f["id"]: bool(f.get("ok")) for f in slot.get("factors", [])}
    groups, k, evaluated = {}, 0, 0
    for g, ids in GROUPS.items():
        present = [i for i in ids if i in ok]
        if not present:
            groups[g] = {"status": "not_evaluated", "factors": []}
            continue
        evaluated += 1
        sat = all(ok[i] for i in present)
        k += sat
        groups[g] = {"status": "satisfied" if sat else "not_satisfied",
                     "factors": [{"id": i, "ok": ok[i]} for i in present]}
    badge = f"Muhurta factors satisfied: {k}/4" + ("" if evaluated == 4 else f" ({evaluated} of 4 evaluated)")
    return {**slot, "groups": groups, "k4": k, "badge4": badge}


def search(event: str, start, end, lat: float, lon: float, place_name: str = "", facts=None, settings=None,
           direction=None, top: int = 3) -> dict:
    out = muhurta_mod.scan(event, start, end, lat, lon, place_name, native_facts=facts, settings=settings,
                           direction=direction, top=max(top, 3))
    slots = [group_slot(s) for s in out.get("slots", [])]
    slots.sort(key=lambda s: (-s["k4"], -s.get("k", 0)))
    out["slots"] = slots[:top]
    out["rule_id"], out["rule_version"] = R, rulepack.version(R)
    out["note"] = ("Muhurta Chintamani tables are applied as implemented in astro/muhurta.py; the "
                   "verse-level table check (MUHURTA_CHINTAMANI_TABLES) is pending.")
    return out
