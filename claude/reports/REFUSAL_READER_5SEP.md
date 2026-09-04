# THE READER — what thirteen unread nights actually contained, 5 September 2026

The diagnosis said publishing stopped because a gate refused *silently*. It did not.
`memory/night_events.jsonl` held the refusals all along, each naming the gate and the
reason. The mechanism worked; nobody opened the file. So this is a reader, not another
writer.

## 1. THE TWO GENUINELY SILENT BRANCHES — FIXED (commit `611bba7`)

Both in `_witness_or_refuse()`, the gate on `github_publish`, `self_modifier` and
`execute_patches`:

- **`:1969`** — the human-channel refusal printed to the cycle log and returned `False`,
  writing no event.
- **`:1970-1971`** — `except Exception: pass`. An import error in `approve_reader`, or
  any exception inside `channel_alive()`, **deleted the human second witness, printed
  nothing at all**, and let the gate carry on and still return `True`.

A new `_refusal_event(step, gate, why)` gives all refusals one shape with a `gate`
field. It is best-effort — it must never stop the cycle — but it **prints when the write
fails**, because a recorder that fails silently is the same defect one level up.

Two further silent `pass` were removed while there: gates 2 and 3 already wrote events
but wrapped each inline write in `except Exception: pass`. All four paths are now
uniform: `human_channel`, `human_channel_check_skipped`, `notary`, `metta_witness`.

**Still open, named rather than quietly widened:** the notary-*unavailable* branch
prints and falls through to the MeTTa gate recording nothing. If MeTTa then passes, the
step proceeds despite the notary being unavailable — a silent degradation, not a
refusal, so it does not fit the "ОТКАЗАНА" shape. Left for a decision.

## 2. THE READER — `tools/read_the_refusals.py`

Groups refusals by gate and step, and reports any run of **consecutive calendar nights**
longer than `--min-streak` (default 2) as a finding. Consecutive *days*, not events: a
night that refuses four times is one night, and one clear night ends the streak. That is
what makes the number mean "how long has this been broken".

It reads its own history: `gate` is only a first-class field since tonight, so older
rows have it recovered from the subject rather than reported as unknown. Malformed lines
are counted and warned about, never dropped quietly. Exit code **2** when there are
findings, so a script can act on it.

### Run over the whole history

```
events scanned   : 580
refusals found   : 72
covering         : 2026-08-16 .. 2026-09-04

BY GATE                          BY STEP
  notary          72               self_modifier     31
                                   github_publish    26
                                   execute_patches   15

FINDINGS — refusal streaks longer than 2 nights

  self_modifier / notary
      19 consecutive nights, 2026-08-17 .. 2026-09-04
      reason: level_0 (неизвестен произход) — слабо звено: no declared inputs

  github_publish / notary
      15 consecutive nights, 2026-08-17 .. 2026-08-31
      reason: level_0 (неизвестен произход) — слабо звено: no declared inputs

  execute_patches / notary
      6 consecutive nights, 2026-08-16 .. 2026-08-21
      reason: вход липсва: memory/last_attempt.txt

  execute_patches / notary
      5 consecutive nights, 2026-08-31 .. 2026-09-04
      reason: level_1 — explicit ceiling by core/notary.MAX_LEVEL
```

**The 15-night `github_publish` streak falls straight out, which is the proof it
works.** It matches the published-commit gap exactly.

### And it found something nobody was looking for

**`self_modifier` has been refused for 19 consecutive nights and is STILL refusing —
including last night, 4 September.** Every night since 17 August. The reader surfaces it
in one line; it has been sitting unread in the same file for nearly three weeks.

```
2026-09-02T01:30:57  level_0 (наследено от memory/improvement_proposals.json)
2026-09-03T01:36:11  level_0 (наследено от memory/improvement_proposals.json)
2026-09-04T01:18:19  level_0 (наследено от memory/improvement_proposals.json)
```

`self_modifier` **is** declared in `config/step_inputs.json` with four inputs, so the
31 August remedy was applied to it. It still fails because one of those inputs —
`memory/improvement_proposals.json` — carries `level_0` *from this cycle*: its own level
is `level_1`, the input's is `level_0`, and the gate takes the minimum. Different cause,
same shape, still open.

`execute_patches`, by contrast, is refusing for a **deliberate** reason since 31 Aug: an
explicit ceiling in `core/notary.MAX_LEVEL`. That is policy working, not an outage — and
a reader has to be able to tell those apart, which is why the reason is printed verbatim.

## 3. WHERE IT SHOULD SURFACE — a proposal, not an implementation

The publish channel works and reaches a public repo every night (28 commits/day). The
audit trail does not leave this machine. **Proposal: publish the refusal digest alongside
the data, so the instrument reports its own refusals publicly.**

Concretely: `github_publisher` writes one more file per day, e.g.
`reports/<date>/refusals.md`, containing the reader's output — streaks first, then counts
by gate and step. Roughly ten lines on a clean night, and on a bad night the first line
says *"self_modifier / notary — 19 consecutive nights"*.

Why publishing rather than a local file or a notification:

- A local report is what we just diagnosed. `night_events.jsonl` **was** the local
  report, and it was read for the first time tonight, nineteen nights late.
- Publishing makes the silence expensive. A gap in a public daily series is visible to
  anyone; a gap in a local JSONL is visible to nobody.
- It is the same honesty the composite already practises — `k1_fresh`, `unresolvable`,
  `COVERAGE_UNKNOWN` — extended to the gates. An instrument that publishes its readings
  but hides its refusals is publishing a filtered view of itself.

**One risk to weigh before implementing, and it is not small:** the reasons are verbatim
internal strings, including file paths (`memory/improvement_proposals.json`) and step
names. That is a small disclosure of internal structure to a public repo. Options are to
publish the streak shape and gate only, or to publish reasons in full and accept it. That
is Emil's call, not mine, which is why this is a proposal.

## 4. THE 13-NIGHT GAP — cause, and what cleared it

**The cause is fully known and was written down at the time.** The notary refused
`github_publish` on every one of those nights because the step inherits provenance from
its inputs and takes the minimum: `web_intelligence` was listed in `VERIFIERS` but
declared **no inputs**, so after a 15 August change (`e17945b`) `_age_state([])` returned
`UNKNOWN(0)` — *"ignorance is not evidence of freshness"* — which made its own level
`min(witness 3, human 2, thought 3, age 0, promise 3) = 0`. That stamped
`memory/web_intelligence` as `level_0`; `github_publish` declares that product, so
`min(own 2, input 0) = 0`, below the `IRREVERSIBLE_MIN` of 2. Refused, nightly, from
17 August. **What cleared it on 31 August was a deliberate fix, not luck:** commit
`467bcf6` (31 Aug 12:39:46 — the exact minute publishing resumed) declared
`web_intelligence`'s inputs in `config/step_inputs.json`, authorised by Emil after being
shown the cause and three simulated alternatives. Nobody is in the dark about this one.

**Correction to my own earlier report.** I wrote that the 17 August change "cannot
explain the silence because it postdates it". That was true of the change I examined —
`b03310a`, `channel_alive`, 19:50 local, ~16 hours after the last publish. But it was the
wrong change: the causal one is the `_age_state` flip in the notary, and the date really
does match. My conclusion "correlation, not causation" was right about the specific
commit I looked at and wrong about the day.

**Can it come back?** Yes, and the reader is the guard. The remedy was to declare one
step's inputs; any step added to `VERIFIERS` without declared inputs reproduces it
exactly, and `self_modifier`'s ongoing 19-night streak shows the same shape can persist
under a different input. The fix is per-step and manual; nothing structurally prevents
the next occurrence. What is different now is that a streak longer than two nights is one
command away from being visible.

---

# ADDENDUM, 01:40 — the finding the reader was built to catch

## 5. `self_modifier` — 19 CONSECUTIVE NIGHTS, STILL REFUSING

This is a bigger open item than the publish gate was. `github_publish` touched a public
repo; `self_modifier` is the step that **modifies the system itself**, and it has not been
allowed to run since 17 August.

```
started : 2026-08-17T16:21:05.499276+00:00
latest  : 2026-09-04T01:18:19.872996+00:00   (last night)
nights  : 19 consecutive, 2026-08-17 .. 2026-09-04
events  : 31 refusals
gate    : notary   (subject: "self_modifier ОТКАЗАНА от нотариуса")
```

**The reason is not one reason. It changed on 21 August, mid-streak**, which is why a
count of nights alone would have been misleading:

```
2026-08-17T16:21:05  (7 events, to 2026-08-21)
  level_0 (неизвестен произход) — слабо звено: no declared inputs - provenance unknown

2026-08-21T14:03:55  (24 events, to 2026-09-04)
  level_0 (неизвестен произход) (наследено от memory/improvement_proposals.json)
  — слабо звено: нивото не е на тази стъпка: собственото ѝ е level_1 (минимално),
    а входът memory/improvement_proposals.json носи level_0 (неизвестен произход)
    от този цикъл
```

The first form is the `web_intelligence` landmine exactly. The second form is what it
became once `self_modifier`'s own inputs were declared — **the declaration worked, and the
step is still refused, for a different reason one step upstream.** That is precisely why a
per-step manual remedy is not a fix.

## 6. THE DIAGNOSIS — and it is not where the reason points

The refusal names `memory/improvement_proposals.json`. Following that to its producer
changes the picture. From `core/cycle_map.STEPS`, **two** steps declare that file as a
product:

```
hyperclaw_plan   idx 15.7   products ['memory/improvement_proposals.json']
self_modifier    idx 18     products ['memory/improvement_proposals.json']
```

Last night's attestations, read from the notary's own log:

```
hyperclaw_plan   01:10:06  level=0  own=0  inherited=3  verifier=False
    age: "no declared inputs - provenance unknown (from the static scanner)"
    inputs: []

self_modifier    01:18:19  level=0  own=1  inherited=0  from=memory/improvement_proposals.json
    age: "най-стар вход memory/self_awareness.json: 176.3 дни
          (from the written declaration in config/step_inputs.json)"
    inputs: [improvement_proposals, development_journal, auto_levels, self_awareness]
```

**`hyperclaw_plan` runs eight minutes earlier, has no declared inputs, scores `own=0`, and
stamps `memory/improvement_proposals.json` at level_0.** `self_modifier` then reads that
file and inherits the 0. The landmine is not on `self_modifier`; it is one step upstream,
on a step that is **not** in VERIFIERS and which the test in item 7 therefore does not
cover.

**There are TWO independent blockers, and fixing either alone changes nothing:**

1. **inherited = 0**, from `hyperclaw_plan`'s undeclared inputs.
2. **own = 1**, because `memory/self_awareness.json` is **176.3 days old**, which the age
   dimension scores MINIMAL. `IRREVERSIBLE_MIN = REDUCED = 2` (`core/notary.py:80`), so
   even with the inheritance cleared, `self_modifier` stands at level_1 and is still
   refused.

There is also a **ratchet worth noticing**: `self_modifier` both reads and produces
`improvement_proposals.json`. Its own stamp on that file is the level it was refused at, so
once the file has been stamped 0, the step re-reads its own 0 the next night. Nothing in
the mechanism recovers on its own.

### The options, none of them taken tonight

| # | option | effect | cost |
|---|---|---|---|
| A | declare `hyperclaw_plan`'s inputs in `config/step_inputs.json` | clears blocker 1 only; `self_modifier` goes 0 → 1, still refused | the honest one; requires reading the module and writing `derived_from` |
| B | refresh or retire `memory/self_awareness.json` (176 days stale) | clears blocker 2 only; still 0 from inheritance | needs a decision on whether that file should be a live input at all |
| C | A **and** B | `self_modifier` reaches level_2 and the gate opens | opens the self-modification path — the one that most deserves a human present |
| D | add `hyperclaw_plan` to `VERIFIERS` | breaks inheritance, level_0 washed clean | **rejected**: it does not verify against a live external source; this would grant the washing privilege to a planner, which is the exact abuse the short explicit list exists to prevent |
| E | leave it | 20th night | the refusal is now visible, which it was not yesterday |

**Taken: E, tonight.** Changing the gate on the only path that modifies the system itself,
at 01:15, before an unattended run, is the wrong hour for it. Nothing in the mechanism was
touched. Option C is the real fix and it wants a human awake.

**One thing to weigh before choosing C:** 19 nights of refusal means 19 nights of proposals
that were never applied. Opening the gate does not replay them one at a time — check what
`self_modifier` would do on its first permitted run before permitting it.

## 7. THE LANDMINE, MADE STRUCTURAL — `test/test_verifier_inputs.py`

A step in `VERIFIERS` may break inherited provenance. That privilege is granted by name, in
a set literal (`core/notary.py:126-132`), and nothing ever checked that the named step can
say what it reads. A verifier with no declared inputs scores `UNKNOWN(0)` and stamps 0 on
everything downstream — 15 nights for `github_publish`, 19 for `self_modifier`.

The new test fails if any name in `VERIFIERS` has no declared inputs in
`config/step_inputs.json`. `for_step()` returns `None` for undeclared and `[]` for
declared-but-empty; **both fail**, because both produce UNKNOWN.

### It is RED today, and these four are why

```
$ venv\Scripts\python.exe -m pytest test/test_verifier_inputs.py -q
1 failed, 8 passed

FAILED test_every_verifier_declares_what_it_reads
  browser_scout
  global_indicators
  internet_intelligence
  sensorium_ingest
```

Four of the five verifiers. The fifth, `web_intelligence`, is the one declared on 31 August
— and it scores level_3 today, which is the counter-example the test also asserts, so the
failure above is not vacuously true of everything.

The other eight tests pass and are the structural part:

- **the ratchet** — a *newly* added undeclared verifier fails in its own test, so it cannot
  hide inside the already-red one. This is what makes the next occurrence impossible to
  miss rather than merely unlikely.
- **the ledger tests** — the four names must leave `KNOWN_UNDECLARED` when declared, and
  must leave it when removed from `VERIFIERS`. A stale ledger silently re-permits.
- **the mechanism** — each of the four is put through `_inputs_for` → `_age_state` right
  now and asserted to answer 0 with "no declared inputs". Not an assumption.

**No `xfail`.** Rendering this failure as something plausible is the exact defect the file
is about.

### The measurement that reframes the whole item

While confirming the above I asked the same question of every step, not just the verifiers:

```
steps in core/cycle_map.STEPS                     : 71
steps whose inputs resolve to []  (-> level_0)    : 66
  ...of those, that PRODUCE artifacts             : 47
```

**Only 5 of 71 steps can say what they read** — the five written into
`config/step_inputs.json`. 47 undeclared steps stamp level_0 onto artifacts that other
steps inherit. `VERIFIERS` is 5 of those 71; the test covers the 5 where the consequence is
worst, because a verifier is also allowed to *wash* a level clean. **It does not cover
`hyperclaw_plan`, which is the step actually blocking `self_modifier` tonight.**

So: the test closes the door on the specific hole that cost 34 nights across two steps, and
the census says the same shape exists 66 times over. That is a scope decision for a human,
not a fix to make at 01:40 — but it should not be discovered a third time by a streak.

