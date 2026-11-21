"""Pre-registration of a prediction: a frozen, hashed record of exactly what
the engine said before any outcome is known.

The payload is built once when the prediction is saved and stored in
PredictionRegistration (never updated; see db.py guards). Backtests read this
payload, not the mutable prediction row, so a later edit cannot leak outcomes
into the rules.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

APP_VERSION = "0.1.0"
SCHEMA = 1
_DATA = Path(__file__).resolve().parents[2] / "data"
_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def rule_pack_hash() -> str:
    h = hashlib.sha256()
    files = [_DATA / "rule_packs.json", *sorted((_DATA / "rulepack").glob("*.json"))]
    for path in files:
        if path.exists():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def rule_key(pillar_rule_id: str, text: str) -> str:
    """Stable rule ID for a free-text triggered rule: dates, house numbers and
    planet names are dropped ('transit Saturn in house 7 (first seen ...)' ->
    '<pillar rule>/transit in house')."""
    t = re.split(r"[@:(,;\d]", str(text), maxsplit=1)[0]
    t = re.sub(r"\b(?:%s)\b" % "|".join(_PLANETS), "", t)
    slug = re.sub(r"[^a-z]+", "_", t.lower()).strip("_")
    return f"{pillar_rule_id}/{slug or 'unnamed'}"


def rules_fired(analysis: dict) -> dict:
    """Per pillar: verdict, pillar rule ID and the sorted stable keys of the rules that fired."""
    out = {}
    verdicts = analysis.get("pillars") or {}
    for f in analysis.get("evidence") or []:
        name, rid = f.get("module"), f.get("rule_id")
        if not name or not rid:
            continue
        keys = sorted({rule_key(rid, r) for r in f.get("triggered_rules") or []})
        out[name] = {"verdict": verdicts.get(name), "rule_id": rid, "rule_pack_version": f.get("rule_version"),
                     "fired": keys}
    return out


def build(analysis: dict, *, question: str = "", settings_dict: dict | None = None,
          calc_fingerprint: str | None = None, protocol: str | None = None,
          now: datetime | None = None) -> dict:
    decision = analysis.get("decision") or {}
    event = decision.get("event") or {}
    window = analysis.get("analysis_window") or {}
    audit = analysis.get("classical") or {}
    return {
        "schema": SCHEMA,
        "domain": analysis.get("domain"),
        "rules_fired": rules_fired(analysis),
        "convergence": {"n_of_4": analysis.get("support_count"), "conflict": analysis.get("conflict_count"),
                        "unavailable": analysis.get("unavailable_count"), "label": analysis.get("convergence")},
        "promise_grade": audit.get("promise"),
        "window": {"start": window.get("start"), "end": window.get("end")},
        "event": {"event_type": event.get("event_type"), "definition": event.get("definition")},
        "success_criteria": decision.get("success_criteria"),
        "disposition": decision.get("disposition"),
        "settings_fingerprint": sha256(settings_dict) if settings_dict is not None else None,
        "calc_fingerprint": calc_fingerprint,
        "rule_pack": {"version": (next(iter(rules_fired(analysis).values()), {}) or {}).get("rule_pack_version"),
                      "sha256": rule_pack_hash()},
        "protocol": protocol,
        "app_version": APP_VERSION,
        "registered_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def make_registration(payload: dict):
    from ..db import PredictionRegistration
    return PredictionRegistration(payload_json=canonical(payload), payload_sha256=sha256(payload))


def verify(reg, record=None) -> bool:
    """True when the stored payload still matches its hash (and, if given, the prediction row's window/event)."""
    try:
        payload = json.loads(reg.payload_json)
    except (TypeError, ValueError):
        return False
    if sha256(payload) != reg.payload_sha256:
        return False
    if record is not None:
        w = payload.get("window") or {}
        if (str(record.window_start) != w.get("start") or str(record.window_end) != w.get("end")
                or record.event_type != (payload.get("event") or {}).get("event_type")):
            return False
    return True
