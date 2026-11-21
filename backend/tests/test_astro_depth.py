"""Astro depth: Mangal dosha, strength, varga discipline, bhava, dasha craft, gochara,
Jaimini depth, new yogas, special points and the time-unknown digest."""
import os
import sys
import uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test_depth.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.astro import (bhava, constants as K, dasha_craft, digest, dosha, gochara, jaimini as J,
                       report as RP, special_points as SP, strength as S, varga_discipline as VD, yogas)
from app.astro.engine import BirthInput, _dignity, engine

NAMES = list(K.PLANET_NAMES.values())
TODAY = date(2026, 11, 20)


@pytest.fixture(scope="module")
def ref():
    b = BirthInput(name="Arjun", year=1990, month=5, day=15, hour=6, minute=15, second=0,
                   lat=13.0827, lon=80.2707, tz_offset=5.5, place_label="Chennai",
                   birth_time_precision="exact")
    return b, engine.compute(b)


def make_facts(lagna, signs, combust=(), degrees=None):
    """Synthetic facts from {planet: sign}; unspecified planets sit in Pisces."""
    degrees = degrees or {}
    planets = {}
    for n in NAMES:
        s = signs.get(n, 11)
        d = degrees.get(n, 5.0)
        planets[n] = {"sign": s, "sign_name": K.SIGN_NAMES[s], "degree": d,
                      "abs_longitude": s * 30 + d, "house": (s - lagna) % 12 + 1,
                      "combust": n in combust, "dignity": _dignity(NAMES.index(n), s, d)}
    houses = {h: {"sign": (lagna + h - 1) % 12,
                  "lord": K.PLANET_NAMES[K.SIGN_LORD[(lagna + h - 1) % 12]]} for h in range(1, 13)}
    return {"planets": planets, "houses": houses,
            "lagna": {"sign": lagna, "sign_name": K.SIGN_NAMES[lagna]}}


def ids(found):
    return {y["id"]: y for y in found}


# ---------------------------------------------------------------- Mangal dosha

def test_mangal_own_sign_cancels():
    f = make_facts(0, {"Mars": 0, "Moon": 2, "Venus": 2, "Jupiter": 5})   # Mars in Aries, 1st
    md = dosha.mangal_dosha(f)
    assert [r["reference"] for r in md["present_from"]] == ["Lagna"]
    assert md["strength"] == "mild"
    assert [c["id"] for c in md["cancellations"]] == ["MD.CX.OWN_OR_EXALTED"]
    assert md["net"] == "cancelled" and md["wording_key"] == "mangal_dosha.cancelled"


def test_mangal_jupiter_conjunct_and_aspect():
    f = make_facts(0, {"Mars": 6, "Jupiter": 6, "Moon": 0, "Venus": 0})   # Mars in Libra, 7th from all three
    md = dosha.mangal_dosha(f)
    assert md["strength"] == "strong" and len(md["present_from"]) == 3
    assert "MD.CX.JUPITER_CONJUNCT" in [c["id"] for c in md["cancellations"]]
    assert md["net"] == "cancelled"
    f = make_facts(0, {"Mars": 6, "Jupiter": 2, "Moon": 0, "Venus": 0})   # Jupiter in Gemini: 5th aspect on Libra
    md = dosha.mangal_dosha(f)
    assert [c["id"] for c in md["cancellations"]] == ["MD.CX.JUPITER_ASPECT"]
    assert md["net"] == "mild"                     # partial: strong -> mild


def test_mangal_sign_exception_is_unverified():
    # Taurus Lagna, Mars in Gemini = 2nd: listed exception, verified False
    f = make_facts(1, {"Mars": 2, "Jupiter": 9, "Moon": 9, "Venus": 9})
    md = dosha.mangal_dosha(f)
    cx = [c for c in md["cancellations"] if c["id"] == "MD.CX.SIGN_EXCEPTION"]
    assert cx and cx[0]["verified"] is False and cx[0]["rule"] == "MD.CX.SIGN_H2_GEMINI"
    assert md["net"] == "mild" and md["net_including_unverified"] == "cancelled"


def test_mangal_partner_and_age_note():
    f = make_facts(0, {"Mars": 6, "Moon": 2, "Venus": 2, "Jupiter": 2})   # Mars Libra, 7th
    partner = make_facts(3, {"Mars": 3, "Moon": 5, "Venus": 5})            # Mars in partner's 1st
    alone = dosha.mangal_dosha(f, age=30)
    assert alone["net"] == "mild"
    assert alone["notes"][0]["id"] == "MD.NOTE.AGE_28" and alone["notes"][0]["kind"] == "belief"
    assert alone["notes"][0]["age_over_28"] is True
    both = dosha.mangal_dosha(f, partner_facts=partner)
    assert "MD.CX.PARTNER_SIMILAR" in [c["id"] for c in both["cancellations"]]
    assert both["net"] == "cancelled"


def test_mangal_absent_and_reference_chart(ref):
    assert dosha.mangal_dosha(make_facts(0, {"Mars": 4, "Moon": 0, "Venus": 0}))["net"] == "absent"
    b, f = ref
    md = f["mangal_dosha"]
    assert md["present_from"] == [{"reference": "Venus", "house": 12, "rule": "MD.REF.VENUS"}]
    assert md["net"] == "mild"
    rep = RP.build_report(f, b, calibrated=True, predictions_allowed=False, today=TODAY)
    assert set(rep["chart"]["mangal_dosha"]) == {"present", "house_from_lagna", "also_from_moon"}
    assert rep["chart"]["mangal_dosha"]["present"] is False
    assert rep["chart"]["mangal_dosha_assessment"]["net"] == "mild"


# ---------------------------------------------------------------- strength

def test_strength_keys_and_shadbala_ratio(ref):
    _, f = ref
    st = f["strength"]
    keys = {"shadbala_ratio", "strong", "vimshopaka", "ishta", "kashta", "baaladi", "jagradadi",
            "deeptadi", "summary"}
    for n in S.SEVEN:
        assert keys <= set(st[n]), n
        assert st[n]["summary"] in ("strong", "moderate", "weak")
    rupas, pj = f["shadbala"][7], f["shadbala"][8]
    for i, n in enumerate(S.SEVEN):
        if n != "Sun":     # PyJHora uses 5 rupas for the Sun; BPHS 6.5
            assert st[n]["shadbala_ratio"] == pytest.approx(pj[i], abs=0.011), n
    assert st["Sun"]["shadbala_ratio"] == pytest.approx(rupas[0] / 6.5, abs=0.01)
    assert st["Moon"]["strong"] is False and st["Mars"]["strong"] is True
    assert st["Mars"]["vimshopaka"] == f["vimshopaka"]["Mars"]
    assert st["Venus"]["jagradadi"] == "Jagrat"                      # exalted
    assert S.VERIFIED["deeptadi"] is False


def test_strength_pure_helpers():
    assert S.baaladi(0, 3) == "Bala" and S.baaladi(1, 3) == "Mrita" and S.baaladi(0, 29) == "Mrita"
    assert S.ishta_kashta(60, 60) == (60.0, 0.0) and S.ishta_kashta(0, 30) == (0.0, pytest.approx(42.43, abs=0.01))
    assert S.uchcha_bala(0, 10.0) == 60.0 and S.uchcha_bala(0, 190.0) == 0.0
    assert S.jagradadi(4, 3) == "Jagrat" and S.jagradadi(4, 9) == "Sushupti" and S.jagradadi(4, 0) == "Swapna"


# ---------------------------------------------------------------- varga discipline

def test_varga_classify_rules():
    assert VD.classify({"changes_s": [-900, 500]}, 120, "D9") == "reliable"
    assert VD.classify({"changes_s": [-60, 500]}, 120, "D9") == "cusp_sensitive"
    assert VD.classify({"changes_s": [-60, 30]}, 120, "D9") == "unusable"
    assert VD.classify({"changes_s": []}, 120, "D60") == "unusable"
    assert VD.classify({"changes_s": []}, 30, "D60") == "reliable"


def test_varga_reliability_uses_stability(ref, monkeypatch):
    from app.astro import stability
    b, f = ref
    seen = {}

    def fake(birth, vargas=None, **kw):
        seen["called"] = True
        return {v: {"changes_s": [10.0] if v == "D10" else []} for v in vargas}
    monkeypatch.setattr(stability, "lagna_windows", fake)
    rel = VD.reliability(b)
    assert seen["called"] and rel["D10"] == "cusp_sensitive" and rel["D9"] == "reliable"
    assert rel["D60"] == "unusable"
    assert f["varga_reliability"]["D60"] == "unusable" and f["varga_reliability"]["D9"] == "reliable"
    d9 = f["varga_analysis"]["D9"]
    assert d9["lagna"] == "Pisces" and d9["d1_house_lord"]["lord"] == "Mars"
    assert "Moon" in d9["vargottama"]


# ---------------------------------------------------------------- bhava

def test_bhava_scores_have_reasons(ref):
    _, f = ref
    bj = f["bhava_judgement"]
    assert set(bj) == set(range(1, 13))
    for h, rec in bj.items():
        assert rec["reasons"] and all(r["id"].startswith("BH.") for r in rec["reasons"])
        assert rec["grade"] in ("strong", "moderate", "weak")
        assert rec["score"] == pytest.approx(sum(r["points"] for r in rec["reasons"]))
    assert bj[7]["lord"] == "Mars" and bj[7]["lord_placement"]["house"] == 10


def test_bhavat_bhavam():
    assert [bhava.bhavat_bhavam(h) for h in (1, 4, 7, 9, 10)] == [1, 7, 1, 5, 7]


# ---------------------------------------------------------------- dasha craft

def test_dasha_relation_table():
    for h in (6, 8, 12):
        r = dasha_craft.relation(h)
        assert r["kind"] == "friction" and r["verified"] is True
    assert dasha_craft.relation(2)["kind"] == "friction" and dasha_craft.relation(2)["verified"] is False
    assert dasha_craft.relation(5)["kind"] == "harmonious" and dasha_craft.relation(10)["kind"] == "harmonious"


def _with_periods(f, rows):
    f["vimshottari"] = {"periods": [{"maha": m, "antar": a, "start": s, "end": e} for m, a, s, e in rows]}
    return f


def test_md_ad_six_eight_friction_and_sandhi():
    # Jupiter (MD) in Aries; Venus (AD) in Virgo = 6th from Jupiter
    f = _with_periods(make_facts(0, {"Jupiter": 0, "Venus": 5, "Moon": 3}), [
        ("Jupiter", "Saturn", "2020-01-01", "2026-01-10"),
        ("Jupiter", "Venus", "2026-01-10", "2027-01-15"),
        ("Saturn", "Saturn", "2027-01-15", "2030-01-01")])
    dc = dasha_craft.analyze(f, None, date(2026, 12, 1))
    assert dc["ad_from_md"]["id"] == "DC.AD_FROM_MD.6" and dc["ad_from_md"]["kind"] == "friction"
    assert dc["sandhi"]["md_sandhi"] is True            # MD ends in 45 days
    assert dc["sandhi"]["ad_sandhi"] is False
    far = dasha_craft.analyze(f, None, date(2026, 5, 1))
    assert far["sandhi"]["flag"] is False


def test_dasha_craft_reference(ref):
    b, f = ref
    dc = dasha_craft.analyze(f, b, TODAY)
    assert dc["md"]["lord"] == "Rahu" and dc["ad"]["lord"] == "Venus"
    assert dc["md"]["dispositor"]["planet"] == "Saturn"
    assert dc["ad"]["owns_from_lagna"] == [1, 6] and dc["ad"]["strength"]["summary"]
    assert dc["pd"]["lord"] == "Mercury"
    assert dc["pravesh"]["md"]["lagna"] in K.SIGN_NAMES


# ---------------------------------------------------------------- gochara

def test_vedha_pairs():
    v = gochara.vedha_for("Jupiter", 2, {"Saturn": 12, "Mars": 4})
    assert v["favourable_house"] and v["vedha_house"] == 12 and v["obstructed_by"] == ["Saturn"]
    # Sun and Saturn do not obstruct each other
    assert gochara.vedha_for("Sun", 3, {"Saturn": 9})["obstructed_by"] == []
    assert gochara.vedha_for("Sun", 3, {"Mars": 9})["obstructed_by"] == ["Mars"]
    assert gochara.vedha_for("Moon", 1, {"Mercury": 5})["obstructed_by"] == []
    assert gochara.vedha_for("Saturn", 4, {})["favourable_house"] is False
    assert gochara.VEDHA_VERIFIED["Rahu"] is False


def test_murti_nirnaya_mapping():
    got = {h: gochara.murti(h) for h in range(1, 13)}
    assert {h for h, m in got.items() if m == "gold"} == {1, 6, 11}
    assert {h for h, m in got.items() if m == "silver"} == {2, 5, 9}
    assert {h for h, m in got.items() if m == "copper"} == {3, 7, 10}
    assert {h for h, m in got.items() if m == "iron"} == {4, 8, 12}


def test_saturn_states_and_chandrabala():
    assert gochara.saturn_states(12)["sade_sati_phase"].startswith("rising")
    assert gochara.saturn_states(4)["dhaiya"] and gochara.saturn_states(4)["kantaka"]
    assert gochara.saturn_states(8)["ashtama"] and not gochara.saturn_states(8)["sade_sati"]
    assert gochara.chandrabala(2, 0)["favourable"] and not gochara.chandrabala(3, 0)["favourable"]


def test_gochara_reference(ref):
    b, f = ref
    g = gochara.gochara(f, b, TODAY)
    sat = g["planets"]["Saturn"]
    assert sat["sign"] == "Pisces" and sat["house_from_moon"] == 4
    assert sat["bav"] == f["binnashtakavarga"][6][11] and sat["sav"] == f["sarvastakavarga"][11]
    assert sat["kakshya"]["lord"] and "bindu" in sat["kakshya"]
    assert g["saturn"]["kantaka"] and g["tarabala"]["name"] and "chandrabala" in g
    assert g["ingresses_12m"] and all(r["murti_nirnaya"]["verified"] is False
                                      for r in g["ingresses_12m"] if r["murti_nirnaya"])


# ---------------------------------------------------------------- Jaimini depth

def test_karakamsha_and_al(ref):
    _, f = ref
    kk = f["jaimini"]["karakamsha"]
    ak = f["jaimini"]["karakas"]["Atmakaraka"]
    assert kk["atmakaraka"] == ak and kk["sign"] == f["vargas"]["D9"][ak]["sign"]
    assert ak in kk["d9_occupants"] and kk["twelfth"]["verified"] is False
    al = f["jaimini"]["al_houses"]
    assert al["sign_name"] == "Capricorn" and al["h2"]["occupants"] == ["Mars"]
    nar = J.running_narayana(f["narayana"], TODAY.isoformat())
    assert nar and nar["md"]["sign_name"] and nar["ad"]


def test_jaimini_raja_ak_amk():
    f = make_facts(0, {"Moon": 4, "Mars": 4}, degrees={"Moon": 29.0, "Mars": 28.0})
    f["jaimini"] = {"karakas": {"Atmakaraka": "Moon", "Amatyakaraka": "Mars"}}
    ry = J.raja_yogas(f)
    assert ry[0]["id"] == "JM.RAJA.AK_AMK" and ry[0]["verified"] is False and "conjunction" in ry[0]["links"]


# ---------------------------------------------------------------- yogas

ALL_VIRGO = {"Mars": 5, "Mercury": 5, "Jupiter": 5, "Venus": 5, "Saturn": 5}


def test_kemadruma_and_cancellation():
    f = make_facts(0, {"Moon": 1, "Sun": 2, "Rahu": 8, "Ketu": 2, **ALL_VIRGO})
    k = ids(yogas.detect(f))["KEMADRUMA"]
    assert k["status"] == "conditional" and k["arishta_type"]
    assert [c["id"] for c in k["cancellations"]] == ["KEMA.CX.JUPITER_ASPECTS_MOON"]
    assert "not a prediction" in k["wording"]
    f = make_facts(0, {"Moon": 1, "Sun": 2, "Rahu": 8, "Ketu": 2, **ALL_VIRGO, "Saturn": 4})
    k = ids(yogas.detect(f))["KEMADRUMA"]
    assert k["status"] == "cancelled" and "KEMA.CX.PLANET_KENDRA_FROM_MOON" in k["cancelled_by"]


def test_lunar_and_solar_yogas():
    found = ids(yogas.detect(make_facts(0, {"Moon": 1, "Mars": 2, "Sun": 8, "Mercury": 9})))
    assert "SUNAPHA" in found and "VESI" in found
    found = ids(yogas.detect(make_facts(0, {"Moon": 1, "Mars": 2, "Saturn": 0, "Sun": 8,
                                            "Mercury": 7, "Venus": 9})))
    assert "DURUDHARA" in found and "UBHAYACHARI" in found
    found = ids(yogas.detect(make_facts(0, {"Moon": 0, "Mercury": 5, "Jupiter": 6, "Venus": 7})))
    assert found["ADHI"]["level"] == "classical"


def test_amala_parvata_saraswati():
    f = make_facts(0, {"Jupiter": 8, "Moon": 3, "Venus": 0, "Mercury": 9, "Mars": 2, "Saturn": 2,
                       "Sun": 2, "Rahu": 2, "Ketu": 8})
    found = ids(yogas.detect(f))
    assert "AMALA.MERCURY_10TH_FROM_LAGNA" in found["AMALA"]["conditions_fired"]
    assert "PARVATA" in found and "SARASWATI" in found


def test_budhaditya_graded_by_orb():
    tight = make_facts(0, {"Sun": 4, "Mercury": 4}, combust=("Mercury",), degrees={"Sun": 10, "Mercury": 12})
    b = ids(yogas.detect(tight))["BUDHADITYA"]
    assert b["status"] == "cancelled" and b["cancelled_by"] == ["BUDHADITYA.MERCURY_DEEP_COMBUST"]
    wide = make_facts(0, {"Sun": 4, "Mercury": 4}, degrees={"Sun": 2, "Mercury": 20})
    b = ids(yogas.detect(wide))["BUDHADITYA"]
    assert b["status"] != "cancelled" and b["grade"] == "formed"


def test_raja_one_way_aspect(ref):
    _, f = ref       # Taurus: Saturn (9/10 lord) in Capricorn aspects Venus (Lagna lord) in Pisces (3rd)
    y = ids(f["yogas"])["RAJA_YOGA.SATURN_VENUS"]
    assert "RAJA.KENDRA_TRIKONA_ASPECT_BY_SATURN" in y["conditions_fired"]
    assert y["link_strength"].startswith("one-way")
    # no aspect either way: no yoga
    f2 = make_facts(1, {"Saturn": 9, "Venus": 2, "Mercury": 5, "Jupiter": 5})
    assert "RAJA_YOGA.SATURN_VENUS" not in ids(yogas.detect(f2))


# ---------------------------------------------------------------- special points

def test_bhrigu_bindu_midpoint():
    assert SP.bhrigu_bindu(100.0, 40.0) == pytest.approx(70.0)
    assert SP.bhrigu_bindu(10.0, 350.0) == pytest.approx(0.0)
    assert SP.bhrigu_bindu(350.0, 10.0) == pytest.approx(180.0)


def test_yogi_points(ref):
    y = SP.yogi(10.0, 20.0)
    assert y["yogi_point"]["abs_longitude"] == pytest.approx(123.3333, abs=1e-3)
    assert y["yogi_planet"] == "Ketu" and y["duplicate_yogi"] == "Sun"         # Magha, Leo
    assert y["avayogi_point"]["abs_longitude"] == pytest.approx(310.0, abs=1e-3)
    _, f = ref
    sp = f["special_points"]
    assert sp["node_axis"]["axis"] == "9/3" and "gulika" in sp and "mandi" in sp
    bb = (f["planets"]["Rahu"]["abs_longitude"]
          + ((f["planets"]["Moon"]["abs_longitude"] - f["planets"]["Rahu"]["abs_longitude"]) % 360) / 2) % 360
    assert sp["bhrigu_bindu"]["abs_longitude"] == pytest.approx(bb, abs=1e-3)


# ---------------------------------------------------------------- digest

def test_digest_time_unknown_has_no_lagna_lines(ref):
    b, f = ref
    d = digest.build_digest(f, b, TODAY, "career", time_known=False)
    assert "Chandra Lagna Sagittarius" in d
    for bad in ("Lagna Taurus", "House lords from Lagna", "from Lagna", "Arudhas:", "VARGA reliability",
                "D9 Lagna", "Functional roles", "STRENGTH (", "BHAVA judgement", "Shadbala rupas", "AL Capricorn"):
        assert bad not in d, bad
    assert "Raja Yoga" not in d and "Sunapha" in d
    assert len(d.splitlines()) <= 70


def test_digest_depth_lines(ref):
    b, f = ref
    d = digest.build_digest(f, b, TODAY, "relationship")
    for want in ("STRENGTH (", "VARGA reliability", "JAIMINI depth: Karakamsha Sagittarius", "DASHA craft",
                 "Tarabala today", "BHAVA judgement: H7", "Mangal dosha (traditional matching factor): net mild"):
        assert want in d, want
    assert "deeptadi" not in d.lower() and "murti" not in d.lower()
    assert "Mangal" not in digest.build_digest(f, b, TODAY, "career")
    assert len(d.splitlines()) <= 70
