# Jyotish AI — a human-like Vedic astrologer

A conversational Vedic astrology app — **not** a chart dashboard. You sign in, enter birth details, and talk to an astrologer who first verifies its timing method against **three past-life periods** from your own history before it says anything about your future.

## What it does

- **Calibration first**: the backend generates three dated life-domain windows (career, education, relocation, …) from your chart, asks you one at a time, and records confirmed / partial / rejected. 3 confirmations → calibrated; 2 → partial (reads with a caution flag); 0–1 → the app **auto-rectifies**: it scores nearby birth times (±30–120 min by stated precision) against your feedback, adopts a clearly better fit, and re-asks — otherwise predictions stay locked, even against prompt injection.
- **Locked chart facts**: PyJHora + Swiss Ephemeris compute everything (signs, degrees, nakshatras, dignity, combustion, retrograde, gandanta, house lords, yogakaraka/maraka/badhaka, Vimshottari, Jaimini 7-karakas + arudhas + Chara dasha, divisional charts D1/D2/D7/D9/D10/D24/D60…, Sarvashtakavarga, Binnashtakavarga, Shadbala, Bhava Chalit, Muntha). The LLM receives these as authoritative facts and is forbidden from computing or stating degrees — enforced by a deterministic verifier on every reply.
- **Four-pillar convergence** for forward-looking questions: Parashari (dasha lordship + varga dignity + bhava-chalit + Shadbala strength), Jaimini (Chara dasha + rashi drishti vs karaka and domain arudhas), Tajika (Muntha house + Muntha-lord dignity), and micro-timing (Jupiter–Saturn double transit, Sun/Mars fast transits, SAV/BAV bindus, nakshatra sub-period lord). Each window is badged `N/4 Confirmed` or `N/4 Conditional` — support / conflict counts only, never numerical probabilities. A `health` domain exists (houses 1/6/8/12, D30, Gnatikaraka) and always appends a not-medical-diagnosis disclaimer.
- **Chat-first UI**: plain conversation, quick-reply buttons for calibration, inline North-Indian chart cards on request, "why do you say that?" reveals the pillar evidence. Light/dark theme, mobile-friendly.

## Stack

- **Backend** `backend/`: FastAPI, SQLAlchemy (SQLite default, Postgres via env), JWT auth, PyJHora 5 + pyswisseph, offline geocoding (bundled ~68k-city database + timezonefinder).
- **Frontend** `frontend/`: Next.js 16 (App Router), Tailwind 4, React 19.
- **LLM providers** (`JYOTISH_LLM_PROVIDER`):
  - `offline` — built-in deterministic responder from locked facts; zero keys, zero cost.
  - `gemini` — Gemini API free tier. Requires `GEMINI_API_KEY` and `JYOTISH_LLM_EXTERNAL_CONSENT=true`. External AI replies are included in the required service terms accepted at signup; existing accounts accept the updated terms once before chatting.
  - `groq` — Groq OpenAI-compatible API. Requires `GROQ_API_KEY` and the same external-consent flag; also used automatically as a fallback when configured and available.
  - `openrouter` — OpenRouter API, restricted to free models (`openrouter/free` or any `:free` model id). Requires `OPENROUTER_API_KEY` and server-level external processing enabled; used as a later fallback when configured.
  - `ollama` / `lmstudio` — local servers (`JYOTISH_OLLAMA_URL`, `JYOTISH_LMSTUDIO_URL`).

## Run it

```bash
# backend (Python 3.10+)
cd backend && pip install -r requirements.txt
export JYOTISH_DEV_INSECURE_JWT=true   # or set JYOTISH_JWT_SECRET (>= 32 bytes) in backend/.env
uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (Node 20+)
cd frontend && npm install && npm run build && npm run start -- --port 3000
```

Open http://localhost:3000 — create an account, enter birth details (place autocomplete is offline), chat.

### Environment

| Var | Default | Purpose |
|---|---|---|
| `JYOTISH_DATABASE_URL` | sqlite at `backend/jyotish.db` | swap to `postgresql+psycopg2://…` for Postgres |
| `JYOTISH_JWT_SECRET` | — (required) | random value, at least 32 bytes; the app refuses to start without it |
| `JYOTISH_DEV_INSECURE_JWT` | `false` | local dev only: `true` uses a random per-process secret when `JYOTISH_JWT_SECRET` is missing; ignored when `JYOTISH_ENV=prod` |
| `JYOTISH_LLM_PROVIDER` | `offline` | `offline` \| `gemini` \| `groq` \| `openrouter` \| `ollama` \| `lmstudio` |
| `GEMINI_API_KEY` | — | free key from ai.google.dev |
| `JYOTISH_GEMINI_MODEL` | `gemini-3.5-flash` | note: 2.0/2.5 flash are retired for new API users |
| `GROQ_API_KEY` | — | optional Groq key; enables fallback when external consent is on |
| `JYOTISH_GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id |
| `OPENROUTER_API_KEY` | — | optional OpenRouter key; free models only |
| `JYOTISH_OPENROUTER_MODEL` | `openrouter/free` | must be `openrouter/free` or end with `:free` |
| `JYOTISH_LLM_EXTERNAL_CONSENT` | `false` | must be `true` before any external LLM call |
| `JYOTISH_LLM_TURN_DEADLINE` | `30` | max seconds a chat turn spends on LLM calls (all providers/retries) before the offline reply |
| `JYOTISH_LLM_MAX_CONCURRENCY` | `4` | max chat turns calling an LLM at once; extra turns get the offline reply |

## Tests

```bash
cd backend && python3 -m pytest tests/ -q
```

17 tests: engine determinism + reference positions, locked-facts shape, birth-time sensitivity, Vimshottari span, verifier (wrong-sign, probabilities, degree injection), full calibration → gate opens, gate blocks predictions pre-calibration, failed calibration locks predictions + survives a prompt-injection attempt + triggers rectification search, unauthenticated rejection, API no-store headers, health-domain disclaimer, pillar gap features.

See `docs/CALCULATION_VALIDATION.md` for calculation choices and caveats, and `docs/LICENSING.md` for the AGPL/GPL licensing situation before you deploy this anywhere public.

## Known limitations (honest list)

- Tajika pillar is a simplified Muntha progression + Muntha-lord dignity (no full Varshaphala chart / sahams / Tajika yogas).
- Jaimini: 7-karaka scheme + arudhas + Chara dasha sign aspects; no pada-specific dashas, no Narayana dasha variants.
- KP pillar is approximated by transit + SAV/BAV + nakshatra sub-period micro-timing (no cuspal sub-lords).
- Birth-time rectification is bounded search (±30–120 min, ~5 candidates) — a conservative hint, not full event-archive rectification.
- Retrograde-aware varga counting, ayanamsa choice (Lahiri), and mean nodes are the recorded fingerprint choices — see CALCULATION_VALIDATION.md.

## Deploy (Render free tier)

The app ships as **one service**: `frontend/` builds to a static export committed at `frontend/out/`, and FastAPI serves it at `/` plus the API at `/api/*`. `render.yaml` is included.

- Build: `pip install -r backend/requirements.txt` · Start: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT` · Health: `/api/health`
- Set env vars on the service: `JYOTISH_LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, optional `GROQ_API_KEY` / `OPENROUTER_API_KEY` fallbacks, `JYOTISH_LLM_EXTERNAL_CONSENT=true`, `JYOTISH_JWT_SECRET`, and optionally `JYOTISH_DATABASE_URL`.
- **Free-tier caveats**: sleeps after ~15 min idle (~30s cold start); without `JYOTISH_DATABASE_URL` the SQLite file lives on ephemeral disk — **accounts reset on every redeploy**. Point `JYOTISH_DATABASE_URL` at a free Postgres (e.g. Neon: `postgresql+psycopg2://…`) to make accounts permanent.
- After editing the frontend, rebuild the export (`npm run build`) and force-add it (`git add -f frontend/out`) — the directory is git-ignored; auto-deploy pulls from `main`.
- Rectification flow is a placeholder (asks for better birth data; does not run a full rectification algorithm).
- Google sign-in not implemented (email/password only).
- Gemini free tier can return transient 503s; the app retries, then falls back to Groq and OpenRouter free models when their keys are set, and finally to the offline responder.

### AI replies and service terms

Signup has one required agreement linking `/terms` and `/privacy` and explaining that chart summaries and recent messages are processed by Gemini, Groq or OpenRouter. There is no separate AI checkbox or chat-menu toggle. The API requires `terms_accepted: true` at registration and records the terms version and acceptance timestamp. Existing accounts must accept the current terms once via `POST /api/auth/terms` before sending chat messages. Migration 0008 leaves their historical consent records unchanged and does not fabricate acceptance. Account exports include the acceptance record. The server-level `JYOTISH_LLM_EXTERNAL_CONSENT` switch and provider credentials still control provider availability.
