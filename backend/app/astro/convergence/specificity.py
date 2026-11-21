"""Specificity gate runner (spec 1.6): how often does a TIMING intent fire on random charts?

    python -m app.astro.convergence.specificity --charts 100 [--intent JOB_TIMING] [--phase 1]

For each random chart (seeded) and a random 12-month window, template T is run and we record
whether ANY window is `supportive_period` and the share of days marked supportive. Release
rule (configurable): supportive on <= 25% of random chart-windows. Results are written to
backend/data/specificity_report.json (read by registry.coverage()). With fewer than 1000
chart-windows the gate status is "provisional".
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..engine import BirthInput, engine
from . import intents, rulepack
from .template_t import template_T
from .types import PILLAR_NAMES, SUPPORTIVE_PERIOD

REPORT = Path(__file__).resolve().parents[3] / "data" / "specificity_report.json"
GATE = 0.25
MIN_RELEASE_WINDOWS = 1000
VERSION = "specificity-v1"


def random_birth(rng: random.Random) -> BirthInput:
    y = rng.randint(1950, 2004)
    return BirthInput(name="random", year=y, month=rng.randint(1, 12), day=rng.randint(1, 28),
                      hour=rng.randint(0, 23), minute=rng.randint(0, 59), second=0,
                      lat=round(rng.uniform(8.0, 32.0), 4), lon=round(rng.uniform(68.0, 92.0), 4),
                      tz_offset=5.5, place_label="random", birth_time_precision="exact")


def random_window(rng: random.Random, birth: BirthInput) -> tuple:
    lo = max(date(birth.year + 18, 1, 1), date(1990, 1, 1))
    hi = min(date(birth.year + 60, 1, 1), date(2034, 1, 1))
    if hi <= lo:
        lo, hi = date(2020, 1, 1), date(2030, 1, 1)
    start = lo + timedelta(days=rng.randint(0, (hi - lo).days))
    return start, start + timedelta(days=364)


def _empty():
    return {"chart_windows": 0, "supportive": 0, "mixed": 0, "share_sum": 0.0, "errors": 0}


def run(n_charts: int, intent_ids: list, seed: int = 20261121, p3_rate: float = 1.0, p4: bool = True,
        gate: float = GATE, progress: bool = False) -> dict:
    rng = random.Random(seed)
    cfgs = [intents.get(i) for i in intent_ids]
    stats = {c.intent_id: _empty() for c in cfgs}
    t0 = time.time()
    for i in range(n_charts):
        birth = random_birth(rng)
        start, end = random_window(rng, birth)
        use_p3 = rng.random() < p3_rate
        pillars = tuple(p for p in PILLAR_NAMES if (p != "P3" or use_p3) and (p != "P4" or p4))
        facts = engine.compute(birth)
        days = (end - start).days + 1
        for c in cfgs:
            st = stats[c.intent_id]
            try:
                out = template_T(facts, birth, c, start, end, pillars=pillars, with_kp=False, use_cache=False)
            except Exception:
                st["errors"] += 1
                continue
            st["chart_windows"] += 1
            sup = [w for w in out.windows if w.result.result_type == SUPPORTIVE_PERIOD]
            st["supportive"] += bool(sup)
            st["mixed"] += any(w.result.result_type == "mixed_period" for w in out.windows)
            st["share_sum"] += sum((w.segment[1] - w.segment[0]).days + 1 for w in sup) / days
        if progress and (i + 1) % 25 == 0:
            print(f"{i + 1}/{n_charts} charts, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    out = {}
    for iid, st in stats.items():
        cw = st["chart_windows"]
        rate = round(st["supportive"] / cw, 4) if cw else None
        passed = rate is not None and rate <= gate
        status = ("pass" if passed else "fail") if cw >= MIN_RELEASE_WINDOWS else \
            ("provisional_pass" if passed else "provisional_fail")
        out[iid] = {"status": status, "chart_windows": cw, "supportive_chart_rate": rate,
                    "mixed_chart_rate": round(st["mixed"] / cw, 4) if cw else None,
                    "mean_supportive_window_share": round(st["share_sum"] / cw, 4) if cw else None,
                    "errors": st["errors"], "gate": gate,
                    "present_as": "timing" if passed else "theme (fails the specificity gate)"}
    return {"version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rulepack_hash": rulepack.pack_hash(),
            "protocol": {"charts": n_charts, "seed": seed, "window_days": 365, "p3_sample_rate": p3_rate,
                         "pillars": [p for p in PILLAR_NAMES if p != "P4" or p4], "kp": "excluded (never in n)",
                         "birth_years": [1950, 2004], "region": "India-like lat 8-32, lon 68-92, UTC+5:30",
                         "gate": f"supportive_period on <= {int(gate * 100)}% of random chart-windows",
                         "release_minimum_chart_windows": MIN_RELEASE_WINDOWS,
                         "metric": "supportive_chart_rate = share of chart-windows with any supportive_period; "
                                   "mean_supportive_window_share = mean share of days marked supportive"},
            "intents": out}


def timing_intents(phase: int | None = None) -> list:
    return [c.intent_id for _, c in sorted(intents.load_all().items())
            if c.is_timing and (phase is None or c.phase == phase)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--charts", type=int, default=100)
    ap.add_argument("--intent", action="append", help="intent id (repeatable); default: timing intents")
    ap.add_argument("--phase", type=int, default=None, help="restrict default intents to a phase")
    ap.add_argument("--seed", type=int, default=20261121)
    ap.add_argument("--p3-rate", type=float, default=1.0, help="fraction of charts that run P3")
    ap.add_argument("--no-p4", action="store_true")
    ap.add_argument("--gate", type=float, default=GATE)
    ap.add_argument("--out", type=Path, default=REPORT)
    a = ap.parse_args(argv)
    ids = a.intent or timing_intents(a.phase)
    rep = run(a.charts, ids, a.seed, a.p3_rate, not a.no_p4, a.gate, progress=True)
    old = {}
    if a.out.exists():
        try:
            old = json.loads(a.out.read_text(encoding="utf-8")).get("intents", {})
        except ValueError:
            old = {}
    rep["intents"] = {**old, **rep["intents"]}
    a.out.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    for iid, r in rep["intents"].items():
        print(f"{iid:24s} {r['status']:18s} supportive {r['supportive_chart_rate']}  share {r['mean_supportive_window_share']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
