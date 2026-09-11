# WORLD FORECAST BENCH — learners vs persistence on the indicators that actually move

Rolling one-step-ahead MAE (lower is better). `last_step` is what axis_next does today.
`ewma_fitted` chose its alpha on this indicator's own past; `ewma_transfer` uses the alpha
learned on the OTHER indicators (leave-one-out) — the generality test.

| indicator | n | persistence | last_step | ewma_fitted (α) | ewma_transfer (α) |
|---|---:|---:|---:|---:|---:|
| CLIMATE_GLOBAL_RISK_REVIEW::climate_risk_score | 47 | 0.071429 | 0.142857 | 0.074074 (0.9) | 0.074074 (0.9) |
| CLIMATE_GLOBAL_RISK_REVIEW::co2_annual_increase | 93 | 0.103636 | 0.21375 | 0.110641 (0.9) | 0.110641 (0.9) |
| CLIMATE_GLOBAL_RISK_REVIEW::co2_ppm_current | 93 | 0.105227 | 0.225114 | 0.113872 (0.9) | 0.113872 (0.9) |
| CLIMATE_GLOBAL_RISK_REVIEW::co2_ppm_year_ago | 93 | 0.071818 | 0.169318 | 0.082651 (0.9) | 0.082651 (0.9) |
| CLIMATE_GLOBAL_RISK_REVIEW::forecast_forecast_max_temp_7d | 46 | 1.304878 | 2.57561 | 1.290302 (0.9) | 1.290302 (0.9) |
| CLIMATE_GLOBAL_RISK_REVIEW::forecast_max_temp_7d | 47 | 1.059524 | 1.747619 | 1.038635 (0.7) | 1.043285 (0.9) |

## Verdict

- indicators_that_move: 6
- last_step_beats_persistence: 0/6
- ewma_fitted_beats_persistence: 2/6
- ewma_TRANSFER_beats_persistence: 2/6
- reading: a learner that only ever sees the same indicator is not tested for transfer; the TRANSFER row is the one that speaks to point 1 (generality)
