# K1b ranking eval — pc_A1

**K=4 distractors, chance = 0.20, batch = 1** -- pre-registered at 2026-09-05T05:15:37: batch 10 did not fit; rule 2
MIN_BUCKET=30, band=0.25
pool 12 distinct · items 120 · unscorable 0 · widened 0
wall 1994s · method unbatched

## UNSEEN — adapter — THIS IS THE VERDICT

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| - | 0 | 0 | - | - | NO DATA |

## UNSEEN — base (the same candidates, adapter disabled)

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| - | 0 | 0 | - | - | NO DATA |

## SEEN — memorisation check, NOT a result

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| pc01_rule | 120 | 120 | 0.2250 | [0.1583, 0.3000] | AT CHANCE |

## THREE REFERENCE POINTS — UNSEEN, on the SAME items

`LEARNED` = the adapter's CI is entirely above the CONTROL's. `BEYOND_TRIVIAL` = entirely above the AXIS RULE's. They are separate on purpose: an adapter can beat a model trained on deranged pairs while losing to a rule that reads one word of the prompt.

| stratum | chance | control | axis rule | LEARNED | BEYOND_TRIVIAL |
|---|---:|---|---|---|---|
| - | - | - | - | - | - |

## SECONDARY: mean NLL of the true target
**Distributional gain, not mapping.** A negative control trained on deranged pairs improved this by +1.2204 nats while learning no mapping at all. It is here for continuity with the old report and must not be read as evidence of learning.

| stratum | n | base NLL | adapter NLL | delta |
|---|---|---|---|---|
| - | 0 | - | - | - |

## How to read this
- Chance is 0.20. AT CHANCE means the adapter cannot tell the true target from 4 real alternatives drawn from the same pool.
- Every candidate comes from the SAME target distribution, so house style cannot move this number. That is the whole point of replacing NLL.
- UNRESOLVABLE is the corpus being too small to grade that bucket.
- 0 item(s) were unscorable and are listed, not dropped: []