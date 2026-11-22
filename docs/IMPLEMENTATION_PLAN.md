# Jyotish AI — Implementation Plan (simplification)

Branch: `simplify` (baseline: `pre-simplify` = `main` at `e16115fe`). Nothing pushed.
Last updated: 2026-11-22.

## 1. Goal
Replace the layered prediction stack (4 pillars + convergence v2 + 61 intents + KP + gates) with **one transparent classical Parashari method** that is checked against the user's own past events and shown as **one short answer card**.

Honest framing: controlled studies have not found astrology predictive. The aim is consistency, traceability and *measured* — not claimed — accuracy. No percentages are shown to users until outcome data supports them.

## 2. Decisions (user, 2026-11-22)
| # | Decision |
|---|---|
| 1 | Save baseline branch `pre-simplify` — yes (it equals `main`; nothing was uncommitted) |
| 2 | ~12 topics — yes |
| 3 | Core engine becomes the **default** after the chat uses it |
| 4 | Convergence engine v2 stays **switched off** (not finished) |
| 5 | Phase 0 (collect wrong predictions) — skipped; regression set built from reference charts instead |

## 3. Target workflow (per question)
1. **Safety screen** (distress, death/longevity, pregnancy, gambling, minors).
2. **Understand** (router call): topic, tense (past / future / natal), period, statement vs question, understood or not.
3. **Core method** `core.answer()`:
   - **Promise** — topic house, lord, karaka from Lagna and Moon; strength, functional role, active yogas, varga only if reliable → strong / moderate / weak.
   - **Period** — MD/AD/PD lords linked to the topic houses.
   - **Trigger** — Saturn **and** Jupiter both on the house or its lord.
   - Weak promise → "not indicated", no timing.
4. **Answer card**: Answer · When · Why (≤2 plain reasons with fact IDs) · Confidence · What you can do.
5. **AI phrases the card only** (≤100 words); consistency check rejects any window/verdict that differs from the card; fallback to deterministic text.
6. **Save** the prediction pre-registered (rule IDs, hash); outcome collected later → backtest.

## 4. Phases and status
| Phase | Scope | Status |
|---|---|---|
| 0 | Baseline branch + plan committed | **Done** (`pre-simplify`, `simplify`, commit `1b825788`) |
| 1 | Core engine: `astro/core.py`, `data/topics.json`, `data/rulepack/core_method.json`, `/api/core/*`, `/api/home` | **Done** (763 tests pass) |
| 4 | Flags: `ENGINE=core`, `CONVERGENCE_V2=off`, `KP_ENABLED=off`, `ADVANCED_SCREENS=on` | **Done** |
| 5 | Simpler screens: Home, AnswerCard component, single nav (Home · Chat · Matching · Muhurta · My predictions + Advanced), en/hi strings | **Done** (tsc/eslint clean; not browser-tested) |
| 1b | Tune core to be selective (firing-rate targets, narrower windows, stricter double transit) → `docs/CORE_ENGINE_TUNING.md` | **In progress** |
| 3 | Answer card in chat; AI phrases card only; consistency check; remove n/4 badges/tables from default; on-demand "Second opinion" | **In progress** |
| 2 | One chart check: user's dated events run backward → fit good / partial / poor; propose better birth time on poor fit (confirm first) | **In progress** (with Phase 3) |
| 6 | Measure: pre-registered core predictions, outcomes page, backtest vs base rate and shuffled control; compare core vs old pillars | Ongoing after release |

## 5. Phase details

### Phase 1 / 1b — Core engine
- Files: `backend/app/astro/core.py`, `backend/data/topics.json`, `backend/data/rulepack/core_method.json`.
- Topics: career, job_change, promotion, business, wealth, marriage, relationship, children, education, foreign, property, wellbeing (theme only).
- Public API: `promise`, `periods`, `triggers`, `answer`, `year_overview`, `dasha_brief`, `card_text`, `topics_list`.
- Card: verdict (likely / mixed / not_indicated; natal: strong / moderate / weak), window, confidence (high / medium / low), why, action, rule IDs, details.
- Tuning targets (firing rates, **not** accuracy): strong promise ≈ ≤25–30% of topic×chart pairs; weak ≥ 25%; "likely" ≤ ~20% of random 12-month windows; "likely" windows ≤ ~4 months; "high" confidence only when promise, link, trigger and a reliable varga all agree.
- Known issue found: first version graded 8/12 topics "strong" on the reference chart; thresholds were my choices, not classical numbers.

### Phase 3 — Chat
- Router topic/event → one of the 12 core topics (unmapped → existing LLM-first path).
- `meta.card` stored with each answer; frontend renders `AnswerCard` with "Why?" and "Second opinion".
- Card consistency check → regenerate once → `card_text()` fallback.
- Past tense: core scans backward (default 15 years) + existing retrospective bundle; one short confirming question only if no event stated.
- `ENGINE=pillars` keeps the old behaviour for tests/comparison.

### Phase 2 — Chart check
- `calibration.chart_check(facts, birth, events)`; events mapped to core topics; explained = promise + period link + double transit within ±6 months (period link alone = partially explained).
- Stores `personal_fit` on the profile (new migration after current head); feeds card confidence and Home "chart check" state.
- Poor fit → nearby birth-time search; apply only after the user confirms; otherwise confidence capped medium/low and the user is told plainly.
- Generated yes/no questions only when the user gives no events.

### Phase 6 — Measurement
- Existing: pre-registration (`astro/preregistration.py`), predictions page, admin backtest (`astro/backtest.py`, `scripts/rule_backtest.py`).
- Add core rule IDs to registrations; compare core vs pillars on the regression set and real outcomes **before** deleting anything.
- Rule weights stay off (`USE_BACKTEST_WEIGHTS=False`) until data is sufficient (≥30 outcomes per rule).

## 6. Parked (switched off, not deleted)
Convergence v2 and the 61 intent files, KP, specificity gate, old pillars (kept as `ENGINE=pillars`), paused timing-engine agent work. Delete only after 4–6 weeks of outcome data **and your approval**.

## 7. Test and release checks
- `cd backend && JYOTISH_JWT_SECRET=<32+ chars> .venv/bin/python -m pytest tests -q` (shared test DB: do not run two suites at once).
- `cd frontend && npx tsc --noEmit && npx eslint src`.
- Manual checks on the real app: graduation-stream question (no period prompt), "I did mechanical engineering in 2006" (no time-frame question), "when did I switch career" (past look-back), unknown-time profile (Moon mode), Home screen, card rendering, Hindi.
- Before release: restart backend, rebuild frontend, confirm you are not on a stale deployment.

## 8. Risks
- Old tests assert the old flow → kept valid behind `ENGINE=pillars`.
- The AI may add content → card-only prompt + consistency check.
- Accuracy may not visibly improve → Phase 6 measures it instead of assuming.
- Thresholds are firing-rate tuning, not validated rules.
- Hindi is partial (card reasons stay English); about 30 rules are marked `verified: False` and kept out of what the AI states as fact.

## 9. Open items
- Review `docs/CORE_ENGINE_TUNING.md` once tuning finishes.
- Decide when to merge `simplify` into `main` and whether to push (nothing pushed yet).
- Privacy page operator values (`NEXT_PUBLIC_LEGAL_NAME`, `NEXT_PUBLIC_GRIEVANCE_OFFICER`, `NEXT_PUBLIC_HOSTING_REGION`, `NEXT_PUBLIC_RETENTION_PERIOD`) still need to be set.
