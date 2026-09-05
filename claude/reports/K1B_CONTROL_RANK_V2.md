# K1b ranking eval — k1b_control

**K=4 distractors, chance = 0.20, batch = 1** -- pre-registered at 2026-09-05T05:15:37: batch 10 did not fit; rule 2
MIN_BUCKET=30, band=0.25
pool 173 distinct · items 223 · unscorable 23 · widened 15
wall 3422s · method unbatched

## UNSEEN — adapter — THIS IS THE VERDICT

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 180 | 0.2111 | [0.1556, 0.2722] | AT CHANCE |
| sig02_approved_with_impact | 27 | 0.0000 | - | UNRESOLVABLE (n<30) |

## UNSEEN — base (the same candidates, adapter disabled)

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 180 | 0.2667 | [0.2056, 0.3333] | ABOVE CHANCE |
| sig02_approved_with_impact | 27 | 0.6667 | - | UNRESOLVABLE (n<30) |

## SEEN — memorisation check, NOT a result

| stratum | n | accuracy | 95% CI | verdict |
|---|---|---|---|---|
| sig01_plain | 5 | 0.0000 | - | UNRESOLVABLE (n<30) |
| sig02_approved_with_impact | 11 | 0.4545 | - | UNRESOLVABLE (n<30) |

## SECONDARY: mean NLL of the true target
**Distributional gain, not mapping.** A negative control trained on deranged pairs improved this by +1.2204 nats while learning no mapping at all. It is here for continuity with the old report and must not be read as evidence of learning.

| stratum | n | base NLL | adapter NLL | delta |
|---|---|---|---|---|
| sig01_plain | 180 | 3.9541 | 2.7337 | +1.2204 |
| sig02_approved_with_impact | 27 | 2.1852 | 1.6265 | +0.5587 |

## How to read this
- Chance is 0.20. AT CHANCE means the adapter cannot tell the true target from 4 real alternatives drawn from the same pool.
- Every candidate comes from the SAME target distribution, so house style cannot move this number. That is the whole point of replacing NLL.
- UNRESOLVABLE is the corpus being too small to grade that bucket.
- 23 item(s) were unscorable and are listed, not dropped: [(11, 'stratum_too_small_for_k'), (13, 'stratum_too_small_for_k'), (17, 'stratum_too_small_for_k'), (18, 'stratum_too_small_for_k'), (37, 'stratum_too_small_for_k'), (39, 'stratum_too_small_for_k'), (43, 'stratum_too_small_for_k'), (44, 'stratum_too_small_for_k'), (68, 'stratum_too_small_for_k'), (69, 'stratum_too_small_for_k')]