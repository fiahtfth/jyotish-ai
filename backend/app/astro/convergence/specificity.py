"""Specificity gate (spec §1.6): each timing intent must release the
supportive_period rule on no more than a share of random charts x random
12-month windows — a method that fires for every chart and every month tells
the client nothing.

CLI:
    python -m app.astro.convergence.specificity --charts 200 --seed 7 \
        --out ../data/specificity_report.json
The release run uses --charts 1000; smaller runs are marked "bounded".
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from ..engine import BirthInput, engine
from . import intents
from .runner import timing_run
from .types import SUPPORTIVE_PERIOD, TIMING_TEMPLATES

GATE_LIMIT = 0.25
RELEASE_CHARTS = 1000


def random_birth(rng: random.Random) -> BirthInput:
    year = rng.randint(1958, 2002)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    lat = round(rng.uniform(8, 37), 3)
    lon = round(rng.uniform(68, 97), 3)
    return BirthInput(name="specificity", year=year, month=month, day=day,
                      hour=rng.randint(0, 23), minute=rng.randint(0, 59), second=0,
                      lat=lat, lon=lon, tz_offset=5.5, place_label="IN")


def run_gate(cfgs, charts: int, seed: int) -> dict:
    rng = random.Random(seed)
    births = [random_birth(rng) for _ in range(charts)]
    rows = {}
    for cfg in sorted(cfgs, key=lambda c: c.number):
        hits, evaluated = 0, 0
        for i, birth in enumerate(births):
            start = date(2024 + (i % 3), rng.randint(1, 12), 1)
            end = start + timedelta(days=365)
            try:
                facts = engine.compute(birth)
                run = timing_run(facts, birth, cfg, start, end)
            except Exception:
                continue
            evaluated += 1
            hits += run.result.result_type == SUPPORTIVE_PERIOD
        rate = hits / evaluated if evaluated else None
        rows[cfg.intent_id] = {
            "number": cfg.number, "charts": evaluated, "supportive": hits,
            "rate": round(rate, 4) if rate is not None else None,
            "gate": ("pass" if rate is not None and rate <= GATE_LIMIT
                     else "fail" if rate is not None else "no_data"),
        }
    return {"charts_per_intent": charts, "seed": seed, "gate_limit": GATE_LIMIT,
            "status": "release" if charts >= RELEASE_CHARTS else "bounded",
            "intents": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description="specificity gate for timing intents")
    ap.add_argument("--charts", type=int, default=60,
                    help="random charts per intent (release gate: 1000)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--intents", type=str, default="",
                    help="comma-separated intent numbers to limit the run")
    ap.add_argument("--out", type=str, default="",
                    help="write the report to this path (default data/specificity_report.json)")
    args = ap.parse_args(argv)
    cfgs = [c for c in intents.load_all().values() if c.template in TIMING_TEMPLATES]
    if args.intents:
        wanted = {int(x) for x in args.intents.split(",")}
        cfgs = [c for c in cfgs if c.number in wanted]
    report = run_gate(cfgs, args.charts, args.seed)
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "data" / "specificity_report.json")
    out.write_text(json.dumps(report, indent=2))
    failed = [k for k, v in report["intents"].items() if v["gate"] == "fail"]
    print(f"charts={args.charts} intents={len(cfgs)} status={report['status']}")
    print(f"gate failures: {len(failed)} {failed[:10]}")
    for k, v in sorted(report["intents"].items(), key=lambda kv: -(kv[1]['rate'] or 0)):
        print(f"  {v['rate']} {k}" if v['rate'] is not None else f"  n/a {k}")


if __name__ == "__main__":
    main()
