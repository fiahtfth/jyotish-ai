"""Shared data types for the multi-method convergence engine.

No percentages anywhere: convergence is a count of independent traditional
methods, not a probability (see docs/INTENT_CONVERGENCE_SPEC.md, Part 1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# Pillar result values (spec 1.1)
S, M, W, A, NE = "S", "M", "W", "A", "NE"
PILLAR_VALUES = (S, M, W, A, NE)
PILLAR_NAMES = ("P1", "P2", "P3", "P4")
NATAL_NAMES = ("M1", "M2", "M3", "M4")

# Window result types (spec 1.4)
SUPPORTIVE_PERIOD = "supportive_period"
MIXED_PERIOD = "mixed_period"
WEAK_INDICATION = "weak_indication"
INSUFFICIENT_DATA = "insufficient_data"
RESULT_TYPES = (SUPPORTIVE_PERIOD, MIXED_PERIOD, WEAK_INDICATION, INSUFFICIENT_DATA)

PROMISE_STRONG, PROMISE_MODERATE, PROMISE_WEAK, PROMISE_NE = "STRONG", "MODERATE", "WEAK", "NE"

PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")


@dataclass(frozen=True)
class Evidence:
    """One traceable piece of evidence. `factors` are the underlying factors used
    for de-duplication, e.g. "PLANET:VENUS", "HOUSE:7", "LORD:H7", "MOON_NAKSHATRA"."""
    rule_id: str
    rule_version: str
    fact_ids: tuple
    direction: int            # +1 supportive, -1 adverse, 0 neutral/informational
    weight: float
    factors: frozenset
    interval: Optional[tuple] = None
    text: str = ""
    ne_reason: Optional[str] = None

    def __post_init__(self):
        if self.direction not in (-1, 0, 1):
            raise ValueError("Evidence.direction must be -1, 0 or +1")
        object.__setattr__(self, "fact_ids", tuple(self.fact_ids))
        object.__setattr__(self, "factors", frozenset(self.factors))

    @property
    def depends_on_factors(self) -> frozenset:
        return self.factors


@dataclass(frozen=True)
class PillarResult:
    pillar: str                       # P1..P4 (timing) or M1..M4 (natal)
    value: str                        # S | M | W | A | NE
    evidence: tuple = ()
    interval: Optional[tuple] = None
    ne_reason: Optional[str] = None
    dependent: bool = False           # set by dedup: S but shares factors with higher priority
    dependent_on: tuple = ()          # pillars whose factors it shares

    def __post_init__(self):
        if self.value not in PILLAR_VALUES:
            raise ValueError(f"unknown pillar value {self.value!r}")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "dependent_on", tuple(self.dependent_on))

    @staticmethod
    def not_evaluated(pillar: str, reason: str, interval=None) -> "PillarResult":
        return PillarResult(pillar, NE, (), interval, reason)

    @property
    def label(self) -> str:
        if self.value == S and self.dependent:
            who = "/".join(self.dependent_on) or "higher-priority pillars"
            return f"S (dependent — shares factors with {who})"
        return self.value


@dataclass(frozen=True)
class PromiseFactor:
    name: str                 # "F1_lord_strength" ...
    score: int                # -1, 0, +1 (0 when unavailable)
    available: bool
    note: str = ""
    evidence: tuple = ()


@dataclass(frozen=True)
class PromiseResult:
    level: str                # STRONG | MODERATE | WEAK | NE (no factor computable)
    score: int
    factors: tuple = ()
    evidence: tuple = ()
    unavailable: tuple = ()   # factor names lacking data (reported, never fabricated)

    @property
    def caps_result_type(self) -> bool:
        return self.level == PROMISE_WEAK


@dataclass(frozen=True)
class WindowResult:
    interval: Optional[tuple]
    pillars: tuple                       # PillarResult x4 (dependency flags applied)
    n: int
    k_evaluated: int
    dependent: tuple                     # names of pillars that are S but dependent
    promise: Optional[PromiseResult]
    result_type: str
    kp: Optional[PillarResult]           # separate frame, never adds to n
    badge: str
    disclaimer: str
    notes: tuple = ()
    supportive_evidence: tuple = ()
    conflicting_evidence: tuple = ()
    ne_pillars: tuple = ()
    overlay: Optional[Any] = None        # natal template: optional P1 'active now?' PillarResult


# ---------------------------------------------------------------- IntentConfig

TEMPLATES = ("T", "N", "N+T", "T_adverse", "special")
TIMING_TEMPLATES = ("T", "T_adverse", "N+T")
VARGAS = ("D1", "D2", "D3", "D4", "D6", "D7", "D9", "D10", "D11", "D12", "D16", "D20", "D24", "D30", "D60")
OPTIONAL_VARGAS = ("D11", "D30", "D60")      # unavailable -> NE, never fabricated
JAIMINI_KARAKAS = ("AK", "AmK", "BK", "MK", "PK", "GK", "DK")
ARUDHAS = tuple(f"A{i}" for i in range(1, 13)) + ("AL", "UL")
DERIVED_J = ("UL_2", "AL_11", "AL_12", "KARAKAMSHA", "KARAKAMSHA_12")
HOOKS = ("sade_sati", "muhurta", "compatibility", "past_event", "rectify", "current_dasha",
         "annual", "transition", "special", "p1_overlay")
KP_STATUSES = ("enabled", "verify", "ne")
SAFETY_DOMAINS = ("career", "marriage_relationship", "finance", "education", "foreign", "property",
                  "children_family", "wellbeing", "personality_spiritual", "general")

_K_DERIVED = re.compile(r"^(LORD|STRONGEST_LINKED):H(1[0-2]|[1-9])$")
_TOP_KEYS = {"intent_id", "number", "phase", "template", "E", "E_optional", "E_adverse_explicit", "K", "V", "J",
             "TAJ", "TRIG", "KP", "hooks", "min_n_for_label", "requires_consent", "safety_domain",
             "legacy_ids", "forecast_events"}


class IntentConfigError(ValueError):
    pass


def _houses(val, name):
    if not isinstance(val, (list, tuple)):
        raise IntentConfigError(f"{name} must be a list")
    out = []
    for h in val:
        if isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= 12:
            raise IntentConfigError(f"{name}: house {h!r} outside 1-12")
        out.append(h)
    if len(set(out)) != len(out):
        raise IntentConfigError(f"{name}: duplicate houses")
    return tuple(out)


def _strs(val, name, allowed=None, pattern=None):
    if not isinstance(val, (list, tuple)) or not all(isinstance(x, str) for x in val):
        raise IntentConfigError(f"{name} must be a list of strings")
    for x in val:
        if allowed is not None and x not in allowed and not (pattern and pattern.match(x)):
            raise IntentConfigError(f"{name}: unknown value {x!r}")
    return tuple(val)


def _exact(d, keys, name):
    if not isinstance(d, Mapping):
        raise IntentConfigError(f"{name} must be an object")
    unknown = set(d) - set(keys)
    missing = set(keys) - set(d)
    if unknown:
        raise IntentConfigError(f"{name}: unknown keys {sorted(unknown)}")
    if missing:
        raise IntentConfigError(f"{name}: missing keys {sorted(missing)}")


@dataclass(frozen=True)
class IntentConfig:
    intent_id: str
    number: int
    phase: int
    template: str
    E: tuple
    E_optional: tuple
    E_adverse_explicit: tuple
    K: tuple
    V: tuple
    J: tuple
    TAJ: Mapping
    TRIG: Mapping
    KP: Mapping
    hooks: tuple
    min_n_for_label: int
    requires_consent: bool
    safety_domain: str
    legacy_ids: tuple
    forecast_events: tuple

    @property
    def primary_house(self) -> Optional[int]:
        return self.E[0] if self.E else (self.E_adverse_explicit[0] if self.E_adverse_explicit else None)

    @property
    def primary_varga(self) -> Optional[str]:
        return next((v for v in self.V if v != "D1"), None)

    @property
    def is_timing(self) -> bool:
        return self.template in TIMING_TEMPLATES

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "IntentConfig":
        _exact(d, _TOP_KEYS, "intent")
        if not isinstance(d["intent_id"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]+", d["intent_id"]):
            raise IntentConfigError("intent_id must be UPPER_SNAKE")
        n = d["number"]
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 61:
            raise IntentConfigError("number must be an int 1-61")
        if d["phase"] not in (1, 2, 3):
            raise IntentConfigError("phase must be 1, 2 or 3")
        if d["template"] not in TEMPLATES:
            raise IntentConfigError(f"unknown template {d['template']!r}")
        E = _houses(d["E"], "E")
        E_opt = _houses(d["E_optional"], "E_optional")
        E_adv = _houses(d["E_adverse_explicit"], "E_adverse_explicit")
        K = _strs(d["K"], "K", set(PLANETS) | set(JAIMINI_KARAKAS), _K_DERIVED)
        V = _strs(d["V"], "V", set(VARGAS))
        J = _strs(d["J"], "J", set(JAIMINI_KARAKAS) | set(ARUDHAS) | set(DERIVED_J) | set(PLANETS))
        taj = d["TAJ"]
        _exact(taj, ("houses", "muntha_supportive"), "TAJ")
        taj = {"houses": _houses(taj["houses"], "TAJ.houses"),
               "muntha_supportive": _houses(taj["muntha_supportive"], "TAJ.muntha_supportive")}
        trig = d["TRIG"]
        _exact(trig, ("slow", "fast"), "TRIG")
        trig = {"slow": _strs(trig["slow"], "TRIG.slow", set(PLANETS)),
                "fast": _strs(trig["fast"], "TRIG.fast", set(PLANETS))}
        kp = d["KP"]
        _exact(kp, ("houses", "negate", "status"), "KP")
        if kp["status"] not in KP_STATUSES:
            raise IntentConfigError(f"KP.status must be one of {KP_STATUSES}")
        kp = {"houses": _houses(kp["houses"], "KP.houses"), "negate": _houses(kp["negate"], "KP.negate"),
              "status": kp["status"]}
        if kp["status"] == "ne" and kp["houses"]:
            raise IntentConfigError("KP.status 'ne' must not list houses")
        hooks = _strs(d["hooks"], "hooks", set(HOOKS))
        mn = d["min_n_for_label"]
        if isinstance(mn, bool) or not isinstance(mn, int) or not 1 <= mn <= 4:
            raise IntentConfigError("min_n_for_label must be an int 1-4")
        if d["template"] in TIMING_TEMPLATES and mn < 3:
            raise IntentConfigError("timing/adverse intents need min_n_for_label >= 3")
        if not isinstance(d["requires_consent"], bool):
            raise IntentConfigError("requires_consent must be bool")
        if d["safety_domain"] not in SAFETY_DOMAINS:
            raise IntentConfigError(f"unknown safety_domain {d['safety_domain']!r}")
        if d["template"] != "special" and not (E or E_adv) and "special" not in hooks:
            raise IntentConfigError("non-special intent without houses needs the 'special' hook")
        if d["template"] in TIMING_TEMPLATES and not (E or E_adv):
            raise IntentConfigError("timing intent needs E houses")
        if set(E) & set(E_adv):
            raise IntentConfigError("E and E_adverse_explicit overlap")
        return cls(d["intent_id"], n, d["phase"], d["template"], E, E_opt, E_adv, K, V, J, taj, trig, kp,
                   hooks, mn, d["requires_consent"], d["safety_domain"],
                   _strs(d["legacy_ids"], "legacy_ids"), _strs(d["forecast_events"], "forecast_events"))
