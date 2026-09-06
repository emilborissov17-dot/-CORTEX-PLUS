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
