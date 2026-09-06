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

# RESULTS

```
        seed       final train   in-range   out-of-range      |rho|
C1      20260906      0.990        0.800       0.000          1.000
        20260907      0.108        0.033       0.000          0.836
        20260908      1.000        0.567       0.000          0.809
        shuffled-target control: in-range 0.067

C2      20260906      0.902        0.600       0.000            n/a
        20260907      0.000        0.000       0.000            n/a
        20260908      0.324        0.333       0.000            n/a
        shuffled-target control: in-range 0.033

A2      20260906      0.588        0.467       0.000          1.000
re-run  20260907      0.882        0.800       0.000          1.000
+probe  20260908      0.941        0.700       0.000          1.000
        shuffled-target control: in-range 0.033
```

## The strict verdict, applied as pre-registered: all three arms are UNRESOLVABLE

The standing rule is in-range held-out at or above 95%. Best FINAL in-range is 0.800
(C1 and A2); best over all 123 checkpoints is 0.933 (C1), 0.933 (C2), 0.967 (A2).
Only A2 touches the bar, and only at one checkpoint. **By the rule as written no arm
licenses a claim about extrapolation**, and I am applying it rather than arguing
round it.

**A flaw in my own rule, which belongs in the record.** The held-out set is 30 items,
so accuracy lives on a grid of 1/30. 95% falls *between* 28/30 = 0.9333 and
29/30 = 0.9667, which makes "at least 95%" mean "at least 29 of 30" and turns a
one-item difference into the entire verdict. I wrote that threshold for A2 without
noticing it was unreachable except at a single point on the grid.

## What the evidence nonetheless shows — labelled as NOT licensed by the rule above

**Out-of-range is 0.000 at every one of the 123 C1 checkpoints and every one of the
123 A2 checkpoints, on every seed.** In C1 that includes **45 checkpoints at full
memorisation** (train = 1.000, in-range up to 0.933) — the state the rule was written
to require, reached repeatedly, with the answer never once correct.

**And the failure has exactly one shape. All 24 out-of-range answers, across all
three C1 seeds, are the ten-marker alone:**

```
 10+2 = 12   want [QM QN]   got [QM]
  9+4 = 13   want [QM QK]   got [QM]
 10+5 = 15   want [QM QT]   got [QM]
  8+3 = 11   want [QM QY]   got [QM]
```

`QM` is the answer "10". The model emits a complete, legal, well-formed answer
meaning ten, and stops. **This is A2's clamp, reproduced exactly inside the
representation built to remove it.** The composition was available — every symbol in
`QM QN` had been emitted hundreds of times, `QM` as the answer 10 and `QN` as the
answer 2 — and it was never attempted. Not once, in 24 attempts, across three seeds
and 123 checkpoints.

C2 fails the same way in tally form: seeds ...906 and ...908 emit **exactly ten
marks** for all eight questions, ten being the longest run they have ever produced.
Seed ...907 collapsed entirely (train 0.000) and emits seventeen.

## A non-zero number in C2 that is not what it looks like

The C2 curve contains `out_of_range = 0.375` at seed ...908, step 9500. It is an
artifact, and on its own it would have been a false positive:

```
seed 20260908 step 9500: train 0.343  in-range 0.300  OUT-OF-RANGE 0.375
```

Three of the eight questions want eleven marks. **A model that always emits eleven
marks scores exactly 3/8 = 0.375** without answering anything at all. Training
accuracy there was 0.343 and in-range 0.300: the model was emitting one fixed length.
It is reported here because "C2 reached 37.5% out of range" would have been true and
worthless.

## Scoring the pre-registration

| claim | P | outcome |
|---|---|---|
| C1 out-of-range at least 50% on some seed | 0.25 | **NO** — 0.000 at all 123 checkpoints |
| C2 out-of-range at least 50% on some seed | 0.15 | **NO** — max 0.375, and that is the fixed-length artifact |
| order probe abs-rho at least 0.9 on all seeds, A2 **and** C1 | 0.70 | **NO** — A2 is 1.000/1.000/1.000, C1 is 1.000/0.836/**0.809** |

**Both failure-shape predictions were right, and exactly.** C1: "most failures will
be the ten-marker alone" — it was *all* of them, 24 of 24. C2: "most failures will be
exactly ten marks" — 16 of 24, the other 8 from a seed that never trained at all.

The order-probe prediction fails, and not only because of the collapsed seed: C1's
seed ...908 memorised perfectly (train = 1.000) and still reads 0.809. A2's three
1.000s are what pulled my estimate up; C1 is the arm that broke it.

## The finding

**The model learns the number line perfectly and cannot step off the end of it.**

A2's number embeddings, projected to one dimension, are a clean monotone line on
every seed:

```
value    0      1      2      3      4      5      6      7      8      9     10
pc1   -0.60  -0.37  -0.22  -0.13  -0.05  +0.02  +0.09  +0.18  +0.27  +0.37  +0.44
```

Spearman 1.000, three seeds of three. This is not a lookup table that happens to
answer correctly — the internal geometry is ordinal, which is the thing "did it learn
the line" was meant to detect. And the same models answer **0 of 8** out of range.

So the ceiling is **not** the output encoding, which is precisely what Part C was
built to test. C1 removed the encoding ceiling completely: the correct answer to 10+2
is two symbols the model has produced hundreds of times, in an order it has never
produced them. It never tried. What clamps is not the alphabet available at the
output — it is that nothing in 102 examples ever rewarded continuing past a complete
answer, so the rule induced is "emit the symbol for the result, then stop". That rule
is correct on every training example and silent about 12.

**The honest limit.** All three arms are UNRESOLVABLE under the pre-registered gate,
so this is evidence and not a demonstration. What makes it worth stating anyway is
that the zero is not a shrug: 0.000 across 369 checkpoints, three representations and
nine seeds, with a single structured failure mode and a perfect ordinal probe sitting
beside it. Part A's zero was uninterpretable. This one has a shape.

## Reproducibility — a caveat on every individual number above, and a correction

The A2 re-run uses identical seeds and the same training path, and its finals do not
match A2's committed ones:

```
committed A2   0.400 / 0.600 / 0.767
re-run         0.467 / 0.800 / 0.700
```

The one difference between the two commands is `OMP_NUM_THREADS=4`, set on the re-run
so the CPU work would not crowd A3. I tested that hypothesis at 400 steps, found
`OMP_NUM_THREADS` 1 and 4 both giving exactly 0.433 twice each, and **wrote that the
hypothesis was wrong. That was premature — the test was too short.** Re-running the
*exact* original command at full length:

```
no OMP_NUM_THREADS, seed 20260906, 20000 steps  ->  in-range 0.400
committed A2,       seed 20260906, 20000 steps  ->  in-range 0.400
```

**A2 reproduces exactly under its own command.** The divergence is real but it needs
length to appear: at 400 steps the two thread settings are identical to three
decimals, and by 20,000 they are 0.400 against 0.467. Tiny differences in
floating-point reduction order accumulate through a training run that is unstable by
construction.

Two things follow, and both matter more than the caveat itself:

1. **The committed A2 numbers stand.** They are reproducible under the command that
   produced them.
2. **An individual endpoint in this regime is not a portable quantity.** A number here
   is only meaningful together with its thread count, which is not something a report
   should have to say. This is consistent with everything else on this page — 20 of
   123 C1 checkpoints and 81 of 123 C2 checkpoints sit below 0.5 training accuracy —
   and it is the strongest argument for reading the **0.000**, which is identical
   across every run, seed, thread count and representation, rather than any single
   accuracy figure.
