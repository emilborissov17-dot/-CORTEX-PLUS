# K1b ranking eval — k1b_A

**K=4 distractors, chance = 0.20, batch = 1** -- pre-registered at 2026-09-05T05:15:37: batch 10 did not fit; rule 2
MIN_BUCKET=30, band=0.25
pool 173 distinct · items 223 · unscorable 23 · widened 15
wall 3312s · method unbatched

## UNSEEN — adapter — THIS IS THE VERDICT

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| sig01_plain | 180 | 157 | 0.2222 | [0.1585, 0.2905] | AT CHANCE |
| sig02_approved_with_impact | 27 | 3 | 0.0000 | - | UNRESOLVABLE (3 distinct pairs < 30) |

## UNSEEN — base (the same candidates, adapter disabled)

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| sig01_plain | 180 | 157 | 0.2667 | [0.1921, 0.3441] | AT CHANCE |
| sig02_approved_with_impact | 27 | 3 | 0.6667 | - | UNRESOLVABLE (3 distinct pairs < 30) |

## SEEN — memorisation check, NOT a result

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| sig01_plain | 5 | 3 | 0.0000 | - | UNRESOLVABLE (3 distinct pairs < 30) |
| sig02_approved_with_impact | 11 | 8 | 0.5455 | - | UNRESOLVABLE (8 distinct pairs < 30) |

## THREE REFERENCE POINTS — UNSEEN, on the SAME items

`LEARNED` = the adapter's CI is entirely above the CONTROL's. `BEYOND_TRIVIAL` = entirely above the AXIS RULE's. They are separate on purpose: an adapter can beat a model trained on deranged pairs while losing to a rule that reads one word of the prompt.

| stratum | chance | control | axis rule | LEARNED | BEYOND_TRIVIAL |
|---|---:|---|---|---|---|
| sig01_plain | 0.2000 | nan - | 0.7778 [0.7174, 0.8356] | UNKNOWN | False |
| sig02_approved_with_impact | 0.2000 | nan - | 0.2000 - | UNKNOWN | UNKNOWN |

## SECONDARY: mean NLL of the true target
**Distributional gain, not mapping.** A negative control trained on deranged pairs improved this by +1.2204 nats while learning no mapping at all. It is here for continuity with the old report and must not be read as evidence of learning.

| stratum | n | base NLL | adapter NLL | delta |
|---|---|---|---|---|
| sig01_plain | 180 | 3.9541 | 2.6277 | +1.3264 |
| sig02_approved_with_impact | 27 | 2.1852 | 1.5958 | +0.5894 |

## How to read this
- Chance is 0.20. AT CHANCE means the adapter cannot tell the true target from 4 real alternatives drawn from the same pool.
- Every candidate comes from the SAME target distribution, so house style cannot move this number. That is the whole point of replacing NLL.
- UNRESOLVABLE is the corpus being too small to grade that bucket.
- 23 item(s) were unscorable and are listed, not dropped: [(11, 'stratum_too_small_for_k'), (13, 'stratum_too_small_for_k'), (17, 'stratum_too_small_for_k'), (18, 'stratum_too_small_for_k'), (37, 'stratum_too_small_for_k'), (39, 'stratum_too_small_for_k'), (43, 'stratum_too_small_for_k'), (44, 'stratum_too_small_for_k'), (68, 'stratum_too_small_for_k'), (69, 'stratum_too_small_for_k')]