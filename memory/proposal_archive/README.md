# Proposal archive

Every proposal CORTEX++ generated, including the ones that were blocked,
duplicated, or wrong. Append-only: nothing here is ever edited or deleted.

## How to answer "what did the system propose about water in July"

Open `2026-07.md` and search for `water` (or `вода`). That is the whole method.
No tooling, no query language.

## What an outcome means

- `ACCEPTED`  — passed the alignment guard and entered memory/improvement_proposals.json.
              It may still have been deleted from there later by the 7-day cutoff
              or the 50-cap. This archive is the only place it survives.
- `BLOCKED`   — alignment guard refused it. The reason is on the `outcome` line.
              These never reached improvement_proposals.json at all.
- `DUPLICATE` — the system proposed it again; the fuzzy dedup dropped it. Kept,
              because "the system keeps raising this" is itself a finding.

## What is NOT here

No separate reasoning trace exists — no provider in the chain is asked for one.
`raw model output (batch)` is the model's full final text for the batch of
proposals that included this one, which is what is actually recoverable.

Entries backfilled on the day the archive was built carry `backfilled: true` and
have no model/provider/cycle_id, because none was recorded when they were made.
