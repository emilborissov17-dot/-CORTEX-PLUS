# experiments/prophecy — K1a: does self-observation actually help? (sealed, un-gameable)

**The bet under test:** persistence + self-observation + self-correction → intelligence.
**The honest test:** not "does the error curve fall" (a trend-line does that), but
**"does a predictor that attends to the system's own recent state beat a matched
control that uses only the static base rate — on predictions sealed BEFORE reality
answered?"** If yes, self-observation adds predictive value about the system's *own*
behaviour. That is direct, falsifiable evidence for the bet.

## Why it can't be faked
Every prediction is appended to a hash-chained ledger (`prophecy_ledger.py`, same
pattern as `memory/existence_ledger.py`): `hash = sha256(prev_hash + record)`. Editing
any past prediction after seeing the outcome breaks every hash after it (proven in the
build: retro-fitting a sealed record flips `verify()` to invalid). At cycle commit the
head hash should be anchored into the Merkle root, exactly like the existence ledger —
so the whole prediction history is sealed into a root a later edit cannot match. Most
agent demos cannot prove they didn't peek. This can.

## What is predicted — the system's OWN actions/state, never smooth externalities
Predicting co2/temperature would be a confounded test: smooth physical series have
trivial baselines, and they measure world-modeling, not self-modeling. So the targets
are things where being right *requires a model of the system itself*:

- **self_failure** (live, first target): will the next cycle finish, or die at a step?
  - learner  = recent-window finish rate (self-observation of the current regime)
  - baseline = all-time finish rate (static prior, no current self-knowledge)
  - outcome  = the next terminal cycle event in `existence_ledger.jsonl`
  Tied directly to the death-attribution fix (efee6f5) that made deaths legible.
- **patch_effect** (scaffold): a just-applied patch's own `measurable_goal` vs "no change".
- **axis_next** (scaffold): self-model of next-cycle axis level vs persistence.

## Pre-declared pass/fail (fixed before running — the (G) discipline)
- **PASS** iff, over N ≥ 20 scored predictions: `learner_beats_control` — the learner's
  MAE is below the control's AND its head-to-head win rate > 0.5, with a chain that
  `verify()`s valid. 
- **FAIL** iff the learner does NOT beat the control despite self-observation. A FAIL is
  a real result: it falsifies "self-observation adds predictive value here" for this
  target, and we do NOT paper over it by switching to an easier metric.
- **Guard:** report N and the win rate every run; never claim learning from a falling
  absolute curve alone.

## Where this sits in the organism (mind / spirit / body + memory levels)
- **BODY** = the sensor spectrum (PULSE, homeostasis, body_scanner, global_indicators)
  supplies the raw self-state the learner attends to.
- **MIND** = *this* loop: predict → seal → observe → score → (later) correct.
- **SPIRIT** = the goal/identity layer the predictions ultimately serve.
- **Memory hierarchy:** heartbeat/pulse (sensory) → cycle state (working) →
  existence_ledger/snapshots (episodic) → dreams (consolidation) → `merkle_to_training`
  (semantic/procedural, into the weights). prophecy reads the episodic level and, once
  a learner is fine-tuned on its own sealed history, tests whether learning reached the
  weights.

## Usage
```
python experiments/prophecy/prophecy.py --predict   # seal a prediction for the next cycle
python experiments/prophecy/prophecy.py --score     # score matured predictions
python experiments/prophecy/prophecy.py --status    # the K1a scoreboard (learner vs control)
```
Recommended wiring (decoupled from the safety-critical runner): a scheduled job runs
`--score` then `--predict` once per cycle cadence. It only reads the existence ledger
and writes its own gitignored data; it cannot affect a cycle.
```
schtasks /Create /TN "CORTEX_Prophecy" /TR "cmd /c cd /d C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED && venv\Scripts\python.exe experiments\prophecy\prophecy.py --score && venv\Scripts\python.exe experiments\prophecy\prophecy.py --predict" /SC DAILY /ST 04:00 /F
```
