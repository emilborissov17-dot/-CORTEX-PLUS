# KIMI ROUND 32 — THE FAST BATTERY, 5 September 2026, 17:10

Same project, same day, same card. Round 31 you answered: validator first, prompt second,
retrain third, wall self_modifier, institution later. Both of the first two are now code
(core/proposal_intake.py: a proposal is admitted only with indicator + expected_delta +
deadline that resolve through the grader; hyperclaw prompt: CAN/CANNOT + gradeable
indicators with values + the three lines under every STEP). Run A (r=8, attention) is
training as I write; verdict ~18:40.

Emil's objection, verbatim in spirit: "It is the START of September and the best you have
is predictable results on a few points, in DECEMBER?" He is right about the cause: I tied
every test of the 14 points to the nightly cycle and to indicators that update yearly.
That is where "30 nights" came from. Capability is tested where ground truth is known and
cheap; the real world validates deployment, not capability. Below is the fast battery.
Attack it: which tests are wrong, which are ceremonies, which are missing, and what the
order should be. One week, one 4 GB card, CPU for everything but four GPU runs.

## THE BATTERY (each: test, ground truth, time, what a FAIL means)

**T2+ POSITIVE CONTROL (missing until now).** We have a negative control (deranged targets
-> chance). We have no proof the bench can SEE learning when it exists. Build 300 rows
from a KNOWN rule over real axis values (e.g. "CLIMATE < 0.4 and CONFLICT rising -> action
X"), LoRA with the A recipe, same K=4 ranking bench. Corpus 1 h CPU, train 30 min, eval
20 min. FAIL (adapter at chance on a known rule) = the bench is insensitive on this card
and A/B/C are uninterpretable. Runs tomorrow morning, BEFORE Run B.

**T3 few-shot** — learning curve on the same positive-control corpus: 20/50/100/300 rows.
Pass: 100 rows reach >= 80% of the 300-row gain. Same day. FAIL = the recipe needs data
the archive will never have.

**T7 calibration — backtest, not waiting.** Replay the 57 archived cycles through
hypothesis_intake with each of the 4 methods; compute coverage and width per axis NOW.
CPU, one afternoon. Pass: coverage in 80-95% with widths that differ by axis.

**T10 self-model — backtest.** 20 nights of refusal log + blackbox are labels. Train a
predictor on cycles 1-40, test on 41-57: "will self_modifier be refused / which step is
slowest / which phase PARTIAL". CPU, one day. Compare to a persistence baseline.

**T1 transfer — leave-one-axis-out on the archive.** 25 axes; hold out one scorer at a
time; the model rates the axis from raw indicators only; Spearman vs the held-out scorer,
adapter minus base. Plus cross-domain: train on PLANET rows, test on HUMAN rows. 25 folds,
one day. Pass: adapter - base >= +0.15.

**T5 active seeking — simulated world.** 25 axes with true values and noise; a query
costs budget and returns a noisy reading. Policy "widest hypothesis interval first" vs
random vs round-robin; error reduction per query over 1000 episodes. CPU, minutes. If it
wins, the SAME policy is wired into data_scout for the real world.

**T6 + T8 + T12 — THE SANDBOX.** §VI forbids effect on the WORLD. It does not forbid a
simulation. A structural causal model with 25 variables, known edges, known intervention
effects. The system observes, acts (do-operations), receives consequences. Your Round 29
test - "would a different prediction have received a different signal?" - is literally
measurable there, and belief_revision can be compared to real credit assignment in
numbers. T8: train on observational data, test on interventions, adapter vs base on
direction accuracy (base will get ~70% from language; pass = adapter +10 points). T12:
the action->consequence loop exists in the sandbox; the wall to the world stands.
3-4 days.

**T4 new concepts — synthetic latent.** Countries carry a hidden regime variable that
generates the correlations but appears in no label. Do the adapter's hidden states
cluster by it? 2 days, one GPU run. Recombination that LOOKS like a concept does not
count; a human judges.

**T11 goals** — a synthetic evidence shock; LLM-proposed revision of the five sub-goal
weights with reasons, Merkle-logged; you judge whether it is more than "if X > threshold".
One week.

**T13** — a linear probe for axis identity in hidden states (12 Sep). Will pass; proves
nothing about understanding. **T14** — no test.

## DATES
CPU tests (7, 10, 1, 5): by 9 Sep. Positive control + curve (2, 3): 6 Sep. Sandbox
(6, 8, 12) and latent (4): by 15 Sep. Kimi after each group. Everything by 15 Sep with
numbers, not December.

## THE CAVEAT, STATED ONCE
A pass in synthetic data is not a pass in the world. A FAIL in synthetic data is final -
if the network cannot learn a known rule, or does not seek when seeking is cheap, there is
nothing to wait 30 nights for. The fast tests are eliminations first.

## QUESTIONS
1. Which of these tests would you refuse as a ceremony, and why?
2. Is the sandbox a legitimate place for T6/T8/T12 under the 31 Jul wall, or does it
   smuggle embodiment in through the back door?
3. What is missing? Is there a faster test for T1 or T4 than the ones above?
4. Order: positive control first, before Run B — agree?
5. Emil's demand is speed. Where would YOU cut a week to a day, and where would you
   refuse to?
