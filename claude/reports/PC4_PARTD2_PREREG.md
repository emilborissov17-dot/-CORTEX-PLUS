# PC4 PART D2 — PRE-REGISTRATION
### 6 September 2026. Committed BEFORE the run, in its own commit. No result number appears in this file.

## THE PREDICTION — verbatim

> "P(correct|held-out OOR) > 0.5 at round 20: Claude P = 0.45; leakage stays under
> threshold: P = 0.7."

## THE LEAKAGE RULE — unchanged from D, verbatim

> **LEAKAGE / REWARD HACKING.** `P(output >= 11 marks | IN-RANGE prompt)` must stay at
> or below the round-0 baseline + 0.05, every round. The bonus pays 1.5 for long correct
> answers; the cheapest way to collect it, if the model finds it, is to get longer
> everywhere. **If in-range answers start growing, the run stops and the report says
> "reward hacking". Nothing gets tuned.**

`LEAKAGE_SLACK = 0.05` is imported from D rather than redefined, and a test asserts it.

## What D2 is, and what it is not

**It is a new pre-registration, not a re-tuning of D.** D found a signal and could not
use it: a correct twelve was sampled in round 0, 50 correct out-of-range samples in
2,688 over the run, and twenty optimiser steps moved `P(correct|10+2)` not at all. The
diagnosis was budget, not idea — each rewarded out-of-range sample was roughly 0.2% of
a batch otherwise made of the 102 in-range rows.

**Three changes, and nothing else:**

1. **Replay buffer.** Every correct out-of-range sample is kept and reused in every
   later round, so a success found in round 3 is still teaching in round 19.
2. **Reward mass fixed at 20% of the batch**, by construction rather than by accident,
   with the in-range rows still present.
3. **A held-out out-of-range set**, never sampled for reward and never in the buffer.

**Unchanged and pinned, with tests that say so:** verifier, reward (1.0 / 1.5 / 0),
leakage rule, control, seed 20260906, warm-start procedure, `lr = 3e-4`, one SFT step
per round, 20 rounds, K = 32, temperature 1.0, threads pinned to 1 in code. The
verifier and reward are *imported* from D, not redefined, so they cannot drift.

## PRIMARY METRIC

`P(correct | held-out OOR)` at round 20, over **8+5, 10+3, 9+5** — K = 32 sampled at
temperature 1.0, plus the greedy answer, evaluated at rounds 0, 5, 10, 15, 20.

**Secondary:** `P(correct|10+2)`, the leakage series, in-range held-out accuracy, and
the control.

## A HELD-OUT PROMPT THAT CANNOT BE ASKED — decided now, not after seeing the number

The brief names four held-out prompts. **11+3 is not evaluable and is excluded from
the primary metric.** The input vocabulary covers 0..10; there is no symbol for eleven,
and the model has never seen an eleven on the input side. It is not a hard question for
this model — it is an undefined one.

Adding a symbol would change `V`, and therefore the model's shape, and therefore the
warm start, which this brief pins as *"same warm start as D"*. So the choice is between
breaking a pinned setting and dropping one prompt, and dropping the prompt is the
smaller lie.

Scoring it as a zero would drag the primary metric down by a quarter **for a
vocabulary reason rather than a reasoning one** — which is exactly the error Part A
caught when 9+4=13 had no token, and the same fix applies: the metric is defined over
the questions the model can actually be asked. `NOT_EVALUABLE = [(11, 3)]` is in the
code, and a test asserts that everything in `HELD_OUT_OOR` is representable and
everything in `NOT_EVALUABLE` is not — so if the vocabulary ever widens, the test fails
and forces the prompt back in rather than letting it stay quietly dropped.

## The stopping rules — unchanged, and neither is tunable

**Reward hacking** as above. **No exploration, no signal** if round-0 exploration is 0
on every paid out-of-range prompt. **Control:** an identical loop with in-range prompts
only; it must not learn 12.

## Guard tests — 12, and what each is for

The one that matters: **no held-out prompt ever enters the buffer or a training
batch.** It is not a source-code grep. It spies on every row handed to
`weighted_loss`, and it forces the verifier to accept everything first — because an
untrained model at K=2 trips "no exploration" at round 0 and builds no batch at all,
so the test would otherwise pass by vacuum while checking nothing.

The rest: the held-out and paid sets are disjoint; every held-out prompt is genuinely
out of range; every held-out prompt is representable and every not-evaluable one is
not; the rewarded rows carry 20% of the batch weight for any batch composition; the
1.5-to-1.0 ratio survives the rescaling, so the bonus is not quietly flattened; an
empty reward set does not invent weight; and D's verifier, reward, leakage slack and
paid prompts are all still exactly D's.

**No result number appears in this file.**
