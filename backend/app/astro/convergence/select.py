"""Choose the intent config for a forecast question.

An explicit event type wins (the spec configs name the forecast events they
own); otherwise the chat domain picks a sensible default and a few question
keywords refine it. Nothing is fabricated — an unmapped question simply keeps
the legacy path.
"""
from __future__ import annotations

from typing import Optional

from . import intents
from .types import IntentConfig

# prediction.EVENTS that no intent config claims via forecast_events
_EVENT_FALLBACK = {
    "foreign_settlement": 32, "foreign_travel": 31,
    "property_purchase": 37, "vehicle_purchase": 41,
    "litigation_win": 24, "litigation_resolution": 24,
    "debt_cleared": 21,
}

_DOMAIN_DEFAULT = {
    "career": 1, "relationship": 9, "education": 26, "relocation": 34,
    "children": 42, "parents": 44, "debt": 21, "litigation": 24,
    "finance": 17, "direction": 51, "health": 49, "property": 37,
}

# (domain, substring, intent number) — checked in order, first hit wins
_QUESTION_REFINEMENTS = [
    ("career", "promotion", 2), ("career", "promote", 2),
    ("career", "change", 3), ("career", "switch", 3), ("career", "new job", 3),
    ("career", "govt", 4), ("career", "government", 4),
    ("career", "business", 19), ("career", "start-up", 19), ("career", "startup", 19),
    ("career", "stagnat", 7), ("career", "stuck", 7),
    ("career", "layoff", 8), ("career", "lost", 8), ("career", "fired", 8),
    ("relationship", "delay", 11), ("relationship", "late", 11),
    ("relationship", "love", 10), ("relationship", "arranged", 10),
    ("relationship", "partner", 9), ("relationship", "marry", 9),
    ("finance", "business", 19), ("finance", "debt", 21), ("finance", "partner", 20),
    ("education", "exam", 27), ("education", "competitive", 27),
    ("education", "abroad", 28), ("education", "foreign", 28),
    ("education", "masters", 29), ("education", "phd", 29), ("education", "higher", 29),
    ("relocation", "settle", 32), ("relocation", "permanent", 32),
    ("relocation", "travel", 31), ("relocation", "visit", 31), ("relocation", "trip", 31),
    ("relocation", "visa", 36), ("relocation", "return", 35), ("relocation", "back", 35),
    ("relocation", "job", 33),
    ("property", "vehicle", 41), ("property", "car", 41),
    ("property", "sell", 38), ("property", "sale", 38),
    ("property", "construct", 40), ("property", "inherit", 39),
]


def for_event(event_type: str) -> Optional[IntentConfig]:
    if not event_type:
        return None
    for cfg in intents.load_all().values():
        if event_type in cfg.forecast_events:
            return cfg
    num = _EVENT_FALLBACK.get(event_type)
    return intents.get(num) if num else None


def for_domain(domain: str, question: str = "") -> Optional[IntentConfig]:
    q = (question or "").lower()
    for dom, needle, num in _QUESTION_REFINEMENTS:
        if dom == domain and needle in q:
            return intents.get(num)
    num = _DOMAIN_DEFAULT.get(domain or "")
    return intents.get(num) if num else None
