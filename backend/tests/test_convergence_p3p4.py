"""P3 (Tajika + Sudarshana) and P4 (Ashtakavarga/Kakshya/fast triggers/Tarabala) on hand-built inputs."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.astro import constants as K
from app.astro import precision, transits, varsha
from app.astro.convergence import rulepack, timing_p3, timing_p4
from app.astro.convergence.types import A, NE, S, W, IntentConfig
from app.astro.settings import DEFAULT as DEFAULT_SETTINGS

D = date.fromisoformat
YEAR = (D("2025-05-15"), D("2026-05-14"))
BIRTH = SimpleNamespace(settings=DEFAULT_SETTINGS, place_label="X", lat=0.0, lon=0.0, tz_offset=0.0,
                        year=1990, month=5, day=15, hour=6, minute=0, second=0, birth_time_precision="exact")
# Lagna Aries; marriage E=7 (Libra, lord Venus). Venus in Gemini, Moon in Aries.
SIGNS = {"Sun": 0, "Moon": 0, "Mars": 3, "Mercury": 2, "Jupiter": 11, "Venus": 2, "Saturn": 6, "Rahu": 8, "Ketu": 2}


def cfg(**kw):
    d = {"intent_id": "TEST_INTENT", "number": 9, "phase": 1, "template": "T", "E": [7], "E_optional": [],
         "E_adverse_explicit": [], "K": ["Venus"], "V": ["D9"], "J": ["DK"],
         "TAJ": {"houses": [7], "muntha_supportive": [7]}, "TRIG": {"slow": ["Saturn"], "fast": ["Mars"]},
         "KP": {"houses": [], "negate": [], "status": "ne"}, "hooks": [], "min_n_for_label": 3,
         "requires_consent": False, "safety_domain": "marriage_relationship", "legacy_ids": [],
         "forecast_events": []}
    d.update(kw)
    return IntentConfig.from_dict(d)


def facts(precision_="exact", venus_nak=(5, "Ardra"), moon_nak=4):
    planets = {}
    for i, (n, s) in enumerate(SIGNS.items()):
        idx, name = (venus_nak if n == "Venus" else ((moon_nak, K.NAKSHATRAS[moon_nak]) if n == "Moon" else (0, "Ashwini")))
        planets[n] = {"sign": s, "degree": 10.0 + i, "house": s + 1, "dignity": [], "combust": False,
                      "nakshatra": {"index": idx, "name": name, "lord": "Sun"}}
    bav = [[3] * 12 for _ in range(7)]
    return {"lagna": {"sign": 0, "degree": 5.0}, "planets": planets,
            "meta": {"birth_time_precision": precision_},
            "binnashtakavarga": bav, "sarvastakavarga": [30] * 12, "prastara_ashtakavarga": {"stub": 1},
            "jaimini": {"karakas": {}}, "vargas": {}}


# ------------------------------------------------------------------ P3
def annual(pvb_venus=20.0, muntha_house=7, mudda=True):
    pos = [["L", (0, 1.0)], [0, (1, 1.0)], [1, (4, 1.0)], [2, (0, 3.0)], [3, (1, 2.0)], [4, (6, 4.0)],
           [5, (6, 9.0)], [6, (9, 2.0)], [7, (3, 1.0)], [8, (9, 1.0)]]
    periods = [{"lords": ["Venus", "Venus"], "start": "2025-05-15", "end": "2025-06-30"},
               {"lords": ["Venus", "Sun"], "start": "2025-06-30", "end": "2025-08-01"},
               {"lords": ["Sun", "Sun"], "start": "2025-08-01", "end": "2025-09-01"}] if mudda else []
    return {"positions": pos, "muntha": {"sign": (muntha_house - 1) % 12, "house_from_varsha_lagna": muntha_house},
            "year_lord": {"planet": "Jupiter"},
            "pancha_vargeeya_bala": {"Venus": pvb_venus, "Mars": 12.0, "Jupiter": 14.0, "Sun": 5.0, "Moon": 5.0,
                                     "Mercury": 5.0, "Saturn": 5.0},
            "tajika": {"yogas": [{"yoga": "Ithasala", "planets": ["Venus", "Mars"], "type": "Vartamana"}]},
            "mudda": {"periods": periods}, "completed_years": 35}


@pytest.fixture
def p3_stubs(monkeypatch):
    state = {"annual": annual(), "sud": {"lagna": 6, "moon": 6, "sun": 7}}
    monkeypatch.setattr(timing_p3, "_year_bounds", lambda birth, cy: YEAR)
    monkeypatch.setattr(precision, "completed_solar_years", lambda birth, d: 35)
    monkeypatch.setattr(varsha, "varsha", lambda birth, cy, natal_lagna_sign=None: state["annual"])
    monkeypatch.setattr(precision, "sudarshana_year_signs", lambda birth, when: state["sud"])
    return state


def test_p3_supportive_ithasala_and_override_muntha(p3_stubs):
    r = timing_p3.evaluate(facts(), BIRTH, cfg(), D("2025-06-01"), D("2025-12-31"))
    assert len(r) == 1 and r[0].pillar == "P3" and r[0].value == S and r[0].interval == YEAR
    ids = {e.rule_id for e in r[0].evidence if e.direction > 0}
    assert {"P3_ANNUAL_ELORD_ITHASALA", "P3_MUNTHA_INTENT_OVERRIDE", "P3_VARSHESHWARA_LINK"} <= ids
    # annual facts are namespaced so they never collide with natal factors in de-dup
    assert all(f.startswith(("VARSHA:", "SUDARSHANA:", "PLANET:", "KARAKA")) for e in r[0].evidence
               for f in e.factors)
    # generic Muntha favourable/adverse sets are VERIFY -> disabled -> reported NE, not applied
    gen = [e for e in r[0].evidence if e.rule_id == "P3_MUNTHA_FAVOURABLE_SETS"]
    assert gen and gen[0].ne_reason == rulepack.DISABLED_REASON and gen[0].direction == 0


def test_p3_weak_annual_lord_adverse(p3_stubs):
    p3_stubs["annual"] = annual(pvb_venus=4.0, muntha_house=8)
    r = timing_p3.evaluate(facts(), BIRTH, cfg(), D("2025-06-01"), D("2025-12-31"))[0]
    weak = [e for e in r.evidence if e.rule_id == "P3_ANNUAL_ELORD_ITHASALA"]
    assert weak and weak[0].direction == -1
    # A needs an adverse Muntha, which only the (disabled) generic rule can give -> never fabricated
    assert r.value == W


def test_p3_sudarshana_score(p3_stubs):
    score, evs = timing_p3.sudarshana_score(facts(), BIRTH, cfg(), D("2025-09-01"))
    # Libra is the 7th from Lagna and from Moon (both Aries); Scorpio from Sun? Sun in Aries -> 7th = Libra(6), not 7
    assert score == 2 and all(e.rule_id == "P3_SUDARSHANA_TRIPLE" for e in evs)
    p3_stubs["sud"] = {"lagna": 6, "moon": 6, "sun": 6}
    assert timing_p3.sudarshana_score(facts(), BIRTH, cfg(), D("2025-09-01"))[0] == 3


def test_p3_mudda_windows(p3_stubs):
    r = timing_p3.evaluate(facts(), BIRTH, cfg(), D("2025-06-01"), D("2025-12-31"))[0]
    md = [e for e in r.evidence if e.rule_id == "P3_MUDDA_WINDOWS"]
    assert md and md[0].interval == (D("2025-05-15"), D("2025-08-01"))       # Venus MD rows collapsed
    assert all(YEAR[0] <= e.interval[0] <= e.interval[1] <= YEAR[1] for e in md)


def test_p3_mode_b_ne(p3_stubs):
    r = timing_p3.evaluate(facts("unknown"), BIRTH, cfg(), D("2025-06-01"), D("2025-12-31"))
    assert len(r) == 1 and r[0].value == NE and "birth time" in r[0].ne_reason


# ------------------------------------------------------------------ P4
def scan_stub(by_planet):
    def scan(birth, start, end, planet):
        sign, events, slices = by_planet.get(planet, (5, [], []))
        return {"start": f"{start}T00:00:00Z", "end": f"{end}T00:00:00Z", "initial_sign": sign,
                "events": events, "kakshya_slices": slices}
    return scan


START, END = D("2025-01-01"), D("2025-12-31")
SLICE = {"start": "2025-02-01T00:00:00Z", "end": "2025-03-15T00:00:00Z", "sign_index": 6, "index": 3}


def test_p4_bav_kakshya_supportive(monkeypatch):
    f = facts()
    f["binnashtakavarga"][6][6] = 5                                   # Saturn BAV in Libra = 5 (strong)
    monkeypatch.setattr(transits, "scan", scan_stub({"Saturn": (6, [], [SLICE])}))
    monkeypatch.setattr(precision, "_kakshya_charged", lambda pr, pid, sign, deg: True)
    res = timing_p4.evaluate(f, BIRTH, cfg(TRIG={"slow": ["Saturn"], "fast": []}), START, END)
    s = [r for r in res if r.value == S]
    assert len(s) == 1 and s[0].interval == (D("2025-02-01"), D("2025-03-15"))
    ids = {e.rule_id for e in s[0].evidence}
    assert {"P4_TRIGGER_INGRESS", "P4_BAV_THRESHOLDS", "P4_KAKSHYA_NARROWING"} <= ids
    bav = next(e for e in s[0].evidence if e.rule_id == "P4_BAV_THRESHOLDS")
    assert bav.weight == 2.0 and "SAV:HOUSE:7" in bav.factors       # 1.5 strong + 0.5 for SAV >= 28
    # uncharged kakshya -> W only
    monkeypatch.setattr(precision, "_kakshya_charged", lambda pr, pid, sign, deg: False)
    res = timing_p4.evaluate(f, BIRTH, cfg(TRIG={"slow": ["Saturn"], "fast": []}), START, END)
    assert [r.value for r in res] == [W]


def test_p4_bav_adverse(monkeypatch):
    f = facts()
    f["binnashtakavarga"][6][6] = 1
    monkeypatch.setattr(transits, "scan", scan_stub({"Saturn": (6, [], [SLICE])}))
    res = timing_p4.evaluate(f, BIRTH, cfg(TRIG={"slow": ["Saturn"], "fast": []}), START, END)
    assert [r.value for r in res] == [A]
    assert any(e.rule_id == "P4_BAV_THRESHOLDS" and e.direction == -1 for e in res[0].evidence)


def test_p4_fast_trigger_aspect(monkeypatch):
    monkeypatch.setattr(transits, "scan", scan_stub({"Mars": (0, [], [])}))   # Mars in Aries aspects Libra (7th)
    res = timing_p4.evaluate(facts(), BIRTH, cfg(TRIG={"slow": [], "fast": ["Mars"]}), START, END)
    assert res and res[0].value == W
    fast = [e for e in res[0].evidence if e.rule_id == "P4_FAST_TRIGGERS"]
    assert fast and "HOUSE:7" in fast[0].factors


def test_p4_tarabala(monkeypatch):
    # Venus natal nakshatra Ardra (5); Moon nakshatra 4 -> tara 2 (Sampat, supportive)
    assert precision.tara_of(5, 4)[0] == 2
    ev = [{"kind": "nakshatra_ingress", "at": "2025-04-01T00:00:00Z", "from": "Mrigashira", "to": "Ardra"}]
    f = facts()
    f["binnashtakavarga"][6][6] = 4
    monkeypatch.setattr(transits, "scan", scan_stub({"Saturn": (6, ev, [])}))
    res = timing_p4.evaluate(f, BIRTH, cfg(TRIG={"slow": ["Saturn"], "fast": []}), START, END)
    tara = [e for r in res for e in r.evidence if e.rule_id == "P4_TARABALA"]
    assert tara and tara[0].interval[0] == D("2025-04-01") and "NAKSHATRA:VENUS" in tara[0].factors


def test_p4_mode_b_ne():
    res = timing_p4.evaluate(facts("unknown"), BIRTH, cfg(), START, END)
    assert len(res) == 1 and res[0].value == NE and "birth time" in res[0].ne_reason


def test_p3_p4_rules_in_pack():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app" / "astro" / "convergence"
    used = set()
    for path in list(root.glob("*.py")) + list((root / "hooks").glob("*.py")):
        used |= set(re.findall(r'"((?:P[1-4]|KP|HOOK|T)_[A-Z0-9_]+)"', path.read_text()))
    assert used and used <= set(rulepack.load()), used - set(rulepack.load())
