"""Mode B: pasted degree-table parsing, precision tracking, ambiguity flags."""
import os
import sys
import uuid

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_modeb.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.astro import modeb
from app.db import init_db
from app.main import app

init_db()

JH_TABLE = """Sun 27°58' Ari
Moon 27°58' Dhanu
Mars 02:15 Vi
Mercury (R) 25°02'44" Simha
Jupiter 18.5 Makara
Venus 14° Taurus
Saturn 22°30' Libra
Rahu 08°10' Capricorn
Ketu 08°10' Cancer
Asc 18°08' Leo"""


def test_jh_style_table_parses_every_row():
    r = modeb.parse_degree_table(JH_TABLE, "jagannatha_hora")
    assert set(r["planets"]) == {"Sun", "Moon", "Mars", "Mercury", "Jupiter",
                                 "Venus", "Saturn", "Rahu", "Ketu", "Lagna"}
    assert r["planets"]["Moon"]["sign_name"] == "Sagittarius"
    assert r["planets"]["Moon"]["degree"] == pytest.approx(27 + 58 / 60, abs=1e-4)
    assert r["planets"]["Mercury"]["retrograde"] is True
    assert r["planets"]["Mercury"]["precision"] == "arcsec"
    assert r["planets"]["Jupiter"]["precision"] == "deg_1dp"


def test_precision_escalates_to_ambiguity_flags():
    r = modeb.parse_degree_table(JH_TABLE, "jagannatha_hora")
    # Venus pasted as a whole degree: ±0.5° swamps a 30′ D60 part
    assert "D60" in r["ambiguity"]["varga_flips"].get("Venus", {})
    assert any("D60 is unreliable" in w for w in r["warnings"])
    # Sun and Moon share the pasted degree — karaka rank cannot be ordered
    assert ["Sun", "Moon"] in r["ambiguity"]["karaka_ties"]
    assert any("karaka rank ambiguous" in w for w in r["warnings"])


def test_ambiguity_is_precision_dependent():
    tight = modeb.parse_degree_table("Moon 27°58'44\" Sagittarius", "drik_panchang")
    loose = modeb.parse_degree_table("Moon 28 Sagittarius", "drik_panchang")
    assert tight["planets"]["Moon"]["error_arcsec"] < loose["planets"]["Moon"]["error_arcsec"]
    assert "Moon" in loose["ambiguity"]["varga_flips"] or loose["ambiguity"]["varga_flips"] != tight["ambiguity"]["varga_flips"]


def test_provenance_required():
    with pytest.raises(ValueError):
        modeb.parse_degree_table("Moon 27°58' Sagittarius", "")
    with pytest.raises(ValueError):
        modeb.parse_degree_table("Moon 27°58' Sagittarius", "jh", "FAGAN")
    with pytest.raises(ValueError):
        modeb.parse_degree_table("   ", "jh")
    with pytest.raises(ValueError):
        modeb.parse_degree_table("no planet data here", "jh")


def test_interval_not_point_for_edges():
    """A value exactly on a varga boundary stays ambiguous, not silently resolved."""
    r = modeb.parse_degree_table("Mars 00°00' Virgo", "astrosage")
    # 0°00' ±30″ straddles the sign edge — any boundary-sensitive varga flips
    assert r["ambiguity"]["varga_flips"].get("Mars")


def test_hindi_and_hyphenated_rows_preserve_source_and_precision():
    line = "  चंद्र 3 कर्क 20′00.20″  "
    r = modeb.parse_degree_table(line + "\nMars Virgo 03-59-37", "astrosage")
    moon = r["planets"]["Moon"]
    assert moon["source_text"] == line
    assert moon["sign_name"] == "Cancer"
    assert moon["error_arcsec"] == pytest.approx(0.005)
    assert r["planets"]["Mars"]["degree"] == pytest.approx(3 + 59 / 60 + 37 / 3600, abs=1e-6)
    assert len(r["vargas"]) == 16


def test_pada_and_high_varga_intervals_include_boundary_alternatives():
    r = modeb.parse_degree_table("Moon 3°20′00″ Ari", "drik_panchang")
    assert [row["pada"] for row in r["ambiguity"]["nakshatra_padas"]["Moon"]] == [1, 2]
    assert r["vargas"]["D9"]["Moon"]["possible_signs"] == [0, 1]
    assert r["vargas"]["D9"]["Moon"]["status"] == "ambiguous"


def _client():
    c = TestClient(app)
    email = f"modeb-{uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/auth/register", json={"terms_accepted": True, "age_confirmed": True, "email": email,
                                         "password": "password123"})
    return c, {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_endpoint_parses_and_422s():
    c, h = _client()
    r = c.post("/api/tools/degree-table",
               json={"text": JH_TABLE, "source_program": "jagannatha_hora", "ayanamsa_id": "LAHIRI"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["planets"]["Mercury"]["retrograde"] is True
    assert "unavailable" in body and "ambiguity" in body
    r = c.post("/api/tools/degree-table",
               json={"text": "junk", "source_program": "x"}, headers=h)
    assert r.status_code == 422
    r = c.post("/api/tools/degree-table",
               json={"text": JH_TABLE, "source_program": "jh", "ayanamsa_id": "FAGAN"},
               headers=h)
    assert r.status_code == 422
