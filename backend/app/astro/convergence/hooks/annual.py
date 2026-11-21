"""#56 ANNUAL_THEMES: rank life domains by de-duplicated n over the next solar-return year.

Each domain runs template T with a representative timing intent; the domain score is the best
n among its windows (ties: longer supportive span). Top 3 themes + 1 caution theme (most
adverse/mixed coverage) + month markers and major slow-planet sign changes."""
from __future__ import annotations

from datetime import date, timedelta

from ... import constants as K
from ... import precision, transits
from .. import _ivl, intents, rulepack
from ..types import A, M

R = "HOOK_ANNUAL_RANK"
DOMAINS = {"career": "JOB_TIMING", "relationships": "MARRIAGE_TIMING", "finance": "INCOME_IMPROVEMENT",
           "education": "COMPETITIVE_EXAMS", "foreign_travel": "FOREIGN_TRAVEL", "property": "PROPERTY_PURCHASE"}


def year_range(birth, today=None) -> tuple:
    today = _ivl.to_date(today) if today else date.today()
    cy = precision.completed_solar_years(birth, today)
    a = precision.solar_return_date(birth, cy)
    b = precision.solar_return_date(birth, cy + 1) - timedelta(days=1)
    return a, b


def domain_summary(out) -> dict:
    best_n, sup_days, caution_days, months = 0, 0, 0, []
    for w in out.windows:
        r = w.result
        days = (w.segment[1] - w.segment[0]).days + 1
        best_n = max(best_n, r.n)
        if r.result_type == "supportive_period":
            sup_days += days
            if r.interval:
                months.append(r.interval[0].strftime("%Y-%m"))
        if any(p.value in (A, M) for p in r.pillars):
            caution_days += days * sum(p.value == A for p in r.pillars) + days * 0.5 * sum(p.value == M for p in r.pillars)
    return {"best_n": best_n, "supportive_days": sup_days, "caution_score": round(caution_days, 1),
            "month_markers": sorted(set(months))}


def rank_domains(summaries: dict) -> dict:
    """Pure: {domain: domain_summary} -> top 3 + caution."""
    order = sorted(summaries, key=lambda d: (-summaries[d]["best_n"], -summaries[d]["supportive_days"], d))
    top = order[:3]
    caution = max(summaries, key=lambda d: (summaries[d]["caution_score"], d)) if summaries else None
    return {"ranking": order, "top_themes": top, "caution_theme": caution}


def major_transits(birth, a, b) -> list:
    out = []
    for pl in ("Jupiter", "Saturn", "Rahu"):
        for sign, s, _ in transits.sign_intervals(birth, pl, a, b)[1:]:
            out.append({"planet": pl, "enters": K.SIGN_NAMES[sign], "date": s.isoformat()})
    return sorted(out, key=lambda x: x["date"])


def annual_themes(facts: dict, birth, today=None, runner=None) -> dict:
    from ..template_t import template_T
    runner = runner or template_T
    a, b = year_range(birth, today)
    summaries, outs = {}, {}
    for dom, iid in DOMAINS.items():
        out = runner(facts, birth, intents.get(iid), a, b)
        outs[dom] = out
        summaries[dom] = domain_summary(out)
    res = rank_domains(summaries)
    try:
        moves = major_transits(birth, a, b)
    except Exception as exc:
        moves = [{"error": str(exc)}]
    return {"year": [a.isoformat(), b.isoformat()], **res, "domains": summaries, "major_transits": moves,
            "rule_id": R, "rule_version": rulepack.version(R),
            "note": "Domains ranked by the count of independent traditional methods agreeing (n/4), not probability."}
