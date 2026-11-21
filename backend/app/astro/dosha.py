"""Mangal (Kuja) dosha with references and individually listed cancellations.

`mangal_dosha(facts, partner_facts=None, age=None)` is a pure function over
locked chart facts (P3's matching module calls it; keep the signature stable).

Rule IDs
- MD.REF.LAGNA / MD.REF.MOON / MD.REF.VENUS: Mars in the 1st, 2nd, 4th, 7th,
  8th or 12th counted from that reference.
- MD.GRADE: app convention — one reference = mild, two or more = strong.
- MD.CX.*: cancellations (see CANCELLATION_RULES). Every entry carries a
  `source` and `verified` flag. Only verified cancellations change `net`;
  unverified ones are listed and summarised in `net_including_unverified`
  and must not be shown to the language model.
- MD.NOTE.AGE_28: a belief that the dosha weakens after 28 — labelled as a
  belief, never applied as a rule.

Classical status: the dosha houses and the general cancellations are
traditional matching practice reproduced in popular compilations; the
verse-level wording has not been checked against a printed edition, so
sources name the tradition rather than a verse.
"""
from __future__ import annotations

from . import constants as K

DOSHA_HOUSES = (1, 2, 4, 7, 8, 12)
REFERENCES = ("Lagna", "Moon", "Venus")
MARS = 2
JUPITER = 4

SRC_TRAD = "Traditional Kuja-dosha matching practice (popular compilations; verse wording not verified)"

# Sign-specific exceptions as commonly listed: (house from reference, signs).
# 1st in Leo/Aquarius is included because it is printed in the same list.
SIGN_EXCEPTIONS = {
    1: (4, 10),       # Leo, Aquarius
    2: (2, 5),        # Gemini, Virgo
    4: (0, 7),        # Aries, Scorpio
    7: (9, 3),        # Capricorn, Cancer
    8: (8, 11),       # Sagittarius, Pisces
    12: (1, 6),       # Taurus, Libra
}

CANCELLATION_RULES = {
    "MD.CX.OWN_OR_EXALTED": {"source": SRC_TRAD, "verified": True, "effect": "full",
                             "text": "Mars is in its own sign or exaltation."},
    "MD.CX.JUPITER_CONJUNCT": {"source": SRC_TRAD, "verified": True, "effect": "full",
                               "text": "Jupiter is together with Mars."},
    "MD.CX.JUPITER_ASPECT": {"source": SRC_TRAD + "; Jupiter's 5/7/9 drishti per BPHS ch.26",
                             "verified": True, "effect": "partial",
                             "text": "Jupiter's aspect falls on Mars."},
    "MD.CX.PARTNER_SIMILAR": {"source": SRC_TRAD, "verified": True, "effect": "full",
                              "text": "The partner's chart carries a comparable Mars placement."},
    "MD.CX.SIGN_EXCEPTION": {"source": SRC_TRAD + " (sign-specific exception list)",
                             "verified": False, "effect": "full",
                             "text": "Mars sits in a sign listed as an exception for this house."},
}

WORDING = {
    "absent": ("mangal_dosha.absent",
               "Mars is not in the houses traditionally linked with Mangal dosha."),
    "cancelled": ("mangal_dosha.cancelled",
                  "Mars touches a traditional Mangal dosha house, but classical cancellations apply, "
                  "so it is not treated as a concern."),
    "mild": ("mangal_dosha.mild",
             "A mild, traditional Mars emphasis on partnership houses — a matching consideration, "
             "not a verdict on any relationship."),
    "present": ("mangal_dosha.present",
                "Mars sits in traditional Mangal dosha houses from more than one reference — "
                "something traditional matching looks at alongside the partner's chart; "
                "it does not decide any relationship's outcome."),
}


def _sign(facts, name):
    return int(facts["planets"][name]["sign"])


def _ref_sign(facts, ref):
    if ref == "Lagna":
        return int(facts["lagna"]["sign"])
    return _sign(facts, ref)


def _present_from(facts, references=REFERENCES) -> list[dict]:
    mars = _sign(facts, "Mars")
    out = []
    for ref in references:
        try:
            h = K.house_from(mars, _ref_sign(facts, ref))
        except (KeyError, TypeError):
            continue
        if h in DOSHA_HOUSES:
            out.append({"reference": ref, "house": h, "rule": f"MD.REF.{ref.upper()}"})
    return out


def _grade(present: list) -> str:
    if not present:
        return "none"
    return "strong" if len(present) >= 2 else "mild"


def _cx(rule_id, **detail):
    r = CANCELLATION_RULES[rule_id]
    return {"id": rule_id, "source": r["source"], "verified": r["verified"],
            "effect": r["effect"], "text": r["text"], **detail}


def _cancellations(facts, present, partner_facts) -> list[dict]:
    out = []
    p = facts["planets"]
    mars_sign = _sign(facts, "Mars")
    if mars_sign in K.OWN_SIGNS[MARS] or mars_sign == K.EXALTATION[MARS][0]:
        out.append(_cx("MD.CX.OWN_OR_EXALTED", sign=K.SIGN_NAMES[mars_sign]))
    jup = p.get("Jupiter")
    if jup is not None:
        if int(jup["sign"]) == mars_sign:
            out.append(_cx("MD.CX.JUPITER_CONJUNCT"))
        elif mars_sign in K.parashari_reaches("Jupiter", int(jup["sign"])):
            out.append(_cx("MD.CX.JUPITER_ASPECT",
                           aspect_house=K.house_from(mars_sign, int(jup["sign"]))))
    for row in present:
        signs = SIGN_EXCEPTIONS.get(row["house"], ())
        if mars_sign in signs:
            out.append(_cx("MD.CX.SIGN_EXCEPTION", reference=row["reference"], house=row["house"],
                           sign=K.SIGN_NAMES[mars_sign],
                           rule=f"MD.CX.SIGN_H{row['house']}_{K.SIGN_NAMES[mars_sign].upper()}"))
    if partner_facts is not None:
        try:
            partner_present = _present_from(partner_facts)
        except (KeyError, TypeError):
            partner_present = []
        if partner_present:
            out.append(_cx("MD.CX.PARTNER_SIMILAR",
                           partner_present_from=[r["reference"] for r in partner_present]))
    return out


def _net(strength: str, cancellations: list) -> str:
    if strength == "none":
        return "absent"
    if any(c["effect"] == "full" for c in cancellations):
        return "cancelled"
    if any(c["effect"] == "partial" for c in cancellations):
        return "mild"
    return "present" if strength == "strong" else "mild"


def mangal_dosha(facts: dict, partner_facts: dict | None = None, age: float | None = None,
                 references: tuple = REFERENCES) -> dict:
    """Kuja dosha from Lagna, Moon and Venus.

    Returns {present_from: [{reference, house, rule}], strength: none|mild|strong,
    cancellations: [{id, source, verified, effect, text, ...}],
    net: absent|cancelled|mild|present (verified cancellations only),
    net_including_unverified, notes, wording_key, wording, references, rules}.
    `partner_facts` (another chart's facts) enables MD.CX.PARTNER_SIMILAR;
    `age` only annotates the age-28 belief note. `references` can drop "Lagna"
    when the birth time is unknown.
    """
    present = _present_from(facts, references)
    strength = _grade(present)
    cx = _cancellations(facts, present, partner_facts) if present else []
    verified = [c for c in cx if c["verified"]]
    net = _net(strength, verified)
    net_all = _net(strength, cx)
    notes = []
    if present:
        notes.append({"id": "MD.NOTE.AGE_28", "kind": "belief", "verified": False,
                      "source": "Folk belief in matching practice",
                      "text": "Some traditions hold that the Mars influence softens after about age 28; "
                              "this is a belief, not a classical rule, and is not applied.",
                      **({"age_over_28": age >= 28} if age is not None else {})})
    key, text = WORDING[net]
    return {"present_from": present, "strength": strength, "cancellations": cx,
            "net": net, "net_including_unverified": net_all, "notes": notes,
            "wording_key": key, "wording": text,
            "mars": {"sign": K.SIGN_NAMES[_sign(facts, "Mars")],
                     "house_from_lagna": K.house_from(_sign(facts, "Mars"), facts["lagna"]["sign"])},
            "references": list(references), "houses_checked": list(DOSHA_HOUSES),
            "rules": {"MD.GRADE": "app convention: 1 reference = mild, 2+ = strong",
                      "net": "only verified cancellations change `net`"}}


def legacy_summary(result: dict) -> dict:
    """The original report keys {present, house_from_lagna, also_from_moon}."""
    refs = {r["reference"] for r in result["present_from"]}
    return {"present": "Lagna" in refs, "house_from_lagna": result["mars"]["house_from_lagna"],
            "also_from_moon": "Moon" in refs}
