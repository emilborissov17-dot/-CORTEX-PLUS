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
3. Drop it in `data/ucdp/` — **under whatever name UCDP's zip gives it**

No rename needed. The loader globs `data/ucdp/` for any `*.csv` whose name starts
with `ucdpprioconflict` (case-insensitively) and takes the highest-sorting one, so
UCDP's own `UcdpPrioConflict_v26_1.csv` works as-is — and next year's
`UcdpPrioConflict_v27_1.csv` will be picked up with no code change.

## What happens then

`fetch_ucdp()` counts **unique `conflict_id` in the latest `year`** and reports it
as `active_armed_conflicts`, with the version read from the CSV's own `version`
column (e.g. `source: "local_csv_26.1"`).

The dataset is a *conflict-year panel*: one row per (conflict, year), and a row
exists only if that conflict was active that year. There is no `active` flag to
filter on — **presence is activity**. (Verified on v26.1: zero duplicate
`(conflict_id, year)` pairs, so the unique count equals the row count.)

## Sanity range

Measured from v26.1, active state-based conflicts per year:

| 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | **2025** |
|------|------|------|------|------|------|------|----------|
| 52   | 57   | 57   | 54   | 56   | 59   | 59   | **65**   |

So **~50–65** is the healthy band, and it has been trending *up*. v26.1 currently
reports **65 for 2025** — the highest in the series, not a bug.

If the count comes back as **0**, or in the **hundreds**, the column mapping is
wrong. Check the log line, which prints the file, the version, the year and the
count.

## When the token arrives

Put `UCDP_ACCESS_TOKEN=<token>` in `.env`. The live API takes precedence
automatically and this CSV is ignored. **No code change, no config change.**

## Why this file is not in git

The CSV is bulk third-party data under UCDP's licence. `data/ucdp/` is
gitignored — same convention as the V-Dem bulk CSV. Download it manually; do not
commit it.
