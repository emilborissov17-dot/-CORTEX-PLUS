# CROSS-SERIES BENCH — does knowing the others help? (E1, points 1 and 3 on the moving world)

_2026-09-11T17:23:29Z · 60 daily series, 4 usable (>= 40 points) · lags 3 · ridge λ=1.0_

| target | n | persistence | EWMA | ridge own lags | ridge ALL lags | all closer than persistence |
|---|---:|---:|---:|---:|---:|---:|
| markets.gld_adjclose | 473 | 4.108732 | 4.124925 | 4.21708 | 4.343639 | 207/473 |
| markets.spy_adjclose | 473 | 4.358262 | 4.376952 | 4.483162 | 4.83259 | 188/473 |
| markets.uup_adjclose | 473 | 0.090578 | 0.090644 | 0.092061 | 0.096517 | 208/473 |
| quakes.quake_m45_count | 701 | 8.479315 | 7.240664 | 8.144364 | 8.577727 | 382/701 |

## Few examples — rows the model may see (MAE ridge ALL vs persistence)

| target | k=10 | k=20 | k=40 | k=80 |
|---|---:|---:|---:|---:|
| markets.gld_adjclose | 6.838403 ✗ | 5.968294 ✗ | 5.235387 ✗ | 4.917018 ✗ |
| markets.spy_adjclose | 7.490338 ✗ | 6.509196 ✗ | 5.571585 ✗ | 5.304876 ✗ |
| markets.uup_adjclose | 0.155254 ✗ | 0.134126 ✗ | 0.112751 ✗ | 0.10644 ✗ |
| quakes.quake_m45_count | 13.886826 ✗ | 13.74983 ✗ | 11.837104 ✗ | 10.601092 ✗ |

## Transfer — weights fitted on A, judged on B against persistence

| A -> B | transfer MAE | persistence MAE | beats |
|---|---:|---:|---|
| markets.gld_adjclose -> markets.spy_adjclose | 4.45555 | 4.358262 | no |
| markets.gld_adjclose -> markets.uup_adjclose | 0.092587 | 0.090578 | no |
| markets.gld_adjclose -> quakes.quake_m45_count | 8.838805 | 8.479315 | no |
| markets.spy_adjclose -> markets.gld_adjclose | 4.186174 | 4.108732 | no |
| markets.spy_adjclose -> markets.uup_adjclose | 0.091835 | 0.090578 | no |
| markets.spy_adjclose -> quakes.quake_m45_count | 9.030784 | 8.479315 | no |
| markets.uup_adjclose -> markets.gld_adjclose | 4.209878 | 4.108732 | no |
| markets.uup_adjclose -> markets.spy_adjclose | 4.460601 | 4.358262 | no |
| markets.uup_adjclose -> quakes.quake_m45_count | 9.245259 | 8.479315 | no |
| quakes.quake_m45_count -> markets.gld_adjclose | 4.465626 | 4.108732 | no |
| quakes.quake_m45_count -> markets.spy_adjclose | 5.132676 | 4.358262 | no |
| quakes.quake_m45_count -> markets.uup_adjclose | 0.105383 | 0.090578 | no |

## E2 — concepts: series that move together, used as one feature (point 4)

| target | concept (found on the training window, named by its members) | own-lags MAE | concept MAE | survives |
|---|---|---:|---:|---|
| markets.gld_adjclose | concept(markets.gld_adjclose)={-markets.uup_adjclose} | 4.21708 | 4.209964 | YES |
| markets.spy_adjclose | — no series moves with it | 4.483162 | 4.483162 | no |
| markets.uup_adjclose | concept(markets.uup_adjclose)={-markets.gld_adjclose} | 0.092061 | 0.092186 | no |
| quakes.quake_m45_count | — no series moves with it | 8.144364 | 8.144364 | no |

## E4 — calibrated uncertainty: 80% intervals, judged against what happened (point 7)

| target | ridge ALL coverage | width | persistence coverage | width |
|---|---:|---:|---:|---:|
| markets.gld_adjclose | 0.695 (n=463) | 10.212267 | 0.683 | 9.166994 |
| markets.spy_adjclose | 0.795 (n=463) | 15.145263 | 0.786 | 13.127198 |
| markets.uup_adjclose | 0.862 (n=463) | 0.344588 | 0.849 | 0.313356 |
| quakes.quake_m45_count | 0.795 (n=691) | 20.3546 | 0.829 | 22.992764 |

**Verdict:** ridge on ALL lags beats persistence on 0/4 targets and beats its own-lags twin on 0/4; EWMA beats persistence on 1/4; transfer beats persistence on 0/12 pairs; few-examples wins: k=10: 0/4, k=20: 0/4, k=40: 0/4, k=80: 0/4; concepts found 2, surviving out of sample 1; 80% intervals covered 0.787 of outcomes.

Reading: on daily market closes persistence is a hard baseline (a random walk has no better one-step predictor); a win here must hold for weeks, not one run. USGS counts are not a random walk and are where a lag model should win first. Nothing here is a trade.
