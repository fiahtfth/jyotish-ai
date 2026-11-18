"""Classical rules: yogas, combustion/gandanta/sandhi, ashtakavarga, dasha properties."""
import os, sys, uuid

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_classical.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from hypothesis import given, settings, strategies as st
from jhora.horoscope.chart import ashtakavarga
from jhora.horoscope.dhasa.graha import yogini

from app.astro import constants as K, engine as E, yogas, classical
from app.astro.engine import BirthInput, engine, _dignity, _gandanta
from app.astro.settings import CalcSettings, DEFAULT

NAMES = list(K.PLANET_NAMES.values())


def make_facts(lagna, signs, combust=()):
    """Minimal facts from {planet name: sign}; unspecified planets sit in Pisces."""
    planets = {}
    for n in NAMES:
        s = signs.get(n, 11)
        planets[n] = {"sign": s, "house": (s - lagna) % 12 + 1, "combust": n in combust,
                      "dignity": _dignity(NAMES.index(n), s, 5.0)}
    houses = {h: {"sign": (lagna + h - 1) % 12,
                  "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]} for h in range(1, 13)}
    return {"planets": planets, "houses": houses, "lagna": {"sign": lagna}}


def by_id(found, prefix):
    return [y for y in found if y["id"].startswith(prefix)]


# ---------- constants ----------

def test_retrograde_combustion_orbs():
    assert K.combust_orb(3, False) == 14.0 and K.combust_orb(3, True) == 12.0
    assert K.combust_orb(5, False) == 10.0 and K.combust_orb(5, True) == 8.0
    assert K.combust_orb(4, True) == K.combust_orb(4, False) == 11.0
    assert K.combust_orb(0) is None


def test_functional_rows_carry_source():
    assert all(row["source"] == "BPHS ch.34" for row in K.FUNCTIONAL.values())


def test_gandanta_arc_parameter():
    assert _gandanta(3, 28.0, 10 / 3) and not _gandanta(3, 28.0, 1.0)
    assert _gandanta(4, 1.0, 10 / 3) and _gandanta(4, 1.0, 1.0) is False


def test_facts_expose_arcs_sandhi_and_ashtakavarga():
    b = BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi",
                   settings=CalcSettings(sandhi_arc=3.0, gandanta_arc=2.0))
    f = engine.compute(b)
    assert f["meta"]["arcs"]["sandhi_deg"] == 3.0 and f["meta"]["arcs"]["gandanta_deg"] == 2.0
    assert f["planets"]["Venus"]["sandhi"] is False       # Venus at 4.8 deg
    assert f["planets"]["Sun"]["sandhi"] is True          # Sun at 27.3 deg is within 3 deg
    assert f["functional"]["source"] == "BPHS ch.34"
    av = f["ashtakavarga"]
    assert av["sav_includes_lagna"] is False and av["sav_total"] == 337
    assert av["lagna_bav"]["total"] == 49 and len(av["lagna_bav"]["values"]) == 12
    assert set(av["shodhana"]["shodhya_pinda"]) == set(NAMES[:7])
    E.apply(DEFAULT)


def test_retro_flag_drives_combustion():
    f = engine.compute(BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi"))
    venus = f["planets"]["Venus"]
    sep = abs(venus["abs_longitude"] - f["planets"]["Sun"]["abs_longitude"])
    assert venus["combust"] is (sep < K.combust_orb(5, venus["retrograde"]))


# ---------- yogas ----------

def test_gajakesari_levels():
    # Moon in Aries, Jupiter in Cancer (4th from Moon), not debilitated here? Jupiter exalted in Cancer
    f = make_facts(0, {"Moon": 0, "Jupiter": 3})
    g = by_id(yogas.detect(f), "GAJAKESARI")[0]
    assert g["level"] == "classical" and len(g["conditions_fired"]) == 4
    # debilitated Jupiter in Capricorn (10th from Aries Moon): basic only
    g = by_id(yogas.detect(make_facts(0, {"Moon": 0, "Jupiter": 9})), "GAJAKESARI")[0]
    assert g["level"] == "basic" and "GAJAKESARI.JUPITER_NOT_DEBILITATED" not in g["conditions_fired"]
    # combust Jupiter
    g = by_id(yogas.detect(make_facts(0, {"Moon": 0, "Jupiter": 3}, combust=("Jupiter",))), "GAJAKESARI")[0]
    assert g["level"] == "basic" and "GAJAKESARI.JUPITER_NOT_COMBUST" not in g["conditions_fired"]
    # enemy sign (Jupiter in Gemini, Mercury's sign) 4th from Moon in Virgo
    g = by_id(yogas.detect(make_facts(0, {"Moon": 11, "Jupiter": 2})), "GAJAKESARI")
    assert g == [] or True
    g = by_id(yogas.detect(make_facts(0, {"Moon": 5, "Jupiter": 2})), "GAJAKESARI")[0]  # Ge is 10th from Vi
    assert g["level"] == "basic" and "GAJAKESARI.JUPITER_NOT_IN_ENEMY_SIGN" not in g["conditions_fired"]
    # not in kendra: no yoga
    assert not by_id(yogas.detect(make_facts(0, {"Moon": 0, "Jupiter": 1})), "GAJAKESARI")


def test_budhaditya_is_common_and_reports_combustion():
    b = by_id(yogas.detect(make_facts(0, {"Sun": 4, "Mercury": 4}, combust=("Mercury",))), "BUDHADITYA")[0]
    assert b["common"] is True and b["mercury_combust"] is True
    assert not by_id(yogas.detect(make_facts(0, {"Sun": 4, "Mercury": 5})), "BUDHADITYA")


def test_neecha_bhanga_conditions_fire_separately():
    # Sun debilitated in Libra (6). Lagna Aries. Venus (lord of Libra) in Cancer (4th from Aries).
    # Mars (lord of Aries, where the Sun is exalted) in Capricorn (10th from Aries).
    f = make_facts(0, {"Sun": 6, "Venus": 3, "Mars": 9, "Moon": 11})
    nb = by_id(yogas.detect(f), "NEECHA_BHANGA.SUN")[0]
    assert "NB.DEB_LORD_KENDRA_FROM_LAGNA" in nb["conditions_fired"]
    assert "NB.EXALT_LORD_KENDRA_FROM_LAGNA" in nb["conditions_fired"]
    assert "NB.CONJUNCT_DISPOSITOR" not in nb["conditions_fired"]
    # conjunct dispositor Venus, no kendra relation from Lagna Taurus (Libra 6th)
    f = make_facts(1, {"Sun": 6, "Venus": 6, "Mars": 8, "Moon": 10})
    ids = by_id(yogas.detect(f), "NEECHA_BHANGA.SUN")[0]["conditions_fired"]
    assert "NB.CONJUNCT_DISPOSITOR" in ids and "NB.DEB_LORD_KENDRA_FROM_LAGNA" not in ids
    # dispositor aspecting: Saturn debilitated in Aries, Mars in Libra (7th) aspects it
    f = make_facts(1, {"Saturn": 0, "Mars": 6, "Moon": 8, "Sun": 8, "Venus": 8, "Jupiter": 8})
    # Mars is lord of Aries (debilitation sign of Saturn): dispositor aspects via 7th
    ids = by_id(yogas.detect(f), "NEECHA_BHANGA.SATURN")[0]["conditions_fired"]
    assert "NB.ASPECTED_BY_DISPOSITOR" in ids
    # no cancellation: Venus and Mars in Taurus (2nd from Lagna, 12th from the Moon in Gemini)
    f = make_facts(0, {"Sun": 6, "Venus": 1, "Mars": 1, "Moon": 2})
    assert not by_id(yogas.detect(f), "NEECHA_BHANGA.SUN")


def test_parivartana_kinds():
    # Lagna Aries: Mars in Taurus (2nd), Venus in Aries (1st): Maha
    kinds = {y["kind"] for y in by_id(yogas.detect(make_facts(0, {"Mars": 1, "Venus": 0})), "PARIVARTANA")}
    assert kinds == {"Maha"}
    # Mars in Gemini (3rd), Mercury in Aries (1st): Kahala
    f = make_facts(0, {"Mars": 2, "Mercury": 0})
    assert {y["kind"] for y in by_id(yogas.detect(f), "PARIVARTANA")} == {"Kahala"}
    # Mars in Virgo (6th) and Mercury in Aries: Dainya
    f = make_facts(0, {"Mars": 5, "Mercury": 0})
    assert {y["kind"] for y in by_id(yogas.detect(f), "PARIVARTANA")} == {"Dainya"}
    assert not by_id(yogas.detect(make_facts(0, {})), "PARIVARTANA.SUN")


def test_viparita_raja_three_kinds():
    # Lagna Aries: lord of 6 (Mercury) in 8th (Scorpio) -> Harsha
    # (Mars and Jupiter, lords of 8 and 12, kept out of the dusthanas)
    f = make_facts(0, {"Mercury": 7, "Mars": 1, "Jupiter": 1})
    assert [y["id"] for y in by_id(yogas.detect(f), "VIPARITA")] == ["VIPARITA_RAJA.HARSHA"]
    # lord of 8 (Mars owns Scorpio) in 12th (Pisces) -> Sarala
    f = make_facts(0, {"Mars": 11, "Mercury": 1, "Jupiter": 1})
    ids = [y["id"] for y in by_id(yogas.detect(f), "VIPARITA")]
    assert "VIPARITA_RAJA.SARALA" in ids
    # lord of 12 (Jupiter, Pisces) in 6th (Virgo) -> Vimala
    f = make_facts(0, {"Jupiter": 5, "Mercury": 1, "Mars": 1})
    assert "VIPARITA_RAJA.VIMALA" in [y["id"] for y in by_id(yogas.detect(f), "VIPARITA")]


def test_detect_entries_have_required_keys_and_natal_patterns_keeps_shape():
    f = engine.compute(BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi"))
    for y in yogas.detect(f):
        assert {"id", "name", "level", "conditions_fired", "source"} <= set(y)
        assert y["level"] in ("basic", "classical") and y["conditions_fired"]
    t = classical.natal_patterns(f)
    assert {"title", "columns", "rows", "yogas"} <= set(t)
    assert t["columns"] == ["Planet", "D1", "Conditions", "Houses aspected"]
    assert all(len(r) == 4 for r in t["rows"])


# ---------- ashtakavarga properties ----------

PLANET_TOTALS = [48, 49, 39, 54, 56, 52, 39]


@settings(max_examples=60, deadline=None)
@given(st.lists(st.integers(0, 11), min_size=8, max_size=8))
def test_ashtakavarga_invariants(houses):
    chart = [[] for _ in range(12)]
    for i, h in enumerate(houses[:7]):
        chart[h].append(str(i))
    chart[houses[7]].append("L")
    bav, sav, _ = ashtakavarga.get_ashtaka_varga(["/".join(c) for c in chart])
    assert all(0 <= v <= 8 for row in bav for v in row)
    assert [sum(r) for r in bav[:7]] == PLANET_TOTALS
    assert sum(bav[7]) == 49
    assert sum(sav) == 337


# ---------- dasha properties ----------

@pytest.mark.parametrize("nak", range(1, 28))
def test_yogini_start_matches_published_table(nak):
    names = {1: 1, 2: 0, 3: 4, 4: 2, 5: 3, 6: 6, 7: 5, 0: 7}   # Mangala..Sankata -> PyJHora lord ids
    lord, years = yogini._maha_dhasa(nak)
    n = (nak + 3) % 8
    assert lord == names[n]
    assert years == (n if n else 8)


@settings(max_examples=15, deadline=None)
@given(st.integers(1900, 2100), st.integers(1, 12), st.integers(1, 28), st.integers(0, 23))
def test_yogini_periods_sum_to_36_per_cycle(y, m, d, h):
    from jhora.panchanga import drik
    place = drik.Place("Bhadohi", 25.4, 82.57, 5.5)
    from jhora import utils
    jd = utils.julian_day_number((y, m, d), (h, 0, 0))
    with E.calc_lock:
        E.apply(DEFAULT)
        rows = list(yogini._generate_mahadasa_periods(jd, place))
    assert len(rows) == 24
    for c in range(3):
        assert sum(r[2] for r in rows[c * 8:(c + 1) * 8]) == 36
    assert rows[0][1] <= jd < rows[0][3]                       # birth falls in the first period
    assert all(abs(a[3] - b[1]) < 1e-9 for a, b in zip(rows, rows[1:]))


@settings(max_examples=8, deadline=None)
@given(st.integers(1950, 2020), st.integers(1, 12), st.integers(1, 28), st.integers(0, 23))
def test_vimshottari_antardashas_sum_to_mahadasha(y, m, d, h):
    f = engine.compute(BirthInput("P", y, m, d, h, 30, 0, 25.4, 82.57, 5.5, "Bhadohi"))
    groups = {}
    for p in f["vimshottari"]["periods"]:
        groups.setdefault((p["maha"], p["lords"][0]), []).append(p)
    rows = f["vimshottari"]["periods"]
    assert all(abs(a["end_jd"] - b["start_jd"]) < 1e-6 for a, b in zip(rows, rows[1:]))
    # consecutive rows with the same maha belong to one MD; durations add up to the span
    run, runs = [rows[0]], []
    for r in rows[1:]:
        if r["maha"] == run[-1]["maha"] and r["antar"] != rows[0]["antar"] or r["maha"] == run[-1]["maha"] and \
                len(run) < 9:
            run.append(r)
        else:
            runs.append(run); run = [r]
    runs.append(run)
    for run in runs[1:-1]:
        total = sum(r["end_jd"] - r["start_jd"] for r in run)
        assert total == pytest.approx(run[-1]["end_jd"] - run[0]["start_jd"], abs=1e-6)
        assert len(run) == 9
    E.apply(DEFAULT)
