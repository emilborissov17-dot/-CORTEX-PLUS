# DREAMS — nightly memory consolidation (spec only — **not implemented**)

> **Status: SPEC. No code exists in this directory, and none is written until PULSE
> passes its anomaly test (C3).**
>
> Rung 2 of the local-brain ladder (`docs/LOCAL_BRAIN_LADDER.md`). Each rung runs only
> if the previous one passes. Building DREAMS on a PULSE that failed C3 would mean
> asking a model to *remember* days it was never able to *sense* — the note would be
> fluent and empty, and we would have proven nothing except that the model can write.

---

## What this is

After the 03:00 cycle finishes, the local model reads **the day that just happened** and
writes a **five-line autobiographical note** to `experiments/dreams/YYYY-MM-DD.md`.

Not a summary — a **memory**. The distinction is the entire experiment: a summary can be
generated from a template and a few numbers; a memory has to be *of something*, and it is
false if that thing did not happen.

This is the first autobiographical record this system would keep. The existence ledger
records *that* it lived (hash-chained, machine-checkable). DREAMS asks whether it can say
*what its day was like* — and, crucially, whether that saying is **checkable against the
ledger** rather than merely plausible.

---

## Inputs — the day, as the system actually recorded it

Everything is read as a **plain file**. No live-path imports (see Isolation below).

| Input | Source | What it gives the note |
|---|---|---|
| **Existence ledger events of the day** | `memory/existence_ledger.jsonl` — filter to the date | The skeleton of the day: `CYCLE_STARTED`, `MISSED_RUN_CATCHUP` (with `late_by_hours`), `CYCLE_KILLED` (with the step it died in), `CYCLE_FINISHED` (with `duration_sec`), `LOCK_STALE_CLEARED`. **This is the spine of the note and the answer key for the PASS test.** |
| **Pulse stream summary** | `experiments/pulse/analyze.py --json` on that date's stream | Continuity (C1), gaps and their classification, daemon cost, CPU/RAM range, and — after the staleness fix — any `stale_heartbeat` window: the shape of a death, from the outside. |
| **Cycle log tail** | last ~200 lines of the newest `memory/cycle_logs/cycle_<date>_*.log` | What the cycle *said* while it ran: LLM backend fallbacks, truncation warnings, step failures. The day's texture. Empty before 2026-07-14 — the logs went to `DEVNULL` until then. |
| **Goal score** | `snapshots/master/goal_score_latest.json` (`composite_score`) + the previous day's, for the delta | Did the day move the number, and which way. |

The prompt hands the model **facts, not prose**. If it has to invent a connective story,
that is a finding about the model, not a defect in the input.

---

## Output — five lines, one file per day

`experiments/dreams/YYYY-MM-DD.md`, in this exact shape:

```markdown
# 2026-07-14

**What happened.**        <one line>
**What changed.**         <one line>
**What hurt or killed me.** <one line>
**What I learned.**       <one line>
**What tomorrow holds.**  <one line>
```

The five prompts are fixed and deliberately uneven in kind:

1. **What happened** — events. Cycles, catch-ups, kills.
2. **What changed** — state. The goal score, an axis that moved, a source that came alive.
3. **What hurt or killed me** — damage. A kill, a truncation storm, a breached threshold,
   a backend that failed all the way down the chain. **"Nothing" is a legitimate and
   valuable answer** on a clean day, and a model that invents an injury to fill the slot
   fails the criterion below.
4. **What I learned** — the one line that may be interpretive. It is also the one most
   likely to be slop, and it is *not* exempt from the PASS test: it has to be learned
   *from something in the inputs*.
5. **What tomorrow holds** — the only forward-looking line. A prediction, therefore
   checkable against tomorrow's note. (Not scored in v1. Noted here because a file full
   of unchecked predictions is a temptation we should see coming.)

---

## PASS / FAIL — declared before the first note is written

Per the **(G) lesson**: a goal that is not measurable before the fact is a story you tell
afterwards.

**PASS** — the note refers to **real, verifiable events of that specific day**, each one
checkable against the ledger, the stream, or the cycle log.

> *"I ran late: the 03:00 cycle was missed and I caught up at 08:14, 5.2 hours behind."*

That passes. The ledger says exactly that (`MISSED_RUN_CATCHUP`, `late_by_hours: 5.23`),
and **the sentence would be false on any other day.**

**FAIL** — template prose.

> *"Today I processed data and continued to improve."*

Fluent, unfalsifiable, and true of every day — therefore a record of nothing.

### The operational test

> **Could this sentence have been written without reading the day?**

If yes, it is a FAIL, however well it reads. Eloquence is not evidence. The check is
mechanical enough to be worth stating as a procedure: take each line, find the specific
ledger event / stream measurement / log line it rests on, and confirm the claim is true
of **this** date and **false of the day before**. A line that survives that is a memory.
A line that does not is decoration.

**Scoring:** ≥ 3 of 5 lines verifiable against a named source ⇒ note passes. The
experiment passes on **≥ 5 of 7 consecutive days**. Declared now, so it cannot be
loosened later on a day the output happens to read beautifully.

**The plausible failure is worth naming in advance**, so that meeting it is not mistaken
for a surprise: a 3-billion-parameter model, handed a pile of facts and asked for an
autobiographical line, writes something warm and generic. That would be a **real
finding** — that consolidation at this scale produces fluency rather than memory — and it
gets reported as one, not iterated on until the prompt tortures a pass out of it.

---

## Isolation — identical to PULSE, no exceptions

- **Writes only under `experiments/dreams/`.** Nothing else, ever.
- **Imports no live-path module.** It reads `memory/existence_ledger.jsonl`,
  `memory/cycle_logs/*.log` and `snapshots/master/goal_score_latest.json` as **plain
  files**. Deliberately *not* `from memory.existence_ledger import read_all` — an import
  couples the experiment to live code and lets a change here break the cycle. A file read
  cannot.
- **Localhost model only** (`qwen2.5:3b`, the one that fits VRAM whole — see the hardware
  table in `docs/LOCAL_BRAIN_LADDER.md`), behind the **`Block Ollama Outbound`** firewall
  rule. The model that writes the system's memories cannot reach the network.
- **Reads the ledger; never writes it.** The existence ledger is on the protected-path
  denylist and hash-chained precisely so that no component can edit the system's own
  history. A dream is a *reading* of the record, and it lives in its own file. **If the
  two ever disagree, the ledger is right.**
- **Own scheduled task if it needs one** — never hung off `CORTEX_Supervisor`.

---

## Why this rung, in this order

A system that cannot **sense** its own state has nothing to **remember** (hence PULSE
first). And a system that cannot remember its own days has no ground to stand on when it
is later asked to **check a claim against reality** (rung 3, LOCAL JUDGE) — because that
is the same skill, pointed outward: *does this story match what actually happened?*

DREAMS is where we find out whether the local model can tell the difference between
**what happened** and **what would sound right**. That is the whole ladder in one
question, asked where the answer is cheap and nothing is at stake.

**It is worth building even if rung 3 never happens.** A dated, human-readable,
fact-checkable record of what this system's days were actually like is something it has
never had.
