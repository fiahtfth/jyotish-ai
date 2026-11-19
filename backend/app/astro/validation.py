"""Evaluate frozen forecasts on a later, person-separated holdout set.

No weights are fitted here. This establishes a reproducible benchmark against
which future rule/precision changes must be tested before deployment.
"""
from datetime import date
from math import log
from statistics import mean, median
from .prediction import scorecard, prospective_rows


def _timing_error(rows):
    errors = []
    for row in rows:
        if row.get("event_date") and row["outcome"] in ("happened", "outside_window"):
            start, end, actual = (date.fromisoformat(str(row[key])[:10])
                                  for key in ("window_start", "window_end", "event_date"))
            errors.append(max((start - actual).days, (actual - end).days, 0))
    return {"dated_events": len(errors), "median_days_outside_window": median(errors) if errors else None,
            "mean_days_outside_window": mean(errors) if errors else None}


def _probability_metrics(rows, development_rate):
    pairs = []
    for row in rows:
        p = row.get("frozen_probability")
        frozen = str(row.get("probability_frozen_at") or "")[:10]
        if type(p) in (float, int) and 0 <= p <= 1 and frozen and frozen < str(row["window_start"])[:10]:
            pairs.append((p, int(row["outcome"] == "happened")))
    if not pairs:
        return {"status": "unavailable", "observations": 0, "reason": "No pre-window probability was provided."}
    bins = {}
    for p, actual in pairs:
        bins.setdefault(min(9, int(p * 10)), []).append((p, actual))
    return {"status": "evaluated", "observations": len(pairs),
            "brier": mean((p - actual) ** 2 for p, actual in pairs),
            "log_loss": -mean(log(max(1e-15, p if actual else 1 - p)) for p, actual in pairs),
            "base_rate_brier": mean((development_rate - actual) ** 2 for _, actual in pairs)
            if development_rate is not None else None,
            "reliability": [{"bin": level, "count": len(group),
                             "mean_forecast": mean(p for p, _ in group), "observed_rate": mean(a for _, a in group)}
                            for level, group in sorted(bins.items())]}


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
                             "timing_error": _timing_error(resolved),
                             "probability_metrics": _probability_metrics(resolved, rate),
                             "scorecard": scorecard([r for r in test if r["domain"] == domain and (r.get("event_type") or "unspecified") == event_type], today=now)}
    return {"cutoff": cutoff, "development_rows": len(train), "holdout_rows": len(test),
            "holdout": metrics, "by_domain": baselines,
            "limitations": ["Self-reported outcomes and selective reporting can bias these results.",
                            "No claim of validated accuracy without adequate prospective data and uncertainty analysis.",
                            "Do not adjust rules on this holdout; use a new future holdout for the next model selection."]}
