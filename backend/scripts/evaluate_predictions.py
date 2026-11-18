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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("dataset")
parser.add_argument("--cutoff", required=True)
parser.add_argument("--holdout-profiles", nargs="+", type=int, required=True)
args = parser.parse_args()
with open(args.dataset) as f:
    data = json.load(f)
rows = data if isinstance(data, list) else data["predictions"]
print(json.dumps(evaluate_dataset(rows, cutoff=args.cutoff, holdout_profiles=args.holdout_profiles), indent=2))
