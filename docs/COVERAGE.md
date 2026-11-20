# Jyotish AI coverage

The public coverage page reads the [versioned intent registry](../backend/data/intent_registry.json). It lists 60 intents, of which 18 are the first delivery group. A partial intent can use some existing calculations while further routing, calibration, or verification remains open. A registered intent alone does not enable timing.

| Area | Status | Evidence or remaining work |
| --- | --- | --- |
| Birth chart and vargas | Partial | The app computes D1 from Swiss Ephemeris UT calls and derives D1 through D60 with versioned, half-open divisional rules. Both node frames and changes in Chara years and karaka ranks are checked. PyJHora remains in several runtime modules. |
| Vimshottari | Partial | Fixed-year MD, AD and active PD boundaries use the app's own UT calculations. New default profiles use a 365.25-day year. Existing default profiles retain the documented tropical convention. Variable solar-year modes still use the library adapter. Full exported PD timelines and independent parity remain open. |
| Mode B | Partial | DMS, decimal, Hindi sign names and common hyphenated degree rows are parsed. Varga and pada alternatives propagate from source precision. Independent exports and the combined degree-table and birth-detail workflow remain open. |
| Birth-time sensitivity | Partial | Varga and Moon-pada stable windows are available in the dashboard. Past-event checks and candidate rectification are available. Independent oracle fixtures and a consolidated candidate-review view remain open. |
| Advanced settings | Partial | Calculation settings and named schemes are exposed in chart output. Some school and ayanamsa alternatives and exact external-preset verification remain open. |
| Tajika and strength | Partial | Annual return, office-bearers, strength and yogas are available in existing calculations. School-specific rules and full strength weighting still require validation. |
| Evidence and scoring | Partial | Grouped pillar evidence carries identifiers, sources and a unique dependency index. The displayed count describes traditional method agreement. Finding-level provenance, strength-weighted aggregation, and a schema-only explanation renderer remain open. |
| Ashtakavarga and transits | Partial | The dashboard includes BAV/SAV, sign and nakshatra ingresses, stations, bindu-active kakshyas and retrograde Sade Sati re-entries. The full convergence explorer remains open. |
| KP | Partial | A separate Swiss Krishnamurti / Placidus view provides cusps, 249 segments, basic significators and ruling planets at the chart instant. Node proxy rules and event timing remain open. |
| Safety and privacy | Partial | Shared charts require recorded permission, automated outcome follow-ups require opt-in, and distress and pregnancy forecasting are handled before the model. Existing account export and deletion are available. Encryption-at-rest verification and DPDP compliance review remain open. |
| Panchanga and matching | Partial | Panchanga and existing muhurta calculations are available. Source-verified task rule packs, synastry and Ashtakoota remain open. |
| Prospective evaluation | Partial | Forecast records include frozen criteria and versions. The holdout runner reports a development base rate, timing error, and reliability metrics when pre-window probabilities are supplied. Independent verified birth-time data, shuffled-chart comparisons and probability calibration remain open. |
| Verification corpus | Partial | The app tests the Bhadohi snapshot and uses PyJHora as a divisional sign oracle. The target of 50 independent Jagannatha Hora and Drik Panchang exports and 50 labelled questions per Phase 1 intent remains open. |

## Synthetic specificity

The file [specificity_results.json](../backend/data/specificity_results.json) contains 1,000 seeded chart-window simulations for ten observable event rules in protocol `2026-11-19.1`. Each window spans 12 calendar months. The supportive chart rate counts issued event windows. Supportive share measures the fraction of days inside qualified micro-timing intervals.

| Event rule | Supportive charts out of 1,000 |
| --- | ---: |
| Admission | 2 |
| Business launch | 3 |
| Engagement | 0 |
| Competitive exam pass | 2 |
| Graduation | 2 |
| Job change | 3 |
| Job offer | 3 |
| Marriage | 0 |
| Promotion | 3 |
| Relocation | 2 |

Two chart windows per rule had an unavailable pillar. These runs measure rule firing and abstention on synthetic inputs. Forecast accuracy requires separately scored, held-out events. The recurring counts across events in the same domain reflect shared domain calculations.

Protocol `2026-11-21.1` requires aligned dasha and micro-timing evidence in a qualifying candidate before it issues a forecast. Promotion, employer change and job offer also require distinct D1 contacts and corroboration in D10. In the new runs, the engine issued two employer-change windows, zero promotion windows and zero offer windows per 1,000 synthetic cases for each event. Run a single event from the backend with `python scripts/evaluate_specificity.py promotion --samples 1000`. The coverage page loads results only for the current protocol and intent version.
