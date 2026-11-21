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


def test_llm_temperature_defaults():
    if not os.environ.get("JYOTISH_LLM_TEMPERATURE"):
        assert settings.LLM_TEMPERATURE == 0.6
    if not os.environ.get("JYOTISH_LLM_ROUTER_TEMPERATURE"):
        assert settings.LLM_ROUTER_TEMPERATURE == 0


def test_classifier_uses_router_temperature_and_reply_uses_reply_temperature(monkeypatch):
    seen = []
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.append(providers._temperature()) or "general")
    providers.conversation_topic([{"role": "user", "content": "hi"}], allow_external=True)
    providers.generate([{"role": "user", "content": "hi"}])
    assert seen == [settings.LLM_ROUTER_TEMPERATURE, settings.LLM_TEMPERATURE]


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


def test_stream_question_is_not_a_graduation_timing_event():
    from app.astro import prediction
    assert prediction.event_spec("tell me 3 possible guess regarding my graduation stream", "education") is None
    assert prediction.event_spec("which subject should I pick for graduation", "education") is None
    # real timing questions still match
    assert prediction.event_spec("when will I graduate", "education")["event_type"] == "graduation"
    assert prediction.event_spec("will I complete my degree this year", "education") is not None


def test_desha_kala_patra_context_uses_profile():
    from datetime import date
    from types import SimpleNamespace as NS
    from app.chat import context
    p = NS(year=2009, month=3, day=10, place_name="Pune", place_state="Maharashtra",
           place_country="India", relation="self")
    facts = {"current_vimshottari": [{"lords": ["Saturn", "Mercury", "Venus"]}]}
    txt = context.build(p, date(2026, 11, 20), facts, [])
    assert "17 years old" in txt and "school student" in txt
    assert "Saturn/Mercury" in txt and "Pune" in txt and "stream" in txt
    assert "never ask where they live" in txt
    other = NS(**{**p.__dict__, "relation": "mother"})
    assert "user's mother" in context.build(other, date(2026, 11, 20), {}, [])
    assert context.age_on(p, date(2026, 3, 9)) == 16


def test_system_prompt_requires_concise_answers_by_default():
    from app.llm import providers
    prompt = next(v for k, v in vars(providers).items() if isinstance(v, str) and "LENGTH AND DETAIL" in v)
    assert "give the gist" in prompt and "unless the client asks" in prompt


def test_context_tells_model_to_use_stated_facts_and_never_ask_timeframe():
    from datetime import date
    from types import SimpleNamespace as NS
    from app.chat import context
    p = NS(year=1984, month=7, day=13, place_name="Bhadohi", place_state="Uttar Pradesh",
           place_country="India", relation="self")
    txt = context.build(p, date(2026, 11, 20), {}, [])
    assert "42 years old" in txt
    assert "NEVER ask the user for a time frame" in txt and "NEXT step" in txt


# ---------------------------------------------------------------- verify repairs

def test_repair_removes_only_the_wrong_sentence_and_keeps_paragraphs(chart):
    _, facts = chart
    actual = facts["planets"]["Moon"]["sign_name"]
    wrong = "Taurus" if actual != "Taurus" else "Leo"
    text = (f"Your chart has a strong Moon, which gives you warmth.\n\n"
            f"Your Moon is in {wrong}, so you are stubborn.\n\n- Keep routines\n- Rest well")
    r = verify.verify_response(text, facts, _grounded(facts))
    assert not r["ok"]
    fixed = verify.repair_response(text, r["issues"])
    assert wrong not in fixed
    assert "Your chart has a strong Moon, which gives you warmth." in fixed
    assert "\n\n- Keep routines\n- Rest well" in fixed


def test_verifier_accepts_correct_empty_house_signs_and_user_dates(chart):
    _, facts = chart
    occupied = {rec["house"] for rec in facts["planets"].values()}
    empty = next((h for h in range(1, 13) if h not in occupied), 12)
    sign = facts["houses"][empty]["sign_name"]
    # grounding built only from planets/analysis still passes: all 12 house signs are added
    ctx = {"grounding_text": "Moon only"}
    assert verify.verify_response(f"Your {empty}th house falls in {sign}.", facts, ctx)["ok"]
    assert not verify.verify_response("You started in March 2006.", facts, ctx)["ok"]
    assert verify.verify_response("You started in March 2006.", facts,
                                  {**ctx, "user_text": "I did mechanical engineering in March 2006"})["ok"]


def test_verifier_still_rejects_invented_values_and_allows_100_percent(chart):
    _, facts = chart
    ctx = _grounded(facts)
    assert not verify.verify_response("Your Venus is at 12.3456 degrees.", facts, ctx)["ok"]
    from app.astro import constants as K
    absent = next(n for n in K.NAKSHATRAS if n.lower() not in ctx["grounding_text"].lower())
    assert not verify.verify_response(f"Your Venus is in {absent}.", facts, ctx)["ok"]
    assert verify.verify_response("That is 100% worth it.", facts, ctx)["ok"]
    assert not verify.verify_response("There is a 65% chance.", facts, ctx)["ok"]


def test_repair_keeps_numbered_lists():
    text = "1. First point.\n2. Expect news on 2027-08-09.\n3. Third point."
    fixed = verify.repair_response(text, ["date '2027-08-09' is not in the supplied facts"])
    assert fixed == "1. First point.\n3. Third point."


# ---------------------------------------------------------------- constrain_reply

def _analysis(question="Will I get a promotion?"):
    from app.astro import prediction as Q
    a = {"domain": "career", "analysis_window": {"start": "2027-01-01", "end": "2027-06-30"},
         "precision": {}, "classical": {"promise": "Weak"}}
    a["decision"] = {"disposition": "abstain", "event": {"event_type": "promotion"},
                     "window": a["analysis_window"]}
    return Q, a


def test_constrain_reply_preserves_paragraphs_and_numbered_lists():
    Q, a = _analysis()
    reply = ("Venus in your 7th house supports harmony.\n\n1. Keep communication open.\n"
             "2. Favour steady growth.\n3. Avoid rushing.\n\nYour promotion is guaranteed.")
    out = Q.constrain_reply(reply, a)
    assert "guaranteed" not in out
    assert out == ("Venus in your 7th house supports harmony.\n\n1. Keep communication open.\n"
                   "2. Favour steady growth.\n3. Avoid rushing.")


def test_constrain_reply_keeps_in_window_prose_dates_and_user_confirmed():
    Q, a = _analysis()
    reply = "March 2027 looks like the strongest stretch. You confirmed you applied in May 2026."
    assert Q.constrain_reply(reply, a, None, [{"role": "user", "content": "I applied in May 2026"}]) == reply
    out, issues = Q.constrain_reply("It lands in March 2031.", a, return_issues=True)
    assert issues and "2031" in issues[0]["message"] and out == ""


def test_constrain_reply_never_replaces_reply_on_percent_or_weak_promise():
    Q, a = _analysis()
    reply = "It is 100% worth it. The promotion looks possible but not promised."
    assert Q.constrain_reply(reply, a) == reply
    out = Q.constrain_reply("There is a 70% chance of promotion. Stay patient.", a)
    assert out == "Stay patient."
    assert "Are you mainly thinking" not in Q.constrain_reply("Venus rules your 10th.", a)


# ---------------------------------------------------------------- providers

def test_memory_goes_into_system_block_not_user_message(monkeypatch):
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    seen = []
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.append((system, messages)) or "ok")
    providers.generate([{"role": "user", "content": "How is my career?"}],
                       consultation_memory=[{"quote": "I work as a teacher"}])
    system, messages = seen[0]
    assert "I work as a teacher" in system and "Use silently" in system
    assert messages[-1]["content"] == "How is my career?"


def test_health_rules_only_when_health_is_relevant(monkeypatch):
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    seen = []
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.append(system) or "ok")
    providers.generate([{"role": "user", "content": "Will my business grow?"}])
    providers.generate([{"role": "user", "content": "My blood pressure is high, what does the chart say?"}])
    assert "HEALTH TOPIC" not in seen[0] and "HEALTH TOPIC" in seen[1]
    assert "paused" not in providers.SYSTEM_PERSONA


def test_plain_text_keeps_list_bullets_and_strips_paired_emphasis():
    out = providers.plain_text("* one **bold** item\n* two _soft_ item\n3 * 4 stays")
    assert out == "- one bold item\n- two soft item\n3 * 4 stays"
    assert providers.plain_text("a snake_case_name and `code`") == "a snake_case_name and code"


def test_offline_message_is_plain_when_service_unreachable(monkeypatch):
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "LLM_SLOT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(providers, "_llm_slots", providers.threading.BoundedSemaphore(1))
    assert providers._llm_slots.acquire(blocking=False)
    text, provider = providers.generate([{"role": "user", "content": "What will happen next year?"}])
    assert provider == "offline"
    assert text == providers.OFFLINE_MESSAGE and "?" not in text


def test_generate_waits_for_a_slot(monkeypatch):
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    monkeypatch.setattr(providers.settings, "LLM_SLOT_WAIT_SECONDS", 3)
    sem = providers.threading.BoundedSemaphore(1)
    monkeypatch.setattr(providers, "_llm_slots", sem)
    monkeypatch.setitem(providers.PROVIDERS, "groq", lambda s, m, timeout=None: "late reply")
    sem.acquire()
    providers.threading.Timer(0.3, sem.release).start()
    assert providers.generate([{"role": "user", "content": "hi"}]) == ("late reply", "groq")


def test_regenerate_with_issues_lists_issues_and_keeps_history(monkeypatch):
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(providers.settings, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.settings, "LLM_EXTERNAL_CONSENT", True)
    seen = []
    monkeypatch.setitem(providers.PROVIDERS, "groq",
                        lambda system, messages, timeout=None: seen.append((system, messages)) or "fixed")
    out = providers.regenerate_with_issues(
        [{"role": "user", "content": "How is my career?"}], None, None, "Draft text.",
        [{"sentence": "Draft text.", "message": "states a definite outcome as certain"}, "plain issue"])
    assert out == ("fixed", "groq")
    system, messages = seen[0]
    assert "REWRITE TASK" in system and len(messages) == 1
    assert "How is my career?" in messages[0]["content"] and "Draft text." in messages[0]["content"]
    assert "states a definite outcome" in messages[0]["content"] and "- plain issue" in messages[0]["content"]
