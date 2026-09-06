# PC4 PART D2 — REPLAY, WEIGHT, AND A HELD-OUT SET
### 6 September 2026. Pre-registration committed separately and BEFORE this run: `claude/reports/PC4_PARTD2_PREREG.md`, commit `697a028`.

## Metadata

| | |
|---|---|
| **command** | `PYTHONIOENCODING=utf-8 CUDA_VISIBLE_DEVICES="" OMP_NUM_THREADS=1 venv_train/Scripts/python.exe -u tools/pc4_partd2.py --rounds 20 --k 32 --pretrain-steps 8000 --lr 3e-4 --out claude/reports/PC4_PARTD2.json --dump-samples claude/reports/PC4_PARTD2_samples.jsonl` |
| **script sha256 at run time** | `74c380e1f1c772f0cc6dcc59f7f10d5c89d920685e29401a25bde3874e211343` (14,614 bytes) |
| **git commit at run time** | `697a028686fc99d4d5c5b2011a9936e849555edb` — the pre-registration commit |
| **venv** | `venv_train` — `C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\venv_train\Scripts\python.exe` |
| **python / torch** | 3.12.10 / 2.7.1+cu118 |
| **threads** | **1**, pinned in code, not by the environment |
| **device** | CPU. `CUDA_VISIBLE_DEVICES=""`; A3 held the GPU throughout and was not touched. |
| **started / ended** | 2026-09-06 16:24:49Z → 16:29:56Z (5 min 07 s) |
| **start model** | **A fresh 8,000-step pretrain, not a checkpoint file** — same procedure and seed as D, and it selected the same checkpoint: **step 2250, in-range 0.8333**. |
| **seed** | 20260906 |
| **guard tests** | `12 passed in 5.07s` under `venv_train`, **0 skipped, 0 failed** |
| **raw dump** | `claude/reports/PC4_PARTD2_samples.jsonl` — 91,392 records, 16 MB |

## Results — main arm

```
 round  explore  P(10+2)  in-range   leak   buffer  HELD-OUT
     0  0.0078   0.0000    0.8333   0.0185      1    0.0417
     1  0.0000   0.0000    0.7667   0.0170      1
     2  0.0234   0.0000    0.8000   0.0180      4
     3  0.0234   0.0000    0.8333   0.0161      7
     4  0.0078   0.0000    0.8333   0.0199      8
     5  0.0000   0.0000    0.8333   0.0170      8    0.0312
     6  0.0234   0.0000    0.8333   0.0199     11
     7  0.0078   0.0000    0.8333   0.0170     12
     8  0.0391   0.0312    0.8333   0.0147     17
     9  0.0312   0.0000    0.8000   0.0137     21
    10  0.0156   0.0000    0.8000   0.0114     23    0.0104
    11  0.0078   0.0000    0.8000   0.0152     24
    12  0.0156   0.0000    0.8333   0.0194     26
    13  0.0156   0.0000    0.8333   0.0180     28
    14  0.0078   0.0000    0.8333   0.0161     29
    15  0.0000   0.0000    0.8333   0.0180     29    0.0104
    16  0.0078   0.0000    0.8333   0.0133     30
    17  0.0156   0.0000    0.8333   0.0152     32
    18  0.0156   0.0000    0.8333   0.0147     34
    19  0.0234   0.0000    0.8000   0.0128     37
    20  0.0234   0.0000    0.8000   0.0137     40    0.0208
```

## Results — control (in-range prompts only)

```
 round  in-range   leak   buffer  HELD-OUT      round  in-range   leak   buffer  HELD-OUT
     0   0.8333  0.0204      0     0.0417          11   0.8000  0.0152      0
     1   0.7667  0.0189      0                     12   0.8333  0.0170      0
     2   0.8000  0.0152      0                     13   0.8333  0.0180      0
     3   0.8333  0.0180      0                     14   0.8333  0.0180      0
     4   0.8333  0.0223      0                     15   0.8333  0.0152      0    0.0000
     5   0.8333  0.0170      0     0.0312          16   0.8333  0.0152      0
     6   0.8333  0.0189      0                     17   0.8333  0.0161      0
     7   0.8333  0.0189      0                     18   0.8333  0.0147      0
     8   0.8333  0.0152      0                     19   0.8000  0.0156      0
     9   0.8000  0.0166      0                     20   0.8000  0.0166      0    0.0208
    10   0.8000  0.0156      0     0.0104
```

The control's buffer stays at 0 for all 21 rounds, and `first_correct_12 = None`: it
never produced a correct answer above ten, on any prompt, at any point.

## PRIMARY METRIC — and the comparison that decides it

`P(correct | held-out OOR)`, over 8+5, 10+3 and 9+5, K = 32 each (96 samples):

```
round      0        5       10       15       20
main    0.0417   0.0312   0.0104   0.0104   0.0208     = 4, 3, 1, 1, 2 of 96
control 0.0417   0.0312   0.0104   0.0000   0.0208     = 4, 3, 1, 0, 2 of 96
```

**At round 20 the main arm scores 2/96 and the control scores 2/96.** At round 0 they
are equal by construction — same warm start, same evaluation seed. At rounds 5, 10 and
20 they are equal by outcome. At round 15 they differ by one sample.

The two arms are not the same model — at round 20 the main arm's two hits are on 9+5
and the control's are on 8+5 and 9+5, so the aggregate coincides while the detail does
not. **The point stands: twenty rounds of reward, a replay buffer that reached 40
retained successes, and a reward mass fixed at 20% of every batch produced no
advantage over a model that was never shown an out-of-range prompt at all.**

## The greedy answers — thirty of thirty

Every held-out prompt, every evaluation round, both arms:

```
30 greedy evaluations   all exactly 10 marks   none correct
```

`8+5 = 13`, `10+3 = 13`, `9+5 = 14`, and the model says ten. Every time. This is the
same clamp Part A2 measured at 369 checkpoints and Part C reproduced inside a
representation built to remove it — now measured after the incentive was added, the
successes were retained, and the signal was given a hundred times the weight it had in
D. **It did not move.**

## Scoring the pre-registration

> "P(correct|held-out OOR) > 0.5 at round 20: Claude P = 0.45; leakage stays under
> threshold: P = 0.7."

| claim | P | outcome |
|---|---|---|
| P(correct \| held-out OOR) > 0.5 at round 20 | 0.45 | **NO — 0.0208**, and the control matched it exactly |
| leakage stays under threshold | 0.70 | **YES** — max 0.0199 against a 0.0685 threshold |

The first was not a near miss. I put 45% on a number that came in at 2%, and the arm
that was supposed to demonstrate the effect was indistinguishable from the arm designed
to show its absence.

## Leakage — no reward hacking, and further from it than in D

```
main    baseline 0.0185   threshold 0.0685   max observed 0.0199
control baseline 0.0204   threshold 0.0704   max observed 0.0223
```

Multiplying the reward mass by a hundred did not tempt the model toward length even
slightly. The bonus for long correct answers is real and the model never went after it
the cheap way — because, on the evidence of everything above, it never went after it at
all.

## What D2 establishes, and what it does not

**Establishes.** D's null was not a budget artefact. D's diagnosis — "each rewarded
out-of-range sample was 0.2% of a batch, twenty steps cannot use that" — was a
reasonable reading and it is now **falsified**. At 20% mass with replay, across 20
rounds, the model is exactly where the control is. Whatever holds the clamp in place, it
is not the size of the gradient signal.

**Does not establish.** That reward cannot work at all. One SFT step per round is still
20 optimiser steps; a genuinely different regime — hundreds of steps, or a policy-gradient
objective rather than weighted SFT — remains untested, and D2 says nothing about it.
What D2 removes is the specific explanation D offered for its own null.

**One honest limitation of the primary metric.** The held-out set is three prompts and
96 samples, so its resolution is 1/96 ≈ 0.0104. The differences being discussed here —
2/96 against 2/96, 1/96 against 0/96 — are one or two samples wide. That is enough to
say the effect is not large, and not enough to say it is exactly zero.

## `11+3` — excluded, as declared before the run

Not evaluable: the input vocabulary covers 0..10 and there is no symbol for eleven, so
the model cannot be shown the question. Adding one would change `V`, the model's shape,
and therefore the warm start, which this brief pins as "same as D". Reported here rather
than scored as a zero, and a guard test asserts it stays that way — if the vocabulary
ever widens, the test fails and forces the prompt back into the metric.

## Verification that the held-out set stayed held out

```
HELD-OUT prompts appearing in the reward dump: 0   (must be 0)
main out-of-range samples in the dump: 2,688   correct: 40
```

Checked against the raw evidence file rather than against the code: no record in the
91,392-line dump has `(a, b)` in the held-out set. The primary metric measures
generalisation, not recall.

**Second 16 MB samples file.** `PC4_PARTD_samples.jsonl` and `PC4_PARTD2_samples.jsonl`
are 32 MB of permanent repository weight between them, and in both cases the part worth
reading is the ~2,700 out-of-range records out of 91,392. Flagging it again rather than
letting it accumulate quietly.
