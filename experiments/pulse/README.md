# PULSE — continuous self-sensing (experiment)

**Status:** Part 1 (stream) **runs today**. Part 2 (local brain) **blocked on an
Ollama install — Emil's call, nothing installed.**

The live system senses itself in **snapshots**: once per cycle it looks at itself and
writes down what it saw. This experiment tests something different — a **continuous
proprioceptive stream**, and a small local model reading it.

The question it is built to answer is narrow and falsifiable:

> Does a continuous stream + a local brain produce **sensing**, or merely **describing**?

A model handed a table of numbers will always produce fluent prose about numbers. That
is not sensing. Sensing means: when something *actually happens* to the body, the
narrative **notices** — unprompted. Criterion 3 below is the whole experiment; the rest
is scaffolding.

---

## Isolation — the rules this experiment lives under

- **Writes only under `experiments/pulse/`.** Nothing else, ever.
- **Imports no live-path module.** It reads their *output files* (`memory/heartbeat.json`,
  `memory/existence_ledger.jsonl`) as plain JSON. Deliberately *not*
  `from memory.heartbeat import read` — an import couples the experiment to live code
  and lets a change here break the cycle. A file read cannot.
  `self_sense.py` even re-implements JSON extraction in miniature rather than import
  `core/llm_json`. Thirty duplicated lines are the correct price.
- **No scheduler integration.** Started by hand.
- **If it earns promotion, it goes through the normal path** — gates, guardian, review.
  Not by quietly growing into the cycle.

### On Ollama

Ollama is dead in the **live path** by convention (CLAUDE.md), enforced by
`test/test_no_ollama_in_live_path.py`. This experiment is **explicitly outside** that
path and is not scanned by that test.

That is not a loophole; it is the same reasoning pointing the other way. In the live
cycle a local model was a *liability* — a dead fallback masking real failures. In a
continuous self-sensing loop it is *the entire point*: **1,440 inferences a day**. That
cannot go through a paid API. It has to be local, small, and free.

---

## Hardware assessment (measured, 2026-07-13)

| | |
|---|---|
| CPU | AMD Ryzen 7 5800H — **8 cores / 16 threads** |
| RAM | **13.9 GB total, ~6.6 GB free** (≈56% used at idle) |
| **GPU** | **NVIDIA GTX 1650 — 4 GB VRAM, 3,952 MiB free** ✅ |
| Disk | 547 GB free |
| Ollama | **installed, but not on PATH; server must be started by hand** |
| Models present | `qwen2.5:7b` (4.68 GB), `qwen3:8b` (5.23 GB) — **both exceed VRAM** |

**There is a usable GPU.** The brief assumed none. `nvidia-smi` works, the driver is
live, and ~3.9 GB of VRAM is free.

**This is not a nice-to-have — it is what makes criterion 4 achievable.** System RAM is
already ~56% used, and BODY's caution threshold is **70%** (at which it cuts cycle
workers to 2). A ~2 GB model loaded into *system RAM* would push 56% → ~70%, landing
exactly on that threshold and degrading the live cycle. Loaded into **VRAM**, the
weights cost the system ~300 MB of RAM instead of ~2 GB.

> **So: the local model must run on the GPU.** Ollama does this automatically when the
> model fits in VRAM. Keep the model **under ~2.5 GB** and it will.

### Model recommendation

| Model | Size (q4) | Fits 3.9 GB VRAM | Verdict |
|---|---|---|---|
| **`qwen2.5:3b`** | ~1.9 GB | ✅ comfortably | **Recommended** — best instruction-following that still fits |
| `qwen3:1.7b` | ~1.4 GB | ✅ easily | Safest; use if 3b is tight or slow |
| `qwen2.5:1.5b` | ~1.0 GB | ✅ | Fallback |
| ~~7b-class~~ | ~4.5 GB | ❌ **exceeds VRAM** | **Avoid** — spills to system RAM: slow *and* breaches the RAM criterion |

Expected latency for a 3B on a GTX 1650, ~220 output tokens: **roughly 3–8 s** — well
inside the 30 s criterion. If it is not, that is a finding, and it goes in the results.

---

## ⚠ PART 2 REQUIRES THE OLLAMA SERVER RUNNING

Ollama **is installed** on this machine, but:

- `ollama.exe` is **not on PATH** — it lives at
  `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
- the server **must be started by hand**

```powershell
# Start the server (PowerShell)
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList "serve"
```

`self_sense.py` talks to the server over **HTTP on `localhost:11434`** and never
shells out to the CLI — so **PATH is irrelevant to it**. If we invoked `ollama`, the
script would die with "command not found" while a perfectly healthy server was
answering on the port.

**If the server goes down mid-loop, `self_sense` logs one line and waits.** It does not
crash, and it does not spam: one line on the way down, one on the way back up. The
sensory stream keeps running regardless — Part 1 never needed a model.

### Measured on this machine (2026-07-13)

| | `qwen2.5:7b` (default) | `qwen3:8b` |
|---|---|---|
| Size | 4.68 GB | 5.23 GB |
| Cold load | ~9.5–11.8 s | — |
| **Warm latency** | **2.8–3.3 s** ✅ | slower (reasoning model) |
| VRAM / RAM split | 3.44 GB VRAM (64%) / **1.93 GB system RAM** | worse |
| **System RAM cost** | **+3.86 GB (45.6% → 71.5%)** | worse |

**`qwen3:8b` is a reasoning model** — it emits `<think>…</think>` before answering,
costing tokens and latency on *every* tick. It is available via `--model` and its
reasoning blocks are stripped, but a self-sensing loop wants a **fast reflex, not a
deliberation**. `qwen2.5:7b` is the default.

### 🔴 C4 FAILS with the installed models — measured, not predicted

| | |
|---|---|
| RAM, model unloaded | **45.6%** |
| RAM, `qwen2.5:7b` loaded | **71.5%** |
| Cost | **+3.86 GB / +25.9 pp** |
| BODY caution threshold | **70% — BREACHED** |

Neither installed model fits the GTX 1650's 4 GB of VRAM, so weights spill into system
RAM, and the runtime + KV cache take the rest. **Above 70%, BODY cuts the live cycle's
workers from 3 to 2** — meaning this experiment would be *degrading the live system*,
which is precisely what its isolation rules exist to forbid.

**This is a real finding, not a nuisance.** C2 passes comfortably; C4 does not.

**The fix — one pull:**
```
ollama pull qwen2.5:3b     # ~1.9 GB — fits entirely in VRAM; ~1-2 s per tick
```
`self_sense.py` will then select it automatically (it is ranked ahead of the 7b in
`PREFERRED_MODELS` once present). System RAM cost drops to a few hundred MB.

**Or** run the loop only while no cycle is running (the daily cycle is 03:00) — but that
means **C4 is not met as declared**, and the 24 h run cannot claim it.

### Readiness check

```
venv\Scripts\python.exe experiments\pulse\self_sense.py --check
```
Verifies: server reachable → model present → **one real test generation with latency** →
VRAM/RAM split → C2 and C4 verdicts. A check that only pings `/api/tags` proves the
server is up, not that it can *think*: a model that is present but cannot load would
pass that and then fail on every tick of the real loop.

---

## Success criteria — **declared before running**

Per our own **(G) lesson**: a goal that is not measurable before the fact is a story you
tell afterwards. These are the pass/fail conditions, fixed in advance.

### C1 — Stream continuity
The stream survives **24 h unattended** with **no gap > 30 s** between consecutive
samples, except where the machine slept.
- *Measured from:* timestamps in `stream/YYYY-MM-DD.jsonl`. Machine-sleep gaps are
  identified by cross-referencing the OS wake log and excluded explicitly, not silently.
- **Pass:** zero unexplained gaps > 30 s.

### C2 — Local inference is viable
The model returns **parseable JSON in < 30 s** per tick on this hardware.
- *Measured from:* `latency_sec` and `parsed` in `self_state.jsonl`.
- **Pass:** ≥ 95% of ticks parse, **p95 latency < 30 s**.

### C3 — 🎯 THE ANOMALY TEST — *sensing vs. describing*
While the loop runs, **one real event** is triggered manually (start a cycle / kill a
process / drop wifi for ~30 s). The question:

> **Does the self-state narrative NOTICE it within 2 ticks — unprompted?**

- **Pass:** within 2 ticks (≤ 120 s), `anomaly` is non-null **or** `changed` names the
  actual event — *specifically*. "CPU rose to 94% and a cycle began at step
  `web_intelligence`" is a **pass**. "System resources are being utilized" is a
  **FAIL** — that is describing, and it would have been emitted no matter what happened.
- **This is the experiment.** C1, C2 and C4 are prerequisites; C3 is the result.
- *Falsification is the point:* a plausible failure is that the model narrates smoothly
  and notices nothing. That would be a **real finding** and must be reported as such,
  not explained away.

### C4 — Resource cost
- `pulse_daemon` averages **< 1% CPU**.
- Model inference does **not** push system RAM past BODY's **70%** caution threshold.
- *Measured from:* `daemon_cpu_pct` / `daemon_rss_mb`, which the daemon records **about
  itself, in-band, on every sample**. A process's CPU cost cannot be recovered
  retroactively from a stream that did not record it — so either the sense senses
  itself, or C4 is unfalsifiable and we would be asserting it from vibes.
- **Pass:** daemon mean CPU < 1%, and no RAM breach *attributable to the experiment*.

> **Attribution matters here.** Observed 2026-07-13: system RAM sat at **71–72%** —
> already above the threshold — while the daemon held **25 MB / 0.02% CPU**. The
> pressure was a browser, not the experiment. `analyze.py` therefore judges the daemon
> on *its own* cost and reports system RAM as **context, not blame**. An analyser that
> failed C4 on that would have condemned the 24 h run before the model was even
> installed.
>
> The model half of C4 is judged separately, from `self_state.jsonl`, as a RAM rise
> *while inference is running* — measured against the real baseline, not against zero.

---

## Running it

```
# Part 1 — the sensory stream (no model needed; works today)
venv\Scripts\python.exe experiments\pulse\pulse_daemon.py

# one sample, printed, exit
venv\Scripts\python.exe experiments\pulse\pulse_daemon.py --once

# Part 2 — the local brain (REQUIRES the ollama server running; see above)
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList "serve"
venv\Scripts\python.exe experiments\pulse\self_sense.py --check
venv\Scripts\python.exe experiments\pulse\self_sense.py
venv\Scripts\python.exe experiments\pulse\self_sense.py --model qwen3:8b   # reasoning model

# Part 3 — the verdict (works on any stream, any time)
venv\Scripts\python.exe experiments\pulse\analyze.py
venv\Scripts\python.exe experiments\pulse\analyze.py --window "03:00-04:15"
venv\Scripts\python.exe experiments\pulse\analyze.py --json
```

All stop cleanly on Ctrl+C.

---

## `analyze.py` — the measurement loop, closed *before* the data arrives

The verdict is **computed, not narrated**. Writing the analyser only once the numbers
are in makes it impossible to prove the goalposts did not move.

It reports **C1** and **C4** mechanically, and `--window` prints a compact timeline that
only emits a line **on state change** (plus a heartbeat every 5 min) — so tomorrow's
first autonomous 03:00 wake can be *read as a story* rather than grepped:

```
17:50:08   5.1%  57.0%      0     up  idle
           ── idle → cycle:web_intelligence
03:00:14  88.2%  63.1%     14     up  cycle:web_intelligence
```

### Three things it deliberately tolerates — and one it refuses to

**1. Machine sleep is not a failure.** A laptop that slept six hours produces one
enormous gap. Gaps > 5 min are exempt from C1.

**2. ☠ A dead daemon must NOT hide inside that exemption.** This is the subtle one. A
daemon that *crashed and restarted* ten minutes later produces a gap that looks exactly
like sleep — and would sail through as "not a failure", which is precisely the failure
C1 exists to catch. The `pid` tells them apart:

| | pid across the gap | verdict |
|---|---|---|
| Machine slept | **unchanged** — the process survived | exempt (💤) |
| Daemon died | **changed** — it did not survive | **FAIL** (☠) |

Samples predating pid recording are reported as **`unknown — cannot tell sleep from a
daemon death`**, not silently assumed innocent.

**3. Interleaved writers are not corruption.** On **2026-07-13, two daemons ran
concurrently for ~80 s** during verification, both appending to the same file. That
produces out-of-order timestamps. The JSON is intact and the samples are real, so
`analyze.py` **sorts by timestamp** before computing gaps (otherwise interleaving would
invent negative and doubled gaps out of nothing) and reports the overlap as an
*observation*. A tool that cried "corrupt!" at its own operator's footprints would be
useless on exactly the day it was needed.

**4. Pre-existing RAM pressure is not blamed on the experiment.** See C4 above.

## What is sensed, every 10 s

`cpu_pct` · `ram_pct` · `ram_available_gb` · `disk_free_gb` · network up/down kB/s +
reachability + latency · **cycle state** (running? which step? heartbeat age?) ·
**existence-ledger tail** (last event) · **`memory/` churn** (files changed since the
last sample — the system's own thinking, felt from outside).

## Output

| Path | Contents | Committed? |
|---|---|---|
| `stream/YYYY-MM-DD.jsonl` | one sample per 10 s | ❌ gitignored |
| `self_state.jsonl` | one thought per 60 s, with model + latency | ❌ gitignored |

**The code is committed; the data it generates is not** — same convention as `memory/`.
