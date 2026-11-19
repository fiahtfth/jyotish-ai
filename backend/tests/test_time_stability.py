"""Time basis resolution (zone / LMT / manual, DST gaps and overlaps) and birth-time stability windows."""
import os, sys, uuid
from datetime import date, datetime, timedelta

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_frame.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import geo
from app.astro import stability
from app.astro.engine import BirthInput

DELHI = (28.6139, 77.2090)
KOLKATA = (22.5726, 88.3639)
MUMBAI = (19.0760, 72.8777)
NYC = (40.7128, -74.0060)


def bhadohi():
    return BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi")


# ---------- offsets ----------

def test_wartime_india_offset_and_question():
    r = geo.resolve_offset(*DELHI, datetime(1944, 6, 15, 6, 0), country="India", state="Delhi")
    assert r["offset_hours"] == 6.5 and r["source"] == "tzdb" and r["tzdb_version"]
    assert any("war" in w.lower() for w in r["warnings"])


def test_kolkata_1942_june_is_standard_time():
    r = geo.resolve_offset(*KOLKATA, datetime(1942, 6, 1, 12, 0), country="India", state="West Bengal")
    assert r["offset_hours"] == 5.5
    assert any("Calcutta Time" in w for w in r["warnings"])


def test_dst_gap_raises():
    with pytest.raises(geo.NonexistentTime) as e:
        geo.resolve_offset(*NYC, datetime(2021, 3, 14, 2, 30), country="United States")
    assert (e.value.before, e.value.after) == (-5.0, -4.0)


def test_dst_overlap_needs_fold():
    when = datetime(2021, 11, 7, 1, 30)
    with pytest.raises(geo.AmbiguousTime) as e:
        geo.resolve_offset(*NYC, when, country="United States")
    assert e.value.offsets == [-4.0, -5.0]
    assert geo.resolve_offset(*NYC, when, fold=0)["offset_hours"] == -4.0
    assert geo.resolve_offset(*NYC, when, fold=1)["offset_hours"] == -5.0
    assert geo.resolve_offset(*NYC, when, fold=1)["ambiguity"]["fold"] == 1


def test_ordinary_time_has_no_ambiguity():
    r = geo.resolve_offset(*NYC, datetime(2021, 7, 1, 12, 0))
    assert r["offset_hours"] == -4.0 and r["ambiguity"] is None and not r["warnings"]


def test_bombay_time_warning():
    r = geo.resolve_offset(*MUMBAI, datetime(1950, 3, 1, 8, 0), country="India", state="Maharashtra")
    assert r["offset_hours"] == 5.5
    assert any("Bombay Time" in w and "4:51" in w for w in r["warnings"])
    assert not any("Bombay" in w for w in geo.resolve_offset(
        *MUMBAI, datetime(1960, 3, 1, 8, 0), country="India", state="Maharashtra")["warnings"])


def test_pre_1906_india_warning():
    r = geo.resolve_offset(*DELHI, datetime(1900, 1, 1, 8, 0), country="India")
    assert any("1906" in w for w in r["warnings"])


def test_lmt_and_manual_basis():
    r = geo.resolve_offset(25.4, 82.57, datetime(1984, 7, 13, 9, 14), basis="lmt")
    assert r["source"] == "lmt" and abs(r["offset_hours"] * 3600 - (5 * 3600 + 30 * 60 + 17)) <= 1
    m = geo.resolve_offset(25.4, 82.57, datetime(1984, 7, 13, 9, 14), basis="manual", manual_offset=5.75)
    assert m["offset_hours"] == 5.75 and m["source"] == "manual"
    with pytest.raises(ValueError):
        geo.resolve_offset(25.4, 82.57, datetime(1984, 7, 13, 9, 14), basis="manual")


def test_historical_utc_offset_still_works():
    assert geo.historical_utc_offset(*DELHI, datetime(1990, 1, 1), 0.0) == 5.5


# ---------- stability windows ----------

def test_bhadohi_d10_cusp_window():
    w = stability.lagna_windows(bhadohi())
    d10 = w["D10"]
    assert -45 <= d10["start_s"] <= -25
    assert d10["status"] == "cusp_sensitive"
    assert d10["margin_before_s"] == pytest.approx(-d10["start_s"], abs=0.01)
    # D1 is nowhere near a sign change; all requested vargas are reported
    assert w["D1"]["status"] == "stable" and w["D1"]["open_ended"]
    assert set(w) == {f"D{n}" for n in stability.DEFAULT_VARGAS}


def test_window_edges_are_true_sign_changes():
    """Inside the reported window the D10 Lagna is constant; just outside it differs."""
    from jhora.panchanga import drik
    from jhora.horoscope.chart import charts
    from app.astro.engine import apply, calc_lock
    from jhora import utils
    b = bhadohi()
    d10 = stability.lagna_windows(b, vargas=(10,))["D10"]
    place = drik.Place("x", b.lat, b.lon, b.tz_offset)
    jd0 = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))

    def sign(t):
        with calc_lock:
            apply(b.settings)
            asc = drik.ascendant(jd0 + t / 86400, place)[:2]
            return charts.dasamsa_chart([["L", asc]])[0][1][0]
    assert sign(d10["start_s"] + 1) == sign(0) != sign(d10["start_s"] - 1)
    assert sign(d10["end_s"] - 1) == sign(0) != sign(d10["end_s"] + 1)


def test_precision_sets_uncertainty():
    b = bhadohi()
    assert stability.uncertainty_for(b) == 120
    approx = BirthInput(**{**b.__dict__, "birth_time_precision": "approximate"})
    assert stability.uncertainty_for(approx) == 1800
    wide = stability.lagna_windows(approx, vargas=(60,))["D60"]
    assert wide["status"] == "cusp_sensitive"      # 30-minute uncertainty swamps a 2-minute D60 window


def test_synthetic_double_crossing_caught():
    def sign(t):
        if -200 < t < -80:
            return 5            # an excursion that returns to the original sign
        if 40.3 < t < 66.1:
            return 4            # a 26 s excursion
        return 3
    w = stability.windows_from_functions({"S": sign})["S"]
    assert w["changes_s"] == pytest.approx([-200, -80, 40.3, 66.1], abs=0.5)
    assert w["start_s"] == pytest.approx(-80, abs=0.5)
    assert w["end_s"] == pytest.approx(40.3, abs=0.5)
    assert w["status"] == "cusp_sensitive"          # 40 s to the next change < 120 s


def test_moon_pada_window_brackets_birth():
    w = stability.moon_pada_window(bhadohi())
    assert w["start_s"] < 0 < w["end_s"]
    assert 1 <= w["pada"] <= 4 and 0 <= w["nakshatra"] < 27
    assert w["status"] == "stable"


def test_planet_edge_windows_shape_and_varga_validation():
    w = stability.planet_edge_windows(bhadohi())
    assert w["uncertainty_s"] == 120 and set(w["vargas"]) == {"D9", "D60"}
    assert isinstance(w["flips"], dict) and isinstance(w["flipping_planets"], list)
    for planet, per_varga in w["flips"].items():
        for vname, rec in per_varga.items():
            assert rec["changes_s"] and rec["transitions"]
    with pytest.raises(ValueError):
        stability.planet_edge_windows(bhadohi(), vargas=("D999",))


def test_cusp_audit_surfaces_moon_pada_and_planet_edges():
    from app.astro import classical
    flips, tbl = classical.cusp_audit(bhadohi())
    kinds = [r[0] for r in tbl["rows"]]
    assert "Moon nakshatra pada" in kinds
    assert "Moon pada" in flips
    edge_rows = [k for k in kinds if " @ " in str(k)]
    assert all("@" in str(k) for k in edge_rows)   # "Planet @ Dvarga" rows only when flagged


# ---------- Muntha years follow solar returns ----------

def test_completed_years_follow_solar_return():
    from app.astro import precision
    b = bhadohi()
    ret = precision.solar_return_date(b, 16)
    assert abs((ret - date(2000, 7, 13)).days) <= 1
    assert precision.completed_solar_years(b, ret) == 16
    assert precision.completed_solar_years(b, ret - timedelta(days=1)) == 15
    assert precision.completed_solar_years(b, date(1984, 7, 12)) == -1


# ---------- API ----------

@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import init_db
    init_db()
    c = TestClient(app)
    email = f"ts_{uuid.uuid4().hex[:8]}@test.dev"
    r = c.post("/api/auth/register", json={"terms_accepted": True, "email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return c, {"authorization": f"Bearer {r.json()['access_token']}"}


NY = dict(display_name="Ny", year=2021, month=3, day=14, hour=2, minute=30,
          place_name="New York", place_state="New York", place_country="United States",
          latitude=40.7128, longitude=-74.0060, birth_time_precision="exact")


def test_api_gap_time_is_422(api):
    c, h = api
    r = c.put("/api/profile", json=NY, headers=h)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "nonexistent_time" and d["offsets"] == [-5.0, -4.0]


def test_api_overlap_then_fold_and_fields(api):
    c, h = api
    body = {**NY, "month": 11, "day": 7, "hour": 1}
    r = c.put("/api/profile", json=body, headers=h)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "ambiguous_time" and d["offsets"] == [-4.0, -5.0]
    r = c.put("/api/profile", json={**body, "dst_fold": 1, "calc_preset": "jh"}, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["utc_offset_hours"] == -5.0 and p["offset_source"] == "tzdb" and p["tzdb_version"]
    assert p["time_basis"] == "zone" and p["dst_fold"] == 1 and p["calc_preset"] == "jh"
    assert isinstance(p["tz_warnings"], list)
    fp = p["calc_fingerprint"]
    # changing the preset is a material change: the chart fingerprint moves
    p2 = c.put("/api/profile", json={**body, "dst_fold": 1, "calc_preset": "drik"}, headers=h).json()
    assert p2["calc_fingerprint"] != fp


def test_api_manual_and_lmt_basis(api):
    c, h = api
    body = {**NY, "month": 7, "day": 1, "hour": 12, "minute": 0}
    r = c.put("/api/profile", json={**body, "time_basis": "manual", "utc_offset_manual": -3.5}, headers=h)
    assert r.status_code == 200 and r.json()["utc_offset_hours"] == -3.5 and r.json()["offset_source"] == "manual"
    r = c.put("/api/profile", json={**body, "time_basis": "lmt"}, headers=h)
    assert r.status_code == 200 and r.json()["utc_offset_hours"] == pytest.approx(-74.006 / 15)
    assert c.put("/api/profile", json={**body, "time_basis": "manual"}, headers=h).status_code == 422
    assert c.put("/api/profile", json={**body, "calc_preset": "bogus"}, headers=h).status_code == 422
