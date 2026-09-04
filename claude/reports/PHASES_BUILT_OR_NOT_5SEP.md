# THE SEVEN PHASES — code or prose? 5 September 2026

Read-only verification. Nothing fixed, nothing moved. The 03:04 cycle was not touched.

## 0. THE DESIGN DOCUMENT ITSELF — DOES NOT EXIST

`claude/CYCLE_PHASES_MAP_20AUG.md` is **not on disk and not in git history**.

```
$ ls claude/
KIMI_ROUND_29.md  KIMI_ROUND_30.md  reports/

$ find . -iname "*CYCLE_PHASES*" -o -iname "*PHASES_MAP*"      # excluding venv
./config/cycle_phases.json
./test/test_cycle_phases_cover_every_step.py

$ git log --all --diff-filter=A -- "*CYCLE_PHASES_MAP*"
(no output)
```

So the specification is being verified from the description in the request, not from a
document I could read. **Everything below is what the code does; I could not diff it
against the map, because the map is gone.** The design survives only in
`config/cycle_phases.json`'s own `_what_this_is` prose and in `_phase_cli.__doc__`.

That matters for one number specifically: the request says the map counted 53 steps
growing to 66. The live config has **71**. I cannot tell whether that is drift from the
map or a map that was already stale — there is nothing to compare against.

---

## 1. `config/cycle_phases.json`, all seven phases — **EXISTS**

13,124 bytes, mtime 3 Sep 16:19. Keys: `_what_this_is`,
`_identity_is_the_index_not_the_name`, `_requires` (`:4`), `_produces` (`:5`),
`_not_exhaustive`, `phases` (`:7`), `_g_learn_attribution_note`.

All seven phases present, in order, each with `_requires` and `_produces`:

| phase | line | steps |
|---|---:|---:|
| A_ORIENT | `config/cycle_phases.json:8` | 8 |
| B_SENSE | | 10 |
| C_SNAPSHOT | | 7 |
| D_SCORE | | 13 |
| E_PROPOSE | | 7 |
| F_SELF | | 2 |
| G_LEARN | `config/cycle_phases.json:319` | 24 |
| **total** | | **71** |

The file states its own contract at `:5`: *"A phase that raised nothing but produced
nothing is PARTIAL, not DONE."* That sentence is implemented — see item 5.

There is a ratchet test on it: `test/test_cycle_phases_cover_every_step.py` reads every
`beat()` in the runner and asserts each declared step belongs to a phase.

---

## 2. `--only` / `--from` restart — **PARTIAL**

`fast_cycle_runner.py:3721 _phase_cli(argv)`, dispatched at `:3795-3796`.

What it **does** do: parses the flag (`:3744-3745`), resolves and validates the phase name
against the config, calls the resume gate, and either refuses by name or prints the phases
it would run.

What it does **not** do — and says so, in the code, not in a comment I had to infer:

```
fast_cycle_runner.py:3781
    print("[PHASE] step-level skipping is not wired yet — see _phase_cli.__doc__. "
          "Nothing was run.")
    raise SystemExit(0)
```

Its docstring (`:3722-3734`) states the reason: `main()` is one linear ~900-line function
and 30 of the (then) 53 step bodies are inline rather than wrapped in `_run()`, so there is
no seam to skip at. It is explicit that `--only`/`--from` currently **"REFUSE OR PERMIT,
print the phases they would run"** and stop there.

**Verdict: the gate is real, the restart is not.** You can ask it whether a resume is
legitimate and get a truthful answer; you cannot resume.

---

## 3. The requires-check that refuses by name — **EXISTS**

`core/phase_resume.py`, 7,754 bytes, mtime 20 Aug 18:36.

- `check_requires(phase, cycle_id, cycle_started, ...)` at `:102`
- `verify_or_refuse(mode, phase, cycle_id, ...)` at `:126` — *"Returns the phases to run,
  or raises ResumeRefused naming what is missing"* (`:130`)
- the refusal, naming each failing path and reason, at `:141-147`

**It checks belonging, not just existence** — the distinction the config claims at `:4`.
`_belongs_to_cycle()` (`:79`) takes the strongest evidence first: if the artifact is JSON
carrying `cycle_id`/`cycleId`/`cycle` equal to the cycle being resumed, it belongs
(`:88-89`). Only if that fails does it fall back to comparing mtime against the cycle start
with a 2 s tolerance. A file with no cycle start to compare against is admitted with the
evidence string saying so, rather than silently.

**It has a live caller beyond the CLI**: `fast_cycle_runner.py:939` imports `check_requires`
inside the artifact gate used by `decide_resume` (`:832`, `:919-948`), which vetoes a resume
when the next phase's required artifacts are missing. `core/cycle_checkpoint.py:326-329`
selftests it as LIVE/INERT.

---

## 4. `memory/phase_reports/<cycle_id>/<PHASE>.json` — **EXISTS, and is written nightly**

**36 cycle directories, 190 report files**, spanning `2026-08-21T00_33_50` through last
night. Last night's directory holds all seven, written in phase order as the cycle moved
through them:

```
A_ORIENT.json    1690  03:07
B_SENSE.json     2143  03:43
C_SNAPSHOT.json  1645  03:50
D_SCORE.json     6266  04:06
E_PROPOSE.json   1348  04:16
F_SELF.json       856  04:18
G_LEARN.json     3480  04:42
```

Report keys: `phase`, `cycle_id`, `started`, `ended`, `seconds`, `steps_run`,
`steps_failed`, `produces_check`, `llm_calls`, `verdict`, `reason` (built at
`core/phase_report.py:238-262`).

The live path is wired end to end:
`fast_cycle_runner.py:92 beat()` → `memory/heartbeat.py:157` → `core/phase_tracker.py:197
on_beat()` → `core/phase_tracker.py:224 PhaseReport(phase, cycle_id)`, closing the previous
phase when the pulse enters the next one; `close_last` is called explicitly for G_LEARN at
`fast_cycle_runner.py:3596` because nothing follows it. Failures reach the report through
`phase_tracker.note_failure()`, called from `_run()`'s except branch at
`fast_cycle_runner.py:1162-1163`.

Two non-cycle directories exist alongside the dated ones — `manual-run-1` and
`unknown-cycle` — the latter being `on_beat`'s fallback when `memory/cycle.lock` cannot be
read (`phase_tracker.py:212`).

---

## 5. `produces_check`, and PARTIAL when a promised file is absent — **EXISTS**

`core/phase_report.py:181-200`. For each path in the phase's `_produces` it records
`present`, `mtime`, and **`written_during_phase`** — the last computed against the phase's
own start with `MTIME_TOLERANCE_SEC = 2.0` (`:68`). Presence alone is not enough; a file
left over from last night is `present: true, written_during_phase: false`.

The verdict function (`:202-236`) is exactly the promised behaviour, and the comment at
`:208-213` states it deliberately:

> *"FAILED is reserved for a phase that BROKE… A phase where nothing raised is never
> FAILED, however empty-handed it came back — that is PARTIAL… PARTIAL means a step
> returned quietly without doing its job, which is the harder and more common defect."*

- `FAILED` only if `steps_failed` **and** nothing fresh (`:214`)
- `DONE` only if no failures, nothing stale, nothing absent (`:221`)
- otherwise `PARTIAL`, with the reason naming *"promised but never written: …"* (`:230`)
  or *"promised but only a stale copy from an earlier cycle: …"* (`:233`)

**It fires in practice, and it fires on the quiet case.** Across the 190 reports on disk:

```
DONE 120   PARTIAL 70   FAILED 0
```

and the first PARTIAL is precisely the shape in question — `steps_failed: []`, nothing
raised, verdict PARTIAL:

```
memory/phase_reports/2026-08-21T00_33_50.628425_03_00/E_PROPOSE.json
  steps_failed : []
  verdict      : PARTIAL
  reason       : promised but only a stale copy from an earlier cycle:
                 snapshots/body/growth_plan_latest.json
```

That is a phase reporting itself incomplete when every step returned normally — the report
contradicting the steps, which is what `_produces` was for.

---

## THE ONE LINE

**Four of the five pieces are working code the cycle runs every night — the phase map, the
requires-gate, the per-phase reports and the PARTIAL verdict; only the `--only`/`--from`
restart is half-built (it validates and refuses honestly, then exits without running
anything), and the design document that specifies all of it exists nowhere on disk or in
git history.**
