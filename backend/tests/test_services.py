"""Services: kundli matching, muhurta, varshaphala, prashna, report views, PDF."""
import os, sys, uuid
from datetime import date

os.environ.setdefault("JYOTISH_DATABASE_URL", "sqlite:////tmp/jyotish_test.db")
os.environ.setdefault("JYOTISH_LLM_PROVIDER", "offline")
os.environ.setdefault("JYOTISH_JWT_SECRET", "test-only-jwt-secret-" + uuid.uuid4().hex)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from jhora.panchanga import drik

from app.main import app
from app.db import init_db
from app.astro import matching as M, muhurta, constants as K
from app.astro.engine import engine, BirthInput
from app import api_extra

init_db()
client = TestClient(app)

ARJUN = dict(display_name="Arjun", year=1990, month=5, day=15, hour=6, minute=15,
             place_name="Chennai", place_state="Tamil Nadu", place_country="India",
             latitude=13.0827, longitude=80.2707, birth_time_precision="exact")
BIRTH = BirthInput("Arjun", 1990, 5, 15, 6, 15, 0, 13.0827, 80.2707, 5.5, "Chennai")


@pytest.fixture(autouse=True)
def _throttle():
    from app.main import reset_auth_throttle
    reset_auth_throttle(); yield; reset_auth_throttle()


def auth():
    email = f"s_{uuid.uuid4().hex[:8]}@test.dev"
    r = client.post("/api/auth/register", json={"terms_accepted": True, "age_confirmed": True,
                                                "email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert client.put("/api/profile", json=ARJUN, headers=h).status_code == 200
    return h


def moon(sign, nak, pada, degree):
    return {"sign": sign, "sign_name": K.SIGN_NAMES[sign], "degree": degree, "nak": nak,
            "nak_name": K.NAKSHATRAS[nak - 1], "pada": pada, "sign_lord": K.SIGN_LORD[sign]}


# ---------------- matching ----------------

def test_ashtakoota_hand_computed_pair():
    """Groom: Uttara Ashadha pada 1, Sagittarius 27.7 deg. Bride: Rohini, Taurus 10 deg.
    Hand values from the standard tables: Varna 1 (Kshatriya >= Vaishya), Vashya 2 (both
    quadruped), Tara 3 (counts 18->9 and 11->2, both good), Yoni 0 (mongoose vs serpent
    enemies), Maitri 0.5 (Jupiter/Venus: enemy + neutral), Gana 6 (both Manushya),
    Bhakoot 0 (6/8), Nadi 0 (both Antya)."""
    k = {x["id"]: x["score"] for x in M.koota_scores(moon(8, 21, 1, 27.7), moon(1, 4, 1, 10.0))}
    assert k == {"varna": 1, "vashya": 2, "tara": 3, "yoni": 0, "maitri": 0.5,
                 "gana": 6, "bhakoot": 0, "nadi": 0}
    assert sum(k.values()) == 12.5


def test_second_pair_and_max():
    # Same nakshatra pair is not max (Nadi/Bhakoot); a Hasta groom with Swati bride: spot-check totals bounds
    ks = M.koota_scores(moon(5, 13, 1, 5.0), moon(6, 15, 2, 8.0))
    assert [x["max"] for x in ks] == [1, 2, 3, 4, 5, 6, 7, 8] and sum(x["max"] for x in ks) == 36
    by = {x["id"]: x["score"] for x in ks}
    assert by["nadi"] == 8            # Hasta (Adi) vs Swati (Antya): different nadis
    assert by["varna"] == 1           # Virgo (Vaishya) groom vs Libra (Shudra) bride
    

def test_nadi_exception_same_rashi_diff_nakshatra():
    g, b = moon(1, 3, 3, 15.0), moon(1, 4, 1, 12.0)        # Krittika & Rohini, both Taurus, both Antya
    res = M.nadi_exceptions(g, b)
    assert res["present"] and res["cancelled"]
    assert any(e["id"] == "NADI-EX-1" and e["applies"] for e in res["exceptions"])
    assert all(e["verified"] is False for e in res["exceptions"])


def test_nadi_no_exception_when_none_apply():
    res = M.nadi_exceptions(moon(8, 21, 1, 27.7), moon(1, 4, 1, 10.0))   # UA & Rohini, enemy lords
    assert res["present"] and not res["cancelled"]


def test_bhakoot_exception_same_lord():
    g, b = moon(0, 1, 1, 5.0), moon(7, 17, 1, 5.0)          # Aries/Scorpio, 6/8, both ruled by Mars
    kk = {x["id"]: x for x in M.koota_scores(g, b)}
    assert kk["bhakoot"]["score"] == 0
    res = M.bhakoot_exceptions(g, b, 0)
    assert res["present"] and res["cancelled"]


def test_pyjhora_cross_check_agreement():
    from jhora import const
    from jhora.horoscope.match.compatibility import Ashtakoota
    for gn, bn in [(21, 4), (1, 14), (8, 12), (17, 26)]:
        sign = lambda n: int(((n - 1) * 360 / 27 + 1) // 30)
        g, b = moon(sign(gn), gn, 1, 5.0), moon(sign(bn), bn, 1, 5.0)
        mine = {x["id"]: x["score"] for x in M.koota_scores(g, b)}
        a = Ashtakoota(gn, 1, bn, 1, method=const.CHART_STYLE.NORTH_INDIAN)
        assert mine["yoni"] == a.yoni_porutham()[0]
        assert mine["gana"] == a.gana_porutham()[0]
        assert mine["nadi"] == a.naadi_porutham()[0]
        assert mine["maitri"] == a.raasi_adhipathi_porutham()[0]


def test_bands_wording():
    assert M.band_for(12.5)["key"] == "below_traditional_minimum"
    assert M.band_for(30)["key"] == "good"
    assert "doom" not in M.band_for(5)["text"].lower()


def test_matching_endpoint_consent_required():
    h = auth()
    pid = client.get("/api/profile", headers=h).json()["id"]
    partner = dict(year=1992, month=3, day=2, hour=9, minute=30, place_name="Mumbai",
                   latitude=19.076, longitude=72.8777, place_country="India")
    body = {"groom": {"profile_id": pid}, "bride": {"birth": partner}}
    assert client.post("/api/matching", json=body, headers=h).status_code == 422
    r = client.post("/api/matching", json={**body, "partner_consent": True}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["max"] == 36 and len(d["kootas"]) == 8 and d["partner_data_stored"] is False
    assert "mangal" in d and "disclaimer" in d


def test_matching_two_entered_partners_rejected():
    h = auth()
    partner = dict(year=1992, month=3, day=2, hour=9, minute=30, place_name="Mumbai",
                   latitude=19.076, longitude=72.8777)
    r = client.post("/api/matching", json={"groom": {"birth": partner}, "bride": {"birth": partner},
                                           "partner_consent": True}, headers=h)
    assert r.status_code == 422


# ---------------- muhurta ----------------

def _rahu_span(on, lat, lon, name):
    place = muhurta.place_for(lat, lon, name, on)
    jd = muhurta.P._jd_noon(on)
    s, e = drik.raahu_kaalam(jd, place)
    return muhurta.P._dms_to_hours(s), muhurta.P._dms_to_hours(e)


def _hours(hm):
    return int(hm[:2]) + int(hm[3:]) / 60


def test_muhurta_excludes_rahu_and_bhadra_at_location():
    lat, lon = 13.0827, 80.2707
    r = muhurta.scan("travel", date(2026, 12, 1), date(2026, 12, 8), lat, lon, "Chennai")
    assert r["slots"]
    for s in r["slots"]:
        on = date.fromisoformat(s["date"])
        a, b = _rahu_span(on, lat, lon, "Chennai")
        assert _hours(s["end"]) <= a + 1e-6 or _hours(s["start"]) >= b - 1e-6
        assert s["karana"] != "Vishti"
        assert s["badge"].startswith("Muhurta factors satisfied: ")
    assert "Rahu Kaal" in r["excluded"]["by_reason"] and "Vishti (Bhadra) karana" in r["excluded"]["by_reason"]


def test_muhurta_real_window_lagna_matches_location():
    lat, lon = 51.5074, -0.1278
    r = muhurta.scan("travel", date(2026, 12, 1), date(2026, 12, 4), lat, lon, "London")
    s = r["slots"][0]
    on = date.fromisoformat(s["date"])
    place = muhurta.place_for(lat, lon, "London", on)
    from jhora import utils
    from app.astro.engine import apply, calc_lock, DEFAULT_SETTINGS
    h, m = int(s["start"][:2]), int(s["start"][3:])
    with calc_lock:
        apply(DEFAULT_SETTINGS)
        asc = int(drik.ascendant(utils.julian_day_number((on.year, on.month, on.day), (h, m, 0)), place)[0])
    assert K.SIGN_NAMES[asc] == s["lagna"]
    # a different location gives a different result set
    r2 = muhurta.scan("travel", date(2026, 12, 1), date(2026, 12, 4), 13.0827, 80.2707, "Chennai")
    assert [(x["date"], x["start"]) for x in r["slots"]] != [(x["date"], x["start"]) for x in r2["slots"]]


def test_muhurta_kharmas_excluded_for_vivah():
    # Sun is in sidereal Sagittarius from ~16 Dec to ~14 Jan
    r = muhurta.scan("vivah", date(2026, 12, 20), date(2026, 12, 28), 13.0827, 80.2707, "Chennai")
    assert r["slots"] == []
    assert "Kharmas (Sun in Sagittarius/Pisces)" in r["excluded"]["by_reason"]
    t = muhurta.scan("travel", date(2026, 12, 20), date(2026, 12, 28), 13.0827, 80.2707, "Chennai")
    assert t["slots"]


def test_muhurta_endpoint_default_location_and_tarabala():
    h = auth()
    r = client.post("/api/muhurta", json={"event": "vehicle", "start": "2026-12-01", "end": "2026-12-07"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["location"]["source"] in ("birthplace", "current_residence")
    assert d["native_moon"] == "Uttara Ashadha"
    assert any(f["id"] == "F-TARA" for f in d["slots"][0]["factors"]) if d["slots"] else True
    assert client.post("/api/muhurta", json={"event": "vehicle", "start": "2026-12-01", "end": "2027-03-07"},
                       headers=h).status_code == 422


# ---------------- varshaphala / prashna / report ----------------

def test_varshaphala_endpoint_shape():
    h = auth()
    r = client.get("/api/varshaphala?year=2026", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("varsha_lagna", "muntha", "year_lord", "mudda", "sahams", "tajika_yogas", "positions", "return_local"):
        assert k in d, k
    assert d["completed_years"] == 36 and d["sahams"] and d["sahams_verified"] is False
    assert d["mudda"]["periods"]
    assert client.get("/api/varshaphala?year=1980", headers=h).status_code == 422


def test_prashna_endpoint():
    h = auth()
    r = client.post("/api/prashna", json={"question_type": "career", "latitude": 28.6139, "longitude": 77.209,
                                          "place_name": "Delhi"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["relevant_house"] == 10 and d["lagna"]["lord"] and d["moon"]["sign"]
    assert d["indicators"] and all(i["verified"] is False for i in d["indicators"])
    assert "not a prediction" in d["summary"]["label"]
    assert d["rectification"]["applicable"] is False
    assert client.post("/api/prashna", json={"question_type": "nope"}, headers=h).status_code == 422


def test_dasha_tree_completeness():
    facts = engine.compute(BIRTH)
    tree = api_extra.dasha_tree(facts)
    assert len(tree) >= 9
    for md in tree:
        ads = md["antars"]
        assert ads[0]["start_jd"] == pytest.approx(md["start_jd"]) and ads[-1]["end_jd"] == pytest.approx(md["end_jd"])
        assert sum(a["end_jd"] - a["start_jd"] for a in ads) == pytest.approx(md["end_jd"] - md["start_jd"], abs=1e-6)
        for a in ads:
            pds = a["pratyantars"]
            assert len(pds) == 9
            assert sum(p["end_jd"] - p["start_jd"] for p in pds) == pytest.approx(a["end_jd"] - a["start_jd"], abs=1e-6)
    assert sum(1 for md in tree if md["running"]) == 1


def test_avakahada_reference_chart():
    """Moon in Uttara Ashadha pada 1, Sagittarius 27.67 deg (second half -> quadruped)."""
    facts = engine.compute(BIRTH)
    av = M.avakahada(facts)["items"]
    assert av["varna"] == "Kshatriya"          # Sagittarius (fire)
    assert av["vashya"] == "Chatushpada"       # Sagittarius second half
    assert av["yoni"] == "Mongoose"            # Uttara Ashadha
    assert av["gana"] == "Manushya"
    assert av["nadi"] == "Antya (Kapha)"
    assert av["nakshatra_lord"] == "Sun" and av["rashi_lord"] == "Jupiter"
    assert av["name_syllable"] == "Bhe"


def test_report_views_and_pdf():
    h = auth()
    v = client.get("/api/report-views", headers=h)
    assert v.status_code == 200, v.text
    d = v.json()
    assert d["settings_line"] and d["panchang"]["nakshatra"]["name"] == "Uttara Ashadha"
    assert d["shadbala"]["planets"][0]["required_rupas"] == 5.0
    assert d["chalit"] is None or d["chalit"]["rows"]
    assert d["dasha"]["chara"] and d["dasha"]["yogini"]
    r = client.get("/api/report.pdf", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
