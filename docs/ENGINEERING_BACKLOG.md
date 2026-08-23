# CORTEX++ — Engineering Backlog

Working list of engineering fixes, with status and commit SHAs.

**Why this file exists:** this backlog previously lived only in a chat session and
was lost when the session ended — the next session had no idea what items 5–7
were. It lives on disk now. Keep it updated as items land.

Last updated: **2026-07-21**

---

## Operational blockers (host machine — no code, highest leverage)

### The machine sleeps mid-cycle — 12 of 13 catchup runs died 16–21 Jul

**Symptom.** Over 16–21 Jul the ledger recorded 15 starts / 1 finish / 12 deaths.
Every death log ends abruptly mid-line — **no traceback, no `MemoryError`, no
shutdown message** — with the body reporting HEALTHY (RAM 44–48%, CPU 3–5%) right
up to the cut. The deaths span every lifecycle point (some at 329 bytes before the
body scan, one 100 KB deep in Cerebras synthesis), so they are not one wedged step;
they are the **process being killed from outside** while it runs.

**Root cause (environmental, not code).** The daily cycle is scheduled for 03:00,
but the machine is asleep at 03:00 every night (all 16 catchups fired 5–7 h late,
~08:00–09:30, as `MISSED_RUN_CATCHUP`). It wakes only when Emil opens the laptop in
the morning; the catchup fires into the brief wake window and the machine re-sleeps
(lid/idle) before the ~60-min cycle finishes → the cycle is SIGKILLed mid-run. The
one clean finish (07-19, 3709 s) is the one morning the machine stayed awake.
**Autonomy is fake until the host stays awake for the cycle it wakes to run.**

**Required host settings (Emil, set once — Windows 11).** On AC power:
- **Never sleep on AC.** Settings → System → Power → Screen and sleep → *When
  plugged in, put my device to sleep after* → **Never**. (Or `powercfg /change
  standby-timeout-ac 0`.)
- **Do not sleep on lid close (AC).** Control Panel → Power Options → *Choose what
  closing the lid does* → *When plugged in* → **Do nothing**.
- **Wake timer for 03:00.** Either keep the machine awake overnight (above), or add a
  Task Scheduler wake timer: the supervisor's scheduled task → *Conditions* → **Wake
  the computer to run this task** = on, and Power Options → Sleep → *Allow wake
  timers* = **Enabled**. This lets the 03:00 run fire on schedule instead of as a
  5–7 h-late morning catchup.

Until this is set, no software fix changes the outcome — the supervisor's restart
budget (2/day) is exhausted every morning by cycles that are killed, not crashed.

---

## Done

### Item 3 + 3b — Shared LLM JSON extraction + truncation detection
**Commit:** `0cd1b00` · **Tests:** `test/test_llm_json.py` (35 cases)

Four divergent JSON extractors replaced by one `core/llm_json.py`.

- Cerebras `gpt-oss-120b` is a reasoning model. When `max_tokens` truncates before it
  finishes thinking, `message["content"]` is empty and `groq_backend` fell back to
  `message["reasoning"]` — so the parsers received raw chain-of-thought
  (`"The user asks: …"`, `"done thinking."`) instead of a payload.
- `cortex_llm_resource`'s hand-rolled brace counter miscounted braces **inside JSON
  strings** (`{"note": "}"}`).
- `internet_agent`'s greedy `re.search(r'\{.*\}', DOTALL)` grabbed from the first
  brace to the **last**, swallowing trailing prose.
- Naive first-`{` scanning locked onto decoy braces in the preamble.
- **No truncation detection anywhere** — a `max_tokens` cut raised the same error as
  "model returned garbage", so nothing ever retried.

Now: `extract_json()` `raw_decode`s at every candidate offset and keeps the widest
value of the expected type. Truncation is a distinct, retryable condition
(`finish_reason=length` normalised across all providers, structural unclosed-bracket
detection, the Cerebras empty-content→reasoning fallback, and leaked chain-of-thought).
`call_llm_json()` retries once at double budget, then raises `TruncatedJSONError`.
A prose refusal is deliberately **not** classified as truncation.

> **Fixture caveat:** the test fixtures are *reconstructed*, not captured. No raw
> Cerebras-era output survived on disk. Provenance is documented at the top of the
> test file. If a real sample is ever captured, add it verbatim.

### Item 4 — Transcript fetching
**Commit:** `94f3cd7` · **Tests:** `test/test_transcript_fetch.py` (27 cases, no network)

- **(a) Sticky IP-block fallback.** First block in a cycle switches the rest of the
  cycle straight to Playwright; resets next cycle (mirrors `_YT_QUOTA_EXHAUSTED`).
  Also bails on the *first* blocked language rather than grinding through all five
  (a block is per-IP, not per-language), and skips `yt-dlp` too — same IP.
- **(b) Bounded parallel Playwright contexts.** Count comes from
  `memory/adaptive_directives.json`, read exactly as `fast_cycle_runner` reads
  `workers=`; clamped to [1, 3]. At `workers=1` it stays fully serial.
- **(c) Cross-cycle transcript cache.** `memory/transcript_cache/<video_id>.json`,
  consulted before *any* fetch. Only real transcripts are cached — description
  fallbacks/timeouts are not, since caching those would permanently poison the video.

Latent bug fixed in passing: `_time_limit()` used `signal.signal()`, which raises off
the main thread — the new parallel fetch would have crashed on Linux.

### Item 5 — Dead endpoints
**Commit:** `ede1688` · **Tests:** `test/test_source_status.py` (18 cases)

- **UCDP** was wrong twice: the resource is `ucdpprioconflict` (not `conflict`), and
  the current version is `26.1` (not 25.1/24.1/23.1/22.1). Fixing both still yields
  **401** — UCDP introduced token auth. URL is now correct and sends
  `x-ucdp-access-token` when a token is configured.
- **CU Boulder sea level**: the `/sites/default/files/<YYYY-MM>/` paths were tied to a
  Drupal upload month and are gone. Files now live at
  `/files/<release>/gmsl_<release>_seasons_rmvd.txt`. Live check now returns 95.3 mm
  vs the 1993 baseline instead of `{}`.
- **New:** `config/dead_sources.json` + `core/source_status.py`. A gone/gated source is
  declared **once**, with a date and evidence, instead of failing every cycle forever.
  `DEAD` = never called; `NEEDS_AUTH` = called if its env var is present, skipped
  quietly if not. A missing/corrupt registry **fails open**.

> **To re-enable UCDP:** request a token (<https://ucdp.uu.se/apidocs/>), then set
> `UCDP_ACCESS_TOKEN=<token>` in `.env`. No code change needed.

### Item 6 — trend_tracker reported GOVERNANCE_RIGHTS as 0.0
**Commit:** `34f7d91` · **Tests:** `test/test_trend_tracker_score.py` (14 cases)

**Not** the suspected 0-100 vs 0-1 mismatch. `trend_tracker` never read the scoring
engine at all — it re-derived its own score by averaging raw metrics clamped with
`max(0, min(100, val))`. Governance uses World Bank **WGI z-scores on a −2.5…+2.5
scale** (world average ≈ 0). All three live values were slightly negative → all
clamped to 0 → mean of zeros = **0.0**, while the real scorer said **0.44**.

The same "every metric is a percentage" assumption was corrupting other axes:

| Axis | Was | Now |
|---|---|---|
| GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL | 0.0 | 44.0 |
| FOOD_REVIEW | 8.5 | 45.0 |
| SPACE_INFRASTRUCTURE_REVIEW | 100.0 | 50.0 |
| COSMIC_RESOURCES_REVIEW | 100.0 | 50.0 |
| GOVERNANCE_INSTITUTIONS_REVIEW | 13.87 | 45.0 |

Score now comes from `cortex_scoring_engine` (`output/cortex_scores_latest.json`,
0-1 → 0-100). The crude metric mean survives only as a **labelled** fallback
(`score_source`, `axes_on_fallback_score`, a printed warning).

Also: `trend_tracker` reassigned `sys.stdout` **at module import**, hijacking stdout
for every importer and breaking pytest's capture. Moved into `__main__`.

### Item 7 — Dead Ollama warmup
**Commit:** `3779e9d` · **Tests:** `test/test_no_ollama_in_live_path.py`

`web_intelligence_agent.run()` called `_warmup_ollama()` every cycle; nothing listens
on `:11434`, so every cycle opened with a connection-refused warning that masked real
startup errors. Removed. The guard test then caught **more** dead Ollama code in
`core/groq_backend.py` (`OLLAMA_URL`, `_get_ollama_model`, `_call_ollama`) — deleted.

Deliberately left alone: `body_scanner._ollama_status()` (misleading name, reads API
keys, makes no Ollama call) and `core/cortex_llm.py` (real Ollama client, but imported
only from `LEGACY/` and `OLD/` — not the live path).

### Item 10 — Giant snapshot archival
**Commit:** `8be841a` (+ locked-file move completed 2026-07-13)

`SelfAwareness → HistoryLoader → TrendAnalyzer.load_snapshots()` blindly `json.load()`d
the last 5 files in `snapshots/self/`, several of which had ballooned to 126 MB–8.8 GB.
Loading one raised a bare `MemoryError()` — and `str(MemoryError())` is `''`, which is
why the failure rendered as an **empty error string**.

- Loud errors: `_run()` and `HistoryLoader.load()` now print `type(e).__name__`.
- 5 MB size guard in `TrendAnalyzer.load_snapshots()`.
- `CodebaseScanner.scan()` scoped to project dirs (was globbing 6600+ files under `venv/`).
- 21 oversized snapshots moved to `snapshots/self_archive/` (gitignored).
  `snapshots/self/` went **8.3 GB → 13 MB**.

> **Open (human decision):** `snapshots/self_archive/` holds **45 GB**. Emil deletes
> manually after a few healthy cycles confirm the ballooning bug is gone. Quarantine
> principle applies to data too — keep one small sample regardless.
>
> **CLOSED 23 Aug 2026.** The directory does not exist on disk; the deletion
> happened. `snapshots/self/` now holds **59 files / 13.4 MB**, of which 23 files
> (12.7 MB) are older than 30 days — the old ones are the fat ones, which is the
> ballooning bug's residue. The `self_archive` skip guards in
> `core/metta_check.py` and `fast_cycle_runner.py` are deliberately kept and
> now say why.

### Dead weight, recorded not removed (23 Aug 2026)

`cycle.log` at the repo root — **233 KB, last written 29 July, and NOTHING in
this repository writes it.** A grep across every file type returns no writer.
`run_fast_cycle.bat` does not write it either: that script `cd`s to
`CORTEX++_QWEN` — the archived system, not this repo — and redirects into
`logs\fast_cycle_log.txt`.

The live stdout path is `memory/cycle_logs/cycle_<stamp>.log`, opened by
`supervisor.spawn_cycle()` with mode `"w"` before the spawn, or teed by
`core/cycle_log.tee_stdio()` when a cycle is started by hand.

It was **not** put on the negative allowlist by name: protecting a file no live
component writes would be protecting a fossil and would state a relationship
that does not exist. It is **not** deleted here either. It is one file, it is
recorded, and the decision is a human's.

> **Open (human decision):** delete `cycle.log`, or leave it. Nothing depends on
> it. The disk actuator would sweep it today only because it is 24 days old, and
> the actuator has no caller.

### Scheduler + Watchdog — the first autonomy rung
**Commits:** `a642dae` (denylist) · `012b7a9` (heartbeat) · `edf42e7` (ledger) · `a18b694` (supervisor)
**Design:** [SCHEDULER_DESIGN.md](SCHEDULER_DESIGN.md) · **Tests:** 116 across 4 suites

Windows Task Scheduler as a dumb trigger + a **stateless 5-min `supervisor.py --tick`**
(not a resident daemon — that would be the single point of failure with no supervisor).
`decide()` is a pure function, so the whole policy is testable offline.

**⚠️ NOT YET LIVE.** The scheduled task is not registered. Run `supervisor.py --install`
and execute the printed `schtasks` command. That is deliberately a human action.

Two live holes closed by the denylist along the way:
- `execute_patches.py` was in `PATCHABLE_FILES` — **the gate could rewrite the gate.**
- `ALLOWED_DIR_PREFIXES` permits `memory/`, where the heartbeat, lock and ledger live —
  generated code could have **forged its own existence history** or faked a heartbeat to
  defeat the watchdog.

---

## Noted — not urgent

- **LOW/HIGH naming confusion on `_RISK_` axes.** For a risk axis, a "HIGH" score is
  ambiguous: high *risk* or high *goodness*? The scoring engine's level labels read one
  way for `ENERGY_REVIEW` and the opposite way for `DEEP_TIME_RISKS_REVIEW`. Needs a
  polarity convention, not a per-axis patch.

- **AST gate could learn to trace literal paths through local helpers.** The gate
  currently rejects `write_text()` when the target is not *statically* verifiable —
  which is why 5 patches sit in quarantine with
  `"write_text() target not statically verif…"`. Teaching it to follow a literal path
  through a local helper function would clear the common false positive without
  weakening the guarantee.

- **`measurable_goal` quality rule for (G).** Proposals carry a `measurable_goal`
  field, but nothing enforces that it is actually measurable. Needs a rule that rejects
  vague goals at proposal time rather than at review time.

---

## Known-failing tests — baseline (2026-07-22)

These 4 reds pre-date the branch merges and are **outside the merged file set**.
Recorded as the accepted baseline during the master merge of the reviewed
branches (self-check #4 / K1a #5 / F1, climate, education-culture, keep-awake).
Suite is otherwise green (445 passed). **Do not treat these as merge-induced.**

- **UCDP sanity-band guard — REAL data/mapping bug.**
  `test/test_source_status.py::test_ucdp_real_csv_if_present_lands_in_the_sanity_band`
  fails: the actual local UCDP CSV yields `active_armed_conflicts = 2816`, far
  outside the measured 40–80 band (v26.1, 2018–2025). The guard is doing its job
  — it means the column mapping against the present CSV is wrong and the axis
  would report a fabricated conflict count. Fix: reconcile `gi.fetch_ucdp()`
  column mapping with the CSV actually on disk. Not fixed now.

- **`dreams` test-signature bug — 3 collection errors.**
  `experiments/dreams/test_dream.py::{test_facts,test_check_discriminates,test_write_and_sidecar}`
  error at setup: each is declared `def test_x(src: dream.Sources)`, so pytest
  tries to resolve `src` as a fixture and can't (`fixture 'src' not found`).
  Not assertion failures — the tests never run. Fix: build `src` inside each
  test (or add a `src` fixture) instead of taking it as a parameter. Not fixed now.

---

## Conventions worth remembering

- **Python:** never call bare `python` — use `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe`.
- **Ollama is dead by convention.** Any subprocess/HTTP Ollama call in the live cycle
  path is a bug. Guarded by `test/test_no_ollama_in_live_path.py`.
- **A dead source is declared, not retried.** Add it to `config/dead_sources.json` with
  a date and evidence rather than letting it 404 every cycle.
- **Never let a fallback number pass as authoritative.** Label it (`score_source`,
  `_status: TRUNCATED`, `needs_reanalysis`) so downstream can tell.

---

## Subtraction, 21 Aug 2026 — deleted with evidence

One commit, six targets, each with the grep that proves nothing calls it. Git
keeps the history; nothing was archived anywhere else.

| deleted | size | proof of zero callers | recoverable from |
|---|---|---|---|
| `LEGACY/` | 278 KB, 27 entries | `grep -rnE "^\s*(from\|import)\s+LEGACY" --include=*.py .` (excluding LEGACY/ and OLD/ themselves) → **no matches** | `git show 2afdcd1^:LEGACY/<file>` |
| `OLD/` | 16 MB, 31 entries | same grep for `OLD` → **no matches** | `git show 2afdcd1^:OLD/<file>` |
| `cortex_dashboard_generator.py` | 12.9 KB | `grep -rnE "import\s+cortex_dashboard_generator" --include=*.py .` → **no matches**. Every remaining mention is prose ABOUT it: `cortex_approval_server.py`'s own comment saying nothing in the cycle writes the dashboard, and `test_dashboard_freshness.py` asserting the string must not appear as a runnable command in the served page | `git show 14ca73c:cortex_dashboard_generator.py` |
| `fast_cycle_runner.py.bak_20260617_180555` | 12.8 KB | 0 references | blob `689449e0` already in git under the live filename |
| `hypercortex_runner.py.bak_20260618_134540` | 4.0 KB | 0 references | blob `d09db34f` already in git |
| `agents/cosmos/cosmos_snapshots_agent_qwen.py.bak_20260617_171145` | — | 0 references | blob `d1af3c9e` already in git |
| `data_providers/human/cognition_learning_provider.py.bak_20260617_160215` | — | 0 references | blob `a9f700ab` already in git |
| `data_providers/planet/ecosystems_biodiversity_review_provider.py.bak_20260617_160215` | 2.1 KB | 0 references | **NOT in git — this was the only copy** |

Three things worth saying out loud rather than leaving in a diff:

- **`data/patch_guardian/backups/*.bak` was NOT deleted, deliberately.** A blanket
  `*.bak` sweep would have taken all 78 of them, and they are not stale editor
  copies — `patch_guardian._rollback()` globs exactly `{filename}.*.bak` to undo an
  applied patch. Deleting them removes the undo, on the day the first patch is
  meant to be accepted.

- **The `.bak_*` files were gitignored (`.gitignore:16`), so git never held them.**
  Four of the five are byte-identical to a blob git already has under the live
  filename. The fifth was genuinely the only copy; it was deleted anyway, and here
  is why: it is the strictly older, strictly worse version of the ecosystems
  provider — the one still using `EN.ATM.CO2E.PC`, an indicator with no WLD
  aggregate, behind a bare `except:` and with no NOAA fallback. It holds nothing
  the live file does not, and it holds one thing the live file deliberately
  removed.

- **`hypercortex_runner.py.bak_20260618_134540` looked referenced and was not.**
  `reports/actions_run_log.json` mentions `hypercortex_runner.py.bak_20260327_...`
  — a different backup, in the CORTEX++_QWEN archive, from March. A `grep -l` on
  the prefix matches it; a grep on the full name does not.

**Newly orphaned as a consequence, NOT deleted (out of the named scope):**
`core/cortex_llm.py`. It was live only in the sense that `LEGACY/cortex4_v2 - Copy.py`
and `OLD/core_legacy/cortex4_v2.py` imported it — both now gone, so it has zero
importers anywhere in the tree. `test/test_no_ollama_in_live_path.py` documents it
as "imported only from LEGACY/ and OLD/, which are not the live path"; that
sentence is now stale in a way that matters, since there is no importer at all.
Decide retire-or-keep in a later pass.

**After:** `scripts/step_callmap.py` regenerates with **0 unresolved imports**
(unchanged — it was 0 before, so the deletion introduced none), 8 OPAQUE steps
(unchanged). `scripts/build_module_map.py` regenerates with 0 parse errors.
