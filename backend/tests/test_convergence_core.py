"""WP-A convergence core: links, ADV, promise gate, de-dup, natal template, intent configs, rule pack."""
import copy
import json
import re
from pathlib import Path

import pytest

from app.astro import constants as K
from app.astro import registry
from app.astro.convergence import intents, links, rulepack
from app.astro.convergence.dedup import converge, narrow_window
from app.astro.convergence.natal import template_N
from app.astro.convergence.promise import promise_gate
from app.astro.convergence.types import (Evidence, IntentConfig, IntentConfigError, PillarResult, PromiseResult,
                                         PROMISE_STRONG, PROMISE_WEAK)
from app.astro.pillars import CONVERGENCE_DISCLAIMER

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
PID = {n: i for i, n in K.PLANET_NAMES.items()}


# ----------------------------------------------------------------- fixture chart
# Lagna Aries. Hand-derived: house 7 = Libra (lord Venus).
SIGNS = {"Sun": 0, "Moon": 1, "Mars": 3, "Mercury": 2, "Jupiter": 11, "Venus": 2, "Saturn": 6, "Rahu": 8, "Ketu": 2}
NAK = {"Sun": "Sun", "Moon": "Sun", "Mars": "Sun", "Mercury": "Moon", "Jupiter": "Venus", "Venus": "Mercury",
       "Saturn": "Sun", "Rahu": "Jupiter", "Ketu": "Sun"}


def make_facts(signs=None, lagna=0, **extra):
    signs = {**SIGNS, **(signs or {})}
    planets = {n: {"sign": s, "house": (s - lagna) % 12 + 1, "nakshatra": {"lord": NAK[n]}, "dignity": [],
                   "combust": False, "retrograde": False, "vargottama": False} for n, s in signs.items()}
    houses = {h: {"sign": (lagna + h - 1) % 12, "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]}
              for h in range(1, 13)}
    facts = {"lagna": {"sign": lagna}, "planets": planets, "houses": houses,
             "meta": {"birth_time_precision": "exact"}}
    facts.update(extra)
    return facts


def cfg_from(**over):
    d = json.loads((ROOT / "data" / "intents" / "09_MARRIAGE_TIMING.json").read_text())
    d.update(over)
    return IntentConfig.from_dict(d)


def types_of(facts, planet, house, ref="lagna"):
    return {e.rule_id[-2:] for e in links.link_evidence(planet, house, facts, ref)}


# ------------------------------------------------------------------------ links
def test_links_L1_to_L6_fixture():
    f = make_facts()
    expected = {"Venus": {"L1"}, "Mercury": {"L4"}, "Saturn": {"L2", "L6"}, "Mars": {"L3"}, "Moon": {"L6"},
                "Jupiter": {"L5"}, "Sun": {"L3"}, "Rahu": {"L4"}, "Ketu": {"L3", "L4"}}
    for planet, want in expected.items():
        assert types_of(f, planet, 7) == want, planet
    # weights: Lagna 1.0 x base; Moon frame halves it (Moon in Taurus: house 7 from Moon = Scorpio, lord Mars)
    e = links.link_evidence("Venus", 7, f, "lagna")[0]
    assert e.weight == links.LINK_WEIGHTS["L1"] and "LORD:H7" in e.factors and "PLANET:VENUS" in e.factors
    m = [x for x in links.link_evidence("Mars", 7, f, "moon") if x.rule_id == "LINK_L1"][0]
    assert m.weight == links.LINK_WEIGHTS["L1"] * 0.5 and "MOON_LORD:H7" in m.factors


def test_adv_computation():
    assert links.adv([10, 6, 11, 2]) == (1, 5, 9)      # 12th from each, excluding members of E
    assert links.adv([7, 2, 11]) == (1, 6, 10)
    assert links.adv([1]) == (12,)
    f = make_facts()
    bal = links.link_balance("Jupiter", [1], f)         # Jupiter owns/occupies the 12th, only aspects Mars (lord of 1)
    assert bal["adverse_dominates"] and bal["ADV_weight"] > bal["E_weight"] > 0
    assert all(e.direction == -1 for e in bal["ADV"]) and all(e.direction == 1 for e in bal["E"])
    sat = links.link_balance("Saturn", [7], f, refs=("lagna",))
    assert sat["activates"] and not sat["adverse_dominates"]


# ---------------------------------------------------------------------- promise
def promise_facts(strong=True):
    f = make_facts()
    sav = [25] * 12
    sav[6] = 30
    d9_lagna = 0
    if strong:
        venus_d9 = 3                                    # house 4 from D9 Lagna: kendra
        extra = dict(shadbala=[[0] * 7] * 8 + [[1.2] * 7], vimshopaka={"Venus": 12.0},
                     compound_dignity={"Venus": {"sign_lord": "Mercury", "relation": "friend"}})
    else:
        f["planets"]["Venus"].update(sign=5, house=6, dignity=["debilitated"])
        venus_d9 = 7                                    # house 8: dusthana
        extra = dict(shadbala=[[0] * 7] * 8 + [[0.7] * 7], vimshopaka={"Venus": 6.0},
                     compound_dignity={"Venus": {"sign_lord": "Mercury", "relation": "enemy"}})
    f.update(extra, sarvastakavarga=sav,
             vargas={"D9": {"Lagna": {"sign": d9_lagna}, "Venus": {"sign": venus_d9}}})
    return f


def test_promise_gate_levels():
    cfg = cfg_from()
    assert cfg.primary_house == 7 and cfg.primary_varga == "D9"
    strong = promise_gate(promise_facts(True), cfg)
    assert strong.level == PROMISE_STRONG and strong.score >= 3 and not strong.caps_result_type
    weak = promise_gate(promise_facts(False), cfg)
    assert weak.level == PROMISE_WEAK and weak.score < 0 and weak.caps_result_type
    assert weak.evidence and all(isinstance(e, Evidence) for e in weak.evidence)


def test_promise_unavailable_factor_not_fabricated():
    f = promise_facts(True)
    for key in ("compound_dignity", "shadbala", "vimshopaka"):
        f.pop(key)
    res = promise_gate(f, cfg_from())
    names = {fa.name: fa for fa in res.factors}
    assert {"F1_lord_strength", "F2_lord_dignity"} <= set(res.unavailable)
    assert names["F2_lord_dignity"].score == 0 and not names["F2_lord_dignity"].available
    assert res.score == sum(fa.score for fa in res.factors)
    # no data at all for any factor -> NE, not a made-up level
    empty = make_facts()
    res2 = promise_gate(empty, cfg_from(V=[], K=[], E=[7]))
    assert "F1_lord_strength" in res2.unavailable and "F5_karaka" in res2.unavailable


# ----------------------------------------------------------------------- dedup
def ev(*factors, d=1, w=1.0, rid="LINK_L1"):
    return Evidence(rid, "1.0", ("x",), d, w, frozenset(factors), None, "t")


def sup(name, *factors, interval=None, value="S"):
    return PillarResult(name, value, (ev(*factors),), interval)


def ne(name):
    return PillarResult.not_evaluated(name, "test")


STRONG_P = PromiseResult(PROMISE_STRONG, 4)
WEAK_P = PromiseResult(PROMISE_WEAK, -2)


def test_dedup_same_planet_p2_dependent():
    p1 = sup("P1", "PLANET:VENUS", "MOON_NAKSHATRA")
    p2 = sup("P2", "PLANET:VENUS")
    w = converge([p1, p2, ne("P3"), ne("P4")], STRONG_P, cfg_from())
    assert w.n == 1 and w.dependent == ("P2",)
    assert w.pillars[1].dependent and "shares factors with P1" in w.pillars[1].label
    # an independent third pillar does count; Yogini-style shared MOON_NAKSHATRA stays dependent
    p3 = sup("P3", "YEAR_LORD:MARS")
    p4 = sup("P4", "MOON_NAKSHATRA")
    w2 = converge([p1, p2, p3, p4], STRONG_P, cfg_from())
    assert w2.n == 2 and set(w2.dependent) == {"P2", "P4"}


def test_ne_pillars_insufficient_data():
    w = converge([sup("P1", "PLANET:VENUS"), ne("P2"), ne("P3"), ne("P4")], STRONG_P, cfg_from())
    assert w.result_type == "insufficient_data" and w.k_evaluated == 1 and w.n == 1
    assert w.badge == "Traditional convergence: 1/4 (1 of 4 methods evaluated)"
    w2 = converge([sup("P1", "PLANET:A"), sup("P2", "PLANET:B"), sup("P3", "PLANET:C"), ne("P4")], STRONG_P, cfg_from())
    assert w2.badge == "Traditional convergence: 3/4 (3 of 4 methods evaluated)" and w2.result_type == "supportive_period"
    full = converge([sup(f"P{i}", f"PLANET:X{i}") for i in range(1, 5)], STRONG_P, cfg_from())
    assert full.badge == "Traditional convergence: 4/4"


def test_promise_weak_caps_result_type():
    ps = [sup(f"P{i}", f"PLANET:X{i}") for i in range(1, 5)]
    assert converge(ps, STRONG_P, cfg_from()).result_type == "supportive_period"
    capped = converge(ps, WEAK_P, cfg_from())
    assert capped.n == 4 and capped.result_type == "weak_indication"
    assert any("capped" in n for n in capped.notes)
    # an adverse pillar blocks supportive_period -> mixed
    mixed = converge(ps[:3] + [PillarResult("P4", "A", (ev("PLANET:Z", d=-1),))], STRONG_P, cfg_from())
    assert mixed.result_type == "mixed_period" and mixed.conflicting_evidence
    # adverse intents need n >= 3 (config default 3): n = 2 is never 'supportive'
    two = converge(ps[:2] + [ne("P3"), ne("P4")], STRONG_P, cfg_from())
    assert two.result_type != "supportive_period"


def test_no_percentages_anywhere():
    ps = [sup(f"P{i}", f"PLANET:X{i}") for i in range(1, 4)] + [ne("P4")]
    w = converge(ps, WEAK_P, cfg_from())
    assert "%" not in w.badge and "%" not in w.disclaimer and not any("%" in n for n in w.notes)
    assert w.disclaimer == CONVERGENCE_DISCLAIMER
    assert w.kp.value == "NE"                         # KP never counted


def test_window_narrowing():
    p1 = sup("P1", "A", interval=(0, 100))
    p2 = sup("P2", "B", interval=(40, 90))
    p3 = sup("P3", "C", interval=(200, 300))         # no overlap: not forced
    p4 = sup("P4", "D", interval=(50, 60))
    win, notes = narrow_window([p1, p2, p3, p4])
    assert win == (50, 60) and any("P3" in n for n in notes)
    assert narrow_window([p1, ne("P2"), ne("P3"), ne("P4")])[0] == (0, 100)


# ------------------------------------------------------------------------ natal
def test_natal_template_badge():
    f = promise_facts(True)
    f["jaimini"] = {"karakas": {"Darakaraka": "Venus"}, "arudhas": {"A7": 6}, "arudha_lagna": {"sign": 1},
                    "upapada_lagna": {"sign": 10}}
    res = template_N(f, cfg_from(template="N", min_n_for_label=2))
    assert res.badge.startswith("Natal agreement: ") and "/4" in res.badge and "%" not in res.badge
    assert [p.pillar for p in res.pillars] == ["M1", "M2", "M3", "M4"]
    assert res.kp.value == "NE"
    calls = []
    res2 = template_N(f, cfg_from(template="N", min_n_for_label=2), p1_overlay=lambda fa, c: calls.append(1) or ne("P1"))
    assert calls and res2.overlay is not None and res2.n == res.n
    f["meta"]["birth_time_precision"] = "unknown"
    assert template_N(f, cfg_from(template="N", min_n_for_label=2)).result_type == "insufficient_data"


# --------------------------------------------------------------- intent configs
def test_all_61_configs_validate_with_unique_numbers():
    cfgs = intents.load_all()
    assert sorted(cfgs) == list(range(1, 62))
    assert len({c.intent_id for c in cfgs.values()}) == 61
    assert sorted(c.number for c in cfgs.values() if c.phase == 1) == [1, 2, 3, 6, 9, 17, 18, 25, 27, 31, 32, 37, 48, 56, 59, 60, 61]
    for c in cfgs.values():
        assert c.KP["status"] in ("ne", "verify"), c.intent_id      # KP never enabled
        if c.template in ("T_adverse", "T", "N+T"):
            assert c.min_n_for_label >= 3
    assert intents.get("PROMOTION").number == 2 and intents.get("job_offer") is None
    assert intents.get(12).requires_consent and "job_offer" in intents.get(1).forecast_events


@pytest.mark.parametrize("patch,msg", [
    ({"bogus": 1}, "unknown keys"),
    ({"E": [13]}, "outside 1-12"),
    ({"V": ["D99"]}, "unknown value"),
    ({"hooks": ["nope"]}, "unknown value"),
    ({"K": ["Pluto"]}, "unknown value"),
    ({"J": ["A13"]}, "unknown value"),
    ({"min_n_for_label": 2}, ">= 3"),
    ({"TRIG": {"slow": [], "fast": [], "x": 1}}, "unknown keys"),
    ({"KP": {"houses": [2], "negate": [], "status": "ne"}}, "must not list"),
    ({"safety_domain": "x"}, "safety_domain"),
])
def test_intent_config_strict_validation(patch, msg):
    d = json.loads((ROOT / "data" / "intents" / "09_MARRIAGE_TIMING.json").read_text())
    d.update(patch)
    with pytest.raises(IntentConfigError, match=msg):
        IntentConfig.from_dict(d)


# --------------------------------------------------------------------- rule pack
def test_rulepack_consistency():
    rules = rulepack.reload()
    for rid, r in rules.items():
        if r["verify"]:
            assert r["status"] == "disabled_verify" or (r["verified_by"] and r["verified_on"]), rid
        if r["status"] == "enabled":
            assert r["tests"], rid
            for t in r["tests"]:
                path, _, name = t.partition("::")
                test_file = ROOT.parent / path
                assert name and test_file.is_file(), (rid, t)
                assert re.search(rf"def {re.escape(name)}\(", test_file.read_text()), (rid, t)
        assert r["version"] and r["source"]
    verify_ids = [i for i, r in rules.items() if r["verify"]]
    assert verify_ids and all(not rulepack.is_enabled(i) for i in verify_ids)
    assert rulepack.ne_reason(verify_ids[0]) == "rule disabled pending source check"
    assert rulepack.ne_reason("LINK_L1") is None
    with pytest.raises(KeyError):
        rulepack.rule("NO_SUCH_RULE")
    used = set()
    for path in (ROOT / "app" / "astro" / "convergence").glob("*.py"):
        used |= set(re.findall(r'"((?:LINK|ADV|PROMISE|DEDUP|RESULT|WINDOW|NATAL)_[A-Z0-9_]+)"', path.read_text()))
    assert used and used <= set(rules), used - set(rules)


# --------------------------------------------------------------------- registry
def test_registry_legacy_unchanged_and_spec_pointers():
    cov = registry.coverage()
    assert len(cov["intents"]) == 60 and cov["spec"]["count"] == 61
    assert registry.forecast_intent("job_offer")["intent_id"] == "JOB_TIMING"
    assert registry.forecast_intent("marriage")["intent_id"] == "MARRIAGE_TIMING"
    assert registry.forecast_intent(None) is None
    extra = registry.registry()["spec_only_intents"]
    assert sorted(r["spec_intent"] for r in extra) == [4, 7, 8, 10, 11, 13, 15, 16, 20, 22, 23, 24, 29, 30, 36, 39, 40, 43, 46, 51, 52, 55]
    legacy = {r["intent_id"]: r for r in registry.registry()["intents"]}
    for lid, n in (("PROMOTION", 2), ("MANGAL_DOSHA", 12), ("HOUSEWARMING_MUHURTA", 58), ("CURRENT_DASHA", 61)):
        assert legacy[lid]["spec_intent"] == n and registry.spec_intent(lid).number == n
    assert "spec_intent" not in legacy["PANCHANGA"]
    assert registry.spec_intent("GOVT_JOB").number == 4 and registry.spec_intent(99) is None
    for c in intents.load_all().values():                      # every legacy id points back to its config
        for lid in c.legacy_ids:
            assert lid in legacy and (legacy[lid].get("spec_intent") == c.number or c.number in legacy[lid].get("spec_intent_secondary", []))


def test_engine_adds_convergence_facts():
    from app.astro.engine import BirthInput, engine
    facts = engine.compute(BirthInput("t", 1990, 5, 15, 10, 30, 0, 28.6139, 77.209, 5.5, "Delhi"))
    assert len(facts["bhava_bala"]["ratio"]) == 12 and facts["vimshopaka"]["Venus"] > 0
    assert facts["compound_dignity"]["Saturn"]["relation"] == "own"
    res = promise_gate(facts, intents.get(9))
    assert res.level in ("STRONG", "MODERATE", "WEAK") and not res.unavailable
