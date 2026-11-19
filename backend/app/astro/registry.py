"""Versioned intent contracts and coverage, independent of user data."""
from functools import lru_cache
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "data" / "intent_registry.json"
_FIRING_RATES = _PATH.with_name("specificity_results.json")


@lru_cache(maxsize=1)
def registry():
    from .prediction import VERSION

    data = json.loads(_PATH.read_text(encoding="utf-8"))
    if _FIRING_RATES.exists():
        runs = json.loads(_FIRING_RATES.read_text(encoding="utf-8"))
        by_intent = {run["intent"]: run for run in runs if run["protocol"] == VERSION and run["chart_windows"] >= 1000}
        for row in data["intents"]:
            run = by_intent.get(row["intent_id"])
            if run and run["intent_version"] == row["version"] and row["specificity"] is not None:
                row["specificity"] = {key: run[key] for key in row["specificity"]}
    return data


def forecast_intent(event):
    return next((row for row in registry()["intents"] if row["forecast_event"] == event), None) if event else None


def spec_intent(intent_id):
    """Resolve a spec intent (INTENT_CONVERGENCE_SPEC Part 3) to its IntentConfig.

    Accepts the spec number, the spec intent_id, or any legacy registry id
    (mapped via the row's `spec_intent` pointer or the config's `legacy_ids`).
    """
    from .convergence import intents as spec_intents
    if intent_id is None:
        return None
    if not isinstance(intent_id, int):
        row = next((r for r in registry()["intents"] + registry().get("spec_only_intents", [])
                    if r["intent_id"] == intent_id), None)
        if row and row.get("spec_intent"):
            return spec_intents.get(row["spec_intent"])
    return spec_intents.get(intent_id)


def _specificity_report():
    path = Path(__file__).resolve().parents[2] / "data" / "specificity_report.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def coverage():
    from .convergence import intents as spec_intents
    rows = registry()["intents"]
    report = _specificity_report() or {}
    rates = report.get("intents", report) if isinstance(report, dict) else {}
    spec = [{"number": c.number, "intent_id": c.intent_id, "phase": c.phase, "template": c.template,
             "kp_status": c.KP["status"], "legacy_ids": list(c.legacy_ids),
             "specificity": rates.get(c.intent_id) if isinstance(rates, dict) else None}
            for _, c in sorted(spec_intents.load_all().items())]
    return {"version": registry()["version"], "counts": {
        status: sum(row["status"] == status for row in rows)
        for status in ("implemented", "partial", "unsupported")
    }, "intents": rows, "spec": {"count": len(spec), "intents": spec,
                                  "specificity_report": bool(report)}}
