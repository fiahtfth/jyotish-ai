"""Run the live timing rules against seeded, synthetic chart/window pairs."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from functools import partial
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.astro import prediction, registry
from app.astro.engine import BirthInput, birth_fingerprint, engine
from app.chat.orchestrator import _precision_analysis

PLACES = [(25.39, 82.57, 5.5, "Bhadohi"), (13.08, 80.27, 5.5, "Chennai"),
          (28.61, 77.21, 5.5, "New Delhi"), (22.57, 88.36, 5.5, "Kolkata")]


def trial(number, *, seed, domain, event):
    rnd = random.Random(f"{seed}:{number}")
    lat, lon, offset, label = rnd.choice(PLACES)
    born = date(1950, 1, 1) + timedelta(days=rnd.randrange(365 * 54))
    birth = BirthInput("Synthetic", born.year, born.month, born.day, rnd.randrange(24),
                       rnd.randrange(60), rnd.randrange(60), lat, lon, offset, label)
    month = rnd.randrange(1, 13)
    start = date(rnd.randrange(2028, 2059), month, 1)
    end = date(start.year + 1, month, 1) - timedelta(days=1)
    profile = SimpleNamespace(calibration_state="calibrated", calc_fingerprint=birth_fingerprint(birth),
                              calibrations=[], milestones=[], milestone_search_done=False)
    facts = engine.compute(birth)
    analysis, _ = _precision_analysis(facts, birth, domain, start, end, profile,
                                      event=event, as_of=start - timedelta(days=1))
    issued = analysis["decision"]["disposition"] == "event_indicated"
    covered = set()
    if issued:
        for interval in analysis["precision"]["timing_windows"]:
            lo = max(start, date.fromisoformat(interval["start"]))
            hi = min(end, date.fromisoformat(interval["end"]))
            covered.update(lo + timedelta(days=k) for k in range((hi - lo).days + 1))
    return issued, len(covered) / ((end - start).days + 1), analysis["unavailable_count"] > 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=[row[2] for row in prediction.EVENTS])
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=4326)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.workers < 1:
        parser.error("samples and workers must be positive")
    domain, _, code, definition = next(row for row in prediction.EVENTS if row[2] == args.event)
    run = partial(trial, seed=args.seed, domain=domain, event={"event_type": code, "definition": definition})
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(run, range(args.samples)))
    else:
        rows = [run(i) for i in range(args.samples)]
    contract = registry.forecast_intent(code)
    result = {"intent": contract["intent_id"] if contract else code, "intent_version": contract["version"] if contract else None,
              "protocol": prediction.VERSION, "seed": args.seed, "chart_windows": len(rows),
              "status": "evaluated" if len(rows) >= 1000 else "smoke_only",
              "supportive_chart_rate": sum(issued for issued, _, _ in rows) / len(rows),
              "mean_supportive_window_share": sum(share for _, share, _ in rows) / len(rows),
              "unavailable_chart_windows": sum(unavailable for _, _, unavailable in rows),
              "scope": "Synthetic chart-window frequency. The share covers qualified micro-timing days within issued windows."}
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
