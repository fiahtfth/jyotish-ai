"""Versioned pillar findings and the unique underlying factors they depend on."""
from functools import lru_cache
import json
from pathlib import Path

_RULES = Path(__file__).resolve().parents[2] / "data" / "rule_packs.json"


@lru_cache(maxsize=1)
def rule_packs():
    return json.loads(_RULES.read_text(encoding="utf-8"))


def pillar_finding(module, verdict, facts, start, end, descriptions, rules):
    pack = rule_packs()
    rule = pack["pillar_rules"][module]
    referenced = []
    for path in rule["computed_facts"]:
        value = facts
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None:
            referenced.append(path)
    return {"id": "pillar:" + module, "intent_id": None, "module": module, "rule_id": rule["rule_id"],
            "rule_version": pack["version"], "source_ref": rule["source_ref"], "computed_facts": referenced,
            "direction": {"support": "supportive", "conflict": "conflicting"}.get(verdict, "neutral"),
            "weight": None, "time_interval": {"start": start.isoformat(), "end": end.isoformat()},
            "depends_on_factors": rule["depends_on_factors"],
            "uncertainty_flags": ["module_unavailable"] if verdict == "unavailable" else [],
            "details": descriptions, "triggered_rules": rules}


def dependency_index(findings):
    """Each factor appears once, even when several methods use it."""
    factors = {}
    for finding in findings:
        if not finding["uncertainty_flags"]:
            for dependency in finding["depends_on_factors"]:
                factors.setdefault(dependency, []).append(finding["id"])
    return factors
