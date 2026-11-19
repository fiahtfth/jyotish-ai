# Verification report

| Check | Result |
| --- | --- |
| Full backend pytest suite | 437 passed. The suite covered the existing chat flows, native varga boundaries, migration of existing default profiles, evidence metadata, transit re-entries, the isolated KP frame, and consent controls. |
| Frontend build and standalone TypeScript check | Passed. Next.js exported the dashboard and coverage pages for the FastAPI static host. |
| Frontend ESLint | Zero errors and two navigation warnings in `frontend/src/lib/api.ts`. |
| Chromium Playwright suite | 13 passed against a local FastAPI server and an isolated SQLite database. The browser smoke exercised the chart, timeline, sensitivity, Ashtakavarga, transits, KP, pasted degrees, and coverage views. No uncaught page exceptions were captured in that smoke flow. |
| Ruff | The new standalone calculation, registry, safety, and evaluation modules passed their focused check. Repository-wide lint still reports violations. |
| Strict mypy | The focused varga, Vimshottari and chat-safety checks passed. The repository-wide strict check still reports type errors. |
| Specificity | 1,000 seeded synthetic windows per event rule across ten rules. Results and unavailable counts are in [specificity_results.json](../backend/data/specificity_results.json). |

The external golden corpus and held-out outcome dataset were unavailable for this run. See [coverage](COVERAGE.md) for implementation status and [calculation validation](CALCULATION_VALIDATION.md) for the documented conventions.
