# CORTEX++

A personal research system that tries to measure how a civilization is doing,
and to be honest about how badly it can do that. It runs once a night on one
Windows laptop. It reads public data — World Bank, NASA, national statistics,
RSS, YouTube transcripts — scores 24 axes grouped into 5 goal dimensions
(`config/target_config.json`), keeps a per-country well-being table for 217
countries (`output/wellbeing_all_countries.json`), and writes a report a human
reads in the morning. It is not a product, it has one user, and most of what is
interesting in it is the machinery for catching itself being wrong.

The organising idea is verification over assertion. A number that nobody
checked, presented next to a number that somebody did, teaches the reader that
neither was checked. So the system separates the two everywhere it can: axes
whose score comes from a live series are marked MEASURED and the rest ASSERTED
(`memory/measurement_honesty_latest.json`); a source earns trust by behaving and
loses it by drifting, in a ledger (`core/source_lifecycle.py`); every phase of
the nightly cycle must debrief itself citing a number from its own data, and
debriefs that fail are kept as failures rather than discarded; and the system's
own existence — started, killed, died, restarted — is an append-only hash-chained
file (`memory/existence_ledger.py`). Several of those mechanisms exist because
the thing they catch actually happened here first. That is the pattern to expect
from the commit history: a defect, then the instrument that would have found it.

## Running it on Windows

Everything below assumes the repo root as the working directory. **The system
Python is not on PATH on the author's machine; use the venv interpreter
explicitly.** Every command in this repo's docs is written that way for a
reason — a bare `python` fails silently there.

```powershell
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONIOENCODING = "utf-8"      # the codebase is bilingual; cp1252 will not do
venv\Scripts\python.exe -m pytest test\ -q
```

Optional browser, transcript and desktop extras live in
`requirements-media.txt` and are not needed for the suite or for a cycle:

```powershell
venv\Scripts\python.exe -m pip install -r requirements-media.txt
venv\Scripts\python.exe -m playwright install chromium    # the wheel is not the browser
```

**One cycle, by hand.** This is the recovery path and the one to use while
reading the code:

```powershell
venv\Scripts\python.exe fast_cycle_runner.py
```

It takes tens of minutes to somewhat over an hour, walks the 61 distinct steps grouped
into 7 phases (`config/cycle_phases.json` — 62 entries, because `body_scan`
runs in two of them), and tees its own output to
`memory/cycle_logs/cycle_<stamp>.log`. Do not start one while another is
running: `memory/cycle.lock` is checked at boot and a second runner aborts.

**Unattended.** `supervisor.py --tick` is the whole scheduler: it decides
whether to start the daily cycle (`daily_hour`, default 03:00 local), whether a
running cycle has gone silent past its step's ceiling and must be killed, and
whether a dead one may be restarted (`max_restarts_per_day`, default 2). It is
meant to be fired by Task Scheduler every few minutes — on this machine, the
`CORTEX_Supervisor` task at `PT5M`:

```powershell
schtasks /create /tn CORTEX_Supervisor /sc minute /mo 5 /tr `
  "\"%CD%\venv\Scripts\python.exe\" \"%CD%\supervisor.py\" --tick"
```

`venv\Scripts\python.exe scripts\micro_cycle.py --install` prints the schtasks
lines for the smaller local-only tasks rather than running them, so you can read
what you are about to install. Ceilings and budgets live in
`config/scheduler.json`, which is in the protected-path denylist: no
self-generated patch may edit it. A system that can widen its own restart budget
does not have one.

**What needs keys and what does not.** Copy `.env.example` to `.env`. The keys
are `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`
(the cloud LLM fallback chain, tried in that order) and `NASA_API_KEY`.
`YOUTUBE_API_KEY` and `EIA_API_KEY` are read if present.

With **no keys at all**: the test suite runs in full; the World Bank, NASA open
endpoints and RSS collectors run; scoring, the phase reports, the step contract,
the existence ledger, the self-mirror and the cycle report all run. What stops
is every cloud LLM call. The local brain (`core/brain.py`) talks to Ollama at
`http://localhost:11434` and needs no key, but it does need Ollama running with
a model pulled — `qwen3:8b` is what the phase debriefs ask for by name. Without
either, the reasoning steps degrade and say so; they do not crash.

## Forking and contributing

Read `CONTRIBUTING.md` first — particularly the list of files a machine may not
edit, and the rule about V-Dem data.

The short version: run the suite before changing anything and write down what
you got. `docs/KNOWN_FORK_FINDINGS.md` records the four findings from the first
fork test (21 Aug 2026), and the first reproduction report in it is our own.
File yours as a GitHub issue using `reproduction_report.md` — OS, commit hash,
suite result, and the first place your numbers diverge from ours. Report your
numbers **before** reading ours; a reproduction that starts by looking up the
expected answer is not one.

The suite is not green, and pretending otherwise would waste your afternoon.
Measured on this machine on 21 Aug 2026: **20 failed, 1266 passed, 1 skipped,
1 xfailed** on Windows, every failure named in `docs/KNOWN_FORK_FINDINGS.md`.
The 21 Aug fork test also reported eleven failures on Linux that Windows does
not produce; that per-test list is not in our hands and the same document says
so and gives the command that would produce it. A fork that sees a different
count has found something, and that is worth an issue.

## Reading the honesty

These are the files to open when you want to know whether to believe a number.

**`memory/measurement_honesty_latest.json`** — per axis, whether the score came
from a live series (MEASURED) or from a model's judgement (ASSERTED), and the
weight each class carries. The composite at the top of any report means very
little until you have read the measured share underneath it.

**`memory/source_lifecycle_ledger.jsonl`** (summarised by
`core/source_lifecycle.py`) — every observation of every source, and the
promotions and demotions that followed. A source is CANDIDATE until it behaves
consistently, TRUSTED after, and DEMOTED when it drifts. Belief in a source is
earned and revocable, and the record of both is here.

**`memory/phase_debriefs/<cycle>/`** — one file per phase, and **read the
`.rejected.json` files as carefully as the accepted ones.** A debrief must cite a
number that exists only in its own phase's evidence; one that would read equally
well under another phase's heading is rejected as `SWAP_GENERIC` and kept. On
21 Aug 2026 one cycle had six debriefs rejected six for six, and the next cycle
had six accepted that turned out to be the same sentence with the phase name
substituted. Both are still on disk. The rejections are the more informative
half.

**`memory/existence_ledger.jsonl`** — append-only, hash-chained, fsynced:
CYCLE_STARTED, CYCLE_FINISHED, CYCLE_KILLED, CYCLE_DIED, CYCLE_RESTARTED,
CYCLE_FAILED_BUDGET_EXHAUSTED. `python -c "from memory import existence_ledger
as l; print(l.verify())"` re-derives the chain and tells you whether the history
was edited. This is how "which step kills me?" is answered by counting rather
than by remembering.

**`output/facade_audit_latest.json`** and `python -m core.scorer_self_check` —
which axis scorers actually consumed real data this cycle and which quietly
returned a default. An axis can be scored and still be a facade; this is the
file that says which.

## What does not ship

Some of this is licensing and some of it is the machine's private state. None of
it is coyness — here is exactly what is missing and why.

- **The V-Dem dataset.** `data/V-Dem-CY-Core-v16.csv` and `data/vdem_cache/` are
  in `.gitignore`. V-Dem's licence does not permit redistribution; download it
  yourself from v-dem.net. Governance-axis code degrades and says so without it.
- **`.env`.** Only `.env.example` is committed, with empty values.
- **Media.** `*.mp4` is ignored. Video pulled for transcript work stays local.
- **Telegram credentials and approval state** — `memory/notify_channel.json`,
  `memory/pending_approvals.json`, `memory/approvals_ledger.jsonl` and the rest
  of the human-channel files listed in `.gitignore`.
- **`memory/cycle_logs/`, `snapshots/self/`, `memory/transcript_cache/`** —
  volume, not secrecy.

**And a thing worth saying plainly:** the four honesty artifacts named in the
section above are, at the time of writing, *untracked in this repository*. They
exist on the machine that runs the cycles and they are not gitignored — nobody
ever committed them. So a fresh clone has the code that writes them and none of
the history they contain, and the first `fast_cycle_runner.py` run is what
creates them. Most of the rest of `memory/` (377 files) *is* committed, which
makes the absence of these four easy to miss. It is recorded here rather than
discovered.

Everything asserted on this page was checked against the repo on 21 Aug 2026
before it was written: the axis and country counts against
`config/target_config.json` and `output/wellbeing_all_countries.json`, the
scheduled task against `Get-ScheduledTask CORTEX_Supervisor`, the key names
against `.env.example`, the ignore rules against `.gitignore`, and the tracking
claims against `git ls-files`. Where a claim could not be checked it was not
made.

`LICENSE` — MIT. `VISION.md` for what it is aimed at, `BOUNDARIES.md` for what
it is not allowed to do, `LAW_OF_THE_BRAIN.md` for the rules the reasoning parts
run under, `CLAUDE.md` for the conventions any agent working in this repo must
follow.
