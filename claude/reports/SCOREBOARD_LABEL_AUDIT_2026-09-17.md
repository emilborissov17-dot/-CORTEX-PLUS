# Scoreboard label audit — 17 September 2026

Every value printed by `scripts/agi_scoreboard.py` and `experiments/prophecy/scoreboard.py`,
with the function that computes it and whether the printed label names that function.

**Read-only. Nothing is fixed here.** One label was corrected earlier today in a separate
commit (`a6cd0f2`) and appears below in its corrected form, with the defect recorded.

The audit exists because T1 is about to use scoreboard numbers as evidence, and a number
is only evidence if the word over it names the statistic underneath. The failure this
guards against is not a wrong number — it is a **true number under a false name**, which
survives review precisely because everything about it looks right.

## Method

Read off the source, not off the rendered page: for each printed value, follow the field
back through `gather()` to the function that produced it. `file:line` is where the
arithmetic happens, not where the string is formatted.

Verdict column:

- **MATCH** — the label names the statistic that produced the value.
- **UNNAMED** — the value is printed with no statistic named. Not false; a reader cannot
  tell what it is without reading the code.
- **MISMATCH** — the label names a different statistic than the one computed.

---

## `experiments/prophecy/scoreboard.py` → `PROPHECY_SCOREBOARD.md`

This file labels **by construction**: `_row()` sets `row["rule"]` to the branch it took,
and the markdown prints that field as its own column (`scoreboard.py:160`). A row cannot
carry a rule it did not use, because the rule string and the arithmetic are set together
in the same `if`.

| printed label | function that computes the value | file:line | match? |
|---|---|---|---|
| `rule` column = `brier` | `brier()` — `(learner - actual) ** 2`, mean | `experiments/prophecy/scoreboard.py:102-108` | **MATCH** |
| `rule` column = `mae` | `mae()` — mean of `learner_err`/`baseline_err`, which are `_abs_err` | `experiments/prophecy/scoreboard.py:113-118` | **MATCH** |
| learner / baseline (brier rows) | `brier()` as above | `:103-104` | **MATCH** |
| **`self_failure` 0.176 vs 0.3202** | `brier()` — mean squared error | `:103-104` | **MATCH** |
| `climatology` | `(base_rate - actual) ** 2`, mean | `:107` | **MATCH** |
| `base_rate` | `sum(acts) / len(acts)` | `:106` | **MATCH** |
| learner / baseline (mae rows) | `mae()` over `o["learner_err"]` = `_abs_err` | `:114-115` | **MATCH** |
| `learner_wins` | count of `l < b`, per row's own rule | `:109`, `:116` | **MATCH** |
| `scored` | `len(pairs)` | `:99` | **MATCH** |
| `degenerate_excluded` | `len(pairs) - len(live)`, `_is_degenerate` | `:98`, `:87-94` | **MATCH** |
| `compared` | `len(live)` | `:99` | **MATCH** |
| `last_30` | same rule, `live[-WINDOW:]`, WINDOW = 30 | `:112-113`, `:63` | **MATCH** |
| `learner_beats_baseline` | `learner < baseline` on `all_time` | `:120-122` | **MATCH** |

`PROB_KINDS = {"self_failure", "self_degraded", "self_step_fail"}` (`:62`) decides which
branch a kind takes. Everything else is scored as MAE.

**Which computation each of the two reports uses, the question that started this:**
`prophecy/scoreboard.py` squares (Brier); `prophecy_ledger._abs_err()` takes the absolute
value (MAE). Both reproduce their own report exactly when recomputed from the sealed
predictions — n = 60, learner/baseline 0.1760/0.3202 squared and 0.2600/0.5351 absolute.

---

## `scripts/agi_scoreboard.py` → `AGI_14_SCOREBOARD.md`

This file reads numbers computed elsewhere and formats them into prose. It has no
rule column, so every statistic is named — or not — in free text.

| # | printed label | function that computes the value | file:line | match? |
|---:|---|---|---|---|
| 1 | `kNN MAE {knn} vs mean {baseline}` | `errs.append(abs(fn(...) - x[target]))`, meaned | `experiments/prophecy/country_bench.py:152` | **MATCH** |
| 1 | `{knn_closer}/{n} closer` | count of held-out countries where learner err < baseline err | `country_bench.py:152` (same loop) | **MATCH** |
| 1 | `weights learned on A beat persistence on B in x/y pairs` | `transfer_beats_persistence` from CROSS_SERIES_BENCH.json | `scripts/cross_series_bench.py` (producer) | **UNNAMED** — "beat" is a count, no metric named |
| 2 | `learner err {x} vs baseline {y}` | `_abs_err` → `learner_mean_err` via `by_kind` | `experiments/prophecy/prophecy_ledger.py:138`, aggregated `:234` | **UNNAMED** — "err" does not say which |
| 2 | `{n} fitted parameter(s)` | `len(learner_state["alpha"])` | `agi_scoreboard.py:222` | **MATCH** |
| 3 | `learning curve … k=10/20/40/80` | `few_examples` counts from CROSS_SERIES_BENCH.json | `scripts/cross_series_bench.py` | **UNNAMED** — a count of targets, metric not stated |
| 4 | `concepts found / surviving out of sample` | counts from CROSS_SERIES_BENCH.json (E2) | `scripts/cross_series_bench.py` | **MATCH** (counts, labelled as counts) |
| 4 | `constancy classes` | class tally | `memory/constancy_bands_latest.json` (producer `core/alarm_bands.py`) | **MATCH** |
| 5 | `accepted / refused` | row counts of jsonl files | `agi_scoreboard.py` `_jsonl` | **MATCH** |
| 5 | `E3 … proposed / judged / kept by the exam` | verdict tallies over `feature_proposals.jsonl` | `agi_scoreboard.py:138-141` | **MATCH** |
| 6 | `cycle reviews on file {n}, failed streak {k}` | `len(rv)`; consecutive `success` false | `agi_scoreboard.py:248-253` | **MATCH** |
| 7 | **`MAE self_failure 0.26 vs 0.5351`** | `_abs_err` → `learner_mean_err` | `prophecy_ledger.py:138`, `:234` | **MATCH** *(corrected today — see below)* |
| 7 | `world 80% intervals covered {x}` | `conformal_coverage` from CROSS_SERIES_BENCH.json | `scripts/cross_series_bench.py` | **MATCH** |
| 8 | `axis_next degenerate {d}/{s}` | `_is_degenerate` counts via `by_kind` | `prophecy_ledger.py:220-233` | **MATCH** |
| 8 | `direction learned (beats honest baselines by 2 SE)` | `direction_wins` from CROSS_SERIES_BENCH.json | `scripts/cross_series_bench.py` | **MATCH** — the test is named in the label |
| 9 | `learner margin over persistence {a} -> {b}` | `margin_then`/`margin_now` from `learner_progress.jsonl` | `agi_scoreboard.py:150-158` | **UNNAMED** — margin of what error is not stated |
| 10 | `learner beats control={bool}` | `learner_mean_err < baseline_mean_err` | `prophecy_ledger.py:236` | **UNNAMED** — the comparison is on MAE, unstated |
| 10 | `canon invariants {n}` | `len(invariants)` | `memory/canon_invariants.json` | **MATCH** |
| 11 | `targets grounded / ungrounded` | counts from TARGET_GROUNDING.md | `scripts/target_grounding.py` | **MATCH** |
| 12 | `sandbox T12 {verdict}` | pass/fail string from SANDBOX_BENCH.json | producer outside this file | **MATCH** |
| 13 | `TRACKS / INSENSITIVE / NOISE_DRIVEN / WRONG / SILENT` | verdict tallies | `core/counterfactual_probe.py` | **MATCH** |
| 13 | `tracks_rate {x}` | TRACKS / answered | `core/counterfactual_probe.py` | **MATCH** |
| 14 | `—` | nothing; no test exists | `agi_scoreboard.py:309` | **MATCH** — absence is stated |

---

## Findings

**One MISMATCH existed and was corrected today, in its own commit.**

Row 7 printed `Brier self_failure 0.26 vs 0.5351`. The value came from
`prophecy_ledger._abs_err()` — a mean **absolute** error. A Brier score is the mean
**squared** error, computed in `prophecy/scoreboard.py:103`. Both numbers were true and
both pointed the same way, which is why it survived: squared error is at most absolute
error on `[0,1]`, so `0.176 < 0.26` and `0.3202 < 0.5351` both look like the same
finding told twice. Corrected in `a6cd0f2` — **label only**; the row still reads
`learner_mean_err` and switching it to the real Brier remains a separate decision.

**Five UNNAMED values.** None is false. Each prints a number with no statistic named, so
a reader has to open the code to learn what it is:

- row 1, `transfer_beats_persistence` — a count of pairs, the winning criterion unstated
- row 2, `learner err … vs baseline` — MAE, unstated
- row 3, the learning curve — counts of targets, the metric unstated
- row 9, `learner margin over persistence` — margin in which error, unstated
- row 10, `learner beats control` — the comparison is on MAE, unstated

Rows 2, 9 and 10 all trace to the same `learner_mean_err` field that produced the row 7
mismatch. **The field name is the root cause**: `learner_mean_err` says "mean error"
without saying which mean of which error, so every consumer picks a word for it. Renaming
it to `learner_mae` would make the mismatch class hard to reintroduce — that is a
proposal, not a change, and it is not made here.

**No MISMATCH remains.** `prophecy/scoreboard.py` cannot produce one, because the rule
string and the arithmetic are assigned together in one branch.

---

## Consequence for T1

T1 may cite `PROPHECY_SCOREBOARD.md` values directly — that file names its own rule per
row. Values taken from `AGI_14_SCOREBOARD.md` rows 1, 2, 3, 9 and 10 must be described
by the statistic in this table, not by the word in the report, because those five name
no statistic at all.
