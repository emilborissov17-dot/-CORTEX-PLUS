# The Meadow — KPI #6

The system's first space for **free, unjudged thought** over a wide, raw slice of its
own world.

Everything built before this — gates, oracles, judges, the promotion pipeline — is
machinery for **selection**. Selection presupposes something to select from, and
nothing yet produces it. The meadow is the generative half: a place where the system
thinks over its world with **nothing scoring the result**.

## The design principle: don't steal the exercise

A baby doesn't learn from indices. It learns from a flood of uncurated, contradictory
stimuli, and *finding the structure in that flood is the thinking*. If we pre-structure
the input — hand the model five tidy scalars — we've already done the exercise and
stolen it. So the meadow builds a **wide, raw, date-rotated slice** and asks the model
to find what repeats, what contradicts, what is signal and what is noise.

## Two phases, one script

**DIVERGE** — build the slice, send it to the best available brain (`call_groq`, full
fallback chain), write the reply **verbatim** to `notebook/YYYY-MM-DD.md`. No parsing,
no validation, no PASS/FAIL. A small header records which slice it saw (sources, seed,
counts) so a future reader knows exactly what a page was written from.

**COMMIT** — feed the model its own notebook page back and let it choose **one** thought,
if any, worth becoming a testable claim → `committed/YYYY-MM-DD.json`. *"None of these
are ready"* is a legitimate and often correct answer. Not wired to any tracker — that's
a later task; the file just exists, human-readable.

## The slice (built fresh each run, rotated by date-seed)

| Section | Source | Nature |
|---|---|---|
| (a) NEWS | `news/news_latest.json` | raw items, flattened across all axes, **not** chosen by topic |
| (b) TRANSCRIPTS | `memory/transcript_cache/` | verbatim fragments of the newest media watched |
| (c) COUNTRIES | `output/wellbeing_all_countries.json` + `output/wb_cache/` | 30 rotated countries, raw indicators, mixed domains — **not** global averages |
| (d) REAL_DATA axes | `snapshots/**` + `memory/goal_score_history.json` | the **only** pre-digested part, labelled as such |
| (e) OWN DAY | `memory/existence_ledger.jsonl` + `memory/cycle_logs/` | the system's own diary, verbatim |

The seed is the date, so a given day always draws the same slice — `--date` reproduces
a past day, and the recorded seed is meaningful.

## Rules (constitutional)

1. **Isolation** like pulse/dreams: own dir, reads `news/ snapshots/ memory/ output/`
   as data only, writes only under `experiments/meadow/`. The one sanctioned live
   import is `core.groq_backend.call_groq` — the shared brain, a one-way dependency.
2. **DIVERGE output is unjudged.** There is no `check.py` and there must never be one.
   Any mechanical quality gate would be judgement, and judgement is what the meadow
   exists to be free of. The only quality signal is Emil reading the notebook.
3. **Notebook + committed are gitignored** — the system's private thought. Only code is
   committed. The notebook is append-only.
4. `--dry-run` prints the bundle and both responses without writing. `--date` reruns a
   past day's slice where the data allows.

## Name the failure in advance (house rule)

The most likely failure is **textbook association** — "CO2 → temperature", a sentence
that could have been written without seeing today's bundle. There is **no defence**
against this in DIVERGE, on purpose: a filter would be judgement, and judgement kills
the meadow. The test is Emil reading the first page. **If it reads like it never saw
the slice, the meadow grew weeds — and we fix the INPUT and the PROMPT, never the
output.**

## Usage

```
venv/Scripts/python.exe experiments/meadow/meadow.py --dry-run     # print, write nothing
venv/Scripts/python.exe experiments/meadow/meadow.py               # today's slice, real
venv/Scripts/python.exe experiments/meadow/meadow.py --date 2026-07-14
```

Tests (mechanics only — never the quality of the thought):

```
cd experiments/meadow && ../../venv/Scripts/python.exe -m pytest test_meadow.py -q
```
