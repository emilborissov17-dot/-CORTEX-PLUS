# K1b BENCH — STOPPED AT THE MEMORY WALL — 4 September 2026

Repo `CORTEX++_MERGED`, branch `feature/lidaction-guard`, venv `venv_train`
(Python 3.12.10, torch 2.7.1+cu118). GTX 1650, 4096 MiB, CC 7.5.

## VERDICT: NOT EVEN `--epochs 1 --max-len 128` FITS. NOTHING WAS TRAINED.

Per the stop condition, the control run and the real run were **not** started.
This is the 'run it tomorrow with the collectors moved' case — except moving the
collectors will not help, because the wall is not the collectors and not the
sequence length. It is measured below.

## STEP 0 — the three fixes are present

| check | result |
|---|---|
| `eval_adapter.py` contains `UNSEEN` | YES, 11 occurrences |
| `train_lora.py` contains `get_device_capability` | YES, `train_lora.py:119` |
| any `r.get("record_kind", <default>)` | **NONE** |

The stratum key is read strictly — `eval_adapter.py:85-93` raises `SystemExit`
naming the observed keys if `record_kind` is missing or empty. The bf16 gate is
correct for this card: `bf16 = bf16_flag and cap >= (8, 0)`, so on CC 7.5 it
reports the flag's `True` next to `real bf16 hardware: False` and uses fp16.

## STEP 1 — THE RECIPE LADDER. Every rung fails, on memory, before time matters.

40-example probe, `--epochs 2` unless stated:

| max-len | epochs | result | wall | allocated at OOM |
|---|---|---|---|---|
| 256 | 2 | **OOM** | 50 s | 3.31 GiB, tried to allocate 86.00 MiB |
| 192 | 2 | **OOM** | 56 s | 3.30 GiB, tried to allocate 86.00 MiB |
| 128 | 2 | **OOM** | 61 s | 3.29 GiB, tried to allocate 76.00 MiB |
| 128 | **1** | **OOM** | 39 s | 3.31 GiB, tried to allocate 76.00 MiB |

Epochs cannot help: it changes how many times the data is seen, not the memory of
one step. It was run anyway rather than argued, because being wrong about this
twice would have cost the night.

**No time extrapolation was possible and none is quoted.** Not one probe survived
to a completed step, so there is no per-step wall time to extrapolate from. Rank
and target modules were NOT reduced, as instructed.

## THE CAUSE, MEASURED — NOT THE SEQUENCE LENGTH

`train_lora.py:142` calls `prepare_model_for_kbit_training(...)`. That helper
upcasts every non-quantised parameter to fp32. Measured on this machine:

```
== AFTER LOAD ==
allocated_MiB 1969.3
model.embed_tokens.weight : torch.float16  311,164,928 params   593.5 MiB

== AFTER prepare_model_for_kbit_training ==
allocated_MiB 2564.3      delta_MiB +595.0
model.embed_tokens.weight : torch.float32  311,164,928 params  1187.0 MiB
```

**The embedding is upcast fp16 -> fp32 and costs +595 MiB.** In Qwen2.5-3B it is
311M parameters, tied to the output head. That cost is **independent of max-len**,
which is exactly why 256, 192 and 128 all died at the same 3.3 GiB.

For contrast, `tools/qlora_smoke.py` — which does NOT call
`prepare_model_for_kbit_training` — peaked at **2270.3 MiB** at seq 128 and
completed a full forward + backward + optimizer step. The go/no-go was real. The
difference between it and the trainer is this one call.

The remaining shortfall is the loss head. Logits are materialised over the
151,936-token vocabulary for every position:

| seq | logits fp16 | logits fp32 |
|---|---:|---:|
| 128 | 37 MiB | **74 MiB** |
| 192 | 56 MiB | 111 MiB |
| 256 | 74 MiB | 148 MiB |

With the head in fp32 the logits are fp32, and `fixed_cross_entropy` needs another
copy — matching the observed `Tried to allocate 76.00 MiB` at seq 128 exactly.
2564 MiB of model + activations + 74 + 76 exceeds 4096 MiB with the desktop
holding the rest.

## WHAT WOULD MAKE IT FIT — for whoever owns train_lora.py

I did not modify the file; these are named so the choice is yours.

1. **Keep the embedding in fp16.** `prepare_model_for_kbit_training` upcasts it
   for numerical safety on the *trainable* params, but the embedding is frozen
   here — only the LoRA adapters train. Skipping that upcast returns 595 MiB,
   more than the shortfall on its own.
2. Chunked or fused cross-entropy so full-vocabulary logits are never materialised
   at once. Removes the 74-148 MiB spike and scales with sequence length.
3. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` — the error message suggests
   it; worth ~120 MiB of fragmentation here, not enough alone.

## WHAT DID GET DONE, AND WAS COMMITTED BEFORE ANY RESULT EXISTED

`training/make_shuffled_control.py` — the negative control, written and committed
**before** any real training number exists, which was the whole point of ordering
it first. Verified against the real corpus:

```
records 1077 | seed 20260904 | fixed_points 0
unchanged_target_string 0  (0.00%)
ids identical      : True
prompts identical  : True
record_kind identical : True
targets all moved  : True
```

The derangement is a seeded permutation rotated by one, so a fixed point is
impossible by construction rather than by rejection sampling. I expected the 44%
exact-duplicate target rate to weaken it — **it did not**: zero rows received a
target string equal to their own.

`cortex_memory/training/{train,holdout}.jsonl` carry `record_kind` on **every**
record (1077 / 246), derived from the contract signature that matched.

## STEP 2 — the machine was clear; that was never the problem

No `memory/cycle.lock`, no CORTEX task `Running`, GPU at 0 MiB before the probes,
main cycle next at 03:04. `CORTEX_Intel` 23:30 and `CORTEX_Collector` 23:58 were
3h+ away and were **not** disabled.

## THE FIVE LINES

```
recipe used                : NONE — 256, 192, 128 and epochs-1/128 all OOM
control UNSEEN verdict     : NOT RUN
control SEEN verdict       : NOT RUN
real UNSEEN verdict        : NOT RUN
real SEEN verdict          : NOT RUN
```