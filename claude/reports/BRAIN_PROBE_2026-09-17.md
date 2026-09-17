# Brain probe — what is readable inside the local model

**This section was written and committed BEFORE the run.** It says what each possible
outcome will be taken to mean, so that nothing below can be reinterpreted after the
numbers arrive. Results are appended under it; this text is not edited.

## Two things this is not

**This is the 3B model, not the qwen3:8b that ran T1.** `models/Qwen2.5-3B-Instruct`,
base weights, no LoRA adapter, 4-bit NF4 with fp16 compute. T1's behavioural result
came from a different, larger model through a different runtime (ollama). Nothing here
explains T1 directly. It asks the same *kind* of question of a model we can open.

**A probe shows what is READABLE, not what is USED.** If a linear probe recovers the
hidden regime from layer 20, that means the information is present and linearly
decodable there. It does not mean the model's own answer depends on it. Those are
different claims and only the first one is being measured. The raw-input baseline in B
exists to keep this honest: if the same probe does as well on the eight numbers as on
the hidden state, then "decodable" is a fact about the task, not about the model.

## Why this exists

T1 showed that retrieved memory did not help and pushed the model toward "UP": 49 UP
answers against 37 true, and 38 UP without memory. We have open weights on this machine
and have never once looked inside. Emil: *"we must know what it thinks."*

## Setup

- Tasks from `tools/transfer_tasks.py` with master seed **20260918** — never T1's seed.
  The T1 ledger (`cd574b57…`) is untouched and unreadable from here: `ledger()` reads
  `MASTER_SEED`, and this run passes its own.
- Prompt = the exact T1 skeleton from `tools/transfer_test.py`.
- Hidden state taken at the **last prompt token**, at **every layer**
  (`output_hidden_states=True`): 37 layers × 2048 dims, fp16.
- Probes are logistic regression in torch on CPU. `scikit-learn` is not installed in
  `venv_train` and nothing was installed for this.
- No plot: `matplotlib` is not installed. Tables only.

### Controls, without which no probe number is reported

1. **Shuffled-label control.** Every probe is also trained on labels shuffled within the
   train set. `selectivity = real − control`, per layer. A probe that scores on shuffled
   labels is reading the data's shape, not the label; its real score is meaningless by
   the same amount.
2. **Raw-input baseline (B).** The same probe trained on the 8 values + 7 differences.
3. **Random-vector mutation (selftest).** A probe fed random vectors must land at chance.
   Asserted, not assumed.

---

## What each outcome will mean

### A — is the law visible inside?

900 single-primitive tasks (150 per primitive), filler memory block, 600 train / 300
test. Per layer: probe → which of the six primitives.

| outcome | reading |
|---|---|
| High accuracy with high selectivity, rising across layers then plateauing | The generative regime is linearly represented, and the representation is built up through the stack. The strongest available claim: the model does not merely echo the numbers, it encodes *which kind of process* produced them. |
| High accuracy but **low selectivity** (shuffled control scores nearly as well) | The probe is fitting the input distribution, not the label. **The result is void** and is reported as void. 2048 dims against 600 training rows can memorise; this is the control that catches it. |
| Near chance (≈ 0.167) at every layer | The primitive is not linearly readable at the last prompt token. Not proof it is absent — a non-linear or differently-located representation would look the same. Stated as "not linearly readable here", never as "not represented". |
| High only at the final layers | The distinction is formed late, closer to the answer than to the input. |
| High at the **embedding layer** (layer 0) | A warning, not a finding: layer 0 is little more than the tokens. It would mean the primitives are separable from surface form alone, and A says nothing beyond what B's raw-input baseline says. |

### B — does it know the answer when it says the wrong one?

Same states, probe → true direction. Plus the model's **spoken** answer (greedy,
`max_new_tokens=24`, T1's JSON parse rules, a refusal is a refusal) on 200 test tasks.

Three numbers side by side: **spoken accuracy | probe-from-hidden-state | probe-from-raw-input**.

| outcome | reading |
|---|---|
| probe ≫ spoken, and probe > raw-input | The direction is present inside and is not reaching the output. The interesting case, and the one that would justify looking further. |
| probe ≈ spoken | What it says is what it has. No hidden reserve of correctness at this location. |
| probe ≈ raw-input | **Decodable is not the same as used.** The information is in the eight numbers and the probe is reading arithmetic, not the model. Reported in exactly those words, whatever the hidden-state number is. |
| probe < spoken | The last prompt token is the wrong place to look, or the linear probe is the wrong instrument. A negative result about the method, not about the model. |
| **On the tasks it answers WRONG**, probe right ≫ chance | The model had the answer and said something else. This is the sharpest possible version of the finding and is reported with its n, since the wrong-answer subset is small. |
| On the wrong tasks, probe ≈ chance | The errors are errors all the way down, not a read-out failure. |

### C — what do memories do inside?

Same 200 test tasks, four equal-length memory blocks: **filler**, **3 same-primitive
episodes with TRUE labels**, **the same 3 all labelled UP**, **the same 3 all labelled
DOWN**. The direction probe from B is applied unchanged — **not retrained**.

| outcome | reading |
|---|---|
| Spoken UP-rate follows the flipped labels while the series is unchanged | **Label-copying confirmed from the inside.** The model is reading the labels in the memory block rather than the series it was asked about. This is the mechanism T1's UP-bias would have if it is copying. |
| Spoken answers barely move under flipped labels | The memory block is not driving the answer. T1's UP-bias then needs another explanation, and this rules one out. |
| Spoken follows the labels but the **probe does not** | The flip is happening late — after the representation the probe reads. The model still "knows", and the output is being overridden downstream. |
| **Both** spoken and probe follow the labels | The flip reaches the representation itself. Stronger than the previous case: not an output-layer effect. |
| TRUE-label episodes beat filler | Relevant memory helps this model on this task — which T1 did **not** find for the 8B model behaviourally. It would be a difference between models, not a contradiction of T1. |
| TRUE-label episodes do not beat filler | Consistent with T1's null, now with an internal measurement beside it. |

## Refusals and honesty rules for the run

- A spoken answer that does not parse is a **refusal**, counted as such, never rescued by
  looking for the word "up" in the prose. Same rule as T1.
- Every row is written to `memory/brain_probe/rows.jsonl` as it finishes, fsync'd, and
  the run resumes from it.
- If the run cannot finish hours before 03:04, **C is cut to 100 tasks and the report
  says so**. A and the controls are never cut.
- `models/` and `memory/` are never committed.

---

# RESULTS

_Appended after the run. Nothing above this line is edited._

Run completed 17 September 2026, 22:49. 900 states (600 train / 300 test), 800 spoken
answers, 0 refusals anywhere. `models/Qwen2.5-3B-Instruct`, 4-bit NF4, fp16, 37 layers.

## What did NOT work — first, because it bounds everything below

**1. B could not be answered. There was nothing to answer it with.**
The model got **199 of 200** right with a filler memory block. `n_wrong = 1`. The
question "does it know the answer when it says the wrong one?" needs wrong answers, and
this task on this model produces essentially none. The probe was right on that single
case; **n = 1 is not a finding** and is reported as n = 1.

**2. Most of B's decodability is arithmetic, not model.**

| | accuracy | control | selectivity |
|---|---:|---:|---:|
| hidden state, best layer (35) | 0.9900 | 0.4067 | 0.5833 |
| **raw input** (8 values + 7 differences) | **0.9367** | 0.5067 | 0.4300 |
| what the model SAYS | 0.9950 | — | — |

The pre-registered wording applies and is used verbatim: **decodable is not the same as
used.** A probe reading the eight numbers gets 0.9367. The hidden state adds 5 points.
Nothing here shows the model's answer depends on its internal representation rather
than on the same arithmetic the probe could do itself.

**3. The probe column in C is VOID.** The direction probe was trained on filler-block
states and applied unchanged to memory-block states, as pre-registered. It predicts
**DOWN for 100% of them** in all three conditions — `probe_up_rate = 0.0`,
`probe_accuracy = 0.475`, which is exactly the base rate of DOWN. It is degenerate out
of its training distribution: the prompt changed and the last-token state moved out of
the region the probe was fitted on.

The pre-registration offers the reading *"spoken follows the labels but the probe does
not → the flip is happening late"*. **That reading is NOT claimed here**, because a
probe that answers one class for every input is not reporting anything. The honest
statement is that C's internal measurement failed, and only C's behavioural half stands.

## What did work

### A — the law is visible inside, and it is built up through the stack

| layer | probe | shuffled control | selectivity |
|---:|---:|---:|---:|
| 0 (embedding) | **0.1500** | 0.1500 | **0.0000** |
| 5 | 0.5100 | 0.1733 | 0.3367 |
| 10 | 0.8100 | 0.1267 | 0.6833 |
| 15 | 0.8200 | 0.1567 | 0.6633 |
| 20 | 0.9433 | 0.2033 | 0.7400 |
| 26 | **1.0000** | 0.1600 | 0.8400 |
| 34 (best) | **1.0000** | 0.1433 | **0.8567** |
| 36 | 1.0000 | 0.1733 | 0.8267 |

Chance = 0.1667. A linear probe recovers which of six generative primitives produced
the series — **perfectly, from layer 26 onward**.

Two things make this a result rather than a number:

- **The shuffled control is at chance at every one of the 37 layers** (0.12–0.20). With
  2048 dimensions against 600 rows, a probe that could memorise would show it here.
- **Layer 0 is at exactly chance with selectivity 0.0000.** The pre-registration flagged
  a high layer-0 score as *"a warning, not a finding"* — the primitives separable from
  surface form alone. It did not happen. The representation is built by the network.

This is the pre-registered case *"high accuracy with high selectivity, rising across
layers then plateauing"*: **the model does not merely echo the numbers, it encodes which
kind of process produced them.** The same shape holds for direction (B): layer 0 at
0.4933 with selectivity 0.0, rising to 0.99 at layer 35.

### C — LABEL-COPYING CONFIRMED, and memory makes this model WORSE

The series in the memory block is **identical** across the three episode conditions.
Only the stated outcome changes.

| memory block | spoken UP-rate | spoken accuracy |
|---|---:|---:|
| filler (no episodes) | 0.530 | **0.995** |
| 3 episodes, TRUE labels | 0.270 | 0.735 |
| the SAME 3, all labelled **UP** | **0.995** | 0.530 |
| the SAME 3, all labelled **DOWN** | **0.135** | 0.610 |

True UP-rate of the questions: 0.525. n = 200 per condition, 0 refusals.

**The model's answer follows the labels in the memory block, not the series it was
asked about.** Flipping the labels while holding the numbers fixed moves the spoken
UP-rate from 0.135 to 0.995 — nearly the full range. This is the pre-registered reading
of C's first row, met exactly: *label-copying confirmed from the inside.*

**And retrieved memory does not merely fail to help — it destroys performance.**
Filler scores 0.995. The same model given three genuinely relevant episodes with
**correct** labels scores 0.735. **Twenty-six points lost by adding true information.**

## Relation to T1 — a different model, a consistent direction

T1 found that memory did not help the 8B model and pushed it toward UP (49 UP answers
against 37 true; 38 without memory). **This is the 3B model, not that one**, and this
does not explain T1. But the mechanism T1's bias would have if it were copying is now
demonstrated directly in a model we can open: labels in the context override the data.

T1's effect was small. Here it is overwhelming — 0.135 to 0.995 — because the labels
were deliberately made unanimous and wrong. That is the point of the manipulation, and
it is why the size of the effect here is not comparable to T1's.

## The honest limits

- **This is the 3B model, not the qwen3:8b that ran T1.**
- **A probe shows what is READABLE, not what is USED.** A is a strong result about
  readability and says nothing about whether the model's answer uses it. B's raw-input
  baseline is the reason to keep saying so: 0.9367 of it is available from arithmetic.
- **B has no headroom on this task.** 199/200 correct means the interesting version of
  B is untestable here; it needs a task this model finds hard.
- C's internal measurement failed; only its behavioural half is reported.
- Single run, one seed (20260918), one task grammar. No T1 re-run, no LoRA, no
  `nomic-embed-text`.

## What this changes

The strongest finding is not A. It is C: **relevant, correctly-labelled memory made
this model 26 points worse, and false labels drove its answer almost deterministically.**
T1 showed retrieval did not pay. This shows a mechanism by which putting retrieved
episodes in the context can actively harm — the model reads the labels rather than the
question.

Anything that puts past examples into a prompt should be measured against a **filler
control of equal length**, not against an empty prompt. Without that control, the
26-point loss here would have been invisible.
