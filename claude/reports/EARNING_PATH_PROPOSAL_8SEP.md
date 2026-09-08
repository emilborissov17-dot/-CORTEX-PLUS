# THE EARNING PATH — how a self-modification CLASS could earn a level-lift

**2026-09-08. DIAGNOSIS AND PROPOSAL ONLY. NOTHING IS IMPLEMENTED.**

`core/notary.py` was not touched. `MAX_LEVEL`, `IRREVERSIBLE_MIN` and
AMENDMENT_001's cooling-off are exactly as they were. This document proposes a
mechanism for Emil to ratify, reject or amend. **It is not a design that may be
built from this file alone** — §7 lists what must be true before any of it is
written, and one of those things is a decision only Emil can make.

---

## 1. THE CEILING AS IT STANDS

From `config/passage_rules.json` (extracted unchanged from `core/notary.py` in
`c4a0d30`):

```json
"irreversible_min": 2,
"ceilings": { "execute_patches": 1 }
```

`execute_patches` is capped at `MINIMAL(1)`, one below the line at which an
irreversible step may act. The cap is applied **last**, after the vector, after
inheritance, after the verifier break — so no dimension, no clean input and no
verifier can lift it. `may_act()` returns False with the ceiling as the stated
reason, and the refusal names AMENDMENT_001 and a cooling-off ending
**19 Oct 2026**.

Why the cap exists is on the record in `core/notary.py`, and it is the most
important paragraph in this whole area: the rule *"execute_patches must never
reach full trust"* was believed to be enforced for ten days while it was in fact
resting on a **typo**. A declared input harvested a phantom filename —
`memory/last_attempt.txt`, a truncation of `memory/last_attempted_cycle_id.txt`
that nothing writes — `_age_state` could not stat it, age fell to UNKNOWN and the
gate shut. When commit `8b0bca6` correctly declared the step's real inputs, the
phantom left, age became FULL, and **the step that rewrites this system's own
source was stamped level_3 with `may_act() = True`**. Measured in the live chain
on 2026-08-30T12:57:14: `level=3, own=3, vector all threes`.

The gate was open for ten days and nobody knew, because an invariant was being
enforced by an accident.

**Any earning path must be read against that fact.** The failure mode is not
"the ceiling is too strict". It is "the system believed a guard was holding when
it was not".

---

## 2. WHAT EVIDENCE ALREADY EXISTS

This is the part of the proposal that needs no new machinery. `execute_patches.py`
already produces real before/after evidence per patch:

| what | where |
|---|---|
| axis levels BEFORE the patch | `_compute_levels()` → `memory.auto_level.run()` |
| axis levels AFTER the patch | same call, second time |
| composite before/after + delta | `_avg_score()`, `_record()` |
| which axes actually moved | `_changed_axes(before, after)` |
| the patch's own claim | `_extract_measured()` — the required `MEASURED: {...}` line |
| whether that claim is worth anything | `_measurement_quality()` |
| the record | `memory/development_journal.json` |

`_measurement_quality()` is the piece that makes an earning path conceivable at
all, and it was itself learned the hard way. Its four verdicts:

- **MEASURED** — a real value derived from a file the system actually has
- **ZERO** — printed a measurement of 0/None/empty; nothing was measured
- **FABRICATED** — never read any existing data file; the number is invented
- **UNMEASURED** — no MEASURED line at all

Its docstring records why: *"Yesterday's rule (every patch must print MEASURED)
worked mechanically and failed substantively: today's four patches all printed
MEASURED and all of them… a number that came from no file is not a measurement,
it is a decoration."*

That is a Goodhart failure already caught once, in this exact subsystem, against
this exact model. It is the strongest reason to expect the first version of any
bar to be gamed.

---

## 3. THE PROPOSAL — a CLASS earns, never a patch, and never the system itself

**The unit is a class of modification, not a patch and not the step.** Lifting
`execute_patches` as a whole would return the system to the ten-day state of §1.
A class is a narrow, named, human-approved kind of change — e.g.
*"add a missing axis key to a scorer's observation map"* — with a declared
before/after metric and a declared bar.

### The three conditions, and why each is necessary

**(i) The evidence clears a bar declared BEFORE the run.**
The bar is written into the class definition and sealed. A bar chosen after
seeing the numbers is not a bar. The repo already has the sealing primitive —
`experiments/prophecy/prophecy_ledger.jsonl` is hash-chained and append-only, and
`hypothesis_intake` pre-registers predictions with an interval before the cycle
that resolves them. An earning class should pre-register the same way: *this
class claims metric M moves by at least D, measured by auto_level, on N
consecutive patches.*

**(ii) Verified by something that is not the model that wrote the patch.**
This condition must be read narrowly, because this repo has already measured what
happens when it is read loosely:

- the moral-gate red-team found the 3B judge is **a rubber stamp: 100% catch and
  100% false-positive rate**;
- quarantine triage found a model judge **rubber-stamped 17/17** rejected
  patches until deterministic wiring checks overruled it, and 16 of the 17 were
  dead weight.

**So "a different model" does not satisfy (ii).** What satisfies it is a
*deterministic, non-model* check: `_measurement_quality() == MEASURED`, the named
file actually read, `_changed_axes` naming the axis the class claimed, and the
`MEASURED` value recomputed independently from the same file by code that did not
come from the patch. A second model may advise; it may not verify.

**(iii) A human approved THE CLASS, once, in advance.**
Not each patch — that is the existing approval path and it does not scale — and
not the mechanism approving itself. The class definition, its metric, its bar and
its ceiling-lift are one artifact Emil signs. The signature covers the class, and
the lift applies only to patches the deterministic classifier assigns to that
class.

### What is lifted

Not `MAX_LEVEL["execute_patches"]`. The proposal is a **per-class ceiling** that
is at most `REDUCED(2)` — exactly the minimum to act, never `FULL(3)` — and that
applies only while the class's rolling evidence still clears its bar. The global
ceiling stays where it is; a class that stops clearing its bar loses the lift
automatically, without a human having to notice.

### The anti-Goodhart clause

`docs/EVIDENCE_BASED_SELF_IMPROVEMENT.md` already defines an anti-Goodhart rule
and the promotion pipeline for KPI #4/#5. Any earning path must be a case of
that rule, not a parallel invention. **A class whose metric is the thing the
class optimises is not eligible** — the metric must be measured by something the
patch cannot write.

---

## 4. THE SHAPE OF THE MECHANISM, IF RATIFIED

```
config/earning_classes.json      one entry per approved class:
                                 name, deterministic classifier, metric,
                                 bar, window N, ceiling_lift (max 2),
                                 human signature + date

core/earning.py                  read-only scorer: given the class and the
                                 last N records from development_journal.json,
                                 does the rolling evidence clear the bar?
                                 Returns (lift_or_none, reason). Appends
                                 nothing. Decides nothing.

core/notary.py                   ONE new line in attest(): the per-class
                                 ceiling is consulted only where MAX_LEVEL
                                 already is, and can only ever LOWER the
                                 effective cap below the global one or raise
                                 it to at most REDUCED for a classified patch.
```

`config/earning_classes.json` slots into the `passage_rules` pattern from
`c4a0d30`: the notary reads it, the actor is shown it, and a structural test
pins byte-identity so a class shown to `self_modifier` is the class actually
applied.

---

## 5. THE MECHANICAL NETS THIS WOULD NEED

Stated now because they are the expensive part, and a proposal that omits them is
proposing something cheaper than the real thing.

1. **Fail closed.** An unreadable or malformed `earning_classes.json` grants no
   lift, exactly as `passage_rules` closes the gate.
2. **The lift cannot exceed `REDUCED`.** A mutation test that sets a class's
   `ceiling_lift` to 3 must go red.
3. **A class cannot classify itself.** The classifier is deterministic code in
   the repo, not a model call and not a field the patch supplies. Mutation: a
   patch that declares its own class is refused.
4. **The signature is checked.** An unsigned or edited class grants no lift;
   editing a class resets its window to zero.
5. **The window is rolling and can go backwards.** A class that stops clearing
   its bar loses the lift on the next evaluation, and that loss is written as an
   event.
6. **The evidence cannot come from the patch's own stdout alone.**
   `_measurement_quality()` already rejects FABRICATED; the earning path must
   additionally recompute the value from the named file.
7. **A regression test for §1.** Something must fail loudly if the effective cap
   on `execute_patches` for an *unclassified* patch ever rises above `MINIMAL`.
   That is the guard whose absence cost ten days.

---

## 6. WHAT THIS DOES NOT SOLVE

Even fully built and ratified, this changes **nothing tonight**, and it is worth
being blunt about that.

`self_modifier` (step 18) is refused before `execute_patches` (step 19) is ever
reached, and its own vector is `age=1` because `memory/self_awareness.json` is
**180.7 days old**. `own=1` is below `IRREVERSIBLE_MIN` regardless of any
ceiling. No earning path lifts a step whose own inputs are half a year stale.

**The stale-input question is upstream of all of this and is not answered here.**

There is also a measured capability limit: local `qwen` never closes the
write→test→fix loop (0/3, identical retries at any temperature), while the cloud
model closes it 3/3. A class earning a lift on evidence produced by a model that
cannot iterate is earning on a narrower basis than it appears to be.

---

## 7. WHAT MUST BE TRUE BEFORE ANY OF THIS IS BUILT

1. **Emil decides whether a per-class lift is wanted at all.** The alternative —
   the ceiling simply stands until 19 Oct 2026 and is then reconsidered as a
   whole — is a legitimate answer and costs nothing to implement.
2. **The stale-input problem is settled** (§6). Building an earning path on top
   of a step that cannot pass for an unrelated reason produces a mechanism nobody
   can test end to end.
3. **The first class is chosen by a human**, from real patches in
   `memory/development_journal.json`, not invented to fit the mechanism.
4. **AMENDMENT_001's cooling-off is respected.** It ends 19 Oct 2026. Nothing
   here should ship before then, and this document is not a request to shorten
   it.

---

## 8. THE HONEST SUMMARY

The evidence layer already exists and is better than expected —
`_measurement_quality()` has already survived one Goodhart failure. The genuinely
hard condition is (ii): **this repo has twice measured its model judges to be
rubber stamps**, so verification has to be deterministic code, which is
considerably more work than "ask a second model".

And the ceiling is not currently what is stopping anything. Step 18 is refused
first, on a 180-day-old input. Fixing that is smaller, cheaper, and has to happen
first regardless of what is decided here.
