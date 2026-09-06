# A3 — THE ONE NUMBER
### 6 September 2026 (eval finished 23:31). Copied from `claude/reports/K1B_A3_RANK.md`.

## THE VERDICT, IN ONE LINE

**UNSEEN sig01 adapter 0.2611 [0.1913, 0.3334] vs base 0.2667 [0.1921, 0.3441], delta −0.006, LEARNED=False, BEYOND_TRIVIAL=False; pre-registered rule ≤ 0 → archive-LoRA DEAD, STOP.**

## The verdict block, verbatim

**UNSEEN — adapter** (chance = 0.20, K=4 distractors, batch 1)

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| sig01_plain | 180 | 157 | **0.2611** | [0.1913, 0.3334] | AT CHANCE |
| sig02_approved_with_impact | 27 | 3 | 0.0000 | – | UNRESOLVABLE (3 < 30) |

**UNSEEN — base** (the same candidates, adapter disabled)

| stratum | rows | effective n (pairs) | accuracy | 95% CI | verdict |
|---|---:|---:|---:|---|---|
| sig01_plain | 180 | 157 | **0.2667** | [0.1921, 0.3441] | AT CHANCE |
| sig02_approved_with_impact | 27 | 3 | 0.6667 | – | UNRESOLVABLE (3 < 30) |

**Three reference points — UNSEEN, same items**

| stratum | chance | control | axis rule | LEARNED | BEYOND_TRIVIAL |
|---|---:|---|---|---|---|
| sig01_plain | 0.2000 | 0.2111 [0.1453, 0.2811] | 0.7778 [0.7174, 0.8356] | **False** | **False** |
| sig02_approved_with_impact | 0.2000 | 0.0000 – | 0.2000 – | UNKNOWN | UNKNOWN |

## The pre-registered rule, and where this lands

```
delta <= 0                          -> DEAD, stop
delta > 0.05 AND CI lower bound > 0 -> SIGNAL
```

**delta = 0.2611 − 0.2667 = −0.0056.** Below zero. **DEAD.**

Not marginal, and not a matter of interpretation: the adapter's interval
[0.1913, 0.3334] and the base's [0.1921, 0.3441] overlap almost entirely, and the
adapter's point estimate is the *lower* of the two. Three epochs on the archive corpus
did not move a 3B model's ability to pick the true target out of four real alternatives
drawn from the same pool.

`BEYOND_TRIVIAL=False` is the harder fact. **The axis rule scores 0.7778 [0.7174, 0.8356]**
on the same items — a rule that reads one word of the prompt is three times better than
the fine-tuned model, and the two intervals do not come close to touching.

## The prediction, scored

Pre-registered in `claude/reports/RUN_A3_PREREGISTRATION_6SEP.md`, before the run:

> **A3 UNSEEN sig01 → AT CHANCE, accuracy 0.19–0.27, P(above base with a clean CI) = 0.20.**

**Correct on both halves.** The verdict is AT CHANCE; 0.2611 falls inside the predicted
0.19–0.27 band; and the 20% event — above base with a clean interval — did not occur.

## What this closes

The confound named on 4 September was that Run A landed AT CHANCE after **one** epoch,
so undertraining could not be ruled out. A3 is the same recipe at **three** epochs, same
corpus (`sha256 079a9d14…`), same holdout, same draw. It lands in the same place, one
sample lower.

**Undertraining is ruled out. Archive-LoRA is dead, and the pre-registered rule says
stop — so it stops.**

## Provenance

Eval wall 3312 s · 223 items · 173 distinct pairs · 23 unscorable, listed not dropped ·
`method unbatched`, per pre-registered rule 2 (batch 10 did not fit). The run survived
four deaths and three relaunches on 6 September; the surviving chain started 16:06:30,
training finished 22:35:37, the eval wrote this at 23:31:19.
