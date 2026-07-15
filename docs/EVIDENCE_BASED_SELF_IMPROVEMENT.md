# Evidence-Based Self-Improvement — the (G) design doc

> **Status: CONSTITUTIONAL. Design only, no code.**
>
> This is the **(G) design document** named as a not-yet-written hard gate in
> `docs/LOCAL_BRAIN_LADDER.md:142,148` — *"this stage cannot begin before the (G)
> design doc exists."* Writing it removes **one** of the two blockers on rung 5
> (SHADOW DUEL); the other (rung 4, LOCAL JUDGE, must pass) is untouched. Nothing
> here is executable. It defines the **law** under which a self-generated change is
> allowed to take authority, and the **two numbers** by which we will know the
> system has crossed from *monitoring civilization* to *growing*.
>
> Per the **(G) lesson** on which the whole ladder rests — *a goal that is not
> measurable before the fact is a story you tell afterwards* — every criterion in
> this document is declared **before** any promotion runs, so that a promotion
> cannot be narrated into existence after the numbers are seen. This document is
> therefore itself on the protected denylist (§6.3): the machinery that decides
> what counts as an improvement must not be reachable by the process it governs.

---

## 0. The threshold, and the two numbers that mark it

CORTEX++ today is a monitor. It reads the world, scores 25 axes, writes proposals,
and — this is the honest finding of `docs/SFF_TECHNICAL_ASSESSMENT.md:194-197,386` —
its self-modification is **simulated**: *"delta = 0.0 across all cycles … patches
write files but close no feedback loop."* The `score_before`/`score_after`/`delta`
recorded in `development_journal.json` is computed by `self_modifier._read_avg_score()`
(`agents/core/self_modifier.py:107-116`), which averages LOW/MEDIUM/HIGH → 25/55/85
from `auto_levels.json` and is explicitly labelled *"Само за tracking — не е цел"*
(only for tracking — not a goal). **That number is not proof of anything and this
document forbids counting it as such** (§4.2).

A monitor becomes a growing intelligence at exactly the point where it can **change
itself and prove the change was good** — not assert it, prove it, against a metric
fixed before the change ran, confirmed by a human, and sealed where it cannot later
be edited. Two KPIs measure that crossing. Both are **0 today**, and this document
is what makes them countable.

- **KPI #4 — self-improvements promoted with proven effect.** The count of changes
  that completed the full pipeline of §2 and were promoted with a **pre-declared,
  measured, human-confirmed** positive effect, Merkle-sealed. Not "patches written."
  Not "proposals accepted." Promotions *with proof*. Currently 0 because nothing has
  ever been promoted — the loop has never closed.

- **KPI #5 — measured cross-domain transfer.** The count of promotions (a subset of
  KPI #4) where the **evidence that justified the change came from a different
  domain than the one the change was applied to.** This is the first mechanical
  measure of the aspirational AGI direction already written into the system —
  `agents/core/self_observer.py:40`, GENERALIZATION: *"Знание от една ос да се
  прилага в друга"* (knowledge from one axis applied to another). Currently 0, and
  §5 defines both the measurement and how the claim is made falsifiable.

Everything below serves those two definitions.

---

## 1. The `measurable_goal` rule

### 1.1 The rule

> **A proposal's `measurable_goal` must be a predicate over named artifacts that is
> decidable TRUE or FALSE at a stated time, and is FALSE at the moment the proposal
> is made.** It states an *end-state to be observed*, never an *action to be taken*.

A goal that satisfies this can be checked by a function that reads files and returns
a bool. A goal that does not is not a goal — it is a description of activity, true of
any day it is uttered, and therefore (per (G)) a story told afterwards.

This is the enforcement the backlog has been asking for. `docs/ENGINEERING_BACKLOG.md:168`
names the exact missing control: *"Proposals carry a `measurable_goal` field, but
nothing enforces that it is actually measurable. Needs a rule that rejects vague
goals at proposal time rather than at review time."* Section 1.4 is that rule, made
mechanical.

### 1.2 The canonical counterexample — the water patches

The rule exists because of a specific failure that is **still sitting in the repo as
evidence** (it was never narrated in prose until now; it lives in the data). OpenClaw,
scanning for gaps, generated proposals like these — `memory/improvement_proposals.json`
(and mirrored in `development_journal.json`, `causal_log.json`):

```json
{ "problem": "Address water scarcity gap",
  "solution": "Implement water conservation strategies",
  "measurable_goal": "Implement water conservation strategies",
  "generated_by": "OPENCLAW" }

{ "problem": "Water scarcity management",
  "solution": "Develop and integrate agents for sustainable water resource management",
  "measurable_goal": "Water scarcity management",
  "generated_by": "OPENCLAW" }
```

Look at the `measurable_goal` field. In the first it is a verbatim copy of the
**solution**; in the second, of the **problem title**. Neither names an artifact.
Neither can be false. Neither would tell you, on any given day, whether it had been
achieved — "implement water conservation strategies" is true the instant you write
one line of code toward it and never becomes checkably done. It is the **"implement
data collection" class** of goal: an action verb pointed at a topic.

These water proposals were fed to the self-modifier, which generated patches, and
**every one was caught and quarantined** by the AST gate (`safety/ast_gate.py`) with
the reason *"write_text() target not statically verified under an allowed directory"*
— you can read them now under `patches/quarantine/` with their source proposals
preserved in the JSON sidecars (5 of the 12 quarantined patches trace to these water
goals). They were stopped by a *capability* gate, by luck of also being unsafe code.
**The `measurable_goal` rule exists so that a proposal this empty is stopped at
proposal time for being unfalsifiable — before a single patch is generated — even
when the code it would produce is perfectly safe.** Safety caught these; measurability
must catch the next one.

### 1.3 The two classes, side by side

| | FORBIDDEN — "implement/improve/address" class | REQUIRED — "artifact X satisfies predicate P" class |
|---|---|---|
| shape | action verb + topic | named artifact + comparator + concrete value |
| example | `"Implement water conservation strategies"` | `"WATER_REVIEW snapshot has ≥ 3 metrics with non-null values sourced from a URL in discovered_data_sources.json"` |
| when true | the moment work starts; never checkably "done" | at a specific, checkable instant, and not before |
| false before the change? | no — it is never false | yes — the predicate is false now, which is the point |
| checkable by a function? | no | yes — reads the named files, returns bool |

Canonical **acceptable** forms (a non-exhaustive grammar the validator recognises):

- `"axis <AXIS> has ≥ <N> real entries from source <SOURCE> with non-null values"`
- `"scorer <AXIS> maps reference set <COUNTRIES> to expected bands with ≤ <K> mismatches"`
- `"metric <M> in <SNAPSHOT> is non-null and within [<a>, <b>]"`
- `"<SOURCE_URL> validates (HTTP 200, contains numeric data) and is persisted under <AXIS> in discovered_data_sources.json"`

Each names an artifact that exists on disk, a concrete threshold, and admits a
one-line checker.

### 1.4 The acceptance test (mechanical, run at proposal time)

A `measurable_goal` is **accepted** iff it passes all four. This mirrors, deliberately,
the operational test in `experiments/dreams/check.py` — *"could this sentence have
been written without reading the day?"* — pointed at goals instead of memories.

1. **Names a concrete artifact** — a file path, a snapshot key, an axis + metric, or
   a source URL that resolves to something on disk or fetchable. (No artifact → reject.)
2. **Has a decidable checker** — there exists, or the proposal supplies, a pure
   function `check(artifacts) -> bool` reading only named artifacts. (No checker
   constructible → reject.)
3. **Is false now** — running that checker at proposal time returns `False`. A goal
   already true is vacuous; a goal that cannot be evaluated at all is worse. (True or
   un-runnable now → reject.)
4. **Names a state, not an action** — the goal contains no bare imperative
   (`implement`, `improve`, `develop`, `address`, `enhance`, `optimise`) as its
   operative verb. (Imperative-topic shape → reject.)

**Rejection is not deletion.** A proposal failing the test is routed to the existing
quarantine (`safety/quarantine.py`) with a new reason string `UNMEASURABLE_GOAL` and
the failed clause recorded, so a human can see *why* at
`scripts/review_quarantine.py`. The system never discards a proposal silently — the
same principle that keeps rejected patches (§7.1).

> **This test is itself declared before the fact and cannot be softened on a day a
> beautiful-sounding goal fails it.** A goal that reads well but names nothing is the
> water patch wearing better prose.

---

## 2. The promotion pipeline

Seven stages. A change enters as a proposal and either takes authority or is
quarantined; there is no other exit. Each stage names its **entry condition**, its
**rejection route**, and the **ledger event** it emits. Stages 1–2 exist today;
stages 3–7 are the machinery this document commissions.

```
  (1) PROPOSAL ──▶ (2) GATE ──▶ (3) SHADOW RUN ──▶ (4) COMPARISON ──▶ (5) HUMAN ──▶ (6) PROMOTION ──▶ (7) SEAL
        │              │              │                   │               │
        ▼              ▼              ▼                   ▼               ▼
   quarantine     quarantine     quarantine          quarantine      quarantine
  UNMEASURABLE   (gate reason)  SHADOW_ABORTED      SHADOW_REGRESSED  HUMAN_REJECTED
```

**Stage 1 — PROPOSAL.** A proposal is admitted only if it (a) passes the
`measurable_goal` test of §1.4, (b) carries an **evidence-origin block** (§5.2), and
(c) targets something inside the MAY perimeter (§6.1). Producers are the existing
ones (`self_observer`, HyperClaw, the strategist). *Reject → quarantine
`UNMEASURABLE_GOAL` / `OUT_OF_PERIMETER` / `MISSING_EVIDENCE_ORIGIN`.* No ledger
event (proposals are cheap and numerous; the ledger records only the weighty steps).

**Stage 2 — GATE.** The existing safety substrate, unchanged, in its existing order:
`alignment/civilization_guard.py::evaluate_proposal_alignment` → `safety/ast_gate.py::check_code`
→ `safety/protected_paths.py::protection_reason`. This decides whether the *code* is
safe and *targets* a permitted path. *Reject → quarantine with the gate's own reason
(the path that produced the water quarantines).* No new event.

**Stage 3 — SHADOW RUN.** The change runs **in parallel with the incumbent for N
cycles, and the incumbent keeps authority** (§3). N and the metric are fixed in the
proposal, before this stage runs. *Reject (crash, timeout, side-effect leak) →
quarantine `SHADOW_ABORTED`.* **Emits `SHADOW_RUN_STARTED`** to the existence ledger.

**Stage 4 — COMPARISON.** The pre-declared metric of §4 is computed over the N shadow
outputs and the N incumbent outputs and compared against the pre-declared threshold.
Verdict ∈ {`IMPROVED`, `NO_EFFECT`, `REGRESSED`}, computed mechanically — no judgment
here. *`NO_EFFECT`/`REGRESSED` → quarantine `SHADOW_REGRESSED` (kept for study, like
HARMFUL patches today).* **Emits `SHADOW_RUN_COMPARED`** with the numbers.

**Stage 5 — HUMAN CONFIRMATION.** A human reads the pre-declared metric, the measured
delta, the shadow record, and the evidence-origin, and confirms or rejects. **No
automatic promotion, ever** — this matches the house rule that the local machinery is
*"triage, never authority"* (`LOCAL_BRAIN_LADDER.md:134`) and the interactive
approval gate already in `execute_patches.py::_needs_approval`. *Reject → quarantine
`HUMAN_REJECTED`.* No event yet (the human's decision is recorded by stage 6/7's
outcome).

**Stage 6 — PROMOTION.** The shadow version takes authority. It is applied **only**
through `patch_guardian.py::PatchGuardian.apply_patch()` — the sole writer of promoted
changes — so every existing guardrail (backup, syntax, import, protected-path,
rollback) applies for free (§7.3). *Apply failure → PatchGuardian rolls back /
quarantines; the promotion does not count.*

**Stage 7 — SEAL.** **Emits `IMPROVEMENT_PROMOTED`** to the existence ledger with the
full record (§7.2), which the next successful cycle anchors into the Merkle root
(`merkle_memory.py`, via `fast_cycle_runner` step 24). **Only now does KPI #4
increment**, and §5 decides whether KPI #5 does too. A promotion that is not sealed
did not happen.

> The ordering is load-bearing. The metric is fixed at stage 1, measured at stage 4,
> and can be re-derived at stage 7 from records sealed at stage 3 — so at no point can
> the criterion be chosen after its result is known. That is the (G) lesson expressed
> as a control-flow invariant.

---

## 3. The shadow run

### 3.1 The authority invariant (the safety heart)

> **During a shadow run, the live system behaves exactly as it would if the shadow
> did not exist.** The shadow computes, records to its own sidecar, and is acted upon
> by nothing. Every non-shadow output byte is identical to the no-shadow world.

If this invariant holds, a shadow run is risk-free by construction: the worst a bad
candidate can do is write a wrong number into a file no one reads. The invariant is
what lets a self-generated change *run on real data* before anyone trusts it — the
whole reason shadowing beats a static review. It is also the first thing a shadow-run
implementation must be tested against: a candidate that reaches a live path is not a
shadow, it is an unreviewed promotion, and the run must abort (`SHADOW_ABORTED`).

Concretely, the shadow writes only under a dedicated, non-authoritative tree — e.g.
`shadow/<proposal_id>/cycle_<cycle_id>.json` — which is a data directory no scorer,
snapshot, or cycle step reads. (That tree is *not* protected; it is the opposite of
protected — it is the sandbox.)

### 3.2 What "parallel for N cycles" means, per improvement class

The mechanism differs by what is being improved, and this is exactly why the
perimeter (§6) is drawn where it is — every MAY item is cheaply shadow-able.

- **Axis scorer** (a pure function in `cortex_scoring_engine.py`). Each cycle, the
  cycle computes the **incumbent** scorer's `ScoreResult` (which keeps authority and
  flows to `goal_score`) **and** the **candidate** scorer's result on the *same
  snapshot inputs*, and writes the candidate's result to the shadow sidecar.
  Deterministic, so N can be small; the comparison is against the sanity oracle
  (§4.1), not against each other.
- **Query proposal / source discovery** (`core/data_scout.py`). The candidate query
  or source is fetched and validated in parallel and its would-be yield recorded, but
  it is **not** written into `discovered_data_sources.json` (the authoritative store)
  until promoted. The metric is the pre-declared "validates and yields ≥ N non-null
  values" predicate.

N is declared in the proposal and bounded (a shadow that needs hundreds of cycles to
show an effect is claiming an effect too small to matter). The default and its
rationale are a stage-1 prerequisite (§9), not fixed here.

### 3.3 The record

The shadow run's existence is a **ledger fact**, not a mere log line, because a
promotion's proof rests on it: `SHADOW_RUN_STARTED` (proposal id, target, metric,
declared threshold, N, evidence-origin) and `SHADOW_RUN_COMPARED` (the N-by-N numbers,
the verdict) are appended to `memory/existence_ledger.jsonl` and hash-chained. This
means **you cannot later claim an improvement was proven unless the shadow record was
sealed before the promotion** — the chain won't allow the record to be back-dated
(§7.2). The dead cannot seal their own record and neither can a promotion seal its own
justification after the fact.

---

## 4. Proof-of-effect, and when KPI #4 increments

### 4.1 The metric must be external — the anti-Goodhart clause

> **No promotion may use the system's own `goal_score`, `composite_score`, or any
> axis `auto_level` as its proof-of-effect metric.**

This is the single most important rule in the document, and it is what makes scorers
safe to self-improve at all. A scorer that is "improved" until the number it produces
goes up has proven nothing except that it can be made to flatter the system —
Goodhart's law as autobiography. `LOCAL_BRAIN_LADDER.md:126` already names this: *"a
patch that chases a score instead of solving a stated, measurable problem is junk,
however clean the diff."* Here it becomes a hard constraint: the metric that justifies
a promotion must be **agreement with something outside the system's own judgment.**

For the three MAY items, the external metric is:

- **Axis scorer → a sanity oracle of hand-transcribed external index values.** A
  **small, human-frozen fixture** (~15–20 countries) committed under
  `safety/promotion/oracle/`, in which each country's expected band per axis is
  **transcribed by hand** from a published third-party composite index the system does
  not compute — HDI (UNDP), the World Bank WGI, V-Dem, and their peers — with **a
  citation on every band: index name, year, and the source value.** The scorer must
  place those countries in the index-implied bands, with the candidate producing **≤ K
  mismatches** where the incumbent produces more.

  *Decided (2026-07-15).* The ground truth is **external index values, frozen** — a
  deliberate composite of the two clean options and a rejection of the third:
  - **External, not our own** — the bands are authored by UNDP / the World Bank /
    V-Dem, never derived from the system's per-country pipeline
    (`wellbeing_country.py`, `output/wellbeing_all_countries.json`). An oracle drawn
    from the system's own computation is one the system can move by moving its
    pipeline, which is precisely the anti-Goodhart failure §4.1 exists to prevent.
  - **Frozen, not fetched** — the numbers are transcribed once and committed, not
    pulled at runtime. This buys three things at once: *independence* (the values are
    UNDP's/World Bank's/V-Dem's, not ours), *auditability* (every band cites the exact
    index, year, and value a human can check against the published source), and **zero
    runtime dependency on any external API** (nothing to hallucinate, rate-limit, or
    silently drift). A human refreshes the fixture perhaps yearly; nothing automated
    ever touches it.

  **The perimeter follows the oracle, not the reverse.** An axis is eligible for
  scorer self-improvement (§6.1) *only* where a defensible external anchor exists and
  has been transcribed. Axes with no clean external analog — most of the `COSMOS`
  group (`COSMIC_RESOURCES_REVIEW`, `SPACE_INFRASTRUCTURE_REVIEW`, `DEEP_TIME_RISKS_REVIEW`,
  `LONG_TERM_FUTURE_REVIEW`) and any other with no published index — simply have **no
  oracle yet, and their scorers stay outside the MAY set until one exists.** We do not
  invent a band to fill a slot — that would be the water patch in oracle form. **This
  fixture does not exist yet** (`cortex_scoring_engine.py` scores global
  population-weighted metrics, not per country), and no scorer may be promoted for an
  axis before its fixture rows do.
- **Query proposal / source → objective validation.** Non-null, numeric, HTTP-200
  data actually retrieved from the proposed source (extending `data_scout._validate`,
  which is HTTP-only today by its own admission at `core/data_scout.py:16-18`). "The
  source returns real data" is checkable without the system's opinion.

### 4.2 The increment condition for KPI #4

KPI #4 increments **once**, at stage 7, iff **all** hold:

1. The proposal's `measurable_goal` passed §1.4, and its checker returns `True` after
   promotion (the stated end-state was actually reached).
2. The pre-declared external metric (§4.1) showed `IMPROVED` beyond the pre-declared
   threshold at stage 4.
3. A human confirmed at stage 5.
4. The `IMPROVEMENT_PROMOTED` event was sealed into the Merkle root (§7.2).

Anything short of all four is not a proven improvement and must not be counted —
explicitly including the `delta` that `self_modifier`/`execute_patches` compute today,
which §0 already disqualified. KPI #4 is stored as a derived count over
`IMPROVEMENT_PROMOTED` ledger events, so it is itself re-derivable and tamper-evident,
never a free-floating integer someone can bump.

---

## 5. Cross-domain transfer, and KPI #5

### 5.1 Definition

> **A promotion counts as cross-domain transfer when the evidence that justified it
> originated in a different domain than the one the change is applied to.**

Transfer is not a separate mechanism — it is a **property of a promotion**, computed
at stage 7. Every promotion has two domain coordinates:

- **application domain** — the axis/domain whose scorer, query, or source the change
  modifies (where authority moves).
- **evidence-origin domain** — the axis/domain of the cycle whose observation
  motivated the change (where the idea came from).

Let *domain* be the axis (fine grain), and *meta-domain* the group it belongs to
(`PLANET` / `HUMAN` / `CIVILIZATION` / `COSMOS`).

- `origin_axis ≠ application_axis` → **transfer** (KPI #5 increments).
- additionally `origin_group ≠ application_group` → **strong transfer** (reported
  separately; the harder, more meaningful signal — a lesson learned watching water
  changing how the system reads energy).

### 5.2 Detection — the evidence-origin block, captured at proposal time

Transfer cannot be reconstructed after the fact without inviting exactly the
storytelling (G) forbids, so it is **captured at stage 1 and made falsifiable**. Every
proposal must carry:

```json
"evidence_origin": {
  "origin_axis":  "<AXIS the justifying evidence came from>",
  "origin_cycle_id": "<cycle_id whose record contains that evidence>",
  "origin_observation": "<the specific finding — a metric, a divergence, a gap>"
}
```

The `origin_cycle_id` is the load-bearing field: it points at a **Merkle-archived
cycle** (`cortex_memory/archive/cycle_*`, sealed per `merkle_memory.py`), so the
transfer claim is itself checkable — a human or an auditor can open that cycle and
confirm the cited observation actually appeared there. A transfer claim whose
`origin_cycle_id` does not contain the cited evidence is a **false transfer** and the
promotion is rejected at stage 5. This is the §1 falsifiability principle applied to
the transfer claim: *transfer, too, must be true of a specific recorded cycle and
false otherwise.*

Where a proposal cannot name a distinct origin — the change came from an observation
in the very axis it modifies — `origin_axis == application_axis` and it is simply a
non-transfer improvement. That is honest and fine; it counts toward KPI #4 and not #5.
The failure mode to guard against is the reverse: **transfer laundering** — attaching
a distant `origin_axis` to a same-domain improvement to inflate KPI #5. The
`origin_cycle_id` check is the defense; without a verifiable cited cycle, the transfer
does not count.

### 5.3 Logging

KPI #5 is a derived count, like #4, over `IMPROVEMENT_PROMOTED` events whose sealed
record carries `transfer: true`. The record (§7.2) includes `origin_axis`,
`application_axis`, `origin_group`, `application_group`, `transfer`, and
`strong_transfer`, so both KPIs and the weak/strong split are re-derivable from the
ledger alone.

---

## 6. The perimeter

### 6.1 What MAY be self-improved first — the beachhead

Three, and only three, to begin. Each was chosen because it is **pure or isolable**
(shadow-able under §3.1 without touching authority), and has an **external check**
(§4.1) that is not the system's own score.

| MAY item | where it lives | why it is safe first | external metric |
|---|---|---|---|
| **Axis scorers** *(only axes with an oracle fixture)* | `cortex_scoring_engine.py` (`AXIS_SCORERS`, pure threshold fns) | pure functions of a snapshot; deterministic; trivially run in parallel | sanity oracle — reference countries land in the bands transcribed from external indices (**fixture must exist for that axis first, §4.1/§9**) |
| **Query proposals** | `core/data_scout.py::_suggest_sources` | a proposed query touches no code and no authority until validated | source validates and yields ≥ N non-null values |
| **Source discovery** | `core/data_scout.py` → `discovered_data_sources.json` | a discovered source feeds *data*, gated by validation, never code | same objective validation, extended past HTTP-only |

These improve the system's **inputs and its measurements** — what it reads and how it
scores — not how it governs itself. That is the entire point of starting here.

### 6.2 What may NEVER be self-improved

Everything on the protected denylist enforced by `safety/protected_paths.py`,
verbatim, because it is code (not config) and covers itself:

- `PROTECTED_DIRS = ("safety", "config")` — the AST gate, the quarantine, this
  denylist itself, the action policy, the scheduler config, the source registry.
- `PROTECTED_FILES` — `patch_guardian.py`, `execute_patches.py`,
  `scripts/review_quarantine.py`, `supervisor.py`, `core/source_status.py`, and the
  audit-trail files `memory/existence_ledger.jsonl`, `memory/heartbeat.json`,
  `memory/cycle.lock`, `memory/scheduler_state.json`.

The stated principle (`safety/protected_paths.py` docstring) governs the whole
perimeter: *"The machinery that GRANTS autonomy must not be reachable by the autonomy
it grants."*

### 6.3 The (G) machinery excludes itself

The denylist above predates this document. This document **adds itself and its own
organs to it**, because the deepest version of the same principle is: *the process
that decides what counts as an improvement must not be improvable by that process.* A
system that can rewrite its own definition of "better" can rationalise itself into
anything, and would do so gradually, each step measurably "improving" against a metric
it just edited.

Therefore the following are NEVER self-improvable and must be placed under protection:

- this document, `docs/EVIDENCE_BASED_SELF_IMPROVEMENT.md`;
- the `measurable_goal` validator (§1.4);
- the shadow-run harness and its authority invariant (§3);
- the comparison / proof-of-effect evaluator and the anti-Goodhart clause (§4);
- the sanity oracle and its reference fixtures (§4.1) — *especially* these: an oracle
  the system can edit is an oracle that proves whatever the system wants;
- the transfer detector and the KPI #4/#5 counters (§5).

**Concrete recommendation (design, not code):** house all of the above under
`safety/promotion/…`. Because `PROTECTED_DIRS` already contains `"safety"`, everything
placed there is protected automatically, with no new enforcement mechanism and no
bootstrap gap — the same trick by which the denylist protects itself. This document
sits in `docs/` and so must be added to `PROTECTED_FILES` explicitly.

---

## 7. Integration with existing machinery

This pipeline invents as little as possible. Three existing, tested subsystems do the
heavy lifting; the new work is the connective tissue and the shadow harness.

### 7.1 Quarantine is the one rejection path

Every rejection in §2 routes to `safety/quarantine.py::quarantine(...)` — the
subsystem that **never deletes** and always writes a JSON sidecar (reason, verdict,
source proposal) reviewable by a human at `scripts/review_quarantine.py`. New reason
strings — `UNMEASURABLE_GOAL`, `OUT_OF_PERIMETER`, `MISSING_EVIDENCE_ORIGIN`,
`SHADOW_ABORTED`, `SHADOW_REGRESSED`, `HUMAN_REJECTED` — are added; the machinery is
unchanged. Quarantined items already fold into the Merkle commit via
`_log_quarantine_event` → `development_journal.json` → `fast_cycle_runner` step 24, so
**a rejection is as tamper-evident as a promotion.** Both halves of the system's
self-improvement judgment — what it kept and what it refused — are sealed.

### 7.2 The existence ledger is the shadow-run and promotion record

The ledger API `memory/existence_ledger.py::append(event_type, **fields)` has an
**open schema** — any string event type, any fields, hash-chained, `fsync`-durable —
so the four new events need no schema change:

- `SHADOW_RUN_STARTED` — `{proposal_id, application_axis, metric, threshold, n_cycles, evidence_origin}`
- `SHADOW_RUN_COMPARED` — `{proposal_id, incumbent_metric, candidate_metric, verdict}`
- `IMPROVEMENT_PROMOTED` — `{proposal_id, application_axis, application_group, origin_axis, origin_group, transfer, strong_transfer, metric, delta, human_confirmed_by, guardian_result}`
- `IMPROVEMENT_REJECTED` — `{proposal_id, stage, reason}`

The hash-chain (`prev_hash` + content, re-derivable from genesis by `verify()`) plus
the per-cycle Merkle anchor (`fast_cycle_runner` writes the ledger HEAD hash into
`MerkleMemory.commit(results=[…])`) means a promotion record **cannot be back-dated or
edited after sealing** — which is the whole basis on which KPI #4 can be trusted.

**One concrete gap to close:** `existence_ledger.summary()` hard-codes the known event
types, so the new events are chained and sealed but will not appear in derived counts
until `summary()` is extended to aggregate them into KPI #4 / #5. That extension is a
listed prerequisite (§9). (`summary()` lives in the ledger module, which is *not*
itself protected — only the `.jsonl` data file is — so this edit is permitted.)

### 7.3 PatchGuardian is the executor, and the only one

Promotion (stage 6) applies the change **exclusively** through
`patch_guardian.py::PatchGuardian.apply_patch(filename, new_code)`. Making it the sole
writer means the full pipeline inherits, for free: protected-path refusal
(`rejected_protected_path`), automatic backup + 10-deep rollback, syntax/import
checks, and quarantine-on-failure. Two concrete facts constrain the design:

- **`PATCHABLE_FILES` must be widened, carefully, and only by a human.**
  `cortex_scoring_engine.py` is **not** in the allowlist
  (`patch_guardian.py:55-61`) today, so a promoted scorer change would be refused as
  `rejected` until a human adds it. That addition is itself an edit to a protected
  file — so the perimeter can only be widened by hand, which is the correct amount of
  friction for expanding what the system may rewrite.
- **`_smoke_test` is a no-op** (`patch_guardian.py:364-374` returns `(True, None)`),
  so PatchGuardian proves *applicability*, not *effect*. That is fine here: **the
  shadow comparison (§4) is the proof of effect; PatchGuardian is only the safe
  hand that applies what was already proven.** The two must not be confused — applying
  cleanly is not the same as being good, and only §4 speaks to good.

---

## 8. Failure modes named in advance

Per the house practice (PULSE/DREAMS both name their plausible failure before running,
so meeting it is not mistaken for a surprise):

1. **Goodhart / score-chasing.** A scorer improved until `goal_score` rises. *Defense:*
   §4.1 forbids the system's own score as a proof metric; the oracle is external.
2. **Post-hoc criterion.** Declaring the metric or threshold after seeing shadow
   results. *Defense:* the metric is sealed in `SHADOW_RUN_STARTED` before stage 3
   runs; stage 4 can only read it (§2 invariant).
3. **File-write as improvement.** Counting patches written, as the current simulated
   path effectively does (delta always 0.0). *Defense:* KPI #4 counts only sealed
   `IMPROVEMENT_PROMOTED` events meeting all four §4.2 conditions; nothing else.
4. **Transfer laundering.** Attaching a distant `origin_axis` to a same-domain change
   to inflate KPI #5. *Defense:* `origin_cycle_id` must contain the cited evidence in
   its Merkle-sealed record, or the transfer does not count (§5.2).
5. **Oracle capture.** Editing the sanity fixtures so a bad scorer passes. *Defense:*
   the oracle lives under `safety/promotion/` and is protected (§6.3); it can only be
   changed by a human.
6. **Perimeter creep.** The pipeline quietly growing to touch governance. *Defense:*
   the MAY set is three named items; widening `PATCHABLE_FILES` or the perimeter is a
   protected-file edit, human-only (§7.3).
7. **The un-promotable truth.** It is entirely possible that, run honestly, this
   pipeline promotes **nothing** for a long time — every candidate shows `NO_EFFECT`
   against an external oracle. That would be a **real finding** — that self-improvement
   at this stage produces motion but not measurable gain — and it gets reported as
   one, with KPI #4 sitting truthfully at 0, not iterated on until a promotion is
   tortured out. A 0 that is honest is worth more than a 1 that is narrated.

---

## 9. Prerequisites — what must be built before the first promotion (design backlog)

Ordered. No code is written by this document; this is the work it authorises, and the
gate on each depending item.

1. **The sanity oracle** (`safety/promotion/oracle/…`): a small, human-frozen fixture
   (~15–20 countries) with expected bands **hand-transcribed from external published
   indices** (HDI/WGI/V-Dem), each band citing index, year, and source value; plus the
   mismatch-count checker. Frozen numbers, no runtime fetch, human-refreshed ~yearly
   (§4.1). *No scorer may be shadowed for an axis without a fixture for that axis, and
   the MAY perimeter (§6.1) expands only as fixtures are added — the perimeter follows
   the oracle. First, because everything scorer-related depends on it.*
2. **The `measurable_goal` validator** (§1.4) wired into stage 1, rejecting to
   quarantine `UNMEASURABLE_GOAL`. *Independent of the oracle; can be built in
   parallel, and pays off immediately by stopping the next water patch.*
3. **The shadow-run harness** (§3) with the authority-invariant test as its first
   test. *The core new capability.*
4. **The comparison evaluator** (§4) and the anti-Goodhart constraint as a hard check.
5. **The evidence-origin capture + transfer detector** (§5), including the
   `origin_cycle_id` verification against Merkle-archived cycles.
6. **The ledger events + `summary()` extension** (§7.2) so KPI #4/#5 become derivable,
   tamper-evident counts.
7. **Protection placement** (§6.3): create `safety/promotion/`, move the above under
   it, add this doc to `PROTECTED_FILES`. *Last, so the machinery is protected the
   moment it is complete — and never before it is trusted.*
8. **A single human-confirmation surface** (§2 stage 5) reusing the
   `execute_patches`/`review_quarantine` interaction idiom.

Only when 1–8 exist can the first real promotion be attempted — and rung 5 (SHADOW
DUEL) of the ladder, which is one *application* of this pipeline (two model versions
as the duelists, adjudicated under this law), remains additionally gated on rung 4.

---

## 10. Amendment and standing

This document is **constitutional-tier**: it defines the criterion by which the system
is permitted to change itself, and it is therefore protected from that very process
(§6.3). It changes only by human edit, deliberately and visibly, never by any
automated proposal — the same asymmetry `safety/protected_paths.py` already enforces
for the machinery it names.

It is complete as a *design*. It is deliberately inert as *capability*: today KPI #4
and KPI #5 both read **0**, honestly, and this document's success is not that they
move soon, but that when the first one does, the increment rests on a shadow record
sealed before the fact, an external metric the system did not author, and a human who
looked — a growth the system can prove, not a story it tells.
