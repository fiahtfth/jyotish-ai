"""Rule pack loader/validator (backend/data/rulepack/*.json).

Every rule used by convergence code must exist here with rule_id, version, source,
conditions, exceptions, status and tests. Rules marked verify=true stay
`disabled_verify` until a source check (verified_by + verified_on) is recorded.
Callers must emit a NE result (never a fabricated one) for a disabled rule.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parents[3] / "data" / "rulepack"
STATUSES = ("enabled", "disabled_verify")
DISABLED_REASON = "rule disabled pending source check"
_KEYS = {"rule_id", "version", "source", "conditions", "exceptions", "status", "verify",
         "verified_by", "verified_on", "tests"}


class RulePackError(ValueError):
    pass


def _validate_rule(r: dict, where: str) -> None:
    if not isinstance(r, dict):
        raise RulePackError(f"{where}: rule must be an object")
    unknown, missing = set(r) - _KEYS, _KEYS - set(r)
    if unknown or missing:
        raise RulePackError(f"{where} {r.get('rule_id')}: unknown {sorted(unknown)} missing {sorted(missing)}")
    rid = r["rule_id"]
    if not isinstance(rid, str) or not rid:
        raise RulePackError(f"{where}: bad rule_id")
    for k in ("version", "source"):
        if not isinstance(r[k], str) or not r[k]:
            raise RulePackError(f"{rid}: {k} required")
    if r["status"] not in STATUSES:
        raise RulePackError(f"{rid}: status must be one of {STATUSES}")
    if not isinstance(r["tests"], list) or not isinstance(r["exceptions"], list):
        raise RulePackError(f"{rid}: tests/exceptions must be lists")
    if r["status"] == "enabled":
        if not r["tests"]:
            raise RulePackError(f"{rid}: enabled rule must list tests")
        if r["verify"] and not (r["verified_by"] and r["verified_on"]):
            raise RulePackError(f"{rid}: VERIFY rule cannot be enabled without verified_by/verified_on")


@lru_cache(maxsize=1)
def load() -> dict:
    rules: dict = {}
    for path in sorted(DIR.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(pack, dict) or not isinstance(pack.get("rules"), list):
            raise RulePackError(f"{path.name}: expected {{'pack','rules':[...]}}")
        for r in pack["rules"]:
            _validate_rule(r, path.name)
            if r["rule_id"] in rules:
                raise RulePackError(f"duplicate rule_id {r['rule_id']}")
            rules[r["rule_id"]] = r
    return rules


def reload() -> dict:
    load.cache_clear()
    return load()


def rule(rule_id: str) -> dict:
    try:
        return load()[rule_id]
    except KeyError:
        raise KeyError(f"rule {rule_id!r} is not in the rule pack") from None


def is_enabled(rule_id: str) -> bool:
    return rule(rule_id)["status"] == "enabled"


def version(rule_id: str) -> str:
    return rule(rule_id)["version"]


def ne_reason(rule_id: str):
    """None if the rule may be used, else the NE reason callers must report."""
    return None if is_enabled(rule_id) else DISABLED_REASON


def all_rule_ids() -> list:
    return sorted(load())
