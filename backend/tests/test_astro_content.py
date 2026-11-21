"""Astro content fixes: functional roles, yogas, node scoring, transit states,
natal career reading, year labels, gochara snapshot."""
import copy
import os, sys, uuid
from datetime import date, timedelta

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_content.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import swisseph as swe

from app.astro import constants as K, classical, pillars, precision, yogas
from app.astro.engine import BirthInput, _dignity, apply as apply_settings, calc_lock, engine
from app.astro.settings import DEFAULT
from app.chat import career

NAMES = list(K.PLANET_NAMES.values())


@pytest.fixture(scope="module")
def ref():
    b = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0,
                   lat=13.0827, lon=80.2707, tz_offset=5.5, place_label="Chennai",
                   birth_time_precision="exact")
    return b, engine.compute(b)


def synth(lagna, signs):
    planets = {}
    for n in NAMES:
        s = signs.get(n, 11)
        planets[n] = {"sign": s, "house": (s - lagna) % 12 + 1, "combust": False,
                      "dignity": _dignity(NAMES.index(n), s, 5.0)}
    houses = {h: {"sign": (lagna + h - 1) % 12,
                  "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]} for h in range(1, 13)}
    return {"planets": planets, "houses": houses, "lagna": {"sign": lagna}}


# ---------- functional table / roles ----------

def test_taurus_row_has_sun_and_saturn_and_source():
    row = K.FUNCTIONAL[1]
    assert {0, 6} <= row["benefics"] and row["yogakaraka"] == 6
    assert row["source"] == "BPHS ch.34" and row["notes"]
    assert all(r["source"] == "BPHS ch.34" for r in K.FUNCTIONAL.values())


def test_lagna_lord_is_never_malefic_in_effective_table():
    for sign, row in K.FUNCTIONAL.items():
        assert K.SIGN_LORD[sign] in row["benefics"] and K.SIGN_LORD[sign] not in row["malefics"]


def test_dual_roles_surface_in_facts(ref):
    _, f = ref
    fn = f["functional"]
    assert {"Sun", "Saturn"} <= set(fn["benefics"])
    assert {"yogakaraka", "badhaka"} <= set(fn["roles"]["Saturn"])
    assert fn["roles"]["Venus"][0] == "lagna_lord" and "malefic_by_lordship" in fn["roles"]["Venus"]
    assert "Venus" not in fn["malefics"] and fn["lagna_lord"] == "Venus"
    assert fn["badhaka"]["lord"] == "Saturn"


def test_min_age_exposed():
    assert K.min_age_for_domain("relationship") == 21
    assert K.min_age_for_domain("nonexistent") == 0


# ---------- nodes ----------

def test_nodes_never_retrograde(ref):
    _, f = ref
    for n in ("Rahu", "Ketu"):
        assert f["planets"][n]["retrograde"] is False
        assert f["planets"][n]["node_note"]


def test_node_scored_once_through_proxies(ref):
    b, f = ref
    rahu_md = next(p for p in f["vimshottari"]["periods"] if p["maha"] == "Rahu")
    # a window inside one antardasha: three sample dates see the same lords
    ad = next(p for p in f["vimshottari"]["periods"] if p["maha"] == "Rahu" and p["antar"] == "Rahu")
    a0 = date.fromisoformat(ad["start"]) + timedelta(days=5)
    a1 = date.fromisoformat(ad["end"]) - timedelta(days=5)
    wide = pillars.pillar_parashari(f, b, "finance", a0, a1)
    narrow = pillars.pillar_parashari(f, b, "finance", a0, a0)
    assert wide["weights"] == narrow["weights"] and wide["conflicts"] == narrow["conflicts"]
    assert not any("Rahu placed in house" in x or "Rahu rules" in x or "Rahu debilitated" in x
                   for x in wide["evidence"])
    assert any("proxies" in r and "not read as retrograde" in r for r in wide["rules"])
    # each proxy planet is credited once: no duplicate evidence line
    assert len(wide["evidence"]) == len(set(wide["evidence"]))


# ---------- transit states ----------

def _fake_transits(monkeypatch, saturn_sign):
    pos = {"Jupiter": {"sign": 0, "degree": 5.0}, "Saturn": {"sign": saturn_sign, "degree": 5.0},
           "Sun": {"sign": 5, "degree": 5.0}, "Mars": {"sign": 5, "degree": 5.0}}
    monkeypatch.setattr(pillars.engine, "transit_positions", lambda *a, **k: pos)


def test_ashtama_counted_once_per_window(ref, monkeypatch):
    b, f = ref
    moon = f["planets"]["Moon"]["sign"]
    _fake_transits(monkeypatch, (moon + 7) % 12)
    r = pillars.pillar_micro_timing(f, b, "career", date(2026, 1, 1), date(2026, 12, 31))
    assert sum("ashtama" in e for e in r["evidence"]) == 1
    assert not any("kantaka" in e or "sade sati" in e for e in r["evidence"])


def test_kantaka_and_sade_sati_are_separate_flags(ref, monkeypatch):
    b, f = ref
    moon = f["planets"]["Moon"]["sign"]
    _fake_transits(monkeypatch, (moon + 3) % 12)
    r = pillars.pillar_micro_timing(f, b, "career", date(2026, 1, 1), date(2026, 12, 31))
    assert sum("kantaka" in e for e in r["evidence"]) == 1
    _fake_transits(monkeypatch, (moon + 11) % 12)
    r = pillars.pillar_micro_timing(f, b, "career", date(2026, 1, 1), date(2026, 12, 31))
    assert sum("sade sati" in e for e in r["evidence"]) == 1
    assert pillars.saturn_moon_states(8, 3) == ["ashtama"]
    assert pillars.saturn_moon_states(8, 11) == ["kantaka"]
    assert pillars.saturn_moon_states(8, 9) == ["sade_sati"]


def test_transit_aspect_is_reported_separately(ref, monkeypatch):
    b, f = ref
    # Saturn three signs behind the 10th-house sign aspects it (3rd aspect: Saturn 3/7/10)
    tenth = f["houses"][10]["sign"]
    _fake_transits(monkeypatch, (tenth - 2) % 12)
    r = pillars.pillar_micro_timing(f, b, "career", date(2026, 1, 1), date(2026, 12, 31))
    assert sum("Saturn aspects house 10" in x for x in r["rules"]) == 1


# ---------- year labels / audit metadata ----------

def test_solar_return_labelled_consistently(ref):
    b, f = ref
    assert precision.completed_solar_years(b, date(2026, 6, 1)) == 36
    ith = precision._ithasala_triggers(f, b, date(2026, 6, 1), date(2026, 6, 30))
    row = next(y for y in ith["year_lords"] if y["varsha_start"] == "2026-05-15")
    assert row["varsha_year"] == row["completed_years"] == 36
    assert row["label"] == pillars.varsha_label(36)
    t = pillars.pillar_tajika(f, b, "career", date(2026, 6, 1), date(2026, 6, 30))
    assert any(r.startswith(f"{pillars.varsha_label(36)} (return 2026-05-15") for r in t["rules"])


def test_disclaimer_is_audit_only(ref):
    b, f = ref
    r = pillars.evaluate(f, b, "career", date(2026, 6, 1), date(2026, 6, 30))
    assert r["convergence_disclaimer"] == pillars.CONVERGENCE_DISCLAIMER       # compat
    assert pillars.CONVERGENCE_DISCLAIMER in r["limitations"]
    assert r["audit"]["disclaimer"] == pillars.CONVERGENCE_DISCLAIMER
    assert "convergence_disclaimer" in r["audit_only"]
    assert pillars.CONVERGENCE_DISCLAIMER not in r["audit"]["llm_visible_limitations"]


# ---------- yogas ----------

def test_reference_chart_yogakaraka_raja_yoga(ref):
    _, f = ref
    y = next(x for x in f["yogas"] if x["id"] == "RAJA_YOGA.YOGAKARAKA.SATURN")
    assert y["level"] == "classical"
    assert {"RAJA.YOGAKARAKA_IN_TRIKONA_9", "RAJA.YOGAKARAKA_OWN_OR_EXALTED",
            "RAJA.YOGAKARAKA_VARGOTTAMA"} <= set(y["conditions_fired"])
    assert y["source"]
    assert any(t["id"] == y["id"] for t in classical.natal_patterns(f)["yogas"])


def test_dhana_yoga_2l_11l_conjunction():
    # Aries lagna: 2L Venus and 11L Saturn together in Libra
    f = synth(0, {"Venus": 6, "Saturn": 6})
    d = next(x for x in yogas.detect(f) if x["id"] == "DHANA_YOGA.L2_L11")
    assert "DHANA.LORD_2_LORD_11_CONJUNCTION" in d["conditions_fired"]
    assert d["level"] == "classical" and d["primary_link"] is True


def test_dhana_yoga_exchange_and_mutual_aspect():
    # 2L Venus in Aquarius (Saturn's) and 11L Saturn in Taurus (Venus's): exchange
    f = synth(0, {"Venus": 10, "Saturn": 1})
    d = next(x for x in yogas.detect(f) if x["id"] == "DHANA_YOGA.L2_L11")
    assert "DHANA.LORD_2_LORD_11_EXCHANGE" in d["conditions_fired"]


def test_raja_yoga_kendra_trikona_conjunction():
    # Aries lagna: 4L Moon with 5L Sun in Leo is conjunction? Moon in Leo, Sun in Leo
    f = synth(0, {"Moon": 4, "Sun": 4})
    ids = {x["id"]: x for x in yogas.detect(f)}
    assert "RAJA.KENDRA_TRIKONA_CONJUNCTION" in ids["RAJA_YOGA.MOON_SUN"]["conditions_fired"]


def test_pancha_mahapurusha_synthetic():
    f = synth(0, {"Mars": 9})          # Mars exalted in Capricorn, 10th from Aries
    p = next(x for x in yogas.detect(f) if x["id"] == "PANCHA_MAHAPURUSHA.RUCHAKA")
    assert "PMP.RUCHAKA.EXALTED" in p["conditions_fired"] and p["level"] == "classical"
    f = synth(0, {"Mars": 4})          # no strength -> none
    assert not any(x["id"].startswith("PANCHA") for x in yogas.detect(f))


def test_chandra_mangala():
    f = synth(0, {"Moon": 2, "Mars": 2})
    assert any(x["id"] == "CHANDRA_MANGALA" for x in yogas.detect(f))


def test_lakshmi_disabled_by_default():
    f = synth(0, {"Jupiter": 3, "Mars": 0})    # 9L exalted in a kendra, strong Lagna lord
    assert not any(x["id"] == "LAKSHMI" for x in yogas.detect(f))
    assert any(x["id"] == "LAKSHMI" and x["verified"] is False
               for x in yogas.detect(f, include_unverified=True))


# ---------- education facts ----------

def test_education_block(ref):
    _, f = ref
    e = f["education"]
    assert set(e["houses"]) == {4, 5, 9}
    assert e["houses"][5]["lord"] == "Mercury" and e["mercury"]["house"] == 12
    assert "dignity" in e["jupiter"]
    assert e["d24"]["lagna"] and e["d24"]["lagna_lord"] and e["d24"]["lagna_lord_in_d24"]["house"] >= 1


# ---------- natal career reading / promise ----------

def test_career_reading_is_fuller(ref):
    b, f = ref
    text, audit = career._chart_reading(f, b, True)
    rf = audit["reading_facts"]
    assert rf["tenth_house_planets"] == ["Mars"] and "Mars sits in the 10th house" in text
    assert "Counted from the Moon, the 10th is Virgo, ruled by Mercury" in text
    assert rf["tenth_from_moon"]["lord"] == "Mercury"
    assert "the Lagna is Pisces" in text and rf["d10"]["lagna"] == "Pisces"
    assert rf["d10"]["tenth_lord_house"] == 7 and "7th house of D10" in text


def test_wealth_promise_reads_11th_lord(ref):
    _, f = ref
    grade, tbl = classical.promise(f, "finance")
    row = next(r for r in tbl["rows"] if "(secondary)" in r[1])
    assert row[1].startswith("H11") and row[2].startswith("Jupiter")
    weak = copy.deepcopy(f)
    weak["planets"]["Jupiter"]["dignity"] = ["debilitated"]
    _, tbl2 = classical.promise(weak, "finance")
    assert next(r for r in tbl2["rows"] if "(secondary)" in r[1])[4] == "Limited"
    strong = copy.deepcopy(f)
    strong["planets"]["Jupiter"]["dignity"] = ["exalted"]
    _, tbl3 = classical.promise(strong, "finance")
    assert next(r for r in tbl3["rows"] if "(secondary)" in r[1])[4] == "Support"


# ---------- gochara ----------

def test_gochara_now_matches_swiss_ephemeris(ref):
    b, f = ref
    today = date(2026, 11, 20)
    g = precision.gochara_now(f, b, today)
    with calc_lock:
        apply_settings(b.settings)
        jd = swe.julday(today.year, today.month, today.day, 12.0 - b.tz_offset)
        flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        want = {n: int((swe.calc_ut(jd, body, flags)[0][0] % 360) // 30)
                for n, body in (("Saturn", swe.SATURN), ("Jupiter", swe.JUPITER), ("Rahu", swe.MEAN_NODE))}
        apply_settings(b.settings)
    want["Ketu"] = (want["Rahu"] + 6) % 12
    for n, sign in want.items():
        assert g["planets"][n]["sign"] == sign, n
    moon, lagna = f["planets"]["Moon"]["sign"], f["lagna"]["sign"]
    sat = g["planets"]["Saturn"]
    assert sat["house_from_moon"] == (want["Saturn"] - moon) % 12 + 1
    assert sat["house_from_lagna"] == (want["Saturn"] - lagna) % 12 + 1
    assert g["kantaka"] is True and g["ashtama"] is False and g["sade_sati"] is False


def test_yoga_status_and_graceful_missing_keys():
    f = synth(0, {"Venus": 6, "Saturn": 6})
    d = next(x for x in yogas.detect(f) if x["id"] == "DHANA_YOGA.L2_L11")
    assert d["status"] == "active" and "Dhana" in d["name"]
    # debilitated participant without Neecha Bhanga -> cancelled
    deb = {"planets": {"Moon": {"dignity": ["debilitated"]}, "Mars": {"dignity": []}}}
    cm = yogas._status([{"id": "CHANDRA_MANGALA", "level": "classical", "participants": ["Moon", "Mars"]}], deb)[0]
    assert cm["status"] == "cancelled" and cm["cancelled_by"]
    # hand-built facts with no optional keys do not raise
    bare = {"planets": f["planets"], "houses": f["houses"], "lagna": f["lagna"]}
    assert isinstance(yogas.detect(bare), list)
    assert yogas.detect({"planets": {}, "houses": {}, "lagna": {"sign": 0}}) == []


def test_tajika_aspects_exclude_2_12_and_6_8():
    from app.astro import varsha
    for gap, expected in {0: True, 1: False, 2: True, 3: True, 4: True, 5: False,
                          6: True, 7: False, 8: True, 9: True, 10: True, 11: False}.items():
        assert varsha._aspects(0, gap) is expected, gap
        assert varsha._aspects(5, (5 + gap) % 12) is expected, gap
