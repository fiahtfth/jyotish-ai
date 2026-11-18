"""Jaimini: Chara dasha (three schools), co-lord rules, arudhas, chara karakas."""
import os, sys, uuid

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_jaimini.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from jhora import utils
from jhora.horoscope.chart import charts
from jhora.panchanga import drik

from app.astro import engine as E, jaimini as J
from app.astro.engine import BirthInput, engine
from app.astro.settings import CalcSettings, DEFAULT

Ar, Ta, Ge, Cn, Le, Vi, Li, Sc, Sg, Cp, Aq, Pi = range(12)
SUN, MOON, MARS, MERC, JUP, VEN, SAT, RAHU, KETU = range(9)
PARK = Pi   # unspecified planets sit here; tests never use Pisces as a subject sign


def R(lagna, **where):
    """Synthetic rasi in PyJHora row format; where = {planet_id: sign | (sign, deg)}."""
    pos = {p: (PARK, 5.0) for p in range(9)}
    for p, v in where.items():
        pid = int(p[1:])
        pos[pid] = v if isinstance(v, tuple) else (v, 5.0)
    return [["L", (lagna, 5.0)]] + [[p, pos[p]] for p in range(9)]


def bhadohi(**kw):
    return BirthInput("Bhadohi", 1984, 7, 13, 9, 14, 0, 25.4, 82.57, 5.5, "Bhadohi",
                      settings=CalcSettings(**kw))


def bhadohi_rasi():
    b = bhadohi()
    with E.calc_lock:
        E.apply(DEFAULT)
        place = drik.Place("Bhadohi", b.lat, b.lon, b.tz_offset)
        jd = utils.julian_day_number((b.year, b.month, b.day), (b.hour, b.minute, b.second))
        return charts.rasi_chart(jd, place), jd


# ---------- Chara dasha ----------

def test_bhadohi_first_period_leo_two_years_forward():
    rasi, jd = bhadohi_rasi()
    ps = J.chara_periods(rasi, jd, "KNRao", 365.2425)
    assert ps[0]["sign"] == Le and ps[0]["years"] == 2
    assert [p["sign"] for p in ps[:3]] == [Le, Vi, Li]          # forward
    assert ps[0]["start_jd"] == jd
    assert ps[0]["end_jd"] == pytest.approx(jd + 2 * 365.2425)


def test_own_sign_lord_gets_twelve():
    for school in J.SCHOOLS:
        assert J.sign_years(R(Ar, P2=Ar), Ar, school)[0] == 12


def test_knrao_ignores_exaltation_pvr_and_rath_add_one():
    # Cancer lord Moon exalted in Taurus; Cancer counts backward: Cn,Ge,Ta = 3 -> 2
    rasi = R(Cn, P1=Ta)
    assert J.sign_years(rasi, Cn, "KNRao")[0] == 2
    assert J.sign_years(rasi, Cn, "PVR")[0] == 3
    assert J.sign_years(rasi, Cn, "Rath")[0] == 3
    # debilitated Moon in Scorpio: backward count 9 -> 8; PVR/Rath 7; KNRao unchanged
    rasi = R(Cn, P1=Sc)
    assert J.sign_years(rasi, Cn, "KNRao")[0] == 8
    assert J.sign_years(rasi, Cn, "PVR")[0] == 7


def test_floor_differs_for_pvr_and_rath():
    # Sagittarius counts forward to its lord Jupiter in Capricorn (debilitated): 2 -> 1 year.
    rasi = R(Sg, P4=Cp)
    assert J.sign_years(rasi, Sg, "KNRao")[0] == 1
    assert J.sign_years(rasi, Sg, "PVR")[0] == 1      # 1 - 1 = 0, PVR floor is 1
    assert J.sign_years(rasi, Sg, "Rath")[0] == 0     # Rath floor is 0


def test_cycle_two_rules():
    rasi, jd = bhadohi_rasi()
    kn = J.chara_periods(rasi, jd, "KNRao", 365.2425)
    assert [p["years"] for p in kn[12:]] == [p["years"] for p in kn[:12]]
    for school in ("PVR", "Rath"):
        ps = J.chara_periods(rasi, jd, school, 365.2425)
        assert len(ps) == 24
        for a, b in zip(ps[:12], ps[12:]):
            assert a["sign"] == b["sign"] and b["years"] == 12 - a["years"]
        assert all(1 <= p["years"] <= 12 or (school == "Rath") for p in ps[:12])


def test_antardasha_start_rules():
    rasi, jd = bhadohi_rasi()
    kn = J.chara_periods(rasi, jd, "KNRao", 365.2425)[0]
    assert kn["sign"] == Le and kn["antardashas"][0]["sign"] == Vi and kn["antardashas"][-1]["sign"] == Le
    pv = J.chara_periods(rasi, jd, "PVR", 365.2425)[0]
    assert pv["antardashas"][0]["sign"] == pv["sign"]
    assert sum(a["end_jd"] - a["start_jd"] for a in pv["antardashas"]) == pytest.approx(
        pv["end_jd"] - pv["start_jd"])


@pytest.mark.parametrize("school", J.SCHOOLS)
def test_running_chara_works_for_every_school(school):
    rows = engine.running_chara(bhadohi(chara_school=school), (2026, 1, 1))
    assert len(rows) == 2 and len(rows[0]["signs"]) == 1 and len(rows[1]["signs"]) == 2
    assert rows[0]["start"] <= "2026-01-01" < rows[0]["end"]
    E.apply(DEFAULT)


def test_knrao_default_has_no_exaltation_adjustment():
    # Bhadohi: Saturn (Aquarius lord) is exalted in Libra; KNRao must not add a year.
    rasi, jd = bhadohi_rasi()
    kn = {p["sign"]: p["years"] for p in J.chara_periods(rasi, jd, "KNRao", 365.2425)[:12]}
    pv = {p["sign"]: p["years"] for p in J.chara_periods(rasi, jd, "PVR", 365.2425)[:12]}
    assert kn[Cp] + 1 == pv[Cp]


# ---------- co-lord branches ----------

@pytest.mark.parametrize("rule", J.SCHOOLS)
def test_colord_both_in_sign_twelve_years(rule):
    rasi = R(Ar, P2=Sc, P8=Sc)
    assert J.stronger_colord(rasi, Sc, rule)[1] == J.BOTH_IN_SIGN
    assert J.sign_years(rasi, Sc, rule)[0] == 12


@pytest.mark.parametrize("rule", J.SCHOOLS)
def test_colord_one_in_sign_uses_other(rule):
    assert J.stronger_colord(R(Ar, P2=Sc, P8=Ge), Sc, rule) == (KETU, J.ONE_IN_SIGN)
    assert J.stronger_colord(R(Ar, P2=Ge, P8=Sc), Sc, rule) == (MARS, J.ONE_IN_SIGN)
    assert J.stronger_colord(R(Ar, P6=Aq, P7=Ge), Aq, rule) == (RAHU, J.ONE_IN_SIGN)
    assert J.stronger_colord(R(Ar, P6=Ge, P7=Aq), Aq, rule) == (SAT, J.ONE_IN_SIGN)


def test_aquarius_colord_pair():
    assert J.stronger_colord(R(Ar, P6=Ge, P7=(Vi, 5.0), P0=Ge, P1=Ge), Aq, "KNRao") == (
        SAT, "KNRAO.COLORD.ASSOC")


def test_knrao_colord_steps():
    assert J.stronger_colord(R(Ar, P2=Ge, P0=Ge, P1=Ge, P8=Vi), Sc, "KNRao") == (MARS, "KNRAO.COLORD.ASSOC")
    assert J.stronger_colord(R(Ar, P2=(Ge, 20.5), P8=(Vi, 10.5)), Sc, "KNRao") == (MARS, "KNRAO.COLORD.DEGREE")
    assert J.stronger_colord(R(Ar, P2=(Ge, 10.2), P8=(Vi, 10.7)), Sc, "KNRao") == (KETU, "KNRAO.COLORD.SECONDS")


def test_rath_colord_steps():
    rule = "Rath"
    assert J.stronger_colord(R(Ar, P2=Ge, P8=Ge), Sc, rule) == (MARS, "RATH.COLORD.TOGETHER")
    assert J.stronger_colord(R(Ar, P2=Ge, P0=Ge, P8=Vi), Sc, rule) == (MARS, "RATH.COLORD.MORE_PLANETS")
    # Jupiter in Taurus aspects Libra (Ketu) but not adjacent Aries (Mars)
    assert J.stronger_colord(R(Ar, P2=Ar, P8=Li, P4=Ta), Sc, rule) == (KETU, "RATH.COLORD.JUP_MER_DISPOSITOR")
    # Mars in own Aries; Ketu in Libra; no benefic contact
    assert J.stronger_colord(R(Ar, P2=Ar, P8=Li), Sc, rule) == (MARS, "RATH.COLORD.DIGNITY")
    assert J.stronger_colord(R(Ar, P2=Ta, P8=Ar), Sc, rule) == (MARS, "RATH.COLORD.MODALITY")
    assert J.stronger_colord(R(Ar, P2=(Ge, 5.0), P8=(Vi, 20.0)), Sc, rule) == (KETU, "RATH.COLORD.DEGREE")
    assert J.stronger_colord(R(Ar, P2=(Ge, 10.0), P8=(Vi, 10.0)), Sc, rule)[1] == "RATH.COLORD.DASA_YEARS"


def test_pvr_colord_steps():
    rule = "PVR"
    assert J.stronger_colord(R(Ar, P2=Ge, P0=Ge, P8=Vi), Sc, rule) == (MARS, "PVR.COLORD.CONJUNCTION")
    assert J.stronger_colord(R(Ar, P2=Cp, P8=Ar), Sc, rule) == (MARS, "PVR.COLORD.EXALTED")
    assert J.stronger_colord(R(Ar, P2=Ge, P8=Cn), Sc, rule) == (MARS, "PVR.COLORD.MODALITY")
    assert J.stronger_colord(R(Ar, P2=Ge, P8=Vi), Sc, rule)[1] == "PVR.COLORD.DASA_YEARS"
    # equal modality and equal years: dasha falls through, arudha compares degrees
    tie = R(Ar, P2=(Sg, 8.0), P8=(Ge, 20.0), P4=Ar, P3=Li)
    assert J.stronger_colord(tie, Sc, rule, "dasha")[1] == J.FALLBACK
    assert J.stronger_colord(tie, Sc, rule, "arudha") == (KETU, "PVR.COLORD.ARUDHA_DEGREE")


def test_colord_rejects_unknown_rule_and_purpose():
    with pytest.raises(ValueError):
        J.stronger_colord(R(Ar), Sc, "nope")
    with pytest.raises(ValueError):
        J.stronger_colord(R(Ar), Sc, "PVR", "other")


# ---------- arudhas ----------

def test_arudha_shortcut_table():
    # Aries lagna, house = Aries (lord Mars); Mars placed k signs from the house
    for k, expect_offset in ((1, 9), (7, 9), (4, 3), (10, 3)):
        mars_sign = (k - 1) % 12
        a1 = J.arudhas(R(Ar, P2=mars_sign), "standard")[0]
        assert a1 == expect_offset % 12, (k, a1)
    # non-exception example: Mars in the 2nd -> same count again = 3rd
    assert J.arudhas(R(Ar, P2=Ta), "standard")[0] == Ge
    # exception="none" leaves the raw result
    assert J.arudhas(R(Ar, P2=Ar), "none")[0] == Ar
    assert J.arudhas(R(Ar, P2=Li), "none")[0] == Ar     # 7th lands on the house itself


def test_bhadohi_arudhas():
    f = engine.compute(bhadohi())
    ju = f["jaimini"]
    assert ju["arudha_lagna"]["sign_name"] == "Aries"
    assert ju["upapada_lagna"]["sign_name"] == "Taurus"
    assert ju["A10"]["sign_name"] == "Virgo"
    assert ju["arudha_rules"] == {"exception": "standard", "colord_rule": "KNRao"}


def test_arudha_exception_setting_is_honoured():
    std = engine.compute(bhadohi())["jaimini"]["arudhas"]
    none = engine.compute(bhadohi(arudha_exception="none"))["jaimini"]["arudhas"]
    assert std != none
    E.apply(DEFAULT)


def test_colord_rule_setting_reaches_arudhas():
    f = engine.compute(bhadohi(colord_rule="Rath"))
    assert f["jaimini"]["arudha_rules"]["colord_rule"] == "Rath"
    E.apply(DEFAULT)


# ---------- karakas ----------

def test_karaka_schemes():
    base = R(Ar, P0=(Ar, 1.5), P1=(Ar, 2.5), P2=(Ar, 3.5), P3=(Ar, 4.5), P4=(Ar, 5.5),
             P5=(Ar, 6.5), P6=(Ar, 7.5), P7=(Ar, 25.0))
    k7 = J.karakas(base, "7_KNRao")
    assert k7["karakas"]["Atmakaraka"] == "Saturn" and k7["karakas"]["Darakaraka"] == "Sun"
    assert len(k7["karakas"]) == 7
    k8 = J.karakas(base, "8_Rath")           # Rahu 25 -> 30-25 = 5 degrees
    assert len(k8["karakas"]) == 8 and "Pitrukaraka" in k8["karakas"]
    assert "Rahu" in k8["karakas"].values()
    assert len(J.karakas(base, "7or8_PVR")["karakas"]) == 7   # all integer degrees differ
    dup = R(Ar, P0=(Ar, 1.2), P1=(Ar, 1.8), P2=(Ar, 3.5), P3=(Ar, 4.5), P4=(Ar, 5.5),
            P5=(Ar, 6.5), P6=(Ar, 7.5), P7=(Ar, 25.0))
    assert len(J.karakas(dup, "7or8_PVR")["karakas"]) == 8


def test_karaka_tie_reported():
    rasi = R(Ar, P0=(Ar, 10.0001), P1=(Ar, 10.0002), P2=(Ar, 20.0), P3=(Ar, 15.0),
             P4=(Ar, 5.0), P5=(Ar, 2.0), P6=(Ar, 25.0))
    ties = J.karakas(rasi)["ties"]
    assert len(ties) == 1
    assert sorted(ties[0]["pair"]) == ["Moon", "Sun"] and ties[0]["margin_arcsec"] < 1
    assert J.karakas(R(Ar, P0=(Ar, 1.0), P1=(Ar, 3.0), P2=(Ar, 5.0), P3=(Ar, 7.0), P4=(Ar, 9.0),
                       P5=(Ar, 11.0), P6=(Ar, 13.0)))["ties"] == []


def test_facts_expose_karaka_scheme_and_ties():
    f = engine.compute(bhadohi())
    assert f["jaimini"]["karaka_scheme"] == "7_KNRao"
    assert isinstance(f["jaimini"]["karaka_ties"], list)
    assert len(f["jaimini"]["karakas"]) == 7
    f8 = engine.compute(bhadohi(karaka_scheme="8_Rath"))
    assert len(f8["jaimini"]["karakas"]) == 8
    E.apply(DEFAULT)
