# BRAIN NEEDS — the brain says what it needs (command C-NEED-1, 1 Oct 2026)

Emil, R29: the brain states what it needs and the finder serves it (COGNITION); every cell of the map is
worked in rotation and kept current (MAINTENANCE, not cognition). Every number below comes from a command
run in this session, or is marked UNVERIFIED.

## What does not work

1. **The 3B's needs are poor, and this is plain from the evidence.** The first reply (47.7 s) gave exactly
   five needs, one per sub-goal, in sub-goal order. None names a fact from the briefing: no refugees (the
   top measured row), no forward row, no place, `about` null in all five. The `would_change` lines paraphrase
   the sub-goal definitions. They were accepted, because code checks form, not value. Nothing was improved
   by hand.
2. **Asked to judge what came back, it called all five WRONG_QUESTION** (44.3 s, one generic reason per
   need: "general observations ... do not offer actionable solutions"). **Then, 50 s later, it re-asked all
   five word for word.** Before 78e3dfa that re-ask overwrote the closed records with fresh OPEN ones and
   erased their verdicts. Fixed: a need asked again is REOPENED, with its history kept. The five live records
   were restored from the ledger. The board's "emitted 10" includes those five pre-fix re-emissions.
3. **What the brain was shown was mostly off-target.** core.knowledge.read returned transcript fragments
   ("That's exactly the problem.", "Panama has a strange problem.") rather than the pages the finder had just
   fetched for that need. Cause, partly verified: only part of the store has vectors (the detached embed is
   still running); unembedded statements are ranked by word overlap, on a different scale from cosine. The
   finder's pages are linked by `need_id`, but read() does not prefer them. UNVERIFIED which share of the
   shown items each path produced.
4. **Engine needs are starved.** The finder takes N=5 open needs, brain first. The brain emits five needs
   every time, so the three forward-row needs (DRC/AFC, Sudan/SFA, Israel/Hamas) were never served:
   ENGINE NEEDS served 0. This follows from the ordering the command specifies; reserving slots would be a
   change to that rule — your call.
5. **No contradiction reaches the briefing today.** The one candidate was the same USGS source reporting 14
   then 15 quakes inside one rolling day. That is one source updating (CHANGED), not two sources
   disagreeing, so contradictions now require two different sources (c584a72). Result: zero VERIFY needs.
6. **Measurements are never linked to a need.** The finder ingests pages as statements; a searched page has
   no declared path, so no card and no atom is made. GAINED rows carry `measurements: 0` by construction.
7. **Maintenance's first pass worked only source cells.** All ten cells it took were `src:` cells: ties sort
   by cell id, and `src:` sorts before `sub:`. Subcategory cells come next pass. Re-fetching a seed source
   duplicates the worker, which fetches every seed on every chain run anyway.
8. **Three of my own defects were caught and fixed in this run**, and are listed so they are not repeated:
   - tests wrote 4 rows into the live `memory/observation_log.jsonl` (1a6f227);
   - a fixture without a `ledger` key wrote 29 rows into the live `memory/vertical_ledger.jsonl`, because
     `_p()` fell back to the live path; it now raises, and the rows were removed (d594c0e);
   - the maintenance pass worked one source twice and logged a refused source as FETCHED (1c719c1).
   `test/_live_net.py` now guards writes too, not only reads.
9. **`memory/brain_needs.json` did not exist** and nothing turned `brain_cycle_plan.json` into a search. The
   plan is still not read by the needs step: the briefing is built from facts, not from the plan's
   focus/watch, whose last `watch` was "DAILY::ai_activity.github_ai_repos_total vs vs vs vs vs vs vs vs".

## Part 0 — what C-OC-3 left, and who reads what (read-only)

HEAD before this command: eb42bcd, 0 ahead / 0 behind origin.
- reader: `core.knowledge.read(need, k)`; store `memory/statements.jsonl`; search `web_intelligence_agent._ddg_search`
  (via `scripts/openclaw_finder.repo_search`); ledger `memory/vertical_ledger.jsonl`; the C-OC-3 needs builder
  `core/needs.py` was the ranking R29 rejects, and was **deleted** in d594c0e.
- `tools/ask.py readers` (995 modules examined each):
  - `memory/brain_cycle_plan.json`: written by `core/brain.py` (PLAN.write_text); read by `core/brain.py` and
    `core/cycle_report.py` (indirect: `edges_runner.py`).
  - `memory/composer_needs.json`: written by `experiments/composers/composer.py`; read by `core/data_scout.py`,
    `experiments/browser_scout/autonomous_scout.py`, `goal_impact_collector.py`, `scripts/cortex_query.py`,
    `experiments/pulse/pulse_continuum.py` (ask.py lists the last as "no read/write use"; it reads through `_load`).
  - `memory/needs_brief.md`: written by `experiments/needs/needs_report.py`; **no reader** (0).
- Facts re-verified: `brain_needs.json` absent; plan focus "Verify process ownership consistency"; grounded
  ranking top measured row SOCIAL_RELATIONS_REVIEW refugee_population need 7.728; 85 pending hypotheses.
  The forward rows the command cited as `memory/metta_forward_F-*.json` are the witness's rule checks (no
  reader); the rows themselves are `experiments/institution/forward/F-*.json`, which the briefing reads.

## Part 1 — maintenance is rotation (6a62432, 1a6f227, 1c719c1)
- `core/maintenance.py`: 187 cells (105 world subcategories + 82 sources), ordered only by last-worked time.
- `core.atoms.write` registers every re-observation in the observation log: UNCHANGED (seen line, no atom),
  CHANGED (the new atom carries `changed_from`), NEW.
- Real pass, 10 cells, 3m20s. After `card_intake` judged its cards, the log shows one CHANGED
  (`surface_temp_c_sofia` 15.3, period 2026-10-01T15:30) and one UNCHANGED (Kp index 0.0).
- `config/taxonomy.json`: `candidate_sources` renamed `source_hints_unverified` (123 entries); `_meta` says
  Claude wrote them on 2026-10-01 unverified; no code reads them.

## Part 2 — a briefing in, well-formed needs out (c584a72)
`core/brain_needs.py`: briefing from code (text + MeTTa lines + sha256); cortex-l1b-3b through
`core.brain.think`; form checks only; SILENCE keeps the raw reply; engine needs (contradiction → VERIFY,
forward row → FIND); the model step is skipped and logged while a cycle is live or the 8b window is open.

## Part 3 — the finder serves the brain first (d594c0e, 78e3dfa)
Brain needs, then engine needs; the query is the brain's own question (+ place/actor/period). Pages are
ingested with `need_id`. `review()` shows the top-k items per searched need and records the verdict; code
never overrules it; no time expiry. Ledger per need: EMITTED, TAKEN, SEARCHED|NO_RESULTS, FETCHED, GAINED,
SHOWN, verdict (REOPENED when re-asked).

## Part 4 — one real loop, verbatim (no commit)

`ollama ps` before: `[['cortex-l1b-3b:latest', 2314803200]]` · after: `[['cortex-l1b-3b:latest', 2314803200], ['nomic-embed-text:latest', 595142656]]`. Model step busy check: `None`.

### The briefing (sha256 `f7509f0c45b2e9fdb2f416d47cd3e415c055a3573b86ea6049107a74f2cfec84`)
```
SUB-GOALS (the five): CIVILIZATIONAL_STABILITY, HEALTHY_ENVIRONMENTS, KNOWLEDGE_UNDERSTANDING, SAFETY, SUSTAINABLE_RESOURCES

WHERE THE SYSTEM IS FURTHEST FROM ITS TARGETS (need = weight x (1 - score)):
- GOAL_PROGRESS_REVIEW goal_score: value None , score None, need 8.0 (NOT MEASURED)
- SOCIAL_RELATIONS_REVIEW refugee_population: value 29429000.0 persons, score 0.034, need 7.728
- LONG_TERM_FUTURE_REVIEW (no key): value None , score None, need 7.0 (NOT MEASURED)
- FOOD_REVIEW food_insecurity_pct: value 10.1427 percent of population, score 0.2465, need 6.7815
- ENERGY_REVIEW renewable_energy_pct: value 19.7356 percent of total energy, score 0.2467, need 6.0264

CONTRADICTIONS (same key, place, period; different values): none

OPEN FORWARD ROWS (commitments being watched):
- F-001: Government of DR Congo (Zaire) - AFC in ['Nord Kivu province', 'Sud Kivu province']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
- F-002: Government of Sudan - SFA in ALL; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
- F-003: Government of DR Congo (Zaire) - AFC in ['Nord Kivu province', 'Sud Kivu province']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))
- F-004: Government of Israel - Hamas in ['Gaza Strip']; kept if sum(best) < 25 from 2026-10-01 to 2026-10-31 (UCDP GED); resolves release date + 14 days (expected around 2026-11-20 (UCDP extracts candidate data on the 20th of every month))

CHANGED SINCE THE LAST BRIEFING: nothing registered

YOUR PREVIOUS NEEDS AND WHAT HAPPENED: none yet
```

### The model's raw reply (cortex-l1b-3b:latest, 47.7 s)
```
{"needs": [{"question": "What are the most pressing issues to address?", "why_subgoal": "SUSTAINABLE_RESOURCES", "about": null, "kind": "FIND", "would_change": "focus on sustainable resources; lower risk of critical resource exhaustion and promote cyclical, regenerative flows."}, {"question": "How can we improve the conditions for life?", "why_subgoal": "HEALTHY_ENVIRONMENTS", "about": null, "kind": "FIND", "would_change": "address pollution and irreversible damage; maintain and improve the conditions for life."}, {"question": "What knowledge should be increased to understand complex systems better?", "why_subgoal": "KNOWLEDGE_UNDERSTANDING", "about": null, "kind": "FIND", "would_change": "investigate and structure knowledge; increase understanding of complex systems."}, {"question": "What actions can we take to avoid high-risk situations?", "why_subgoal": "SAFETY", "about": null, "kind": "FIND", "would_change": "identify and mitigate high-risk actions; prefer reversible strategies."}, {"question": "How can we reduce the risk of wars and collapses in sustainable civilisation?", "why_subgoal": "CIVILIZATIONAL_STABILITY", "about": null, "kind": "FIND", "would_change": "analyze and address factors leading to wars and collapses; promote fair distribution of resources."}]}
```

### Needs accepted (refused: 0; silence: None)
- `BN-6dddb2e609` brain FIND SUSTAINABLE_RESOURCES — What are the most pressing issues to address?
- `BN-580dae4f5e` brain FIND HEALTHY_ENVIRONMENTS — How can we improve the conditions for life?
- `BN-1340065e41` brain FIND KNOWLEDGE_UNDERSTANDING — What knowledge should be increased to understand complex systems better?
- `BN-e0f5781722` brain FIND SAFETY — What actions can we take to avoid high-risk situations?
- `BN-1bdc390518` brain FIND CIVILIZATIONAL_STABILITY — How can we reduce the risk of wars and collapses in sustainable civilisation?
- `EN-6278ddc06c` engine FIND  — Find current reports on Government of DR Congo (Zaire) - AFC in Nord Kivu province, Sud Kivu province for the period October 2026
- `EN-193ac3136d` engine FIND  — Find current reports on Government of Sudan - SFA in ALL for the period October 2026
- `EN-da6b7fe660` engine FIND  — Find current reports on Government of Israel - Hamas in Gaza Strip for the period October 2026

### Searches (40.8 s; 14 pages fetched, 6 unreachable, 8272 statements gained)
| need | query | hits | fetched | gained |
|---|---|---:|---:|---:|
| `BN-6dddb2e609` | What are the most pressing issues to address? | 4 | 2 | 159 |
| `BN-580dae4f5e` | How can we improve the conditions for life? | 4 | 4 | 641 |
| `BN-1340065e41` | What knowledge should be increased to understand complex systems better? | 4 | 3 | 389 |
| `BN-e0f5781722` | What actions can we take to avoid high-risk situations? | 4 | 3 | 733 |
| `BN-1bdc390518` | How can we reduce the risk of wars and collapses in sustainable civilisation? | 4 | 2 | 6350 |

### What was shown back
```
NEED BN-6dddb2e609: What are the most pressing issues to address?
  1. [statement] What are the biggest problems that we face in this country?
  2. [statement] But there are challenges.
  3. [statement] That's exactly the problem.
  4. [statement] And it really sets the stage for one of the most urgent challenges of our time.
  5. [statement] Panama has a strange problem.

NEED BN-580dae4f5e: How can we improve the conditions for life?
  1. [statement] what's possible and using that knowledge to improve life on Earth from developing new technologies that solve problems on Earth to inspiring future generations to reach for the
  2. [statement] existence and a good quality of life but points to a start humans are transforming the planet's natural habitat at an unprecedented rate Jonathan Vigliotti is in Los Angeles eluate in Los Angeles with what the future could look like
  3. [statement] A good education can make us richer, healthier and help us to thrive.
  4. [statement] Second, access to healthy diets is improved slightly to 2.6 billion people that cannot afford a healthy diet, the minimum cost healthy diet.
  5. [statement] Number two, we are going to make sure that our first [music] wishes broadly benefit humanity and that we kind of get the world to a place where a lot more people get to [music] have a lot more wishes wishes.

NEED BN-1340065e41: What knowledge should be increased to understand complex systems better?
  1. [statement] research it refers to AI systems that can understand learn and apply knowledge across various domains just like humans can AGI stands for artificial general intelligence which is another term for General ai ai is the hypothetical AI system that
  2. [statement] true understanding and generalizability remain Beyond reach the first stage of AGI involves delving into the intricate workings of the human brain scientists aim to comprehend and mimic the complexities found within our brains this stage includes replicating the
  3. [statement] what's possible and using that knowledge to improve life on Earth from developing new technologies that solve problems on Earth to inspiring future generations to reach for the
  4. [statement] does Humanity know what it's doing does Humanity know what it's doing no um I think we're moving into a period when for the first time ever we may have things more intelligent than us you believe they can understand
  5. [statement] such as recognizing faces playing games or writing code AI systems are usually designed to excel in specific domains such as chess image recognition or natural language processing General AI on the other hand is the ultimate goal of AI

NEED BN-e0f5781722: What actions can we take to avoid high-risk situations?
  1. [statement] Why would Russia risk this?
  2. [statement] So, why would Putin take such a huge risk?
  3. [statement] This I think is a dangerous situation.
  4. [statement] The combination is what makes the situation so dangerous.
  5. [statement] Rare PDS red flag warnings were issued, meaning a particularly dangerous situation was developing.

NEED BN-1bdc390518: How can we reduce the risk of wars and collapses in sustainable civilisation?
  1. [statement] If we can avoid wiping ourselves out, because the worry this century is that for the first time, one species, the human species, has the power to destroy all life.
  2. [statement] We're in aware of the risk of nuclear war, whereas now we have things that I worry about still more, engineered viruses producing lethal pandemics that spread worldwide.
  3. [statement] The future of human civilization will be what we make it.
  4. [statement] with devastating hurricanes refugee crisis and the real possibility of nuclear war it can sometimes feel like the end is near but what are the biggest threats to humanity and is there anything we can do to stop them experts
  5. [statement] It falls to us to apply the brakes that will prevent climate change becoming a runaway juggernaut that no one can stop.
```

### The raw second reply — verdicts (44.3 s)
```
{"reasoning": "None of the statements provide specific issues or challenges to address; they are general observations or questions about existing problems. They do not offer actionable solutions. Therefore, these needs should be classified as 'WRONG_QUESTION'.", "verdicts": [{"id": "BN-6dddb2e609", "reasoning": "None of the statements provide specific issues to address; they are general observations or questions about existing problems. They do not offer actionable solutions.", "verdict": "WRONG_QUESTION"}, {"id": "BN-580dae4f5e", "reasoning": "The statements discuss improving life conditions and solving problems on Earth, which is relevant but does not provide specific issues to address; they are general observations or questions about existing problems. They do not offer actionable solutions.", "verdict": "WRONG_QUESTION"}, {"id": "BN-1340065e41", "reasoning": "The statements discuss increasing knowledge for understanding complex systems, which is relevant but does not provide specific issues to address; they are general observations or questions about existing problems. They do not offer actionable solutions.", "verdict": "WRONG_QUESTION"}, {"id": "BN-e0f5781722", "reasoning": "The statements discuss high-risk situations and the risk of wars, which is relevant but does not provide specific issues to address; they are general observations or questions about existing problems. They do not offer actionable solutions.", "verdict": "WRONG_QUESTION"}, {"id": "BN-1bdc390518", "reasoning": "The statements discuss the risk of wars and collapses, which is relevant but does not provide specific issues to address; they are general observations or questions about existing problems. They do not offer actionable solutions.", "verdict": "WRONG_QUESTION"}]}
```

- `BN-6dddb2e609` → WRONG_QUESTION (recorded True)
- `BN-580dae4f5e` → WRONG_QUESTION (recorded True)
- `BN-1340065e41` → WRONG_QUESTION (recorded True)
- `BN-e0f5781722` → WRONG_QUESTION (recorded True)
- `BN-1bdc390518` → WRONG_QUESTION (recorded True)

### The next reply (50.0 s) — the same five questions again
```
{"needs": [{"question": "What are the most pressing issues to address?", "why_subgoal": "SUSTAINABLE_RESOURCES", "about": null, "kind": "FIND", "would_change": "focus on sustainable resources; lower risk of critical resource exhaustion; encourage cyclical, regenerative flows"}, {"question": "How can we improve the conditions for life?", "why_subgoal": "HEALTHY_ENVIRONMENTS", "about": null, "kind": "FIND", "would_change": "focus on maintaining and improving environmental conditions; limit pollution and irreversible damage"}, {"question": "What knowledge should be increased to understand complex systems better?", "why_subgoal": "KNOWLEDGE_UNDERSTANDING", "about": null, "kind": "FIND", "would_change": "increase understanding of complex systems; structure knowledge for future agents"}, {"question": "What actions can we take to avoid high-risk situations?", "why_subgoal": "SAFETY", "about": null, "kind": "FIND", "would_change": "focus on avoiding high-risk actions; prefer reversible strategies"}, {"question": "How can we reduce the risk of wars and collapses in sustainable civilisation?", "why_subgoal": "CIVILIZATIONAL_STABILITY", "about": null, "kind": "FIND", "would_change": "address risks to war and collapse; promote stability in civilisation"}]}
```

## Part 5 — the board shows cognition and maintenance separately (b196b16)
Today's rows (rendered from the live files after the loop and the maintenance pass):
- `BRAIN NEEDS emitted 10 · served 5 · satisfied 0 · silence 0`
- `ENGINE NEEDS emitted 3 · served 0`
- `MAINTENANCE cells worked 10 · unchanged 1 · changed 1 · nothing found 0`

Each row reads one file and is MISSING (never 0) when it is absent.
Chain: worker → brain_needs → finder → card_intake → maintenance (`tools/openclaw_chain.bat`, asserted
from its `%PY%` lines).

## Tests
Every part's commit was gated on its related suites plus `test/test_behaviour_claims_are_backed.py`
(RC 0 each time: 200, 76, 197, 47, 199, 96 passed).

Full gate on HEAD 1c719c1 (`-m "not live_state"`):
- `test/test_cockpit_render_sweep.py`: **117 passed, RC 0** (694.9 s).
- everything else: **INCOMPLETE.** Claude Code stopped the run because the machine ran low on memory (the
  detached embedding job was also running). Up to that point: 4,281 results, **4,269 passed, 0 failed,
  0 errors**; it stopped at `test/test_quarantine_triage.py`. The remaining ~1,650 tests are **UNVERIFIED**.
  To close it:
  `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe -m pytest -v -p no:cacheprovider -m "not live_state" --ignore=test/test_cockpit_render_sweep.py test/`
