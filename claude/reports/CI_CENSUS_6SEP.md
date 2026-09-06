# CI CENSUS — the check has been red for 15 days, so it stopped being a check
### 6 September 2026. Read-only. Nothing committed; the choice at the end is Emil's.

## What runs on a push to `feature/lidaction-guard`

**`.github/workflows/ci.yml` only.** `codeql.yml` is `branches: [master]`, and the API
confirms it: **110 of 110 runs on this branch are named `CI`** — CodeQL has never
fired here. `ci.yml` is `on: [push, pull_request]`, so every push runs four jobs:

| job | OS | gate? | what it executes |
|---|---|---|---|
| `compile` | ubuntu | **HARD** | `py_compile` on every tracked `.py` |
| `install` | windows + ubuntu | **HARD** | `pip install -r requirements.txt`, then `pytest --collect-only` |
| `tests` | windows + ubuntu | informational (`continue-on-error`) | `pytest test/ -q -m "not network"` |
| `ruff` | ubuntu | informational | `ruff check .` |

## Why it fails — first failing step, latest completed run (34031007694, 7187373)

**`install` → step 4, "install the pinned closure", on ubuntu-latest.** Verbatim:

```
error: could not compile `pywinpty` (build script) due to 2 previous errors
    7 | #[cfg(windows)]
      |       ------- the item is gated here
ERROR: Failed building wheel for pywinpty
× Failed to build installable wheels for some pyproject.toml based projects
╰─> pywinpty
```

`requirements.txt:99` is `pywinpty==3.0.5` **with no environment marker**. It is a
Windows-only package; on Linux pip falls back to building it from source and the Rust
source is `#[cfg(windows)]`-gated, so it cannot compile. The same job on
windows-latest passes. The `tests` job on ubuntu dies at the same step, for the same
reason, before pytest is ever reached.

The other two reds are informational and do not fail the run: `tests` on windows is
**81 failed, 3724 passed**, and `ruff` reports **6110 errors** (3311 when the comment
in the YAML was written on 17 Aug).

## Since when — the last 30 runs

Last green: **2026-08-22 08:25, `5fa201c`**. First red: **2026-08-22 17:05, `7a36d19`**.
`pywinpty==3.0.5` entered `requirements.txt` in **`8f99bda`, 22 Aug 15:55, "embedded
terminal: a real shell, described honestly"** — 70 minutes before the first red, and
`git show 5fa201c:requirements.txt` has no `pywinpty` while `7a36d19` has it on line
99. **Every one of the 78 CI runs since has failed.** The last 30:

```
2026-09-06 12:10  fc9bdd2  IN_PROGRESS (running)
2026-09-06 12:06  5b120e5  IN_PROGRESS (running)
2026-09-06 11:42  7187373  failure
2026-09-06 11:38  e3a67a4  failure
2026-09-06 10:25  74f799f  failure
2026-09-06 10:24  df8ef22  failure
2026-09-06 10:00  78cff71  failure
2026-09-06 09:36  7671c54  failure
2026-09-06 09:35  fcc8b9d  failure
2026-09-06 09:10  ca0c8ed  failure
2026-09-06 09:06  3eb1e60  failure
2026-09-06 09:04  ae4f92b  failure
2026-09-06 09:01  9560e23  failure
2026-09-06 08:48  ea20087  failure
2026-09-06 08:35  e861e77  failure
2026-09-06 08:33  9f2ef34  failure
2026-09-06 07:22  b114f24  failure
2026-09-06 07:02  470c144  failure
2026-09-06 06:58  73b40ad  failure
2026-09-05 21:04  f1572bb  failure
2026-09-05 18:52  a58e513  failure
2026-09-05 18:37  76f1df2  failure
2026-09-05 18:05  eb0424b  failure
2026-09-05 17:46  7efc01c  failure
2026-09-05 17:16  bdf0859  failure
2026-09-05 17:14  d227dc5  failure
2026-09-05 13:01  c9105e6  failure
2026-09-05 12:41  e4acd15  failure
2026-09-05 12:38  8b294ff  failure
2026-09-05 08:53  f5a36bb  failure
```

## The finding that matters more than the cause

A permanently-red check hides new reds, and it has. Running today's commits locally on
CPU:

- **`test/test_suite_gate.py` — 7 failed, and they reproduce on this machine**, not
  only on CI: `assert 'INCOMPLETE' == 'INVALID'`. I introduced that at **12:36 today**
  (`7671c54`, "suite_gate: a run that did not finish is not a clean run"). The new
  `INCOMPLETE` branch at `tools/suite_gate.py:315` fires whenever pytest prints no
  summary line, which is the condition every one of those seven tests sets up, so it
  shadows the `INVALID` verdict they exist to pin. **A gate I wrote to stop silent
  passes now silently overwrites a verdict, and CI could not say so.**
- **`test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code` — genuine**,
  red locally and on CI (`core/receptors.py:695` and others).
- **`test_axis_history` (4) and `test_cadence_gate` (6) are green here and red on CI** —
  they read live runtime state (`measured_axes() now returns 0, was 13 on 6 Sep`;
  `trends.json has no series`). Environment, not defect.

So of the 81 CI reds, at least three classes are mixed together: genuine defects,
state-coupled tests, and a checkout with no runtime history at all — the largest group
by far is the third (`FileNotFoundError: D:\a\-CORTEX-PLUS\...`, `expected at least 133
reports, found 0`).

## Proposal — I recommend **(b)**, with one prerequisite that belongs to neither

**Prerequisite, independent of the choice:** `pywinpty==3.0.5 ; sys_platform == "win32"`.
One marker on one line turns both hard gates green. Neither (a) nor (b) addresses it,
and until it lands every proposal below still shows a red X.

**(b) — limit CI to what runs anywhere.** It is cheap, it is honest about what it
measures, and it is *demonstrably sufficient for the only regression this census
actually found*: `test_suite_gate` is state-free and would have gone red on `7671c54`
within a minute of the push. **(a) is the better instrument and the wrong one to build
first** — a NEW-reds-only gate needs a baseline, and the baseline is not the local ~20:
it is 81, it drifts every night as state changes underneath tests that pin today's
numbers, and marking the machine-dependent ones is not the four markers the brief
assumes (GPU / `.env` / V-Dem / `live_state`) but a fifth and much bigger category,
*"reads runtime state a fresh checkout does not have"*. A baseline that moves on its
own is a gate that goes red for reasons nobody caused, which is how CI got ignored in
the first place. One caveat on (b) as scoped: **`axis_history` cannot be in the
CI-runs-anywhere set as written** — it asserts `measured_axes() == 13`, which is a fact
about this machine today. Either it moves to fixtures or it stays on the machine.

Build (b) now; keep (a) as the goal once the marker vocabulary exists and the
runs-anywhere set has proved it can stay green for a week.
