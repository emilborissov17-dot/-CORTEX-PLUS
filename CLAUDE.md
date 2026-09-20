# CORTEX++ — agent instructions

Започни с claude/reports/STATE_2026-09-12.md.

## Python interpreter

Never call bare `python` in shell commands on this machine — it is not on PATH and fails silently (empty output, exit code often swallowed by a trailing `2>/dev/null`). Always invoke the venv interpreter explicitly and force UTF-8 I/O:

```
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe -c "..."
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe script.py
```

## Before you build anything: check whether it already exists

Added 2026-08-03 after two duplicates were written into this repo in a single session —
`config/data_providers.json` against the live `config/providers.json`, and
`core/creative_tick.py` against the already-running creative tick in
`experiments/pulse/pulse_continuum.py`. A second implementation that looks authoritative and
is loaded by nothing is worse than a missing file: the next reader has to work out which one
is real.

Mandatory, in this order, before writing a new module or config:

1. **List the target directory.** `config/`, `core/`, `experiments/<area>/` — read what is
   already there before adding a neighbour.
2. **Grep for the loader.** `grep -rn "<filename>" core/ experiments/ scripts/` — if nothing
   imports or reads it, you are about to create dead weight.
3. **If you are implementing from a spec, check whether the spec is already implemented.**
   `SPEC_*.md` items are frequently already live under `experiments/`. Search for the spec's
   own artifact path (e.g. `memory/idea_stream.jsonl`) before writing a producer for it.
4. **Check the taxonomy files before inventing a category.** `config/reporter_independence.json`
   defines exactly four independence classes. Do not add a fifth.

## After you build anything: prove it ran

Never report "works" or "built" from a smoke test in a scratch directory. The claim is only
allowed after:

1. the file is on disk at the intended path, with the expected size and a fresh mtime;
2. the code was executed **against this repo**, not a synthetic copy, and its real output is
   quoted verbatim;
3. every integration the module depends on was checked for existence in THIS repo — a missing
   module makes a documented feature inert, and describing project intent as working state is
   the failure mode this section exists to stop;
4. anything that could not be verified is reported explicitly as UNVERIFIED, with one command
   the human can run to close the loop.

Every new module ships a `--selftest` that reports which of its integrations are LIVE and
which are INERT in the repo it finds itself in. A module that degrades silently lets a claim
stay true in the docstring and false on disk.

## Two model biases — double defense

TWO MODEL BIASES — DOUBLE DEFENSE (see claude/NORM_TWO_BIASES_DOUBLE_DEFENSE_7SEP.md).
Biases: (1) helpfulness — produce/recover instead of refuse; (2) least-resistance —
satisfy the letter/easy proxy, not the intent. For each, ship BOTH a sharp instruction
AND a mechanical net. When writing any code or tests:
 - Say plainly what a REFUSAL / no-output success looks like, and name the forbidden fallback.
 - Ask for the failure paths (plausible-but-wrong outputs) before the happy path.
 - For each guard/check: add a mutation test that FAILS if the guarded thing is removed.
 - Structural tests check code (identifiers/behaviour), never prose (no grep/docstrings).
 - Put a mechanical net (raise-not-return, no-live-writes, refuse-loud) behind the instruction, not just the instruction.

## Three questions are answered by tools/ask.py, never by a grep

Added 2026-09-20, after the same mistake twice in one day: a question about the
repo was answered with an ad-hoc grep for ONE literal string, and the empty
result was reported as the answer to a BROADER question. "Does this file contain
the string extracted_at" is not "does this record carry an observation date" —
memory/browse_sources/*.json carry `data_date`, and config/field_names.json now
registers thirteen spellings of that one concept, including a whole per-indicator
year map under `_observed_years`.

A GREP FOR ONE SPELLING IS WRONG WHENEVER THE CONCEPT HAS TWO. It is wrong in the
worst direction, too: it returns nothing, and nothing reads exactly like a
negative answer.

So these three questions have ONE implementation each, and it is the only allowed
source for the answer:

```
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe tools/ask.py observation-date <path>
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe tools/ask.py readers <path>
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe tools/ask.py callers <dotted.name>
```

  * **observation-date** — per record, whether an observation date is present
    under ANY registered spelling, which spelling, its value and its age. It
    never falls back to the file's mtime, and says so when there is none.
  * **readers** — which code READS a file. A mention in a docstring or a comment
    is not a reader. Segments match whole, so `registry.json` never matches
    `feature_registry.json`.
  * **callers** — every call site, and whether any LIVE caller exists outside
    `test/`. A function whose only callers are tests enforces nothing.

Every subcommand prints WHAT IT SEARCHED and HOW MANY candidates it examined, so
an empty answer can be told apart from a question that could never have returned
anything. Quote that preamble when reporting the answer.

A NEW SPELLING GOES IN config/field_names.json, with where it was found. Do not
invent one, and do not add a spelling to the tool — it holds none, which is what
makes the registry the single place a concept is named.

## Prose that asserts behaviour needs an assertion behind it

Added 2026-09-19, after a docstring sentence sent a whole command down a false trail.
test_heartbeat_coverage said "the watchdog's per-step ceiling is keyed on that id, so a
slow step reporting a fast step's number gets killed early". Every identifier in it was
real. The RELATION was invented: supervisor.ceiling_for() keys on the step NAME, and
config/scheduler.json carries seventeen ceiling keys, all names, zero ids. The sentence
was copied into a triage report as rank-1 evidence and planned against.

THE RULE. A docstring, comment or report may record a DECISION or a RULE freely — what
we chose, why, what is forbidden, what happened on which date. But a sentence that
asserts how the code BEHAVES — what keys on what, what reads what, what a module
guarantees, what a grep returns, how many of a thing there are — is allowed ONLY if an
assertion exists that FAILS when it stops being true.

No test behind it: the sentence is DELETED. Not softened, not hedged, not moved into the
passive voice. A vaguer claim is the same defect at lower resolution, and it is harder to
falsify, which makes it worse rather than better.

WHAT THIS DOES NOT COVER, and it is the larger half. A mechanical scanner can check that
every identifier, path and line number in a sentence EXISTS. It cannot check that the
relation between them is true — which is exactly what the watchdog sentence got wrong.
Measured on this repo the same day: an automated pass over the claims produced 17 flags
and essentially all of them were false positives, while the four genuinely false
sentences were found only by reading the code. Do not report a scanner as verification.

TWO SHAPES THAT ROT FASTEST, from the 2026-09-19 sweep:
  * a line-number citation (`supervisor.py:642-643`) — 2 of the 9 in the repo were
    already pointing at different code;
  * a present-tense COUNT ("the quarantine holds 38 patches" — it holds 5).
Prefer naming the symbol over citing the line, and prefer a test that counts to a
sentence that does.

## Where module paths actually are (verified 2026-08-03, correct these if they move)

- symbolic oracle: `experiments/symbolic_duel/metta_oracle.py` — **not** `core/metta_oracle.py`.
  Runs MeTTa through the `venv312_metta` sidecar. API: `ask(levels, rules, timeout)`,
  `levels_from_scores(path)`.
- provider registry: `config/providers.json`, read by `core/provider_catalog.py`.
- SDG goal→axis routing hint: `config/sdg_axis_map.json` (routing only — never a filter).
- axis→candidate series and semantic sources: `config/axis_source_map.json`.
- reporter independence org→class table: `config/reporter_independence.json`.
- creative tick / ideation: `experiments/pulse/pulse_continuum.py` (SPEC_penumbra_pulse.md
  Part B item 7), fired by the `CORTEX_Pulse` scheduled task, writes `memory/idea_stream.jsonl`.
