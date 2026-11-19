"""Engine frame: calculation settings, ephemeris, ayanamsa, varga tables, dasha year."""
import os, sys, uuid, threading
from datetime import date
from functools import partial

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_frame.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import swisseph as swe
from hypothesis import given, strategies as st
from jhora.horoscope.chart import charts

from app.astro import engine as E
from app.astro.engine import BirthInput, engine, birth_fingerprint
from app.astro.settings import CalcSettings, DEFAULT, PRESETS

ARC = 30 * 3600  # arcseconds per sign


def birth(**kw):
    return BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi",
                      settings=CalcSettings(**kw))


def jupiter_md_start(facts) -> date:
    p = next(p for p in facts["vimshottari"]["periods"]
             if p["maha"] == "Jupiter" and p["antar"] == "Jupiter")
    return date.fromisoformat(p["start"])


# ---------- settings object ----------

def test_defaults_use_julian_year_and_keep_legacy_preset():
    d = DEFAULT
    assert (d.ayanamsa, d.node, d.positions, d.dasha_year) == ("LAHIRI", "mean", "true", "julian")
    assert (d.chara_school, d.karaka_scheme, d.colord_rule) == ("KNRao", "7_KNRao", "school")
    assert (d.arudha_exception, d.d24, d.combust_table) == ("standard", "forward", "surya_siddhanta")
    assert d.gandanta_arc == pytest.approx(10 / 3) and d.sandhi_arc == 1.5
    assert set(PRESETS) == {"default", "drik", "jh", "iae", "legacy_tropical"}
    assert PRESETS["legacy_tropical"].dasha_year == "true_tropical"


def test_validation_rejects_unknown_values():
    with pytest.raises(ValueError):
        CalcSettings(ayanamsa="FAGAN")
    with pytest.raises(ValueError):
        CalcSettings.from_preset("nope")
    with pytest.raises(ValueError):
        CalcSettings.from_dict({"bogus": 1})
    with pytest.raises(ValueError):
        CalcSettings(sandhi_arc=0)


@given(st.sampled_from(["LAHIRI", "LAHIRI_ICRC", "LAHIRI_1940", "LAHIRI_VP285", "TRUE_CITRA"]),
       st.sampled_from(["mean", "true"]), st.sampled_from(["forward", "reverse"]))
def test_settings_dict_roundtrip(ay, node, d24):
    cs = CalcSettings(ayanamsa=ay, node=node, d24=d24)
    assert CalcSettings.from_dict(cs.fingerprint_dict()).fingerprint_dict() == cs.fingerprint_dict()


@pytest.mark.parametrize("field,alt", [
    ("ayanamsa", "LAHIRI_ICRC"), ("node", "true"), ("positions", "apparent"),
    ("center", "topocentric"), ("combust_table", "wide_variant"),
    ("dasha_year", "gregorian"), ("chara_school", "PVR"), ("karaka_scheme", "8_Rath"),
    ("colord_rule", "Rath"), ("arudha_exception", "none"), ("d24", "reverse"),
    ("gandanta_arc", 3.0), ("sandhi_arc", 2.0)])
def test_fingerprint_changes_with_every_setting(field, alt):
    assert getattr(DEFAULT, field) != alt
    assert birth_fingerprint(birth()) != birth_fingerprint(birth(**{field: alt}))


# ---------- ayanamsa ----------

def _ay(name, jd):
    E.apply(CalcSettings(ayanamsa=name))
    with E.calc_lock:
        E.apply(CalcSettings(ayanamsa=name))
        return swe.get_ayanamsa_ut(jd)


def test_ayanamsa_variants_vs_lahiri_2022():
    jd = swe.julday(2022, 1, 1, 0)
    base = _ay("LAHIRI", jd)
    for name, expect in (("LAHIRI_1940", -53.0), ("LAHIRI_VP285", 23.0), ("LAHIRI_ICRC", -1.1)):
        assert (_ay(name, jd) - base) * 3600 == pytest.approx(expect, abs=0.5), name
    E.apply(DEFAULT)


def test_icrc_ayanamsa_at_1956_equinox():
    jd = swe.julday(1956, 3, 21, 0)
    _ay("LAHIRI_ICRC", jd)
    with E.calc_lock:
        E.apply(CalcSettings(ayanamsa="LAHIRI_ICRC"))
        with_nut = swe.get_ayanamsa_ex_ut(jd, 0)[1]
        mean = swe.get_ayanamsa_ut(jd)
    # 23 deg 15' 00" (the ICRC value includes nutation; the mean value differs by it)
    assert abs(with_nut - 23.25) * 3600 <= 1.0
    assert abs(mean - 23.25) * 3600 <= 18.0
    E.apply(DEFAULT)


def test_meta_discloses_frame():
    f = engine.compute(birth())
    m = f["meta"]
    assert m["ayanamsa"]["id"] == "LAHIRI" and 23.6 < m["ayanamsa"]["degrees"] < 23.7
    assert "″" in m["ayanamsa"]["dms"]
    assert m["ephemeris"] == "swiss"
    assert (m["node"], m["positions"], m["center"]) == ("mean", "true", "geocentric")
    assert m["dasha_year"] == {"mode": "julian", "days": 365.25}
    assert m["warnings"] == []


def test_high_latitude_warning():
    b = BirthInput("N", 1990, 6, 1, 12, 0, 0, 64.15, -21.9, 0.0, "Reykjavik")
    w = engine.compute(b)["meta"]["warnings"]
    assert any("High latitude" in x and "°/min" in x for x in w)


def test_swiss_ephemeris_files_present():
    for f in ("sepl_18.se1", "semo_18.se1", "seas_18.se1"):
        assert os.path.getsize(os.path.join(E.EPHE_DIR, f)) > 100_000, f
    assert E.ephemeris_in_use(swe.julday(1984, 7, 13, 3.7)) == "swiss"


# ---------- nodes ----------

def test_true_node_mode_works_and_node_check_present():
    mean = engine.compute(birth())
    true = engine.compute(birth(node="true"))
    assert true["meta"]["node"] == "true"
    sep = abs(mean["planets"]["Rahu"]["abs_longitude"] - true["planets"]["Rahu"]["abs_longitude"])
    assert 0.001 < min(sep, 360 - sep) < 3.0       # true node oscillates around the mean
    chk = mean["node_check"]
    assert {"mean", "true", "d1_differs", "d9_differs", "flag", "separation_deg"} <= set(chk)
    assert chk["flag"] == (chk["d1_differs"] or chk["d9_differs"])
    E.apply(DEFAULT)


def test_node_sensitivity_flags_sign_difference():
    # find a date where mean and true node straddle a sign boundary: scan 1 year
    jd0 = swe.julday(2000, 1, 1, 0)
    hits = [E.node_sensitivity(jd0 + i * 3.0) for i in range(120)]
    assert any(h["flag"] for h in hits)
    assert not all(h["flag"] for h in hits)


# ---------- vargas ----------

def test_d30_d3_d45_present():
    v = engine.compute(birth())["vargas"]
    assert {"D3", "D30", "D45"} <= set(v)


def test_d24_forward_vs_reverse():
    fw = engine.compute(birth())["vargas"]["D24"]
    rv = engine.compute(birth(d24="reverse"))["vargas"]["D24"]
    assert fw != rv
    E.apply(DEFAULT)


def _ref(div, sign, arcsec):
    """Table-driven reference: half-open parts in integer arcseconds, 0-based signs
    (Aries=0, so even index = odd sign)."""
    n = {"D2": 2, "D3": 3, "D7": 7, "D9": 9, "D10": 10, "D12": 12, "D24": 24, "D60": 60}[div]
    part = (arcsec * n) // ARC
    odd = sign % 2 == 0
    if div == "D2":   # Leo/Cancer hora: odd sign Sun(Leo) first, even sign Moon(Cancer) first
        return 4 if (part == 0) == odd else 3
    if div == "D3":
        return (sign + 4 * part) % 12
    if div == "D7":
        return (sign + (0 if odd else 6) + part) % 12
    if div == "D9":
        return ({0: 0, 1: 9, 2: 6, 3: 3}[sign % 4] + part) % 12
    if div == "D10":
        return (sign + (0 if odd else 8) + part) % 12
    if div in ("D12", "D60"):
        return (sign + part) % 12
    if div == "D24":
        return ((4 if odd else 3) + part) % 12


VARGA_FN = {
    "D2": partial(charts.hora_chart, chart_method=2), "D3": charts.drekkana_chart,
    "D7": charts.saptamsa_chart, "D9": E.navamsa_chart, "D10": charts.dasamsa_chart,
    "D12": charts.dwadasamsa_chart,
    "D24": partial(charts.chaturvimsamsa_chart, chart_method=1), "D60": charts.shashtyamsa_chart,
}
DIVS = {"D2": 2, "D3": 3, "D7": 7, "D9": 9, "D10": 10, "D12": 12, "D24": 24, "D60": 60}


def test_all_native_varga_parts_match_the_oracle_interior_and_are_half_open():
    from app.astro import vargas
    oracles = {**VARGA_FN, "D1": lambda rows: rows,
               "D4": charts.chaturthamsa_chart, "D6": partial(charts.shashthamsa_chart, chart_method=1),
               "D9": charts.navamsa_chart, "D16": charts.shodasamsa_chart, "D20": charts.vimsamsa_chart,
               "D30": charts.trimsamsa_chart, "D40": charts.khavedamsa_chart, "D45": charts.akshavedamsa_chart}
    for n in vargas.SCHEMES:
        for sign in range(12):
            if n == 30:
                degrees = [0, 5, 10, 18, 25, 30] if sign % 2 == 0 else [0, 5, 12, 20, 25, 30]
                bounds = [d * 3600 for d in degrees]
            else:
                bounds = [-(-part * ARC // n) for part in range(n + 1)]
            for left, right in zip(bounds, bounds[1:]):
                center = (left + right) / 7200
                expected = oracles[f"D{n}"]([["L", (sign, center)]])[0][1][0]
                assert vargas.position(n, sign, left / 3600)[0] == expected
                assert vargas.position(n, sign, (right - 1) / 3600)[0] == expected
            assert vargas.position(n, sign, 30) == vargas.position(n, (sign + 1) % 12, 0)


def _points(n):
    """Every part: its first arcsecond, the arcsecond before it, last arcsecond, midpoint."""
    pts = set()
    for k in range(n + 1):
        b = -(-k * ARC // n)              # ceil(k*ARC/n): first whole arcsecond of part k
        pts.update(a for a in (b - 1, b, b + 1) if 0 <= a < ARC)
        if k < n:
            pts.add((2 * k + 1) * ARC // (2 * n))
    return sorted(pts)


@pytest.mark.parametrize("div", list(DIVS))
def test_varga_exhaustive_vs_reference(div):
    n = DIVS[div]
    bad = []
    for sign in range(12):
        for a in _points(n):
            got = VARGA_FN[div]([["L", (sign, a / 3600)]])[0][1][0]
            if got != _ref(div, sign, a):
                bad.append((sign, a, got, _ref(div, sign, a)))
    assert not bad, bad[:5]


def test_d9_exact_part_boundaries():
    for sign in range(12):
        for a in range(0, ARC, ARC // 9):
            got = VARGA_FN["D9"]([["L", (sign, a / 3600)]])[0][1][0]
            assert got == _ref("D9", sign, a), (sign, a)


def test_sign_end_belongs_to_next_sign_in_varga_reference():
    # 29deg59'59" is last part; exactly 30deg00'00" would be the next sign's first part
    for div, n in DIVS.items():
        assert _ref(div, 0, ARC - 1) != _ref(div, 0, 0) or n == 1
        assert (ARC * n) // ARC == n   # 30deg00'00" is outside the half-open part range [0, n)


# ---------- dasha year ----------

def test_dasha_year_julian_and_savana_shift():
    base = jupiter_md_start(engine.compute(birth()))
    jul = jupiter_md_start(engine.compute(birth(dasha_year="julian")))
    sav = jupiter_md_start(engine.compute(birth(dasha_year="savana_360")))
    assert abs((jul - date(2024, 12, 10)).days) <= 1
    assert abs((base - date(2024, 12, 10)).days) <= 1
    assert 205 <= (jul - sav).days <= 220          # ~212 days earlier
    assert engine.compute(birth(dasha_year="savana_360"))["meta"]["dasha_year"]["days"] == 360.0
    E.apply(DEFAULT)


def test_running_vimshottari_follows_settings():
    run = engine.running_vimshottari(birth(dasha_year="savana_360"), (2026, 1, 1))
    assert run[0]["start"] == "2024-05-11"
    run = engine.running_vimshottari(birth(), (2026, 1, 1))
    assert run[0]["start"] == "2024-12-10"
    E.apply(DEFAULT)


def test_topocentric_moon_shows_parallax():
    """center='topocentric' must move the Moon (diurnal parallax ~0-1°)."""
    geo = engine.compute(birth())
    topo = engine.compute(birth(center="topocentric"))
    assert topo["meta"]["center"] == "topocentric"
    diff = abs(geo["planets"]["Moon"]["abs_longitude"]
               - topo["planets"]["Moon"]["abs_longitude"])
    assert 0.05 < diff < 1.2, f"topocentric lunar parallax {diff}° is implausible"
    E.apply(DEFAULT)


def test_positions_setting_reaches_planet_flags():
    """Regression: drik.PLANET_FLAGS was written to the copied module dict and
    never reached PyJHora's own calls — 'apparent' must differ from 'true'."""
    tru = engine.compute(birth())
    app = engine.compute(birth(positions="apparent"))
    diffs = [abs(tru["planets"][n]["abs_longitude"] - app["planets"][n]["abs_longitude"])
             for n in ("Sun", "Moon", "Mercury")]
    assert any(1e-5 < d < 0.02 for d in diffs)   # aberration ~ arcseconds, not 0, not degrees
    E.apply(DEFAULT)


def test_node_check_reports_chara_and_karaka_flags():
    chk = engine.compute(birth())["node_check"]
    assert {"chara_years_differ", "chara_sequence_differs",
            "karaka_rank_differs"} <= set(chk)
    assert isinstance(chk["chara_years_differ"], bool)
    if chk["chara_years_differ"]:
        assert set(chk["chara_year_diffs"]) <= {"Scorpio", "Aquarius"}
    E.apply(DEFAULT)


def test_combust_table_selection_changes_orb():
    from app.astro.constants import combust_orb
    assert combust_orb(4, table="surya_siddhanta") == 11.0
    assert combust_orb(4, table="wide_variant") == 12.0
    assert combust_orb(6, table="wide_variant") == 16.0
    f = engine.compute(birth(combust_table="wide_variant"))
    assert f["meta"]["arcs"]["combust_table"] == "wide_variant"
    E.apply(DEFAULT)


def test_threads_with_different_settings_do_not_cross_contaminate():
    results = {}

    def work(key, **kw):
        for _ in range(3):
            results[key] = jupiter_md_start(engine.compute(birth(**kw)))
            engine.running_vimshottari(birth(**kw), (2026, 1, 1))

    ts = [threading.Thread(target=work, args=("a",), kwargs={}),
          threading.Thread(target=work, args=("b",), kwargs={"dasha_year": "savana_360"})]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert abs((results["a"] - date(2024, 12, 10)).days) <= 1
    assert (results["a"] - results["b"]).days > 200
    E.apply(DEFAULT)
