"""Core method (astro/core.py): promise -> period -> trigger -> answer card, topics.json,
the core rule pack, /api/core/* and /api/home, and the Phase 4 flags."""
import copy
import json
import uuid
from dataclasses import replace
from datetime import date

import pytest

from app.astro import constants as K
from app.astro import core, gochara
from app.astro.engine import BirthInput, engine

TODAY = date(2026, 11, 22)
ARJUN = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0, lat=13.0827,
                   lon=80.2707, tz_offset=5.5, place_label="Chennai", birth_time_precision="exact")
# Same date and place at 00:00: Lagna changes and the 7th house promise is weak (checked below).
MIDNIGHT = replace(ARJUN, hour=0, minute=0)
UNKNOWN = replace(ARJUN, hour=12, minute=0, birth_time_precision="unknown")
FUTURE_VERDICTS = {"likely", "mixed", "not_indicated"}
NATAL_VERDICTS = {"strong", "moderate", "weak"}


@pytest.fixture(scope="module")
def facts():
    return engine.compute(ARJUN)


def _all_reasons(card):
    yield from card.why
    yield from card.details["promise"]["reasons"]
    for p in card.details["periods"]:
        yield from p["reasons"]
        for pd in p["pds"]:
            yield from pd["reasons"]
    for t in card.details["triggers"]:
        yield {"text": t["text"], "fact_ids": t["fact_ids"]}


# ------------------------------------------------------------------ topics / rule pack

def test_topics_json_valid():
    topics = core.load_topics()
    assert set(topics) == {"career", "job_change", "promotion", "business", "wealth", "marriage", "relationship",
                           "children", "education", "foreign", "property", "wellbeing"}
    assert topics["career"]["houses"][0] == 10 and topics["career"]["varga"] == "D10"
    assert topics["marriage"]["houses"][0] == 7 and topics["marriage"]["varga"] == "D9"
    assert topics["wellbeing"]["timing"] is False
    assert all(t["label"]["hi"] and len(t["questions"]) >= 3 for t in topics.values())
    good = json.loads(core.TOPICS_PATH.read_text())
    for patch, msg in ((lambda t: t["career"]["label"].pop("hi"), "label"),
                       (lambda t: t["career"].__setitem__("houses", [13]), "houses"),
                       (lambda t: t["career"].__setitem__("varga", "D99"), "varga"),
                       (lambda t: t["career"].__setitem__("karakas", ["Pluto"]), "karakas"),
                       (lambda t: t["wellbeing"].__setitem__("timing", True), "theme only"),
                       (lambda t: t["career"].__setitem__("safety_domain", "medical"), "safety_domain")):
        bad = copy.deepcopy(good)
        patch(bad["topics"])
        with pytest.raises(core.TopicError, match=msg):
            core.validate_topics(bad)
    with pytest.raises(core.TopicError):
        core.topic("lottery")


def test_core_rulepack_valid(facts):
    from app.astro.convergence import rulepack
    rules = rulepack.reload()
    core_ids = {r for r in rules if r.startswith("CORE.")}
    assert {"CORE.PROMISE", "CORE.PERIOD_LINK", "CORE.DOUBLE_TRANSIT", "CORE.CONFIDENCE"} <= core_ids
    assert "K.N. Rao" in rules["CORE.DOUBLE_TRANSIT"]["source"] and "BPHS" in rules["CORE.PROMISE"]["source"]
    for tid in ("career", "marriage"):
        card = core.answer(facts, ARJUN, tid, today=TODAY)
        used = {r for step in card.rule_ids.values() for r in step if r.startswith("CORE.")}
        assert used <= core_ids, used - core_ids


# ------------------------------------------------------------------ promise

def test_promise_career_and_marriage(facts):
    # Taurus Lagna: 10th Aquarius -> Saturn, own sign in the 9th, yogakaraka; 7th Scorpio -> Mars.
    assert facts["lagna"]["sign_name"] == "Taurus"
    assert facts["houses"][10]["lord"] == "Saturn" and facts["planets"]["Saturn"]["house"] == 9
    career = core.promise(facts, "career")
    assert career["grade"] == "strong"
    assert career["details"]["lord"] == "Saturn" and career["details"]["refs"] == ["lagna", "moon"]
    texts = " ".join(r["text"] for r in career["reasons"])
    assert "yogakaraka" in texts and "Saturn" in texts
    assert {"CORE.PROMISE", "CORE.PROMISE_MOON", "CORE.FUNC_ROLE", "BH.LORD_KENDRA_TRIKONA"} <= set(career["rule_ids"])
    assert any(f == "functional.roles.Saturn" for r in career["reasons"] for f in r["fact_ids"])
    assert 1 <= len(career["reasons"]) <= 3

    marriage = core.promise(facts, "marriage")
    assert marriage["grade"] in ("strong", "moderate") and marriage["details"]["lord"] == "Mars"
    assert all(r["fact_ids"] and r["text"] for r in marriage["reasons"])
    assert marriage["details"]["house_judgement"]["lagna"]["sign"] == "Scorpio"
    # Moon view: Moon in Sagittarius -> 7th from Moon is Gemini (Mercury)
    assert marriage["details"]["house_judgement"]["moon"]["lord"] == "Mercury"


def test_varga_confirmation_only_when_reliable(facts):
    assert facts["varga_reliability"]["D10"] == "reliable"
    assert core.promise(facts, "career")["details"]["varga"] == "D10 used"
    f2 = copy.deepcopy(facts)
    f2["varga_reliability"]["D10"] = "cusp_sensitive"
    p2 = core.promise(f2, "career")
    assert p2["details"]["varga"].startswith("D10 not used") and "CORE.VARGA_CONFIRM" not in p2["rule_ids"]
    assert facts["varga_reliability"]["D24"] != "reliable"
    edu = core.promise(facts, "education")
    assert "not used" in edu["details"]["varga"] and "CORE.VARGA_CONFIRM" not in edu["rule_ids"]


# ------------------------------------------------------------------ periods

def test_periods_link_hand_check(facts):
    career = core.topic("career")
    sat = core.planet_links(facts, "Saturn", career)
    assert any(r["kind"] == "owns" and r["house"] == 10 and r["ref"] == "lagna" for r in sat["reasons"])
    assert sat["strength"] == "strong"
    # Venus rules Taurus (1st) and Libra (6th) for a Taurus Lagna; the 6th is a career house.
    assert facts["houses"][6]["lord"] == "Venus"
    rows = core.periods(facts, ARJUN, "career", TODAY, date(2027, 11, 22))
    assert rows and all(r["start"] < "2027-11-22" and r["end"] > "2026-11-22" for r in rows)
    venus = next(r for r in rows if r["ad"] == "Venus")
    assert venus["md"] == "Rahu" and venus["link"] in ("strong", "medium")
    assert any("Venus rules your 6th house" in r["text"] and "houses.6.lord" in r["fact_ids"]
               for r in venus["reasons"])
    assert venus["friction"]["rule_id"].startswith("DC.AD_FROM_MD.")
    assert "CORE.PERIOD_LINK" in venus["rule_ids"]
    assert venus["pds"] and all(len(pd["lords"]) == 3 and pd["lords"][:2] == ["Rahu", "Venus"]
                                for pd in venus["pds"])


# ------------------------------------------------------------------ triggers

def _touches(planet, sign, targets):
    return any(sign == t or t in K.parashari_reaches(planet, sign) for t in targets)


def test_triggers_double_transit(facts):
    start, end = date(2026, 1, 1), date(2028, 12, 31)
    rows = core.triggers(facts, ARJUN, "career", start, end)
    assert rows and all(r["rule_id"] == "CORE.DOUBLE_TRANSIT" and r["fact_ids"] for r in rows)
    lag_targets = {(facts["lagna"]["sign"] + 9) % 12, facts["planets"]["Saturn"]["sign"]}   # Aquarius, Capricorn
    moon = facts["planets"]["Moon"]["sign"]
    moon_10 = (moon + 9) % 12
    moon_targets = {moon_10, facts["planets"][core._lord_of_sign(moon_10)]["sign"]}
    triggered = {r["month"] for r in rows}

    def go(d):
        g = gochara.gochara(facts, ARJUN, d, months=0, ingresses=False)["planets"]
        return g["Saturn"]["sign_index"], g["Jupiter"]["sign_index"]

    for r in rows[:4]:
        y, m = map(int, r["month"].split("-"))
        days = [go(date(y, m, d)) for d in (1, 10, 20, core._month_end(date(y, m, 1)).day)]   # incl. ingress day
        targets = lag_targets if r["from_lagna"] else moon_targets
        assert any(_touches("Saturn", s, targets) for s, _ in days), r
        assert any(_touches("Jupiter", j, targets) for _, j in days), r
    # a month that is not listed has no day on which both touch (checked on the 15th)
    for y in (2026, 2027, 2028):
        for m in range(1, 13):
            if f"{y}-{m:02d}" in triggered:
                continue
            s, j = go(date(y, m, 15))
            for targets in (lag_targets, moon_targets):
                assert not (_touches("Saturn", s, targets) and _touches("Jupiter", j, targets)), (y, m)


# ------------------------------------------------------------------ answer card

def test_weak_promise_not_indicated():
    f = engine.compute(MIDNIGHT)
    pr = core.promise(f, "marriage")
    assert pr["grade"] == "weak"
    card = core.answer(f, MIDNIGHT, "marriage", today=TODAY)
    assert card.verdict == "not_indicated" and card.window is None
    assert card.details["periods"] == [] and card.details["triggers"] == []
    assert card.why and all(r["fact_ids"] for r in card.why)
    natal = core.answer(f, MIDNIGHT, "marriage", question_tense="natal", today=TODAY)
    assert natal.verdict == "weak" and natal.window is None


def test_unknown_time_moon_only_and_low_confidence():
    f = engine.compute(UNKNOWN)
    pr = core.promise(f, "career", time_known=False)
    assert pr["details"]["refs"] == ["moon"] and "CORE.PROMISE_MOON" in pr["rule_ids"]
    assert "CORE.FUNC_ROLE" not in pr["rule_ids"] and "CORE.YOGA" not in pr["rule_ids"]
    assert not any(fid.startswith(("houses.", "lagna.", "strength.", "bhava_bala."))
                   for i in pr["details"]["factors"] for fid in i["fact_ids"])
    for tid in ("career", "marriage", "wealth"):
        card = core.answer(f, UNKNOWN, tid, today=TODAY, personal_fit="good")
        assert card.time_known is False and card.confidence == "low"
        assert card.details["promise"]["details"]["refs"] == ["moon"]
    assert all(p["reasons"] and all(r["fact_ids"] for r in p["reasons"])
               for p in core.periods(f, UNKNOWN, "career", TODAY, date(2027, 11, 22)))


def test_past_tense_returns_past_periods(facts):
    card = core.answer(facts, ARJUN, "career", question_tense="past", today=TODAY)
    assert card.tense == "past" and card.verdict in FUTURE_VERDICTS
    assert card.range["end"] == TODAY.isoformat() and card.range["start"] <= "2011-12-31"
    assert card.candidates and card.window
    assert all(c["end"] <= TODAY.isoformat() and c["start"] >= card.range["start"] for c in card.candidates)
    assert [c["start"] for c in card.candidates] == sorted((c["start"] for c in card.candidates), reverse=True)
    assert card.window["end"] <= TODAY.isoformat()
    assert "CORE.PAST_SCAN" in card.rule_ids["card"]


def test_card_json_round_trip(facts):
    card = core.answer(facts, ARJUN, "career", today=TODAY)
    assert card.verdict in FUTURE_VERDICTS and card.confidence in ("high", "medium", "low")
    assert card.window and TODAY.isoformat() <= card.window["start"] < card.window["end"] <= "2027-11-22"
    assert card.details["window_basis"] in ("pd+transit", "ad+transit", "ad")
    assert 1 <= len(card.why) <= 2 and card.action
    assert set(card.rule_ids) == {"promise", "period", "trigger", "card"}
    raw = card.to_json()
    back = core.Card.from_dict(json.loads(raw))
    assert back == card and back.to_json() == raw
    text = core.card_text(card)
    assert "Answer:" in text and "Confidence:" in text and card.action in text
    assert "उत्तर" in core.card_text(card.to_dict(), lang="hi")
    natal = core.answer(facts, ARJUN, "career", question_tense="natal", today=TODAY)
    assert natal.verdict in NATAL_VERDICTS and natal.window is None
    theme = core.answer(facts, ARJUN, "wellbeing", today=TODAY)
    assert theme.verdict in NATAL_VERDICTS and theme.window is None and theme.tense == "natal"


def test_every_reason_has_fact_ids(facts):
    for tid in core.load_topics():
        card = core.answer(facts, ARJUN, tid, today=TODAY)
        assert len(card.why) <= 2 and len(card.details["promise"]["reasons"]) <= 3
        for r in _all_reasons(card):
            assert r["text"] and r["fact_ids"] and all(isinstance(f, str) and f for f in r["fact_ids"]), (tid, r)
        json.dumps(card.to_dict())


def test_year_overview_shape(facts):
    items = core.year_overview(facts, ARJUN, TODAY)
    assert 1 <= len(items) <= 4
    main = [i for i in items if not i["caution"]]
    assert len(main) <= 3 and all(i["verdict"] in ("likely", "mixed") for i in main)
    rank = {"likely": 2, "mixed": 1}
    assert [rank[i["verdict"]] for i in main] == sorted((rank[i["verdict"]] for i in main), reverse=True)
    assert len({core.topic(i["topic"])["safety_domain"] for i in main}) == len(main)
    cautions = [i for i in items if i["caution"]]
    assert len(cautions) <= 1 and (not cautions or items[-1]["caution"])
    for i in items:
        assert set(i) >= {"topic", "label", "verdict", "window", "confidence", "why", "action"}
        assert i["window"] is None or set(i["window"]) == {"start", "end"}
        assert all(set(w) == {"text", "fact_ids"} and w["fact_ids"] for w in i["why"])
    excl = core.year_overview(facts, ARJUN, TODAY, exclude=("career", "job_change", "promotion"))
    assert not {i["topic"] for i in excl} & {"career", "job_change", "promotion"}
    # desh-kaal-paristhiti: topics implausible at the user's age never appear
    senior = replace(ARJUN, year=1966)            # 60 — past childbirth/education/career-change age
    topics_60 = {i["topic"] for i in core.year_overview(facts, senior, TODAY)}
    assert "children" not in topics_60 and "education" not in topics_60
    young = core.year_overview(facts, ARJUN, TODAY)
    assert {i["topic"] for i in young} - topics_60 or len(young) >= len(topics_60) - 1
    assert core.dasha_brief(facts, TODAY) == "Rahu major period, Venus sub-period until June 2027"


# ------------------------------------------------------------------ API and flags

def _user(profile):
    from tests.test_jyotish import client
    r = client.post("/api/auth/register", json={"terms_accepted": True, "age_confirmed": True,
                                                  "email": f"core_{uuid.uuid4().hex[:8]}@test.dev",
                                                  "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert client.put("/api/profile", json=profile, headers=h).status_code == 200
    return client, h


def test_api_home_and_core_answer():
    from tests.test_jyotish import ARJUN as ARJUN_PROFILE
    client, h = _user(ARJUN_PROFILE)
    home = client.get("/api/home", headers=h)
    assert home.status_code == 200, home.text
    body = home.json()
    assert set(body) == {"chart_brief", "year_overview", "chart_check", "suggested_questions"}
    cb = body["chart_brief"]
    assert cb["lagna"] == "Taurus" and cb["moon_sign"] == "Sagittarius" and cb["nakshatra"] == "Uttara Ashadha"
    assert isinstance(cb["current_dasha"], str) and "major period" in cb["current_dasha"]
    assert cb["time_known"] is True
    assert body["chart_check"]["state"] in ("checked", "not_checked")
    assert body["chart_check"]["personal_fit"] in ("good", "partial", "poor", None)
    assert body["chart_check"] == {"state": "not_checked", "personal_fit": None}
    qs = body["suggested_questions"]
    assert 4 <= len(qs) <= 6 and all(isinstance(q, str) and q for q in qs)
    for item in body["year_overview"]:
        assert item["verdict"] in FUTURE_VERDICTS
        assert item["window"] is None or set(item["window"]) == {"start", "end"}
        assert all(w["fact_ids"] for w in item["why"])
    if body["year_overview"] and any(i["caution"] for i in body["year_overview"]):
        assert body["year_overview"][-1]["caution"]

    ans = client.get("/api/core/answer?topic=career", headers=h)
    assert ans.status_code == 200, ans.text
    card = ans.json()
    assert set(card) >= {"topic", "verdict", "window", "confidence", "why", "action", "rule_ids", "details"}
    assert card["verdict"] in FUTURE_VERDICTS and card["tense"] == "future"
    natal = client.get("/api/core/answer?topic=marriage&tense=natal", headers=h).json()
    assert natal["verdict"] in NATAL_VERDICTS and natal["window"] is None
    past = client.get("/api/core/answer?topic=career&tense=past&start=2015-01-01&end=2020-01-01", headers=h).json()
    assert past["range"] == {"start": "2015-01-01", "end": "2020-01-01"}
    assert all("2015-01-01" <= c["start"] and c["end"] <= "2020-01-01" for c in past["candidates"])
    assert client.get("/api/core/answer?topic=lottery", headers=h).status_code == 404
    assert client.get("/api/core/answer?topic=career&tense=someday", headers=h).status_code == 422
    assert client.get("/api/core/answer?topic=career&start=2026-01-01&end=2025-01-01",
                      headers=h).status_code == 422
    topics = client.get("/api/core/topics").json()
    assert len(topics) == 12 and {"id", "label", "houses", "questions"} <= set(topics[0])


def test_flags_off_disable_convergence_and_kp():
    from app.config import settings
    from tests.test_jyotish import ARJUN as ARJUN_PROFILE
    assert settings.ENGINE == "core" and settings.ADVANCED_SCREENS is True
    assert settings.CONVERGENCE_V2 is False and settings.KP_ENABLED is False
    client, h = _user(ARJUN_PROFILE)
    kp = client.get("/api/kp", headers=h)
    assert kp.status_code == 404 and "KP" in kp.json()["detail"]
    conv = client.post("/api/convergence/MARRIAGE_TIMING", json={}, headers=h)
    assert conv.status_code == 404 and "switched off" in conv.json()["detail"]
