# PC4 PART C — COMPOSITIONAL REPRESENTATION
### 6 September 2026. Everything above the results line was written and committed BEFORE any model was trained.

## The question A2 left open

A2 established two things. A small transformer **can** be made to generalise in-range —
median 0.800 held-out at full memorisation, against 0.433 with no weight decay. And
that gain moved out-of-range accuracy by **exactly nothing**: 0.000 at all 123 logged
checkpoints, every wrong answer clamped at 10.

But A2 tested one representation, in which **a number is an atom**. Under that
encoding "12" is a token the model has never emitted, and no rule it could induce
would make it emit one. The clamp may not be a failure of reasoning at all — it may
be the encoding's ceiling, and the experiment could not tell the difference.

Part C changes only the **output representation**, and makes the output a **sequence
the model must terminate itself** — decoded greedily until it emits END, scored
exact-match on the whole string. An answer right except for its length is wrong.

**C1 — ten-plus-remainder.** A number ≤ 10 is one symbol. A number > 10 is the
ten-marker then the remainder: `12 = <ten> <2>`. Every symbol in that answer has been
emitted before — the ten-marker as the answer 10, the remainder as its own small
answer. **Only the composition is new.** This is the representation that removes the
ceiling if the ceiling was the encoding.

**C2 — tally.** A number is that many marks; 12 is twelve marks. No new symbol at
all, only a **length never produced**. This is the classic failure mode of
transformers and it is here as the hard half of the same question.

## Held constant, so the representation is the only variable

Same split logic, same 102 training pairs, same 30 held-out in-range, the same eight
out-of-range pairs from A2 (results 11–15). Same `wd=1.0` regime, same 3 seeds, same
20,000 steps, same curve every 500. **Inputs are single symbols in both arms** — only
the answer side differs, or a difference in the result could be the longer input
rather than the longer answer. Same two controls: shuffled targets must land near
zero, and **in-range held-out below 95% makes the run UNRESOLVABLE**, because a model
that cannot answer a held-out in-range question has induced nothing to extrapolate.

## A deviation from the brief, and it costs nothing

The brief names the letters A..J for 1..9, K for 10, Z for 0. That assignment is
**alphabetically ordered in value order**, which is the one property Part A destroyed
on purpose — `test_the_symbols_carry_no_order` exists because a symbol that reveals
its own value turns induction into reading. The letters are therefore shuffled under
a fixed seed, and the ten-marker is drawn from the same pool. **Emil's scheme is
untouched** — one symbol at or below ten, ten-marker plus remainder above it — and
the generated mapping is printed below so it can be checked.

## The order probe

Each number symbol's learned input embedding is projected to 1-D by the first
principal component, and correlated (Spearman) with the value it stands for. It asks
whether the model's internal picture of the numbers is **ordered like the numbers**,
or an unordered lookup table that happens to answer correctly. Applied to C1 and,
retrospectively, to A2 under identical seeds so the two are comparable. **It does not
apply to C2**, which has no per-number output symbol to probe.

Only values 0..10 are read. In A2 the tokens for 11..15 exist in the vocabulary
because they are out-of-range *targets*, but they never appear as an *input*, so
those embedding rows never took a gradient — including them would measure the
initialiser.

## PRE-REGISTERED — Claude, on record, before any run

| claim | probability |
|---|---|
| **C1** out-of-range exact ≥ 50% on some seed | **P = 0.25** |
| **C2** out-of-range exact ≥ 50% on some seed | **P = 0.15** |
| Order probe \|Spearman\| ≥ 0.9 on **all** seeds, in A2 **and** C1 | **P = 0.7** |

**Predicted failure shapes, so a wrong prediction is visible as wrong:**

- **C1** — the model must emit the ten-marker in a position it has never occupied,
  then a remainder. Most failures will be **the ten-marker alone** (it stops, having
  produced a complete legal answer meaning 10) or **the remainder alone** (it never
  reaches for the marker). Both are the clamp wearing a different coat.
- **C2** — most failures will be **exactly ten marks**: the longest length it has
  ever produced, which is the tally form of the same clamp.

**Standing rules from A2, carried forward unchanged:** in-range held-out below 95%
makes an arm UNRESOLVABLE and its out-of-range number uninterpretable; the shuffled
control must land near zero or the split leaks and both arms are void.

---

<!-- RESULTS BELOW THIS LINE. Nothing above it was edited after the first run. -->
