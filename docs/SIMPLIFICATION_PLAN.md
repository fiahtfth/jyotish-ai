# Simplification plan: one clear method, one answer card

Goal: replace the layered engine with one transparent classical method (promise → period → trigger), validated against the user's own past events, presented as a short answer card. No Jyotish method has been shown to predict reliably in controlled studies; the aim is consistency, traceability and measured (not claimed) accuracy.

Decisions (user, 2026-11-22): baseline branch `pre-simplify` = yes; ~12 topics = yes; core engine becomes the default after Phase 3 = yes; convergence engine v2 stays switched off; Phase 0 wrong-prediction examples skipped.

Phase 1 — Core engine `backend/app/astro/core.py` + `backend/data/topics.json` (~12 topics: career, job change, promotion, business, income/wealth, marriage, relationship, children, education, foreign/relocation, property, wellbeing-theme). Steps: Promise (topic house, lord, karaka from Lagna & Moon; strength, functional role, active yogas → strong/moderate/weak + 2 reasons); Period (MD/AD/PD lords linked to topic houses); Trigger (Saturn + Jupiter double transit on house or lord). Card: verdict likely/mixed/not indicated, narrowest window, confidence high/medium/low, ≤2 plain reasons, one action line, rule IDs. Weak promise → no timing. Past questions run backward. Unknown time → Moon as Lagna, confidence capped low.
Phase 2 — One chart check: user's 3–5 dated events → core engine backward → personal fit good/partial/poor → if poor test nearby birth times and propose correction; generated yes/no questions only if no events.
Phase 3 — Answer card in chat: core.answer() → card → AI phrases card only → verifier → card shown (Answer · When · Why · Confidence · What you can do); 'Second opinion' on request; n/4 badges and tables removed from default chat.
Phase 4 — Flags: ENGINE=core (default after Phase 3), CONVERGENCE_V2=off, KP_ENABLED=off; old pillars kept for comparison; delete only after outcome data + approval.
Phase 5 — Simpler screens: Home (chart in brief, current dasha in plain words, this year's top 3 topics, chart-check status, suggested questions); nav Home · Chat · Matching · Muhurta · My predictions; Advanced holds tables/Varshaphala/Prashna/KP.
Phase 6 — Measure: core predictions pre-registered; outcomes collected; backtest vs base rate and shuffled control; compare core vs old engine before deleting anything.
