# A3 DIED, AND NOBODY WAS TOLD
### 6 September 2026. Cause, fix, relaunch.

## What happened

```
13:04:32   A3 launched, card verified at 0 MiB
13:22:09   K1B_RUN_A3.out.log last written — "base 100/223  1006s", step 1 of 3
13:24:22   K1B_RUN_A3.err.log — RuntimeError: CUDA error: out of memory
           in scaled_dot_product_attention
14:59      found by hand, 95 minutes later
```

The chain never reached training. `models/adapters/k1b_A3` was never created. Step 1
was the control re-score, not A3 itself, so no training time was lost — only wall
clock.

## 1. WHAT TOOK THE CARD — **not established**, and I said otherwise earlier

I told Emil "the ollama runner respawned". **That was more confident than the
evidence supports, and I am withdrawing it.** What is actually established:

| fact | evidence |
|---|---|
| At 13:03:46 an ollama RUNNER held 3812 MiB | `run_a3_6sep.ps1` refusal line, pid 414364, RSS 449 MB |
| It was killed and the card went to 0 MiB | taskkill output + `nvidia-smi` |
| A3 launched into 0 MiB at 13:04:32 | launcher log |
| A3 OOM'd at 13:24:22 | `K1B_RUN_A3.err.log` |
| By 13:25:42 **no runner existed** | `tasklist`, only server 122476 |
| **No repo file was written 13:15–13:30** | full-tree mtime scan, 0 hits |
| ollama's own logs are silent | `server.log` 0 bytes; `app.log` last written **30 July** |

So a consumer took ~3.5 GB of a 4 GB card between 13:04 and 13:24 and was gone by
13:25, leaving no trace in the repo and none in ollama's logs. **It was never caught
in the act.**

Candidates, and what can be said about each:

- **An ollama runner** — most likely by precedent (one did exactly this at 13:03),
  but unproven: no load record exists because ollama's logging is not writing.
- **PC4 Part A on the GPU by mistake** — **excluded**: it ran at ~14:20, after the
  death, and with `CUDA_VISIBLE_DEVICES=""`.
- **The capability test falling back to local** — **excluded**: never run.
- **The cockpit's brain.py** — **excluded**: the cockpit is not running (nothing on
  port 5055; confirmed in COCKPIT_STATE_6SEP.md).
- **The suite** — finished at 13:11:01, thirteen minutes before.

`CORTEX_Pulse` and `CORTEX_Supervisor` both fired at 13:24:01, twenty-one seconds
before the OOM, which is suggestive; but `pulse_continuum.py` only probes port 11434
and can *start* ollama — it does not load a model. So the correlation is real and the
mechanism is not demonstrated.

**The honest conclusion: the instrumentation to answer this did not exist.** No GPU
sampling ran during the job, and the one log that would have named the consumer has
not been written since July.

## 2. Card freed

`tools/gpu_guard.ps1` — kills ollama RUNNERS only, never the server, then refuses if
the card is still held. Confirmed 0 MiB before relaunch.

## 3. Relaunched

```
15:06:21   chain pid 421920, alive after 8 s, GPU 3778 MiB, step 1 running again
```

Step 1 restarted from scratch as expected (~55 min); `--resume` covers training only.

**New ETA: control re-score ≈16:00, training ≈22:00, eval ≈22:55.** Clear of the
03:04 cycle by four hours.

## 4. The watchdog — the thing whose absence is the real failure

`tools/detached_watchdog.ps1`, started by `launch_detached.ps1` for every child. On
exit it writes ONE line to `night_events.jsonl` and one to the launcher log: pid,
observation window, last stdout line, tail of stderr.

Proven on a child that prints, sleeps 5 s, writes to stderr and exits 1:

```
DETACHED EXIT pid=423840 observed_after=60s job_started=15:04:23,
last out.log line: about to fail, err.log tail: BOOM: the thing that killed it
```

The label says **observed_after**, not *after*: that number is how long the watchdog
waited, not how long the job lived. The first draft printed "after 0s" for a job that
had run and failed, which reads as "died instantly" and would have been a new small
lie in the place built to stop them.

## 5. Root cause for tonight

The fix cannot depend on knowing the culprit, because the culprit is unknown. So:

- **`gpu_guard.ps1` runs before the job** and refuses rather than hoping.
- **The watchdog means the next death is known within 60 seconds**, not 95 minutes.
  If it happens again the event will carry the stderr tail, and — because A3 now
  logs with `python -u` — the out.log will be current rather than two minutes stale.

**Not done, and deliberately:** I have not set `OLLAMA_KEEP_ALIVE=0` on the server,
and I have not made `brain.py` or the capability test refuse on a live pid file.
Both are reasonable, and both act on a cause that has not been demonstrated. The
guard and the watchdog are cause-agnostic; the targeted fixes should wait until the
next occurrence is actually observed, which is now possible.

**If A3 dies again**, the event will name what the last log line was, and GPU
sampling should be added to the chain before a third attempt.
