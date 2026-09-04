# THE SILENCES — a census, 5 September 2026

Read-only. Nothing was repaired. Counted over live code only — `venv*/`, `test/`,
`history/`, `__pycache__/`, `claude/` excluded.

A *silence* here means: a failure at this point produces something plausible instead
of an error, and a reader downstream cannot tell the difference.

## THE TEMPLATE — `_witness_or_refuse`, and it is still open

`fast_cycle_runner.py:1947`. Three irreversible steps depend on it: `github_publish`
(touches the world), `self_modifier` and `execute_patches` (touch the system itself).

```python
1963:    try:
1964:        from experiments.needs.approve_reader import channel_alive
1965:        _ok_human, _why_human = channel_alive()
1966:        if not _ok_human:
1967:            print(... human channel is dead ...)      # <- this path IS visible
1969:            return False
1970:    except Exception:
1971:        pass                                          # <- THE SILENCE
```

**What the caller sees:** the function carries on to the notary and can return
`True`. An import error in `approve_reader`, or any exception inside
`channel_alive()`, removes the human second witness entirely — and prints nothing.

**Visible anywhere?** No. Not a log line, not an event, not an exit code. The refusal
at 1967 is loud; the *absence of the check* is mute. That asymmetry is the defect:
the gate reports when it says no, never when it was not asked.

**Time to notice:** unbounded. This is the shape that cost 15 invisible nights.

## THE COUNTS

| category | count |
|---|---:|
| `except Exception: pass` (silent swallow) | **364** |
| bare `except: pass` | 0 |
| `.get(k, "")` | 478 |
| `.get(k, 0)` | 325 |
| `.get(k, [])` | 340 |
| `.get(k, {})` | 309 |
| **defaulted `.get` total** | **1452** |
| functions named gate/witness/refuse/publish/verify/check | 100 |
| ...of those, returning falsy BEFORE any write | **6** |
| hardcoded `http(s)://` URLs | 372 |
| hardcoded model names (`qwenX:Nb`) | 55 |
| hardcoded `C:\Users` paths | 2 |

1452 defaulted `.get`s cannot each be judged, and most are harmless (formatting,
display). The ranking below is by **what the default feeds** — a decision, a metric,
or a training target.

## RANKED — longest to shortest time-to-notice

### 1. `_witness_or_refuse` human-channel check — UNBOUNDED
`fast_cycle_runner.py:1970-1971`. Gates the only three irreversible steps. Silence
removes a witness; nothing anywhere records that it was removed.

### 2. `core/source_trust.py` — 9 silent swallows, feeds trust decisions
Lines `91, 157, 384, 426` and five more. Source trust decides which readings are
believed. A swallowed exception leaves the previous trust value standing, which is
indistinguishable from "checked and fine". Nothing logs the skip.
**Time to notice: months** — trust decays or fails to decay with no visible event.

### 3. `core/global_indicators.py` — 30 defaulted `.get` + 3 silent swallows
This file IS the composite's data intake. Every `.get(field, 0)` converts "the
provider did not return this" into "the value is zero", and zero is a legitimate
reading for several axes. Time to notice: only via the axis going flat — exactly the
staleness `k1_fresh` was built to expose, which went unnoticed for months.

### 4. `merkle_to_training.py` — 8 defaulted `.get`, 1 silent swallow
**This one already fired.** `d.get("action", "")` produced 46 training records with
empty targets over two months, reported as success every night. Fixed 4 Sep by
routing through the declared contract in `training/corpus_from_merkle.py`; the
remaining 8 defaults are the same class. **Time to notice: two months, measured.**

### 5. `core/notary.py` — the gate `_witness_or_refuse` delegates to
`154-155` returns `UNKNOWN` with a reason on exception (honest). But `278-279` is
`except Exception: pass`, and `175-176` returns bare `None`. The notary decides
whether irreversible actions may proceed; a `None` from it reads as absence, not as
failure.

### 6. `core/request_signing.py:136 verify()` — fail-closed but mute
Returns `False` for three different facts: payload is not a dict, no signature
present, and *no key loaded*. A missing key fails everything closed forever — the
safe direction — but the caller cannot distinguish "unsigned" from "we have no key"
from "forged". Consumed directly by
`experiments/desktop_hands/action_ledger.py:138`,
`experiments/grounding/divergence_ledger.py:364`,
`experiments/prophecy/prophecy_ledger.py:210`.

### 7. Gate-named functions returning falsy before any write — 6 total
```
core/axon_agents.py:500         _refuse_url()
core/cycle_vector.py:171        was_refused()
core/p_survive.py:137           _ttt_to_gate()
core/request_signing.py:140     verify()
fast_cycle_runner.py:979        _checkpoint_step()
memory/existence_ledger.py:327  was_refused()
```
`_checkpoint_step` is notable: a checkpoint that silently does not happen makes a
future `--resume` re-run work it believes was already done.

### 8. Silence density by file (top of the 364)
```
32  fast_cycle_runner.py                 21  supervisor.py
13  core/cycle_report.py                  9  experiments/pulse/pulse_continuum.py
 9  experiments/needs/needs_report.py     9  core/source_trust.py
 9  core/brain.py                         8  experiments/needs/approve_reader.py
 8  core/self_diagnosis.py                8  core/phase_evidence.py
```
`supervisor.py` at 21 deserves its own pass: it is the component that decides whether
the cycle is alive and whether to kill it.

## WHAT IS *NOT* SILENT — the counter-examples worth copying

- `goal_score_calculator.py`: **0** silent swallows. Its failure paths print to
  stderr with a named reason and a fix command.
- `evaluator.py`, `core/cycle_integrity.py`: **0 and 0**. Every refusal carries a
  named reason (`unresolvable_reason`, `not_full[].why`).
- `core/measurement_honesty.py`: 2 defaulted `.get`, 0 silent swallows; `k1_why`
  states how the numerator was reached, or why there is no number.
- `core/notary.py:212` chooses `UNKNOWN` over `MINIMAL` on failure, with a comment
  saying the old behaviour was "the same hole under another name".

Same codebase. The pattern is available; it is simply not applied uniformly.

## HONEST LIMITS OF THIS CENSUS

- 1452 defaulted `.get`s were counted, not individually judged. The ranking is by the
  file's role, not by proving each site reaches a decision.
- 372 hardcoded URLs is a raw count including comments and docstrings — an upper
  bound, not 372 configuration defects.
- The gate scan is AST-based and matches on *name*, so a gate not named
  gate/witness/refuse/publish/verify/check is invisible to it. There will be more.
- Nothing was repaired, per instruction.
