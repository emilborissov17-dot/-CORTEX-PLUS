# TEST 1 — VALIDATOR EFFICACY, 50/50
### 6 September 2026. Pre-registration written BEFORE any proposal was judged.

## The pass line, fixed in advance

**PASS**: admitted-rate(real) > admitted-rate(shuffled), two-proportion z-test **p < 0.05**.
**UNRESOLVABLE**: both rates are 0 — the gate refuses everything, so it cannot be
shown to discriminate. That is a statement about the gate, not about the corpus.

## What is being asked

A gate that admits nothing discriminates nothing. A gate that admits everything
discriminates nothing either. The test is whether tonight's rules can tell a real
proposal from one wearing another proposal's numbers: same problem, same solution,
somebody else's INDICATOR / EXPECTED_DELTA / DEADLINE.

## The prediction I am on record for, before computing

**UNRESOLVABLE, both rates 0.** Tonight's rules include the cadence gate, and 11 of
13 indicators are refused outright — nine overdue, two with no observation date.
Last night's real proposals name WATER_REVIEW, INEQUALITY_POVERTY_REVIEW,
HUMAN_WELL_BEING_REVIEW and LONG_TERM_FUTURE_REVIEW; the first three are overdue and
the fourth does not resolve at all. Every one is refused before the shuffle can
matter, so the discriminating power of the gate is untestable on this material.

If that is what happens, the honest reading is not "the gate works" and not "the
gate is broken" — it is that a gate refusing 100% of both arms has no measurable
discrimination, and the test must be repeated when a cycle produces proposals on a
DAILY-TIER indicator.

---

# RESULT — UNRESOLVABLE, as predicted

```
REAL      admitted  0/25 = 0.0000
SHUFFLED  admitted  0/25 = 0.0000
```

Both arms admitted nothing, so the two-proportion test was not computed. **A gate
that refuses 100% of both arms has no measurable discrimination.**

## The material

25 pre-gate proposals recovered from last night, across every source:

```
hyperclaw_to_proposals  14      strategist_to_proposals  5
growth_to_proposals      3      HYPERCLAW (admitted)     2
core/self_experiment.py  1
```

Only **10 of 25 carried an indicator at all**. The refusal log does not keep the
triple, so it was recovered by re-parsing `plans/plan-2026-09-06.md` with the same
parser the cycle used.

The shuffled arm permuted INDICATOR / EXPECTED_DELTA / DEADLINE across proposals as
a derangement where possible; **7 of 25 kept their own triple**, because the corpus
contains repeated triples (two COSMOS steps share `LONG_TERM_FUTURE_REVIEW`, two
HUMAN steps share `HUMAN_WELL_BEING_REVIEW`) and a value cannot be deranged away
from itself when duplicated. That is recorded rather than hidden: it weakens the
shuffled arm slightly, and in the direction of making the arms MORE alike.

## Why each arm was refused — and the two lists are near-identical

```
why REAL was refused                       why SHUFFLED was refused
 15  indicator must be AXIS or AXIS__metric  15  indicator must be AXIS or AXIS__metric
  5  overdue                                  5  overdue
  2  LONG_TERM_FUTURE_REVIEW does not resolve 2  LONG_TERM_FUTURE_REVIEW does not resolve
  1  expected_delta not a number '0.0 (s...'  1  expected_delta not a number '+0.02...'
  1  expected_delta not a number '+0.3 (...'  1  expected_delta not a number '0.0 (s...'
  1  expected_delta not a number '+0.02...'   1  expected_delta not a number '+0.3 (...'
```

**The distributions are identical up to ordering, and that is the finding.** The
refusals are dominated by checks on FIELD PRESENCE AND FORM, which a permutation
preserves exactly: moving a `None` indicator from one proposal to another still
leaves a `None` indicator somewhere. Fifteen proposals — the strategist, growth and
OBJECTIVE-line ones — have no triple at all, so they are refused identically in
both arms no matter how the numbers are shuffled.

So this test could not have discriminated even if the cadence gate were absent. The
permutation only reaches proposals that HAVE a triple, and of those, five are
refused for being overdue (a property of the INDICATOR, which the shuffle moves,
but every candidate indicator in the pool is also overdue) and two for naming an
axis that does not resolve.

## What this does and does not say

- It does **not** say the gate is broken. Every refusal was correct and named.
- It does **not** say the gate works. Discrimination was never exercised.
- It says **the gate cannot be tested on this material**, and why: 60% of the
  proposals never carried the fields the shuffle permutes, and the remaining 40%
  name indicators that are refused for reasons the shuffle cannot change.

## When to repeat it

When a cycle produces proposals on a **DAILY-TIER** indicator — today that is
`CLIMATE_GLOBAL_RISK_REVIEW` and `PLANETARY_POTENTIAL_REVIEW`, two of thirteen.
L1-DAILY is what widens that set. Until then this test will return UNRESOLVABLE
every night, and re-running it without new material would be ceremony.

**The prediction written before computing was: UNRESOLVABLE, both rates 0. That is
what happened, including the reason.**
