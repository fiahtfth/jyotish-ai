# Jyotish AI — a human-like Vedic astrologer

A conversational Vedic astrology app — **not** a chart dashboard. You sign in, enter birth details, and talk to an astrologer who first verifies its timing method against **three past-life periods** from your own history before it says anything about your future.

## What it does

- **Calibration first**: the backend generates three dated life-domain windows (career, education, relocation, …) from your chart, asks you one at a time, and records confirmed / partial / rejected. 3 confirmations → calibrated; 2 → partial (reads with a caution flag); 0–1 → locked: the astrologer offers rectification and will **not** predict, even if you try prompt injection.
- **Locked chart facts**: PyJHora + Swiss Ephemeris compute everything (signs, degrees, nakshatras, dignity, combustion, retrograde, gandanta, house lords, yogakaraka/maraka/badhaka, Vimshottari, Jaimini 7-karakas + arudhas + Chara dasha, divisional charts D1/D2/D7/D9/D10/D24/D60…, Sarvashtakavarga, Muntha). The LLM receives these as authoritative facts and is forbidden from computing or stating degrees — enforced by a deterministic verifier on every reply.
- **Four-pillar convergence** for forward-looking questions: Parashari (dasha + varga), Jaimini (Chara dasha + rashi drishti + karakas), Tajika (Muntha), and transit micro-timing (Jupiter/Saturn + SAV bindus). Verdicts are support / conflict / neutral / unavailable — never numerical probabilities.
- **Chat-first UI**: plain conversation, quick-reply buttons for calibration, inline North-Indian chart cards on request, "why do you say that?" reveals the pillar evidence. Light/dark theme, mobile-friendly.

## Stack

- **Backend** `backend/`: FastAPI, SQLAlchemy (SQLite default, Postgres via env), JWT auth, PyJHora 5 + pyswisseph, offline geocoding (bundled ~68k-city database + timezonefinder).
- **Frontend** `frontend/`: Next.js 16 (App Router), Tailwind 4, React 19.
- **LLM providers** (`JYOTISH_LLM_PROVIDER`):
  - `offline` — built-in deterministic responder from locked facts; zero keys, zero cost.
  - `gemini` — Gemini API free tier. Requires `GEMINI_API_KEY` and `JYOTISH_LLM_EXTERNAL_CONSENT=true` (explicit opt-in before any data leaves the machine).
  - `ollama` / `lmstudio` — local servers (`JYOTISH_OLLAMA_URL`, `JYOTISH_LMSTUDIO_URL`).

## Run it

```bash
# backend (Python 3.10+)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (Node 20+)
cd frontend && npm install && npm run build && npm run start -- --port 3000
```

Open http://localhost:3000 — create an account, enter birth details (place autocomplete is offline), chat.

### Environment

| Var | Default | Purpose |
|---|---|---|
| `JYOTISH_DATABASE_URL` | sqlite at `backend/jyotish.db` | swap to `postgresql+psycopg2://…` for Postgres |
| `JYOTISH_JWT_SECRET` | dev default | **set in production** |
| `JYOTISH_LLM_PROVIDER` | `offline` | `offline` \| `gemini` \| `ollama` \| `lmstudio` |
| `GEMINI_API_KEY` | — | free key from ai.google.dev |
| `JYOTISH_GEMINI_MODEL` | `gemini-3.5-flash` | note: 2.0/2.5 flash are retired for new API users |
| `JYOTISH_LLM_EXTERNAL_CONSENT` | `false` | must be `true` before any external LLM call |

## Tests

```bash
cd backend && python3 -m pytest tests/ -q
```

13 tests: engine determinism + reference positions, locked-facts shape, birth-time sensitivity, Vimshottari span, verifier (wrong-sign, probabilities, degree injection), full calibration → gate opens, gate blocks predictions pre-calibration, failed calibration locks predictions + survives a prompt-injection attempt, unauthenticated rejection.

See `docs/CALCULATION_VALIDATION.md` for calculation choices and caveats, and `docs/LICENSING.md` for the AGPL/GPL licensing situation before you deploy this anywhere public.

## Known limitations (honest list)

- Tajika pillar is a simplified Muntha progression only (no full Varshaphala chart / sahams / Tajika yogas).
- Jaimini: 7-karaka scheme + arudhas + Chara dasha sign aspects; no pada-specific dashas, no Narayana dasha variants.
- KP pillar is approximated by transit + SAV micro-timing (no cuspal sub-lords).
- Retrograde-aware varga counting, ayanamsa choice (Lahiri), and mean nodes are the recorded fingerprint choices — see CALCULATION_VALIDATION.md.
- Rectification flow is a placeholder (asks for better birth data; does not run a full rectification algorithm).
- Google sign-in not implemented (email/password only).
- Gemini free tier can return transient 503s; the app retries then falls back to the offline responder.
