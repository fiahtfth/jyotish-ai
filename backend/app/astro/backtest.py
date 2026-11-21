"""Outcome backtest: do the pre-registered rules beat the base rate and a shuffled-chart null?

Input is the immutable pre-registration payload of each prediction (see
preregistration.py) joined to the user-reported outcome. Nothing is fitted:
this only measures. For every rule ID and every pillar it reports

* hit rate when the rule fired, vs the base rate of the same event type and
  window length (stratum), and the lift (= hit rate / expected base rate);
* a shuffled-chart null: outcomes are permuted across charts within each
  (event type, window length) stratum, keeping every chart's fired rules
  fixed; the two-sided permutation p-value says whether the rule's hit rate
  differs from what randomly paired outcomes give (Bonferroni-adjusted over
  all tested features);
* below MIN_SAMPLES scored outcomes nothing is evaluated: "insufficient data".

Also: a reliability table by convergence n/4 and leave-one-out Brier scores of
"hit rate of this convergence level" vs the constant base rate. The engine
emits no probabilities; these figures are for the owner, never shown to users
until validated (docs/CALCULATION_VALIDATION.md).

Rule weighting hook: rule_weights() turns a report into per-rule multipliers
(1.0 unless sufficient data and significant lift). It is NOT applied to
scoring. Applying it would change the verdict thresholds in
pillars.pillar_*() (the `supports`/`conflicts` tallies), which is not a small
localized change, so config.USE_BACKTEST_WEIGHTS (default False) only gates
active_rule_weights(); the place to apply it is where each pillar increments
`supports`/`conflicts` for a triggered rule: add `rule_weight(rule_key)` instead
of 1.
"""
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

MIN_SAMPLES = 30
N_PERMUTATIONS = 2000
SEED = 20261121
ALPHA = 0.05
WEIGHT_CLAMP = (0.5, 1.5)
HITS = {"happened"}
MISSES = {"partly", "did_not", "outside_window"}   # partial/outside-window are never hits
_BUCKETS = ((31, "<=1m"), (93, "<=3m"), (186, "<=6m"), (10 ** 9, ">6m"))
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REPORT_JSON = DATA_DIR / "backtest_report.json"
REPORT_MD = DATA_DIR / "backtest_report.md"


def window_bucket(days: int) -> str:
    return next(label for limit, label in _BUCKETS if days <= limit)


def wilson(hits: int, n: int, z: float = 1.96):
    if not n:
        return None
    p, d = hits / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


# ------------------------------------------------------------------ data

def rows_from_db(db):
    """Scored rows from immutable registrations; returns (rows, exclusions)."""
    from ..db import PredictionRecord
    from . import preregistration
    ex = defaultdict(int)
    seen, rows = set(), []
    for rec in db.query(PredictionRecord).order_by(PredictionRecord.id).all():
        if rec.outcome is None or rec.forecast != "event_indicated":
            continue
        if rec.outcome not in HITS | MISSES:
            ex["unsure"] += 1
            continue
        reg = rec.registration
        if reg is None:
            ex["legacy_no_registration"] += 1
            continue
        if not preregistration.verify(reg, rec):
            ex["registration_mismatch"] += 1
            continue
        p = json.loads(reg.payload_json)
        w = p["window"]
        # Dedup identity is the payload minus its timestamp: exact
        # re-registrations of one prediction collapse, but different
        # questions sharing event_type+window are scored separately.
        ident = {k: v for k, v in p.items() if k != "registered_at"}
        key = (rec.profile_id, preregistration.sha256(ident))
        if key in seen:                       # repeated forecasts are scored once (earliest)
            ex["duplicate"] += 1
            continue
        seen.add(key)
        rows.append({
            "id": rec.id, "profile_id": rec.profile_id, "outcome": rec.outcome,
            "event_type": (p.get("event") or {}).get("event_type") or "unknown",
            "window_days": (date.fromisoformat(w["end"]) - date.fromisoformat(w["start"])).days + 1,
            "n_support": (p.get("convergence") or {}).get("n_of_4"),
            "pillars": {n: v.get("verdict") for n, v in (p.get("rules_fired") or {}).items()},
            "rules": sorted({r for v in (p.get("rules_fired") or {}).values() for r in v.get("fired", [])}),
        })
    return rows, dict(ex)


def _features(row) -> set:
    f = {f"pillar:{n}" for n, v in (row.get("pillars") or {}).items() if v == "support"}
    f |= {f"rule:{r}" for r in row.get("rules") or []}
    return f


# ------------------------------------------------------------------ math

def _cell(row):
    return (row["event_type"], window_bucket(int(row["window_days"])))


def build_report(rows, *, min_samples=MIN_SAMPLES, permutations=N_PERMUTATIONS, seed=SEED,
                 exclusions=None, now=None) -> dict:
    rows = [r for r in rows if r.get("outcome") in HITS | MISSES]
    n = len(rows)
    y = np.array([int(r["outcome"] in HITS) for r in rows], dtype=float)
    cells = [_cell(r) for r in rows]
    by_cell = defaultdict(list)
    for i, c in enumerate(cells):
        by_cell[c].append(i)
    cell_rate = {c: float(y[idx].mean()) for c, idx in by_cell.items()}
    expected = np.array([cell_rate[c] for c in cells]) if n else np.array([])
    report = {
        "schema": 1, "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {"min_samples": min_samples, "permutations": permutations, "seed": seed, "alpha": ALPHA,
                   "window_buckets": [b for _, b in _BUCKETS],
                   "hit": sorted(HITS), "miss": sorted(MISSES),
                   "null": "outcomes permuted across charts within event type x window length"},
        "data": {"scored": n, "hits": int(y.sum()), "excluded": exclusions or {}},
        "base_rates": [{"event_type": c[0], "window": c[1], "n": len(idx), "hits": int(y[idx].sum()),
                        "base_rate": round(cell_rate[c], 4),
                        "status": "evaluated" if len(idx) >= min_samples else "insufficient data"}
                       for c, idx in sorted(by_cell.items())],
        "pillars": {}, "rules": {}, "convergence": {},
        "notice": "Owner-only diagnostics on self-reported outcomes. Not probabilities; never shown to users "
                  "until validated on an untouched holdout.",
    }
    if n < min_samples:
        report["status"] = "insufficient data"
        report["reason"] = f"{n} scored outcomes; at least {min_samples} are required."
        report["convergence"] = {"reliability": _reliability(rows, y, min_samples), "brier": None}
        return report
    report["status"] = "evaluated"

    rng = np.random.default_rng(seed)
    perm = np.empty((permutations, n))
    for idx in by_cell.values():
        idx = np.array(idx)
        perm[:, idx] = rng.permuted(np.tile(y[idx], (permutations, 1)), axis=1)

    feats = [_features(r) for r in rows]
    names = sorted(set().union(*feats)) if feats else []
    for name in names:
        mask = np.array([name in f for f in feats])
        k = int(mask.sum())
        entry = {"n": k, "hits": int(y[mask].sum())}
        if k < min_samples:
            entry.update(status="insufficient data", reason=f"{k} outcomes where this fired; need {min_samples}.")
        else:
            obs, exp = float(y[mask].mean()), float(expected[mask].mean())
            null = perm[:, mask].mean(axis=1)
            nm = float(null.mean())
            p = (1 + int((np.abs(null - nm) >= abs(obs - nm) - 1e-12).sum())) / (permutations + 1)
            cells_out = []
            for c, idx in sorted(by_cell.items()):
                m = mask[idx]
                if m.any():
                    kk = int(m.sum())
                    hh = int(y[idx][m].sum())
                    cells_out.append({"event_type": c[0], "window": c[1], "n": kk, "hits": hh,
                                      "hit_rate": round(hh / kk, 4), "base_rate": round(cell_rate[c], 4),
                                      "status": "evaluated" if kk >= min_samples else "insufficient data"})
            entry.update(status="evaluated", hit_rate=round(obs, 4), base_rate=round(exp, 4),
                         lift=round(obs / exp, 4) if exp > 0 else None, wilson95=wilson(entry["hits"], k),
                         null_hit_rate=round(nm, 4), null_p95=round(float(np.quantile(null, 0.95)), 4),
                         p_value=round(p, 5), by_cell=cells_out)
        report["pillars" if name.startswith("pillar:") else "rules"][name.split(":", 1)[1]] = entry
    evaluated = [e for sect in ("pillars", "rules") for e in report[sect].values() if e["status"] == "evaluated"]
    for e in evaluated:      # Bonferroni across every feature actually tested
        e["p_adjusted"] = round(min(1.0, e["p_value"] * len(evaluated)), 5)
        e["significant"] = e["p_adjusted"] < ALPHA
    report["convergence"] = {"reliability": _reliability(rows, y, min_samples), "brier": _brier(rows, y)}
    return report


def _reliability(rows, y, min_samples):
    out = []
    n = len(rows)
    base = float(y.mean()) if n else None
    for level in range(5):
        idx = [i for i, r in enumerate(rows) if r.get("n_support") == level]
        if not idx:
            continue
        h = int(y[idx].sum())
        ok = len(idx) >= min_samples
        out.append({"convergence": f"{level}/4", "n": len(idx), "hits": h,
                    "status": "evaluated" if ok else "insufficient data",
                    **({"hit_rate": round(h / len(idx), 4), "wilson95": wilson(h, len(idx)),
                        "base_rate": round(base, 4)} if ok else {})})
    return out


def _brier(rows, y):
    """Leave-one-out: predict each outcome with the hit rate of its convergence level (excluding itself)
    vs the overall hit rate (excluding itself)."""
    n = len(rows)
    levels = [r.get("n_support") for r in rows]
    tot, hits = n, y.sum()
    cnt, sm = defaultdict(int), defaultdict(float)
    for lv, v in zip(levels, y):
        cnt[lv] += 1
        sm[lv] += v
    model = baseline = 0.0
    for lv, v in zip(levels, y):
        pb = (hits - v) / (tot - 1)
        pm = (sm[lv] - v) / (cnt[lv] - 1) if cnt[lv] > 1 else pb
        model += (pm - v) ** 2
        baseline += (pb - v) ** 2
    model, baseline = model / n, baseline / n
    return {"method": "leave-one-out", "n": n, "level_brier": round(model, 5), "base_rate_brier": round(baseline, 5),
            "skill": round(1 - model / baseline, 4) if baseline > 0 else None}


# ------------------------------------------------------------------ output

def to_markdown(report: dict) -> str:
    L = [f"# Rule backtest report", "", f"Generated {report['generated_at']} · status: **{report['status']}**", "",
         report["notice"], "",
         f"Scored outcomes: {report['data']['scored']} (hits {report['data']['hits']}); "
         f"excluded: {report['data']['excluded'] or 'none'}. Minimum per estimate: {report['config']['min_samples']}.", ""]
    if report["status"] != "evaluated":
        L += [f"**Insufficient data.** {report['reason']}", ""]
    L += ["## Base rates (event type x window length)", "", "| Event | Window | n | Hits | Base rate | Status |", "|---|---|---|---|---|---|"]
    L += [f"| {b['event_type']} | {b['window']} | {b['n']} | {b['hits']} | {b['base_rate']} | {b['status']} |"
          for b in report["base_rates"]]
    for title, sect in (("Pillars", "pillars"), ("Rules", "rules")):
        L += ["", f"## {title}", "", "| ID | n | Hit rate | Base rate | Lift | Null | p (adj) | Status |", "|---|---|---|---|---|---|---|---|"]
        for k, e in sorted(report[sect].items()):
            if e["status"] == "evaluated":
                L.append(f"| {k} | {e['n']} | {e['hit_rate']} | {e['base_rate']} | {e['lift']} | {e['null_hit_rate']} | "
                         f"{e['p_adjusted']}{' *' if e['significant'] else ''} | evaluated |")
            else:
                L.append(f"| {k} | {e['n']} | - | - | - | - | - | insufficient data |")
    L += ["", "## Reliability by convergence", "", "| Level | n | Hit rate | 95% CI | Base rate | Status |", "|---|---|---|---|---|---|"]
    for r in report["convergence"].get("reliability", []):
        L.append(f"| {r['convergence']} | {r['n']} | {r.get('hit_rate', '-')} | {r.get('wilson95', '-')} | "
                 f"{r.get('base_rate', '-')} | {r['status']} |")
    b = report["convergence"].get("brier")
    L += ["", "Brier (leave-one-out): " + (f"level {b['level_brier']} vs base-rate {b['base_rate_brier']} "
                                           f"(skill {b['skill']})" if b else "insufficient data"), ""]
    return "\n".join(L)


def write_report(report: dict, directory=None) -> tuple:
    d = Path(directory) if directory else DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    j, m = d / "backtest_report.json", d / "backtest_report.md"
    j.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    m.write_text(to_markdown(report), encoding="utf-8")
    return j, m


def load_report(path=None):
    p = Path(path) if path else REPORT_JSON
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ weighting hook

def rule_weights(report: dict | None = None, path=None) -> dict:
    """Per-rule multipliers from the latest report. 1.0 unless the rule has
    sufficient data AND a Bonferroni-adjusted significant lift vs the shuffled
    null; then the lift, clamped to WEIGHT_CLAMP. Not applied to scoring."""
    report = report if report is not None else load_report(path)
    if not report:
        return {}
    out = {}
    for rid, e in (report.get("rules") or {}).items():
        w = 1.0
        if (e.get("status") == "evaluated" and e.get("n", 0) >= report["config"]["min_samples"]
                and e.get("significant") and e.get("lift")):
            w = min(WEIGHT_CLAMP[1], max(WEIGHT_CLAMP[0], float(e["lift"])))
        out[rid] = round(w, 4)
    return out


def active_rule_weights(path=None) -> dict:
    """What scoring may consume: empty (all 1.0) unless USE_BACKTEST_WEIGHTS is on."""
    from ..config import settings
    return rule_weights(path=path) if settings.USE_BACKTEST_WEIGHTS else {}


def rule_weight(rule_id: str, weights: dict | None = None) -> float:
    return (active_rule_weights() if weights is None else weights).get(rule_id, 1.0)
