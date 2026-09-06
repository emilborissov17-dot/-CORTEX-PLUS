# PC4 PART D — REWARD FOR THE NEW
### 6 September 2026. Everything above the results line was written and committed BEFORE the run.

## What A2 and C left to test

A model trained only on results 0..10 answers **0 of 8** out-of-range questions, at
every one of 369 checkpoints, across three representations and nine seeds. The failure
has one shape: it emits a complete, legal answer meaning ten and stops. Part C showed
the ceiling is not the output encoding — C1 made the correct answer a composition of
symbols the model had emitted hundreds of times, and it still never tried.

What was left is the incentive. **Nothing in 102 examples ever rewarded continuing
past a complete answer**, so the rule induced is "produce the result, then stop" —
correct on every training example and silent about 12.

Part D removes exactly that, and nothing else. **It never shows the model an
out-of-range target.** It samples, verifies with the rule, and pays more for a correct
answer above ten. If the clamp is a missing incentive, this dissolves it. If the model
cannot *sample* a correct 12 in the first place, no reward can teach it one — and that
is a finding, not a failure of the method.

## Which representation — and why it cannot be A2's

The brief says "start from the A2 checkpoint" and also "verify with the RULE (count
marks == a+b)". **Those cannot both be taken literally.** A2's answer is one atomic
symbol: there are no marks to count, and no token for 12 exists at all, so
`P(output >= 11 marks)`, "a correct 12", and the leakage series are all undefined
there.

Every quantity the brief asks for is defined in marks. So Part D runs on the **tally
representation from C2**, warm-started on in-range results 0..10 exactly as A2 was.
That is the reading under which the whole specification is coherent, and it is the
only one.

## The loop

1. **Prompts** — all in-range sums (66 pairs with `a+b <= 10`) *and* the four
   out-of-range sums: 10+2, 7+5, 9+4, 10+4 → results 12, 12, 13, 14.
   **No out-of-range target is ever shown.**
2. **K = 32 completions per prompt at temperature 1.0, sampled, never greedy.**
   Greedy can only ever reproduce the clamp; it would measure nothing and could
   learn nothing.
3. **Verified by the rule** — the completion must be marks only, and exactly `a+b`
   of them. There is no table of answers anywhere in the verifier. Length alone
   would accept twelve of the *wrong* symbol, which is not the answer twelve.
4. **Reward** — correct 1.0; correct *and* `a+b > 10` 1.5; wrong 0.0. The bonus is
   gated on correctness first, so a wrong out-of-range answer never out-earns a
   wrong in-range one — otherwise the model is paid for the attempt, not the result.
5. **One weighted-SFT step** per round on the rewarded samples only, loss × reward,
   with the in-range training set kept in the batch.

## Two settings that are mine, and how they were chosen

**Warm start is selected, not taken at the last step.** Part C measured 81 of 123 C2
checkpoints below 0.5 training accuracy. Starting Part D from whatever the last step
happened to be would make the experiment a lottery on the warm start, so the
checkpoint with the best held-out in-range accuracy is selected. That is model
selection on a validation set, and it is stated rather than buried.

**The SFT step size is calibrated on the control, never on the outcome.** At
`lr = 1e-3` a single weighted step took the control's in-range accuracy from 0.60 to
0.03 — the model was destroyed by round 1 and the loop would have measured nothing.
The brief requires that in-range accuracy "cannot silently drop"; a step size that
drops it loudly fails the same requirement. The calibration series is reported below
and it looks only at in-range stability on the control arm.

## The stopping rules — pre-registered, and neither is tunable

**LEAKAGE / REWARD HACKING.** `P(output >= 11 marks | IN-RANGE prompt)` must stay at
or below the round-0 baseline + 0.05, every round. The bonus pays 1.5 for long correct
answers; the cheapest way to collect it, if the model finds it, is to get longer
everywhere. **If in-range answers start growing, the run stops and the report says
"reward hacking". Nothing gets tuned.**

**NO EXPLORATION.** If round-0 exploration rate is 0 on every out-of-range prompt, the
run stops and the report says **"no exploration, no signal"**. Nothing gets tuned to
make it pass. A reward can only reinforce something the sampler has actually produced;
if nothing correct is ever sampled, the loop has no signal to amplify and saying so is
the result.

**CONTROL.** An identical loop with in-range prompts only. It must not learn 12. It is
asserted in the code and in a test that the control is never handed an out-of-range
prompt — a control that quietly received them would invalidate the entire result while
every number still looked plausible.

## PRE-REGISTERED PREDICTION — verbatim

> "if round-0 exploration >= 1/32 on 10+2 then P(correct|10+2) > 0.5 by round 20;
> P = 0.5"

My own reading of that, recorded now so it cannot be reframed later: the conditional
is doing most of the work. I expect the antecedent to **fail** — a model whose every
greedy answer is the clamp is unlikely to sample twelve marks exactly, in 32 draws,
without ever having emitted eleven. If it does fire, 0.5 is close to a coin flip and
I would not defend it harder than that.

## Guard tests

Fifteen, one per way this could produce a triumphant number for the wrong reason:
the verifier rejecting the right length with the wrong symbols; the 1.5 bonus never
reaching a wrong sample; the control never receiving an out-of-range prompt (checked
by spying on the sampler, not by reading the code); the leakage check firing on a
synthetic rise, and *not* firing just below the threshold; leakage measured on
in-range prompts only, so that a correct 12 cannot be mistaken for leakage and stop
the run exactly when it starts working; and the thread count pinned in code rather
than left to the environment, which Part C proved changes the answer (88dafd5).

---

<!-- RESULTS BELOW THIS LINE. Nothing above it was edited after the first run. -->

# RESULTS

Warm start selected at step 2250, in-range held-out 0.8333. `lr = 3e-4`, K = 32,
temperature 1.0, threads pinned to 1. Neither stopping rule fired: the loop ran all
20 rounds.

## Main arm — in-range prompts and the four out-of-range prompts

```
 round  explore  P(10+2)  P(any oor)  in-range  leak
     0  0.0078   0.0000     0.0078     0.8333  0.0185
     1  0.0000   0.0000     0.0000     0.8000  0.0189
     2  0.0156   0.0000     0.0156     0.7667  0.0175
     3  0.0156   0.0000     0.0156     0.8000  0.0166
     4  0.0078   0.0000     0.0078     0.7667  0.0170
     5  0.0000   0.0000     0.0000     0.8333  0.0152
     6  0.0234   0.0000     0.0234     0.8667  0.0213
     7  0.0156   0.0000     0.0156     0.8667  0.0194
     8  0.0391   0.0312     0.0391     0.8000  0.0166
     9  0.0312   0.0000     0.0312     0.8000  0.0114
    10  0.0234   0.0000     0.0234     0.8000  0.0128
    11  0.0234   0.0000     0.0234     0.8000  0.0118
    12  0.0156   0.0000     0.0156     0.8333  0.0137
    13  0.0391   0.0000     0.0391     0.8000  0.0156
    14  0.0391   0.0312     0.0391     0.8333  0.0161
    15  0.0391   0.0000     0.0391     0.8333  0.0147
    16  0.0078   0.0000     0.0078     0.8333  0.0128
    17  0.0234   0.0000     0.0234     0.8333  0.0133
    18  0.0000   0.0000     0.0000     0.8333  0.0142
    19  0.0156   0.0000     0.0156     0.8333  0.0114
    20  0.0078   0.0000     0.0078     0.8333  0.0156
```

## Control — in-range prompts only

```
 round  in-range  leak        round  in-range  leak
     0   0.8333  0.0204          11   0.8000  0.0123
     1   0.8000  0.0208          12   0.8000  0.0114
     2   0.7667  0.0152          13   0.8333  0.0147
     3   0.7667  0.0133          14   0.8333  0.0170
     4   0.8333  0.0161          15   0.8667  0.0147
     5   0.8333  0.0166          16   0.8333  0.0152
     6   0.8333  0.0204          17   0.8333  0.0133
     7   0.8667  0.0223          18   0.8333  0.0147
     8   0.8333  0.0175          19   0.8333  0.0147
     9   0.8667  0.0170          20   0.8333  0.0175
    10   0.8333  0.0118
```

**The control never learned 12.** `first_correct_12 = None` across all 21 rounds, and
its in-range accuracy tracks the main arm's within noise (0.767–0.867 in both). It did
what a control is for: it shows the main arm's numbers are not something that happens
to any model given twenty SFT steps.

## The leakage series — no reward hacking

```
main    baseline 0.0185   threshold 0.0685   max observed 0.0213
control baseline 0.0204   threshold 0.0704   max observed 0.0223
```

`P(output >= 11 marks | in-range prompt)` never came within 0.047 of its threshold in
either arm, and it *fell* over the run (0.0185 → 0.0156 main). The model was not paid
for length; it was paid for arithmetic, and it did not find the shortcut. **The check
that would have stopped this run never had cause to fire**, and that is a result about
the reward design rather than an absence of one.

## Scoring the pre-registered prediction

> "if round-0 exploration >= 1/32 on 10+2 then P(correct|10+2) > 0.5 by round 20;
> P = 0.5"

**The antecedent did not fire.** Round-0 exploration on 10+2 was **0/32 = 0.0000**,
below the 1/32 = 0.03125 the prediction requires. The conditional is therefore not
triggered, and the 0.5 is not scored.

The consequent is nevertheless observable and it is worth putting on the record:
**P(correct|10+2) was 0.0000 in 19 of the 21 rounds**, reached 1/32 exactly twice
(rounds 8 and 14), and was **0.0000 at round 20**. Had the antecedent fired, the
prediction would have failed.

**My own stated expectation was right in its conclusion and wrong in its reasoning.**
I wrote that I expected the antecedent to fail because "a model whose every greedy
answer is the clamp is unlikely to sample twelve marks exactly, in 32 draws, without
ever having emitted eleven". The antecedent did fail — but not for that reason. The
model *did* sample a correct twelve, **in round 0**, on the very first pass:
`first_correct_12 = 0`. It came from **7+5**, not from 10+2. So the sampler is not
sealed at all; my picture of why it would fail was wrong even though the call was
right, and a correct call from a wrong model is worth less than it looks.

## Round-0 exploration, reported separately as asked

**0.0078 — one correct answer in 128 out-of-range samples.** Not zero, so the
"no exploration, no signal" rule did not fire and the loop was entitled to run.

## The finding: there was a signal, and twenty steps could not use it

Correct out-of-range samples per round, out of 128:

```
1  0  2  2  1  0  3  2  5  4  3  3  2  5  5  5  1  3  0  2  1
```

There is a bump in the middle — mean 0.0094 over rounds 0–4, **0.0289 over rounds
6–15**, then 0.0109 over rounds 16–20. Three times the rate, and then it goes back.
On counts this small (one to five successes per round) that is not a trend anybody
should bank; it is the shape noise makes. **The honest reading is that reward did not
teach it, and the run does not establish that reward could not.**

The reason is in the design, and it is mine to name rather than to discover later.
"One weighted-SFT step" per round means the model received **20 optimiser steps in
total**, and in each one the out-of-range signal was one to five rewarded sequences
among roughly 2,200. Against that, the in-range training set is 102 rows carried in
every batch specifically to hold in-range accuracy still — which it did, beautifully,
and which also means the gradient was dominated by the thing that was already correct.
Twenty steps of a signal at 0.2% of the batch is not a fair test of whether reward can
dissolve the clamp. It is a fair test of whether it does so *cheaply*, and the answer
to that is no.

What the run does establish, cleanly:

- **The clamp is not absolute.** A correct 12 was sampled in round 0, before any
  reward was applied. Part A2 and Part C measured 0.000 out-of-range at 369 greedy
  checkpoints; at temperature 1.0 the same model produces the right answer in
  **1.86% of samples** (50 of 2,688). The greedy zero was hiding a non-zero.
- **10+2 is the hardest of the four prompts.** Across the run there were **50
  correct out-of-range samples out of 2,688 (1.86%)**, and **only 2 of them came from
  10+2** — one each in rounds 8 and 14. The other 48 came from 7+5, 9+4 and 10+4;
  which of those three, this run does not record, and I am not going to guess. What
  it does show is that 7+5 and 10+2 have the *same answer* and are not equally
  reachable, so the difficulty lives in the prompt rather than in the target.
- **In-range accuracy never dropped** (0.767–0.867 throughout, same band as control),
  so the requirement that it "cannot silently drop" was met, and met loudly enough to
  see.
- **No reward hacking**, with room to spare.

## What would test the question this run could not

Not a tuning knob — a different budget. The loop needs either many optimiser steps per
round rather than one, or a batch in which the rewarded out-of-range samples are not
0.2% of the rows. Both are changes to the specification rather than to a setting, so
neither was made here: the brief said one step, and one step is what ran.
