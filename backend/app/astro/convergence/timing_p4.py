"""P4 micro-timing (Ashtakavarga + Kakshya + fast transits + Tarabala), spec 1.4.

evaluate() returns a list of PillarResult, one per (trigger planet, stay) micro-window:
  1 trigger planet in TRIG transits the primary E-house sign / D1 E-lord sign / karaka sign
  2 BAV of the planet in that sign: >=4 support, >=5 strong, <=2 adverse; SAV(E-house) >=28 raises weight
  3 Kakshya: narrow to the 3deg45' slice whose lord contributed a bindu to the planet's BAV in that sign
  4 fast triggers (Mars/Sun in cfg.TRIG.fast) transiting or aspecting E-house / E-lord sign: month-level
  5 transit over natal nakshatra of the E-lord / a karaka with supportive Tarabala (from natal Moon)
S = 1+2(>=4)+3, W = 1+2 only (or 1 with BAV 3 / no BAV for nodes), A = BAV <=2.
A planet the transit scanner does not support (transits.BODIES) is skipped with an NE result that
carries the reason; it never raises. "A = BAV <=2 for every trigger planet" is decided per window
by template_t.aggregate_p4.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import swisseph as swe
from jhora.panchanga import drik

from .. import constants as K
from .. import precision, transits
from ..engine import apply, calc_lock
from . import _ivl, links, rulepack
from ._facts import unknown_time
from .promise import resolve_karakas
from .timing_p3 import NO_BIRTH_TIME, event_houses
from .types import A, S, W, Evidence, IntentConfig, PillarResult

PILLAR = "P4"
R_TRIG, R_BAV, R_SAV = "P4_TRIGGER_INGRESS", "P4_BAV_THRESHOLDS", "P4_SAV_WEIGHT"
R_KAK, R_FAST, R_TARA, R_RESULT = "P4_KAKSHYA_NARROWING", "P4_FAST_TRIGGERS", "P4_TARABALA", "P4_RESULT"
BAV_SUPPORT, BAV_STRONG, BAV_ADVERSE, SAV_HIGH = 4, 5, 2, 28
SUPPORTIVE_TARAS = {2, 4, 6, 8, 9}        # Sampat, Kshema, Sadhaka, Mitra, Parama Mitra
MAX_DAYS = 366 * 15
_PID = {n: i for i, n in K.PLANET_NAMES.items()}


def _ev(rule, direction, weight, factors, text, fids=(), interval=None, ne_reason=None):
    return Evidence(rule, rulepack.version(rule), tuple(fids), direction, round(weight, 4),
                    frozenset(factors), interval, text, ne_reason)


def bav_grade(bav: Optional[int]) -> str:
    """'strong' (>=5) | 'support' (4) | 'neutral' (3) | 'adverse' (<=2) | 'none' (no BAV)."""
    if bav is None:
        return "none"
    if bav >= BAV_STRONG:
        return "strong"
    if bav >= BAV_SUPPORT:
        return "support"
    return "adverse" if bav <= BAV_ADVERSE else "neutral"


def _d(ts: str):
    return _ivl.to_date(ts)


def _stays(tr: dict) -> list:
    """[(sign, start_date, end_date)] from the scan's sign ingresses."""
    out, cur, sign = [], _d(tr["start"]), tr["initial_sign"]
    for e in tr["events"]:
        if e["kind"] != "sign_ingress":
            continue
        d = _d(e["at"])
        out.append((sign, cur, d))
        cur, sign = d, e["sign_index"]
    out.append((sign, cur, _d(tr["end"])))
    return out


def _nak_stays(birth, planet, tr, jd_start) -> list:
    """[(nakshatra_name, start, end)] from nakshatra ingresses plus the opening nakshatra."""
    first = next((e["from"] for e in tr["events"] if e["kind"] == "nakshatra_ingress"), None)
    try:
        with calc_lock:
            apply(birth.settings)
            lon = swe.calc_ut(jd_start, transits.BODIES[planet], drik.PLANET_FLAGS)[0][0] % 360
        first = K.NAKSHATRAS[int(lon // K.NAK_SPAN) % 27]
    except Exception:
        pass
    if first is None:
        return []
    out, cur, nak = [], _d(tr["start"]), first
    for e in tr["events"]:
        if e["kind"] != "nakshatra_ingress":
            continue
        d = _d(e["at"])
        out.append((nak, cur, d))
        cur, nak = d, e["to"]
    out.append((nak, cur, _d(tr["end"])))
    return out


def _targets(facts, cfg) -> dict:
    """sign -> {'reasons': [...], 'factors': set()} for the primary E-house sign, its D1 lord's sign and karakas."""
    h0 = cfg.primary_house
    t: dict = {}

    def add(sign, reason, factors):
        d = t.setdefault(sign, {"reasons": [], "factors": set()})
        d["reasons"].append(reason)
        d["factors"] |= set(factors)

    add(links.house_sign(facts, h0), f"primary E-house {h0} sign", {f"HOUSE:{h0}"})
    lord = links.lord_of(facts, h0)
    add(facts["planets"][lord]["sign"], f"D1 E-lord {lord} sign", {f"LORD:H{h0}", f"PLANET:{lord.upper()}"})
    for k in resolve_karakas(cfg, facts):
        add(facts["planets"][k]["sign"], f"karaka {k} sign", {f"PLANET:{k.upper()}"})
    return t


def _res(value, evs, iv):
    return PillarResult(PILLAR, value, tuple(evs), iv)


def _planet_results(facts, birth, cfg, planet, fast, tr, targets, start, end) -> list:
    pid = _PID[planet]
    bavs = facts.get("binnashtakavarga")
    sav = facts.get("sarvastakavarga")
    h0 = cfg.primary_house
    sav_e = sav[links.house_sign(facts, h0)] if sav else None
    prastara = facts.get("prastara_ashtakavarga")
    window = (start, end)
    tfac = {f"TRANSIT:PLANET:{planet.upper()}"}
    results = []
    for sign, d0, d1 in _stays(tr):
        iv = _ivl.overlap((d0, d1), window)
        if iv is None:
            continue
        sname = K.SIGN_NAMES[sign]
        if sign not in targets:
            if not fast:
                continue
            # item 4: fast trigger aspecting the E-house sign / E-lord sign (occupancy handled below)
            hit = [s for s in targets if s != sign and s in K.reaches(planet, sign)]
            if hit:
                fac = tfac | set().union(*(targets[s]["factors"] for s in hit))
                results.append(_res(W, [_ev(R_FAST, 1, 0.5, fac,
                                            f"fast trigger {planet} in {sname} aspects "
                                            f"{', '.join(targets[s]['reasons'][0] for s in hit)} "
                                            f"({_ivl.fmt(iv)}, month-level)", [f"transit.{planet}"], iv)], iv))
            continue
        tgt = targets[sign]
        evs = [_ev(R_TRIG, 1, 1.0, tfac | tgt["factors"],
                   f"{planet} transits {sname}: " + "; ".join(tgt["reasons"]) + f" ({_ivl.fmt(iv)})",
                   [f"transit.{planet}"], iv)]
        if fast:
            evs.append(_ev(R_FAST, 1, 0.5, tfac, f"fast trigger {planet}: month-level window", [f"transit.{planet}"], iv))
        bav = int(bavs[pid][sign]) if bavs and pid < 7 and len(bavs) > pid else None
        grade = bav_grade(bav)
        bfac = {f"BAV:{planet.upper()}:{sign}"}
        if grade in ("strong", "support"):
            w = 1.5 if grade == "strong" else 1.0
            note = f"{planet} BAV in {sname} = {bav} ({grade})"
            if sav_e is not None and sav_e >= SAV_HIGH:
                w += 0.5
                note += f"; SAV of E-house sign = {sav_e} >= {SAV_HIGH} raises weight"
            evs.append(_ev(R_BAV, 1, w, bfac | ({f"SAV:HOUSE:{h0}"} if sav_e is not None and sav_e >= SAV_HIGH else set()),
                           note, ["binnashtakavarga"], iv))
            charged = []
            if prastara:
                for sl in tr["kakshya_slices"]:
                    if sl["sign_index"] != sign:
                        continue
                    siv = _ivl.overlap((_d(sl["start"]), _d(sl["end"])), iv)
                    if siv and precision._kakshya_charged(prastara, pid, sign, sl["index"] * precision.KAKSHYA_SPAN + 1):
                        charged.append((sl["index"], siv))
            if charged:
                for idx, siv in charged:
                    lord = precision.kakshya_lord(idx)
                    kev = _ev(R_KAK, 1, 1.0, {f"KAKSHYA:{planet.upper()}:{sign}:{idx}"},
                              f"{planet} in {lord} kakshya of {sname} ({_ivl.fmt(siv)}): {lord} gave a bindu "
                              f"in {planet}'s BAV for {sname}", ["prastara_ashtakavarga"], siv)
                    results.append(_res(S, evs + [kev], siv))
            else:
                results.append(_res(W, evs, iv))
        elif grade == "adverse":
            evs.append(_ev(R_BAV, -1, 1.0, bfac, f"{planet} BAV in {sname} = {bav} (<= {BAV_ADVERSE}, adverse)",
                           ["binnashtakavarga"], iv))
            results.append(_res(A, evs, iv))
        else:
            evs.append(_ev(R_BAV, 0, 0.0, bfac, f"{planet} BAV in {sname} = {bav}"
                           if bav is not None else f"no BAV exists for {planet}: item 2 not evaluated",
                           ["binnashtakavarga"], iv, ne_reason=None if bav is not None else "BAV undefined for nodes"))
            results.append(_res(W, evs, iv))
    return results


def _tarabala(facts, birth, cfg, planet, tr, start, jd_start) -> list:
    """[(interval, Evidence)] where `planet` sits in the natal nakshatra of the E-lord / a karaka
    and that nakshatra is a supportive tara counted from the natal Moon's nakshatra."""
    moon_nak = int(facts["planets"]["Moon"]["nakshatra"]["index"])
    xs = {links.lord_of(facts, cfg.primary_house)} | set(resolve_karakas(cfg, facts))
    out = []
    for x in sorted(xs):
        nk = facts["planets"][x]["nakshatra"]
        n_idx = int(nk["index"])
        tara, tname = precision.tara_of(n_idx, moon_nak)
        if tara not in SUPPORTIVE_TARAS:
            continue
        for name, d0, d1 in _nak_stays(birth, planet, tr, jd_start):
            if name != nk["name"]:
                continue
            iv = _ivl.overlap((d0, d1), (start, _d(tr["end"])))
            if iv:
                out.append((iv, _ev(R_TARA, 1, 0.5, {f"TRANSIT:PLANET:{planet.upper()}", f"NAKSHATRA:{x.upper()}"},
                                    f"{planet} transits {nk['name']}, natal nakshatra of {x} "
                                    f"({tname} tara from natal Moon, supportive) ({_ivl.fmt(iv)})",
                                    [f"transit.{planet}", f"planets.{x}.nakshatra"], iv)))
    return out


def evaluate(facts: dict, birth, cfg: IntentConfig, start, end) -> list:
    start, end = _ivl.to_date(start), _ivl.to_date(end)
    rng = (start, end)
    if unknown_time(facts, birth) or not facts.get("lagna"):
        return [PillarResult.not_evaluated(PILLAR, NO_BIRTH_TIME.replace("P3", "P4"), rng)]
    if not event_houses(cfg):
        return [PillarResult.not_evaluated(PILLAR, "intent has no event houses", rng)]
    if end <= start:
        end = start + timedelta(days=1)
    if (end - start).days > MAX_DAYS:
        return [PillarResult.not_evaluated(PILLAR, "range longer than the 15-year transit scan limit", rng)]
    targets = _targets(facts, cfg)
    jd_start = swe.julday(start.year, start.month, start.day, 0)
    results, skipped = [], []
    planets = list(dict.fromkeys([*cfg.TRIG["slow"], *cfg.TRIG["fast"]]))
    taras = []
    for planet in planets:
        if planet not in transits.BODIES:
            skipped.append(f"trigger planet {planet} not supported by the transit scanner yet: skipped")
            continue
        try:
            tr = transits.scan(birth, start, end, planet)
        except Exception as exc:
            skipped.append(f"trigger planet {planet} transit scan failed ({type(exc).__name__}): skipped")
            continue
        results += _planet_results(facts, birth, cfg, planet, planet in cfg.TRIG["fast"], tr, targets, start, end)
        taras += _tarabala(facts, birth, cfg, planet, tr, start, jd_start)
    # item 5: attach Tarabala evidence to overlapping results; stand-alone W otherwise
    for iv, ev in taras:
        hit = [i for i, r in enumerate(results) if r.value != A and _ivl.overlap(r.interval, iv)]
        if hit:
            for i in hit:
                r = results[i]
                results[i] = PillarResult(PILLAR, r.value, r.evidence + (ev,), r.interval)
        else:
            results.append(_res(W, [ev], iv))
    results.sort(key=lambda r: (r.interval[0], r.interval[1]))
    if not results and len(skipped) < len(planets):
        results.append(PillarResult(PILLAR, W, (_ev(R_RESULT, 0, 0.0, set(),
                                                    "no trigger planet transits a target sign in this range"),), rng))
    for s in skipped:
        results.append(PillarResult.not_evaluated(PILLAR, s, rng))
    return results
