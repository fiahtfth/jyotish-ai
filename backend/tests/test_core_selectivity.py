"""Selectivity of the core method (astro/core.py): firing rates over random charts.

These are FIRING-RATE checks, not accuracy checks: a method that says 'strong' / 'likely'
for almost every chart and every year carries no information. Target bands live in
core.TUNING["targets"]; the measured rates are recorded in docs/CORE_ENGINE_TUNING.md.

Full measurement (150 charts):
    cd backend && .venv/bin/python -m tests.test_core_selectivity 150
"""
import random
import sys
from datetime import date, timedelta

import pytest

from app.astro import core
from app.astro.engine import BirthInput, engine

SEED = 20261122


def random_births(n: int, seed: int = SEED) -> list:
    """n random births across India, 1960-2005, each with a random 12-month window start (2024-2031)."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        d = date(1960, 1, 1) + timedelta(days=rnd.randrange((date(2005, 12, 31) - date(1960, 1, 1)).days))
        b = BirthInput(name=f"r{i}", year=d.year, month=d.month, day=d.day, hour=rnd.randrange(24),
                       minute=rnd.randrange(60), second=0, lat=round(rnd.uniform(8.0, 32.0), 3),
                       lon=round(rnd.uniform(69.0, 92.0), 3), tz_offset=5.5, place_label="India",
                       birth_time_precision="exact")
        start = date(2024, 1, 1) + timedelta(days=rnd.randrange(8 * 365))
        out.append((b, start))
    return out


def measure(n: int, seed: int = SEED) -> dict:
    """Promise grade shares, future-verdict shares, and the share of days inside 'likely' windows."""
    topics = core.load_topics()
    grades = {"strong": 0, "moderate": 0, "weak": 0}
    verdicts = {"likely": 0, "mixed": 0, "not_indicated": 0}
    conf = {"high": 0, "medium": 0, "low": 0}
    per_topic = {tid: {"strong": 0, "likely": 0, "n": 0} for tid in topics}
    likely_days, likely_lens, range_days, n_timed = 0, [], 0, 0
    for b, start in random_births(n, seed):
        f = engine.compute(b)
        for tid, t in topics.items():
            g = core.promise(f, tid)["grade"]
            grades[g] += 1
            per_topic[tid]["n"] += 1
            per_topic[tid]["strong"] += g == "strong"
            if not t["timing"]:
                continue
            c = core.answer(f, b, tid, start=start, end=start + timedelta(days=365), today=start)
            n_timed += 1
            verdicts[c.verdict] += 1
            conf[c.confidence] += 1
            range_days += 365
            if c.verdict == "likely":
                per_topic[tid]["likely"] += 1
                w = (date.fromisoformat(c.window["end"]) - date.fromisoformat(c.window["start"])).days
                likely_days += w
                likely_lens.append(w)
    n_pairs = sum(grades.values())
    return {
        "charts": n,
        "promise": {k: round(v / n_pairs, 3) for k, v in grades.items()},
        "verdict": {k: round(v / n_timed, 3) for k, v in verdicts.items()},
        "confidence": {k: round(v / n_timed, 3) for k, v in conf.items()},
        "likely_day_share": round(likely_days / range_days, 3),
        "likely_window_days_mean": round(sum(likely_lens) / len(likely_lens), 1) if likely_lens else 0.0,
        "likely_window_days_max": max(likely_lens) if likely_lens else 0,
        "per_topic": {tid: {"strong": round(v["strong"] / v["n"], 2),
                            "likely": round(v["likely"] / v["n"], 2) if topics[tid]["timing"] else None}
                      for tid, v in per_topic.items()},
    }


@pytest.fixture(scope="module")
def rates():
    return measure(40)


def test_promise_grade_bands(rates):
    tg = core.TUNING["targets"]
    assert rates["promise"]["strong"] <= tg["promise_strong_max"], rates["promise"]
    assert rates["promise"]["weak"] >= tg["promise_weak_min"], rates["promise"]
    assert rates["promise"]["moderate"] > 0.2, rates["promise"]


def test_likely_rate_bands(rates):
    tg = core.TUNING["targets"]
    assert 0 < rates["verdict"]["likely"] <= tg["likely_max"], rates["verdict"]
    # no single topic says 'likely' for most charts
    assert all(v["likely"] is None or v["likely"] <= tg["likely_topic_max"] for v in rates["per_topic"].values()), \
        rates["per_topic"]
    assert rates["verdict"]["not_indicated"] >= 0.25, rates["verdict"]


def test_likely_windows_are_narrow(rates):
    tg = core.TUNING["targets"]
    assert rates["likely_day_share"] <= tg["likely_day_share_max"], rates
    assert rates["likely_window_days_mean"] <= tg["likely_window_days_mean_max"], rates


def test_high_confidence_is_rare(rates):
    assert rates["confidence"]["high"] <= core.TUNING["targets"]["confidence_high_max"], rates["confidence"]


if __name__ == "__main__":   # full measurement for docs/CORE_ENGINE_TUNING.md
    import json
    import time
    t0 = time.time()
    out = measure(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
    out["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(out, indent=1))
