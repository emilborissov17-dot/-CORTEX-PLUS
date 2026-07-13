# SCHEDULER + WATCHDOG — Design

**Status:** ✅ **BUILT** (2026-07-13) — but **NOT YET LIVE**. The scheduled task is
not registered. Run `venv/Scripts/python.exe supervisor.py --install` and execute the
printed `schtasks` command to give the system continuous existence.

**Date:** 2026-07-13
**Purpose:** the system's first autonomy rung — *continuous existence*.

## Decisions taken (Emil, 2026-07-13)

| # | Decision |
|---|---|
| 1 | **5-minute tick.** 288 no-op process starts/day is negligible; a 15-min hang window on a system whose thesis is continuous existence is not. |
| 2 | **Accept the logged-on constraint.** No stored credentials; catch-up covers the gaps. |
| 3 | **03:00 daily.** `media_intel_scheduler` moved 02:00 → 05:00 to avoid contention. |
| 4 | **Denylist shipped first**, as a separate prior commit. |
| 5 | **20h catch-up grace window.** |
| + | **Kills record their reason** — which step, heartbeat age, ceiling used. |

## What was built

| Component | Commit | Tests |
|---|---|---|
| Protected-path denylist | `a642dae` | 57 |
| Heartbeat (all 39 step boundaries) | `012b7a9` | 14 |
| Existence ledger (hash-chained, Merkle-anchored) | `edf42e7` | 17 |
| Supervisor (tick, watchdog, catch-up, lock) | `a18b694` | 28 |

Full suite: **254 passed.**

---

## 0. TL;DR — the recommendation

**Windows Task Scheduler as a dumb, durable trigger + a short-lived, stateless
`supervisor.py --tick` invoked every 5 minutes.** Not a resident daemon.

The tick is a pure function of on-disk state: it looks at `last_run`, the heartbeat,
and the lock, decides *one* of {do nothing / start cycle / catch up / kill+restart /
declare failure}, writes the outcome, and exits. All intelligence is in Python.
Task Scheduler contributes exactly one thing: "run this every 5 minutes, and keep
doing it across reboots."

This collapses **scheduling and watchdogging into a single mechanism**, and it
dissolves the who-watches-the-watchman problem (see §2).

---

## 1. Findings from the existing code (these shape the design)

Four things I found while reading, which change what the design can safely do.

### 1.1 ⚠️ Reusing `MerkleMemory.commit()` for scheduler events would corrupt memory

`commit()` (`merkle_memory.py:113`) is **the cycle's self-report**, called at step 24
of `fast_cycle_runner`. It does far more than append an event:

- increments `total_cycles`
- appends `goal_score` to the **trend series** (`_update_trends`)
- updates `self_profile` — `avg_goal_score`, `best_goal_score` (`_update_profile`)
- creates `archive/cycle_NNNNNN/` and recomputes the Merkle root from all cycle hashes

If the supervisor called `commit()` to log "cycle killed", it would register a **fake
cycle**: `total_cycles` inflates, a `goal_score: 0.0` gets pushed into the trend
vectors, and `avg_goal_score` in the self-profile is dragged down by an event that was
never a cycle. The system's self-model would be poisoned by its own supervision.

**→ Scheduler events get their own ledger (§5), Merkle-*anchored* but not
Merkle-*committed* as cycles.**

### 1.2 ⚠️ A killed cycle can never report its own death

The Merkle commit is step 24 — the *end* of the cycle. A cycle that hangs at step 11
and gets killed **never reaches it**. It cannot log its own failure; by definition the
dying process is not the one that can testify.

This is the fundamental asymmetry of the whole design: **only the supervisor, as a
separate surviving process, can witness a death.** It is why the audit trail (req 4)
must be written by the supervisor, not the cycle, and why the ledger must be
append-only and crash-safe.

### 1.3 ⚠️ The heartbeat cannot live only in `_run()`

`_run(label, fn)` (`fast_cycle_runner.py:50`) looks like the natural instrumentation
point — one wrapper, every step. It isn't. **Many steps bypass it entirely** and use
inline `try/except`:

`body_scan`, `homeostasis`, `needs_reanalysis`, `global_indicators`,
`system_hypergraph`, `scoring_engine`, `auto_levels`, `goal_score_calculator`,
`MerkleMemory commit`, `training accumulation`, `web_intelligence_agent` …

If the heartbeat only fires inside `_run()`, the cycle would look **frozen** during
every one of those steps — and `global_indicators` (20 live HTTP APIs) or
`web_intelligence` legitimately take many minutes. The watchdog would kill healthy
cycles.

**→ The heartbeat needs an explicit `beat(step)` call at every step boundary, not a
wrapper.** This is the one invasive change to `fast_cycle_runner`, and it must be
complete or the watchdog is actively harmful. See §4.3 for how to make "complete"
verifiable rather than hoped-for.

### 1.4 ✅ Prior art to reuse: `media_intel_scheduler.py`

It already solves the lock + state-file problem in this repo, in this style:
PID lock file with a staleness threshold (`_acquire_lock`, `MAX_LOCK_AGE_SEC = 6h`),
a JSON state file with `last_run_utc`, and a `--run-now` escape hatch.

**Reuse the pattern; do not reinvent it.** Two notes:
- It hardcodes `SCHEDULE_HOUR = 2`. If the main cycle is also scheduled near 02:00 the
  two will contend for CPU/RAM and the LLM rate limits. The supervisor should own the
  daily hour and `media_intel` should be scheduled off it (or, later, folded in).
- Its lock uses mtime-only staleness. Ours must also check **PID liveness** (§6) — an
  mtime-only lock either deadlocks for 6h after a hard kill, or races.

### 1.5 ⚠️ Nothing currently protects `supervisor.py` from the self-modifier

`execute_patches.py` gates patches through the AST gate (`check_code`), but I found
**no protected-path denylist** — no `PROTECTED_PATHS`, no target allowlist. The gate
reasons about *code shape*, not *which file is being written*.

That means a self-generated patch could, in principle, target `supervisor.py`,
`config/openclaw_action_policy.json`, or the AST gate itself. For req 6 that is not
acceptable: **the thing that grants autonomy must not be reachable by the autonomy it
grants.** See §7.

---

## 2. Decision: Task Scheduler vs. resident supervisor

Both were evaluated against the stated criteria.

| | **Task Scheduler alone** | **Resident supervisor** | **TS trigger + stateless tick (recommended)** |
|---|---|---|---|
| **Survives reboot** | ✅ native | ❌ needs TS/Startup to launch it anyway | ✅ native |
| **No admin** | ✅ user-context task needs no elevation¹ | ✅ | ✅ |
| **Debuggable** | ❌ opaque result codes (`0x41301`), no stack traces | ✅ one process, one log | ✅ one log; `--tick` runnable by hand |
| **Per-step heartbeat watchdog** | ❌ **impossible** — TS only offers a blunt "stop if runs > N" | ✅ | ✅ |
| **Restart budget (2/day)** | ❌ no state | ✅ | ✅ (state file) |
| **Missed-run catch-up** | ⚠️ `StartWhenAvailable` exists but is XML-only and semantically vague | ✅ | ✅ explicit, from `last_run` |
| **Who watches the watchman** | n/a | ❌ **if the supervisor hangs, nothing runs and nothing notices** | ✅ each tick is a fresh process; Windows re-invokes |

¹ A user-context task ("run only when user is logged on") needs no admin and no stored
password. "Run whether user is logged on or not" *does* require storing credentials —
avoid it. Consequence: **the cycle runs when Emil is logged in.** Given the machine is a
personal desktop that is the honest trade; if the box is ever left logged-out for days,
the catch-up path (§4.2) covers it.

**Task Scheduler alone is disqualified** by requirement 3: it fundamentally cannot
watch a heartbeat file and kill a hung child on a per-step ceiling. It has one blunt
instrument ("terminate if the task runs longer than X hours"), which cannot tell a
cycle legitimately spending 40 minutes in `web_intelligence` from one wedged on a dead
socket.

**A resident supervisor is disqualified** by its own fragility. It is the single point
of failure that has no supervisor: if it deadlocks, leaks, or dies silently at 03:00,
the system stops existing and *nothing is there to notice or say so*. For a component
whose entire purpose is "continuous existence, auditable," that is a self-defeating
architecture.

**The recommended hybrid** takes durability from the OS and intelligence from Python.
Each tick is a fresh process that cannot inherit corruption from the last one, and the
OS guarantees re-invocation. The supervisor is *stateless in memory and stateful on
disk* — which is also what makes it testable (§8) and what lets a future agent read its
own existence history (§9).

### Registration (no admin)

```
schtasks /Create /TN "CORTEX_Supervisor" /SC MINUTE /MO 5 ^
         /TR "<repo>\venv\Scripts\python.exe <repo>\supervisor.py --tick" ^
         /F
```
Runs as the current user, no elevation, survives reboot. One task. That is the entire
OS-level footprint.

> **Open question for Emil:** a 5-minute tick means a `python.exe` starts 288×/day. It
> is cheap (~0.3s, import-light if we keep `--tick` free of heavy imports) but it is
> visible in Task Manager. Acceptable? Alternative is a 15-minute tick, which widens
> the worst-case hang-detection window to 15 min + ceiling.

---

## 3. Component map

```
Windows Task Scheduler  ──every 5 min──▶  supervisor.py --tick   (short-lived)
                                                │
                        reads:  scheduler_state.json  (last_run, restarts_today)
                                heartbeat.json        (step, ts, pid)
                                cycle.lock            (pid, started_at)
                                config/scheduler.json (hour, ceilings, budget)
                                │
                        decides ONE action:
                                │
        ┌───────────────┬───────┴────────┬──────────────┬─────────────────┐
        ▼               ▼                ▼              ▼                 ▼
     nothing      start cycle      catch-up run    kill + restart   declare FAILURE
                        │                │              │                 │
                        └────────────────┴──────┬───────┴─────────────────┘
                                                ▼
                                    existence_ledger.jsonl  (append-only, hash-chained)
                                                │
                                    anchored into the NEXT cycle's
                                    MerkleMemory.commit(results=[...])
```

The cycle itself (`fast_cycle_runner.py`) gains exactly one new responsibility:
**`beat(step_name)` at every step boundary.** It knows nothing about the supervisor.

---

## 4. Behaviour

### 4.1 Daily run
Configurable hour in `config/scheduler.json` (`"daily_hour": 3`, local time). On each
tick: if `now >= today@hour` and `last_run_date < today` and no lock → **start**.

### 4.2 Missed-run catch-up (req 2)
Catch-up is not a special mode — it falls out of the same rule. The tick never asks
"is it 03:00 right now?" (which a sleeping machine would miss forever); it asks
**"has today's scheduled run happened yet?"** So a machine booted at 09:40, having been
off at 03:00, sees `last_run_date < today` and `now >= 03:00` → runs immediately, and
logs `MISSED_RUN_CATCHUP` with `scheduled_for` vs `actual_start`.

A `catchup_grace_hours` setting (default: 20) bounds this — if the machine is booted at
23:55 we probably do not want to start a multi-hour cycle that collides with tomorrow's.
Past the grace window it logs `MISSED_RUN_SKIPPED` and waits for tomorrow. **Skipping is
logged as loudly as running** — a day with no cycle is a fact about the system's
existence and must appear in the ledger.

### 4.3 Heartbeat + watchdog (req 3)

`memory/heartbeat.json`, rewritten atomically (temp + `os.replace`) at each step:

```json
{
  "pid": 12345,
  "cycle_id": "2026-07-13T03:00:04Z",
  "step": "internet_agent",
  "step_index": 11,
  "step_started_utc": "2026-07-13T03:41:22Z",
  "updated_utc": "2026-07-13T03:41:22Z"
}
```

**A file, not stdout** — per the 2026-07-11 lesson: PowerShell buffers a child's stdout,
so "no output for 15 min" is indistinguishable from "hung," and we would kill healthy
cycles. A file write is observable immediately by an unrelated process.

Watchdog rule on each tick: if a lock exists and
`now - heartbeat.updated_utc > ceiling(step)` → the cycle is wedged → **kill the PID
tree, log `CYCLE_KILLED`, restart** (subject to budget).

**Per-step ceilings.** A single global 15-minute ceiling would kill healthy cycles
(§1.3): `web_intelligence_agent` and `global_indicators` legitimately run long. So:

```json
"step_ceilings_sec": {
  "_default": 900,
  "web_intelligence_agent": 3600,
  "internet_agent": 2700,
  "global_indicators": 1200,
  "energy_review_agent": 1800
}
```
Default 15 min as specified; named overrides for the known-slow steps. **Ceilings are
config, not code** — tuning them must never require a patch to the supervisor (§7).

**Restart budget:** max 2 per calendar day (config). On the 3rd → no restart; write
`CYCLE_FAILED_BUDGET_EXHAUSTED` to the ledger, set a `failure` block in
`scheduler_state.json`, and surface it **loudly in the daily report** (req 3). It must
be impossible for the system to be quietly dead.

### 4.4 What "kill" means on Windows
`taskkill /PID <pid> /T /F` — `/T` is essential: the cycle spawns children (`yt-dlp`,
Playwright/Chromium, `subprocess` calls to `trend_tracker`). Killing only the parent
orphans a Chromium that then holds the RAM the *next* cycle needs. Verify the PID's
identity (image name + start time) before killing — a stale lock whose PID has been
recycled by the OS must never cause us to kill an unrelated process. **The supervisor
kills only a process it can prove is our cycle.**

---

## 5. The audit trail (req 4 + req 7)

`memory/existence_ledger.jsonl` — append-only, one JSON object per line, **hash-chained**:

```json
{"seq": 1041, "ts": "2026-07-13T03:00:04Z", "event": "CYCLE_STARTED",
 "cycle_id": "...", "pid": 12345, "trigger": "SCHEDULED",
 "prev_hash": "9f2c…", "hash": "4ab1…"}
```

`hash = sha256(prev_hash + canonical_json(event_without_hash))`. Tamper-evident, and
crash-safe: a torn last line is detectable and does not destroy the chain before it.

**Events:** `SUPERVISOR_TICK` (only when it acts — not 288 no-ops/day),
`CYCLE_STARTED`, `CYCLE_FINISHED`, `CYCLE_KILLED`, `CYCLE_RESTARTED`,
`MISSED_RUN_CATCHUP`, `MISSED_RUN_SKIPPED`, `CYCLE_FAILED_BUDGET_EXHAUSTED`,
`LOCK_STALE_CLEARED`, `SUPERVISOR_STARTED_AFTER_REBOOT`.

**Merkle anchoring — without corrupting the cycle history (§1.1).** The ledger is *not*
committed via `MerkleMemory.commit()` as a cycle. Instead, at step 24 the cycle passes
the ledger's **head hash and the events since the last commit** into the existing
`results=[...]` list — which already accepts arbitrary event dicts (it currently carries
patch executions and quarantine events). The ledger head hash therefore lands inside
`archive/cycle_NNNNNN/`, and any later edit to the ledger's history breaks the chain
against a hash already sealed in the Merkle tree.

This gives req 4 in full — every scheduler event is Merkle-committed — while
`total_cycles`, the trend vectors, and `self_profile` continue to mean exactly what they
meant before. **Supervision is recorded, not mistaken for living.**

> Edge case worth stating: events from a *killed* cycle are anchored by the **next**
> successful cycle. So there is a window where a death is in the ledger but not yet in
> the Merkle tree. That is unavoidable — the dead cannot seal their own record — and it
> is exactly why the ledger is independently hash-chained.

---

## 6. Single-instance lock (req 5)

`memory/cycle.lock`, JSON: `{"pid": 12345, "started_utc": "...", "cycle_id": "..."}`.

Acquire: if the file exists → **verify the PID is alive AND is actually our cycle**
(image name + process start time ≥ lock's `started_utc`). Three outcomes:
- alive and ours → **do not start.** Log nothing (this is the normal steady state).
- dead / not ours → stale (machine lost power mid-cycle; PID recycled) →
  log `LOCK_STALE_CLEARED`, clear, proceed.
- unreadable/corrupt → treat as stale, but log it.

PID-liveness beats the mtime-only approach in `media_intel_scheduler` (§1.4): after a
hard power loss, an mtime lock blocks all runs for 6 hours for no reason, while a
PID-checked lock recovers on the next tick.

Released in a `finally` by the cycle wrapper, and defensively cleared by the supervisor
whenever the PID is gone.

---

## 7. Autonomy boundary (req 6) — the part that must not be got wrong

The supervisor **starts and stops the cycle. It does nothing else.** Explicitly:

**MAY write:** `memory/heartbeat.json`, `memory/cycle.lock`,
`memory/existence_ledger.jsonl`, `memory/scheduler_state.json`, `logs/supervisor.log`.
That is the complete list.

**MUST NOT** — not "should not", *must not*, enforced:
- modify itself (`supervisor.py`) or its config (`config/scheduler.json`)
- modify the guardian, the AST gate, `safety/`, or `config/openclaw_action_policy.json`
- generate, approve, or apply patches
- change the cycle's *content* — it may not skip steps, reorder them, or pass different
  arguments. It may only start the cycle as configured, or kill it.
- widen its own restart budget or ceilings

On the OpenClaw ladder the supervisor's actions are **level_2** (local writes, backed
up, rollback-able) — it never reaches level_3. Its actions are mechanical, not
judgemental: no LLM call is made anywhere in the supervisor. **It cannot form an
intention; it can only observe a clock and a file.**

### 7.1 Required prerequisite: a protected-path denylist

Per §1.5 this **does not exist today**, and without it req 6 is aspirational rather than
enforced. Before the supervisor ships, `execute_patches.py` must refuse to write to:

```
supervisor.py
config/scheduler.json
config/openclaw_action_policy.json
safety/**
patch_guardian.py
execute_patches.py          # the gate must not be able to rewrite the gate
memory/existence_ledger.jsonl
```

The AST gate reasons about code *shape*; this is about *target*. They are different
guarantees and we currently have only the first. **I recommend shipping the denylist as
a separate, prior commit** — it is small, independently testable, and it is the thing
that makes "NEVER autonomous" true rather than merely intended.

---

## 8. Testability

The tick is a pure decision over on-disk state, so the decision function is directly
unit-testable with **no clock, no processes, no OS**:

```python
decide(now, state, heartbeat, lock, config) -> Action
```

Tests to write (all offline, all fast):
- missed run → `CATCHUP`; missed run past grace → `SKIPPED`
- fresh heartbeat mid-long-step → `NOTHING` (**the false-kill regression** — a healthy
  40-min `web_intelligence` must never be killed)
- stale heartbeat past the step ceiling → `KILL_RESTART`
- 3rd restart in a day → `FAILURE`, not a restart
- lock held by a live PID → `NOTHING`; lock held by a dead PID → `CLEAR_AND_START`
- lock with a recycled PID belonging to another process → `CLEAR`, and **never kill it**
- ledger chain verifies; a mutated middle line is detected
- supervisor writes nothing outside its permitted list (assert on the denylist)

Manual escape hatches, mirroring `media_intel_scheduler`: `--tick` (one decision, print
it, exit), `--run-now` (force a cycle), `--status` (human-readable existence report),
`--verify-ledger`.

---

## 9. Reading its own existence (req 7)

The ledger is designed as **data, not log lines**, so a future agent can answer
questions about itself:

- *"How long have I existed continuously?"* → first `CYCLE_STARTED` → now, minus gaps
- *"When did I stop existing, and why?"* → `MISSED_RUN_SKIPPED` / `CYCLE_KILLED` rows
- *"Which step kills me?"* → `GROUP BY step` over `CYCLE_KILLED`
- *"Am I getting less reliable?"* → restarts/week over time
- *"Was my history edited?"* → verify the hash chain against the Merkle-sealed head

Derived view `memory/existence_summary.json`, refreshed each cycle: `total_cycles`,
`uptime_days`, `longest_unbroken_streak`, `restarts_last_7d`, `missed_days`,
`kills_by_step`. This is the natural input to a future `self_awareness` question —
*"what is my life like?"* — answered from evidence rather than from a prompt.

That is the honest scope of this rung: **the system does not decide to exist. It merely
records, faithfully, that it did.** Deciding remains human.

---

## 10. Proposed build order

1. **Protected-path denylist** in `execute_patches.py` (+ tests) — *prerequisite for §7*
2. `heartbeat.beat()` + wire into **every** step boundary of `fast_cycle_runner`
   (+ a test asserting every step is instrumented, so coverage cannot silently rot)
3. `existence_ledger` — append, hash-chain, verify (+ tests)
4. `supervisor.py` — `decide()` pure function first, then the effectful shell (+ tests)
5. Merkle anchoring of ledger head into step 24's `results`
6. `schtasks` registration + `--status` / `--verify-ledger` CLI
7. Daily-report surfacing of `CYCLE_FAILED_BUDGET_EXHAUSTED`

Steps 1–3 are independently useful and land no autonomy. The system only becomes
continuous at step 6.

---

## 11. Decisions I need from Emil

1. **5-minute tick** (288 `python.exe` starts/day) vs 15-minute (wider hang window)?
2. **Logged-on constraint** — user-context task means the cycle runs only when logged
   in. Accept, or store credentials for "run whether logged on or not"? (I recommend
   accepting; catch-up covers the gap.)
3. **Daily hour** (default 03:00) — and should `media_intel_scheduler`'s 02:00 move to
   avoid contention?
4. **Ship the protected-path denylist first?** (I recommend yes — §7.1.)
5. **Catch-up grace window** — default 20h. Reasonable?
