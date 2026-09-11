# PROPHECY SCOREBOARD — CORTEX's own sealed predictions, scored
Generated 2026-09-11T09:00:04.448112+00:00 · ledger events 1717 · chain VALID · head b2a3137b6ecd

Learner = the self-observing predictor. Baseline = the control that does not look at
recent self-state. Climatology = the constant base rate over the scored set. Lower is better.
Brier for probabilities, MAE for numbers. Degenerate = learner and baseline sealed the same
number: counted, not compared.

| kind | rule | scored | degen. | compared | learner | baseline | climatology | learner wins | last-30 learner | last-30 baseline | verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| axis_next | mae | 748 | 620 | 128 | 18.5941 | 8.4399 |  | 12/128 | 26.568 | 15.177 | baseline holds |
| composer_series | mae | 2 | 2 | 0 | None | None |  | 0/0 | None | None | baseline holds |
| self_degraded | brier | 1 | 0 | 1 | 0.1975 | 0.5562 | 0.0 | 1/1 | 0.1975 | 0.5562 | LEARNER BEATS BASELINE |
| self_duration | mae | 1 | 0 | 1 | 194.6 | 1316.2 |  | 1/1 | 194.6 | 1316.2 | LEARNER BEATS BASELINE |
| self_failure | brier | 54 | 0 | 54 | 0.1644 | 0.3279 | 0.2006 | 42/54 | 0.148 | 0.285 | LEARNER BEATS BASELINE |
| self_step_fail | brier | 1 | 0 | 1 | 0.605 | 0.2178 | 0.0 | 0/1 | 0.605 | 0.2178 | baseline holds |
| world_next | mae | 5 | 1 | 4 | 0.0522 | 0.075 |  | 1/4 | 0.0522 | 0.075 | LEARNER BEATS BASELINE |

Open (sealed, not yet matured): axis_next 12, composer_series 1, goal_axis_next 50, goal_next 6, self_degraded 1, self_duration 1, self_failure 2, self_step_fail 1, world_next 11

Read-only over experiments/prophecy/prophecy_ledger.jsonl. Regenerate: `venv\Scripts\python.exe experiments/prophecy/scoreboard.py --write`.
