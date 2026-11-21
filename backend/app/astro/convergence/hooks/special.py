"""Dispatcher for `special`-template intents (spec Part 3, hooks)."""
from __future__ import annotations

from datetime import date

from .. import _ivl
from ..types import IntentConfig

NEEDS = {"MUHURTA": "event, lat, lon", "PAST_EVENT_CHECK": "events", "BIRTH_TIME_CHECK": "events (>= 3)",
         "COMPATIBILITY": "partner_facts and consent"}
WELLBEING_NOTE = ("Traditional period context only, not medical or psychological advice. If you are in "
                  "distress, please reach out (India: Tele-MANAS 14416).")


def dispatch(cfg: IntentConfig, facts: dict, birth, *, start=None, end=None, today=None, **kw) -> dict:
    today = _ivl.to_date(today) if today else date.today()
    iid = cfg.intent_id
    if iid == "SADE_SATI":
        from . import sade_sati
        a, b = (start, end) if kw.get("explicit_range") else sade_sati.default_range(today)
        return sade_sati.phases(facts, birth, a, b, include_dhaiya=kw.get("include_dhaiya", True))
    if iid in ("CURRENT_DASHA", "EMOTIONAL_SUPPORT", "STRESS_PHASE"):
        from . import current_dasha
        out = {"current_dasha": current_dasha.current(facts, birth, today)}
        if iid == "STRESS_PHASE":
            from . import sade_sati
            out["sade_sati"] = sade_sati.phases(facts, birth, today, today, include_dhaiya=True)
        if iid != "CURRENT_DASHA":
            out["note"] = WELLBEING_NOTE
            out["badge"] = None          # no convergence badge for well-being context
        return out
    if iid == "ANNUAL_THEMES":
        from . import annual
        return annual.annual_themes(facts, birth, today)
    if iid == "LIFE_TRANSITION":
        from . import transition
        return transition.life_transition(facts, birth, today)
    if iid == "MUHURTA":
        if not {"event", "lat", "lon"} <= set(kw):
            return {"status": "needs_input", "needs": NEEDS[iid]}
        from . import muhurta
        return muhurta.search(kw["event"], start, end, kw["lat"], kw["lon"], kw.get("place_name", ""),
                              facts=facts, settings=getattr(birth, "settings", None))
    if iid == "PAST_EVENT_CHECK":
        if not kw.get("events"):
            return {"status": "needs_input", "needs": NEEDS[iid]}
        from . import past_event
        return past_event.check(facts, birth, kw["events"])
    if iid == "BIRTH_TIME_CHECK":
        if not kw.get("events"):
            return {"status": "needs_input", "needs": NEEDS[iid]}
        from . import rectify
        return rectify.rectify(birth, kw["events"], kw.get("span_min", 15))
    if iid == "COMPATIBILITY":
        if kw.get("partner_facts") is None:
            return {"status": "needs_input", "needs": NEEDS[iid]}
        from . import compatibility
        return compatibility.compatibility(facts, kw["partner_facts"], bool(kw.get("consent")))
    return {"status": "not_implemented", "reason": f"no special handler for {iid}"}
