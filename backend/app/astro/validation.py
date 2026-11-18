"""Evaluate frozen forecasts on a later, person-separated holdout set.

No weights are fitted here. This establishes a reproducible benchmark against
which future rule/precision changes must be tested before deployment.
"""
from datetime import date
from .prediction import scorecard, prospective_rows


def evaluate_dataset(rows, *, cutoff, holdout_profiles, today=None):
    cutoff = date.fromisoformat(cutoff).isoformat()
    if not holdout_profiles:
        raise ValueError("Explicit held-out profile IDs are required.")
    holdout = set(holdout_profiles)
    train = [r for r in rows if r.get("profile_id") not in holdout
             and r.get("window_end") and str(r["window_end"])[:10] < cutoff
             and r.get("outcome_at") and str(r["outcome_at"])[:10] < cutoff
             and r.get("event_type") and r.get("protocol") and r.get("success_criteria")
             and r.get("outcome") in ("happened", "did_not", "outside_window")]
    test = [r for r in rows if r.get("profile_id") in holdout
            and r.get("created_at") and str(r["created_at"])[:10] >= cutoff
            and r.get("window_start") and str(r["window_start"])[:10] >= cutoff]
    metrics = scorecard(test, today=today)
    baselines = {}
    now = today or date.today()
    for domain, event_type in sorted({(r["domain"], r.get("event_type") or "unspecified") for r in test}):
        dev = [r for r in train if r["domain"] == domain and r["event_type"] == event_type]
        event_count = sum(r["outcome"] == "happened" for r in dev)
        rate = event_count / len(dev) if dev else None
        predicted_event = rate is not None and rate >= 0.5
        prospective, _ = prospective_rows([r for r in test if r["domain"] == domain and (r.get("event_type") or "unspecified") == event_type])
        resolved = [r for r in prospective if r.get("window_end")
                    and date.fromisoformat(str(r["window_end"])[:10]) < now
                    and r.get("outcome") in ("happened", "did_not", "outside_window")]
        hits = sum((r["outcome"] == "happened") == predicted_event for r in resolved) if dev else None
        baselines[f"{domain}:{event_type}"] = {"development_observations": len(dev), "development_event_frequency": rate,
                             "test_observations": len(resolved), "baseline_hits": hits,
                             "scorecard": scorecard([r for r in test if r["domain"] == domain and (r.get("event_type") or "unspecified") == event_type], today=now)}
    return {"cutoff": cutoff, "development_rows": len(train), "holdout_rows": len(test),
            "holdout": metrics, "by_domain": baselines,
            "limitations": ["Self-reported outcomes and selective reporting can bias these results.",
                            "No claim of validated accuracy without adequate prospective data and uncertainty analysis.",
                            "Do not adjust rules on this holdout; use a new future holdout for the next model selection."]}
