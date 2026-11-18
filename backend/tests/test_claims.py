"""Claim hygiene: no percentages, convergence disclaimer, verifier, LLM temperature."""
import os
import sys
import uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_claims.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pytest

from app.astro import pillars, verify
from app.astro.engine import BirthInput, engine
from app.config import settings
from app.llm import providers


@pytest.fixture(scope="module")
def chart():
    b = BirthInput("Arjun", 1990, 5, 15, 6, 15, 0, 13.0827, 80.2707, 5.5, "Chennai")
    return b, engine.compute(b)


def test_pillar_output_has_no_percentages_and_carries_disclaimer(chart):
    b, facts = chart
    for domain in ("career", "health", "marriage"):
        r = pillars.evaluate(facts, b, domain, date(2026, 1, 1), date(2027, 6, 30))
        assert "%" not in json.dumps(r, ensure_ascii=False)
        assert r["convergence"].startswith("Traditional convergence: ")
        assert "pillars indicate this window" in r["convergence"]
        assert r["convergence_disclaimer"] == pillars.CONVERGENCE_DISCLAIMER
        assert "Carlson 1985" in r["convergence_disclaimer"]
        assert "not an empirically validated probability" in r["convergence_disclaimer"]
        assert pillars.CONVERGENCE_DISCLAIMER in r["limitations"]


def test_llm_temperature_default():
    assert settings.LLM_TEMPERATURE == 0.2 or os.environ.get("JYOTISH_LLM_TEMPERATURE")
    if not os.environ.get("JYOTISH_LLM_TEMPERATURE"):
        assert settings.LLM_TEMPERATURE == 0.2


def test_no_hardcoded_temperature_in_providers():
    src = open(providers.__file__).read()
    assert '"temperature": 0.7' not in src


def test_facts_are_tagged_and_settings_line_present(chart):
    _, facts = chart
    brief = providers._facts_brief(facts)
    assert "[F001]" in brief and "Settings: ayanamsa" in brief
    reduced = {**facts, "meta": {**facts["meta"], "ephemeris": "moshier"}}
    assert "REDUCED PRECISION" in providers._facts_brief(reduced)


def _grounded(facts):
    return {"grounding_text": providers.grounding_text(facts, None)}


def test_verifier_rejects_invented_degree(chart):
    _, facts = chart
    r = verify.verify_response("Your Moon sits at 3.1415 degrees of its sign.", facts, _grounded(facts))
    assert not r["ok"] and any("degree" in i for i in r["issues"])


def test_verifier_accepts_degree_in_facts(chart):
    _, facts = chart
    deg = facts["planets"]["Moon"]["degree"]
    r = verify.verify_response(f"Moon is at {deg:.4f}° of its sign.", facts, _grounded(facts))
    assert not [i for i in r["issues"] if "degree" in i]
    assert not [i for i in verify.verify_response(f"Moon is near {deg:.1f}°.", facts,
                                                  _grounded(facts))["issues"] if "degree" in i]


def test_verifier_nakshatra(chart):
    _, facts = chart
    real = facts["planets"]["Moon"]["nakshatra"]["name"]
    assert verify.verify_response(f"Moon is in {real}.", facts, _grounded(facts))["ok"]
    other = "Rohini" if real != "Rohini" else "Bharani"
    r = verify.verify_response(f"The Sun is in {other}.", facts, _grounded(facts))
    assert not r["ok"] and any("nakshatra" in i for i in r["issues"])


def test_verifier_dates(chart):
    _, facts = chart
    ctx = {"grounding_text": "Window 2026-03-01 to 2026-04-15"}
    assert verify.verify_response("Look at 2026-03-01.", facts, ctx)["ok"]
    assert verify.verify_response("Around March 2026 things move.", facts, ctx)["ok"]
    bad = verify.verify_response("Expect news on 2027-08-09.", facts, ctx)
    assert not bad["ok"] and "2027-08-09" in bad["issues"][0]
    assert not verify.verify_response("Expect news in August 2027.", facts, ctx)["ok"]
    fixed = verify.repair_response("Fine sentence here. Expect news on 2027-08-09.", bad["issues"])
    assert "2027-08-09" not in fixed and "Fine sentence" in fixed


def test_verifier_probability_language_and_percent(chart):
    _, facts = chart
    for text in ("There is a 70% chance.", "The probability of marriage is high.",
                 "Your chances of promotion are good."):
        assert not verify.verify_response(text, facts, _grounded(facts))["ok"], text


def test_verifier_duration(chart):
    _, facts = chart
    ctx = {"grounding_text": "Jupiter dasha 16 years"}
    assert verify.verify_response("The Jupiter dasha lasts 16 years.", facts, ctx)["ok"]
    assert not verify.verify_response("This dasha period lasts 13 years.", facts, ctx)["ok"]
