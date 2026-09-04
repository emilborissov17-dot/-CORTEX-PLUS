# THE PROVENANCE CLOSURE — which steps actually gate an irreversible action
### Phase 0, read-only. 5 September 2026, 02:00. Nothing declared, nothing changed.

## THE ANSWER: 6 steps, of which 2 are undeclared

Smaller than the dozen expected, not larger. **But the number is a lower bound produced by
ignorance, and the section after it is the one that matters.**

```
CLOSURE SIZE: 6

  d0  github_publish       DECLARED     1 input
  d0  self_modifier        DECLARED     4 inputs
  d0  execute_patches      DECLARED     1 input     cap=1 (core/notary.MAX_LEVEL)
  d1  web_intelligence     DECLARED     1 input     VERIFIER
  d1  hyperclaw_plan       UNDECLARED   0 inputs
  d1  auto_levels          UNDECLARED   0 inputs
```

**Already declared: 4.** github_publish, self_modifier, execute_patches, web_intelligence.
**Undeclared: 2.** `hyperclaw_plan`, `auto_levels`.

That is the whole scope of the decision as it stands tonight: **two declarations**, not 47.

### How it was computed

Backward transitive walk from the three irreversible steps. Edges are
`consumer ← artifact ← producer`, where the consumer's inputs come from
`config/step_inputs.json` (or the scanner, when declared inputs are absent) and the
producer is whichever step lists that artifact in `core/cycle_map.STEPS`. A declared
*directory* input matches any product beneath it.

```
github_publish    <- memory/web_intelligence                <- web_intelligence
self_modifier     <- memory/improvement_proposals.json      <- hyperclaw_plan
self_modifier     <- memory/improvement_proposals.json      <- self_modifier      (self-loop)
self_modifier     <- memory/development_journal.json        <- execute_patches
self_modifier     <- memory/auto_levels.json                <- auto_levels
self_modifier     <- memory/self_awareness.json             <- (no step produces it)
execute_patches   <- memory/development_journal.json        <- execute_patches    (self-loop)
web_intelligence  <- memory/web_intelligence                <- web_intelligence   (self-loop)
```

Note the three self-loops. `self_modifier` and `execute_patches` both read and produce the
same file they are graded on, so once either is stamped level_0 it reads its own 0 the next
night. Nothing in the mechanism recovers on its own.

---

## THE CAVEAT THAT DECIDES HOW TO PROCEED

**The walk stops at `hyperclaw_plan` and `auto_levels` because they cannot say what they
read — not because they read nothing.** Their inputs resolve to `[]`, so there is no edge to
follow backwards. The closure is bounded by the same ignorance it exists to remove.

**Declaring a step therefore GROWS the closure by one ring.** 6 is what is knowable today,
not the final set.

The upper bound is knowable, from the phase graph in `config/cycle_phases.json`, which is
coarse but complete:

```
phase of github_publish   : E_PROPOSE
phase of self_modifier    : F_SELF
phase of execute_patches  : F_SELF

phase closure (backward over requires/produces):
  A_ORIENT 8 + B_SENSE 10 + C_SNAPSHOT 7 + D_SCORE 13 + E_PROPOSE 7 + F_SELF 2  =  47 steps
```

Six of the seven phases feed the irreversible steps; only `G_LEARN` is downstream of them.
So **the true closure is somewhere in [6, 47]**, and only declaring reveals where.

### The stopping rule, and it is not a count

Declare, then **re-run this trace**. The trace is the measurement. After each declaration
the closure is recomputed and either it stayed at 6 (the new inputs come from files nobody
produces, so the chain ends there) or it names its next ring explicitly.

That is also why the guard in Phase 1 must be over **the named set**: a count would be
satisfied by any six steps, and the set changes by construction every time a declaration
lands. The invariant is *"every step on the path to an irreversible action can say what it
reads"*, and the path is recomputed, never assumed.

Reproduce with the script used here (kept out of the repo; it is 40 lines over
`cycle_map.STEPS`, `notary._inputs_for` and `declared_inputs.for_step`).

---

## THE NEXT RING, ALREADY READ — evidence for Phase 1, not a declaration

Read from the code, not inferred from the step name. These are the candidate inputs; the
actual entries wait until after the 03:04 cycle.

### `hyperclaw_plan` (idx 15.7) — the live blocker on `self_modifier`

Entry point: `_hyperclaw_to_proposals()`, `fast_cycle_runner.py:1691`, dispatched at `:2992`.

```
fast_cycle_runner.py:1693   plans_dir      = BASE / "plans"
fast_cycle_runner.py:1694   proposals_path = BASE / "memory" / "improvement_proposals.json"
fast_cycle_runner.py:1697   plan_files     = sorted(plans_dir.glob("plan-*.md"),
                                                    key=..., reverse=True)
fast_cycle_runner.py:1701   plan_text      = plan_files[0].read_text(...)
```

It reads **the newest `plans/plan-*.md`** and merges into `memory/improvement_proposals.json`.
The plan files are written by `agents/hyperclaw/hyperclaw_orchestrator.py:14 PLAN_DIR`,
which is the separate step `hyperclaw` (idx 15.6).

### `auto_levels` (idx 12.5)

Entry point: `memory.auto_level.run()`, dispatched at `fast_cycle_runner.py:2820`.

```
memory/auto_level.py:12   MASTER_PATH = snapshots/master/master_snapshot_latest.json
memory/auto_level.py:13   LEVELS_PATH = memory/auto_levels.json
memory/auto_level.py:197  master      = json.loads(MASTER_PATH.read_text(...))
memory/auto_level.py:201  prev_levels = json.loads(LEVELS_PATH.read_text(...))
```

The master snapshot, plus its own previous output — a fourth self-loop.

---

## THE GAP THAT WILL MAKE A CORRECT DECLARATION USELESS

**Inheritance only flows through artifacts that some step CLAIMS AS A PRODUCT.**
`notary.attest()` builds `stamps` from the attestation log's `products` field, and
`products` comes from `core/cycle_map.STEPS`. If no step lists an artifact as a product,
`stamps.get(artifact)` is `None`, and the input contributes **nothing** to inheritance —
only to the age dimension.

Both artifacts in the next ring are in exactly that position:

| artifact | claimed as a product by | consequence |
|---|---|---|
| `plans/plan-*.md` | **nobody** — `hyperclaw` (idx 15.6) declares `products: []` | declaring it gives `hyperclaw_plan` an age, but no inherited level |
| `snapshots/master/master_snapshot_latest.json` | **no step**; only the *phase* `D_SCORE` declares it | same |
| `memory/self_awareness.json` | **nobody** (already visible in the edge list above) | same — this is why `self_modifier`'s `own=1` is an age verdict alone |

**20 of 71 steps in `cycle_map.STEPS` declare no products at all.**

So Phase 1 has two halves, and doing only the first produces the failure mode named in the
instruction — *a wrong declaration makes a blind step look verified*:

1. declare what the step **reads** (`config/step_inputs.json`), which fixes the age
   dimension and removes the `UNKNOWN(0)` verdict; **and**
2. register what the upstream step **writes** (`cycle_map.STEPS` products), without which the
   artifact carries no stamp and the chain is silently broken one link earlier.

A step that passes (1) and fails (2) reports a real age and an unearned `inherited=FULL`,
because `attest()` initialises `inherited = FULL` and only lowers it when a stamp is found.
**Absence of a stamp currently reads as a clean one.** That is the same "ignorance scores as
evidence" defect the 17 August `_age_state([])` change fixed on the age dimension and which
the inheritance dimension still has.

I am flagging it, not fixing it: it is a change to the notary's inheritance default, on the
night before an unattended run, and it deserves the same caution as the gate itself.

---

## WHAT THIS MEANS FOR THE DECISION

- The scope you chose is **two declarations**, `hyperclaw_plan` and `auto_levels`, and it is
  well inside the dozen you expected. Proceed.
- Neither one alone unblocks `self_modifier`. `hyperclaw_plan` clears the inherited 0;
  `self_modifier`'s own level stays at 1 because `memory/self_awareness.json` is 176.3 days
  old. That file was **not touched**, per instruction, and remains a separate finding.
- Expect the closure to grow when the trace is re-run, and expect the growth to be small —
  the next ring's artifacts (`plans/`, the master snapshot) have no registered producer, so
  the walk will terminate there again until `cycle_map` products are filled in. **That is a
  reason to re-measure, not a reason to assume.**
