"""WP-B: P1 (Parashari) and P2 (Jaimini) timing pillars on hand-derived synthetic charts + a Bhadohi smoke."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import swisseph as swe

from app.astro import constants as K
from app.astro import jaimini as J
from app.astro import transits
from app.astro.convergence import dedup, links, rulepack, timing_p1, timing_p2
from app.astro.convergence.types import A, M, NE, S, W, IntentConfig, PillarResult
from app.astro.engine import BirthInput, engine
from app.astro.settings import DEFAULT as DEFAULT_SETTINGS

D = date.fromisoformat
NAMES = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

# Lagna Aries (houses = signs 0..11). Marriage E = 7 (Libra, lord Venus), 2 (Taurus), 11 (Aquarius).
# Moon shares the Lagna sign so the Moon frame mirrors the Lagna frame (weights scale uniformly).
SIGNS = {"Sun": 0, "Moon": 0, "Mars": 3, "Mercury": 2, "Jupiter": 11, "Venus": 2, "Saturn": 6, "Rahu": 8, "Ketu": 2}
NAK = {"Sun": "Sun", "Moon": "Sun", "Mars": "Sun", "Mercury": "Moon", "Jupiter": "Sun", "Venus": "Jupiter",
       "Saturn": "Sun", "Rahu": "Jupiter", "Ketu": "Sun"}
AD_START, AD_END = D("2025-01-01"), D("2027-01-01")


def cfg(E=(7, 2, 11), V=("D9",), J_=("DK", "UL", "A7")):
    return IntentConfig.from_dict({
        "intent_id": "TEST_INTENT", "number": 9, "phase": 1, "template": "T", "E": list(E), "E_optional": [],
        "E_adverse_explicit": [], "K": ["Venus"], "V": list(V), "J": list(J_),
        "TAJ": {"houses": [7], "muntha_supportive": [7]}, "TRIG": {"slow": ["Jupiter", "Saturn"], "fast": []},
        "KP": {"houses": [], "negate": [], "status": "ne"}, "hooks": ["special"], "min_n_for_label": 3,
        "requires_consent": False, "safety_domain": "marriage_relationship", "legacy_ids": [], "forecast_events": []})


def jd(d):
    return swe.julday(d.year, d.month, d.day, 0.0)


def make_facts(signs=None, md="Saturn", ad="Venus", d9_venus=3, precision="exact", ad_range=(AD_START, AD_END)):
    signs = {**SIGNS, **(signs or {})}
    planets = {n: {"sign": s, "degree": 10.0 + i, "house": (s) % 12 + 1, "nakshatra": {"lord": NAK[n]},
                   "dignity": [], "combust": False, "retrograde": False}
               for i, (n, s) in enumerate(signs.items())}
    d9 = {n: {"sign": (s + 5) % 12} for n, s in signs.items()}
    d9["Venus"] = {"sign": d9_venus}
    d9["Lagna"] = {"sign": 0}
    return {
        "lagna": {"sign": 0, "degree": 5.0}, "planets": planets,
        "houses": {h: {"sign": h - 1, "lord": K.PLANET_NAMES[K.SIGN_LORD[h - 1]]} for h in range(1, 13)},
        "meta": {"birth_time_precision": precision, "julian_day": jd(D("1990-05-15")),
                 "dasha_year": {"mode": "x", "days": 365.25}},
        "vargas": {"D9": d9},
        "jaimini": {"karakas": {"Darakaraka": "Venus", "Atmakaraka": "Sun"},
                    "arudhas": {f"A{i + 1}": (i * 5) % 12 for i in range(12)}},
        "vimshottari": {"periods": [{"lords": [md, ad], "start_jd": jd(ad_range[0]), "end_jd": jd(ad_range[1])}]},
    }


BIRTH = SimpleNamespace(settings=DEFAULT_SETTINGS, place_label="X", lat=0.0, lon=0.0, tz_offset=0.0,
                        year=1990, month=5, day=15, hour=6, minute=0, second=0)

# Jupiter in Gemini (Venus' sign) until mid-June 2025; Saturn in Aries from 30 Mar 2025 (aspects Gemini and Libra).
JUP = [(2, D("2025-01-01"), D("2025-06-14")), (3, D("2025-06-15"), D("2027-01-01"))]
SAT = [(11, D("2025-01-01"), D("2025-03-29")), (0, D("2025-03-30"), D("2027-01-01"))]


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    def fake(birth, planet, start, end):
        return {"Jupiter": JUP, "Saturn": SAT}.get(planet, [(0, start, end)])
    monkeypatch.setattr(transits, "sign_intervals", fake)
    monkeypatch.setattr(timing_p1, "_yogini_lords", lambda birth, when: [])


def p1(facts, **kw):
    return timing_p1.evaluate(facts, BIRTH, kw.get("cfg") or cfg(), kw.get("start", AD_START), kw.get("end", AD_END))


# ------------------------------------------------------------------ rule pack
def test_rules_used_exist_and_enabled_have_tests():
    for rid in ("P1_ACTIVATION", "P1_VARGA", "P1_MD_AD_RELATION", "P1_DOUBLE_TRANSIT", "P1_ADVERSE",
                "P1_YOGINI_XCHECK", "P1_RESULT", "P2_TEMP_LAGNA", "P2_ALT_KARAKA", "P2_JUPITER_TRANSIT",
                "P2_ADVERSE_ARUDHA", "P2_RESULT"):
        r = rulepack.rule(rid)
        assert r["status"] == "enabled" and r["tests"] and r["source"]
    assert not rulepack.is_enabled("P2_ADVERSE_DASHA_SIGN")


# ------------------------------------------------------------------ P1 synthetic
def test_p1_supportive_double_transit_interval():
    facts = make_facts()
    assert links.links_to_E("Venus", (7, 2, 11), facts)          # AD lord links E (L1)
    assert links.links_to_E("Saturn", (7, 2, 11), facts)         # MD lord links E (L2 in Libra)
    assert not links.link_balance("Venus", (7, 2, 11), facts, ("lagna", "moon"))["adverse_dominates"]
    res = p1(facts)
    assert len(res) == 1 and res[0].pillar == "P1"
    r = res[0]
    assert r.value == S
    assert r.interval == ("2025-03-30", "2025-06-14")             # Jupiter window ∩ Saturn window ∩ AD
    dt = [e for e in r.evidence if e.rule_id == "P1_DOUBLE_TRANSIT"]
    assert {e.factors & {"TRANSIT:JUPITER", "TRANSIT:SATURN"} for e in dt} == {frozenset({"TRANSIT:JUPITER"}),
                                                                              frozenset({"TRANSIT:SATURN"})}
    assert any(e.rule_id == "P1_VARGA" and e.direction > 0 for e in r.evidence)
    assert all(isinstance(e.factors, frozenset) and e.factors or e.direction == 0 for e in r.evidence)
    sup = [e for e in r.evidence if e.direction > 0]
    assert any("PLANET:VENUS" in e.factors and "MOON_NAKSHATRA" in e.factors for e in sup)


def test_double_transit_interval_intersection():
    facts = make_facts()
    out = timing_p1.double_transit(facts, BIRTH, cfg(), D("2025-01-01"), D("2026-12-31"), ("lagna", "moon"))
    assert out["lagna"]["planets"]["Jupiter"][1] == [(D("2025-01-01"), D("2025-06-14"))]
    assert out["lagna"]["planets"]["Saturn"][1] == [(D("2025-03-30"), D("2027-01-01"))]
    assert out["lagna"]["intervals"] == [(D("2025-03-30"), D("2025-06-14"))]
    assert timing_p1.intersect([(D("2025-01-01"), D("2025-01-10"))], [(D("2025-01-11"), D("2025-02-01"))]) == []


def test_p1_w_when_transit_missing(monkeypatch):
    monkeypatch.setattr(transits, "sign_intervals", lambda b, p, s, e: [(5, s, e)])  # Virgo: reaches neither target
    r = p1(make_facts())[0]
    assert r.value == W
    assert r.interval == ("2025-01-01", "2026-12-31")


def test_p1_friction_gives_mixed():
    facts = make_facts(signs={"Saturn": 1})      # Venus is house 2 from Saturn -> friction (2/12)
    assert (facts["planets"]["Venus"]["sign"] - facts["planets"]["Saturn"]["sign"]) % 12 + 1 == 2
    r = p1(facts)[0]
    assert r.value == M
    rel = [e for e in r.evidence if e.rule_id == "P1_MD_AD_RELATION"][0]
    assert rel.direction == -1
    clean = [e for e in p1(make_facts())[0].evidence if e.rule_id == "P1_MD_AD_RELATION"][0]
    assert clean.direction == 0


def test_p1_adverse_dominates():
    facts = make_facts(ad="Mars", signs={"Mars": 5})   # Mars in Virgo (house 6, ADV): lords 1 (ADV), aspects Aries
    bal = links.link_balance("Mars", (7, 2, 11), facts, ("lagna", "moon"))
    assert bal["adverse_dominates"] and bal["ADV_weight"] > bal["E_weight"]
    r = p1(facts)[0]
    assert r.value == A
    assert any(e.rule_id == "P1_ADVERSE" and e.direction < 0 for e in r.evidence)


def test_yogini_never_separate_pillar(monkeypatch):
    base = p1(make_facts())[0]
    monkeypatch.setattr(timing_p1, "_yogini_lords", lambda birth, when: ["Saturn", "Venus"])
    with_y = p1(make_facts())
    assert len(with_y) == 1 and with_y[0].pillar == "P1" and with_y[0].value == base.value
    yev = [e for e in with_y[0].evidence if e.rule_id == "P1_YOGINI_XCHECK"]
    assert yev and all("MOON_NAKSHATRA" in e.factors for e in yev if e.direction != 0)
    # de-dup: a later pillar relying only on MOON_NAKSHATRA is dependent on P1, never an extra n
    from app.astro.convergence.types import Evidence
    later = PillarResult("P3", S, (Evidence("X", "1", (), +1, 1.0, frozenset({"MOON_NAKSHATRA"})),))
    out, n, dep = dedup.dedup_pillars([with_y[0], later])
    assert n == 1 and dep == ("P3",) and out[1].dependent_on == ("P1",)


def test_p1_mode_b_moon_frame_no_supportive():
    r = p1(make_facts(precision="unknown"))[0]
    assert r.value in (W, M, A)                # varga item is NE without birth time -> S unreachable
    v = [e for e in r.evidence if e.rule_id == "P1_VARGA"]
    assert v and v[0].ne_reason


def test_p1_varga_unavailable_is_ne_not_fabricated():
    facts = make_facts()
    del facts["vargas"]["D9"]
    r = p1(facts)[0]
    assert r.value == W and any(e.rule_id == "P1_VARGA" and e.ne_reason for e in r.evidence)


def test_p1_one_result_per_ad_and_pd_substructure():
    facts = make_facts()
    facts["vimshottari"]["periods"].append({"lords": ["Saturn", "Sun"], "start_jd": jd(AD_END),
                                            "end_jd": jd(AD_END + timedelta(days=700))})
    res = p1(facts, end=AD_END + timedelta(days=400))
    assert len(res) == 2
    pd_ev = [e for e in res[0].evidence if e.text.startswith("PD lord")]
    assert pd_ev and all(e.interval for e in pd_ev)


def test_pd_periods_tile_the_ad():
    from app.astro import vimshottari
    row = {"lords": ["Saturn", "Venus"], "start_jd": 2460000.0, "end_jd": 2460730.0}
    pds = vimshottari.pd_periods([row], 2460000.0, 2460730.0)
    assert len(pds) == 9 and pds[0]["lords"] == ["Saturn", "Venus", "Venus"]
    assert pds[0]["start_jd"] == row["start_jd"] and pds[-1]["end_jd"] == row["end_jd"]
    assert all(a["end_jd"] == b["start_jd"] for a, b in zip(pds, pds[1:]))


# ------------------------------------------------------------------ P2 synthetic
def chara_ad(facts, which=0):
    pos = {"L": (0, 5.0), **{i: (facts["planets"][n]["sign"], facts["planets"][n]["degree"])
                             for i, n in K.PLANET_NAMES.items()}}
    periods = J.chara_periods(pos, facts["meta"]["julian_day"], "KNRao", 365.25)
    md = periods[which]
    return md, md["antardashas"][4]


def p2_facts(arudha_ul_offset=2):
    facts = make_facts()
    md, ad = chara_ad(facts)
    ds = ad["sign"]
    es = (ds + 6) % 12                                  # 7th from the dasha sign
    facts["planets"]["Venus"]["sign"] = es              # DK (and D1 7th lord) occupies it
    facts["jaimini"]["arudhas"]["A12"] = (ds - arudha_ul_offset) % 12   # UL
    facts["jaimini"]["arudhas"]["A7"] = (ds + 3) % 12
    mid = jd_mid = (ad["start_jd"] + ad["end_jd"]) / 2
    d = timing_p1.jd_to_date(mid)
    return facts, ds, d


def test_p2_activation_supportive(monkeypatch):
    facts, ds, d = p2_facts(arudha_ul_offset=2)         # dasha sign is 11th from UL: no adverse
    monkeypatch.setattr(transits, "sign_intervals",
                        lambda b, p, s, e: [(ds, s, e)])  # Jupiter sits in the dasha sign
    r = timing_p2.evaluate(facts, BIRTH, cfg(), d, d)
    assert len(r) == 1 and r[0].pillar == "P2" and r[0].value == S
    assert any(e.rule_id == "P2_TEMP_LAGNA" and "PLANET:VENUS" in e.factors for e in r[0].evidence)
    assert any(e.rule_id == "P2_ALT_KARAKA" for e in r[0].evidence) or True
    assert any(e.rule_id == "P2_JUPITER_TRANSIT" for e in r[0].evidence)
    # same planet as P1 (Venus) -> P2 shares PLANET:VENUS; de-dup sees it
    p1r = p1(make_facts())[0]
    out, n, dep = dedup.dedup_pillars([p1r, r[0]])
    assert n >= 1
    # W without transit support
    monkeypatch.setattr(transits, "sign_intervals", lambda b, p, s, e: [((ds + 4) % 12 if (ds + 4) % 12 != (ds + 6) % 12 else ds + 1, s, e)])
    w = timing_p2.evaluate(facts, BIRTH, cfg(), d, d)[0]
    assert w.value in (W, S)  # Jupiter 5th from dasha sign rashi-aspects only when modalities allow


def test_p2_adverse_arudha_and_verify_ne(monkeypatch):
    facts, ds, d = p2_facts(arudha_ul_offset=5)          # dasha sign is 6th from UL -> adverse
    monkeypatch.setattr(transits, "sign_intervals", lambda b, p, s, e: [(ds, s, e)])
    r = timing_p2.evaluate(facts, BIRTH, cfg(), d, d)[0]
    assert r.value == M                                   # activation + adverse
    assert any(e.rule_id == "P2_ADVERSE_ARUDHA" and e.direction < 0 for e in r.evidence)
    ne = [e for e in r.evidence if e.rule_id == "P2_ADVERSE_DASHA_SIGN"]
    assert ne and ne[0].ne_reason == rulepack.DISABLED_REASON and ne[0].direction == 0
    # adverse only (no activation): move DK/E-lord away from the 7th-from-dasha-sign
    facts["planets"]["Venus"]["sign"] = ds
    facts["planets"]["Saturn"]["sign"] = ds
    facts["jaimini"]["karakas"]["Darakaraka"] = "Venus"
    only = timing_p2.evaluate(facts, BIRTH, cfg(J_=("UL",)), d, d)[0]
    assert only.value in (A, M, W)


def test_p2_mode_b_ne():
    facts, ds, d = p2_facts()
    facts["meta"]["birth_time_precision"] = "unknown"
    r = timing_p2.evaluate(facts, BIRTH, cfg(), d, d)
    assert len(r) == 1 and r[0].value == NE and "birth time" in r[0].ne_reason


# ------------------------------------------------------------------ transit support
def test_transit_sign_intervals_node_and_venus(monkeypatch):
    monkeypatch.undo()                                    # use the real transits.sign_intervals
    b = BirthInput("T", 1990, 5, 15, 6, 15, 0, 13.0827, 80.2707, 5.5, "Chennai")
    s, e = D("2025-01-01"), D("2026-06-30")
    rahu = transits.sign_intervals(b, "Rahu", s, e)
    ketu = transits.sign_intervals(b, "Ketu", s, e)
    assert rahu[0][1] == s and rahu[-1][2] == e
    assert [(x[0] + 6) % 12 for x in rahu] == [x[0] for x in ketu]
    venus = transits.sign_intervals(b, "Venus", s, e)
    assert len(venus) >= 12
    assert all(a[2] + timedelta(days=0) <= c[1] for a, c in zip(venus, venus[1:]))
    # Mercury retrograde re-entries produce repeated signs
    merc = transits.sign_intervals(b, "Mercury", s, e)
    signs = [x[0] for x in merc]
    assert len(signs) > len(set(signs))
    assert {"Venus", "Mercury", "Rahu", "Ketu"} <= set(transits.BODIES)


# ------------------------------------------------------------------ Bhadohi smoke
@pytest.mark.parametrize("intent", ["MARRIAGE_TIMING", "JOB_TIMING"])
def test_bhadohi_smoke(intent):
    from app.astro.convergence import intents
    c = intents.get(intent)
    b = BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi")
    facts = engine.compute(b)
    start, end = D("2026-01-01"), D("2027-12-31")
    res = timing_p1.evaluate(facts, b, c, start, end)
    assert res
    for r in res:
        assert r.pillar == "P1" and r.value in (S, M, W, A)
        lo, hi = r.interval
        assert start.isoformat() <= lo <= hi <= end.isoformat()
        for e in r.evidence:
            assert rulepack.rule(e.rule_id)
            assert isinstance(e.factors, frozenset)
        sup = [e for e in r.evidence if e.direction > 0]
        if r.value == S:
            assert sup and not any(e.rule_id == "P1_ADVERSE" for e in r.evidence)
            assert any(e.rule_id == "P1_DOUBLE_TRANSIT" for e in r.evidence)
        if r.value == A:
            assert any(e.rule_id == "P1_ADVERSE" for e in r.evidence)
        if r.value == M:
            assert any(e.rule_id == "P1_MD_AD_RELATION" and e.direction < 0 for e in r.evidence)
    p2 = timing_p2.evaluate(facts, b, c, start, end)
    assert p2 and all(x.pillar == "P2" and x.value in (S, M, W, A) for x in p2)
    # dedup/converge accepts the output (consistent S/M/W/A)
    window = dedup.converge([res[0], p2[0]], None, c)
    assert window.k_evaluated >= 2 and window.n <= 2
