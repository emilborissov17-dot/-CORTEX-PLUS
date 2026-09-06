# L1-DAILY — NSIDC Sea Ice Index probe → CLIMATE
### 6 September 2026. Live payload, extract path read off it, cadence derived from the payload's own dates.

## The probe

```
GET https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v4.0.csv
    http_status=200   bytes=1,894,282   seconds=2.05
GET https://noaadata.apps.nsidc.org/NOAA/G02135/south/daily/data/S_seaice_extent_daily_v4.0.csv
    http_status=200   bytes=1,822,751   seconds=2.11
```

**Key required: no.** Anonymous HTTPS GET, no token, no browser, no CAPTCHA.

## First finding: the version everyone cites is dead

`N_seaice_extent_daily_v3.0.csv` — the filename in essentially every tutorial and in
most code that touches this dataset — returns **404**. So does the old
`masie_web.apps.nsidc.org` host.

I found the live file by **listing the directory** rather than guessing:

```
GET https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/
  -> N_seaice_extent_climatology_1981-2010_v4.0.csv
  -> N_seaice_extent_daily_v4.0.csv
```

A wired-in v3.0 URL would fail silently into whatever the caller does with a 404 body.
**The directory listing is the check that should be run before this is wired, and again
whenever it breaks.**

## The payload, as it came back

```
Year, Month, Day,     Extent,    Missing, Source Data
YYYY,    MM,  DD, 10^6 sq km, 10^6 sq km, Source data product web sites: …
1978,    10,  26,     10.231,      0.000, ['/ecs/DP1/PM/NSIDC-0051.001/…']
...
2026,    09,  05,      4.668,      0.000, ['/disks/sidads_ftp/DATASETS/…']
```

**Two header rows, not one.** Row 1 is names, row 2 is units. A reader that skips one
header line parses `YYYY, MM, DD, 10^6 sq km` as data.

## The extract path

```
skip 2 header rows
row[0] Year   row[1] Month   row[2] Day        -> date
row[3] Extent -> float, UNITS: 10^6 sq km
row[4] Missing -> float, same units; 0.000 means nothing was interpolated
row[5] Source Data -> provenance list; may be QUOTED and contain commas
```

**Units: million square kilometres.** Not km², not percent, not anomaly.

## Real update cadence — derived from the dates, not the docs

```
Arctic     rows 15,831   first 1978-10-26   last 2026-09-05
Antarctic  rows 15,831   first 1978-10-26   last 2026-09-05
step in days across the last 365 rows: {1: 365}      <- every single day, no gaps
lag (today 2026-09-06 minus last row): 1 day
Missing column over the last 30 rows: max 0.000, nonzero 0
```

**Genuinely daily, with a one-day lag, and no gaps in the last year.** That is the
strongest daily cadence of anything probed so far — stronger than USGS, which is a
rolling window rather than a dated series.

Current values: **Arctic 4.668**, **Antarctic 17.404** (10⁶ km², 2026-09-05).

## What would be wrong to do with it

**1. Adding the hemispheres together.** Arctic and Antarctic sea ice are on opposite
seasonal cycles — the Arctic is near its September minimum while the Antarctic is near
its maximum. Their sum is dominated by whichever is in season and moves for reasons that
have nothing to do with the climate signal. **They are two indicators, never one.**

**2. Reading a day-to-day change as a trend.** Arctic extent moved 4.656 → 4.690 →
4.668 over three days: it goes *up* on a day inside a multi-decade decline. Daily deltas
are weather. The daily cadence makes this a good *freshness* source; the signal is
seasonal-minimum or anomaly-against-climatology, and the climatology file
(`N_seaice_extent_climatology_1981-2010_v4.0.csv`) is sitting in the same directory for
exactly that.

**3. Ignoring the `Missing` column.** It is 0.000 today, which is why it is easy to
forget. When a satellite drops out it is not zero, and `Extent` is then partly
interpolated — a value that looks like every other value.

**4. Splitting `Source Data` on commas.** The last field is a Python-repr list that is
sometimes double-quoted and contains commas. Naive `line.split(",")` gives a different
column count on those rows.

## Status

**Probe only.** Nothing wired, no config entry, no axis claimed. The finding is a
keyless, 2-second, genuinely daily, gap-free series with a 1-day lag and honest units —
and a canonical URL that has moved, which is the reason to read the directory rather
than the tutorial.
