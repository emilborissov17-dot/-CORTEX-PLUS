# CROSS-SERIES BENCH — direction first, then the % step, then (last) the level

_2026-09-11T17:49:56Z · 60 daily series, 4 usable (>= 40 points) · lags 3 · ridge λ=1.0_

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

## STAGE 1 — direction (up/down), against honest baselines

Baselines: always up (markets drift up), momentum (same sign as the last H days), training majority. A win = best model beats the best baseline by >= 2.0 standard errors on n_eff = n / H.

| target | H days | n (eff) | best model hit rate | best baseline hit rate | z | win |
|---|---:|---:|---:|---:|---:|---|
| markets.gld_adjclose | 1 | 473 (473.0) | ewma 0.5455 | train_majority 0.5793 | -1.49 | no |
| markets.gld_adjclose | 5 | 469 (93.8) | ewma 0.5032 | always_up 0.6055 | -2.03 | no |
| markets.gld_adjclose | 20 | 454 (22.7) | ridge_own 0.5154 | always_up 0.652 | -1.37 | no |
| markets.spy_adjclose | 1 | 473 (473.0) | ridge_own 0.5159 | always_up 0.5539 | -1.66 | no |
| markets.spy_adjclose | 5 | 469 (93.8) | ewma 0.5267 | always_up 0.5906 | -1.26 | no |
| markets.spy_adjclose | 20 | 454 (22.7) | ewma 0.4912 | train_majority 0.7048 | -2.23 | no |
| markets.uup_adjclose | 1 | 455 (455.0) | ewma 0.5341 | always_up 0.5275 | 0.28 | no |
| markets.uup_adjclose | 5 | 457 (91.4) | ewma 0.5383 | always_up 0.5186 | 0.38 | no |
| markets.uup_adjclose | 20 | 448 (22.4) | ewma 0.5022 | always_up 0.5201 | -0.17 | no |
| quakes.quake_m45_count | 1 | 657 (657.0) | ewma 0.6895 | always_up 0.4749 | 11.02 | YES |
| quakes.quake_m45_count | 5 | 664 (132.8) | ewma 0.7169 | always_up 0.4804 | 5.45 | YES |
| quakes.quake_m45_count | 20 | 654 (32.7) | ewma 0.711 | always_up 0.5061 | 2.34 | YES |

## STAGE 2 — the size of the step in % of today's value (80% conformal range)

| target | H days | ridge ALL: mean error % | range ±% | covered | EWMA: error % | range ±% | covered |
|---|---:|---:|---:|---:|---:|---:|---:|
| markets.gld_adjclose | 1 | 1.195 | 1.74 | 0.762 | 1.128 | 1.491 | 0.739 |
| markets.gld_adjclose | 5 | 2.741 | 3.886 | 0.771 | 2.57 | 3.493 | 0.736 |
| markets.gld_adjclose | 20 | 5.469 | 8.145 | 0.712 | 5.21 | 7.371 | 0.703 |
| markets.spy_adjclose | 1 | 0.769 | 1.279 | 0.827 | 0.694 | 1.107 | 0.819 |
| markets.spy_adjclose | 5 | 1.688 | 2.965 | 0.841 | 1.565 | 2.616 | 0.824 |
| markets.spy_adjclose | 20 | 3.394 | 5.805 | 0.836 | 3.205 | 5.147 | 0.831 |
| markets.uup_adjclose | 1 | 0.353 | 0.633 | 0.86 | 0.332 | 0.582 | 0.838 |
| markets.uup_adjclose | 5 | 0.778 | 1.364 | 0.843 | 0.708 | 1.216 | 0.828 |
| markets.uup_adjclose | 20 | 1.543 | 3.193 | 0.912 | 1.406 | 2.679 | 0.887 |
| quakes.quake_m45_count | 1 | 38.148 | 55.313 | 0.819 | 33.962 | 49.951 | 0.813 |
| quakes.quake_m45_count | 5 | 49.207 | 60.031 | 0.78 | 41.433 | 54.516 | 0.799 |
| quakes.quake_m45_count | 20 | 50.121 | 67.841 | 0.811 | 44.42 | 54.086 | 0.792 |

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

**Stage:** 2 — direction learned somewhere; the size of the step in % is now the headline. Direction wins: quakes.quake_m45_count@1d, quakes.quake_m45_count@20d, quakes.quake_m45_count@5d (of 12 target×horizon cells).

The exact price is NOT the goal; it stays as the third, hardest table below only so that a model which is right about direction and wrong about size is not mistaken for one that is wrong about everything.

**Verdict:** ridge on ALL lags beats persistence on 0/4 targets and beats its own-lags twin on 0/4; EWMA beats persistence on 1/4; transfer beats persistence on 0/12 pairs; few-examples wins: k=10: 0/4, k=20: 0/4, k=40: 0/4, k=80: 0/4; concepts found 2, surviving out of sample 1; 80% intervals covered 0.787 of outcomes.

Reading: on daily market closes persistence is a hard baseline (a random walk has no better one-step predictor); a win here must hold for weeks, not one run. USGS counts are not a random walk and are where a lag model should win first. Nothing here is a trade.
