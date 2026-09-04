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
