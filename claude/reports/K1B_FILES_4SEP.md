# K1b BENCH FILES — 4 September 2026

Repo `CORTEX++_MERGED`, branch `feature/lidaction-guard`, venv `venv_train` (Python 3.12.10).

## BLOCKER — THE TWO FILES ON DISK ARE NOT THE VERSIONS DESCRIBED

I was asked to use two files said to contain three deliberate fixes: a compute-capability
bf16 gate, a no-default stratum key, and a SEEN/UNSEEN memorisation split.
**None of the three is present in the files on disk.** They are byte-identical to the
versions already there before the request — same mtime, same size.

| file | mtime | bytes | sha256 |
|---|---|---:|---|
| `training/eval_adapter.py` | 2026-09-04 20:01:12 | 7814 | `1ef6096f68e179fcfb7f9adedfb2b99a…` |
| `training/train_lora.py` | 2026-09-04 20:01:24 | 9047 | `7654b674da0e43a94ca18bd0501e8fce…` |

Grep for the three fixes, both files:

| marker | eval_adapter.py | train_lora.py |
|---|---:|---:|
| `UNSEEN` | 0 | 0 |
| `SEEN` | 0 | 0 |
| `get_device_capability` | 0 | 0 |
| `compute capability` | 0 | 0 |
| `record_kind` | 1 | 0 |

And the single `record_kind` occurrence is the **opposite** of a no-default key —
`training/eval_adapter.py:142`:

```python
        kind = r.get("record_kind", "unspecified")
```

**I did not run training or eval.** A result from this code would be attributed to a
memorisation split and a capability gate it does not contain. I was also told not to
rewrite these files, so I did not author the fixes myself.

## STEP 1 — record_kind (done, in my file)

`cortex_memory/training/{train,holdout}.jsonl` did not exist, and emitted records did
not carry `record_kind`:

```
corpus_train.jsonl    1077 rows | record_kind present in 0
corpus_holdout.jsonl   246 rows | record_kind present in 0
train.jsonl           MISSING   (what the bench scripts default to)
holdout.jsonl         MISSING
```

Fixed in `training/corpus_from_merkle.py`: each contract entry now declares its own
stratum id, so `record_kind` is **derived from the key-set signature that matched** —
never invented, never defaulted. Output filenames are now `train.jsonl` / `holdout.jsonl`
so there is one naming convention rather than two.

### record_kind distribution (all 1323 emitted)

| kind | all | train | holdout |
|---|---:|---:|---:|
| `sig01_plain` | 786 | 601 | 185 |
| `sig02_approved_with_impact` | 470 | 432 | 38 |
| `sig03_experiment_authored` | 18 | 8 | 10 |
| `sig04_moral_checked` | 18 | 9 | 9 |
| `sig05_gate_signalled` | 13 | 13 | 0 |
| `sig06_feedback_no_component` | 8 | 8 | 0 |
| `sig07_dependency_check` | 6 | 2 | 4 |
| `sig08_approved_no_component` | 4 | 4 | 0 |
| **total** | **1323** | **1077** | **246** |

The strata are unbalanced, and three kinds appear only in train
(`sig05_gate_signalled` 13, `sig06_feedback_no_component` 8, `sig08_approved_no_component` 4).
A per-stratum holdout verdict on those is not computable at all — a property of the
archive, not of the split.

## STEP 2 — the nightly cycle is NOT running

```
memory/cycle.lock : absent
lock_present      : false
pid               : null
last sealed cycle : 2026-09-04T03:04:01.407826+03:00
```

All CORTEX scheduled tasks report `Ready`, none `Running`. The main nightly cycle is
next due ~03:04 tomorrow. **But two tasks fall inside a long training run:**
`CORTEX_Intel` next at 23:30 and `CORTEX_Collector` at 23:58. Peak was 2270 of 4096 MiB
with 223 MiB free — if either loads the local model while training holds the GPU, one of
the two dies. A run must finish before 23:30, or those tasks be disabled first.

## PACKAGE VERSIONS (venv_train — all already present, nothing installed)

| package | version |
|---|---|
| `accelerate` | 1.14.0 |
| `bitsandbytes` | 0.50.2 |
| `datasets` | 5.0.1 |
| `numpy` | 2.5.2 |
| `peft` | 0.20.0 |
| `safetensors` | 0.8.0 |
| `torch` | 2.7.1+cu118 |
| `transformers` | 5.16.1 |

No import failures. Both modules import cleanly. `peft` and `bitsandbytes` are imported
inside functions (`eval_adapter.py:118`, `train_lora.py:119-120`), so `--help` does not
exercise them; both resolve when imported directly.

## --help OUTPUT (verbatim)
### training/eval_adapter.py
```
usage: eval_adapter.py [-h] [--base BASE] [--adapter ADAPTER]
                       [--holdout HOLDOUT] [--report REPORT]
                       [--max-tokens MAX_TOKENS]

options:
  -h, --help            show this help message and exit
  --base BASE
  --adapter ADAPTER
  --holdout HOLDOUT
  --report REPORT
  --max-tokens MAX_TOKENS
```
### training/train_lora.py
```
usage: train_lora.py [-h] [--base BASE] [--train TRAIN] [--out OUT]
                     [--report REPORT] [--epochs EPOCHS] [--max-len MAX_LEN]
                     [--accum ACCUM] [--lr LR] [--rank RANK] [--alpha ALPHA]
                     [--targets TARGETS]

options:
  -h, --help         show this help message and exit
  --base BASE
  --train TRAIN
  --out OUT
  --report REPORT
  --epochs EPOCHS
  --max-len MAX_LEN
  --accum ACCUM
  --lr LR
  --rank RANK
  --alpha ALPHA
  --targets TARGETS
```

## WHAT IS NEEDED TO UNBLOCK

Place the real versions of `training/eval_adapter.py` and `training/train_lora.py` on
disk. The corpus side is ready: 1323 records, each carrying a contract-derived
`record_kind`, at the exact paths the scripts already default to.