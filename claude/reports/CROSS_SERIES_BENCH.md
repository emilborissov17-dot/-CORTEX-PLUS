# CROSS-SERIES BENCH — does knowing the others help? (E1, points 1 and 3 on the moving world)

_2026-09-11T13:16:01Z · 60 daily series, 4 usable (>= 40 points) · lags 3 · ridge λ=1.0_

| target | n | persistence | EWMA | ridge own lags | ridge ALL lags | all closer than persistence |
|---|---:|---:|---:|---:|---:|---:|
| markets.gld_adjclose | 32 | 5.394691 | 5.479247 | 5.281192 | 6.251798 | 11/32 |
| markets.spy_adjclose | 32 | 4.377495 | 4.369189 | 4.914008 | 5.701715 | 10/32 |
| markets.uup_adjclose | 32 | 0.070312 | 0.067074 | 0.078261 | 0.093576 | 11/32 |
| quakes.quake_m45_count | 61 | 7.983607 | 7.203151 | 7.682474 | 8.421585 | 29/61 |

## Few examples — rows the model may see (MAE ridge ALL vs persistence)

| target | k=10 | k=20 | k=40 | k=80 |
|---|---:|---:|---:|---:|
| markets.gld_adjclose | 7.449919 ✗ | 6.763107 ✗ | 6.454663 ✗ | 6.251798 ✗ |
| markets.spy_adjclose | 6.071751 ✗ | 5.617104 ✗ | 5.81215 ✗ | 5.701715 ✗ |
| markets.uup_adjclose | 0.123924 ✗ | 0.115941 ✗ | 0.095364 ✗ | 0.093576 ✗ |
| quakes.quake_m45_count | 11.268954 ✗ | 10.391029 ✗ | 9.022144 ✗ | 8.427115 ✗ |

## Transfer — weights fitted on A, judged on B against persistence

| A -> B | transfer MAE | persistence MAE | beats |
|---|---:|---:|---|
| markets.gld_adjclose -> markets.spy_adjclose | 4.073007 | 4.377495 | YES |
| markets.gld_adjclose -> markets.uup_adjclose | 0.078329 | 0.070312 | no |
| markets.gld_adjclose -> quakes.quake_m45_count | 8.483335 | 7.983607 | no |
| markets.spy_adjclose -> markets.gld_adjclose | 5.749725 | 5.394691 | no |
| markets.spy_adjclose -> markets.uup_adjclose | 0.084556 | 0.070312 | no |
| markets.spy_adjclose -> quakes.quake_m45_count | 8.597055 | 7.983607 | no |
| markets.uup_adjclose -> markets.gld_adjclose | 6.091762 | 5.394691 | no |
| markets.uup_adjclose -> markets.spy_adjclose | 5.124548 | 4.377495 | no |
| markets.uup_adjclose -> quakes.quake_m45_count | 9.724666 | 7.983607 | no |
| quakes.quake_m45_count -> markets.gld_adjclose | 5.647773 | 5.394691 | no |
| quakes.quake_m45_count -> markets.spy_adjclose | 5.017339 | 4.377495 | no |
| quakes.quake_m45_count -> markets.uup_adjclose | 0.093416 | 0.070312 | no |

**Verdict:** ridge on ALL lags beats persistence on 0/4 targets and beats its own-lags twin on 0/4; EWMA beats persistence on 3/4; transfer beats persistence on 1/12 pairs; few-examples wins: k=10: 0/4, k=20: 0/4, k=40: 0/4, k=80: 0/4.

Reading: on daily market closes persistence is a hard baseline (a random walk has no better one-step predictor); a win here must hold for weeks, not one run. USGS counts are not a random walk and are where a lag model should win first. Nothing here is a trade.
