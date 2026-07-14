# The local-brain ladder

Five stages. **Each runs only if the previous one passes.**

The order is not arbitrary and it is not a project plan — it is a claim about what has
to be true before the next thing is even meaningful to attempt:

> **senses → remembers → distinguishes truth → judges → earns a role**

A system that cannot sense its own state has nothing to remember. One that cannot
remember its own days has no ground to check a claim against. One that cannot tell a
true claim from a fluent one has no business judging a patch. And one that has never
judged anything correctly has not earned a role in the live cycle.

**Every stage is independently useful even if the next one fails.** A pulse that never
grows into a judge is still a proprioceptive record the system did not have. A dream
log that never becomes a cross-checker is still the first autobiographical memory this
system has ever kept. Nothing here is scaffolding that gets thrown away — which is what
makes it safe to stop at any rung.

Per the **(G) lesson**: *a goal that is not measurable before the fact is a story you
tell afterwards.* Every PASS/FAIL below is declared before the stage runs, not after.

---

## The rungs at a glance

| # | Stage | Status | The question it answers |
|---|-------|--------|------------------------|
| 1 | **PULSE** | 🟢 running | Can it *sense* itself, continuously and cheaply? |
| 2 | **DREAMS** | 📋 specced, not built | Can it *remember* a specific day as its own? |
| 3 | **LOCAL JUDGE** | ⬜ blocked on 2 | Can it tell a *true* claim from a fluent one? |
| 4 | **QUARANTINE PRE-READER** | ⬜ blocked on 3 | Can it *judge* work before a human does? |
| 5 | **SHADOW DUEL** | ⬜ blocked on 4 + (G) doc | Has it *earned* a role in the live cycle? |

---

## 1. PULSE — continuous self-sensing

**Running.** `experiments/pulse/`. Registered as the `CORTEX_Pulse` scheduled task
(MINUTE/5 variant: the single-instance lock makes a 5-minute respawn tick safe, and it
self-heals — a daemon that dies is replaced within five minutes rather than leaving a
hole in the record).

A 10-second sensory stream: CPU, RAM, disk, network throughput and reachability, cycle
step (from `memory/heartbeat.json`), the existence ledger's last event, and churn under
`memory/`. No LLM in the daemon. The local model reads the stream and narrates
(`self_sense.py`); making meaning is a **separate process** from sensing.

| Criterion | Status |
|---|---|
| **C1** — stream survives 24 h with no unexplained gap > 30 s | ✅ measured (median gap 9.99 s; sleep/restart gaps classified, not silently dropped) |
| **C2** — local model returns parseable JSON in < 30 s per tick | ✅ measured — 8.28 s with `qwen2.5:3b` |
| **C4** — daemon < 1% CPU; inference does not breach BODY's 70% RAM threshold | ✅ measured — daemon mean **0.018% CPU / 25 MB**; model **0.00 GB system RAM** |
| **C3** — 🎯 **THE ANOMALY TEST** | ⏳ **pending — running now** |

**C3 is the stage.** C1, C2 and C4 are prerequisites; C3 is the result. A real event is
triggered while the loop runs, and the question is whether the narrative **notices it
within 2 ticks, unprompted**:

- **PASS** — `anomaly` is non-null, or `changed` names the actual event *specifically*:
  *"CPU rose to 94% and a cycle began at step `web_intelligence`"*.
- **FAIL** — *"System resources are being utilized."* That is **describing, not
  sensing**: it would have been emitted no matter what happened.

*Falsification is the point.* The plausible failure is that the model narrates smoothly
and notices nothing. That is a **real finding** and gets reported as one — not explained
away, and not retried until it passes.

**Nothing below this line starts until C3 passes.**

---

## 2. DREAMS — nightly memory consolidation

**Specced, not built.** Full implementation spec: `experiments/dreams/README.md`.

After the 03:00 cycle finishes, the local model reads **the day**: the existence
ledger's events, the pulse stream (via `analyze.py`), the tail of the cycle log, and the
resulting goal score. It writes a **5-line autobiographical note** to
`experiments/dreams/YYYY-MM-DD.md`.

- **PASS** — the note refers to **real, verifiable events of that specific day**, each
  checkable against the ledger, the stream, or the cycle log. *"I ran late — the 03:00
  cycle was missed and I caught up at 08:14, 5.2 hours behind"* is a pass, because the
  ledger says exactly that and the sentence would be **false on any other day**.
- **FAIL** — template prose. *"Today I processed data and continued to improve."*
  Fluent, unfalsifiable, and true of every day, which means it is a record of nothing.

The test is **specificity, not eloquence**. The question behind the criterion: *could
this sentence have been written without reading the day?* If yes, it is a FAIL however
well it reads.

---

## 3. LOCAL JUDGE — sovereign cross-check

**Blocked on stage 2.**

The local model verifies **narrative claims made by the external LLM** against the raw
data underneath them. Not levels — *narratives*. `[CORR]` already catches a number that
disagrees with its source; this is about a **story** that disagrees with its source.

- **PASS** — catches **at least what `[CORR]` catches**, and does it on narratives
  rather than on levels.
- **FAIL** — anything less. A cross-checker that catches less than the mechanism it
  supplements is a second opinion nobody should ask for.

**Why this rung matters most.** It is the first one where the local model is not merely
useful but **structurally load-bearing**: an external API cannot be the sole judge of
whether an external API told the truth. Divergence detection is the system's mission
(`docs/IDENTITY.md`), and a mission that depends entirely on the thing it is meant to
audit is not a mission — it is a formality. A local judge running on hardware Emil owns,
on weights that cannot phone home, is **sovereignty by construction** rather than
sovereignty by promise.

---

## 4. QUARANTINE PRE-READER — 2-line verdicts on quarantined patches

**Blocked on stage 3.**

For each quarantined patch, the local model writes **two lines**:

1. **What it does**, and **where it writes**.
2. **Junk or not**, per the `measurable_goal` rule — a patch that chases a score instead
   of solving a stated, measurable problem is junk, however clean the diff.

- **PASS** — agrees with **Emil's verdict on ≥ 4 of 5** historically reviewed patches.
  We hold **10 patches with known human verdicts**, so this is scored against a real
  answer key that already exists — it cannot be graded generously after the fact.
- **FAIL** — ≤ 3 of 5.

This rung is **triage, never authority**. The pre-reader does not approve, merge, or
release anything from quarantine. It reads first so a human reads second, faster. The
guardian and the protected-path denylist are untouched by it, and stay that way.

---

## 5. SHADOW DUEL — local vs external on the `self_observer` role

**Blocked on stage 4, and on a design document that does not yet exist.**

The local model runs **in parallel** with the external one on the `self_observer` role
for N cycles. Neither is switched off; the local one has no effect on the live cycle.
Metrics are **pre-declared**, promotion follows the **(G) rules**.

> **Hard gate: this stage cannot begin before the (G) design doc exists.** Promotion
> criteria written after seeing the results are not criteria, they are a rationalisation
> — the exact failure the (G) lesson names. If the doc is not written, the duel does not
> run. No exceptions, including "it obviously won".

---

## Hardware facts — measured, not assumed

Measured **2026-07-14** on this machine (GTX 1650, ~3.9 GB free VRAM; system RAM already
~56–70% used at rest, against BODY's **70%** caution threshold):

| Model | Size | Fit | System RAM cost |
|---|---|---|---|
| **`qwen2.5:3b`** | 1.93 GB | ✅ **fits VRAM entirely** (2.39 GB total, **100% VRAM**) | **0.00 GB** |
| `qwen3:1.7b` | ~1.4 GB | ✅ fits — but reasoning (`<think>` costs latency every tick) | ~0 |
| `qwen2.5:7b` | 4.68 GB | ❌ **spills** ~1.9 GB into system RAM | pushed RAM to **92.3%** |
| `qwen3:8b` | 5.23 GB | ❌ spills more, and reasoning on top | worse |

**Fit beats capability on this hardware, and it is not close.** A model that fits costs
~zero system RAM. One that spills eats exactly the resource BODY's threshold protects —
and above 70% BODY cuts the live cycle's workers from 3 to 2, which means **the
experiment would be degrading the live system it is supposed to be isolated from.**

`qwen2.5:3b` is therefore the default for every rung of this ladder, and
`PREFERRED_MODELS` in `self_sense.py` is ordered by **fit**, not by intelligence. The
7b is not a better model we settle for; it is a worse one we fall back to only if
nothing that fits is installed.

> Caveat, stated because it will otherwise be misread later: the C4 pass sits at **69.6%
> system RAM against a 70% threshold — a 0.4-point margin, and that residual is not
> ours.** The model contributes 0.00 GB. The pressure is everything else on the machine.
> A future C4 breach is therefore not automatically the pulse's fault, and must not be
> read as one.

---

## Egress policy — sovereignty by construction

**Windows Firewall rule `Block Ollama Outbound` is ENABLED.** The local model cannot
reach the network. Not "is configured not to" — **cannot**.

This is the difference between a sovereignty claim and a sovereignty *property*. A local
judge that could phone home would be trusted on the strength of a promise about its
configuration; one that is firewalled off is trusted on the strength of the operating
system. The whole point of stage 3 is to have a judge whose independence does not rest
on the good behaviour of the thing it is judging.

**To pull a model:**

```
1. Disable  "Block Ollama Outbound"
2. ollama pull <model>
3. Re-enable "Block Ollama Outbound"      ← do not skip; do not defer
```

The window is open only for the pull, and it is closed by hand immediately after. A rule
that is "usually on" is a rule that is off on the day it matters.

---

## Isolation rules — every stage, no exceptions

Inherited unchanged from PULSE (`experiments/pulse/README.md`), because they are what
make it safe to run experimental code on the same machine as the live system:

- **Writes only under its own `experiments/<stage>/` directory.** Nothing else, ever.
- **Imports no live-path module.** It reads their *output files* as plain JSON. An import
  couples the experiment to live code and lets a change here break the cycle. A file read
  cannot. `self_sense.py` re-implements JSON extraction in miniature rather than import
  `core/llm_json` — thirty duplicated lines are the correct price.
- **Localhost model only**, behind the egress block above.
- **No live-path writes, no scheduler entanglement.** PULSE has its own scheduled task
  (`CORTEX_Pulse`), deliberately **not** hung off `CORTEX_Supervisor`: the supervisor is
  constitutional machinery on the protected-path denylist, and day-0 experimental code
  does not get to reach into it. Every later stage inherits this.
- **If a stage earns promotion, it goes through the normal path** — gates, guardian,
  review. Not by quietly growing into the cycle.
