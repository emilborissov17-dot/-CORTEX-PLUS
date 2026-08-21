# Contributing to CORTEX++

This is a one-person research system, not a product with a roadmap. The most
valuable contribution is not a feature — it is a reproduction report that
disagrees with us.

## Running the tests

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING = "utf-8"
venv\Scripts\python.exe -m pytest test\ -q
```

On Linux or macOS, `python -m venv venv && venv/bin/python -m pip install -r
requirements.txt && PYTHONIOENCODING=utf-8 venv/bin/python -m pytest test/ -q`.

Two things about this suite that will otherwise waste your time:

**It is not green, and that is documented rather than hidden.** 20 failed /
1266 passed / 1 skipped / 1 xfailed on Windows as of 21 Aug 2026. Every one is
listed in `docs/KNOWN_FORK_FINDINGS.md`. If your count differs, you have found
something — please file it.

**Twenty-five files in `test/` are script-style** (counted from `test/_script_style.SCRIPT_STYLE`, 21 Aug 2026; the root `conftest.py` docstring still says 21 — it is stale): they assert at import time and
end in `sys.exit(...)`. `conftest.py` excludes them from direct collection and
`test/test_script_suite.py` runs each as a subprocess, so a bare `pytest` still
covers all of them and a failure inside one fails the run. You can also run any
of them alone: `venv\Scripts\python.exe test\test_origin_honesty.py`.

`pytest -m "not network"` deselects the one module that makes a live outbound
request (`test/test_llm_models_exist.py`). It skips itself without credentials
anyway; the marker saves the timeout.

**Do not start a cycle to test a change.** `fast_cycle_runner.py` takes the
better part of an hour, writes to `memory/`, `snapshots/` and `output/`, and
collides with the scheduled `CORTEX_Supervisor` task if one is already running.
`memory/cycle.lock` will stop a second runner, but the first thing to check is
whether a cycle is already up.

## Files a machine may not edit

`safety/protected_paths.py` is the list, and it is the authority — this section
is a readable copy, not a second source of truth. Anything a self-generated
patch tries to write here is refused, by design, and the refusal is logged
rather than swallowed.

Whole directories: **`config/`**, **`safety/`**.

Individual files: `BOUNDARIES.md`, `civilization_goal.txt`,
`civilization_vision.txt`, `config/step_inputs.json`, `core/canon.py`,
`core/source_status.py`, `execute_patches.py`, `memory/cycle.lock`,
`memory/existence_ledger.jsonl`, `memory/heartbeat.json`,
`memory/scheduler_state.json`, `patch_guardian.py`,
`scripts/review_quarantine.py`, `scripts/triage_quarantine.py`,
`supervisor.py`.

The reasons are individually worth reading in that file, but the shape is one
idea: **a system that can widen its own limit does not have that limit.** The
scheduler's restart budget, the input contract that decides whether a step's
provenance is fresh, the ledger that records its own deaths, the guardian that
judges its patches, and the review scripts that quarantine them — a machine that
could edit any of those could pass its own gate by moving it.

A human editing them by hand is fine and normal. That is the entire distinction:
it has to be a decision someone made, in a diff that says so.

## The V-Dem rule

`data/V-Dem-CY-Core-v16.csv` and `data/vdem_cache/` are gitignored and must stay
that way. V-Dem's licence does not permit redistribution. Download it yourself
from v-dem.net.

**Never commit V-Dem data, in any form, to this repository or a fork of it** —
not the CSV, not a "small excerpt", not a derived per-country table that carries
the underlying values. The governance-axis code degrades and announces itself
without the file; that is the correct behaviour for someone who does not have it.

The same rule, for the same reason, applies to `*.mp4` and anything else under
`memory/transcript_cache/`: material fetched under a licence to *read* is not
material we may *redistribute*.

## Reproduction reports

Use `.github/ISSUE_TEMPLATE/reproduction_report.md`. It asks for your OS, the
commit hash, the suite result, and the first divergence.

**Report your numbers before you read ours.** The template puts the comparison
section last on purpose. A reproduction that begins by looking up the expected
answer is a spot-the-difference puzzle: it finds the differences you were already
looking for, and confirms whatever you started with. `docs/KNOWN_FORK_FINDINGS
.md` is written to be read *second*.

If a finding of ours does not reproduce on your machine, that is more interesting
than a new failure, not less. A machine-specific defect already written down as
settled is worse than an unknown one.

## About the CI badge

`.github/workflows/ci.yml` runs on `windows-latest` and `ubuntu-latest`, both on
CPython 3.12.

**Two OSes is not two opinions.** Same interpreter family, same pins, same
repository, same test code. The matrix catches path separators, case-sensitive
filesystems, line endings, and the drive-letter class of bug — and it caught a
real one: a test that asserted an unwritable path on Windows was asserting an
ordinary relative path on Linux, and passed there while testing nothing
(`docs/KNOWN_FORK_FINDINGS.md` #4). That is worth having.

It is **cosmetic redundancy, not independence.** Two green checks that agree are
one measurement reported twice. Nothing in this pipeline is an independent
verification of anything, and it should not be read as one. Independent
verification is a person on a different machine running the suite and reporting
a number before reading ours — which is what the issue template is for, and why
it is the contribution this project actually needs.

## Style

Match the file you are editing. The repo is bilingual (Bulgarian and English)
and deliberately so: the operator reads Bulgarian, the code and the commits are
in English. Comments explain *why*, and specifically why some past failure made
the line necessary — a comment that restates the code is noise, a comment
carrying the date and the symptom of the bug it prevents is the most valuable
thing in the file.

New modules ship a `--selftest` that reports which of their integrations are
LIVE and which are INERT in the repo they find themselves in. See `CLAUDE.md`
for the full conventions, including the rule about checking whether a thing
already exists before building it — this repo has grown duplicates before.
