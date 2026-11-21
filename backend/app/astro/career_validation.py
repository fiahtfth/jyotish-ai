"""Offline comparisons on a pre-registered, consented career-event cohort."""
from datetime import date, timedelta
from random import Random
from statistics import mean
from types import SimpleNamespace

from . import career_events, prediction

PROTOCOL_PUBLISHED = date(2026, 11, 21)

CONTEXT_STAGES = {
    "promotion": {"no_review_scheduled", "review_scheduled", "promotion_discussed"},
    "job_change": {"not_searching", "applying", "interviewing", "offer_received"},
    "job_offer": {"not_searching", "applying", "interviewing"},
}


def _date(value):
    return date.fromisoformat(value[:10])


def _trial(row, today):
    event = row.get("event_type")
    if row.get("consented") is not True or row.get("protocol") != prediction.VERSION or event not in career_events.RULES:
        return None
    try:
        registered, start, end, resolved = (_date(row[k]) for k in
                                            ("registered_at", "window_start", "window_end", "outcome_at"))
        actual = _date(row["event_date"]) if row.get("event_date") else None
        person = row["profile_id"]
        birth = row["birth_input"]
    except (KeyError, TypeError, ValueError):
        return None
    if type(person) is not int or not isinstance(birth, dict) or not isinstance(row.get("calibrated"), bool):
        return None
    if not PROTOCOL_PUBLISHED <= registered < start <= end < resolved <= today or (end - start).days > 365:
        return None
    outcome = row.get("outcome")
    if outcome == "happened":
        if actual is None or not start <= actual <= end:
            return None
    elif outcome != "did_not" or actual is not None:
        return None
    stage = row.get("career_stage")
    return {**row, "start": start, "end": end, "actual": actual, "registered": registered,
            "resolved": resolved,
            "stage": stage if isinstance(stage, str) and stage in CONTEXT_STAGES[event] else "unspecified"}


def _replay(trial, chart):
    # The engine receives chart inputs, pre-window dates and the event identity.
    # Career context and later outcome fields stay outside the chart rules.
    from ..chat.orchestrator import _precision_analysis
    from .engine import BirthInput, birth_fingerprint, engine
    from .settings import CalcSettings

    raw = chart["birth_input"]
    birth = BirthInput(**{**raw, "settings": CalcSettings(**raw["settings"])})
    profile = SimpleNamespace(calibration_state="calibrated" if chart["calibrated"] else "skipped",
                              calc_fingerprint=birth_fingerprint(birth), calibrations=[], milestones=[],
                              milestone_search_done=False)
    kind = trial["event_type"]
    definition = next(description for _, _, code, description in prediction.EVENTS if code == kind)
    analysis, _ = _precision_analysis(engine.compute(birth), birth, "career", trial["start"], trial["end"], profile,
                                      event={"event_type": kind, "definition": definition},
                                      as_of=trial["start"] - timedelta(days=1))
    decision = analysis["decision"]
    if decision["disposition"] == "event_indicated":
        return tuple(_date(decision["window"][k]) for k in ("start", "end"))
    return None


def _metrics(trials, windows):
    issued = [(row, window) for row, window in zip(trials, windows) if window is not None]
    hits = sum(row["actual"] is not None and window[0] <= row["actual"] <= window[1] for row, window in issued)
    return {"trials": len(trials), "issued": len(issued), "abstained": len(trials) - len(issued),
            "exact_window_hits": hits, "exact_window_misses": len(issued) - hits}


def _benchmark(development, test, chart_windows, shuffled_windows):
    """Compare on the whole registered horizon, with the same rows for each model."""
    if not development or not test:
        return None
    rates = {}
    for row, window in development:
        value = row["actual"] is not None
        issued = window is not None
        for key in [(), (row["stage"],), (issued,), (row["stage"], issued)]:
            rates.setdefault(key, []).append(value)

    def estimate(stage, window=None, chart=False):
        key = (stage, window is not None) if chart else (stage,)
        return mean(rates.get(key) or rates.get((stage,)) or rates[()])

    actual = [row["actual"] is not None for row in test]
    groups = {
        "base_rate": [mean(rates[()])] * len(test),
        "chart_only": [mean(rates.get((w is not None,)) or rates[()]) for w in chart_windows],
        "career_context": [estimate(row["stage"]) for row in test],
        "career_context_plus_chart": [estimate(row["stage"], w, True) for row, w in zip(test, chart_windows)],
    }
    if shuffled_windows is not None:
        groups["career_context_plus_shuffled_chart"] = [
            estimate(row["stage"], w, True) for row, w in zip(test, shuffled_windows)]
    return {key: {"correct": sum((p >= 0.5) == y for p, y in zip(values, actual)),
                  "brier": mean((p - y) ** 2 for p, y in zip(values, actual))}
            for key, values in groups.items()}


def evaluate_career_trials(rows, *, cutoff, holdout_profiles, today=None, seed=4326):
    """Replay one pre-registered trial per person/event and shuffle only holdout charts."""
    if not holdout_profiles:
        raise ValueError("Explicit held-out profile IDs are required.")
    today, cutoff = today or date.today(), _date(cutoff)
    holdout = set(holdout_profiles)
    eligible = [trial for row in rows if (trial := _trial(row, today)) is not None]
    seen, unique = set(), []
    for trial in sorted(eligible, key=lambda row: row["registered"]):
        key = trial["profile_id"], trial["event_type"]
        if key not in seen:
            unique.append(trial)
            seen.add(key)
    reports = {}
    for event in career_events.RULES:
        dev = [r for r in unique if r["event_type"] == event and r["profile_id"] not in holdout and r["resolved"] < cutoff]
        test = sorted((r for r in unique if r["event_type"] == event and r["profile_id"] in holdout
                       and r["registered"] >= cutoff), key=lambda r: r["profile_id"])
        development = [(r, _replay(r, r)) for r in dev]
        actual_windows = [_replay(r, r) for r in test]
        shuffled = None
        if len(test) >= 2:
            order = list(range(len(test)))
            Random(seed).shuffle(order)
            donors = dict(zip(order, order[1:] + order[:1]))
            shuffled = [_replay(r, test[donors[i]]) for i, r in enumerate(test)]
        reports[event] = {
            "development": len(dev), "holdout": len(test),
            "chart": _metrics(test, actual_windows),
            "shuffled_chart": _metrics(test, shuffled) if shuffled is not None else None,
            "same_horizon_comparison": _benchmark(development, test, actual_windows, shuffled),
        }
    return {"protocol": prediction.VERSION, "cutoff": cutoff.isoformat(), "shuffle_seed": seed,
            "eligible_trials": len(eligible), "duplicate_person_events": len(eligible) - len(unique),
            "ineligible_trials": len(rows) - len(eligible), "events": reports}
