# CORTEX++ — agent instructions

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
