"""Golden-chart comparison against recorded reference fixtures.

Fixtures live in tests/golden/*.json (schema in tests/golden/README.md).
With no fixtures the test is skipped, not passed.
"""
import glob
import json
import os
import sys
import uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_golden.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.astro.engine import BirthInput, engine
from app.astro.settings import CalcSettings

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
FIXTURES = sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json")))

PLANET_TOL_ARCSEC = 1.0
LAGNA_TOL_ARCSEC = 2.0
DASHA_TOL_DAYS = 1


def _arc_diff(a: float, b: float) -> float:
    d = abs(a - b) % (360 * 3600)
    return min(d, 360 * 3600 - d)


def _birth(fx: dict) -> BirthInput:
    i = fx["input"]
    y, mo, d = (int(x) for x in i["date"].split("-"))
    h, mi, s = (int(x) for x in i["time"].split(":"))
    cs = CalcSettings(**fx["settings"].get("engine", {}))
    return BirthInput(fx.get("name", "golden"), y, mo, d, h, mi, s, i["lat"], i["lon"],
                      i["tz_offset"], i.get("place", "golden"), settings=cs)


@pytest.mark.skipif(not FIXTURES, reason="no golden fixtures in tests/golden/*.json")
@pytest.mark.parametrize("path", FIXTURES, ids=[os.path.basename(p) for p in FIXTURES])
def test_golden_chart(path):
    with open(path) as fh:
        fx = json.load(fh)
    for key in ("source_program", "version", "settings", "input", "expected"):
        assert key in fx, f"fixture missing {key}"
    facts = engine.compute(_birth(fx))
    exp = fx["expected"]

    for name, arcsec in exp.get("planets_arcsec", {}).items():
        got = facts["planets"][name]["abs_longitude"] * 3600
        assert _arc_diff(got, arcsec) <= PLANET_TOL_ARCSEC, f"{name}: {got:.2f}\" vs {arcsec}\""

    if "lagna_arcsec" in exp:
        got = (facts["lagna"]["sign"] * 30 + facts["lagna"]["degree"]) * 3600
        assert _arc_diff(got, exp["lagna_arcsec"]) <= LAGNA_TOL_ARCSEC

    for chart, bodies in exp.get("vargas", {}).items():
        for body, sign in bodies.items():
            assert facts["vargas"][chart][body]["sign"] == sign, f"{chart} {body}"

    rows = {(p["maha"], p["antar"]): p["start"] for p in facts["vimshottari"]["periods"]}
    for row in exp.get("dasha", []):
        got = rows[(row["maha"], row["antar"])]
        delta = abs((date.fromisoformat(got) - date.fromisoformat(row["start"])).days)
        assert delta <= DASHA_TOL_DAYS, f"{row['maha']}/{row['antar']}: {got} vs {row['start']}"


def test_fixture_labels_are_honest():
    """A fixture produced by this engine must say so."""
    for path in FIXTURES:
        with open(path) as fh:
            fx = json.load(fh)
        if "self" in fx["source_program"].lower():
            assert fx["source_program"] == "self-snapshot (NOT an external reference)"
