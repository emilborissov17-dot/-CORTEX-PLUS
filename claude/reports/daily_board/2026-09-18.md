# DAILY BOARD — 2026-09-18

Written 2026-09-18T06:21:40.933229+00:00 by `tools/daily_board.py`, run from `tools/prophecy_morning.bat` after the `agi_scoreboard` step.

One row per running experiment. Every number is printed under the name of the statistic that produced it. A row whose source is unusable prints **MISSING** and the path — never a default, and never yesterday's number moved into today's column.

Yesterday's column: no earlier board on disk in `claude/reports/daily_board/` — this is the first one, so the yesterday column says so rather than showing a recompute.

| experiment | what ran last night | today's number | yesterday's number | needs correction? |
|---|---|---|---|---|
| T1 transfer test | tools/transfer_test.py (qwen3:8b), 0.67 d ago (2026-09-17T14:12:45.625392+00:00) | verdict FAIL · success-rate difference on-off = -0.0156 (95% CI [-0.125, 0.0938], n=64) | no earlier board | **yes** — verdict is FAIL with 0/3 pre-registered conditions met — the design, not the run, is what has to change (condition: verdict != PASS) |
| Brain probe (scanner) | tools/brain_probe.py (models/Qwen2.5-3B-Instruct (4-bit NF4, fp16 compute)), 0.45 d ago (2026-09-17T19:28:29.947031+00:00) | best layer 35 · probe accuracy real 0.99 / control 0.4067 / selectivity (real - control) 0.5833 | no earlier board | **yes** — probe accuracy is below chance (0.5) in condition(s) all_down, all_up, true — the layer-35 probe does not transfer to the memory conditions it was read out on |
| Self-model | cycle 2026-09-18T03:04:01.569002+03:00 CYCLE_FINISHED after 6171.5 s, 42 steps completed, 2 degraded | 4 self-prediction(s) sealed for last night, none scored yet (self_failure, self_duration, self_degraded, self_step_fail); actual duration 6171.5 s | no earlier board | **yes** — 4 prediction(s) still open at board time — self_forecast --score runs earlier in the same 09:00 batch, so an open row here means the board was built before it or the scorer refused |
| World forecasts | 6 world_next sealed and 6 scored on 2026-09-18 | MAE (mean absolute error) learner 1.4311 vs naive-persistence baseline 1.84 over n=51 scored, exact ties excluded; 1.8715 vs 2.4062 over n=39 with ties to 3 decimals also excluded · Brier NOT DEFINED for this row | no earlier board | **yes** — 4/6 forecasts sealed this morning are the baseline to 3 decimals — EWMA on a near-flat series is persistence with a rounding tail, and exact-equality degeneracy does not catch it |
| Data freshness | core/daily_tier.py recorded 57 rows dated 2026-09-18; measurement honesty written 2026-09-18T01:13:10+00:00 | k1_fresh 0.0599 (share of goal weight resting on an observation no older than 30 days) · 4/57 daily indicators moved | no earlier board | **yes** — k1_fresh 0.0599 < 0.1; moved share 0.0702 < 0.1 — the daily tier is recording the same numbers again, so the world loop has almost nothing to learn from |
| Local brain alive | 135 logged model answers on 2026-09-18, 41 of them local | 41 local:* answers of 135 logged since 00:00 UTC (count of rows whose backend starts with 'local:'), 94 cloud | no earlier board | **no** — local share 0.3037 >= 0.25 |

---

## Detail, row by row

### T1 transfer test

Source(s): `memory/t1_result_full.json`

- success rate (share of trials whose stated direction was correct): on 0.7812 · off 0.7969 · shuffled 0.7188
- Brier score (mean squared error of the stated probability): on 0.315 · off 0.3042 · shuffled 0.3328
- success-rate difference, total (on - off): -0.0156 (95% CI [-0.125, 0.0938], n=64)
- success-rate difference, retrieval-specific (on - shuffled): 0.0625 (95% CI [-0.0469, 0.1719], n=64)
- success-rate difference, format (shuffled - off): -0.0781 (95% CI [-0.1719, 0.0156], n=64)
- every interval is a paired bootstrap, 10,000 resamples over tasks
- pre-registered acceptance conditions met: 0/3
- parse failures (on/off/shuffled) 0/0/0 · transport errors 0/0/0 — the Brier comparison is not void

Needs correction: **yes** — verdict is FAIL with 0/3 pre-registered conditions met — the design, not the run, is what has to change (condition: verdict != PASS)

### Brain probe (scanner)

Source(s): `claude/reports/BRAIN_PROBE_2026-09-17.json`

- A, primitive identity, best layer 34: probe accuracy real 1.0 · control 0.1433 · selectivity 0.8567 · chance 0.1667
- B, direction, best layer 35: probe accuracy real 0.99 · control 0.4067 · selectivity 0.5833 · chance 0.5
- spoken accuracy (share of 200 answers whose stated direction was correct): 0.995 · refusals 0 — against probe accuracy 0.99 at layer 35
- condition filler: spoken accuracy 0.995 · spoken up-rate 0.53 · probe accuracy not measured · n 200 · refusals 0
- condition true: spoken accuracy 0.735 · spoken up-rate 0.27 · probe accuracy 0.475 · n 200 · refusals 0
- condition all_up: spoken accuracy 0.53 · spoken up-rate 0.995 · probe accuracy 0.475 · n 200 · refusals 0
- condition all_down: spoken accuracy 0.61 · spoken up-rate 0.135 · probe accuracy 0.475 · n 200 · refusals 0

Needs correction: **yes** — probe accuracy is below chance (0.5) in condition(s) all_down, all_up, true — the layer-35 probe does not transfer to the memory conditions it was read out on

### Self-model

Source(s): `experiments/prophecy/prophecy_ledger.jsonl`, `memory/existence_ledger.jsonl`

- what happened: cycle 2026-09-18T03:04:01.569002+03:00 CYCLE_FINISHED after 6171.5 s, 42 steps completed, 2 degraded
- anchor the predictions were sealed against: next_cycle_after::2026-09-17T02:07:56.224958+00:00
- self_failure: SEALED, NOT YET SCORED — learner 0.8 vs baseline 0.5039; no error is computed here, experiments/prophecy/self_forecast.py --score owns that arithmetic
- self_duration: SEALED, NOT YET SCORED — learner 6826.0 vs baseline 7430.7; no error is computed here, experiments/prophecy/self_forecast.py --score owns that arithmetic
- self_degraded: SEALED, NOT YET SCORED — learner 0.7778 vs baseline 0.3284; no error is computed here, experiments/prophecy/self_forecast.py --score owns that arithmetic
- self_step_fail: SEALED, NOT YET SCORED — learner 0.2222 vs baseline 0.2222; no error is computed here, experiments/prophecy/self_forecast.py --score owns that arithmetic

Needs correction: **yes** — 4 prediction(s) still open at board time — self_forecast --score runs earlier in the same 09:00 batch, so an open row here means the board was built before it or the scorer refused

### World forecasts

Source(s): `experiments/prophecy/prophecy_ledger.jsonl`

- MAE (mean absolute error of the point forecast), excluding pairs where learner and baseline were sealed EXACTLY equal — the rule experiments/prophecy/scoreboard.py uses, so this number is the one in PROPHECY_SCOREBOARD.md: learner 1.4311 vs baseline 1.84, learner closer in 17/51
- MAE, excluding pairs equal to 3 decimals as well: learner 1.8715 vs baseline 2.4062, learner closer in 17/39. This is the honest head-to-head — the 12 near-ties the first rule keeps are pairs where the learner IS the baseline to display precision, and they pull both means toward each other.
- Brier (mean squared error of a stated probability): NOT DEFINED for world_next. experiments/prophecy/world_forecast.py seals a point value, not a probability, and experiments/prophecy/scoreboard.py:62 PROB_KINDS does not contain world_next. A 0/1 direction hit-rate printed under the word Brier would be the row-7 mislabel again, so this row prints the absence instead of a number.
- sealed this morning (2026-09-18): 6, of which 4 equal the baseline to 3 decimals
- scored this morning: 6
- sealed all time: 70, of which 24 equal the baseline to 3 decimals and only 8 are equal exactly — the 16 in between are counted as live comparisons by scoreboard.py's exact-equality _is_degenerate()
    equal to 3 dp: CLIMATE_GLOBAL_RISK_REVIEW::climate_risk_score learner 2.99955 vs baseline 3.0
    equal to 3 dp: CLIMATE_GLOBAL_RISK_REVIEW::co2_annual_increase learner 1.600002 vs baseline 1.6
    equal to 3 dp: CLIMATE_GLOBAL_RISK_REVIEW::co2_ppm_current learner 426.080003 vs baseline 426.08
    equal to 3 dp: CLIMATE_GLOBAL_RISK_REVIEW::co2_ppm_year_ago learner 424.480001 vs baseline 424.48

Needs correction: **yes** — 4/6 forecasts sealed this morning are the baseline to 3 decimals — EWMA on a near-flat series is persistence with a rounding tail, and exact-equality degeneracy does not catch it

### Data freshness

Source(s): `memory/measurement_honesty_latest.json`, `memory/daily_tier.jsonl`

- k1 0.6826 — share of goal weight whose axis is MEASURED and names the external observation that measured it
- k1_fresh 0.0599 — of that, the share dated within 30 days: 10.0 of 167.0 total weight (114.0 measured)
- undated weight 18.0 — counts toward k1, is neither fresh nor stale, only unaudited
- oldest dated observation: ENERGY_REVIEW at 2087.0 days
- daily tier, latest observation date 2026-09-18: 57 indicators carry a row dated that day; 4 changed value against that indicator's most recent earlier dated row (share 0.0702), 53 are identical, 0 have no earlier row to compare

Needs correction: **yes** — k1_fresh 0.0599 < 0.1; moved share 0.0702 < 0.1 — the daily tier is recording the same numbers again, so the world loop has almost nothing to learn from

### Local brain alive

Source(s): `memory/llm_provenance.jsonl`

- counted over rows of memory/llm_provenance.jsonl whose ts falls on the UTC day 2026-09-18
- local 41 · cloud 94 · local share 0.3037
    Groq: 64
    local:cortex-l1b-3b:latest: 24
    OpenRouter: 24
    local:qwen3:8b: 13
    local:qwen2.5:3b: 4
    Gemini: 3
    NVIDIA-Kimi: 3

Needs correction: **no** — local share 0.3037 >= 0.25

---

Thresholds this board uses to answer *needs correction*, declared in `tools/daily_board.py` rather than buried in a condition:

- `FRESH_K1_FLOOR = 0.1` · `MOVED_SHARE_FLOOR = 0.1` · `LOCAL_SHARE_FLOOR = 0.25` · `SELECTIVITY_FLOOR = 0.1` · `EQ_DECIMALS = 3`

Regenerate by hand: `venv\Scripts\python.exe tools/daily_board.py --write`.

The block below is what tomorrow's board reads for its *yesterday* column. It is written by this board about itself and is never recomputed by the reader.

```json machine
{
 "date": "2026-09-18",
 "generated_utc": "2026-09-18T06:21:40.933229+00:00",
 "rows": {
  "t1": "verdict FAIL · success-rate difference on-off = -0.0156 (95% CI [-0.125, 0.0938], n=64)",
  "probe": "best layer 35 · probe accuracy real 0.99 / control 0.4067 / selectivity (real - control) 0.5833",
  "selfmodel": "4 self-prediction(s) sealed for last night, none scored yet (self_failure, self_duration, self_degraded, self_step_fail); actual duration 6171.5 s",
  "world": "MAE (mean absolute error) learner 1.4311 vs naive-persistence baseline 1.84 over n=51 scored, exact ties excluded; 1.8715 vs 2.4062 over n=39 with ties to 3 decimals also excluded · Brier NOT DEFINED for this row",
  "fresh": "k1_fresh 0.0599 (share of goal weight resting on an observation no older than 30 days) · 4/57 daily indicators moved",
  "local": "41 local:* answers of 135 logged since 00:00 UTC (count of rows whose backend starts with 'local:'), 94 cloud"
 },
 "status": {
  "t1": "OK",
  "probe": "OK",
  "selfmodel": "OK",
  "world": "OK",
  "fresh": "OK",
  "local": "OK"
 }
}
```

