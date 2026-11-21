"""Graha strength: Shadbala vs BPHS minimum, Vimshopaka, Ishta/Kashta, avasthas.

`compute(facts, jd=None, place=None)` returns {planet: {...}} for Sun..Saturn and
is called by the engine under `calc_lock` (the optional jd/place are only used
for the Sun's ayana bala). Every helper below is pure and testable.

Rules
- STR.SHADBALA_MIN (BPHS ch.27, Shadbala): required minimum in rupas — Sun 6.5,
  Moon 6, Mars 5, Mercury 7, Jupiter 6.5, Venus 5.5, Saturn 5. PyJHora's table
  uses 5 for the Sun; `pyjhora_ratio` keeps its figure, `shadbala_ratio` uses BPHS.
- STR.VIMSHOPAKA (BPHS ch.7): Shodasha-varga scheme via PyJHora
  charts.vimsopaka_shodhasavarga_of_planets (out of 20).
- STR.ISHTA_KASHTA (BPHS, Ishta-Kashta phala): Ishta = sqrt(Uchcha x Cheshta),
  Kashta = sqrt((60-Uchcha) x (60-Cheshta)). Uchcha bala = arc from the deep
  debilitation point / 3. Cheshta bala: Mars..Saturn from PyJHora shadbala;
  Sun = ayana bala, Moon = paksha bala (the BPHS substitution).
- STR.BAALADI (BPHS ch.45): 6 deg bands Bala, Kumara, Yuva, Vriddha, Mrita in
  odd signs; reversed in even signs.
- STR.JAGRADADI (BPHS ch.45): own/exalted = Jagrat, friend/neutral sign = Swapna,
  enemy/debilitated = Sushupti (natural relationship to the sign lord).
- STR.DEEPTADI (BPHS ch.45, nine avasthas): precedence among the overlapping
  conditions varies by edition, so it is marked verified=False and kept out of
  LLM-facing text.
- STR.SUMMARY: app convention (points from the above), not a classical rule.
"""
from __future__ import annotations

import logging
import math

from . import constants as K

log = logging.getLogger(__name__)

SEVEN = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
PID = {n: i for i, n in enumerate(SEVEN)}
BPHS_MIN_RUPAS = {"Sun": 6.5, "Moon": 6.0, "Mars": 5.0, "Mercury": 7.0,
                  "Jupiter": 6.5, "Venus": 5.5, "Saturn": 5.0}
SOURCES = {
    "shadbala_ratio": "BPHS ch.27 (Shadbala minimums)",
    "vimshopaka": "BPHS ch.7 (Vimshopaka, Shodasha-varga scheme) via PyJHora",
    "ishta_kashta": "BPHS (Ishta-Kashta phala): sqrt(Uchcha x Cheshta)",
    "baaladi": "BPHS ch.45 (Baaladi avastha)",
    "jagradadi": "BPHS ch.45 (Jagradadi avastha)",
    "deeptadi": "BPHS ch.45 (Deeptadi avastha) — precedence unverified",
    "summary": "app convention",
}
VERIFIED = {"shadbala_ratio": True, "vimshopaka": True, "ishta_kashta": True, "baaladi": True,
            "jagradadi": True, "deeptadi": False, "summary": True}
BAALADI = ["Bala", "Kumara", "Yuva", "Vriddha", "Mrita"]


# ------------------------------------------------------------------ pure helpers

def uchcha_bala(pid: int, abs_long: float) -> float:
    """Arc from the deep debilitation point / 3 (0..60 virupas)."""
    s, d = K.DEBILITATION[pid]
    deb = s * 30 + d
    arc = abs((abs_long - deb) % 360)
    if arc > 180:
        arc = 360 - arc
    return round(arc / 3.0, 2)


def paksha_cheshta(sun_long: float, moon_long: float) -> float:
    """Moon's cheshta = paksha bala: elongation from the Sun / 3 (0..60)."""
    e = (moon_long - sun_long) % 360
    if e > 180:
        e = 360 - e
    return round(e / 3.0, 2)


def ishta_kashta(uchcha: float, cheshta: float) -> tuple[float, float]:
    u = max(0.0, min(60.0, float(uchcha)))
    c = max(0.0, min(60.0, float(cheshta)))
    return round(math.sqrt(u * c), 2), round(math.sqrt((60 - u) * (60 - c)), 2)


def baaladi(sign: int, degree: float) -> str:
    band = min(4, int(float(degree) // 6))
    odd = int(sign) % 2 == 0           # Aries (0) is an odd sign
    return BAALADI[band] if odd else BAALADI[4 - band]


def _in_own_or_exalted(pid, sign):
    return sign in K.OWN_SIGNS.get(pid, []) or K.EXALTATION.get(pid, (None,))[0] == sign


def jagradadi(pid: int, sign: int) -> str:
    if _in_own_or_exalted(pid, sign):
        return "Jagrat"
    if K.DEBILITATION.get(pid, (None,))[0] == sign:
        return "Sushupti"
    rel = K.natural_relation(pid, K.SIGN_LORD[sign])
    return "Sushupti" if rel == "enemy" else "Swapna"


def deeptadi(pid: int, sign: int, degree: float, combust: bool, compound: str | None,
             with_malefic: bool = False) -> str:
    """Nine-fold avastha. Order used: Kopa (combust), Deepta (exalted), Swastha
    (own/moolatrikona), Khala (debilitated), then by compound relation to the sign
    lord: adhimitra Mudita, friend Shanta, neutral Deena, enemy Dukhita, adhishatru
    Khala; Vikala when only a malefic conjunction qualifies (verified=False)."""
    if combust:
        return "Kopa"
    if K.EXALTATION.get(pid, (None,))[0] == sign:
        return "Deepta"
    if sign in K.OWN_SIGNS.get(pid, []):
        return "Swastha"
    if K.DEBILITATION.get(pid, (None,))[0] == sign:
        return "Khala"
    if with_malefic and compound in (None, "neutral"):
        return "Vikala"
    rel = compound or K.natural_relation(pid, K.SIGN_LORD[sign])
    return {"adhimitra": "Mudita", "friend": "Shanta", "neutral": "Deena",
            "enemy": "Dukhita", "adhishatru": "Khala"}.get(rel, "Deena")


def summarise(ratio: float | None, vimshopaka: float | None, ishta: float | None,
              kashta: float | None, dignity: list | None = None) -> tuple[str, list[str]]:
    """STR.SUMMARY (app convention): +1/-1 points from each available measure."""
    pts, why = 0, []
    if ratio is not None:
        if ratio >= 1.0:
            pts += 1; why.append(f"shadbala {ratio:.2f}x of BPHS minimum")
        else:
            pts -= 1; why.append(f"shadbala below BPHS minimum ({ratio:.2f}x)")
        if ratio >= 1.3:
            pts += 1
    if vimshopaka is not None:
        if vimshopaka >= 12:
            pts += 1; why.append(f"vimshopaka {vimshopaka:.1f}/20")
        elif vimshopaka < 8:
            pts -= 1; why.append(f"low vimshopaka {vimshopaka:.1f}/20")
    if ishta is not None and kashta is not None:
        if ishta > kashta:
            pts += 1; why.append("ishta exceeds kashta")
        elif kashta > ishta:
            pts -= 1; why.append("kashta exceeds ishta")
    dig = set(dignity or [])
    if dig & {"exalted", "own sign", "moolatrikona"}:
        pts += 1; why.append("strong sign dignity")
    if "debilitated" in dig:
        pts -= 1; why.append("debilitated")
    label = "strong" if pts >= 3 else "weak" if pts <= -1 else "moderate"
    return label, why


# ------------------------------------------------------------------ compute

def _sun_ayana_cheshta(jd, place):
    if jd is None or place is None:
        return None
    try:
        from jhora.horoscope.chart import strength as jstrength
        return round(min(60.0, float(jstrength._ayana_bala(jd, place)[0]) / 2.0), 2)
    except Exception:
        log.exception("ayana bala unavailable")
        return None


def compute(facts: dict, jd=None, place=None) -> dict:
    """{planet: {shadbala_rupas, shadbala_required, shadbala_ratio, pyjhora_ratio, strong,
    vimshopaka, uchcha_bala, cheshta_bala, ishta, kashta, baaladi, jagradadi, deeptadi,
    summary, reasons, sources, verified}} for Sun..Saturn."""
    p = facts["planets"]
    shad = facts.get("shadbala")
    rupas = shad[7] if shad and len(shad) > 8 else None
    pj_ratio = shad[8] if shad and len(shad) > 8 else None
    cheshta_row = shad[3] if shad and len(shad) > 3 else None
    vims = facts.get("vimshopaka") or {}
    cd = facts.get("compound_dignity") or {}
    sun_long = p["Sun"]["abs_longitude"]
    sun_cheshta = _sun_ayana_cheshta(jd, place)
    malefics = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}
    out = {}
    for name in SEVEN:
        pid = PID[name]
        rec = p[name]
        sign, deg = int(rec["sign"]), float(rec["degree"])
        r = float(rupas[pid]) if rupas else None
        need = BPHS_MIN_RUPAS[name]
        ratio = round(r / need, 2) if r is not None else None
        u = uchcha_bala(pid, rec["abs_longitude"])
        if name == "Sun":
            c = sun_cheshta
        elif name == "Moon":
            c = paksha_cheshta(sun_long, rec["abs_longitude"])
        else:
            c = float(cheshta_row[pid]) if cheshta_row else None
        ishta, kashta = ishta_kashta(u, c) if c is not None else (None, None)
        rel = (cd.get(name) or {}).get("relation")
        with_mal = any(o != name and o in malefics and p[o]["sign"] == sign for o in p)
        v = vims.get(name)
        label, why = summarise(ratio, v, ishta, kashta, rec.get("dignity"))
        out[name] = {
            "shadbala_rupas": r, "shadbala_required": need, "shadbala_ratio": ratio,
            "pyjhora_ratio": float(pj_ratio[pid]) if pj_ratio else None,
            "strong": bool(ratio is not None and ratio >= 1.0),
            "vimshopaka": v, "uchcha_bala": u, "cheshta_bala": c,
            "ishta": ishta, "kashta": kashta,
            "baaladi": baaladi(sign, deg), "jagradadi": jagradadi(pid, sign),
            "deeptadi": deeptadi(pid, sign, deg, bool(rec.get("combust")),
                                 None if rel == "own" else rel, with_mal),
            "summary": label, "reasons": why,
            "sources": SOURCES, "verified": VERIFIED,
        }
    return out
