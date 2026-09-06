# CO₂ PROVENANCE — where 427.15 actually comes from
### 6 September 2026. Read-only trace. Nothing changed; the 03:04 cycle runs on the code as it is.

## Answer, in one line

**`core/global_indicators.py:78` fetches `co2_weekly_mlo.csv` — the WEEKLY Mauna Loa
file — while `config/axis_source_map.json:63` declares `co2_trend_gl.csv`, the DAILY
GLOBAL file. The config and the code name different products, and the code wins.**

## The write path

```
core/global_indicators.py:77   def fetch_co2() -> dict:
core/global_indicators.py:78       text = _get("https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv")
core/global_indicators.py:81       lines = [l for l in str(text).splitlines() if not l.startswith("#") and l.strip()]
core/global_indicators.py:85       p = lines[-1].split(",")
core/global_indicators.py:87       "co2_ppm":             float(p[4]),
core/global_indicators.py:88       "co2_ppm_1yr_ago":     float(p[6]),
core/global_indicators.py:89       "co2_annual_increase": round(float(p[4]) - float(p[6]), 2),
core/global_indicators.py:90       "co2_date":            f"{p[0]}-{p[1].zfill(2)}-{p[2].zfill(2)}",
```

→ `snapshots/master/global_indicators_latest.json` → `memory/composed_indicators.json`
(anchor `gi_noaa_co2`, origin `snapshots/master/global_indicators_latest.json`) →
`CLIMATE_GLOBAL_RISK_REVIEW`.

## The exact row it read

Last line of `co2_weekly_mlo.csv`, fetched live today:

```
year,month,day,decimal,average,ndays,1 year ago,10 years ago,increase since 1800
2026,8,30,2026.6616,427.15,4,425.25,401.12,150.11
```

| snapshot field | code | column | value | matches? |
|---|---|---|---|---|
| `co2_ppm` | `float(p[4])` | `average` | **427.15** | ✅ exact |
| `co2_ppm_1yr_ago` | `float(p[6])` | `1 year ago` | **425.25** | ✅ exact |
| `co2_annual_increase` | `p[4] - p[6]` | — | **1.90** | ✅ exact |
| `co2_date` | `p[0]-p[1]-p[2]` | — | **2026-08-30** | ✅ exact |

**All four fields reproduce exactly.** There is no cache, no staleness bug and no
parsing error. The number is correct *for the file the code fetches*.

## Which file yields 427.15 on 2026-08-30

Three NOAA products, same date, fetched live:

| file | value(s) on 2026-08-30 | yields 427.15? |
|---|---|---|
| **`co2_weekly_mlo.csv`** col `average` | **427.15** | ✅ **this one** |
| `co2_daily_mlo.csv` | 427.32 | ✗ (+0.17) |
| `co2_trend_gl.csv` `smoothed` | 423.77 | ✗ (−3.38) |
| `co2_trend_gl.csv` `trend` | 427.85 | ✗ (+0.70) |

**Only the weekly Mauna Loa file produces it**, which settles the hypothesis I recorded
in `L1_DAILY_NOAA_CO2_6SEP.md`. I guessed the mismatch was global-vs-Mauna-Loa. It is
that, **plus weekly-vs-daily** — and the second half is the one that explains the lag.

## Why the date is 7 days behind

**Because the file is weekly, not stale.**

```
co2_weekly_mlo.csv : 2,729 rows, 1974-05-19 → 2026-08-30
                     step = 7 days on all of the last 60 intervals
                     lag today − last row = 7 days
```

One row per week. The most recent row *is* 2026-08-30, and the next will be 2026-09-06.
**Nothing is behind; the source simply publishes weekly.**

The three files, ranked by freshness:

```
co2_trend_gl.csv     last 2026-09-05    lag 1 day     daily, global
co2_daily_mlo.csv    last 2026-09-03    lag 3 days    daily, Mauna Loa
co2_weekly_mlo.csv   last 2026-08-30    lag 7 days    WEEKLY, Mauna Loa   <- in use
```

## What this means for the gate

`CLIMATE_GLOBAL_RISK_REVIEW` is the **one** indicator the cadence gate rates usable for
a 14-day deadline. It is registered as `daily` — and the feed behind it delivers a new
value **once a week**.

That is not fatal: the cadence gate's `daily` tier allows a 30-day horizon and a weekly
series still lands inside it. But the tier is wrong about the thing it describes, and
the consequence is concrete — **for six days out of seven, a "daily" indicator returns
the same number it returned yesterday.** A prediction registered on day 2 of a week has
five days in which nothing can move it.

## A second finding, not asked for

`ndays` on the row in use is **4**:

```
2026,8,30,2026.6616,427.15,4,425.25,401.12,150.11
                            ^ ndays
```

That weekly average is built from **four days of measurement**, not seven. `fetch_co2`
reads `p[4]` and `p[6]` and never looks at `p[5]`. A week with 1 or 2 valid days
produces a value indistinguishable from a week with 7 — and NOAA publishes `-999.99`
for weeks with no data at all, which `float()` would accept and pass through as a CO₂
reading of minus a thousand ppm.

## Summary of the discrepancy

| | declared | actual |
|---|---|---|
| URL | `co2_trend_gl.csv` (`axis_source_map.json:63`, `composer_specs.json:55`) | `co2_weekly_mlo.csv` (`global_indicators.py:78`) |
| geography | global marine surface | Mauna Loa, single station |
| cadence | daily | **weekly** |
| `primary_metric` says | `co2_ppm_mauna_loa` | Mauna Loa ✅ — the *metric* name matches the code, the *URL* does not |

The `primary_metric` name and the code agree with each other; the URL in the same config
block disagrees with both. Whichever is wrong, **the config cannot currently be used to
tell what the number is** — which is what a provenance record is for.

## Not fixed tonight, deliberately

Per the instruction: the 03:04 cycle runs on the code exactly as it is, so tonight's
gate report is comparable with this morning's. **No file was modified by this trace.**
