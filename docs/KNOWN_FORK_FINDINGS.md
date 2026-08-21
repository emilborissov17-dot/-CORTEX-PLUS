# Known fork findings

**The first reproduction report is ours.** On 21 August 2026 this repository was
checked out fresh and treated as if by someone who had never seen it: install
from `requirements.txt`, run the suite, read what broke. Four things broke. They
are recorded here in the same shape the issue template asks of you — what was
run, what came back, and what it means — so that a report from someone else can
be compared against a report and not against a mood.

**Read this document SECOND.** `CONTRIBUTING.md` explains why. If you are here
to reproduce, fill in sections 1–4 of the issue template first, then come back.

---

## Finding 1 — the published repository was 40 commits behind the machine

**Status: OPEN. Human decision, deliberately not automated.**

`git status -sb` on the machine that runs the cycles:

```
## feature/lidaction-guard...origin/feature/lidaction-guard [ahead 40]
```

Forty commits existed only on one laptop, on a feature branch, unpushed. Anyone
cloning the public repository was reading a system that materially differs from
the one producing the numbers in the reports.

This is not a bug to fix in code. Pushing, and merging a feature branch into
`master`, is Emil's decision and nothing in this repo does it automatically —
`scripts/publish_reports.py` exists precisely to stage a commit and then stop,
because the push is where a mistake becomes public. The finding is recorded
because "the code you are reading is the code that ran" is an assumption every
reproduction rests on, and here it was false.

**What a fork should do:** check `git log origin/master..HEAD` before trusting
that a clone is current, and say in your report which commit you actually ran.

---

## Finding 2 — `psutil` was required and declared nowhere

**Status: FIXED, 21 Aug 2026 (`requirements.txt` rewrite).**

A clean venv installed from the old `requirements.txt` — `requests`, `flask`,
`chromadb`, `pytest`, four names — could not run the suite. `psutil` is imported
by twelve modules including `memory/heartbeat.py` and
`agents/body/body_scanner.py`, i.e. the first things any run touches, and
appeared in no requirements file in the repository.

Re-testing after adding it by hand surfaced two more of the same class:

```
ERROR test/test_dashboard_freshness.py   ModuleNotFoundError: No module named 'flask'
ERROR test/test_training_record.py       ModuleNotFoundError: No module named 'numpy'
!!! Interrupted: 2 errors during collection !!!
1299 tests collected, 2 errors
```

`flask` was in the old file and had been dropped in a later edit; `numpy` never
was. Both are unguarded module-level imports, so they are *collection*-time
dependencies, not merely runtime ones.

The list is now derived rather than remembered: an AST scan of all 423 tracked
`.py` files for every top-level import that is neither stdlib nor a module of
this repo, resolved through `importlib.metadata.packages_distributions()` and
pinned to the version in `venv/`. Media, browser and desktop extras moved to
`requirements-media.txt`.

**Proved after the fix, on two clean venvs:**

| interpreter | `pip install -r` | `pytest --collect-only` |
|---|---|---|
| CPython 3.14.5 (this machine) | exit 0 | 1332 tests, 0 errors, 2.10 s |
| CPython 3.12.10 (the CI version) | exit 0 | 1332 tests, 0 errors, 4.17 s |

---

## Finding 3 — eleven failures on Linux that Windows does not produce

**Status: OPEN, and PARTLY UNVERIFIED HERE. Read the caveat.**

The 21 Aug fork test reported eleven test failures on Linux that do not occur on
Windows.

**The per-test list is not in our hands, and it is not reconstructed here.**
Attempting to reproduce it on this machine failed: WSL is registered but cannot
start —

```
The operation could not be started because a required feature is not installed.
Error code: Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE
```

— the Virtual Machine Platform feature is not enabled, and enabling it needs a
reboot, which would have killed the cycle that was running. No Docker on this
machine either. So the count is repeated from the fork test's report and the
list is absent, and inventing eleven plausible test names would have been worse
than saying so.

**This is the finding a fork can close for us in ten minutes.** On any Linux
box:

```bash
python3 -m venv venv && venv/bin/python -m pip install -r requirements.txt
PYTHONIOENCODING=utf-8 venv/bin/python -m pytest test/ -q -m "not network" \
  2>&1 | tail -40
```

Diff the `short test summary info` block against the Windows list below and file
the difference. `.github/workflows/ci.yml` now runs `ubuntu-latest` alongside
`windows-latest`, so the next push produces this list automatically — but a
human running it on a real machine is worth more, because CI shares our pins and
our Python.

Finding 4 is one confirmed member of this class, found by reading rather than by
running.

---

## Finding 4 — the `Z:/` bug: a test that tested nothing on Linux

**Status: FIXED, 21 Aug 2026 (`test/test_heartbeat_coverage.py`).**

```python
monkeypatch.setattr(hb, "HEARTBEAT_PATH", Path("Z:/nonexistent/dir/hb.json"))
hb.beat("x", "1")   # must not raise
```

The test is called
`test_beat_never_raises_even_if_the_path_is_unwritable`. On Windows `Z:/...` is
an absolute path on an unmapped drive, so the write fails and the test measures
what it claims. **On Linux `Z:/nonexistent/dir/hb.json` is an ordinary relative
path.** `hb.beat()` creates a directory literally named `Z:` inside the working
directory, writes the heartbeat into it, and passes — having exercised the happy
path under the name of the failure path, and leaving a junk directory in the
checkout.

Fixed by building the unwritable path from `tmp_path`: a real *file*, with a
child path underneath it, so `mkdir` fails with `NotADirectoryError` on every
platform. The test now also asserts the write actually failed, so it cannot
silently pass by succeeding again.

**Two more hardcoded drive letters were found in the same sweep and fixed:**

- `core/axis_task_executor.py` — `BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"`.
  Not merely machine-specific: it names `CORTEX++`, while the file lives in
  `CORTEX++_MERGED`. On the one machine where it resolved at all, it resolved to
  a *different checkout's* `logs/`. Everywhere else `LOGS_DIR` did not exist and
  every function returned `None` with a printed excuse — indistinguishable, in
  the output, from "there was nothing to execute". Now repo-relative, with
  `CORTEX_BASE` as the override the supervisor already sets at spawn.
- `check_axes.py` — an absolute path into `CORTEX++_QWEN`, the archived system
  whose scheduler was disabled on 2 Jul 2026. Now repo-relative.

The remaining drive letters in the repository are in `safety/safe_path.py`,
`safety/protected_paths.py`, `test/test_safe_path.py`,
`test/test_protected_paths.py` and `test/test_guardian_diagnosis.py`. Those are
deliberate and must stay: they are the code that *rejects* drive-absolute paths
and the tests that prove it does.

---

## The Windows red list, measured

`venv\Scripts\python.exe -m pytest test\ -q`, 21 Aug 2026, on the machine that
runs the cycles:

```
20 failed, 1266 passed, 1 skipped, 1 xfailed, 16 warnings in 520.78s (0:08:40)
```

```
test/test_cerebras_budget.py::test_other_openai_backends_still_send_plain_max_tokens[_call_groq-GROQ_API_URL]
test/test_cerebras_budget.py::test_gemini_still_sends_plain_max_output_tokens
test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk
test/test_declared_step_inputs.py::test_an_undeclared_step_still_refuses
test/test_declared_step_inputs.py::test_the_scanner_prefers_the_written_declaration
test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in
test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data
test/test_level_reconciler.py::test_climate_global_risk_is_corrected_to_high_under_the_ruling
test/test_level_reconciler.py::test_the_correction_row_carries_the_translation
test/test_metta_parallel.py::test_the_live_climate_fact_is_what_we_think_it_is
test/test_metta_parallel.py::test_r3_fires_on_the_live_climate_contradiction
test/test_metta_parallel.py::test_the_disagreement_states_both_readings
test/test_metta_parallel.py::test_hyperon_and_the_reference_agree_on_live_data
test/test_metta_parallel.py::test_an_empty_hyperon_result_does_not_erase_the_reference
test/test_notary_gate.py::test_execute_patches_never_reaches_full_trust
test/test_notary_gate.py::test_the_phantom_is_still_the_thing_holding_the_gate
test/test_script_suite.py::test_script_style_suite[experiments/dreams/test_dream.py]
test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]
test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]
test/test_script_suite.py::test_script_style_suite[test/test_origin_honesty.py]
```

**A confound worth knowing about before you compare.** That run happened while a
live cycle was running on the same machine. Several of those tests read live
artifacts — `test_level_reconciler` and `test_metta_parallel` say so in their
names ("on live data") — and a cycle rewriting `snapshots/` and `output/`
underneath them is a plausible cause for some of the twenty. The number is
reported as measured, under the conditions it was measured in, rather than
tidied up. If your idle-machine run gives a smaller number, that is a useful
finding about this list, not about your machine.

`test/test_metta_parallel.py` additionally needs the `venv312_metta` sidecar
(see `CLAUDE.md`); a fork without it should expect those five regardless of OS.

---

## What is not a finding

For completeness, so nobody files these:

- **`ruff check .` reports thousands of findings.** Measured 17 Aug 2026: 3311
  over 393 files with ruff's default rule set, 754 restricted to `E4,E7,E9,F`.
  No ruff config is committed, deliberately — the raw number comes first. The CI
  job is informational.
- **`tests/` (plural) is not a directory.** The suite is `test/`. An empty
  `tests/` existed untracked on the machine and was removed; a CI step that
  named it once reported a green check it had not earned.
- **The suite is slow.** 8m40s. `test/test_script_suite.py` spawns 25
  subprocesses, each with its own interpreter start-up.
