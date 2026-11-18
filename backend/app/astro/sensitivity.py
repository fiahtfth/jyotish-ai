"""Finite birth-time perturbation checks; stability is not an accuracy claim."""
from dataclasses import replace
from datetime import datetime, timedelta

from . import pillars, precision, stability
from .constants import DOMAINS
from .engine import engine

OFFSETS = {"exact": (-2, 0, 2), "approximate": (-60, -30, 0, 30, 60),
           "unknown": (-120, -60, 0, 60, 120)}


def evaluate(facts, birth, domain, start, end, calibrated, base=None):
    samples, errors = [], []
    stamp = datetime(birth.year, birth.month, birth.day, birth.hour, birth.minute, birth.second)
    for offset in OFFSETS[birth.birth_time_precision]:
        try:
            shifted = stamp + timedelta(minutes=offset)
            candidate = replace(birth, year=shifted.year, month=shifted.month, day=shifted.day,
                                hour=shifted.hour, minute=shifted.minute, second=shifted.second)
            f = facts if offset == 0 else engine.compute(candidate)
            core = base["verdict"] if offset == 0 and base else pillars.evaluate(f, candidate, domain, start, end)
            timing = base["timing"] if offset == 0 and base else precision.timing_windows(f, candidate, domain, start, end, calibrated)
            if core["unavailable_count"] or timing.get("status") == "unavailable":
                raise ValueError("a sampled layer is unavailable")
            samples.append({"offset_minutes": offset, "lagna": f["lagna"]["sign_name"],
                            "pillars": core["pillars"],
                            "windows": [{"start": w["start"], "end": w["end"]} for w in timing["windows"]]})
        except Exception as exc:
            errors.append({"offset_minutes": offset, "reason": f"{type(exc).__name__}: {exc}"})
    complete = not errors and len(samples) == len(OFFSETS[birth.birth_time_precision])
    verdict_stable = complete and all(s["pillars"] == samples[0]["pillars"] for s in samples)
    timing_stable = complete and all(s["windows"] == samples[0]["windows"] for s in samples)
    # exact sign-change windows (seconds), not just the sampled offsets
    try:
        wanted = ("D1", DOMAINS[domain]["varga"], "D9")
        windows = stability.lagna_windows(birth, vargas=tuple(dict.fromkeys(wanted)))
    except Exception as exc:
        windows = {"error": f"{type(exc).__name__}: {exc}"}
    return {"stability_windows": windows, "status": "sampled_stable" if verdict_stable and timing_stable else ("sensitive" if complete else "incomplete"),
            "assumed_precision": birth.birth_time_precision, "tested_offsets_minutes": list(OFFSETS[birth.birth_time_precision]),
            "verdict_stable": verdict_stable, "timing_stable": timing_stable,
            "samples": samples, "errors": errors,
            "note": "A finite sensitivity check, not proof of birth-time accuracy or predictive validity."}
