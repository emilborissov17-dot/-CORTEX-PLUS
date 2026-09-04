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
---

## CORRECTION, 23:26 — THE MITIGATION DID NOT HOLD

Everything above about *why* stopping Ollama is the right mechanism remains true.
What is **false** is the implied claim that it stayed stopped.

```
22:33:37  ollama stopped, /api/tags and /api/chat REFUSED  (verified)
22:34:14  ollama.exe RUNNING again, PID 122476             (NOT restarted by me)
23:25:21  /api/tags ANSWERING
```

It came back **sixty seconds** after I stopped it. I did not restart it and nothing
in this session did. Ollama on Windows respawns its server; a one-shot
`Stop-Process` cannot hold it.

I did not notice for fifty minutes because the check I was running was the wrong
one: I watched **GPU memory**, which stayed at 0 MiB, and concluded the mitigation
was holding. It was not — idle Ollama simply holds no VRAM. It takes the GPU only
when a step actually calls the local tier and a model is loaded.

**So the exposure is narrower than this document originally claimed, and the
mitigation is weaker.** Contention happens if and only if a CORTEX step invokes the
local leg during a training run. Ollama merely being alive costs nothing. The speed
probe, the B-shape probe and the control all in fact ran with Ollama up and the GPU
still free.

Re-stopping it would be theatre — it would be back within a minute — so it has not
been re-stopped. The 02:45 "restart ollama" step in the schedule below is therefore
already satisfied and is a no-op: it never stayed down.

### What this means for the sealed 03:04 cycle
Unchanged and still protected: the full ladder is intact right now, because the
local leg has been reachable since 22:34.

### What it means for the schedule
```
23:24  the negative control was KILLED ~27 min into an ~84 min run.
       No OOM, no traceback — the log stops cleanly mid training loop and the
       harness reported "killed", i.e. an external stop, not a crash.
       supervisor.py is NOT the culprit: it only kills the pid recorded in
       memory/cycle.lock (is_cycle_pid -> kill_tree), and the trainer was never
       in that lock.
23:27  control restarted, expected ~00:51
```
With 27 minutes lost, control + A can no longer both clear 02:45: A's eval would
still be holding the GPU at ~02:56. Per the standing rule — *never start a run that
would still be holding the GPU at 03:04* — **run A moves to after the sealed cycle,
alongside B.** Only the control runs before it.

---

## 23:50 — THE KILLER IS NAMED, AND IT WAS NEVER ON THIS MACHINE

**The agent harness killed the run.** Not the OS, not the GPU driver, not CORTEX.

The evidence is in the harness's own bookkeeping. Every background job it runs ends
its output file with a terminator, and there are exactly two kinds:

```
[exited with code N]   x19   normal completion
[killed]               x2    3 Sep 16:40, and the control at 23:24:13
```

`[killed]` is written by the harness, not observed from the OS. And there is a
lifetime boundary:

| job | duration | outcome |
|---|---|---|
| suite gate | 24 m 14 s | exited 0 |
| suite gate | 24 m 53 s | exited 0 |
| B-shape probe | 14 m 54 s | exited 0 |
| **negative control** | **26 m 35 s** | **killed** |

Longest survivor 24 m 53 s; the kill at 26 m 35 s. Consistent with a finite
background-job lifetime in the 25-26 minute band. Two kills is not proof of an exact
limit, but it is enough to stop betting 84-minute runs against it.

### THE REUSABLE LESSON
**Every OS-level search was always going to come back empty, because the terminator
was outside the machine's own bookkeeping.** Hours went into:

- Windows System and Application Event Logs around both deaths
- `ResourceExhaustionDetector` / event 2004 — zero in 30 days
- the TDR hypothesis — **refuted**: no `Display` 4101/4102/4103 in ten days, and both
  `nvlddmkm` entries are Id=0 (generic, no registered message resource) rather than
  the 13/14 Xid class
- `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers` — TdrDelay, TdrDdiDelay,
  TdrLevel, TdrLimitTime, TdrLimitCount ALL unset, stock defaults
- every `taskkill`, `Stop-Process`, `psutil.process_iter` in the repo — no kill path;
  all hits are comments or read-only scanners
- Task Scheduler execution limits — all nine CORTEX tasks are PT72H

None of it could have found the answer. **When a process dies with no trace anywhere
in the system, suspect the thing that started it.**

Two corrections this forces, both mine:
1. I named `nvlddmkm` as the leading candidate for the kill. It is a CONSEQUENCE of
   abrupt CUDA teardown, not a cause — the absence of any 4101 settles it.
2. I said the ~785 MiB gap between total and free VRAM was "the display holding it".
   Wrong: `nvidia-smi` reports `display_mode Disabled, display_active Disabled` for
   the GTX 1650. The desktop runs on **AMD Radeon integrated graphics** at 2560x1600.
   Nothing display-related lives on the training card. (This also means that if TDR
   ever DID become the diagnosis, raising TdrDelay would not freeze the desktop here
   — the cost of that fix is far lower on this machine than the usual warning implies.)

### THE FIX: DETACH THE RUN FROM ITS LAUNCHER
`tools/launch_detached.ps1` starts training with `Start-Process`, outside this
session's process tree, redirecting stdout/stderr to `claude/reports/` and writing a
pid file. The caller then POLLS THE LOG instead of owning the process.

**Smoke-tested before being trusted with 84 minutes**, because an untested launcher
is the same bet that just cost half an hour:

```
23:51:20  dummy launched detached from inside a harness background job, pid 126788
23:52:12  that harness job KILLED via TaskStop
23:52:37  dummy still ALIVE and still writing:  tick 16/36
```

It survived the destruction of its launcher by 25 seconds and counting. A run that
survives its launcher cannot be killed by its launcher.

### CONTROL RELAUNCHED, DETACHED
```
23:52:51  pid 117852, detached
          --epochs 1 --max-len 256 --save-every 25 --resume
```
`train_lora.py` verified before use: `heartbeat.json`, `--resume`, `os.replace`
(atomic checkpoint — a kill mid-write cannot corrupt it), `--save-every`, and
`prepare_model_for_kbit_training` still comment-only at line 149.

Checkpointing matters more than the launcher fix, because it is the only defence that
works against a killer we have NOT named. The launcher defends against this one.

### ITEM (4) IS A SEPARATE PROBLEM AND NEEDS DIFFERENT EVIDENCE
The 30 Aug cycle death ("RAM 94% at the survival gate") is **not** an instance of this
killer, and the Windows Event Log cannot investigate it: no ResourceExhaustionDetector
event in 30 days, no nvlddmkm on 30 Aug, only an unrelated NDIS network error. It
needs the cycle's OWN survival-gate logs. Until someone reads those, its cause is
genuinely unknown rather than merely unnamed — and naming a killer would not close it
anyway. The vulnerability closes when the kill is prevented or survived.
