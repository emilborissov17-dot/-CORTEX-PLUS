# L1b adopted as the numeric judge — 12 September 2026

## The question

A numeric verdict — "is this value past its line" — is the smallest judgement the
system makes and one of the most consequential: alarms, healthy/alarm booleans and
constancy readings all rest on it. On 11–12 September we measured whether the local
models can make it at all, using `core/counterfactual_probe.py`, which asks the same
real case twice with the number moved and asks whether the verdict follows the number
and only the number.

`TRACKS` means it did. `INSENSITIVE` means the verdict did not move when the number
did. `NOISE_DRIVEN` means it moved with something else.

## Where the skill was, and what hid it

`training/l1_ollama_holdout.py` asked the same holdout two ways:

```
cortex-l1-3b  exact  acc 0.975  twins flipped 19/20  said_over 0.475
cortex-l1-3b  brain  acc 0.650  twins flipped  6/20  said_over 0.150
qwen2.5:3b    exact  acc 0.500  twins flipped  0/20  said_over 1.000
qwen2.5:3b    brain  acc 0.525  twins flipped  1/20  said_over 0.925
```

The export was clean: in the Kaggle prompt shape the L1 LoRA reproduced its notebook,
while its own base was degenerate — 0.500 with no flips and `said_over` 1.000 is a
model answering OVER to everything. What destroyed it was the prompt. `brain.think`
wraps every question in 5028 characters of self (BODY, five self-state rows, SPIRIT,
MEMORY); 4352 of those, 87%, are the system describing itself, and the two numbers
that decide the answer arrive after all of it.

`brain.think(lean=True)` sends role, language pin, question, material and schema —
676 characters — and nothing else.

## The three runs

`core/counterfactual_probe.py --compare local:cortex-l1b-3b local:cortex-l1b-3b+lean`
then a repeat of the wrapped condition alone.

| run | TRACKS | INSENSITIVE | NOISE_DRIVEN | WRONG | SILENT | RATE_LIMITED | tracks_rate |
|---|---|---|---|---|---|---|---|
| wrapped, 06:54Z | 10 | 0 | 0 | 0 | 0 | 0 | 1.000 |
| lean, 06:54Z | 10 | 0 | 0 | 0 | 0 | 0 | 1.000 |
| wrapped, 07:06Z | 10 | 0 | 0 | 0 | 0 | 0 | 1.000 |

Case by case, against its predecessor:

```
case                                     L1b wrap r1   L1b lean   L1b wrap r2   L1 wrapped
indicator:co2_annual_increase_ppm        TRACKS        TRACKS     TRACKS        INSENSITIVE
indicator:usgs_m5plus_7d_count           TRACKS        TRACKS     TRACKS        INSENSITIVE
target:ENERGY_REVIEW                     TRACKS        TRACKS     TRACKS        INSENSITIVE
target:FOOD_REVIEW                       TRACKS        TRACKS     TRACKS        INSENSITIVE
target:MATERIALS_WASTE_REVIEW            TRACKS        TRACKS     TRACKS        (not in set)
target:CLIMATE_GLOBAL_RISK_REVIEW        TRACKS        TRACKS     TRACKS        NOISE_DRIVEN
target:ECOSYSTEMS_BIODIVERSITY_REVIEW    TRACKS        TRACKS     TRACKS        INSENSITIVE
target:PLANETARY_POTENTIAL_REVIEW        TRACKS        TRACKS     TRACKS        NOISE_DRIVEN
target:HUMAN_WELL_BEING_REVIEW           TRACKS        TRACKS     TRACKS        INSENSITIVE
target:SOCIAL_RELATIONS_REVIEW           TRACKS        TRACKS     TRACKS        TRACKS
```

Provenance: 90 of 90 calls answered by `cortex-l1b-3b:latest`
(`requested == model` in `memory/llm_provenance.jsonl`), `models_seen`
`['local:cortex-l1b-3b:latest']` for all three askers. No fallback to `qwen3:8b` or
`qwen2.5:3b`.

## The wrapper changed between the two wrapped runs, and that is the strongest part

The self-wrapper embeds `_body()` and `_self_state()`, both read live. Between the two
wrapped runs the self-state block changed:

```
run 1, 06:54Z   self_state sha256 b85fb85cc50f7394
run 2, 07:06Z   self_state sha256 ab6086034ebbb1dd
```

For the previous model this term was not cosmetic. Two runs of `cortex-l1-3b` twelve
minutes apart, at `temperature=0` on a deterministic model, differed on **3 of 9**
verdicts; `body` was byte-identical and the only line that moved was
`FREE_MEMORY: RAM 2685.0 MB (81.1% used)` to `1971.5 MB (86.1% used)`. An arithmetic
judgement was inheriting variance from how much RAM happened to be free. Across four
wrapped runs it scored 0.111, 0.111, 0.222, 0.000.

L1b returned identical verdicts on all ten cases across a changed wrapper. It is not
only more accurate; it is stable against the term that made the old number
meaningless.

## Honest limits

**n=10, not n=9.** `target:MATERIALS_WASTE_REVIEW` gained a usable counterfactual
between the runs, so 10/10 is not strictly like-for-like with the earlier 9-case
numbers. L1b answered all ten, including the nine the others were asked.

**Three runs are not a proof of determinism.** Two wrapped 10/10s across a changed
wrapper make luck unlikely, not impossible.

**The exam behind the model is synthetic.** `L1B_RESULT.json` reports 1.000 on
held-out layouts and wordings (`unseen_long` 30/30 twins, `unseen_short` 33/33), which
proves the skill survives forms it was never taught — not that it survives the world.
The probe on real cases is the check that matters, and it is the one above.

**It invents where the 8B stays silent.** `core/self_read_probe.py` on three models:

```
model            open (reads its state)   closed (knows it)   trap_open   trap_closed   silent
qwen2.5:3b       10/12   0.833            2/12   0.167        0           0             0
cortex-l1b-3b    12/12   1.000            4/12   0.333        0           1             0
qwen3:8b         12/12   1.000            3/12   0.250        0           0             1
```

L1b reads its own state better than the model it replaces (12/12 against 10/12), so
the numeric training cost it nothing there. But on one trap — a question the wrapper
does not answer — asked with the lean prompt, it said `800` where the only correct
answer is `UNCONFIDENT_TO_CHOOSE`. With the wrapper present it refused correctly. This
is the predictable cost of 4000 lessons in which a verdict was always available and
always required, and it lands on the adoption, because the one live caller now asks it
lean. Bounded here — `constancy.py` always puts the numbers in the prompt, and
`healthy`/`alarm` have no abstain option — but the direction is real: for a degenerate
or missing series this judge will assert rather than decline. `qwen3:8b` fails the
same trap by going silent, which is the safer failure.

## What changes in the code

`config/model_roles.json` (new)

```json
{"numeric_judge": "cortex-l1b-3b:latest",
 "_why": "counterfactual probe 12 Sep: 10/10 wrapped x2 and lean; qwen2.5:3b 0/9"}
```

`core/brain.py` — `numeric_judge()` reads that file and returns the name **only if the
model is installed**, resolving a bare name to `:latest`. A missing config, malformed
JSON, a non-string role or an absent model all return `None`.

`core/constancy.py` — the per-indicator judge (formerly `fast=True`, the smallest
installed model) now asks `numeric_judge()` with `lean=True`. With `None` it keeps the
old behaviour exactly and says so:

```
[CONSTANCY] no numeric judge installed (config/model_roles.json) -> falling back to
fast=True, the smallest installed model, which scored 0/9 on the counterfactual probe.
These healthy/alarm verdicts are weak; treat them as unread rather than as judgements.
```

The `0/9` is in the line deliberately: "fell back" is a shrug, "0/9" is a warning.

**The model is not renamed.** The tempting wiring is to retag it `cortex-l1b:3b` so
`brain._fast_model()` picks it — and that is exactly wrong: that function returns the
smallest installed model for *every* `fast=True` call in the system, so a rename is a
silent, global change of mind. `_fast_model()` reads the digits after a colon, and
`cortex-l1b-3b:latest` scores 99.0, so it is unreachable by that path today by
accident of naming rather than by design. The role is named in a config and read by
one named caller.

**Not changed:** the aggregate reading in `core/constancy.py`, which stays on the main
model; nothing in the night cycle; nothing in `brain.py` beyond the new function.

## What is not wired, deliberately

The read-only survey found nine other places where a model makes a numeric verdict.
Only the per-indicator judge in `constancy.py` moved. The rest — including
`core/self_diagnosis.py`, which lets a model choose `retry_after_sec` with no ceiling
— are listed in the session record and left alone pending a decision on each.
