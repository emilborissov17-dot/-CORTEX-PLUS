# K1b NIGHT RUN — GPU CONTENTION RECORD — 4/5 September 2026

Written and pushed BEFORE any training run started, so the change to the machine
is on the record independently of whether the runs succeed.

## WHAT I CHANGED

**Stopped the Ollama server process.** Nothing else. No config file edited, no
scheduled task disabled, no code changed.

```
process : ollama.exe   PID 14820
path    : C:\Users\emilb\AppData\Local\Programs\Ollama\ollama.exe
service : none registered — it is a user-level process, not a Windows service
```

### RESTORE COMMAND (the only thing needed to undo this)

```powershell
Start-Process "C:\Users\emilb\AppData\Local\Programs\Ollama\ollama.exe" -ArgumentList "serve"
```
Verify with:

```powershell
Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -UseBasicParsing
```

## WHY THIS MECHANISM AND NOT A CONFIG FLAG

The local leg is selected in `core/groq_backend.py:786`:

```python
res = _budget.run_call(
    cloud=_cloud_chain,
    local_3b=_local_tier(_small),
    local_8b=_local_tier(_big) if _mw.is_open() else None,
)
```
`_small = core.model_window.small_model()` reads `config/model_window.json`
`"small_model"` = `qwen2.5:3b`; `_local_tier` POSTs to `{_OLLAMA_URL}/api/chat`
(`groq_backend.py:456,498`).

Two obvious alternatives were rejected on evidence:

1. **`config/model_window.json` `"enabled": false` does NOT do it.** By that
   file's own README, false means *"8b denied everywhere (3b only, all cycle)"* —
   it gates the **8b** tier only. The 3B leg would keep running. No config key
   removes local from the ladder.
2. **`CORTEX_OLLAMA_URL` does NOT do it either.** `core/data_scout.py:187`
   hardcodes `_OLLAMA_URL = "http://localhost:11434"` with no `os.environ`
   lookup, so that caller would ignore the override. Nor would tasks launched by
   Task Scheduler inherit this shell's environment.

Stopping the server covers **every** caller, including the hardcoded one, touches
no cloud leg, and needs no file reverted.

## VERIFIED AFTER THE CHANGE (STEP C)

```
ollama process                   : NOT RUNNING
http://localhost:11434/api/tags  -> REFUSED ConnectionError
http://localhost:11434/api/chat  -> REFUSED ConnectionError
GPU before training              : 0 MiB used, 3952 MiB free
only GPU consumer during runs    : the training process itself
```

## ACCEPTED COST, STATED PLAINLY

`CORTEX_Intel` (23:30) and `CORTEX_Collector` (23:58) run tonight on a
**cloud-only** ladder. Any step that would have degraded to local now fails
outright. Per instruction this is allowed to fail loudly and be recorded; the
local leg is NOT re-enabled mid-run to rescue it.

**The 03:04 sealed cycle is protected.** Ollama is restarted at 02:45 and left
up, so the nightly cycle runs with the full ladder intact. It is the project's
daily proof and produces tomorrow's corpus; losing it is not an accepted cost.

## A CORRECTION TO THE PROJECT STATUS BLOCK

The status block says **"Ollama is dead"**. That is wrong and it misleads.

`ollama.exe` was serving on `http://localhost:11434` when this session started
(PID 14820), it backs the local 3B leg of the ladder in `core/groq_backend.py`,
and it carries roughly a quarter of all model calls.
**What is dead is the subprocess `ollama` CLI path** — the CLI constants and
`_call_ollama` / `_get_ollama_model` were removed on 2026-07-13
(`core/groq_backend.py:154`). The HTTP server is alive and load-bearing.

Anyone reading the status block and concluding the GPU is free, or that the local
tier cannot answer, will be wrong on both counts.

## THE MEASURED NUMBERS THIS SCHEDULE IS BUILT ON

Memory fix confirmed — `prepare_model_for_kbit_training` is no longer called
(comment only, `train_lora.py:144`) and embeddings are cast bf16 -> fp16:

| | before the fix | after the fix |
|---|---:|---:|
| after load | 1969.3 MiB | 1969.3 MiB |
| after prepare | 2564.3 MiB | **1970.1 MiB** |
| cost of prepare | **+595.0 MiB** | **+0.8 MiB** |
| embedding dtype | torch.float32 | **torch.float16** |
| peak allocated @ 256 | OOM | **2321.5 MiB** |
| peak reserved @ 256 | OOM | 2708.0 MiB of 4096 |

Speed, same 40-example / 2-epoch probe at max-len 256:

```
before fp16 cast : 405 s wall  ->  ~4.8 s/example
after  fp16 cast : 373 s wall  ->  ~4.4 s/example
```
**4.4 s/example is above the 3.0 s/example threshold, so all three runs use
epochs 1.** Never a different epoch count between runs.

### Extrapolation, 1077 examples

```
1077 examples x 4.4 s = 4739 s = ~79 min training
+ load/save overhead  = ~5 min
                      = ~84 min per training run
```

## THE SCHEDULE

| time | action |
|---|---|
| 22:33 | ollama STOPPED, GPU freed |
| ~22:40-22:55 | probe run B's shape (rank 16, 7 targets) to fix the shared max-len |
| ~23:00-00:25 | negative control (shuffled corpus, A's rank/targets) |
| ~00:25-00:45 | control eval |
| ~00:45-02:10 | run A |
| ~02:10-02:30 | run A eval |
| **02:45** | **ollama RESTARTED and left up** |
| 03:04 | sealed nightly cycle, full ladder intact |
| after the cycle releases the GPU | stop ollama, run B, eval B |
| after B | restart ollama, verify, commit |

Control and A both land before 02:45 with margin. **No run will be started that
would still be holding the GPU at 03:04.** If the arithmetic stops fitting, A
moves after the cycle rather than the cycle being sacrificed.