# UCDP local snapshot (interim, no API key)

The UCDP API is token-gated as of 2026-07-13 (`401 API token required`), and the
token request is pending. The **full datasets are freely downloadable without a
key**, so the axis runs off a local snapshot until the token arrives.

This works because **UCDP/PRIO ACD is a yearly release** — a one-time local file
is not a staleness risk. There is nothing newer to fetch until the next annual
release.

## What to download

1. Go to <https://ucdp.uu.se/downloads/>
2. Take the **UCDP/PRIO Armed Conflict Dataset**, version **26.1**, in **CSV**
3. Save it here as:

```
data/ucdp/ucdpprioconflict_26_1.csv
```

That exact filename — it is what `core/global_indicators.UCDP_LOCAL_CSV` looks for.

## What happens then

`fetch_ucdp()` counts **unique `conflict_id` in the latest `year`** and reports it
as `active_armed_conflicts` with `source: "local_csv_26.1"`.

The dataset is a *conflict-year panel*: one row per (conflict, year), and a row
exists only if that conflict was active that year. There is no `active` flag to
filter on — **presence is activity**.

Sanity: the count should land somewhere around 50–60 for recent years. If it
comes back as 0, or in the hundreds, the column mapping is wrong — check the log
line, which prints the year and the count.

## When the token arrives

Put `UCDP_ACCESS_TOKEN=<token>` in `.env`. The live API takes precedence
automatically and this CSV is ignored. **No code change, no config change.**

## Why this file is not in git

The CSV is bulk third-party data under UCDP's licence. `data/ucdp/` is
gitignored — same convention as the V-Dem bulk CSV. Download it manually; do not
commit it.
