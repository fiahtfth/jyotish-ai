"""KP frame (convergence/kp.py): Placidus cusps in the chart's ayanamsa, sub-lords, significators,
report never feeding n."""
from dataclasses import replace
from datetime import date

import pytest
import swisseph as swe

from app.astro.convergence import dedup, intents
from app.astro.convergence import kp as conv_kp
from app.astro.convergence.types import NE, S, W, Evidence, PillarResult
from app.astro.engine import BirthInput, engine

ARJUN = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0, lat=13.0827,
                   lon=80.2707, tz_offset=5.5, place_label="Chennai", birth_time_precision="exact")
ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19,
         "Mercury": 17}
NAK = 40.0 / 3.0


def _star_sub(lon):
    """Independent KP star/sub lord: nakshatra of 13deg20' split in Vimshottari proportion."""
    k = int(lon // NAK)
    off = lon - k * NAK
    first = k % 9
    acc = 0.0
    for i in range(9):
        lord = ORDER[(first + i) % 9]
        seg = NAK * YEARS[lord] / 120.0
        if off < acc + seg:
            return ORDER[first], lord, off - acc
        acc += seg
    return ORDER[first], ORDER[(first + 8) % 9], 0.0


@pytest.fixture(scope="module")
def chart():
    return conv_kp.kp_chart(ARJUN)


def test_cusp_sublord_reference_chart(chart):
    # direct swe: Lahiri (the chart's settings) + Placidus, sidereal
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    jd_ut = swe.julday(1990, 5, 15, 6.25 - 5.5)
    cusps, _ = swe.houses_ex(jd_ut, 13.0827, 80.2707, b"P", swe.FLG_SIDEREAL)
    assert len(chart["cusps"]) == 12 and chart["frame"]["houses"] == "Placidus"
    assert chart["frame"]["ayanamsa"] == "LAHIRI"
    for row, lon in zip(chart["cusps"], cusps[:12]):
        assert abs(row["longitude"] - lon % 360) < 1e-5, row["house"]
        star, sub, off = _star_sub(lon % 360)
        assert row["star_lord"] == star
        if off > 1e-4:                       # not on a sub boundary
            assert row["sub_lord"] == sub, (row["house"], row["sub_lord"], sub)
        assert row["sub_sub_lord"] in YEARS
    # cusp 1 is the chart's Lagna (same frame as the Vedic chart)
    facts = engine.compute(ARJUN)
    lagna = facts["lagna"]["sign"] * 30 + facts["lagna"]["degree"]
    assert abs(chart["cusps"][0]["longitude"] - lagna) < 1e-3
    # planets keep the engine's longitudes
    assert abs(chart["planets"]["Moon"]["longitude"] - facts["planets"]["Moon"]["abs_longitude"]) < 1e-4


def test_significator_table_shape(chart):
    table = chart["significators"]
    assert [r["house"] for r in table] == list(range(1, 13))
    for r in table:
        assert set(r["levels"]) == {"1", "2", "3", "4"}
        assert r["levels"]["4"] == [r["owner"]] and r["levels"]["2"] == r["occupants"]
        assert r["owner"] == chart["cusps"][r["house"] - 1]["sign_lord"]
        assert all(chart["planets"][o]["house"] == r["house"] for o in r["occupants"])
        assert all(chart["planets"][p]["star_lord"] in r["occupants"] for p in r["levels"]["1"])
        assert all(chart["planets"][p]["star_lord"] == r["owner"] for p in r["levels"]["3"])
    sig = chart["planet_significations"]
    assert set(sig) == set(YEARS)
    for name, s in sig.items():
        assert s["houses"] == sorted({h for lv in s["by_level"].values() for h in lv})
    # every planet occupies exactly one house
    assert sum(len(r["occupants"]) for r in table) == 9
    # legacy display keys kept (frontend KpChart)
    assert len(chart["segments"]) == 249 and chart["ruling_planets"]["weekday_lord"]


def test_kp_report_not_evaluated_until_verified(chart):
    facts = engine.compute(ARJUN)
    cfg = intents.get("MARRIAGE_TIMING")
    rep = conv_kp.kp_report(facts, ARJUN, cfg, when=date(2026, 6, 1))
    assert rep["label"] == "KP: not evaluated" and rep["value"] == NE
    assert "source" in rep["reason"]
    c = rep["computed"]
    assert c["cusp_sub_lord"] == chart["cusps"][6]["sub_lord"]
    assert len(c["dasha_lords"]) == 3 and c["verdict_if_enabled"] in ("supportive", "not supportive")
    assert rep["negate"] == [1, 6, 10]
    # an intent with KP 'ne' is never computed
    ne = conv_kp.kp_report(facts, ARJUN, intents.get("JOB_CHANGE"))
    assert ne["value"] == NE and ne["computed"] is None


def test_kp_report_computes_when_enabled(monkeypatch):
    facts = engine.compute(ARJUN)
    cfg = intents.get("JOB_TIMING")
    monkeypatch.setattr(conv_kp, "_kp_enabled", lambda c: None)
    rep = conv_kp.kp_report(facts, ARJUN, cfg, when=date(2026, 6, 1))
    assert rep["label"] in ("KP: supportive", "KP: not supportive")
    assert rep["value"] == (S if rep["computed"]["verdict_if_enabled"] == "supportive" else W)
    assert rep["negate"] == [1, 5, 9]            # 12th from 2,6,10,11 minus the favourable set
    assert {e.rule_id for e in rep["pillar"].evidence} == {"KP_CUSP_SUBLORD_PROMISE", "KP_DASHA_SIGNIFICATION"}


def test_kp_never_changes_n():
    cfg = intents.get("MARRIAGE_TIMING")
    ev = lambda f: Evidence("X", "1", (), 1, 1.0, frozenset({f}))
    pillars = [PillarResult("P1", S, (ev("PLANET:VENUS"),)), PillarResult("P2", S, (ev("ARUDHA:UL"),)),
               PillarResult("P3", W), PillarResult("P4", W)]
    base = dedup.converge(pillars, None, cfg)
    with_kp = dedup.converge(pillars, None, cfg, kp=PillarResult("KP", S, (ev("KP:CSL:H7"),)))
    assert (base.n, base.result_type, base.k_evaluated) == (with_kp.n, with_kp.result_type, with_kp.k_evaluated) \
        == (2, "weak_indication", 4)
    assert dedup.kp_label(with_kp.kp) == "KP: supportive" and dedup.kp_label(base.kp) == "KP: not evaluated"


def test_kp_unknown_time_not_evaluated():
    b = replace(ARJUN, birth_time_precision="unknown")
    with pytest.raises(conv_kp.KPUnavailable):
        conv_kp.kp_chart(b)
    facts = dict(engine.compute(ARJUN))
    facts["meta"] = {**facts["meta"], "birth_time_precision": "unknown"}
    rep = conv_kp.kp_report(facts, b, intents.get("MARRIAGE_TIMING"))
    assert rep["value"] == NE and "birth time" in rep["reason"]
