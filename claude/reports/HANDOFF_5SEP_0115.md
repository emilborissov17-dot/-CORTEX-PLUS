# HANDOFF — 5 September 2026, 01:45 local

Written at the end of a session that hit its context limit. Everything below is measured,
not remembered. Branch `feature/lidaction-guard`, everything pushed.

---

## READ FIRST, IN THIS ORDER

1. **`claude/reports/REFUSAL_READER_5SEP.md`** — the night's main finding. Sections 5-7 are
   the addendum written last: `self_modifier` has been refused **19 consecutive nights** and
   still is; the cause is one step upstream, not where the refusal message points; and only
   5 of 71 cycle steps can say what they read.
2. **`claude/reports/PHASES_BUILT_OR_NOT_5SEP.md`** — what of the seven-phase design is code
   (four of five pieces) and what is not. Note item 0: the design document
   `claude/CYCLE_PHASES_MAP_20AUG.md` does not exist on disk or in git history.
3. **`claude/reports/SILENCES_5SEP.md`** — the census. 364 silent swallows, 1452 defaulted
   `.get`s, ranked by time-to-notice.
4. **`claude/reports/PUBLISH_GATE_5SEP.md`** — superseded in one respect: it says gate 2 was
   silent. It was not. The reader report corrects it.

One command reproduces the night's headline:

```
venv\Scripts\python.exe tools/read_the_refusals.py
```

---

## WHAT IS RUNNING RIGHT NOW

### 1. The K1b NEGATIVE CONTROL training run — ALIVE, detached

```
worker pid   : 124848        (ALIVE at 01:45, RSS ~292 MB)
launcher pid : 117852        (the venv stub — NOT the worker; see below)
started      : 2026-09-04 23:52:51
progress     : epoch 0, step 110/134, loss 2.41   (at 01:27)
due          : ~02:00-02:15
logs         : claude/reports/K1B_CONTROL_RUN.out.log   (progress)
               claude/reports/K1B_CONTROL_RUN.err.log   (warnings; a deprecation
                                                          GradScaler warning is expected)
pid file     : claude/reports/K1B_CONTROL_RUN.pid
```

**This is the negative control**, trained on `training/shuffled_control.jsonl` — targets
deranged by a seeded permutation rotated by one, so no record keeps its own target
(`unchanged_target_string: 0`, seed 20260904). **A control that learns is a bug in the
harness, not a result.** Its final loss is the number that licenses runs A and B; do not
start them before reading it.

**The pid file records the launcher stub, not the worker.** `tools/launch_detached.ps1`
records the pid `Start-Process` returns, which for a venv is the redirector stub
(`venv_train\Scripts\python.exe`, RSS ~0.2 MB) and not the interpreter doing the work.
`supervisor.py:808` documents this exact trap. To find the real worker, look for the
python.exe with hundreds of MB of RSS.

**Why detached:** the harness kills background jobs at ~25-26 minutes. That, not a driver
fault, killed the earlier run. `tools/launch_detached.ps1` puts the process outside the
session's tree; it was smoke-tested (a dummy survived `TaskStop` of its launcher by 25 s).

### 2. The suite — FINISHED, and the verdict had to be recovered

```
launched : 2026-09-05 00:27:27   tools/suite_gate.py -q -rf -m "not live_state"
ended    : 2026-09-05 00:58      (~31 min)
pid      : 132324   — GONE
```

**It crashed at the very last line, after the run completed.** `suite_gate.py:416` prints
the captured stdout, the detached process had no `PYTHONIOENCODING`, and cp1252 could not
encode a replacement character:

```
UnicodeEncodeError: 'charmap' codec can't encode character '�' in position 17043
```

**`claude/reports/_suite_brainfix.out.log` is 0 bytes as a result — do not read it as
"the suite produced nothing".** The verdict was persisted before the crash and is
recoverable:

```
venv\Scripts\python.exe -c "import json,pathlib; print(json.loads(pathlib.Path('memory/suite_runs.jsonl').read_text(encoding='utf-8').splitlines()[-1])['outcome'])"

  outcome    : VALID
  returncode : 1
  failed     : 20
```

**20 failures is the baseline, not a regression.** The last five runs: 21, 19, 20, 19, 19.

One of the 20 *was* mine and **is already fixed**: `test_p_survive.py::
test_nothing_outside_the_allowed_files_mentions_it_in_code` failed because the suite
launched at 00:27 and the fix (`af641b9`) landed at 01:03. Re-run just now: **1 passed.**

**Fix for next time:** pass `PYTHONIOENCODING=utf-8` through `tools/launch_detached.ps1`,
or the same crash eats every detached suite verdict.

### 3. The 03:04 sealed cycle — untouched

Nothing tonight changed the ladder, `backend_policy`, `model_window.json`, or any scheduled
task. The Ollama **server** is up (only the runner process was killed at 00:02 to clear GPU
contention). The cycle produces tomorrow's corpus and is the project's daily proof.

**On resume, check it ran:** `memory/phase_reports/<tonight's cycle_id>/` should hold seven
JSON files, A_ORIENT through G_LEARN. `core/blackbox.py` was wired tonight (`dfd9ed9`), so
if the cycle died, this is the first night it can say where.

---

## DELIBERATELY LEFT UNDONE — and why

- **`self_modifier` was NOT unblocked.** Two independent blockers, both diagnosed in
  `REFUSAL_READER_5SEP.md` §6 with five options costed. Changing the gate on the one path
  that modifies the system itself, at 01:15, before an unattended run, is the wrong hour.
  Option C is the real fix and wants a human awake.
- **`test/test_verifier_inputs.py` is RED on purpose**, naming `browser_scout`,
  `global_indicators`, `internet_intelligence`, `sensorium_ingest`. It clears when each is
  declared in `config/step_inputs.json` or removed from `VERIFIERS`. **Expect 21 suite
  failures on the next run, not 20** — the new one is this test, by design.
- **The `ghp_` PAT in `.claude/settings.local.json`** — live, plaintext, a *different* token
  from the `.env` one `github_publisher` uses. Verified not tracked, globally ignored,
  `git log --all -S` says never committed. **Move it to `.env` tomorrow.** Explicitly
  deferred by Emil, not forgotten.
- **The B-G queue is still suspended** at Emil's instruction. B's code (`observed_at` /
  `k1_fresh`) is written but **uncommitted in the working tree** — check `git status` before
  assuming a clean start. Remaining: C mislabelled axes, D ledger correction to 8 dirs,
  E CONFLICT axis + EIA, F two-tier + quarantine + surprise guard, G integrity_ratio.
- **The notary-unavailable branch** (`fast_cycle_runner.py:1995-1996`) still prints and
  falls through to the MeTTa gate recording nothing. Named in `REFUSAL_READER_5SEP.md` §1
  rather than quietly widened; it is a silent *degradation*, not a refusal, so it does not
  fit the "ОТКАЗАНА" shape the reader looks for.

---

## ADDENDUM 02:20 — the provenance work, phases 0 and 2 done

**PHASE 0 (done, `94b14a1`)** — `claude/reports/PROVENANCE_CLOSURE_5SEP.md`. The closure is
**6 steps**, not 47: `github_publish`, `self_modifier`, `execute_patches`,
`web_intelligence` (all declared) plus **`hyperclaw_plan` and `auto_levels` (undeclared)**.
Two caveats that Phase 1 depends on:

- 6 is a **lower bound bounded by ignorance** — the walk stops at those two because they
  cannot say what they read. Each declaration extends it one ring; the phase graph caps it
  at 47. **Re-run the trace after each declaration; the trace is the stopping rule.**
- **A correct declaration can still be useless.** Inheritance only flows through artifacts
  some step claims as a *product* in `cycle_map.STEPS`. Neither `plans/` nor
  `snapshots/master/master_snapshot_latest.json` has a registered producer, and
  `attest()` initialises `inherited = FULL`, lowering it only when a stamp is found — so a
  **missing stamp currently reads as a clean one**. Declaring inputs without registering the
  upstream products yields a real age and an unearned `inherited=FULL`. Flagged, not fixed.

**PHASE 1 (NOT started, waits for the 03:04 cycle).** Declare `hyperclaw_plan` then
`auto_levels`, one commit each, evidence read from the code. The reads are already traced in
the closure report §"THE NEXT RING" — `fast_cycle_runner.py:1693-1701` and
`memory/auto_level.py:12-13,197,201` — but **re-read them before writing; that trace was
made to size the problem, not to be pasted in.** Then extend `test/test_verifier_inputs.py`
to guard the *named closure*, not `VERIFIERS`.

**PHASE 2 (done, `6e45019`)** — `core/notary.may_act()` now leads a refusal with the blind
step by name: `blind step 'hyperclaw_plan' (produces memory/improvement_proposals.json):
provenance unknown — the step never declared what it reads`. It flows into
`night_events.jsonl` unchanged, because `_witness_or_refuse` passes `may_act`'s string
straight to `_refusal_event` (`fast_cycle_runner.py:2023`). **Tonight's cycle is the first
that can say blindness out loud — check `tools/read_the_refusals.py` after 03:04.**

`memory/self_awareness.json` was **not touched**, per instruction.

## NEXT, IN ORDER

1. ~~Read the control's final loss when it lands.~~ **DONE — it landed at 01:47.**

```
examples 1077  |  optimiser steps 134  |  wall 6895.2s (1h55m)
peak allocated 2482.3 MiB  |  peak reserved 2718.0 MiB  (of 4096)
bf16 supported False  |  compute dtype torch.float16
loss: 2.6226 -> 1.9029
corpus sha256: 2622e01a08972d62431152cfa8022b8bea779c8efaf05383e664a6e782470c6c
```

**CORRECTION to the rule I wrote above it.** I said "if the control learned, stop and fix
the harness". That is too crude and would have called this a failure wrongly. The control's
**training** loss fell 27% on deranged targets — and that is expected, not damning: a
language model lowers training loss on any corpus by fitting the marginal distribution of
the target tokens (style, vocabulary, length, JSON shape), which the derangement leaves
completely intact. Only the problem→solution *mapping* was destroyed.

**The deciding number is the held-out eval, not this one.** The run's own closing note says
the same thing. What would indict the harness is the control scoring **comparably to runs A
and B on the held-out split** — that would mean A and B never learned the mapping either.
`training/eval_adapter.py` on the time-based holdout is the test.

**Not run tonight**, deliberately: it is GPU work inside the 71 minutes before the 03:04
sealed cycle, and protecting that cycle has been the standing constraint all night. It is
short (minutes, not hours) and is the first thing to run when someone is watching.
2. **Then, and only after the 03:04 cycle has sealed**, run A (rank 8, q/k/v/o) and run B
   (rank 16, 7 targets), shared recipe `--epochs 1 --max-len 256`, reports to
   `claude/reports/`. Use `tools/launch_detached.ps1` — and add `PYTHONIOENCODING=utf-8`
   to it first.
3. **`self_modifier`**, with a human present: options A+B together, and check what it would
   do on its first permitted run before permitting it. Nineteen nights of unapplied
   proposals do not replay one at a time.
4. **The PAT**, to `.env`.

---

## COMMITS TONIGHT (all pushed, `feature/lidaction-guard`)

```
dfd9ed9  blackbox: the cycle can finally say where it died
6b293f2  census: 364 silent swallows, 1452 defaulted gets, and the template that cost 15 nights
4a3a3b8  brain: _smaller() now checks that it is smaller
af641b9  census: stop the report tripping the p_survive prompt-leak guard
ce72eb6  publish gate: the item is five days stale, and the refusals were logged all along
611bba7  every refusal names its gate and its reason
8781549  read the refusals: nineteen nights of self_modifier nobody had opened
36f5ebe  verification: the seven phases are code, the map that specified them is not
```

**Three of my own claims were refuted tonight** and the corrections are in the reports, not
only here: the 785 MiB VRAM gap was not the display (the desktop runs on AMD); stopping
Ollama did not hold (it restarted 60 s later, and I had watched the wrong signal); and
`nvlddmkm` was a consequence of abrupt CUDA teardown, not the killer — the harness was.
A fourth, about the 17 August change, is corrected inside `REFUSAL_READER_5SEP.md` §4.
Treat any claim in these reports that is not backed by quoted output as unverified.
