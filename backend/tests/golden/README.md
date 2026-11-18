# Golden reference charts

Fixtures here are compared with the engine by `tests/test_golden.py`. The
goal is agreement with an *external* program (Jagannatha Hora or Drik
Panchang) under identical, recorded settings. Until such fixtures exist the
only accuracy evidence is the self-snapshot, which detects regressions, not
errors.

## Exporting a chart from JH / Drik

1. Open the program, enter the birth data (local date and time, UTC offset,
   latitude, longitude). Use a rectified or AA-rated time.
2. Record the settings that were active. Every one of these can move a
   planet, a sign or a dasha date:
   - `source_program` and `version` (for example `Jagannatha Hora` / `7.x`)
   - ayanamsa id and its **value in degrees for the birth date** (read it
     from the program; Lahiri differs between ICRC, 1940 and VP285 tables)
   - node type (mean or true)
   - positions: true or apparent
   - center: geocentric or topocentric (observer at the birth coordinates)
   - combustion orb table (surya_siddhanta or wide_variant)
   - dasha year mode (365.25, 365.2425, sidereal, 360 savana, true tropical)
   - varga schemes (Hora, D6, D24 direction, D30 and D60 variants)
3. Export planet longitudes to the arcsecond (not rounded to the minute),
   the Lagna, the divisional-chart signs, and the Vimshottari maha/antar
   dates.
4. Save as `<name>.json` in this directory using the schema below.

## Fixture schema

```json
{
  "source_program": "Jagannatha Hora",
  "version": "7.x",
  "settings": {
    "ayanamsa": "LAHIRI", "ayanamsa_value_deg": 24.0,
    "node": "mean", "positions": "true",
    "dasha_year": "true_tropical",
    "varga_schemes": {"d24": "forward"},
    "engine": {"ayanamsa": "LAHIRI", "node": "mean", "positions": "true",
               "dasha_year": "true_tropical"}
  },
  "input": {"date": "1984-07-13", "time": "09:14:00", "tz_offset": 5.5,
            "lat": 25.4, "lon": 82.57, "place": "name"},
  "expected": {
    "planets_arcsec": {"Sun": 0, "Moon": 0},
    "lagna_arcsec": 0,
    "vargas": {"D9": {"Lagna": 0, "Sun": 0}},
    "dasha": [{"maha": "Jupiter", "antar": "Jupiter", "start": "YYYY-MM-DD"}]
  }
}
```

* `planets_arcsec` and `lagna_arcsec`: sidereal longitude 0-360 degrees in
  arcseconds (degrees x 3600).
* `vargas`: `{D-chart: {body: sign index 0-11}}`, 0 = Aries.
* `dasha`: maha/antar rows with `start` dates.
* `settings.engine` holds the `CalcSettings` field values the engine must be
  run with; the other `settings` keys are recorded provenance.

## Tolerances

| Quantity | Tolerance |
|---|---|
| Planet longitude | 1 arcsecond |
| Lagna | 2 arcseconds |
| Dasha dates | 1 day |
| Varga signs | exact |

## Self-snapshot (not a reference)

`bhadohi_self_snapshot.json` is produced by this engine and has
`"source_program": "self-snapshot (NOT an external reference)"`. It only
pins current behaviour. Regenerate it deliberately (and review the diff) when
a calculation is intentionally changed.

## Edge-case fixtures (TODO, all need an external reference)

- [ ] DST gap (non-existent local time) and DST overlap (repeated hour)
- [ ] India 1942-45 (war time, UTC+6:30) and other wartime offsets
- [ ] Pre-1955 Bombay local time (UTC+4:51) and other historical LMT zones
- [ ] Southern hemisphere birth
- [ ] |latitude| 60-70 degrees (Lagna speed, house systems)
- [ ] Moon within 10 arcseconds of a nakshatra edge
- [ ] Planet at 29 deg 59 min 59 sec (sign boundary)
- [ ] Chara karaka ties (equal degrees)
- [ ] Mean vs true node falling in different signs (D1 and D9)
- [ ] Every co-lord branch (Scorpio/Aquarius, school-dependent rule paths)
