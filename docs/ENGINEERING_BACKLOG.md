# CORTEX++ — Engineering Backlog

Working list of engineering fixes, with status and commit SHAs.

**Why this file exists:** this backlog previously lived only in a chat session and
was lost when the session ended — the next session had no idea what items 5–7
were. It lives on disk now. Keep it updated as items land.

Last updated: **2026-07-13**

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

## Conventions worth remembering

- **Python:** never call bare `python` — use `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe`.
- **Ollama is dead by convention.** Any subprocess/HTTP Ollama call in the live cycle
  path is a bug. Guarded by `test/test_no_ollama_in_live_path.py`.
- **A dead source is declared, not retried.** Add it to `config/dead_sources.json` with
  a date and evidence rather than letting it 404 every cycle.
- **Never let a fallback number pass as authoritative.** Label it (`score_source`,
  `_status: TRUNCATED`, `needs_reanalysis`) so downstream can tell.
