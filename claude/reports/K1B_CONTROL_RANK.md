# K1b ranking eval — k1b_control

**K=4 distractors, chance = 0.20, batch = 1** -- pre-registered at 2026-09-05T05:15:37: batch 10 did not fit; rule 2
MIN_BUCKET=30, band=0.25
pool 173 distinct · items 246 · unscorable 0 · widened 1
wall 3536s · method unbatched

## UNSEEN — adapter — THIS IS THE VERDICT

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 180 | 0.2222 | [0.1611, 0.2833] | AT CHANCE |
| sig02_approved_with_impact | 27 | 1.0000 | - | UNRESOLVABLE (n<30) |
| sig03_experiment_authored | 9 | 0.0000 | - | UNRESOLVABLE (n<30) |

## UNSEEN — base (the same candidates, adapter disabled)

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 180 | 0.2500 | [0.1889, 0.3167] | AT CHANCE |
| sig02_approved_with_impact | 27 | 1.0000 | - | UNRESOLVABLE (n<30) |
| sig03_experiment_authored | 9 | 0.0000 | - | UNRESOLVABLE (n<30) |

## SEEN — memorisation check, NOT a result

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 5 | 0.0000 | - | UNRESOLVABLE (n<30) |
| sig02_approved_with_impact | 11 | 0.6364 | - | UNRESOLVABLE (n<30) |
| sig03_experiment_authored | 1 | 0.0000 | - | UNRESOLVABLE (n<30) |
| sig04_moral_checked | 9 | 1.0000 | - | UNRESOLVABLE (n<30) |
| sig07_dependency_check | 4 | 0.0000 | - | UNRESOLVABLE (n<30) |

## SECONDARY: mean NLL of the true target
**Distributional gain, not mapping.** A negative control trained on deranged pairs improved this by +1.2204 nats while learning no mapping at all. It is here for continuity with the old report and must not be read as evidence of learning.

| stratum | n | base NLL | adapter NLL | delta |
|---|---|---|---|---|
| sig01_plain | 180 | 3.9541 | 2.7337 | +1.2204 |
| sig02_approved_with_impact | 27 | 2.1852 | 1.6265 | +0.5587 |
| sig03_experiment_authored | 9 | 2.9705 | 2.5867 | +0.3838 |

## How to read this
- Chance is 0.20. AT CHANCE means the adapter cannot tell the true target from 4 real alternatives drawn from the same pool.
  (This line said 0.10 and 'nine' when first generated: it was hardcoded to the K=9 default while the run used the pre-registered K=4. The header was right, the footer was stale. Fixed in the generator so it derives from the knobs in force.)
- Every candidate comes from the SAME target distribution, so house style cannot move this number. That is the whole point of replacing NLL.
- UNRESOLVABLE is the corpus being too small to grade that bucket.
- 0 item(s) were unscorable and are listed, not dropped: []
---

# THE VERDICT — the metric is clean, and the control is the null it was meant to be

## PASSED. The control lands AT CHANCE.

```
sig01_plain   n=180   accuracy 0.2222   CI [0.1611, 0.2833]   chance 0.20   AT CHANCE
```

The CI contains 0.20 comfortably. **Under the pre-registered rule this metric is not
contaminated, and runs A and B are unblocked.**

The base model, on the identical candidates: **0.2500, CI [0.1889, 0.3167] — also AT
CHANCE.** The adapter is a hair *lower* than the base and the intervals overlap almost
entirely, which is exactly the shape "trained on deranged pairs, learned no mapping" should
produce.

## THE POINT OF THE WHOLE EXERCISE, IN TWO ROWS

Same adapter. Same 180 examples. Same night.

| metric | sig01_plain, UNSEEN | reads as |
|---|---|---|
| mean NLL of the true target | **+1.2204 nats better** | a large improvement |
| ranking against 4 real alternatives | **0.2222 vs chance 0.20** | nothing at all |

The first number is what an adapter gains by learning the house style of a CORTEX proposal.
The second is what it knows about *which* proposal answers *this* problem. The old metric
could not tell them apart; this one puts them side by side and the gap is the whole finding.

## AN OPEN QUESTION, RESOLVED BY THIS RUN

The probe reported `max_abs_diff = 0.0237` between its unbatched and "batched" passes, and
because the batched pass had fallen back on OOM I flagged that it might be **run-to-run
non-determinism in the model** — which would have put a noise floor under every delta.

**It is not.** The NLL secondary here reproduces the 02:33 eval to four decimal places, in a
separate process three hours later:

```
sig01_plain   base 3.9541 -> adapter 2.7337   delta +1.2204   (both runs, identical)
sig02         base 2.1852 -> adapter 1.6265   delta +0.5587   (both runs, identical)
sig03         base 2.9705 -> adapter 2.5867   delta +0.3838   (both runs, identical)
```

The model is deterministic at this precision. So the 0.0237 came from the items that
genuinely *did* batch before memory ran out — i.e. it is a real batching disagreement, and
rule 2 was right to refuse it. The flag is closed, in the direction that validates the
decision rather than excusing it.

## AN ANOMALY THAT IS NOT ABOUT THE ADAPTER — flag before those buckets grow

```
sig02_approved_with_impact   n=27   base 1.0000   adapter 1.0000
sig03_experiment_authored    n= 9   base 0.0000   adapter 0.0000
sig04_moral_checked (SEEN)   n= 9   base 1.0000   adapter 1.0000
```

**Exactly 1.0 and exactly 0.0, identical for base and adapter.** A number that does not move
when the weights change is a property of the DATA, not of the model: in sig02 the true
target is trivially identifiable from its prompt, and in sig03 it is never identifiable.
Neither is learning.

All three are UNRESOLVABLE at n<30 so none of them touches tonight's verdict. **But sig02 is
at 27 and the corpus grows every night.** When it crosses 30 it will read `ABOVE CHANCE` at
accuracy 1.0 and look like a spectacular result. It must be understood before then, not
after. Likely causes to check, in order: the prompt containing the target verbatim for that
record kind; a length band so distinctive that the true target is the only plausible
candidate; near-duplicate targets in sig03 tying and scoring 0 by the strict-lowest rule.

**This is a corpus finding, and it is the reason strata are reported separately rather than
averaged.** Pooled, these would have vanished into sig01's 180 rows.

## WHAT IS NOW TRUE

- The ranking metric is **not** contaminated by the distributional gain that fooled NLL.
- The control is established as the null model: **0.2222 on sig01**, the number A and B must
  beat, in addition to clearing 0.20.
- Only `sig01_plain` can carry a verdict. That was stated before the run and is unchanged.
- Cost, measured: 2460 forwards, **3536 s wall (59 min)** at 1.44 s/forward — inside the
  1.32–1.57 band predicted from the NLL eval, and within a minute of the 58 min estimate.
