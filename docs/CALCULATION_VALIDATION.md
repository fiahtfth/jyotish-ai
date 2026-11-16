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
