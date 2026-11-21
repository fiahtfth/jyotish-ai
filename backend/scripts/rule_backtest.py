"""Usage: python backend/scripts/rule_backtest.py [--min-samples 30] [--permutations 2000] [--out DIR]

Reads recorded outcomes from the app database (JYOTISH_DATABASE_URL), runs the
per-rule / per-pillar backtest against base rates and a shuffled-chart null,
and writes backend/data/backtest_report.{json,md}. Aggregate output only.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.astro import backtest
from app.db import SessionLocal, init_db

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--min-samples", type=int, default=backtest.MIN_SAMPLES)
parser.add_argument("--permutations", type=int, default=backtest.N_PERMUTATIONS)
parser.add_argument("--out", default=None)
args = parser.parse_args()
init_db()
with SessionLocal() as db:
    rows, excluded = backtest.rows_from_db(db)
report = backtest.build_report(rows, min_samples=args.min_samples, permutations=args.permutations, exclusions=excluded)
j, m = backtest.write_report(report, args.out)
print(f"{report['status']}: {report['data']['scored']} scored outcomes -> {j}, {m}")
