# L1-DAILY — NOAA GML CO₂ probe → CLIMATE, the reference case
### 6 September 2026. Confirming what we already fetch — and the stored value does not match the file.

## What the repo already declares

```
config/axis_source_map.json:63   "url": "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_trend_gl.csv"
config/composer_specs.json:55    same URL, id "noaa_co2_trend_global"
config/axis_source_map.json:55   "primary_metric": "co2_ppm_mauna_loa"
```

`CLIMATE_GLOBAL_RISK_REVIEW` is the **one** indicator the cadence gate currently rates
usable for a 14-day deadline — the daily tier's single working example. So this is the
reference case, and it is the one most worth checking.

## The probe

```
GET https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_trend_gl.csv
http_status=200   bytes=114,685   seconds=1.56
```

**Key required: no.**

## The payload

```
# NOTE: In general, the data presented for the last year are subject to change,
# depending on recalibration of the reference gas mixtures used, ...
year,month,day,smoothed,trend
2016, 1, 1,  402.67,  401.55
...
2026, 9, 5,  423.97,  427.89
```

## The extract path

```
skip lines beginning with '#'   (the comment block is ~50 lines and ends with a bare '# ')
row[0..2] year, month, day  -> date   (values are SPACE-PADDED: ' 9', ' 5')
row[3] smoothed -> float, UNITS: ppm
row[4] trend    -> float, UNITS: ppm
```

## Real update cadence — from the file's own dates

```
rows 3,901    first 2016-01-01    last 2026-09-05
step over the last 365 rows: {1 day: 365}     no gaps
lag today (2026-09-06) minus last row: 1 day
```

**Genuinely daily, one-day lag, no gaps** — the same grade as NSIDC, and the reason this
axis passes the cadence gate when twelve others do not.

## THE FINDING: the stored value is not in the file

`snapshots/master/global_indicators_latest.json` carries:

```json
"co2": {"co2_ppm": 427.15, "co2_ppm_1yr_ago": 425.25,
        "co2_annual_increase": 1.9, "co2_date": "2026-08-30"}
```

The live file on **that same date**:

```
2026-08-28   smoothed 423.73   trend 427.84
2026-08-29   smoothed 423.75   trend 427.85
2026-08-30   smoothed 423.77   trend 427.85     <- the snapshot's own date
2026-08-31   smoothed 423.80   trend 427.86
```

**Neither column equals 427.15.** It is 0.70 ppm below `trend` and 3.38 ppm above
`smoothed`, on the date the snapshot itself declares.

**And the value is seven days old** — dated 2026-08-30 against a file that has run
through 2026-09-05 with a one-day lag throughout. The one indicator the gate calls
daily is being served a week late.

**What this probe establishes and what it does not.** It establishes the mismatch: the
stored number is not a row of the file the config names, on its own date. It does
**not** establish the cause. NOAA publishes several CO₂ products — Mauna Loa versus
global, daily versus weekly versus monthly — and `primary_metric` is declared as
`co2_ppm_mauna_loa` while the URL points at the **global** trend file. That is a
plausible explanation and it is a hypothesis, not a finding. A stale cache would
explain the seven days but not the 0.70 ppm.

**This is worth a follow-up and is not one I am making here.** Nothing was changed.

## What would be wrong to do with it

**1. Using `smoothed` where `trend` is meant, or the reverse.** They differ by **3.92
ppm today** and by more at other points in the seasonal cycle. `smoothed` retains the
annual breathing of the biosphere; `trend` has it removed. A number that silently
switches columns moves several ppm for no physical reason.

**2. Reading a day-to-day change as signal.** The daily step is ~0.01 ppm and the file's
own header warns that **the last year of data is subject to revision** — recalibration
of reference gas mixtures can move recent values after the fact. Yesterday's number is
not final.

**3. Calling the global file "Mauna Loa".** `co2_trend_gl.csv` is the **globally
averaged** marine surface series. `primary_metric` in `axis_source_map.json` says
`co2_ppm_mauna_loa`. Those are different measurements from different places, and the
config currently names one and fetches the other.

**4. Splitting on whitespace.** Fields are space-padded inside a comma-separated file
(`2026, 9, 5,  423.97,  427.89`). Split on `,` and strip; splitting on whitespace gives
a different column count.

## Status

**Probe only. Nothing wired, nothing changed, no config touched.** Two findings on the
reference case: the source is keyless, 1.6 s, genuinely daily with a one-day lag and no
gaps — and **the value the axis is currently reporting is seven days old and matches no
column of that file on its own stated date.**
