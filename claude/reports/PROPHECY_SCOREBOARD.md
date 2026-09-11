# PROPHECY SCOREBOARD — CORTEX's own sealed predictions, scored
Generated 2026-09-10T09:00:02.555886+00:00 · ledger events 1670 · chain VALID · head d77817fc2142

Learner = the self-observing predictor. Baseline = the control that does not look at
recent self-state. Climatology = the constant base rate over the scored set. Lower is better.
Brier for probabilities, MAE for numbers. Degenerate = learner and baseline sealed the same
number: counted, not compared.

| kind | rule | scored | degen. | compared | learner | baseline | climatology | learner wins | last-30 learner | last-30 baseline | verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| axis_next | mae | 736 | 609 | 127 | 18.7247 | 8.4985 |  | 12/127 | 26.9013 | 15.3437 | baseline holds |
| composer_series | mae | 2 | 2 | 0 | None | None |  | 0/0 | None | None | baseline holds |
| self_failure | brier | 53 | 0 | 53 | 0.1675 | 0.3293 | 0.2029 | 41/53 | 0.148 | 0.2886 | LEARNER BEATS BASELINE |

Open (sealed, not yet matured): axis_next 12, composer_series 1, goal_axis_next 50, goal_next 6, self_degraded 1, self_duration 1, self_failure 2, self_step_fail 1, world_next 6

Read-only over experiments/prophecy/prophecy_ledger.jsonl. Regenerate: `venv\Scripts\python.exe experiments/prophecy/scoreboard.py --write`.
