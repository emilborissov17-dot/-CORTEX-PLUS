# OPENCLAW — open sources, one criterion (command C-OC-3, 1 Oct 2026)

Ruling R27: what we attribute to a source must really be in that source. Every fetched page passes whole;
two refusals remain (a quote not on the page; a label contradicting the source's structure). Every number
below comes from a command run in this session, or is marked UNVERIFIED.

## What does not work

1. **planetary-agent can probably still reach a shell — through agent `main`** (Part 6, read-only, nothing changed).
   `exec`/`process` are gone from its catalog (gateway log: `cataloged 48 tools` → `cataloged 46 tools` at 15:44:19
   after the deny reload). But no `tools.agentToAgent` key is set, so `sessions_send` to `main` is allowed
   (openclaw dist `session-visibility-*.mjs:235`, `routingA2A?.enabled !== false`), and `main` runs claude-cli with
   `security` defaulting to `"full"` → `--permission-mode bypassPermissions` (`cli-shared-*.mjs:107-113,354`).
   UNVERIFIED end to end. Suggested fix (NOT applied — your call): `"tools": {"agentToAgent": {"enabled": false}}`
   and add `sessions_send`, `sessions_spawn`, `terminal` to planetary-agent's deny list.
   Close the catalog question: `openclaw gateway call tools.effective --params '{"sessionKey":"agent:planetary-agent:main"}'`.
2. **KNOWN is MISSING on the board.** Statement labels (subcategory by embedding) are not computed yet. Embedding
   runs detached (PID 17764, log `claude/reports/KNOWLEDGE_EMBED_1OCT.*`) at **~7.1 sentences/s** measured
   (10,240 vectors 16:41→17:05), not the 20.8/s probe — flattened JSON lines are long. That pass covers the 132,177
   statements it loaded (~4.8 h); the ~59k added afterwards need a second `--embed-pending --label` run.
3. **The finder's queries are crude.** Declared needs (39 from `memory/composer_needs.json`) rank first, so the
   default 5-per-pass finder will spend ~8 passes on them before any world subcategory is searched. Queries built
   from axis names fetch junk: "cosmic resources official annual statistics" returned an astrology site (HTTP 429).
4. **`brain_needs` does not exist.** No file, producer or reader in this repo. `core/needs.py` uses the composers'
   declared hunger as the declared tier and its selftest says `brain_needs: INERT`.
5. **Coverage did not move.** Before and after the finder run: KNOWN MISSING · MEASURED 38/105 · CURRENT 30/105 ·
   SEEN 2/105. The finder adds statements; until labels exist they count toward nothing.
6. **The volume is dominated by a few JSON dumps.** Of 129,551 web statements, 82,559 come from one source
   (`scout:NASA-EONET:6ff38f86`), and two UNSD sources contribute 10,514 each. Every flattened row is a statement.
7. **A "discovered source" is our own snapshot.** `scout:UCDP/PRIO:cbd450c7` has url
   `local://snapshots/master/global_indicators_latest.json` (lifecycle ledger: `InvalidSchema`). The fetch standard
   now refuses it by scheme; the scout that registered it is unfixed.
8. **Old `.metta` atom lines keep epoch-ms periods** (e.g. `"1790857400000"`) — written before Part 0, append-only.
9. **No PDF reader** is installed; a PDF page is recorded as a need, its text is not ingested.
10. **Nightly derivations steer almost nothing** (Part 7c, below).

## Part 0 — atom identity excludes the feed's clock (0acfee6, committed earlier)

## Part 1 — every fetched page passes whole (e2591c6, 54d7178)
- `core/knowledge.py` (new, `--selftest`): body→text (JSON flattened losslessly, HTML reduced), ingest with
  content dedup, embed (nomic-embed-text), labels (kind, subcategory ≥0.55 else `unplaced`, source_class,
  corroborated_by hosts ≥0.90), `read(need,k)` over statements AND atoms.
- `quote_gate.REQUIRED` back to six; declarations are labels; OWID seed passes with `period_how=parallel_index`
  (value 1930, period 2026).
- 1f tests in `test/test_open_criterion.py` (12) and `test/test_knowledge.py`, a mutation per refusal.
- 1g, two real chain runs:

| | run 1 (chain-20261001-162755) | run 2 (chain-20261001-163329) |
|---|---|---|
| sources | 82 | 82 |
| pages ingested / same content | 80 / 1 | 8 / 73 |
| statements added | 128,828 | 748 |
| carded / stored / label_refused / unreachable | 65 / 15 / 1 / 1 | 10 / 15 / 1 / 1 |
| judge: accepted / refused / atoms_written | 63 / 2 / 9 | 2 / 1 / 2 |

  Run 2 re-wrote 25 unchanged sentences of two changed USGS feeds. Fixed in 54d7178 (a changed page writes only
  its new sentences; mutation test); the 25 rows were removed from the store (backup kept in scratch).
  Manifest after: atoms_total 70, atoms_live 68, collapsed 2.

## Part 2 — sources are open, a fetch standard replaces the fence (11e50a3)
- `core/fetch_standard.py`: GET only; no credentials/cookies/auth headers/posts; no private/loopback/LAN on the
  literal, the resolved name, or any redirect hop; ≤5 MB; ≤30 s; 1 request/host/2 s. 32 tests, a mutation per rule
  (the method rule by source mutation). Parked after 3 consecutive failures; unparked when a need names it.
- Config header rewritten as the SEED.
- Existing caches ingested per item under the item's own url (a model's `analysis` block is not ingested):

| origin | items | statements added | already held | same content |
|---|---:|---:|---:|---:|
| web_intelligence | 26,839 | 30,602 | 1,379 | 17,942 |
| transcript_cache | 824 | 5,493 | 2,626 (the earlier transcripts) | 0 |
| news | 23,540 | 19,940 | 1,557 | 17,453 |
| browse_sources | 6 | 6 | 0 | 0 |

## Part 3 — the finder (7e09adf, d117826)
- Search: `web_intelligence_agent._ddg_search` (ddgs 9.14.4), GDELT fallback. Proof: "Antarctic sea ice extent
  2026" → 5 results in 4.4 s (nsidc.org, phys.org, nipr.ac.jp, argo.net, science.nasa.gov). `core/data_scout.py`
  uses a local model and is not in this path. No model anywhere in needs/finder (AST test).
- Chain: worker → finder → card_intake (`tools/openclaw_chain.bat`, asserted from its `%PY%` lines).
- Real run (66 s): 144 needs emitted (39 declared); 5 taken; 16 pages fetched; 4 unreachable (one >5 MB refused by
  the standard, HTTP 203, 403, 429); **3,302 statements gained**. Ledger `memory/vertical_ledger.jsonl`, rows:
  EMITTED 1, TAKEN 5, SEARCHED 5, UNREACHABLE 4, FETCHED 5, GAINED 5
  (gains 1138 / 602 / 181 / 500 / 881).

## Part 4 — coverage reads through core.knowledge (0b5ac84, eaa593e)
Board row: `world: KNOWN MISSING/105 · MEASURED 38/105 · CURRENT 30/105 · SEEN 2/105`

| domain | KNOWN | MEASURED | CURRENT | SEEN |
|---|---|---:|---:|---:|
| A | MISSING/26 | 14 | 11 | 0 |
| B | MISSING/41 | 14 | 11 | 0 |
| C | MISSING/25 | 9 | 7 | 1 |
| D | MISSING/13 | 1 | 1 | 1 |

The snapshot-evidence SEEN stays in the coverage file as a labelled legacy diagnostic, not on the board.

## Part 5 — tests read fixtures; K2 rests on a fact (520ec52)
- Five metta_parallel tests + the June belief_revision test read frozen fixtures. `test/_live_net.py` raises AND
  records any read under memory/, snapshots/, cortex_memory/ — it caught two more tests reading
  `memory/llm_provenance.jsonl`. The June test now asserts the guard that actually holds (status `unresolvable`,
  then the missing method; `no_interval` is never incremented anywhere), a mutation per layer.
- `K2_NOT_WIRED_UNTIL` deleted. The reason now: nightly step 12.68 `agents/axis/axis_feed.py` reads neither atoms
  nor trusted feed rows — asserted from its AST, with a mutation, and the runner is asserted to call that module.

## Part 6 — planetary-agent (read-only) — see "What does not work" #1
Deny is applied before the tool_search catalog is built (`agent-tools-*.mjs:649,688` → `applyToolPolicyPipeline`;
catalog from the filtered `effectiveTools`), so `tool_call` cannot reach exec/process. `terminal` exists (sandbox
off) but input throws under `policy.mode === "deny"`. `nodes`/`computer` are inert (no paired node). The 46 names
are UNVERIFIED beyond the six in the stored trace.

## Part 7 — MeTTa (read-only)
- **7a.** `C:\Users\emilb\Desktop\AGI\OMEGA_EXPERIMENT\PeTTa` (trueagi-io/PeTTa, ae66fa8) and
  `PeTTa\repos\Omega` (singnet/Omega, 78c6691). **Present:** `Omega/lib_nal.metta` (202 lines),
  `Omega/lib_pln.metta` (309), `PeTTa/lib/lib_pln.metta` (466). SWI-Prolog installed. Nothing downloaded.
- **7b.** hyperon 0.2.10 in venv312_metta, five real atoms (A1.1×2, C2.1, C5.1, B3.1):
  ```
  !(match &self (obs "A1.1" $k $p $per $v $u $c $h) ($k $per $v))
  !(match &self (obs $s $k $p $per $v $u "independent" $h) (add-atom &self (independent-reading $s $k $v)))
  !(match &self (independent-reading $s $k $v) ($s $k $v))
  ```
  Output: `[("child_wasting_pct" "2024" 6.6), ("severe_food_insecurity_pct" "2024" 10.142652)]`, `[()]`,
  `[("C5.1" "quake_m45_count" 14.0)]`. import 0.035 s, run 0.029 s, total 0.064 s.
- **7c.** (readers via `tools/ask.py`, 995 modules examined)
  - `core/deduction.py` (step 12.65, pure Python, "MeTTa mirror pending"): rules R1–R7 →
    `memory/deductions_latest.json`. Readers: daily_analysis_agent (display), needs_report (human brief),
    `core/reconsider.py` uses only the conclusion COUNT for the rollback-right streak.
    `memory/deduction_rule_stats.json` is written and never read.
  - `core/metta_check.py` (every beat, real hyperon): `(consumers $s)` queried; `(needs $s)` defined, never queried.
    The irreversible-step gate refuses when MeTTa did not RUN — not on anything it derived.
  - `core/metta_parallel.py` (step 25.35): R1–R5 → `memory/metta_assessment_latest.json`; hyperon result used only
    when equal to the Python reference. R3/R4 reach the D_SCORE phase report — one cycle stale (D_SCORE ends before
    25.35). R1, R2, R5 are written and never read. Tonight: R3 0, R4 14.
  - Summary: no derived rule content steers a decision.

## Tests
Each part's commit was gated on its related suites (623 passed at Part 5, RC 0). Those suites did not include
`test_behaviour_claims_are_backed`, and the first full run caught it red: 22 new behaviour sentences from the
C-OC-1..3 work. Fixed in eff9de1 — 5 deleted (false since C-OC-3, or unbacked: "the store the brain reads" —
core/brain.py does not read it), 17 entered as BACKED with their tests named; UNBACKED debt 612 → 611.

Full gate on HEAD eff9de1 (`-m "not live_state"`), run as two processes:
- everything except the render sweep: **5894 passed, 17 skipped, 22 deselected, 6 xfailed — RC 0** (1910.9 s)
- `test/test_cockpit_render_sweep.py`: **117 passed — RC 0** (694.0 s)
