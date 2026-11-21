"""Deterministic KEY INDICATIONS digest sent to the model on every turn.

Everything here is read from the locked chart facts (plus the optional
running-dasha rows and transit positions); nothing is invented. A line whose
source field is absent is omitted. The text is authoritative context for the
model and is also part of the verifier's grounding.
"""
from __future__ import annotations

from datetime import date

from . import constants as K

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
SEVEN = PLANETS[:7]
_NODES = ("Rahu", "Ketu")
_ASPECTS = {"Mars": (4, 7, 8), "Jupiter": (5, 7, 9), "Saturn": (3, 7, 10)}  # nodes: 7th only
_TITLES = [("Atmakaraka", "AK", "self"), ("Amatyakaraka", "AmK", "career/advisor"),
           ("Bhratrukaraka", "BK", "siblings"), ("Matrukaraka", "MK", "mother/learning"),
           ("Putrakaraka", "PK", "children/creativity"), ("Gnatikaraka", "GK", "rivals/obstacles"),
           ("Darakaraka", "DK", "spouse")]
DOMAIN_ALIASES = {"marriage": "relationship", "wealth": "finance", "investment": "finance",
                  "wealth-investment": "finance", "stream": "education"}
NATURAL_KARAKAS = ("NATURAL karakas (these are NOT chara-karaka titles): Sun soul/father, Moon mind/mother, "
                   "Mars brothers/land, Mercury intellect, Jupiter wealth/children, Venus spouse/comforts, "
                   "Saturn longevity/service")


def _sn(i) -> str:
    return K.SIGN_NAMES[int(i) % 12]


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _rel(sign, ref) -> int:
    return (int(sign) - int(ref)) % 12 + 1


def _dig(facts, name) -> str:
    rec = facts["planets"].get(name) or {}
    bits = list(rec.get("dignity") or [])
    cd = (facts.get("compound_dignity") or {}).get(name)
    if cd and cd.get("relation") and not (cd["relation"] == "own" and any("own" in b for b in bits)):
        bits.append(f"{cd['relation']} sign (lord {cd.get('sign_lord')})")
    if rec.get("combust"):
        bits.append("combust")
    if rec.get("vargottama"):
        bits.append("vargottama")
    return ", ".join(bits)


def _place(facts, name) -> str:
    rec = facts["planets"].get(name)
    if not rec:
        return "?"
    d = _dig(facts, name)
    return f"{rec['sign_name']} H{rec['house']}" + (f" ({d})" if d else "")


def _lords(facts, ref_sign) -> list[str]:
    """house-from-reference -> lord -> placement, as compact items."""
    out = []
    for h in range(1, 13):
        sign = (int(ref_sign) + h - 1) % 12
        lord = K.PLANET_NAMES[K.SIGN_LORD[sign]]
        rec = facts["planets"].get(lord)
        if rec is None:
            continue
        out.append(f"{h}:{lord}({_sn(sign)[:3]})@{_rel(rec['sign'], ref_sign)}")
    return out


def _lord_of_house(facts, h):
    rec = (facts.get("houses") or {}).get(h) or (facts.get("houses") or {}).get(str(h)) or {}
    return rec.get("lord")


def _varga_house(facts, varga, planet):
    v = (facts.get("vargas") or {}).get(varga) or {}
    lag, rec = v.get("Lagna"), v.get(planet)
    if not lag or not rec:
        return None
    return rec["sign"], _rel(rec["sign"], lag["sign"])


def _varga_line(facts, varga, planets) -> str | None:
    v = (facts.get("vargas") or {}).get(varga)
    if not v or "Lagna" not in v:
        return None
    items = []
    for pl in planets:
        r = _varga_house(facts, varga, pl)
        if r:
            items.append(f"{pl} {_sn(r[0])} H{r[1]}")
    return f"{varga} Lagna {_sn(v['Lagna']['sign'])}" + ("; " + ", ".join(items) if items else "")


def _aspect_map(facts) -> dict[int, list[str]]:
    got: dict[int, list[str]] = {}
    for name in PLANETS:
        rec = facts["planets"].get(name)
        if not rec:
            continue
        for d in _ASPECTS.get(name, (7,)):
            h = (rec["house"] + d - 2) % 12 + 1
            got.setdefault(h, []).append(name)
    return got


def _yoga_label(y: dict) -> str:
    name = y.get("name") or y.get("id") or "?"
    status = next((str(y[k]) for k in ("status", "state", "activity", "label") if y.get(k)), "")
    level = y.get("level")
    tags = [t for t in (status, level) if t]
    return name + (f" [{', '.join(tags)}]" if tags else "")


def _yogas(facts) -> list[dict]:
    found = facts.get("yogas")
    if found is None:
        try:
            from . import yogas
            found = yogas.detect(facts)
        except Exception:
            found = []
    if isinstance(found, dict):
        found = found.get("yogas") or found.get("found") or []
    return [y for y in found if isinstance(y, dict)]


def _dasha_rows(facts, birth, today) -> list[dict]:
    rows = facts.get("current_vimshottari")
    if rows:
        return rows
    if birth is not None:
        try:
            from .engine import engine
            return engine.running_vimshottari(birth, (today.year, today.month, today.day))
        except Exception:
            pass
    iso = today.isoformat()
    for p in (facts.get("vimshottari") or {}).get("periods", []):
        if p["start"] <= iso < p["end"]:
            return [p]
    return []


def _dasha_lines(facts, birth, today) -> list[str]:
    out = []
    rows = _dasha_rows(facts, birth, today)
    labels = ["MD", "AD", "PD"]
    if rows and all(len(r.get("lords", [])) == 1 + i for i, r in enumerate(rows[:3])):
        cur = "; ".join(f"{labels[i]} {r['lords'][-1]} {r['start']} to {r['end']}" for i, r in enumerate(rows[:3]))
    elif rows:
        r = rows[0]
        cur = f"MD {r['lords'][0]}, AD {r['lords'][-1]}: {r['start']} to {r['end']}"
    else:
        cur = ""
    periods = (facts.get("vimshottari") or {}).get("periods", [])
    iso = today.isoformat()
    if not cur:
        cur_p = next((p for p in periods if p["start"] <= iso < p["end"]), None)
        if cur_p:
            cur = f"MD {cur_p['maha']} AD {cur_p['antar']}: {cur_p['start']} to {cur_p['end']}"
    if cur:
        out.append("DASHA now (Vimshottari): " + cur)
        md_lord = rows[0]["lords"][0] if rows else None
        if md_lord:
            md = next((p for p in periods if p["maha"] == md_lord and p["start"] <= iso < p["end"]), None)
            if md:
                allm = [p for p in periods if p["maha"] == md_lord]
                out.append(f"  {md_lord} Mahadasha runs {allm[0]['start']} to {allm[-1]['end']}; "
                           f"{md_lord} rules houses {_owned(facts, md_lord)}")
    nxt = [p for p in periods if p["start"] > iso][:3]
    if nxt:
        out.append("  Next Antardashas: " + "; ".join(
            f"{p['maha']}-{p['antar']} {p['start']} to {p['end']}" for p in nxt))
    for r in rows[:2]:
        lord = r["lords"][-1]
        out.append(f"  {lord}: rules houses {_owned(facts, lord)}, sits {_place(facts, lord)}")
    return out


def _owned(facts, planet) -> str:
    hs = [h for h in range(1, 13) if _lord_of_house(facts, h) == planet]
    return ",".join(map(str, hs)) or "none (node; acts via dispositor, conjuncts, star lord)"


def _gochara(facts, birth, today) -> list[str]:
    if birth is None:
        return []
    try:
        from .engine import engine
        from . import precision
        pos = engine.transit_positions((today.year, today.month, today.day), precision._place(birth), birth.settings)
    except Exception:
        return []
    lag, moon = facts["lagna"]["sign"], facts["planets"]["Moon"]["sign"]
    items = []
    for pl in ("Saturn", "Jupiter", "Rahu", "Ketu"):
        if pl in pos:
            s = pos[pl]["sign"]
            items.append(f"{pl} in {_sn(s)} (H{_rel(s, lag)} from Lagna, H{_rel(s, moon)} from Moon)")
    if not items:
        return []
    out = [f"GOCHARA (transit) on {today.isoformat()}: " + "; ".join(items)]
    if "Saturn" in pos:
        r = _rel(pos["Saturn"]["sign"], moon)
        status = {12: "Sade Sati first phase (Saturn 12th from Moon)", 1: "Sade Sati peak phase (Saturn over Moon)",
                  2: "Sade Sati last phase (Saturn 2nd from Moon)", 4: "Kantaka Shani (Saturn 4th from Moon)",
                  8: "Ashtama Shani (Saturn 8th from Moon)"}.get(r)
        out.append("  Saturn from Moon: " + (status or f"{_ord(r)} house; no Sade Sati/Kantaka/Ashtama"))
    return out


def _domain_lines(facts, domain, birth, today) -> list[str]:
    d = DOMAIN_ALIASES.get(domain, domain)
    p, jk = facts["planets"], (facts.get("jaimini") or {})
    kar, arud = jk.get("karakas") or {}, jk.get("arudhas") or {}
    lag, moon = facts["lagna"]["sign"], p["Moon"]["sign"]
    sav = facts.get("sarvastakavarga")

    def sav_h(h):
        return f"SAV H{h}={sav[(lag + h - 1) % 12]}" if sav else ""

    def lordline(h):
        lord = _lord_of_house(facts, h)
        return f"{_ord(h)} house {_sn((lag + h - 1) % 12)}, lord {lord} in {_place(facts, lord)}" if lord else ""

    def at(h):
        names = [n for n in PLANETS if p[n]["house"] == h]
        return ("planets in it: " + ", ".join(names)) if names else "no planets in it"

    def arud_line(*keys):
        bits = [f"{k} {_sn(arud[k])} (H{_rel(arud[k], lag)})" for k in keys if k in arud]
        return ", ".join(bits)

    out = []
    if d == "career":
        out.append(f"DOMAIN career: {lordline(10)}; {at(10)}")
        out.append(f"  10th from Moon: {_sn((moon + 9) % 12)} (lord {K.PLANET_NAMES[K.SIGN_LORD[(moon + 9) % 12]]}), "
                   f"planets there: " + (", ".join(n for n in PLANETS if _rel(p[n]["sign"], moon) == 10) or "none"))
        if kar.get("Amatyakaraka"):
            out.append("  " + "; ".join(x for x in (
                f"AmK {kar['Amatyakaraka']} in {_place(facts, kar['Amatyakaraka'])}",
                arud_line("A10"), sav_h(10)) if x))
        l10 = _lord_of_house(facts, 10)
        out.append("  " + (_varga_line(facts, "D10", [l10] if l10 else []) or "D10 unavailable"))
    elif d == "finance":
        for h in (2, 11):
            out.append(f"DOMAIN wealth {_ord(h)}: {lordline(h)}; {at(h)}; {sav_h(h)}" if h == 2
                       else f"  {_ord(h)}: {lordline(h)}; {at(h)}; {sav_h(h)}")
        out.append(f"  Jupiter in {_place(facts, 'Jupiter')}; {arud_line('A2', 'A11')}")
        dhana = [_yoga_label(y) for y in _yogas(facts) if "dhana" in (y.get("name", "") + y.get("id", "")).lower()]
        if dhana:
            out.append("  Dhana yogas: " + ", ".join(dhana))
        out.append(f"  Investment view: gains houses 2/5/11 {sav and [sav[(lag + h - 1) % 12] for h in (2, 5, 11)]} "
                   f"vs loss houses 8/12 {sav and [sav[(lag + h - 1) % 12] for h in (8, 12)]} (SAV); "
                   "5th house is speculation, never recommended")
    elif d == "education":
        for h in (4, 5, 9):
            out.append((f"DOMAIN education: " if h == 4 else "  ") + lordline(h) + f"; {at(h)}")
        out.append(f"  Mercury {_place(facts, 'Mercury')}; Jupiter {_place(facts, 'Jupiter')}"
                   + (f"; MK {kar['Matrukaraka']}" if kar.get("Matrukaraka") else ""))
        l5 = _lord_of_house(facts, 5)
        out.append("  " + (_varga_line(facts, "D24", [x for x in {_lord_of_house(facts, 4), l5} if x]) or "D24 unavailable"))
    elif d == "relationship":
        out.append(f"DOMAIN marriage: {lordline(7)}; {at(7)}; {sav_h(7)}")
        dk = kar.get("Darakaraka")
        out.append(f"  Venus {_place(facts, 'Venus')}" + (f"; DK {dk} in {_place(facts, dk)}" if dk else ""))
        ul = jk.get("upapada_lagna")
        if ul:
            out.append(f"  UL {ul['sign_name']} (H{_rel(ul['sign'], lag)}); lord "
                       f"{K.PLANET_NAMES[K.SIGN_LORD[ul['sign']]]}")
        l7 = _lord_of_house(facts, 7)
        out.append("  " + (_varga_line(facts, "D9", [l7] if l7 else []) or "D9 unavailable"))
        v9 = (facts.get("vargas") or {}).get("D9") or {}
        if "Lagna" in v9:
            s7 = (v9["Lagna"]["sign"] + 6) % 12
            out.append(f"  D9 7th house {_sn(s7)}, lord {K.PLANET_NAMES[K.SIGN_LORD[s7]]}")
    return [x for x in out if x.strip()]


# Yogas whose conditions do not depend on the Lagna (safe when the birth time is unknown).
_TIME_FREE_YOGAS = ("GAJAKESARI", "BUDHADITYA", "CHANDRA_MANGALA", "SUNAPHA", "ANAPHA", "DURUDHARA",
                    "KEMADRUMA", "VESI", "VASI", "UBHAYACHARI", "ADHI", "SHAKATA")
_LAGNA_KEYS = ("vargas", "bhava", "shadbala", "bhava_bala", "functional", "strength", "varga_reliability",
               "varga_analysis", "bhava_judgement", "special_points", "education", "sarvastakavarga")


def chandra_view(facts: dict) -> dict:
    """Facts re-based on the Moon as Lagna (Chandra Lagna) with every Lagna- or
    birth-time-dependent block removed. Used when the birth time is unknown."""
    p = facts["planets"]
    moon = int(p["Moon"]["sign"])
    planets = {n: {**r, "house": _rel(r["sign"], moon)} for n, r in p.items()}
    houses = {h: {"sign": (moon + h - 1) % 12, "sign_name": _sn(moon + h - 1),
                  "lord": K.PLANET_NAMES[K.SIGN_LORD[(moon + h - 1) % 12]]} for h in range(1, 13)}
    out = {k: v for k, v in facts.items() if k not in _LAGNA_KEYS}
    out.update(planets=planets, houses=houses,
               lagna={"sign": moon, "sign_name": _sn(moon), "lord": K.PLANET_NAMES[K.SIGN_LORD[moon]],
                      "chandra": True})
    jk = dict(facts.get("jaimini") or {})
    for k in ("arudha_lagna", "upapada_lagna", "A10", "arudhas", "al_houses", "raja_yogas"):
        jk.pop(k, None)
    if jk.get("karakamsha") and jk["karakamsha"].get("atmakaraka") == "Moon":
        jk.pop("karakamsha")        # the Moon's navamsa can change within hours
    out["jaimini"] = jk
    out["yogas"] = [y for y in (facts.get("yogas") or []) if y.get("id") in _TIME_FREE_YOGAS]
    return out


def _strength_line(facts) -> str | None:
    st = facts.get("strength")
    if not st:
        return None
    items = [f"{n} {r['summary']} ({r['shadbala_ratio']}x, vimshopaka {r['vimshopaka']:.1f}/20, "
             f"{r['baaladi']}/{r['jagradadi']})" if r.get("shadbala_ratio") is not None and r.get("vimshopaka") is not None
             else f"{n} {r['summary']}" for n, r in st.items()]
    return "STRENGTH (shadbala vs BPHS minimum, vimshopaka, Baaladi/Jagradadi avastha): " + "; ".join(items)


def _avastha_line(facts) -> str | None:
    try:
        from . import strength as S
    except Exception:
        return None
    p = facts["planets"]
    items = [f"{n} {S.baaladi(p[n]['sign'], p[n]['degree'])}/{S.jagradadi(S.PID[n], p[n]['sign'])}"
             for n in SEVEN if n != "Moon" and "degree" in p[n]]
    return "Avasthas (Baaladi/Jagradadi; time-independent): " + ", ".join(items) if items else None


def _varga_rel_line(facts) -> str | None:
    vr = facts.get("varga_reliability")
    if not vr:
        return None
    keep = [v for v in ("D9", "D10", "D7", "D24", "D12", "D4", "D60") if v in vr]
    return ("VARGA reliability vs stated birth time: " + ", ".join(f"{v} {vr[v]}" for v in keep)
            + " (never read an unusable varga; hedge cusp_sensitive ones)")


def _bhava_lines(facts, domain) -> list[str]:
    bj = facts.get("bhava_judgement")
    d = DOMAIN_ALIASES.get(domain, domain)
    spec = K.DOMAINS.get(d)
    if not bj or not spec:
        return []
    items = []
    for h in spec["houses"][:3]:
        rec = bj.get(h) or bj.get(str(h))
        if not rec:
            continue
        top = sorted(rec["reasons"], key=lambda r: -abs(r["points"]))[:3]
        items.append(f"H{h} {rec['grade']} ({rec['score']:+g}: " + "; ".join(r["text"] for r in top) + ")")
    return ["  BHAVA judgement: " + " | ".join(items)] if items else []


def _rel_text(rel) -> str:
    base = f"{_ord(rel['house'])} from MD lord"
    return base + (f" ({rel['kind']})" if rel.get("verified") else "")


def _dasha_craft_lines(facts, birth, today, time_known) -> list[str]:
    try:
        from . import dasha_craft
        dc = dasha_craft.analyze(facts, birth, today, pravesh=False)
    except Exception:
        return []
    if not dc.get("available"):
        return []
    md, ad = dc["md"], dc["ad"]
    owns = "owns_from_lagna" if time_known else "owns_from_moon"
    ref = "" if time_known else " (houses from Moon)"
    line = (f"DASHA craft{ref}: AD {ad['lord']} is {_rel_text(dc['ad_from_md'])}; "
            f"{md['lord']} owns {','.join(map(str, md[owns])) or 'none'}, "
            f"{ad['lord']} owns {','.join(map(str, ad[owns])) or 'none'}")
    if time_known and dc.get("md_lord_dusthana"):
        line += f"; MD lord {md['lord']} in a dusthana"
    sd = dc["sandhi"]
    if sd["flag"]:
        line += "; DASHA SANDHI (" + ", ".join(k for k in ("md_sandhi", "ad_sandhi") if sd[k]) + ")"
    out = [line]
    if dc.get("next_ads"):
        out.append("  Next ADs from MD lord: " + "; ".join(
            f"{r['lord']} {_rel_text(r['from_md'])}" for r in dc["next_ads"]))
    return out


def _gochara_extra(facts, birth, today, time_known) -> list[str]:
    if birth is None:
        return []
    try:
        from . import gochara
        g = gochara.gochara(facts, birth, today, ingresses=True)
    except Exception:
        return []
    out = []
    vb = [f"{n} {r['vedha']['result']}" + (f" by {','.join(r['vedha']['obstructed_by'])}"
                                            if r['vedha']['obstructed_by'] else "")
          for n, r in g["planets"].items() if r["vedha"]["favourable_house"] and r["vedha"]["verified"]]
    bits = []
    if g.get("tarabala"):
        t = g["tarabala"]
        bits.append(f"Tarabala today {t['name']} ({'favourable' if t['favourable'] else 'adverse'})")
    if g.get("chandrabala"):
        c = g["chandrabala"]
        bits.append(f"Chandrabala Moon {_ord(c['house_from_natal_moon'])} from natal Moon "
                    f"({'favourable' if c['favourable'] else 'unfavourable'})")
    if g.get("saturn", {}).get("dhaiya"):
        bits.append("Shani Dhaiya (Saturn 4th/8th from Moon)")
    if vb:
        bits.append("Vedha from Moon: " + "; ".join(vb))
    if bits:
        out.append("  " + "; ".join(bits))
    bav = [f"{n} BAV {r['bav']}" + (f", kakshya {r['kakshya']['lord']} {'with' if r['kakshya'].get('bindu') else 'without'} bindu"
                                    if r.get("kakshya") and time_known else "")
           for n, r in g["planets"].items() if n in ("Saturn", "Jupiter") and "bav" in r]
    if bav:
        out.append("  Transit bindus: " + "; ".join(bav))
    ing = [f"{r['date']} {r['planet']} enters {r['sign']} (H{r['house_from_moon']} from Moon"
           + (f", H{r['house_from_lagna']} from Lagna)" if time_known else ")")
           for r in g.get("ingresses_12m", []) if r["planet"] in ("Saturn", "Jupiter", "Rahu")][:4]
    if ing:
        out.append("  Next 12 months: " + "; ".join(ing))
    return out


def _jaimini_depth_line(facts, time_known) -> str | None:
    jk = facts.get("jaimini") or {}
    bits = []
    kk = jk.get("karakamsha")
    if kk:
        bits.append(f"Karakamsha {kk['sign_name']} (AK {kk['atmakaraka']} in D9; D9 occupants "
                    f"{', '.join(kk['d9_occupants'])})")
    al = jk.get("al_houses")
    if al and time_known:
        bits.append(f"AL {al['sign_name']} with {', '.join(al['occupants']) or 'none'}; from AL "
                    + ", ".join(f"{_ord(h)} {al['h' + str(h)]['sign_name']}({','.join(al['h' + str(h)]['occupants']) or '-'})"
                                for h in (2, 7, 11, 12)))
    return "JAIMINI depth: " + "; ".join(bits) if bits else None


def _mangal_line(facts, time_known) -> str | None:
    try:
        from . import dosha
        refs = dosha.REFERENCES if time_known else ("Moon", "Venus")
        md = dosha.mangal_dosha(facts, references=refs)
    except Exception:
        return None
    if md["net"] == "absent":
        return f"  Mangal dosha: absent (checked from {', '.join(refs)})"
    frm = ", ".join(f"{r['reference']} {_ord(r['house'])}" for r in md["present_from"])
    cx = [c["text"] for c in md["cancellations"] if c["verified"]]
    return (f"  Mangal dosha (traditional matching factor): net {md['net']}; Mars counted from {frm}"
            + (f"; mitigations: {' '.join(c.rstrip('.') for c in cx)}" if cx else "")
            + ". Present gently; never as a verdict.")


def build_digest(facts: dict, birth=None, today: date | None = None, domain: str | None = None,
                 time_known: bool = True) -> str:
    """KEY INDICATIONS text. `birth` (BirthInput) enables the transit block and
    running-dasha lookup; `today` defaults to date.today(). With time_known=False
    every Lagna-based block is dropped and the Moon is read as Lagna (Chandra Lagna)."""
    today = today or date.today()
    full = facts
    if not time_known:
        facts = chandra_view(facts)
    p, lag = facts["planets"], facts["lagna"]
    lines = ["KEY INDICATIONS (precomputed from the chart; authoritative; internal, never recite as a list)"]
    lg = lag["lord"]
    if time_known:
        lines.append(f"Lagna {lag['sign_name']} (lord {lg}); Lagna lord {lg} in {_place(facts, lg)}")
    else:
        lines.append("BIRTH TIME UNKNOWN: no ascendant, houses-from-ascendant, divisional ascendants, arudhas "
                     "or bhava strengths are available. Houses below are counted from the Moon (Chandra Lagna).")
        lines.append(f"Chandra Lagna {lag['sign_name']} (lord {lg}); its lord {lg} in {_place(facts, lg)}")
    moon = p["Moon"]
    bh = (facts.get("bhava") or {}).get("Moon")
    nk = moon["nakshatra"]
    lines.append(f"Moon {moon['sign_name']}" + (f" H{moon['house']}" if time_known else "")
                 + (f" (bhava-chalit H{bh})" if bh else "")
                 + f"; {_dig(facts, 'Moon') or 'no special dignity'}; nakshatra {nk['name']} pada {nk['pada']}"
                 + (f" (star lord {nk['lord']})" if nk.get("lord") else ""))
    if time_known:
        lines.append("House lords from Lagna (house:lord(sign)@house of lord): " + " ".join(_lords(facts, lag["sign"])))
        lines.append("House lords from Moon (read as second Lagna): " + " ".join(_lords(facts, moon["sign"])))
    else:
        lines.append("House lords from Chandra Lagna (house:lord(sign)@house of lord): "
                     + " ".join(_lords(facts, moon["sign"])))

    f = facts.get("functional") or {}
    if f:
        roles = []
        bad = f.get("badhaka") or {}
        for name in SEVEN:
            tags = []
            if name == f.get("yogakaraka"):
                tags.append("yogakaraka")
            elif name in f.get("benefics", []):
                tags.append("functional benefic")
            elif name in f.get("malefics", []):
                tags.append("functional malefic")
            if bad.get("lord") == name:
                tags.append(f"badhaka (lord of {bad.get('house')}th)")
            if tags:
                text = f"{name} " + " AND ".join(tags)
                if name == lg and name in f.get("malefics", []):
                    text += " (but Lagna lord)"
                roles.append(text)
        lines.append("Functional roles: " + "; ".join(roles))

    groups = {}
    for n in PLANETS:
        groups.setdefault(p[n]["house"], []).append(n)
    conj = [f"H{h}: {'+'.join(ns)}" for h, ns in sorted(groups.items()) if len(ns) > 1]
    lines.append("Conjunctions: " + ("; ".join(conj) if conj else "none"))
    asp = _aspect_map(facts)
    lines.append("Graha drishti received by house (Mars 4/8, Jupiter 5/9, Saturn 3/10, all incl. nodes 7th): "
                 + "; ".join(f"H{h}<-{','.join(ns)}" for h, ns in sorted(asp.items())))

    for n in _NODES:   # nodes: never tagged retrograde (they always move backward)
        rec = p[n]
        disp = K.PLANET_NAMES[K.SIGN_LORD[rec["sign"]]]
        co = [x for x in PLANETS if x != n and p[x]["house"] == rec["house"]]
        nk = rec["nakshatra"]
        lines.append(f"{n} {rec['sign_name']} H{rec['house']}; dispositor {disp} in {_place(facts, disp)}; "
                     f"conjunct {', '.join(co) or 'none'}; star lord {nk.get('lord', '?')} ({nk['name']})")

    sb = facts.get("shadbala")
    if sb and len(sb) >= 9:
        rup, ratio = sb[7], sb[8]
        strong = [f"{n} {rup[i]}({ratio[i]}x)" for i, n in enumerate(SEVEN) if ratio[i] >= 1]
        weak = [f"{n} {rup[i]}({ratio[i]}x)" for i, n in enumerate(SEVEN) if ratio[i] < 1]
        lines.append("Shadbala rupas (x = ratio to required minimum): strong " + (", ".join(strong) or "none")
                     + "; weak " + (", ".join(weak) or "none"))
    extra = _strength_line(facts) if time_known else _avastha_line(facts)
    if extra:
        lines.append(extra)
    sav = facts.get("sarvastakavarga")
    if sav and len(sav) == 12:
        lines.append("SAV bindus by HOUSE from Lagna (avg 28; 30+ strong, under 25 weak): " + " ".join(
            f"H{h}={sav[(lag['sign'] + h - 1) % 12]}" for h in range(1, 13)))
    elif not time_known and full.get("sarvastakavarga") and len(full["sarvastakavarga"]) == 12:
        fs = full["sarvastakavarga"]
        lines.append("SAV bindus by HOUSE from Chandra Lagna (planet-only SAV is time-robust; avg 28): " + " ".join(
            f"H{h}={fs[(lag['sign'] + h - 1) % 12]}" for h in range(1, 13)))
    ys = _yogas(facts)
    if ys:
        lines.append("Yogas: " + "; ".join(_yoga_label(y) for y in ys))

    kl = [x for x in (_varga_line(facts, "D9", [lg, "Moon"]),
                      _varga_line(facts, "D10", [_lord_of_house(facts, 10)] if _lord_of_house(facts, 10) else []),
                      _varga_line(facts, "D24", [_lord_of_house(facts, 5)] if _lord_of_house(facts, 5) else []))
          if x]
    if kl:
        lines.append("Vargas (house counted from that varga's Lagna): " + " | ".join(kl))
    vr = _varga_rel_line(facts)
    if vr:
        lines.append(vr)

    jk = facts.get("jaimini") or {}
    kar = jk.get("karakas") or {}
    if kar:
        parts = [f"{ab} {kar[t]} ({meaning})" for t, ab, meaning in _TITLES if t in kar]
        lines.append("JAIMINI chara karakas (7-karaka by degree). ONLY these planets carry these titles: "
                     + ", ".join(parts))
        if jk.get("karaka_ties"):
            lines.append("  (tie noted between karakas: " + json_short(jk["karaka_ties"]) + ")")
        lines.append(NATURAL_KARAKAS)
        ar = []
        if jk.get("arudha_lagna"):
            ar.append(f"AL {jk['arudha_lagna']['sign_name']} (H{_rel(jk['arudha_lagna']['sign'], lag['sign'])})")
        if jk.get("upapada_lagna"):
            ar.append(f"UL {jk['upapada_lagna']['sign_name']} (H{_rel(jk['upapada_lagna']['sign'], lag['sign'])})")
        if jk.get("A10"):
            ar.append(f"A10 {jk['A10']['sign_name']} (H{_rel(jk['A10']['sign'], lag['sign'])})")
        if ar:
            lines.append("Arudhas: " + ", ".join(ar))
    jd_line = _jaimini_depth_line(facts, time_known)
    if jd_line:
        lines.append(jd_line)

    lines.extend(_dasha_lines(facts, birth, today))
    lines.extend(_dasha_craft_lines(facts, birth, today, time_known))
    if time_known:
        lines.extend(_gochara(facts, birth, today))
    else:
        lines.extend(_gochara_moon_only(facts, birth, today))
    lines.extend(_gochara_extra(full if time_known else facts, birth, today, time_known))
    if domain:
        lines.extend(_domain_lines(facts, domain, birth, today))
        if time_known:
            lines.extend(_bhava_lines(facts, domain))
        if DOMAIN_ALIASES.get(domain, domain) == "relationship":
            ml = _mangal_line(full, time_known)
            if ml:
                lines.append(ml)
    return "\n".join(lines)


def _gochara_moon_only(facts, birth, today) -> list[str]:
    """Transit block for an unknown birth time: houses from the natal Moon only."""
    if birth is None:
        return []
    try:
        from .engine import engine
        from . import precision
        pos = engine.transit_positions((today.year, today.month, today.day), precision._place(birth), birth.settings)
    except Exception:
        return []
    moon = facts["planets"]["Moon"]["sign"]
    items = [f"{pl} in {_sn(pos[pl]['sign'])} (H{_rel(pos[pl]['sign'], moon)} from Moon)"
             for pl in ("Saturn", "Jupiter", "Rahu", "Ketu") if pl in pos]
    if not items:
        return []
    out = [f"GOCHARA (transit) on {today.isoformat()}: " + "; ".join(items)]
    if "Saturn" in pos:
        r = _rel(pos["Saturn"]["sign"], moon)
        status = {12: "Sade Sati first phase (Saturn 12th from Moon)", 1: "Sade Sati peak phase (Saturn over Moon)",
                  2: "Sade Sati last phase (Saturn 2nd from Moon)", 4: "Kantaka Shani (Saturn 4th from Moon)",
                  8: "Ashtama Shani (Saturn 8th from Moon)"}.get(r)
        out.append("  Saturn from Moon: " + (status or f"{_ord(r)} house; no Sade Sati/Kantaka/Ashtama"))
    return out


def json_short(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)[:200]
