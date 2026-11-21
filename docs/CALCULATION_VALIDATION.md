# Calculation validation

The app uses Swiss Ephemeris directly for natal placements and uses its own whole-sign varga and fixed-year Vimshottari calculations. PyJHora 5.0.0 remains in use for the other modules documented below. Settings and engine versions contribute to a calculation fingerprint stored with each chart.

## Recorded settings

Every setting lives in `backend/app/astro/settings.py` (`CalcSettings`, frozen, validated) and is folded into the calc fingerprint and the chart cache key. Defaults reproduce the historical behaviour. `facts["meta"]` discloses the frame actually used (ayanamsa id/degrees/DMS, ephemeris, node, positions, centre, dasha-year mode/days, warnings).

| Setting | Default | Options / notes |
|---|---|---|
| `ayanamsa` | **LAHIRI** (Swiss Ephemeris) | LAHIRI_ICRC, LAHIRI_1940, LAHIRI_VP285, TRUE_CITRA. PyJHora's own default is TRUE_PUSHYA (~1.14 deg off Lahiri), so we always set one explicitly. Variants differ from SE Lahiri by about -1.1", -53", +23" (2022). |
| `node` | **mean** | `true` is allowed only if a smoke test of PyJHora's true-node mode (Rahu equals `swe.TRUE_NODE`) passes; otherwise `ValueError`. `facts["node_check"]` compares mean vs true Rahu (D1 and D9 sign) so a chart sensitive to the choice is flagged. |
| `positions` | **true** (geometric, `FLG_TRUEPOS`) | `apparent` clears the flag (adds aberration/deflection). |
| `center` | **geocentric** | `topocentric` sets `swe.FLG_TOPOCTR` and the observer location; Moon moves up to ~1° (parallax), Sun <8". PyJHora exposes it via `PLANET_POSITIONS_GEOCENTRIC=False` — patched into the module's private globals (see note on `drik` patching below). |
| `dasha_year` | **julian**, 365.25 days | Existing profiles using the previous default retain `legacy_tropical`. Fixed alternatives include Gregorian 365.2425, sidereal 365.256363 and savana 360. The two variable solar-year modes use PyJHora. |
| `chara_school`, `karaka_scheme`, `colord_rule`, `arudha_exception` | KNRao, 7_KNRao, school, standard | Read by the Jaimini layer. The engine's running Chara dasha maps KNRao and PVR; Rath raises `ValueError` (not implemented). |
| `d24` | **forward** | `reverse` = PyJHora D24 method 2 (even signs counted from Cancer in reverse). |
| `combust_table` | **surya_siddhanta** | `wide_variant` = the wider set of combustion orbs. Applied when the engine marks planets combust; recorded in `meta.arcs`. |
| `gandanta_arc`, `sandhi_arc` | 10/3 deg (one nakshatra pada), 1.5 deg | Recorded for downstream consumers. |
| Ephemeris | **Swiss (.se1 files)** | `backend/data/ephe/` ships `sepl_18`, `semo_18`, `seas_18` (1800-2400 AD). Without them pyswisseph silently falls back to Moshier; the engine logs a warning and records `meta.ephemeris`. PyJHora's own `data/ephe` is on the path too (fixed stars for True Chitra). |
| Chara karakas | **7-karaka** (AK...DK, Rahu excluded) | PyJHora's `get_chara_karakas` returns the 8-karaka scheme; implemented directly by within-sign advancement. |
| Varga methods | Own Parashari tables, version `parashari-v3-half-open` | D1, D2, D3, D4, D6, D7, D9, D10, D12, D16, D20, D24, D30, D40, D45 and D60. D30 has five unequal parts and a separately declared within-part degree convention. |
| Geocoding | bundled `geonames_places_5k.csv` + timezonefinder/zoneinfo | fully offline; historical UTC offset from IANA tzdb. |

Presets `default`, `drik`, `jh`, `iae` are approximations of Drik Panchang / Jagannatha Hora / IAE-Rashtriya-Panchang conventions and **must be verified against your own JH / Drik / IAE install** before being described as matching either.

`drik.X` patching note: PyJHora 5 loads `drik` into a private globals dict while the visible module's `__dict__` is a copy. The engine patches the private dict (`drik.sidereal_longitude.__globals__`) — `drik.PLANET_FLAGS = ...` alone would be inert for PyJHora-internal calls, which is how `positions`/`center` propagate.

PyJHora keeps calculation state in process globals; the engine serialises compute / running_vimshottari / running_chara / transit_positions under one re-entrant lock (`engine.calc_lock`) and re-applies settings only when they change. Other modules calling `drik` directly (panchang, precision) should hold `calc_lock` if they must be isolated from a settings switch.

The app's half-open varga calculations treat an exact boundary as the beginning of the next part. Tests compare the interior of every supported part to the PyJHora oracle and check boundaries against the app's numeric convention.

## Regression checks (automated, `backend/tests/`)

- **Reference positions** — 1990-05-15 06:15 IST, Chennai (Lahiri, mean nodes):
  Sun 0.22° Taurus (just ingressed sidereal Taurus on May 15), Moon 27.7° Sagittarius (Uttara Ashadha), Lagna Taurus 7.4°, Rahu Capricorn / Ketu Cancer (correct node axis for mid-1990), Saturn ~1.5° Capricorn (Saturn ingressed Capricorn Feb 1990). All assertions tolerate small deltas and pin sign + nakshatra.
- **Determinism**: same input → byte-identical planets JSON.
- **Sensitivity**: +20 min moves Lagna degree while Sun sign is stable — lagna boundaries are genuinely time-critical (hence the timing caution when past-event checks are inconclusive).
- **Vimshottari**: period list spans ~120 years end-to-end; every antardasha ordered. `test_edge_cases.py` additionally asserts the nine mahadashas are contiguous, each lord appears exactly once, and total coverage equals 120 dasha-years (exact for savana_360; within drift for true_tropical).
- **Edge/property** (`test_edge_cases.py`): every varga row has 9 grahas + Lagna with valid sign/degree; D1 sign = floor(lon/30); lagna boundary flags fire within 2° of a sign edge; southern-hemisphere charts compute; `meta.ephemeris` matches the backend actually used.
- **Node/center** (`test_engine_frame.py`): mean-vs-true node sensitivity reports D1/D9 sign flips, Chara-dasha year changes for Scorpio/Aquarius, and karaka-rank ambiguity; topocentric Moon differs from geocentric by parallax; `apparent` positions differ by aberration.
- **Time stability** (`test_time_stability.py`): divisional-lagna sign windows and Moon nakshatra-pada windows are computed by grid-scan + bisection and surfaced in the cusp audit; ambiguous D9/D60 and pada boundaries are flagged, never guessed.
- **Varshaphala** (`test_varsha.py`): solar-return, Muntha, office-bearers, bala, Mudda dasha and yoga rows against the Bhadohi fixture.
- **Mode B** (`test_modeb.py`): pasted degree-table parser — precision detection (deg / deg.dec / D:M / D:M:S / retrograde / Lagna), ambiguous varga/karaka flags at coarse precision, explicit `unavailable` list for layers needing birth data (houses, dashas, Chara dasha); authenticated endpoint returns 422 on unparseable input.

## Reference check vs other software

Sun at sidereal Taurus ingress on 15-May-1990, Moon in Uttara Ashadha, Rahu in Capricorn (mean node) all agree with standard ephemerides (e.g., Drik Panchang / Jagannatha Hora for the same instant). Remaining divergence vs other apps should come from ayanamsa choice — Lahiri documented above; a ~24' difference vs apps defaulting to other ayanamsas is expected, not an error.

## Pillar caveats

- **Tajika**: full Varshaphala (`backend/app/astro/varsha.py`): exact solar return solved against `swe` to ~1e-6", Varsha Lagna, Muntha, five office-bearers (Varsheshwara via Pancha-vargiya bala, Muntha-lord, Varsha-lagna lord, birth-lagna lord, Trirashi-lord), Mudda dasha, and the classical Tajika yogas (Ithasala, Ishrafa, Kamboola…) via PyJHora's `tajaka`/`annual`/`mudda` APIs. Sahams are not implemented; the solar-return pillar reports that explicitly.
- **KP/micro-timing**: implemented as monthly Jupiter/Saturn transit-over-domain-house + SAV≥28 bindu strength + ashtama-Shani flag. No cuspal sub-lord KP.
- **Jaimini**: Chara dasha sign vs karaka sign / A10 / UL via rashi drishti (movable↔fixed, dual↔dual).
- The four pillars can each return `unavailable` — missing data is reported, never guessed.

## Verifier

Every LLM reply is checked before display: planet-in-sign, planet-in-house, running-dasha claims vs computed values; % probabilities banned; precise degree assertions banned (degrees are locked facts); classical citations rejected unless retrieved from a knowledge source. Offending sentences are stripped, else a fallback reply is substituted.

## Prediction protocol 2026-11-18.1

A follow-up may refine the event or period from the preceding reading. Each new record freezes the resolved event and calculation window alongside the user's original wording. Earlier records retain the protocol used when they were issued.

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

## Outcome tracking and rule backtest

This is the measurement pipeline that precedes any calibrated-probability mode. It measures; it does not tune.

**Pre-registration (immutable).** When an event forecast is saved, `prediction_registrations` stores a canonical JSON payload and its SHA-256: stable rule IDs that fired per pillar (`<pillar rule>/<rule label>`, with dates, planets and house numbers removed), per-pillar verdicts, convergence n/4, promise grade, window, event definition and success criteria, settings fingerprint, calc fingerprint, rule-pack version and file hash, app version and timestamp (`app/astro/preregistration.py`). Code enforces it: an ORM guard rejects any update of a `PredictionRecord` outside `followup_asked_at / outcome / outcome_at / event_date`, and any update of a registration. A bulk SQL edit bypasses ORM guards, so the backtest re-verifies hash, window and event type per row and excludes mismatches (reported as `registration_mismatch`). Legacy records without a registration are excluded.

**Outcome capture.** `GET /api/predictions/due` lists the user's issued forecasts whose window has ended; `POST /api/predictions/{id}/outcome` records happened / partly / did_not / unsure / outside_window (an event date is required for "happened" and is checked against the window); `GET /api/predictions/history` lists answered ones. The page `/predictions` and the chat follow-up buttons use them. Only `happened` is a hit; partly, did_not and outside_window are misses; unsure is excluded. Repeated forecasts for the same profile, event and window count once (earliest).

**Backtest** (`app/astro/backtest.py`, `backend/scripts/rule_backtest.py`, admin-only `GET /api/admin/backtest`, `refresh=true` recomputes and writes `backend/data/backtest_report.{json,md}`). For every rule ID and pillar: hit rate when fired vs the base rate of the same event type and window length (<=1m, <=3m, <=6m, >6m); lift; a shuffled-chart null (outcomes permuted across charts within each event type x window stratum, 2000 permutations, fixed seed) with a two-sided p-value, Bonferroni-adjusted across all tested features; reliability by convergence n/4 with Wilson intervals; leave-one-out Brier score of "hit rate of the convergence level" against the constant base rate. Anything with fewer than 30 outcomes is reported as `insufficient data` and gets no estimate. Access: set `JYOTISH_ADMIN_EMAILS`.

```sh
JYOTISH_DATABASE_URL=... backend/.venv/bin/python backend/scripts/rule_backtest.py
```

**Weighting hook.** `backtest.rule_weights()` returns a multiplier per rule: 1.0 unless the rule has at least 30 outcomes and a significant adjusted p-value against the null, then its lift clamped to 0.5-1.5. It is not applied to scoring. `JYOTISH_USE_BACKTEST_WEIGHTS` (default false) only gates `active_rule_weights()`. Applying weights would mean changing the `supports/conflicts` tallies inside each `pillars.pillar_*()` verdict rule, which is not a small change, so it is deliberately not wired in; that is where it would go. Weights fitted on a sample must be tested on a later untouched holdout before use.

**Display policy.** No percentages, lifts or hit rates are shown to users until a holdout validation passes; the report is owner-only. Outcomes are self-reported and subject to selection and recall bias; the backtest cannot establish predictive validity, only whether a rule beats randomly paired outcomes in this sample.

## Calibrated probabilities (not implemented)

The software deliberately emits no probabilities. The convergence badge ("Traditional convergence: n/4 pillars indicate this window") counts agreement among techniques that share the same birth data; it is not a probability and carries a fixed disclaimer (Carlson 1985; Narlikar et al. 2009 found no better-than-chance performance in controlled studies). A calibrated-probability mode would require, in order:

1. Birth data of AA (Rodden) rating, with recorded time source.
2. Pre-registered rules and event definitions, fixed before any outcome is seen.
3. Base rates for each event type and window length.
4. A train / held-out split, scored with Brier score, log loss and reliability (calibration) curves against the base-rate baseline.
5. A shuffled-chart null: the same rules run on charts paired with other people's outcomes, to show the real result beats chance.
6. Publication of the method, data description and negative results.

`backend/app/astro/validation.py::evaluate_dataset` already implements the cutoff / held-out-profile split and majority-event baseline for step 4; the shuffled null and per-rule Brier-style metrics are computed by the outcome backtest above (log loss is not).

## LLM output controls

Provider temperature defaults to 0.2 (`JYOTISH_LLM_TEMPERATURE`); the model id and temperature are logged on every call. Facts are sent with stable IDs (F001..), and computed evidence/rules with E###/R### IDs, and the model is asked to cite them inline. The verifier checks degrees, sign and nakshatra names, ISO and "Month YYYY" dates, dasha year durations and probability wording against the text the model was shown. Strict JSON-schema output is deferred: it does not fit the current streaming plain-text response path.

Golden-chart scaffolding is in `backend/tests/golden/` (see its README); the only fixture so far is a self-snapshot, which is a regression guard and not an external reference.
