# L1-DAILY — GDELT daily event count → the first gate-resolvable daily indicator
### 7 September 2026. Read-only probe + wiring built. NOT activated: no registration written before the 03:04 cycle.

## 1. The endpoint the cycle already pulls returns nothing

`core/global_indicators.py:603 fetch_gdelt()` calls the DOC 2.0 API with
`mode=timelinetone`. Measured live, 2026-09-07:

```
mode=timelinetone   http 200  121 bytes  {"timeline":[{"series":"Average Tone","data":[ ]}]}
mode=timelinevolraw http 200   80 bytes  {"timeline":[ ]}
every request after those:     http 429  "Please limit requests to one every 5 seconds"
```

**Two separate problems.** It returns *tone*, not a count — so no event count exists in
it at all. And it returns an **empty series**, so `fetch_gdelt()` falls through to `{}`
and the media slot is dead on arrival. The 429 then persisted for **45+ minutes**, not
the advertised 5 seconds, so this is a cooldown rather than a rate window.

`"date_resolution": "15m"` came back for a `timespan=1month` request, which is a second
sign the query is being rejected rather than served.

## 2. The static file server answers — one file per day

```
GET https://data.gdeltproject.org/events/<YYYYMMDD>.export.CSV.zip
  20260903  http 200  7,348,025 bytes   Last-Modified: Fri 04 Sep 07:00:10 GMT
  20260904  http 200  6,747,569 bytes   Last-Modified: Sat 05 Sep 07:00:12 GMT
  20260905  http 200  3,983,991 bytes   Last-Modified: Sun 06 Sep 07:00:06 GMT
```

Different host, no key, no rate limit hit.

## 3. The extract path, read off the real payload

```
zip://<YYYYMMDD>.export.CSV.zip  !/  <YYYYMMDD>.export.CSV
  -> TAB-separated, 58 columns, NO header row
  -> column 0 = GLOBALEVENTID
  -> column 1 = SQLDATE (YYYYMMDD)
  -> THE DAILY EVENT COUNT IS THE NUMBER OF ROWS
```

**Units: events per day** (count of GDELT event records). Unzipped ~42–46 MB per day.

## 4. Cadence and the series, from the payload's own dates

```
day         rows      SQLDATE == filename    published
20260903  117,020     114,504  (97.8%)       04 Sep 07:00 UTC
20260904  107,037     104,882  (98.0%)       05 Sep 07:00 UTC
20260905   66,878      65,683  (98.2%)       06 Sep 07:00 UTC
```

**Daily, published ~07:00 UTC the following day — a one-day lag.** `recent_days()`
never asks for today, because today's file does not exist yet.

**MOVED across the last 3 available days: TRUE**, and true under either counting
definition. That is the precondition FIRST BET requires, and it is the first indicator
probed that actually satisfies it.

## 5. The traps

**1. The SQLDATE trap, and how nearly it caught me.** The first row of the 20260903
file has `SQLDATE = 20160905` — a 2016 event. Read from row 0 alone, the obvious
conclusion is "this file is full of stale dates". **It is not**: 97.8% of rows carry the
file's own date. A daily export holds events *recorded* that day, and ~2% are older
events reported today. Row-count and SQLDATE-filtered count are **both defensible and
different**; `count_from_zip(..., sqldate_filter=)` makes the choice explicit rather
than a default nobody chose.

**2. Strong weekly seasonality.** 117k → 107k → 67k. 2026-09-05 is a **Saturday**, and
news volume collapses at weekends. A day-on-day delta will be dominated by day-of-week,
not by the world. Any forecast or threshold has to be against the same weekday, or
against a 7-day baseline.

**3. The API and the file server disagree about what "GDELT" means.** The cycle's
`media` slot is tone from the DOC API; this is an event count from the export files.
They are different measurements from different products, and only the second one is
currently returning data.

**4. `metric_details` is not a file.** It is a key inside
`snapshots/master/goal_score_latest.json`. And `TRENDS_PATH` is
`cortex_memory/abstractions/trends.json`, **not** `memory/trends_latest.json` — I wrote
the wrong path into the module first, and a registration written there would have
resolved nothing while looking done.

## 6. The wiring — built, tested, NOT activated

`core/gdelt_daily.py` + `test/test_gdelt_daily.py` (11 tests, no network, no GPU).

**The resolution chain, traced rather than assumed:**

```
proposal_intake.judge
  -> proposal_intake._default_resolver          (proposal_intake.py:54)
  -> hypothesis_intake._resolves                (hypothesis_intake.py:244)
  -> evaluator.ground_truth(axis, metric)       (evaluator.py:89)
  -> cortex_memory/abstractions/trends.json[axis]  ... takes values[-1]
```

**The one line for tomorrow**, produced by `registration_entry()` and written by
nothing:

```json
{"GDELT_DAILY": [117020, 107037, 66878]}
```

merged into `cortex_memory/abstractions/trends.json` **after** the 03:04 cycle.

**Proved by test, with the staged entry in a temp file:** `judge()` returns `ADMITTED`
for `GDELT_DAILY` when the registration is present, and `REFUSED` naming the missing
series when it is not.

**The tripwire.** `test_the_registration_is_NOT_live_yet` asserts `GDELT_DAILY` is
absent from the live `trends.json` *and* that the file is non-empty, so it cannot pass
vacuously. It is meant to be **inverted by hand tomorrow, in the same commit that adds
the entry** — which makes activation a decision somebody makes rather than something
that drifts in.
