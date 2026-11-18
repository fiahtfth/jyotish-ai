"""Varshaphala: exact solar return, annual chart, Varsheshwara, Mudda, Tajika pillar."""
import os
import uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_varsha.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)

import pytest
import swisseph as swe

from app.astro import pillars, varsha
from app.astro import constants as K
from app.astro.engine import BirthInput, apply, calc_lock, engine
from jhora.panchanga import drik


def _birth():
    return BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi")


def _facts(b):
    return engine.compute(b)


def _sun_lon(jd_utc):
    return swe.calc_ut(jd_utc, swe.SUN, drik.PLANET_FLAGS)[0][0]


def test_return_jd_is_exact_solar_return():
    """The return instant puts the sidereal Sun back on its natal longitude."""
    b = _birth()
    with calc_lock:
        apply(b.settings)
        natal = _sun_lon(varsha.return_jd(b, 0) - b.tz_offset / 24)
        for k in (1, 18, 42, 60):
            r = varsha.return_jd(b, k) - b.tz_offset / 24
            diff = abs((_sun_lon(r) - natal + 180) % 360 - 180)
            assert diff * 3600 < 0.05, f"return {k} off by {diff * 3600:.4f} arcsec"


def test_varsha_zero_is_the_natal_year():
    b = _birth()
    f = _facts(b)
    v = varsha.varsha(b, 0, natal_lagna_sign=f["lagna"]["sign"])
    assert v["year_of_life"] == 1 and v["completed_years"] == 0
    assert v["muntha"]["sign"] == f["lagna"]["sign"]
    assert v["varsha_lagna"]["sign"] == f["lagna"]["sign"]


def test_muntha_counts_completed_years():
    b = _birth()
    f = _facts(b)
    lagna = f["lagna"]["sign"]
    for k in (5, 42):
        v = varsha.varsha(b, k, natal_lagna_sign=lagna)
        assert v["muntha"]["sign"] == (lagna + k) % 12
        assert v["muntha"]["house_from_varsha_lagna"] == \
            (v["muntha"]["sign"] - v["varsha_lagna"]["sign"]) % 12 + 1


def test_year_lord_comes_from_the_five_office_bearers():
    b = _birth()
    f = _facts(b)
    v = varsha.varsha(b, 42, natal_lagna_sign=f["lagna"]["sign"])
    yl = v["year_lord"]
    assert yl["planet"] in yl["candidates"]
    assert set(v["office_bearers"]) == {
        "luminary_sign_lord", "natal_lagna_lord", "muntha_lord",
        "varsha_lagna_lord", "trirasi_lord"}
    assert yl["rule"] in {"single_benefic_aspects", "single_malefic_aspects",
                          "pancha_vargeeya_bala", "first_candidate"}
    if yl["rule"] == "single_benefic_aspects":
        assert yl["shortlist"] == [yl["planet"]]
    assert isinstance(v["night"], bool)
    assert set(v["pancha_vargeeya_bala"]) == set(K.PLANET_NAMES[p] for p in range(7))


def test_pancha_vargeeya_bala_and_precision_year_lord_agree():
    """precision._annual_lord must return the same planet id as varsheshwara."""
    from app.astro import precision
    b = _birth()
    f = _facts(b)
    v = varsha.varsha(b, 30, natal_lagna_sign=f["lagna"]["sign"])
    lord_id = precision._annual_lord(v["positions"], v["return"]["jd"], b, 30,
                                     f["lagna"]["sign"])
    assert lord_id == v["year_lord"]["id"]


def test_tajika_yoga_report_is_labeled():
    b = _birth()
    v = varsha.varsha(b, 42, natal_lagna_sign=_facts(b)["lagna"]["sign"])
    tj = v["tajika"]
    for y in tj["yogas"]:
        assert y["yoga"] and y["planets"] and y["detail"]
        assert all(p in K.PLANET_NAMES.values() for p in y["planets"])
    assert set(tj["not_evaluated"]) == {"Khallasaar", "Dutthottha-Davira", "Durapha"}


def test_mudda_periods_tile_the_year():
    b = _birth()
    v = varsha.varsha(b, 42, natal_lagna_sign=_facts(b)["lagna"]["sign"])
    periods = v["mudda"]["periods"]
    assert periods and all(len(p["lords"]) == 2 for p in periods)
    for prev, cur in zip(periods, periods[1:]):
        assert cur["start"] == prev["end"], "mudda periods must tile without gaps"
    # every mudda period sits inside (or across the boundary of) the varsha year
    assert periods[0]["start"][:4] in (v["return"]["local"][:4],
                                     str(int(v["return"]["local"][:4]) - 1))


def test_pillar_uses_the_annual_chart():
    b = _birth()
    f = _facts(b)
    r = pillars.pillar_tajika(f, b, "career", date(2026, 1, 1), date(2027, 6, 30))
    assert "Varshaphala" in r["method_note"]
    assert any("varsha year" in x for x in r["rules"])
    assert any("Muntha" in x for x in r["evidence"])
    assert r["verdict"] in {"support", "conflict", "neutral"}


def test_pillar_falls_back_and_says_so(monkeypatch):
    b = _birth()
    f = _facts(b)
    def broken(*a, **kw):
        raise RuntimeError("annual chart unavailable")
    monkeypatch.setattr(varsha, "varsha", broken)
    r = pillars.pillar_tajika(f, b, "career", date(2026, 1, 1), date(2027, 6, 30))
    assert "fallback" in r["method_note"]
    assert any("annual chart error" in x for x in r["rules"])


def test_solar_return_precision_independent_of_ayanamsa_setting():
    """Return instant must follow the *configured* ayanamsa, not a hard-coded one."""
    from app.astro.settings import CalcSettings
    b = BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi",
                   settings=CalcSettings(ayanamsa="LAHIRI_VP285"))
    with calc_lock:
        apply(b.settings)
        natal = _sun_lon(varsha.return_jd(b, 0) - b.tz_offset / 24)
        r = varsha.return_jd(b, 42) - b.tz_offset / 24
        diff = abs((_sun_lon(r) - natal + 180) % 360 - 180)
        assert diff * 3600 < 0.05
