# THE SURVIVAL GATE DID NOT FAIL. IT WAS NEVER ASKED.

13 September 2026, after `CYCLE_FAILED_BUDGET_EXHAUSTED` at 09:49 UTC.

**Investigation only. `core/homeostasis.py`, `config/scheduler.json` and the
survival gate are untouched.**

---

## The short answer to all three questions

The gate is `fast_cycle_runner.py:2571`. The process died at line 2444, about
eight seconds in, inside the FIRST heartbeat of the night — 127 lines of code
before anything asked how much memory the machine had.

It did not misread 138 MB. It never read anything.

---

## 1. Does a catch-up run go through the gate?

**Yes in principle, and it is not a separate path.** `MISSED_RUN_CATCHUP` is a
decision the supervisor makes about *whether to spawn*; what it spawns is the same
`fast_cycle_runner.py` every other origin runs, gate included. There is no
catch-up bypass.

**But the supervisor performs no memory check of its own before spawning.** A grep
of `supervisor.py` for `virtual_memory`, `available` or any RAM reading returns
nothing. It checks the lock, the restart budget, the schedule and the grace window
— all facts about time and bookkeeping, none about the machine. So the only memory
check in the whole chain is the one inside the child, and the child has to survive
long enough to reach it.

## 2. Why did it not stop at 138 MB? Which number did it read?

**None.** Reconstructed from `memory/cycle_trace/2026-09-13T12_34_02.797470_03_00.jsonl`,
which is the first boot-death recorded under the flight recorder:

```
t=0.11s  spawn    nvidia-smi --query-gpu=memory.used            x9
t=0.45s  touch    mkdir memory ; open-a memory/blackbox.jsonl
t=1.03s  pulse    experiments/keepalive/lidaction_guard.py:106  avail 106.2 MB
t=1.35s  touch    cycle_origin.json, night_events.jsonl, cycle.lock
t=1.36s  touch    heartbeat.json (renamed into place)
t=1.98s  connect  ::1:11434
t=2.05s  pulse    core/brain.py:409:models                      avail  46.7 MB
t=4.01s  connect  127.0.0.1:11434
t=6.22s  connect  127.0.0.1:11434                               x2
t=8.32s  (last event; the process is gone)
```

The path, line by line:

```
fast_cycle_runner.py:2444   beat("boot", "-1", cycle_id=...)
memory/heartbeat.py:163       from core.brain import attend as _attend
memory/heartbeat.py:164       _said = _attend(step)
core/brain.py:409             def models(): requests.get("http://localhost:11434/api/tags")
--------------------------------------------------------------------------
fast_cycle_runner.py:2571   homeo = _homeo_assess(verbose=True)      <- never reached
fast_cycle_runner.py:2572   if not homeo.get("can_start"):           <- never reached
```

**The gate sits behind the brain.** The first thing the cycle does after taking the
lock is ask a language model whether it has anything to say about the step — and
that happens before anything checks whether there is memory to run at all. On a
machine with 138 MB free, an HTTP call into a model server is not a question that
can be answered; it is the last thing the process does.

The cycle log agrees and ends exactly where the trace does:

```
[STEP] boot
[PHASE] >>> A_ORIENT
```

No error line, because there was no Python exception to print: the process was
gone. This is also why `cycle_exit.json` is stuck at `WATCHING` — the reaper died
in the same squeeze, before it could write the exit code. That record's own note
already says this is the finding rather than the absence of one.

## 3. Today's launches, and the memory each had

From `memory/blackbox.jsonl`, `step == "cycle"`, all times UTC (local is +3):

| start (UTC) | pid | avail at start | outcome | avail at exit |
|---|--:|--:|---|--:|
| 00:04:03 | 245008 | **3446.8 MB** | CYCLE_FINISHED after 2h09 | 957.0 MB |
| 06:12:42 | 260244 | 459.0 MB | exited in 1.1s | 394.8 MB |
| 06:17:09 | 256204 | 2505.2 MB | exited in 1.1s | 2505.4 MB |
| 06:57:59 | 264420 | 4022.0 MB | exited in 30.0s | 3653.3 MB |
| 07:03:58 | 258708 | 3032.4 MB | exited in 30.0s | 4430.9 MB |
| 07:07:26 | 265804 | 4150.5 MB | killed (manual, under coverage) | no exit row |
| 07:59:03 | 273836 | **2283.2 MB** | CYCLE_DIED 09:29 | no exit row |
| 09:34:05 | 286932 | **138.3 MB** | CYCLE_DIED 09:49 | no exit row |

**How many reached the gate: three.** Only three of today's runs got far enough to
print a `[BODY]` line, which is the gate's own input:

```
cycle_2026-09-13_030401.log   74 steps   RAM 73.6%
cycle_2026-09-13_070728.log   19 steps   RAM 83.1%
cycle_2026-09-13_105902.log   41 steps   RAM 69.4%
cycle_2026-09-13_123402.log    1 step    no [BODY] line at all
```

All three that reached it were nowhere near the 92% refusal line. The one that was
at 99% is the one that never got there.

The three-run collapse is visible in the ledger:

```
07:54:03  CYCLE_DIED
07:59:02  MISSED_RUN_CATCHUP   -> spawn with 2283 MB   -> died 09:29
09:34:04  MISSED_RUN_CATCHUP   -> spawn with  138 MB   -> died 09:49
09:49:04  CYCLE_FAILED_BUDGET_EXHAUSTED
```

Fifteen minutes between the second catch-up and the exhausted budget. The
supervisor spawned into 138 MB because nothing in its decision looks at memory,
and the budget it spent is the budget that exists to survive a real crash.

---

## What I would change, and none of it is in a protected file

Three candidates, cheapest first. **None is implemented.**

### A. The supervisor refuses to spawn below the gate's own threshold

`supervisor.py`, one check before `START`/`CATCHUP`: read the same number
`core/homeostasis.py` reads, and if it already fails, record a refusal instead of
spawning. This costs one function call and stops the spawn-die-retry loop that
burned the restart budget in fifteen minutes.

It is also the only one of the three that fixes the *loop* rather than the
individual death. A child that refuses cleanly still spends a spawn; a supervisor
that does not spawn spends nothing.

The threshold is not duplicated — it is read from homeostasis, so there is one
number and the protected file stays the source of it.

### B. The gate moves in front of the first beat

`fast_cycle_runner.py`, move the `assess()` call from line 2571 to before
`beat("boot")` at 2444. Nothing between those lines needs the brain: it is the
lock, the origin record, the heartbeat and the phase banner.

The objection to weigh: the boot beat is what writes the first heartbeat, and the
supervisor uses that heartbeat to tell a live cycle from a dead one. A gate that
refuses before the first heartbeat must write the refusal somewhere the supervisor
already looks — `_seal_refusal_record` does exactly that today, so the machinery
exists.

### C. The first heartbeat does not reach a model

`memory/heartbeat.py:163`, the `attend()` hook. A heartbeat's job is to say "I am
alive at step X". Asking a language model for commentary is a second job that was
attached to it, and `test/conftest.py` already carries three paragraphs about the
damage that coupling has done in tests. Making `attend()` skip the call when
available memory is under a floor — or simply not calling it for the boot beat —
removes the model from the one moment the machine is least able to afford it.

**Recommendation: A first, C second, B last.** A stops the loop, C removes the
specific cause, B is correct but touches the most delicate ordering in the file.

---

## One defect in my own recorder, found while reading this

The trace contains:

```
{"ev": "open-w", "path": "4", "n": 1}
```

`4` is a file descriptor, not a path. `core/flight_recorder._rel_if_ours` runs
`os.path.abspath` over whatever the audit hook was handed, and `open()` accepts an
integer fd. It is harmless — one meaningless row — but it is a recorder writing
something it did not observe, and that is the class of thing this recorder exists
to stop. Worth a two-line fix when the recorder is next touched.
