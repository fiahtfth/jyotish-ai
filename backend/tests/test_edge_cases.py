"""Edge & property tests: dasha totality, varga validity, ephemeris disclosure,
sign boundaries, southern hemisphere."""
import os, sys, uuid

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_edge.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import swisseph as swe

from app.astro import engine as E
from app.astro.engine import BirthInput, engine
from app.astro.settings import CalcSettings


def birth(**kw):
    return BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi",
                      settings=CalcSettings(**kw))


def test_vimshottari_totality_120_years_and_contiguous():
    """Mahadasha coverage from birth = exactly 120 dasha-years, no gaps/overlaps."""
    for mode in ("true_tropical", "savana_360"):
        f = engine.compute(birth(dasha_year=mode))
        md = f["vimshottari"]["periods"]
        # group consecutive antardashas by maha lord
        mahas, cur = [], None
        for p in md:
            if cur is None or p["maha"] != cur["maha"]:
                if cur:
                    mahas.append(cur)
                cur = {"maha": p["maha"], "start_jd": p["start_jd"], "end_jd": p["end_jd"]}
            else:
                cur["end_jd"] = p["end_jd"]
        mahas.append(cur)
        assert len(mahas) == 9                      # exactly one full cycle
        assert len({m["maha"] for m in mahas}) == 9  # each lord exactly once
        year_days = f["meta"]["dasha_year"]["days"]
        total = sum(m["end_jd"] - m["start_jd"] for m in mahas)
        # tropical year drifts over the 120y span (per-period year length); savana is exact
        assert total == pytest.approx(120 * year_days, abs=1.5 if mode == "true_tropical" else 0.05)
        for a, b in zip(mahas, mahas[1:]):          # contiguous
            assert a["end_jd"] == pytest.approx(b["start_jd"], abs=1e-6)


def test_varga_totality_and_valid_signs():
    f = engine.compute(birth())
    vargas = f["vargas"]
    for name in ("D1", "D9", "D60"):
        assert name in vargas
    for name, table in vargas.items():
        planets = [k for k in table if k != "Lagna"]
        assert len(planets) == 9, name              # 7 grahas + Rahu + Ketu
        for body, rec in table.items():
            assert 0 <= rec["sign"] <= 11, (name, body, rec)
            assert 0 <= rec["degree"] < 30, (name, body, rec)
            assert rec["abs_longitude"] == pytest.approx(
                (rec["sign"] * 30 + rec["degree"]) % 360, abs=1e-4)


def test_d1_sign_consistency_and_edges():
    """D1 sign is always floor(lon/30); a day's births keep every value in range."""
    for hh in range(0, 24, 3):
        f = engine.compute(BirthInput("B", 1984, 7, 13, hh, 0, 0, 25.4, 82.57, 5.5, "B"))
        for body, rec in f["vargas"]["D1"].items():
            assert rec["sign"] == int(rec["abs_longitude"] // 30)
            assert 0 <= rec["abs_longitude"] < 360


def test_lagna_boundary_flag_fires():
    """Find a birth time with lagna within 2° of a sign edge; flag must appear."""
    lat, lon = 25.4, 82.57
    edge_time = None
    for hh in range(24):                            # lagna sweeps ~360°/day
        b = BirthInput("B", 1984, 7, 13, hh, 0, 0, lat, lon, 5.5, "B")
        f = engine.compute(b)
        d = f["lagna"]["degree"]
        if d <= 2.0 or d >= 28.0:
            edge_time = hh
            assert f["lagna"]["boundary_flags"], f"degree {d} but no flag"
            assert "birth-time accuracy" in f["lagna"]["boundary_flags"][0]
            break
    assert edge_time is not None, "no lagna-edge time found in 24 samples"
    # and a mid-sign lagna must carry no flag
    f = engine.compute(birth())
    d = f["lagna"]["degree"]
    if not (d <= 2.0 or d >= 28.0):
        assert f["lagna"]["boundary_flags"] == []


def test_southern_hemisphere_chart():
    b = BirthInput("Sydney", 1990, 3, 21, 14, 30, 0, -33.87, 151.21, 11.0, "Sydney")
    f = engine.compute(b)
    assert 0 <= f["lagna"]["sign"] <= 11
    assert f["meta"]["lat"] == -33.87
    for body, rec in f["vargas"]["D1"].items():
        assert 0 <= rec["abs_longitude"] < 360


def test_ephemeris_disclosure_matches_backend():
    f = engine.compute(birth())
    assert f["meta"]["ephemeris"] == E.ephemeris_in_use(f["meta"]["julian_day"] - 5.5 / 24)
    # modern dates resolve to swiss when .se1 files are present
    assert f["meta"]["ephemeris"] in ("swiss", "moshier")
