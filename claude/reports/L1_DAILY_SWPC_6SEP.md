# L1-DAILY — NOAA SWPC planetary K-index probe → SPACE_INFRASTRUCTURE
### 6 September 2026. Live payload, extract path read off it, cadence derived from the payload's own timestamps.

## The probe

```
GET https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
http_status=200   bytes=4,709   seconds=0.32
```

**Key required: no.** Anonymous GET, no token, no browser, no CAPTCHA. The smallest and
fastest payload of anything probed today.

## The payload, as it came back

```
rows        : 61
element     : dict (NOT the header-row array most SWPC products use)
keys        : time_tag, Kp, a_running, station_count

first : {'time_tag': '2026-08-30T00:00:00', 'Kp': 3.67, 'a_running': 22, 'station_count': 8}
last  : {'time_tag': '2026-09-06T12:00:00', 'Kp': 1.33, 'a_running':  5, 'station_count': 8}
```

**First trap, hit immediately.** Most `services.swpc.noaa.gov/products/*.json`
endpoints return a list-of-lists whose **first row is the column names**, so the
idiomatic reader is `data[0]` = header, `data[1:]` = rows. **This endpoint does not.**
It is a list of dicts and `data[0]` is real data. A reader that drops the first row here
silently discards a genuine measurement, and one that reads `row[0]` gets a `KeyError`
— which is the lucky case, because it fails loudly.

## The extract path

```
data[i]["time_tag"]      -> "2026-09-06T12:00:00"   ISO, UTC, NO timezone suffix
data[i]["Kp"]            -> 1.33                    UNITS: Kp index, 0–9, dimensionless
data[i]["a_running"]     -> 5                       UNITS: nT (running "a" index)
data[i]["station_count"] -> 8                       how many magnetometers contributed
```

## Real update cadence — derived from the timestamps

```
span    : 2026-08-30 00:00 -> 2026-09-06 12:00  = 180.0 hours (7.5 days)
step    : 180 minutes, on all 60 intervals       <- 3-hourly, no gaps
lag     : 328 minutes (5.5 h) behind utcnow 17:28
rows in the last 24 h : 9
```

**This is a 3-HOURLY series, not a daily one, and the brief's "last 24 h" is 9 rows,
not one.** Kp is defined on 3-hour UT intervals — that is the measurement, not a
sampling choice — so any daily number is an aggregate somebody has to choose (max? mean?
count above 5?) and that choice is a modelling decision, not a read.

The **5.5-hour lag** matters too: the most recent interval is not the current one. A job
running at 03:04 sees data ending around 21:00 the previous evening.

## Current values

```
Kp last          : 1.33
Kp range in file : 0.33 – 3.67
max Kp in 24 h   : 1.33
a_running        : 2 – 22
station_count    : 7 or 8   (it varies)
```

## What would be wrong to do with it

**1. Averaging Kp.** Kp is a **quasi-logarithmic** index — the step from 5 to 6 is a far
larger change in disturbance than 1 to 2 — and its values are quantised in thirds
(0.33, 0.67, 1.00, …, as the distinct set above shows). The mean of a log-scaled ordinal
index is not a physical quantity. `a_running` exists precisely because it is the linear
one; if something must be averaged, average that.

**2. Calling a quiet week "improving space infrastructure".** Kp measures geomagnetic
*disturbance*, which is driven by the Sun. It says nothing about the state of anyone's
satellites, grid or infrastructure — it is a hazard input, not an outcome. Wiring
`Kp` to a `SPACE_INFRASTRUCTURE` axis and reading a low value as "things are going well"
is the facade pattern: a real number, moving daily, attached to a concept it does not
measure. **What Kp can honestly support is a hazard/exposure count — e.g. "hours at
Kp ≥ 5 in the last 24 h" — not a health score.**

**3. Treating `station_count` as constant.** It is 7 on some intervals and 8 on others.
A Kp derived from fewer magnetometers is a slightly different measurement, and nothing
in the value itself says so.

**4. Parsing `time_tag` as local time.** It is UTC with **no suffix** — no `Z`, no
offset. `datetime.fromisoformat` returns a naive object that will be treated as local
time by anything that later localises it, silently shifting every reading by the
machine's offset (here, +03:00).

## Status

**Probe only.** Nothing wired, no config entry, no axis claimed. The finding: keyless,
0.32 s, no gaps — but **3-hourly rather than daily, 5.5 hours behind, and measuring a
hazard rather than a state**. It is the best-behaved feed probed today and the one most
likely to be misused.
