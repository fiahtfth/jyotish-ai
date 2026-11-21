"""LLM-first chat: deterministic code computes facts and handles safety; the
model writes the reply. Each test covers one reviewer finding."""
import json

import pytest

from tests import test_jyotish as T
from tests.test_jyotish import client, send, register_and_profile, _reset_auth_throttle  # noqa: F401 (autouse)


@pytest.fixture
def model(monkeypatch):
    """Capture what the model receives; reply like a live provider."""
    from app.llm import providers
    calls = []

    def generate(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return "Model reply.", "groq"

    monkeypatch.setattr(providers, "generate", generate)
    return calls


def _calibrated():
    h = register_and_profile()
    T._open_calibrated(h)
    return h


def _router(monkeypatch, reply):
    """Answer the structured turn-router prompt with `reply` (a dict)."""
    from app.llm import providers
    original = providers._classify

    def classify(prompt, messages, allow_external, *, timeout=None):
        if prompt.startswith("You route one turn"):
            return json.dumps(reply)
        return original(prompt, messages, allow_external, timeout=timeout)

    monkeypatch.setattr(providers, "_classify", classify)


# ---- H2: a past year inside a statement is a fact, not a period question ----

def test_statement_with_a_past_year_reaches_the_model_without_a_period_question(model):
    h = _calibrated()
    out = send("I did mechanical engineering in 2006", h)
    assert out[-1]["content"] == "Model reply."
    assert "explore for" not in out[-1]["content"] and "analysis" not in out[-1]["meta"]
    assert model[-1]["messages"][-1]["content"] == "I did mechanical engineering in 2006"
    assert "states a fact" in model[-1]["context_note"]


def test_future_year_without_topic_is_an_outlook_written_by_the_model(model):
    h = _calibrated()
    out = send("what will happen next year?", h)[-1]
    assert out["content"] == "Model reply." and out["meta"]["pending_outlook"]
    assert "COMPUTED OUTLOOK" in model[-1]["context_note"]


# ---- H1: timing questions without dates use the coming twelve months ----

@pytest.mark.parametrize("question, event", [
    ("when will I get married", "marriage"),
    ("kab hogi meri shaadi", "marriage"),
    ("will I get a job", "job_offer"),
    ("should I change jobs?", "job_change"),
    ("I am a software engineer and I want to start a business", "business_launch"),
])
def test_timing_question_without_dates_runs_the_default_window_and_calls_the_model(model, question, event):
    h = _calibrated()
    out = send(question, h)[-1]
    analysis = out["meta"]["analysis"]
    assert analysis["default_window"] and not analysis["period_requested"]
    assert analysis["decision"]["event"]["event_type"] == event
    assert model[-1]["analysis"]["decision"]["event"]["event_type"] == event
    assert "coming twelve months" in model[-1]["context_note"]
    assert "What period" not in out["content"]


# ---- H3: no canned date questions ----

def test_tell_me_about_my_future_reads_the_coming_year(model):
    h = _calibrated()
    out = send("tell me about my future", h)[-1]
    assert out["content"] == "Model reply." and out["meta"]["requested_window"]


def test_past_statements_are_ignored_and_two_candidates_are_compared(model):
    from datetime import date
    h = _calibrated()
    out = send("I married in 2015 and moved in 2019, how will 2027 be?", h)[-1]
    assert out["meta"]["requested_window"] == ["2027-01-01", "2027-12-31"]
    assert "Which dates" not in out["content"]
    both = send("should I marry in May or June?", h)[-1]["meta"]["analysis"]["analysis_window"]
    assert both["start"][5:7] in ("05", "06") and both["end"][5:] == "06-30"
    assert "more than one candidate period" in model[-1]["context_note"]


def test_full_report_without_period_is_not_a_question():
    h = _calibrated()
    out = send("give me my full report", h)[-1]
    assert out["kind"] == "report"


# ---- H6: the role matcher only for listed roles ----

def test_career_suits_me_goes_to_the_model_with_d10_facts(model):
    h = _calibrated()
    out = send("which career suits me as per my chart", h)[-1]
    assert "career_match" not in out["meta"] and out["content"] == "Model reply."
    assert model[-1]["facts"]["selected_chart"]["name"] == "D10"
    assert "10th-house ruler" in model[-1]["context_note"]
    liked = send("I like teaching", h)[-1]
    assert "career_match" not in liked["meta"] and liked["content"] == "Model reply."


def test_years_are_never_treated_as_roles(model):
    from app.chat import career
    assert not career.starts_match("compare 2026 and 2028 for my career")
    h = _calibrated()
    out = send("compare 2026 and 2028 for my career", h)[-1]
    assert "career_match" not in out["meta"]


# ---- H7: complaints reach the model ----

def test_complaint_is_recorded_and_answered_by_the_model(model):
    from app.chat.memory import KEY
    h = _calibrated()
    send("How is my career looking?", h)
    out = send("that's wrong, I'm not in IT", h)
    assert out[0]["meta"][KEY][0]["status"] == "disagreed"
    assert out[-1]["content"] == "Model reply."
    assert "reacting to an earlier reading" in model[-1]["context_note"]


# ---- M1: day lists only for days/dates/muhurat ----

@pytest.mark.parametrize("question", ["when should I marry", "is it a good time to invest"])
def test_life_timing_questions_are_readings_not_day_lists(model, question):
    h = _calibrated()
    out = send(question, h)[-1]
    assert out["kind"] != "timing" and out["content"] == "Model reply."


# ---- M2: explanations are written in plain words ----

def test_why_is_explained_by_the_model_and_tables_stay_in_meta(model):
    h = _calibrated()
    send("Will I get a promotion in 2027?", h)
    why = send("why?", h)[-1]
    assert why["content"] == "Model reply." and why["meta"]["explained"]
    assert "expanded" not in why["meta"]
    assert "plain words" in model[-1]["context_note"] and model[-1]["analysis"]["domain"] == "career"
    details = send("show me the details", h)[-1]
    assert details["meta"]["expanded"] and details["content"] == "Model reply."


# ---- M3: a pending Sade Sati question doesn't capture other topics ----

def test_pending_sade_sati_does_not_capture_another_topic(model):
    h = _calibrated()
    pending = send("Check my sade sati from 2027 to 2035", h)[-1]
    assert pending["meta"]["pending_sade_sati"]
    out = send("ok forget that, how is my career next year", h)[-1]
    assert "sade_sati" not in out["meta"] and out["content"] == "Model reply."
    send("Check my sade sati from 2027 to 2035", h)
    assert "sade_sati" in send("2027", h)[-1]["meta"]


def test_sade_sati_without_dates_uses_a_default_instead_of_asking():
    h = _calibrated()
    out = send("tell me about my sade sati", h)[-1]
    assert "sade_sati" in out["meta"] and "Which dates" not in out["content"]


# ---- M4: birth-time checks never swallow conversation ----

def test_hi_does_not_get_the_birth_time_notice_as_a_reply(model):
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    send("Continue with the reading", h)
    T._db_profile_and_conv(h)
    db, conv, _ = T._db_profile_and_conv(h)
    # forget the notice so the next turn would carry it
    for m in conv.messages:
        meta = json.loads(m.meta_json or "{}")
        meta.pop("birth_time_notice", None)
        m.meta_json = json.dumps(meta)
    db.commit()
    db.close()
    out = send("hi", h)
    assert len(out) == 2 and out[-1]["content"] == "Model reply."
    assert "less accurate" in out[-1]["meta"]["notice"]


@pytest.mark.parametrize("text, feedback", [
    ("yes but I want to ask about my marriage", "confirmed"),
    ("no, I was in college then", "rejected"),
])
def test_mixed_check_answer_records_the_answer_and_reaches_the_model(model, text, feedback):
    h = register_and_profile()
    T.start_checks(h)
    out = send(text, h)
    events = client.get("/api/calibration", headers=h).json()["events"]
    assert events[0]["user_feedback"] == feedback
    assert out[-1]["content"] == "Model reply." and out[-1]["kind"] != "options"
    assert model[-1]["messages"][-1]["content"] == text
    db, conv, _ = T._db_profile_and_conv(h)
    assert conv.state == "open"
    db.close()


def test_plain_button_answers_still_advance_the_checks():
    h = register_and_profile()
    T.start_checks(h)
    out = send("No, that didn't happen", h)
    assert out[-1]["kind"] == "options" and out[-1]["meta"].get("event_id")


def test_dated_statement_after_failed_checks_is_conversation(model, monkeypatch):
    h = register_and_profile()
    T._fail_calibration(h)
    out = send("I did mechanical engineering in 2006", h)
    assert out[-1]["content"] == "Model reply." and "One or two more" not in out[-1]["content"]
    db, _, prof = T._db_profile_and_conv(h)
    assert prof.milestones == []
    db.close()


# ---- M5: the 12-month anchor only for future/timing questions ----

def test_no_future_anchor_for_thanks_or_unrelated_questions(model):
    h = _calibrated()
    anchor = "Anchor the answer to the running dasha"
    send("thanks", h)
    assert anchor not in model[-1]["context_note"]
    send("what about my brother", h)
    assert anchor not in model[-1]["context_note"]
    send("will I be happy?", h)
    assert anchor in model[-1]["context_note"]


# ---- M7: routing ----

@pytest.mark.parametrize("text, domain", [
    ("I want to learn about my marriage", "relationship"),
    ("how does this work?", None),
    ("lets move on to something else", None),
    ("I love painting, what suits me", None),
    ("what is the meaning of rahu in 7th", None),
    ("engineering", "education"),
    ("commerce", "education"),
    ("will I buy a house", "relocation"),
    ("when will my child be born", "children"),
])
def test_keyword_fallback_routing(text, domain):
    from app.chat.orchestrator import detect_domain
    assert detect_domain(text) == domain


def test_structured_router_result_is_validated():
    from datetime import date
    from app.llm import decider
    route = decider.parse_turn_route(json.dumps({
        "topic": "relationship", "event": "marriage", "window": {"start": "2027-01-01", "end": "2027-06-30"},
        "needs_muhurta": False, "needs_chart_image": False, "is_statement": False, "is_feedback": False,
        "wants_detail": False, "understood": True, "interpretation": "Asks when marriage is likely.",
        "clarifying_question": None}))
    assert route.topic == "relationship" and route.event == "marriage"
    assert route.window == (date(2027, 1, 1), date(2027, 6, 30)) and route.understood
    assert decider.parse_turn_route('{"topic": "invented"}') is None
    assert decider.parse_turn_route("not json") is None
    # an event from another topic is dropped
    assert decider.parse_turn_route('{"topic": "career", "event": "marriage"}').event is None
    # "not understood" without a question is treated as understood
    assert decider.parse_turn_route('{"topic": "general", "understood": false}').understood


def test_router_overrides_keywords_and_passes_its_interpretation(model, monkeypatch):
    _router(monkeypatch, {"topic": "relationship", "event": None, "window": None, "understood": True,
                          "interpretation": "Wants to learn what the chart says about marriage."})
    h = _calibrated()
    out = send("I want to learn about my marriage", h)[-1]
    assert out["meta"]["reading_domain"] == "relationship"
    assert "Wants to learn what the chart says about marriage." in model[-1]["context_note"]


def test_router_profile_context_is_sent(monkeypatch):
    from app.llm import providers
    prompts = []
    monkeypatch.setattr(providers, "_classify",
                        lambda prompt, *a, **k: prompts.append(prompt) or "")
    h = _calibrated()
    send("how is my career looking", h)
    router = next(p for p in prompts if p.startswith("You route one turn"))
    assert "born in Chennai" in router and "age 36" in router


def test_ambiguous_message_surfaces_a_clarifying_question(model, monkeypatch):
    _router(monkeypatch, {"topic": "general", "understood": False,
                          "clarifying_question": "Do you mean your own job, or your brother's?"})
    h = _calibrated()
    out = send("what about that one", h)[-1]
    assert out["meta"]["clarifying"] and "analysis" not in out["meta"]
    assert "Do you mean your own job, or your brother's?" in model[-1]["context_note"]
    assert out["content"] == "Model reply."


def test_clarifying_question_falls_back_to_the_router_wording_offline(monkeypatch):
    _router(monkeypatch, {"topic": "general", "understood": False,
                          "clarifying_question": "Do you mean the job offer from last week?"})
    h = _calibrated()
    out = send("is it the one?", h)[-1]
    assert out["content"] == "Do you mean the job offer from last week?"


def test_clear_message_without_dates_gets_no_question(model, monkeypatch):
    _router(monkeypatch, {"topic": "relationship", "event": "marriage", "window": None, "understood": True,
                          "interpretation": "Asks when marriage is likely."})
    h = _calibrated()
    out = send("when will I get married", h)[-1]
    assert "clarifying" not in out["meta"] and out["meta"]["analysis"]["default_window"]
    assert "Asks when marriage is likely." in model[-1]["context_note"]


# ---- M8: old-prediction survey ----

def test_followup_survey_is_not_appended_to_an_unrelated_answer(model):
    h = _calibrated()
    assert client.put("/api/predictions/followups", json={"enabled": True}, headers=h).status_code == 200
    send("Will I get a promotion in my career next year?", h)
    T._age_predictions(h)
    unrelated = send("what is my moon sign", h)[-1]
    assert "followup" not in unrelated["meta"] and unrelated["content"] == "Model reply."
    related = send("How is my career looking?", h)[-1]
    assert related["meta"]["followup"]["id"]
    assert related["content"].startswith("Model reply.") and related["content"].count("\n\n") == 1
    reply = send("yes", h)
    # a "happened" answer is confirmed against the window: the date is asked first
    assert "What date" in reply[-1]["content"]
    before = client.get("/api/predictions", headers=h).json()["predictions"][0]
    send(before["window_start"], h)
    after = client.get("/api/predictions", headers=h).json()["predictions"][0]
    assert after["outcome"] == "happened"
    assert after["event_date"] == before["window_start"]
    assert len(reply) == 2


# ---- Low ----

def test_health_note_once_per_conversation(model):
    from app.astro.constants import HEALTH_DISCLAIMER
    h = _calibrated()
    first = send("how is my health", h)[-1]["content"]
    # (a reply carrying a health *analysis* gets the note re-added by
    # app.main._msg_out on every read — outside the orchestrator)
    second = send("tell me more about my health", h)[-1]["content"]
    assert HEALTH_DISCLAIMER in first and HEALTH_DISCLAIMER not in second


def test_chart_reply_has_no_stock_question():
    h = _calibrated()
    out = send("show my D9 chart", h)[-1]
    assert out["kind"] == "chart" and "Anything you'd like" not in out["content"]


def test_safety_reply_stays_in_model_context(model):
    h = _calibrated()
    send("I want to end my life", h)
    send("yes I'm safe now", h)
    history = model[-1]["messages"]
    assert any("14416" in m["content"] for m in history if m["role"] == "assistant")
    assert not any("end my life" in m["content"] for m in history)


def test_long_reply_is_shortened_unless_detail_requested(monkeypatch):
    from app.chat import orchestrator as o
    from app.llm import providers
    long_text = " ".join(["word"] * 400)
    calls = []

    def fake_regen(history, facts, analysis, previous, issues, **kw):
        calls.append(issues)
        return "Short direct answer.", "gemini"
    monkeypatch.setattr(providers, "regenerate_with_issues", fake_regen)
    hist = [{"role": "user", "content": "what is my source of wealth"}]
    out = o._shorten_if_needed(long_text, "gemini", hist, {}, None, "", [], True)
    assert out == "Short direct answer." and calls
    calls.clear()
    hist = [{"role": "user", "content": "explain in detail my source of wealth"}]
    assert o._shorten_if_needed(long_text, "gemini", hist, {}, None, "", [], True) == long_text
    assert not calls
    # offline / short replies untouched
    assert o._shorten_if_needed(long_text, "offline", hist[:0], {}, None, "", [], True) == long_text
    assert o._shorten_if_needed("ok " * 50, "gemini", [{"role": "user", "content": "hi"}], {}, None, "", [], True) == "ok " * 50
