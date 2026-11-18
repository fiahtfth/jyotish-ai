# Calculation validation

Engine: **PyJHora 5.0.0** over **pyswisseph** (Swiss Ephemeris). All values below are locked into a per-chart `calc_fingerprint` (sha256 of settings + library versions) stored with each profile.

## Recorded settings

| Setting | Value | Why |
|---|---|---|
| Ayanamsa | **LAHIRI** | PyJHora defaults to TRUE_PUSHYA (~1.14° off Lahiri); Lahiri is the standard reference. |
| Nodes | **Mean** | PyJHora 5.0.0's TRUE_NODE path crashes pyswisseph (`swe.calc_ut` on negative jd). |
| Chara karakas | **7-karaka** (AK…DK, Rahu excluded) | PyJHora's `get_chara_karakas` returns the 8-karaka scheme; spec requires 7. Implemented directly by within-sign advancement. |
| Varga methods | PyJHora varga functions (Parashari counting), method=1 | D2/D4/D7/D9/D10/D12/D16/D20/D24/D40/D60. No trimshamsa function exists in 5.0.0. |
| Geocoding | bundled `geonames_places_5k.csv` (~68k cities) + timezonefinder/zoneinfo | fully offline; historical UTC offset computed from IANA tzdb. |

## Regression checks (automated, `backend/tests/`)

- **Reference positions** — 1990-05-15 06:15 IST, Chennai (Lahiri, mean nodes):
  Sun 0.22° Taurus (just ingressed sidereal Taurus on May 15), Moon 27.7° Sagittarius (Uttara Ashadha), Lagna Taurus 7.4°, Rahu Capricorn / Ketu Cancer (correct node axis for mid-1990), Saturn ~1.5° Capricorn (Saturn ingressed Capricorn Feb 1990). All assertions tolerate small deltas and pin sign + nakshatra.
- **Determinism**: same input → byte-identical planets JSON.
- **Sensitivity**: +20 min moves Lagna degree while Sun sign is stable — lagna boundaries are genuinely time-critical (this is why the calibration gate exists).
- **Vimshottari**: period list spans ~120 years end-to-end; every antardasha ordered.

## Reference check vs other software

Sun at sidereal Taurus ingress on 15-May-1990, Moon in Uttara Ashadha, Rahu in Capricorn (mean node) all agree with standard ephemerides (e.g., Drik Panchang / Jagannatha Hora for the same instant). Remaining divergence vs other apps should come from ayanamsa choice — Lahiri documented above; a ~24' difference vs apps defaulting to other ayanamsas is expected, not an error.

## Pillar caveats

- **Tajika**: Muntha progression only (`(lagna_sign - 1 + completed_years) % 12`), labeled "simplified" — a full Varshaphala (solar-return chart, sahams, Tajika yogas, Mudda dasha) is not implemented.
- **KP/micro-timing**: implemented as monthly Jupiter/Saturn transit-over-domain-house + SAV≥28 bindu strength + ashtama-Shani flag. No cuspal sub-lord KP.
- **Jaimini**: Chara dasha sign vs karaka sign / A10 / UL via rashi drishti (movable↔fixed, dual↔dual).
- The four pillars can each return `unavailable` — missing data is reported, never guessed.

## Verifier

Every LLM reply is checked before display: planet-in-sign, planet-in-house, running-dasha claims vs computed values; % probabilities banned; precise degree assertions banned (degrees are locked facts); classical citations rejected unless retrieved from a knowledge source. Offending sentences are stripped, else a fallback reply is substituted.

## Prediction protocol 2026-11-17.1

- Pillar counts describe **rule agreement**, not measured probabilities. Strong agreement requires at least three supports, no conflicting pillar and no unavailable core method.
- Solar-return years use PyJHora's one-based convention (`years=age+1`). Annual charts overlapping the requested interval are included even if their start precedes it. Seven classical-planet year-lord candidates are evaluated at the actual return, avoiding PyJHora 5's node/index bugs. This repairs the additional annual-trigger filter; the core Tajika pillar remains explicitly simplified Muntha progression.
- Confirmation, contributor-level timing, eclipses and annual triggers report calculation failures as unavailable/partial. No result is not equivalent to successful calculation with no indication.
- Sensitivity checks sample exact time at ±2 minutes, approximate time at ±30/60 minutes, and unknown time at ±60/120 minutes. These are disclosed assumed ranges, not inferred error distributions. Every sample retains its core verdict and timing intervals. Changed/unavailable samples cause abstention; unstable narrow windows are withheld. Finite sampling cannot establish the correct birth time.
- AI analysis JSON is transmitted whole. Event forecasts are buffered until verification; the final server-authored decision remains authoritative. An abstention cannot be replaced by an AI event promise.
- Each domain analysis records a frozen versioned snapshot, explicit event definition (when supported), criteria, requested future interval, decisions and final response. Broad outlooks are interpretations and recorded as abstentions. Historical records remain legacy; they are not retroactively assigned predictions.
- The scorecard excludes legacy and same-day/retrospective issuance from prospective accuracy counts, and evaluates only closed intervals. Partial, uncertain and missing outcomes never count as hits. Out-of-window events are misses. Outcomes are self-reported; event dates entered in the scorecard are checked and retained.
- Coverage and abstention counts remain visible. Accuracy is not claimed from software tests or three retrospective checks.

### Validation workflow

`backend/scripts/evaluate_predictions.py` accepts an account export or array of prediction records. Select a time cutoff and explicitly held-out profile IDs. Development outcomes must be available before the cutoff and cannot belong to held-out people. Test forecasts must be issued after the cutoff, before the target interval, for held-out people. The report compares the engine with a majority-event baseline learned only from development records of the same domain **and event type**. Missing baseline data is reported, not invented.

```sh
backend/.venv/bin/python backend/scripts/evaluate_predictions.py private-export.json \
  --cutoff 2027-01-01 --holdout-profiles 12 18
```

Do not commit private exports. Synthetic regression fixtures verify evaluation behavior; they are not evidence of prediction accuracy. A real prospective cohort with event-negative observations, complete follow-up, adequate sample size and uncertainty estimates is still required. Future rule changes need a new untouched holdout; fitting weights to this test set is not permitted.

Repeated forecasts for the same profile, event definition and interval are scored once (the earliest record). The API also returns a Wilson interval around the observed hit rate; it describes uncertainty in the self-reported scored subset and does not correct selection bias or prove predictive validity.
