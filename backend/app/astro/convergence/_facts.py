"""Shared read-only views over engine facts used by several convergence modules.

Uses the richer facts the engine already computes (varga_reliability, strength)
instead of recomputing them.
"""
from __future__ import annotations

from typing import Optional

UNRELIABLE = ("cusp_sensitive", "unusable")


def unknown_time(facts: dict, birth=None) -> bool:
    """Mode B / unknown birth time: Lagna-dependent pillars must be NE."""
    if (facts.get("meta") or {}).get("birth_time_precision") == "unknown":
        return True
    return getattr(birth, "birth_time_precision", "exact") == "unknown"


def varga_unusable(facts: dict, varga: str) -> Optional[str]:
    """NE reason when the engine marks `varga` cusp-sensitive/unusable for this birth time, else None.

    D1 is never gated here (its Lagna sensitivity is handled by the unknown-time path)."""
    if varga == "D1":
        return None
    status = (facts.get("varga_reliability") or {}).get(varga)
    if status in UNRELIABLE:
        return f"{varga} is {status.replace('_', '-')} for this birth time (varga_reliability)"
    return None
