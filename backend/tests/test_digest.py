"""KEY INDICATIONS digest, its wiring into the prompt/grounding, and the structural verifier checks."""
import os
import sys
import uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_digest.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.astro import digest, verify
from app.astro.engine import BirthInput, engine
from app.llm import providers

TODAY = date(2026, 11, 20)


@pytest.fixture(scope="module")
def chart():
    b = BirthInput("Arjun", 1990, 5, 15, 6, 15, 0, 13.0827, 80.2707, 5.5, "Chennai")
    return b, engine.compute(b)


def _ctx(facts):
    return {"grounding_text": providers.grounding_text(facts, None)}


def test_digest_karakas_labelled_and_correct(chart):
    b, facts = chart
    d = digest.build_digest(facts, b, TODAY)
    assert "ONLY these planets carry these titles: AK Moon" in d
    assert "AmK Mars" in d and "BK Venus" in d and "MK Jupiter" in d
    assert "PK Mercury" in d and "GK Saturn" in d and "DK Sun" in d
    assert "NATURAL karakas (these are NOT chara-karaka titles)" in d


def test_digest_nodes_not_retrograde(chart):
    b, facts = chart
    d = digest.build_digest(facts, b, TODAY)
    node_lines = [l for l in d.splitlines() if l.startswith(("Rahu ", "Ketu "))]
    assert node_lines and not any("retro" in l.lower() for l in node_lines)
    assert "dispositor" in node_lines[0] and "star lord" in node_lines[0]
    brief = providers._facts_brief(facts)
    assert not any(l.split("] ", 1)[1].startswith(("Rahu:", "Ketu:")) and "retro" in l for l in brief.splitlines())


def test_digest_house_lords_sav_dasha_gochara(chart):
    b, facts = chart
    d = digest.build_digest(facts, b, TODAY)
    assert "House lords from Lagna" in d and "House lords from Moon" in d
    assert "SAV bindus by HOUSE from Lagna" in d and "H10=34" in d     # Aquarius (sign index 10) = 34
    assert "DASHA now" in d and "MD Rahu 2012-12-01 to 2030-12-01" in d and "Next Antardashas" in d
    assert "GOCHARA" in d and "from Lagna" in d and "from Moon" in d
    assert "Kantaka Shani" in d       # Saturn in Pisces is 4th from natal Sagittarius Moon
    assert 20 <= len(d.splitlines()) <= 60


def test_digest_dual_roles(chart):
    b, facts = chart
    d = digest.build_digest(facts, b, TODAY)
    assert "Saturn yogakaraka AND badhaka" in d
    venus = next(x for x in d.split("Functional roles: ", 1)[1].splitlines()[0].split("; ") if x.startswith("Venus"))
    if "malefic" in venus:                      # a malefic Lagna lord states its dual role
        assert "(but Lagna lord)" in venus


def test_digest_domain_only_when_routed(chart):
    b, facts = chart
    assert "DOMAIN" not in digest.build_digest(facts, b, TODAY)
    career = digest.build_digest(facts, b, TODAY, "career")
    assert "DOMAIN career" in career and "AmK Mars" in career and "D10 Lagna" in career
    assert "DOMAIN marriage" not in career and "DOMAIN wealth" not in career
    assert "DOMAIN marriage" in digest.build_digest(facts, b, TODAY, "relationship")
    assert "D24 Lagna" in digest.build_digest(facts, b, TODAY, "education")
    assert "DOMAIN wealth" in digest.build_digest(facts, b, TODAY, "finance")


def test_digest_without_birth_omits_gochara(chart):
    _, facts = chart
    d = digest.build_digest(facts, None, TODAY)
    assert "GOCHARA" not in d and "DASHA now" in d


def test_grounding_includes_digest(chart):
    b, facts = chart
    g = providers.grounding_text(facts, None, birth=b, today=TODAY, domain="career")
    assert "KEY INDICATIONS" in g and "DOMAIN career" in g
    brief = providers._facts_brief(facts, birth=b, today=TODAY)
    assert "[F001]" in brief and "Settings: ayanamsa" in brief


def test_generate_sends_digest_and_grounding_reuses_it(chart, monkeypatch):
    b, facts = chart
    seen = {}
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.setdefault("system", system) and "ok")
    providers.generate([{"role": "user", "content": "career?"}], facts=facts, domain="career",
                       birth=b, today=TODAY)
    assert "KEY INDICATIONS" in seen["system"] and "DOMAIN career" in seen["system"]
    assert "GOCHARA" in seen["system"]
    # a later grounding call with no extra args sees the same text
    assert "GOCHARA" in providers.grounding_text(facts, None)


def test_system_prompt_checklist_and_remedies():
    s = providers.SYSTEM_PERSONA
    assert "INTERPRETIVE METHOD" in s and "No D1 promise means no timing" in s
    assert "Never call Rahu or Ketu retrograde" in s and "Bhavat Bhavam" in s
    assert "REMEDIES AND ETHICS" in s and "no gemstone unless the client asks".lower() in s.lower()
    assert "never mention\n  miscarriage" in s or "miscarriage" in s
    assert "LENGTH AND DETAIL" in s


def test_skeptic_disclaimer_not_sent_to_model(chart, monkeypatch):
    from app.astro import pillars
    b, facts = chart
    r = pillars.evaluate(facts, b, "career", date(2026, 1, 1), date(2027, 6, 30))
    seen = {}
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.setdefault("system", system) and "ok")
    providers.generate([{"role": "user", "content": "career?"}], facts=facts, analysis=r)
    assert "Carlson" not in seen["system"] and "empirically validated" not in seen["system"]
    assert "Carlson 1985" in r["convergence_disclaimer"]      # app-side audit keeps it


def test_verifier_karaka_titles(chart):
    _, facts = chart
    bad = verify.verify_response("Sun is your Atmakaraka, the soul of the chart.", facts, _ctx(facts))
    assert not bad["ok"] and any("Atmakaraka" in i for i in bad["issues"])
    assert verify.verify_response("Moon is your Atmakaraka.", facts, _ctx(facts))["ok"]
    assert verify.verify_response("Your Darakaraka is the Sun.", facts, _ctx(facts))["ok"]
    for wrong in ("Mars is the Bhratrukaraka.", "Saturn is your Putrakaraka.", "Jupiter is the Gnatikaraka."):
        assert not verify.verify_response(wrong, facts, _ctx(facts))["ok"], wrong
    fixed = verify.repair_response("Sun is your Atmakaraka. Moon is calm.", bad["issues"])
    assert "Atmakaraka" not in fixed and "Moon is calm." in fixed


def test_verifier_node_retrograde(chart):
    _, facts = chart
    r = verify.verify_response("Rahu retrograde makes this period intense.", facts, _ctx(facts))
    assert not r["ok"] and any("retrograde" in i for i in r["issues"])
    assert verify.verify_response("Rahu shapes this period through Saturn.", facts, _ctx(facts))["ok"]
    assert "retrograde" not in verify.repair_response("Rahu retrograde is strong. Work is steady.",
                                                      r["issues"]).lower()


def test_verifier_house_lordship(chart):
    _, facts = chart
    assert facts["houses"][10]["lord"] == "Saturn"
    ok = verify.verify_response("Saturn rules the 10th house and Mercury is the 2nd lord.", facts, _ctx(facts))
    assert ok["ok"], ok
    bad = verify.verify_response("Mars rules the 10th house.", facts, _ctx(facts))
    assert not bad["ok"] and any("rules the 10th" in i for i in bad["issues"])
    assert not verify.verify_response("The 7th lord is Venus.", facts, _ctx(facts))["ok"]
    assert verify.verify_response("Venus rules the 1st and 6th houses.", facts, _ctx(facts))["ok"]
    assert "Mars rules" not in verify.repair_response("Mars rules the 10th house. Keep going.", bad["issues"])
