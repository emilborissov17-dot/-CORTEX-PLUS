# SANDBOX BENCH — causal learning in a world with hidden structure
5 worlds (seeds 1000+), 400 observational rows, 100 held-out interventions each, 10 variables, non-linear mechanisms, collider + mediator + confounder forced.

## T8 — observational training, interventional test
| learner | direction acc (moving vars) | MAE (sd units) | false-move on non-descendants |
|---|---:|---:|---:|
| naive_correlation | 0.7766 | 0.3531 | 0.8073 |
| adjusted_regression | 0.6834 | 0.2932 | 0.5962 |
| anm_causal | 0.6863 | 0.2348 | 0.3834 |
| persistence | 0.0 | 0.1973 | 0.0 |

Graph recovered by anm_causal: recall 0.3052, precision 0.4806.

## T6 — credit: which single intervention moves the target most (hit-rate, 20 targets/world)
| naive_correlation | adjusted_regression | anm_causal | random |
|---:|---:|---:|---:|
| 0.44 | 0.34 | 0.44 | 0.1 |

## T6A — the SAME credit questions, asked again after the T12 interventions
Identical targets, candidate values and ground truth as T6 above; the only difference is 20 self-chosen interventions of the learner's own.

| anm_causal before acting | anm_causal after acting | naive_correlation | random |
|---:|---:|---:|---:|
| 0.44 | 0.66 | 0.44 | 0.1 |

## T12 — action -> consequence -> revision (MAE on a fixed held-out set, per round)
MAE by round:          0:0.2296  1:0.1749  2:0.1538  3:0.1372  4:0.1365  5:0.1351
graph recall by round: 0:0.305  1:0.432  2:0.483  3:0.556  4:0.575  5:0.615

## Verdict (pre-registered rules)

- T8: **FAIL**
- T6: **FAIL**
- T12: **PASS**
- T6A: **PASS**
- rule: **pre-registered in bench.py docstring, 10 Sep 2026, before the first run**

## Reading (written after the run, 10 Sep 2026 — the rules above were written before it)

- **T8 FAIL, and the failure is the finding.** From observation alone NO learner beats
  "nothing changes" on MAE (persistence 0.197; the best learner 0.235). The naive
  correlational learner has the highest direction accuracy (0.78) because it moves
  EVERYTHING — 81% of non-descendants moved falsely. The causal learner halves that
  (0.38) but pays in direction accuracy (0.68). Observation buys the skeleton, not the
  arrows: graph recall 0.31 from 400 rows. This is point 5 of the definition in
  numbers: "not correlation, but intervention — this requires action, not only
  observation."
- **T6 FAIL (tie at 0.44 vs the naive learner; random 0.10).** Credit assignment from
  observation alone is no better than following correlations.
- **T6A PASS — and this is the answer to "does credit learn from action too?".**
  The same twenty credit questions per world, same targets, same candidate values, same
  Monte-Carlo ground truth; the only change is that the learner has spent 20
  interventions of its own choosing first. Hit-rate 0.44 -> 0.66 (random 0.10). So the
  answer is yes: credit is learned from action, and by the same mechanism as structure —
  the intervention re-orients the edges, and a correctly oriented graph is what "which
  of these nine would move the target most" needs. Per seed: 0.20->0.60, 0.45->0.65,
  0.35->0.70, **0.75->0.60**, 0.45->0.75. Four of five improve; seed 1003 gets WORSE,
  and it is the one where observation alone had already scored highest — acting is not
  a monotone improvement per world, only in the mean of five.
- Price of T6A: exactly 20 interventions x 50 rows = 1000 interventional samples, the
  learner's own budget (`world.spent()` reads 350 interventions per world, but 330 of
  those are the GRADER establishing ground truth — do not read that number as the
  learner's cost).

- **T12 PASS.** Twenty self-chosen interventions (the least-known edges first): MAE
  0.230 -> 0.135, BELOW persistence after the second round; graph recall 0.31 -> 0.62,
  reversed edges -> 0-1. Acting taught the learner what observing could not.
  That is action -> consequence -> revised world model (points 5, 8, 12), inside the
  wall of 31 July, with ground truth.
- What this does NOT show: any of this on the real world; any neural learner; the
  learner is a hand-built non-neural causal learner (partial-correlation skeleton,
  HSIC-oriented additive-noise edges, forward simulation). It is the floor the next
  learner must beat.
- **One number does not reproduce across machines: `anm_causal` direction accuracy.**
  Re-run on the local machine (10 Sep 2026): 0.6863, where the first run reported 0.675.
  Every other figure in this report matched to four decimals and all four verdicts are
  unchanged. Cause, measured: 391 of the 1635 scored pairs have a predicted shift below
  1e-3 sd units, so their SIGN is decided by float noise in the ridge solve and a
  different BLAS flips a handful of them. Direction accuracy on a learner that leaves
  non-descendants exactly at the mean is a fragile metric; MAE and the false-move rate
  are not, and T8 misses its rule by 0.24 — nowhere near the boundary. Do not tune on it.
- Cost: ~12 s CPU for 5 worlds. Reproduce: `venv\Scripts\python.exe experiments\sandbox\bench.py --seeds 5 --write`.
  `--write` regenerates the tables above and carries this Reading section across
  unchanged; before T6A was added it deleted it silently.
