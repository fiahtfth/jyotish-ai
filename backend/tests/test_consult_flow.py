"""Consultation-flow policy: tense routing and retrospective answers, the
opening birth-time check, and sensitive-request handling."""
import json
from datetime import date

import pytest

from app.astro import calibration as C
from app.chat import safety
from app.llm import decider
from tests import test_jyotish as T
from tests.test_jyotish import client, send, register_and_profile, make_facts, _reset_auth_throttle  # noqa: F401


@pytest.fixture
def model(monkeypatch):
    from app.llm import providers
    calls = []

    def generate(messages, facts=None, analysis=None, context_note="", allow_external=True, on_delta=None,
                 routing_seconds=0, consultation_memory=(), system_suffix="", domain=None,
                 birth=None, today=None):
        calls.append({"messages": messages, "analysis": analysis, "context_note": context_note,
                      "domain": domain, "birth": birth, "today": today})
        return "Model reply.", "groq"

    monkeypatch.setattr(providers, "generate", generate)
    return calls


def _calibrated():
    h = register_and_profile()
    T._open_calibrated(h)
    return h


def _router(monkeypatch, reply):
    from app.llm import providers
    original = providers._classify

    def classify(prompt, messages, allow_external, *, timeout=None):
        if prompt.startswith("You route one turn"):
            return json.dumps(reply)
        return original(prompt, messages, allow_external, timeout=timeout)

    monkeypatch.setattr(providers, "_classify", classify)


# ------------------------------------------------------------------ A. tense

@pytest.mark.parametrize("text, tense", [
    ("when did I switch my career and in which direction?", "past"),
    ("was I ever promoted? it feels like it was long ago", "past"),
    ("when will I get a promotion?", "future"),
    ("what does next year look like for my career", "future"),
    ("what kind of work suits me by nature", "natal"),
    ("tell me about my career", None),
])
def test_tense_keyword_fallback(text, tense):
    assert decider.detect_tense(text) == tense


def test_router_reply_carries_a_validated_tense():
    raw = json.dumps({"topic": "career", "tense": "past"})
    assert decider.parse_turn_route(raw).tense == "past"
    assert decider.parse_turn_route(json.dumps({"topic": "career", "tense": "sideways"})).tense is None


def test_past_question_gets_a_retrospective_bundle_not_a_forecast(model):
    h = _calibrated()
    out = send("when did I switch my career and in which direction?", h)
    assert out[-1]["content"] == "Model reply."
    call = model[-1]
    assert call["analysis"] is None
    note = call["context_note"]
    assert "PAST-TENSE QUESTION about career" in note
    assert "No period was named" not in note and "coming twelve months" not in note
    meta = out[-1]["meta"]
    assert "analysis" not in meta and "requested_window" not in meta
    retro = meta["retrospective"]
    assert retro["domain"] == "career" and retro["antardasha"]
    today = date.today()
    assert all(date.fromisoformat(r["end"]) >= date(today.year - 16, 1, 1) for r in retro["antardasha"])
    assert all(date.fromisoformat(r["start"]) <= today for r in retro["antardasha"])
    assert retro["transits"] is not None
    # nothing reported yet: the model is told to offer likely periods and ask once
    assert "has not said when" in note and "ONE short natural question" in note


def test_past_question_uses_the_router_tense_and_reported_events(model, monkeypatch):
    h = _calibrated()
    _router(monkeypatch, {"topic": "career", "tense": "past", "understood": True})
    send("I started my first job in July 2012", h)
    db, conv, prof = T._db_profile_and_conv(h)
    from app.db import UserMilestone
    db.add(UserMilestone(profile_id=prof.id, year=2012, month=7, domain="career",
                         description="started my first job in July 2012"))
    db.commit(); db.close()
    send("what changed in my work back then?", h)
    assert "started my first job in July 2012" in model[-1]["context_note"]
    assert "has not said when" not in model[-1]["context_note"]


def test_future_question_keeps_the_default_twelve_month_window(model):
    h = _calibrated()
    out = send("when will I get a promotion?", h)
    assert out[-1]["meta"]["analysis"]["default_window"] is True
    assert "retrospective" not in out[-1]["meta"]


def test_natal_tense_has_no_window(model, monkeypatch):
    h = _calibrated()
    _router(monkeypatch, {"topic": "career", "tense": "natal", "understood": True})
    out = send("what is my career nature", h)
    assert "analysis" not in out[-1]["meta"]
    assert "untimed interpretation" in model[-1]["context_note"]


def test_generate_receives_domain_birth_and_today(model):
    h = _calibrated()
    send("how is my career going to be in 2027?", h)
    call = model[-1]
    assert call["domain"] == "career"
    assert call["birth"] is not None and call["today"] is not None


# ------------------------------------------------------------------ B. opening

def _two_year_windows(lords=("Sun", "Moon")):
    return [{"lords": list(lords), "start": date(y, 1, 1), "end": date(y, 12, 31)}
            for y in (2010, 2012, 2014, 2016, 2018, 2020)]


def _fake_eval(support=3, conflict=0, table=None):
    def evaluate(facts, birth, domain, start, end):
        s, c = (table or {}).get((domain, start.year), (support, conflict))
        return {"support_count": s, "conflict_count": c, "traditional_rule_ids": [], "convergence": "x",
                "pillars": {"parashari": "support" if s >= 3 else "neutral"}}
    return evaluate


def test_opening_invites_the_clients_own_dated_events_first():
    h = register_and_profile()
    first = client.get("/api/chat/history", headers=h).json()[-1]
    assert "3–5 major events" in first["content"] and "month and year" in first["content"]
    assert "Ask me a few questions instead" in first["meta"]["options"]
    assert client.get("/api/calibration", headers=h).json()["events"] == []


def test_own_events_run_the_milestone_search_and_skip_generated_questions(monkeypatch):
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    monkeypatch.setattr(C, "search_with_milestones", lambda *a, **k: None)
    send("started my first job in July 2012", h)
    send("got married March 2016", h)
    out = send("moved to Pune in 2019", h)
    assert "keep the recorded time" in " ".join(m["content"] for m in out)
    assert client.get("/api/calibration", headers=h).json()["events"] == []
    assert client.get("/api/profile", headers=h).json()["calibration_state"] == "skipped"


def test_questions_instead_asks_one_specific_event_at_a_time():
    h = register_and_profile()
    client.get("/api/chat/history", headers=h)
    out = send("Ask me a few questions instead", h)
    text = out[-1]["content"]
    assert out[-1]["meta"]["event_id"].startswith(C.OPENING_EVENT_PREFIX)
    assert " or " not in text.split("Between", 1)[1].split("?")[0].replace("such as a degree", "")
    assert text.count("?") == 1


def test_questions_ask_one_event_each_and_include_a_control(monkeypatch):
    birth, facts = make_facts()
    old = {"lords": ["Sun", "Moon"], "start": date(2006, 1, 1), "end": date(2006, 12, 31)}
    monkeypatch.setattr(C, "_past_ad_windows", lambda *a: _two_year_windows() + [old])
    monkeypatch.setattr(C.pillars, "evaluate", _fake_eval(
        table={(d, 2006): (0, 1) for d in ("career", "education", "relocation", "relationship")}, support=3))
    statements = C.generate_statements(facts, birth, "fp", sensitivity_fn=lambda *a: 0,
                                       today=date(2026, 11, 20))
    real = [s for s in statements if not s["control"]]
    controls = [s for s in statements if s["control"]]
    assert len(real) == 3 and len(controls) == 1
    assert controls[0]["event_id"] == C.CONTROL_EVENT_ID and controls[0]["predicted_window"]["start"] == "2006-01"
    for s in statements:
        body = s["chat_text"].split("?")[0]
        assert " or " not in body.replace("such as a degree", "")
        assert s["event_id"].startswith("recent_calibration_v5_")
    assert statements[1]["control"]          # not asked last, so it is not obvious


def test_windows_are_ranked_by_birth_time_sensitivity_not_support(monkeypatch):
    birth, facts = make_facts()
    monkeypatch.setattr(C, "_past_ad_windows", lambda *a: _two_year_windows())
    # support is higher in 2010 for career; sensitivity is higher in 2018
    monkeypatch.setattr(C.pillars, "evaluate", _fake_eval(
        table={("career", 2010): (4, 0)}, support=2))
    calls = []

    def sensitivity(domain, window, evidence):
        calls.append((domain, window["start"].year))
        return 10 if window["start"].year == 2018 else 1

    statements = C.generate_statements(facts, birth, "fp", sensitivity_fn=sensitivity,
                                       today=date(2026, 11, 20))
    career = next(s for s in statements if s["domain"] == "career" and not s["control"])
    assert career["predicted_window"]["start"] == "2018-01"
    assert calls                                     # the ranking function was consulted
    flat = C.generate_statements(facts, birth, "fp", sensitivity_fn=lambda *a: 0,
                                 today=date(2026, 11, 20))
    career = next(s for s in flat if s["domain"] == "career" and not s["control"])
    assert career["predicted_window"]["start"] == "2010-01"      # support breaks ties only


def test_each_question_asks_the_event_of_the_antardasha_lord(monkeypatch):
    birth, facts = make_facts()
    lord = facts["houses"][7]["lord"]
    assert C.lord_event_domain(facts, lord) in {"relationship", "career", "relocation", "education"}
    owned7 = [h for h in range(1, 13) if facts["houses"][h]["lord"] == lord]
    if 7 in owned7 and not {10, 6} & set(owned7):
        assert C.lord_event_domain(facts, lord) == "relationship"


def test_education_minimum_age_is_fifteen_and_relationship_matches_constants(monkeypatch):
    from dataclasses import replace
    from app.astro import constants as K
    ages = C.min_ages()
    assert ages["education"] == 15
    assert ages["relationship"] == K.MIN_CALIBRATION_AGE_FOR_DOMAIN["relationship"] == 21
    birth, facts = make_facts()
    birth = replace(birth, year=2010, month=1, day=1)
    monkeypatch.setattr(C, "_past_ad_windows", lambda *a: [
        {"lords": ["Sun", "Moon"], "start": date(2016, 1, 1), "end": date(2016, 12, 31)},   # age 6
        {"lords": ["Sun", "Moon"], "start": date(2019, 1, 1), "end": date(2019, 12, 31)}])  # age 9
    monkeypatch.setattr(C.pillars, "evaluate", _fake_eval())
    assert C.generate_statements(facts, birth, "fp", sensitivity_fn=lambda *a: 0,
                                 today=date(2026, 11, 20)) == []


def test_opening_uses_the_birthplace_local_today(monkeypatch):
    from dataclasses import replace
    birth, facts = make_facts()
    birth = replace(birth, year=2000, month=1, day=1)
    seen = []
    monkeypatch.setattr(C, "_past_ad_windows", lambda f, b, today=None: seen.append(today) or [])
    C.generate_statements(facts, birth, "fp", today=date(2031, 3, 4))
    assert seen == [date(2031, 3, 4)]


def _outcome(feedback, control=None):
    rows = [{"user_feedback": f, "event_id": f"recent_calibration_v5_{i:03d}"} for i, f in enumerate(feedback)]
    if control:
        rows.append({"user_feedback": control, "event_id": C.CONTROL_EVENT_ID})
    return C.calibration_outcome(rows)["state"]


def test_calibrated_needs_two_specific_confirmations_and_an_unconfirmed_control():
    assert _outcome(["confirmed"] * 3, control="rejected") == "calibrated"
    assert _outcome(["confirmed"] * 3) == "calibrated"
    assert _outcome(["confirmed"] * 2, control="rejected") == "calibrated"
    assert _outcome(["confirmed"] * 3, control="confirmed") == "partial"       # 'yes' to everything lowers it
    assert _outcome(["confirmed"] * 2, control="confirmed") == "uncalibrated"
    assert _outcome(["confirmed"], control="rejected") == "partial"            # a lone confirmation
    assert _outcome(["confirmed", "confirmed", "rejected"], control="rejected") == "partial"
    assert _outcome(["confirmed", "rejected", "rejected"], control="rejected") == "uncalibrated"


def test_confirming_the_control_in_chat_blocks_calibration():
    h = register_and_profile()
    T.answer_checks(h, T.start_checks(h), real="Yes, that happened", control="Yes, that happened")
    assert client.get("/api/profile", headers=h).json()["calibration_state"] == "partial"


# ------------------------------------------------------------------ C. safety

@pytest.mark.parametrize("text", [
    "when will I die?",
    "How long will my father live?",
    "what is my lifespan according to my chart",
    "when will my mother pass away",
    "will I die young",
])
def test_death_and_longevity_questions_are_declined_with_care(text):
    reply = safety.private_reply(text)
    assert reply and "don’t predict death" in reply and "doctor" in reply


def test_death_intercept_does_not_catch_ordinary_questions():
    assert safety.private_reply("when will this pressure die down?") is None
    assert safety.private_reply("when did my grandfather die?") is None
    assert safety.private_reply("how long will this job last") is None


@pytest.mark.parametrize("text", [
    "when will I get pregnant?",
    "when will I conceive",
    "when will we have a child?",
    "when will we have a baby",
])
def test_conception_and_child_timing_get_the_same_symbolic_reply(text):
    reply = safety.private_reply(text)
    assert reply == safety.private_reply("when will I get pregnant?")
    assert "symbolically" in reply and "clinician" in reply


def test_remedy_question_adds_the_routing_note(model):
    assert "low-cost" not in safety.context_note("what is my career")
    h = _calibrated()
    send("which gemstone should I wear?", h)
    note = model[-1]["context_note"]
    assert "optional, low-cost remedies first" in note and "functional benefic or the Lagna lord" in note
    send("how is my career", h)
    assert "low-cost remedies" not in model[-1]["context_note"]


def test_death_question_is_not_sent_to_the_model(model):
    h = _calibrated()
    out = send("when will I die?", h)
    assert out[-1]["kind"] == "private" and not model
