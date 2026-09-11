# COUNTRY BENCH — learning from a world that does not move

79 countries present in BOTH V-Dem (data/vdem_cache) and OWID energy (data/energy),
features from the energy dataset only: log_energy_per_capita, log_gdp_per_capita, renewables_share_energy, log_elec_per_capita.
Leave-one-country-out: every number below is a prediction for a country the model never saw.
MAE on a 0–1 index; lower is better. `closer` = countries where the learner beat the mean baseline.

| target | baseline (mean) | kNN k=5 | ridge, 4 features | ridge, energy only | n |
|---|---:|---:|---:|---:|---:|
| v2x_rule | 0.2797 | 0.1392 (61 closer) | 0.171 (59 closer) | 0.2456 (51 closer) | 79 |
| v2x_corr_inv | 0.2739 | 0.1339 (60 closer) | 0.1453 (64 closer) | 0.208 (56 closer) | 79 |
| v2x_freexp_altinf | 0.2676 | 0.1838 (53 closer) | 0.1987 (56 closer) | 0.2702 (44 closer) | 79 |

Reading: if a learner's MAE is below the baseline and `closer` is well above n/2, knowledge about
how wealth and energy relate to institutions TRANSFERS to countries it never saw — point 1 on
data that never changed. The energy-only column is the 'knowing one cause' test.
