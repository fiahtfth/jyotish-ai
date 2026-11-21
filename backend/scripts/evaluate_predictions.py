"""Usage: python backend/scripts/evaluate_predictions.py export.json --cutoff 2027-01-01 --holdout-profiles 12 18

Input is an account export or a JSON array of prediction rows. Output contains
aggregate metrics only. Never commit exports containing personal data.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.astro.validation import evaluate_dataset
from app.astro.career_validation import evaluate_career_trials

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dataset")
parser.add_argument("--cutoff", required=True)
parser.add_argument("--holdout-profiles", nargs="+", type=int, required=True)
parser.add_argument("--career-trials", action="store_true", help="evaluate a consented, pre-registered career cohort")
parser.add_argument("--shuffle-seed", type=int, default=4326)
args = parser.parse_args()
with open(args.dataset) as f:
    data = json.load(f)
options = {"cutoff": args.cutoff, "holdout_profiles": args.holdout_profiles}
if args.career_trials:
    rows = data if isinstance(data, list) else data["career_trials"]
    result = evaluate_career_trials(rows, seed=args.shuffle_seed, **options)
else:
    rows = data if isinstance(data, list) else data["predictions"]
    result = evaluate_dataset(rows, **options)
print(json.dumps(result, indent=2))
