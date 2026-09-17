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
