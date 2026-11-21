"""Extra services: kundli matching, muhurta, varshaphala, prashna, report views, PDF.

Auth and profile ownership reuse main.py's helpers (imported lazily inside
handlers to avoid a circular import: main includes this router at the end).
"""
import logging
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from jhora import utils
from jhora.horoscope.chart import charts
from jhora.horoscope.dhasa.graha import yogini
from jhora.horoscope.transit import saham
from jhora.panchanga import drik
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import geo
from .astro import constants as K
from .astro import jaimini as J
from .astro import matching, muhurta, prashna, varsha
from .astro import vimshottari as native_vimshottari
from .astro.engine import BirthInput, apply, calc_lock, engine
from .auth import current_user
from .chat import orchestrator
from .db import BirthProfile, User, get_db

log = logging.getLogger(__name__)
router = APIRouter()


def _main():
    from . import main
    return main


# ------------------------------------------------------------------ helpers

def _usable_profile(db: Session, user: User, pid: int) -> BirthProfile:
    p = _main()._owned_profile(db, user, pid)
    if (p.relation or "self") != "self" and not p.permission_confirmed_at:
        raise HTTPException(409, "Confirm permission for this birth profile before using it.")
    return p


def _residence(p: BirthProfile | None):
    """(lat, lon, name) of the profile's current residence, if set."""
    if p is None or getattr(p, "residence_lat", None) is None or getattr(p, "residence_lon", None) is None \
            or not getattr(p, "residence_name", None):
        return None
    return p.residence_lat, p.residence_lon, p.residence_name


def _location(p: BirthProfile | None, lat, lon, name):
    if lat is not None and lon is not None:
        return float(lat), float(lon), name or "Chosen location", "request"
    res = _residence(p)
    if res:
        return res[0], res[1], res[2], "current_residence"
    if p is not None:
        return p.latitude, p.longitude, p.place_name, "birthplace"
    raise HTTPException(422, "A location is required.")


def _ymd(jd):
    y, m, d, _ = utils.jd_to_gregorian(jd)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _tup(t):
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"


# ------------------------------------------------------------------ matching

class PartnerBirth(BaseModel):
    display_name: str = ""
    year: int = Field(ge=1900, le=2030)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    second: int = Field(default=0, ge=0, le=59)
    place_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_state: str = ""
    place_country: str = ""
    gender: Optional[Literal["male", "female"]] = None


class PersonRef(BaseModel):
    profile_id: Optional[int] = None
    birth: Optional[PartnerBirth] = None


class MatchIn(BaseModel):
    groom: PersonRef
    bride: PersonRef
    partner_consent: bool = False


def _facts_for(db, user, ref: PersonRef):
    if ref.profile_id is not None:
        p = _usable_profile(db, user, ref.profile_id)
        return orchestrator.chart_facts(p), (p.display_name or "Profile"), "profile"
    if ref.birth is None:
        raise HTTPException(422, "Each person needs a profile_id or birth details.")
    b = ref.birth
    try:
        dt = datetime(b.year, b.month, b.day, b.hour, b.minute, b.second)
        res = geo.resolve_offset(b.latitude, b.longitude, dt, country=b.place_country, state=b.place_state)
    except geo.NonexistentTime as exc:
        raise HTTPException(422, f"{exc}")
    except geo.AmbiguousTime:
        res = geo.resolve_offset(b.latitude, b.longitude, dt, country=b.place_country,
                                 state=b.place_state, fold=0)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    bi = BirthInput(name=b.display_name, year=b.year, month=b.month, day=b.day, hour=b.hour,
                    minute=b.minute, second=b.second, lat=b.latitude, lon=b.longitude,
                    tz_offset=res["offset_hours"], place_label=b.place_name)
    return engine.compute(bi), (b.display_name or "Partner"), "entered"


@router.post("/api/matching")
def kundli_matching(body: MatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entered = [r for r in (body.groom, body.bride) if r.profile_id is None]
    if entered and not body.partner_consent:
        raise HTTPException(422, "Confirm you have this person's permission to use their birth details.")
    if len(entered) == 2:
        raise HTTPException(422, "At least one person must be a saved profile.")
    gf, gname, gsrc = _facts_for(db, user, body.groom)
    bf, bname, bsrc = _facts_for(db, user, body.bride)
    out = matching.match(gf, bf)
    out["groom_name"], out["bride_name"] = gname, bname
    out["sources"] = {"groom": gsrc, "bride": bsrc}
    out["partner_data_stored"] = False
    return out


# ------------------------------------------------------------------ muhurta

class MuhurtaIn(BaseModel):
    event: Literal["vivah", "griha_pravesh", "vehicle", "business", "property", "travel", "namkaran"]
    start: date
    end: date
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    place_name: str = ""
    use_profile_moon: bool = True
    direction: Optional[Literal["east", "west", "north", "south"]] = None


@router.post("/api/muhurta")
def muhurta_search(body: MuhurtaIn, user: User = Depends(current_user)):
    p = _main()._require_profile(user)
    lat, lon, name, src = _location(p, body.latitude, body.longitude, body.place_name)
    facts = orchestrator.chart_facts(p) if body.use_profile_moon else None
    try:
        out = muhurta.scan(body.event, body.start, body.end, lat, lon, name, native_facts=facts,
                           settings=orchestrator.birth_input(p).settings, direction=body.direction)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    out["location"]["source"] = src
    return out


# ------------------------------------------------------------------ varshaphala

SAHAMS = [("Punya", saham.punya_saham), ("Vidya", saham.vidya_saham), ("Yasas", saham.yasas_saham),
          ("Mitra", saham.mitra_saham), ("Mahatmya", saham.mahatmaya_saham), ("Asha", saham.asha_saham),
          ("Bhratri", saham.bhratri_saham), ("Pithri", saham.pithri_saham), ("Maathri", saham.maathri_saham),
          ("Puthra", saham.puthra_saham), ("Karma", saham.karma_saham), ("Roga", saham.roga_saham),
          ("Vivaha", saham.vivaha_saham), ("Vyaapaara", saham.vyaapaara_saham), ("Laabha", saham.laabha_saham)]


def varsha_view(birth: BirthInput, facts: dict, year: int) -> dict:
    cy = year - birth.year
    if cy < 0 or cy > 119:
        raise HTTPException(422, "Choose a year from the birth year up to age 119.")
    rec = varsha.varsha(birth, cy, facts["lagna"]["sign"])
    lagna = rec["varsha_lagna"]["sign"]
    names = {**K.PLANET_NAMES, "L": "Lagna"}
    positions = []
    for pid, (sign, deg) in rec["positions"]:
        positions.append({"planet": names.get(pid, str(pid)), "sign": K.SIGN_NAMES[sign], "degree": round(deg, 2),
                          "house": (sign - lagna) % 12 + 1})
    sahams = []
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    with calc_lock:
        apply(birth.settings)
        for nm, fn in SAHAMS:
            try:
                lon = float(fn(rec["return"]["jd"], place)) % 360
                s = int(lon // 30)
                sahams.append({"name": nm, "sign": K.SIGN_NAMES[s], "degree": round(lon % 30, 2),
                               "house": (s - lagna) % 12 + 1, "lord": K.PLANET_NAMES[K.SIGN_LORD[s]]})
            except Exception:
                continue
    return {
        "year": year, "completed_years": cy, "year_of_life": cy + 1,
        "return_local": rec["return"]["local"], "tz_offset_hours": rec["return"]["tz_offset_hours"],
        "varsha_lagna": rec["varsha_lagna"], "muntha": rec["muntha"],
        "year_lord": rec.get("year_lord"), "office_bearers": rec.get("office_bearers"),
        "pancha_vargeeya_bala": rec.get("pancha_vargeeya_bala"),
        "positions": positions, "tajika_yogas": (rec.get("tajika") or {}).get("yogas", []),
        "mudda": rec.get("mudda"), "sahams": sahams,
        "sahams_note": "Sahams (Arabic parts) per Tajika Neelakanthi as implemented in PyJHora; day/night "
                       "formulas handled by the library. verified: false.",
        "sahams_verified": False, "status": rec["status"], "errors": rec["errors"],
        "chart": {n["planet"]: {"sign": K.SIGN_NAMES.index(n["sign"]), "degree": n["degree"]} for n in positions},
    }


@router.get("/api/varshaphala")
def varshaphala(year: int | None = Query(default=None), user: User = Depends(current_user)):
    p = _main()._require_profile(user)
    birth = orchestrator.birth_input(p)
    if birth.birth_time_precision == "unknown":
        raise HTTPException(422, "Varshaphala needs a birth time (the annual chart depends on the Lagna).")
    facts = orchestrator.chart_facts(p)
    y = year or max(orchestrator._today_at(birth).year, birth.year)
    return varsha_view(birth, facts, y)


# ------------------------------------------------------------------ prashna

class PrashnaIn(BaseModel):
    question_type: str = "general"
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    place_name: str = ""
    when_local: Optional[datetime] = None      # defaults to now at the location


@router.post("/api/prashna")
def prashna_cast(body: PrashnaIn, user: User = Depends(current_user)):
    if body.question_type not in prashna.QUESTIONS:
        raise HTTPException(422, f"question_type must be one of: {', '.join(prashna.QUESTIONS)}")
    p = _main()._require_profile(user)
    lat, lon, name, src = _location(p, body.latitude, body.longitude, body.place_name)
    birth = orchestrator.birth_input(p)
    b = prashna.moment_input(lat, lon, name, body.when_local, settings=birth.settings)
    out = prashna.analyse(b, body.question_type)
    out.pop("_facts", None)
    out["cast"]["location_source"] = src
    out["rectification"] = prashna.rectification_hint(out, birth)
    return out


# ------------------------------------------------------------------ report views

REQUIRED_RUPAS = {"Sun": 5.0, "Moon": 6.0, "Mars": 5.0, "Mercury": 7.0, "Jupiter": 6.5, "Venus": 5.5, "Saturn": 5.0}
SHAD_COMPONENTS = ["Sthana", "Kala", "Dig", "Cheshta", "Naisargika", "Drik"]


def dasha_tree(facts: dict) -> list[dict]:
    """Vimshottari MD -> AD -> PD with dates (PDs tile each AD exactly)."""
    rows = facts["vimshottari"]["periods"]
    today = date.today().isoformat()
    mds: list[dict] = []
    for r in rows:
        if not mds or mds[-1]["lord"] != r["maha"]:
            mds.append({"lord": r["maha"], "start": r["start"], "end": r["end"], "start_jd": r["start_jd"],
                        "end_jd": r["end_jd"], "antars": []})
        md = mds[-1]
        md["end"], md["end_jd"] = r["end"], r["end_jd"]
        pds = native_vimshottari.pd_periods([r], r["start_jd"], r["end_jd"])
        md["antars"].append({
            "lord": r["antar"], "start": r["start"], "end": r["end"], "start_jd": r["start_jd"],
            "end_jd": r["end_jd"], "running": r["start"] <= today < r["end"],
            "pratyantars": [{"lord": q["lords"][2], "start": _ymd(q["start_jd"]), "end": _ymd(q["end_jd"]),
                             "start_jd": q["start_jd"], "end_jd": q["end_jd"],
                             "running": _ymd(q["start_jd"]) <= today < _ymd(q["end_jd"])} for q in pds]})
    for md in mds:
        md["running"] = md["start"] <= today < md["end"]
    return mds


def yogini_tree(birth: BirthInput) -> list[dict]:
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    with calc_lock:
        apply(birth.settings)
        rows = yogini.get_dhasa_antardhasa(drik.Date(birth.year, birth.month, birth.day),
                                           (birth.hour, birth.minute, birth.second), place,
                                           dhasa_level_index=2)
    today = date.today().isoformat()
    parsed = [(lords, _tup(start)) for lords, start, _ in rows]
    mds: list[dict] = []
    for i, (lords, start) in enumerate(parsed):
        end = parsed[i + 1][1] if i + 1 < len(parsed) else None
        name = K.PLANET_NAMES[lords[0]]
        if not mds or mds[-1]["lord"] != name:
            mds.append({"lord": name, "start": start, "end": end, "antars": []})
        mds[-1]["end"] = end
        mds[-1]["antars"].append({"lord": K.PLANET_NAMES[lords[-1]], "start": start, "end": end,
                                  "running": bool(end) and start <= today < end})
    for md in mds:
        md["running"] = bool(md["end"]) and md["start"] <= today < md["end"]
    return mds


def chara_tree(birth: BirthInput) -> list[dict]:
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    cs = birth.settings
    with calc_lock:
        apply(cs)
        jd = utils.julian_day_number((birth.year, birth.month, birth.day), (birth.hour, birth.minute, birth.second))
        rasi = charts.rasi_chart(jd, place)
        year_days = float(drik.dhasa_year_duration(jd=jd, place=place))
        periods = J.chara_periods(rasi, jd, cs.chara_school, year_days, colord_rule=cs.colord_rule)
    today = date.today().isoformat()
    out = []
    for md in periods:
        s, e = _ymd(md["start_jd"]), _ymd(md["end_jd"])
        out.append({"sign": K.SIGN_NAMES[md["sign"]], "start": s, "end": e, "running": s <= today < e,
                    "antars": [{"sign": K.SIGN_NAMES[a["sign"]], "start": _ymd(a["start_jd"]), "end": _ymd(a["end_jd"]),
                                "running": _ymd(a["start_jd"]) <= today < _ymd(a["end_jd"])}
                               for a in md["antardashas"]]})
    return out


def birth_panchang(facts: dict, birth: BirthInput) -> dict:
    """The five limbs at the birth instant (not sunrise), from the natal Sun and Moon."""
    from .astro import panchang as P
    sun = facts["planets"]["Sun"]["abs_longitude"]
    moon = facts["planets"]["Moon"]["abs_longitude"]
    elong = (moon - sun) % 360
    t = int(elong // 12) + 1
    k = int(elong // 6) + 1
    n = int(moon // K.NAK_SPAN) + 1
    y = int(((sun + moon) % 360) // K.NAK_SPAN) + 1
    place = drik.Place(birth.place_label, birth.lat, birth.lon, birth.tz_offset)
    jd = utils.julian_day_number((birth.year, birth.month, birth.day), (birth.hour, birth.minute, birth.second))
    with calc_lock:
        apply(birth.settings)
        vaara = drik.vaara(jd, place)
    return {"tithi": {"index": t, "name": P._tithi_name(t), "paksha": "Shukla" if t <= 15 else "Krishna"},
            "vaara": P.VAARA_NAMES[vaara], "vaara_lord": P.VAARA_LORDS[vaara],
            "nakshatra": {"index": n, "name": K.NAKSHATRAS[n - 1],
                          "pada": int((moon % K.NAK_SPAN) // (K.NAK_SPAN / 4)) + 1},
            "yoga": {"index": y, "name": P.YOGA_NAMES[y - 1]},
            "karana": {"index": k, "name": P._karana_name(k)},
            "basis": "At the recorded birth moment (weekday follows the sunrise-to-sunrise Vedic day)."}


def shadbala_table(facts: dict) -> dict | None:
    sb = facts.get("shadbala")
    if not sb or len(sb) < 9:
        return None
    rows = []
    for i, name in enumerate(list(REQUIRED_RUPAS)):
        rupas = float(sb[7][i])
        rows.append({"planet": name, "components": {c: float(sb[j][i]) for j, c in enumerate(SHAD_COMPONENTS)},
                     "total_virupas": float(sb[6][i]), "rupas": rupas, "required_rupas": REQUIRED_RUPAS[name],
                     "ratio": round(rupas / REQUIRED_RUPAS[name], 2),
                     "meets_minimum": rupas >= REQUIRED_RUPAS[name]})
    bb = facts.get("bhava_bala")
    bhava = None
    if bb:
        bhava = [{"house": i + 1, "rupas": bb["rupas"][i], "ratio": bb["ratio"][i]} for i in range(12)]
    return {"planets": rows, "bhava_bala": bhava,
            "note": "Required minimums follow BPHS (Sun 5, Moon 6, Mars 5, Mercury 7, Jupiter 6.5, "
                    "Venus 5.5, Saturn 5 rupas). Component order as returned by PyJHora 5.0."}


def chalit_view(facts: dict) -> dict | None:
    bh = facts.get("bhava")
    if not bh:
        return None
    lagna = facts["lagna"]["sign"]
    chart = {"Lagna": {"sign": lagna, "degree": facts["lagna"]["degree"]}}
    rows = []
    for name, ch in bh.items():
        p = facts["planets"][name]
        chart[name] = {"sign": (lagna + ch - 1) % 12, "degree": p["degree"]}
        rows.append({"planet": name, "rasi_house": p["house"], "chalit_house": ch, "shifted": ch != p["house"]})
    return {"chart": chart, "rows": rows,
            "note": "Bhava chalit places each planet in the house whose span (not sign) contains it."}


def planet_rows(facts: dict) -> list[dict]:
    cd = facts.get("compound_dignity") or {}
    out = []
    for name, p in facts["planets"].items():
        deg = float(p["degree"])
        d, rem = int(deg), (deg - int(deg)) * 60
        m, s = int(rem), (rem - int(rem)) * 60
        out.append({"planet": name, "sign": p["sign_name"], "house": p["house"],
                    "longitude_dms": f"{d}°{m:02d}′{s:04.1f}″",
                    "nakshatra": p["nakshatra"]["name"], "pada": p["nakshatra"]["pada"],
                    "nakshatra_lord": p["nakshatra"].get("lord", ""),
                    "dignity": p.get("dignity", []),
                    "compound_dignity": (cd.get(name) or {}).get("relation"),
                    "avastha": p.get("avastha"),
                    "flags": [f for f, on in (("retrograde", p["retrograde"]), ("combust", p["combust"]),
                                              ("vargottama", p["vargottama"])) if on]})
    return out


def settings_line(facts: dict) -> str:
    m = facts["meta"]
    return (f"{m['ayanamsa']['id']} ayanamsa {m['ayanamsa']['dms']} · {m['node']} nodes · "
            f"{m['dasha_year']['mode']} year ({m['dasha_year']['days']} days)")


def build_report_views(p: BirthProfile) -> dict:
    facts = orchestrator.chart_facts(p)
    birth = orchestrator.birth_input(p)
    from .astro import matching as M

    def safe(fn):
        try:
            return fn()
        except Exception as exc:
            log.exception("report view section failed")
            return {"unavailable": f"{type(exc).__name__}: {exc}"}
    known = birth.birth_time_precision != "unknown"
    return {
        "time_known": known,
        "settings_line": settings_line(facts),
        "dasha": {"vimshottari": safe(lambda: dasha_tree(facts)), "yogini": safe(lambda: yogini_tree(birth)),
                  "chara": safe(lambda: chara_tree(birth))},
        "panchang": safe(lambda: birth_panchang(facts, birth)),
        "avakahada": M.avakahada(facts),
        "shadbala": shadbala_table(facts) if known else None,
        "chalit": chalit_view(facts) if known else None,
        "planets": planet_rows(facts),
        "ashtakavarga": {"signs": K.SIGN_NAMES, "planets": list(K.PLANET_NAMES.values())[:7],
                         "bav": facts.get("binnashtakavarga"), "sav": facts.get("sarvastakavarga")},
    }


@router.get("/api/report-views")
def report_views(user: User = Depends(current_user)):
    return build_report_views(_main()._require_profile(user))


@router.get("/api/report.pdf")
def report_pdf_endpoint(user: User = Depends(current_user)):
    from . import report_pdf
    p = _main()._require_profile(user)
    views = build_report_views(p)
    facts = orchestrator.chart_facts(p)
    data = report_pdf.build_pdf(p.display_name or "Chart", facts, views)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="kundli.pdf"'})


# ------------------------------------------------------------------ convergence v2 (read-only)

class ConvergenceIn(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None


_CONVERGENCE_SPECIAL_OK = {"SADE_SATI", "CURRENT_DASHA", "ANNUAL_THEMES", "LIFE_TRANSITION",
                           "STRESS_PHASE", "EMOTIONAL_SUPPORT"}
_CONVERGENCE_MAX_DAYS = 366 * 3


def _evidence_rows(evs) -> list:
    from .astro.convergence.serialize import jsonable
    return [{"rule_id": e.rule_id, "rule_version": e.rule_version, "direction": e.direction,
             "weight": e.weight, "factors": sorted(e.factors), "fact_ids": list(e.fact_ids),
             "interval": jsonable(e.interval), "text": e.text, "ne_reason": e.ne_reason} for e in evs]


def _window_view(w, display_type=None, segment=None) -> dict:
    from .astro.convergence import dedup
    from .astro.convergence.serialize import jsonable
    return {"segment": jsonable(segment), "interval": jsonable(w.interval), "result_type": w.result_type,
            "display_type": display_type or w.result_type, "badge": w.badge, "n": w.n,
            "k_evaluated": w.k_evaluated, "dependent": list(w.dependent), "ne_pillars": list(w.ne_pillars),
            "pillars": [{"pillar": p.pillar, "value": p.value, "label": p.label, "ne_reason": p.ne_reason,
                         "interval": jsonable(p.interval), "dependent_on": list(p.dependent_on)} for p in w.pillars],
            "kp": dedup.kp_label(w.kp), "kp_reason": w.kp.ne_reason if w.kp else None,
            "supportive_evidence": _evidence_rows(w.supportive_evidence),
            "conflicting_evidence": _evidence_rows(w.conflicting_evidence),
            "notes": list(w.notes), "rule_ids": dedup.rule_ids(w), "disclaimer": w.disclaimer,
            "overlay": jsonable(w.overlay) if w.overlay is not None else None}


@router.post("/api/convergence/{intent_id}")
def convergence_intent(intent_id: str, body: ConvergenceIn, user: User = Depends(current_user)):
    """Read-only convergence v2 result for one spec intent (no chat/LLM involvement)."""
    from .astro.convergence import intents as conv_intents
    from .astro.convergence import template_t
    from .astro.convergence.serialize import jsonable
    key = int(intent_id) if intent_id.isdigit() else intent_id.upper()
    cfg = conv_intents.get(key)
    if cfg is None:
        raise HTTPException(404, "unknown intent")
    p = _main()._require_profile(user)
    birth = orchestrator.birth_input(p)
    facts = orchestrator.chart_facts(p)
    today = orchestrator._today_at(birth)
    start = body.start or today
    end = body.end or (start + timedelta(days=364))
    if end < start:
        raise HTTPException(422, "end must not precede start")
    if (end - start).days > _CONVERGENCE_MAX_DAYS:
        raise HTTPException(422, "Choose a range of at most three years.")
    if cfg.template == "special" and cfg.intent_id not in _CONVERGENCE_SPECIAL_OK:
        raise HTTPException(422, f"{cfg.intent_id} needs extra input; use its dedicated tool.")
    try:
        res = template_t.run_intent(facts, birth, cfg, start, end, today=today)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    out = {"intent_id": cfg.intent_id, "number": cfg.number, "template": cfg.template,
           "range": [start.isoformat(), end.isoformat()], "kp_status": cfg.KP["status"],
           "time_known": birth.birth_time_precision != "unknown"}
    if "timing" in res:
        t = res["timing"]
        out["timing"] = {"framing": t.framing, "notes": list(t.notes), "rulepack_hash": t.rulepack_hash,
                         "promise": jsonable(t.promise) if t.promise is not None else None,
                         "windows": [_window_view(w.result, w.display_type, w.segment) for w in t.windows]}
    if "natal" in res:
        out["natal"] = _window_view(res["natal"])
        out["natal"]["promise"] = jsonable(res["natal"].promise) if res["natal"].promise else None
    if "special" in res:
        out["special"] = jsonable(res["special"])
    return out
