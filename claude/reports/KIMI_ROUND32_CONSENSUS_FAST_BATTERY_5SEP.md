# KIMI ROUND 32 — CONSENSUS ON THE FAST BATTERY, 5 September 2026, 17:55

Provenance: same kimi.ai chat as Round 31 (`1a070ed8-…`), K2.6 INSTANT (site fell back
from Thinking under load), package `claude/reports/KIMI_ROUND32_PACKAGE_FAST_BATTERY_5SEP.md`.
Kimi has the package, not the repo. Two exchanges: the attack, then three closing questions.
Consensus was reached explicitly; Emil's instruction was "consult Kimi, then put it on the
board as tasks". This file is what went on the board.

## KIMI'S RULINGS (verbatim where it matters)

**Refused outright — deleted from the battery.**
- T11 (goals): "You just spent Round 31 eliminating imagination from the proposal
  generator. T11 reintroduces it for goals… A Merkle hash of subjective judgment is still
  subjective. Cut it."
- T13 (linear probe for axis identity): "A ceremony is a test that cannot fail
  meaningfully. This cannot."

**Refused in stated form, core kept.**
- T4 (new concepts): no human judge — "p-hacking with extra steps". Quantitative: linear
  probe on the adapter's hidden states predicts the KNOWN synthetic latent above chance.
  "The human is not ground truth; the data-generating process is." 2 h on an existing adapter.
- T10 (self-model): "which step is slowest" is telemetry; "will self_modifier be refused"
  is persistence 20/20. Legitimate form: multi-class classification of WHICH notary rule
  fires, given the proposal, vs persistence baseline. "If the system cannot learn them from
  20 nights of logs, it cannot model a bureaucracy simpler than itself."

**Conditional.**
- Sandbox (T6/T8/T12): legitimate under the 31 Jul wall — "a pilot in a flight simulator is
  not flying a plane". Ceremony IF transparent: must be a black-box observe()/intervene()
  API with the true structure hidden from every process; non-linear, colliders, mediators,
  10 variables not 25; 2 days not 4; T8 (observational train → interventional test) is the
  single critical eval. Size (closing q. c): **400 observational + 100 interventional.**
- T3 (few-shot curve): only if T2+ is marginal; skip if T2+ passes with margin.

**Cut to hours.**
- T1 (transfer): one adapter, evaluated ZERO-SHOT per held-out axis, no retraining — 25
  evaluations, not 25 GPU runs. "A week to a morning."
- T7 (calibration backtest): keep, script it, 2 h. "Refuse to skip — calibration is real."
- T5 (active seeking): keep as is. "The only test of information-seeking."

**Two tests Kimi added (day 2).**
- Validator efficacy, 30 min: 50 old "Action required for PLANET" proposals → 50 refusals;
  50 synthetic proposals with real indicator + delta + deadline → 50 admissions. "The
  load-bearing wall between Round 30 and Round 32."
- Capability constraint, 1 h: with the new prompt, generate 100 proposals from real axis
  triggers; count those outside {read indicator, write JSON, propose patch, publish}. >10%
  = "the generator is still hallucinating agency."

**Order: positive control first, before Run B — "Yes. Unconditionally."** If T2+ fails,
stop and fix the bench; Run B waits. Run A's adapter can be evaluated on the
positive-control corpus retroactively.

**Closing questions.** (a) synthetic readings in the positive control: "Yes — bench
sensitivity is a property of the ranking metric, not the data source." (b) SEEN table as
the verdict for a finite label set: "Yes — the real task is a closed finite axis set; SEEN
is the correct frame." (c) sandbox size: 400 + 100.

## THE WEEK, AS AGREED
- Day 1 (6 Sep): T2+ positive control (morning). Pass → Run A's adapter on the PC corpus
  (afternoon). Fail → stop, fix bench.
- Day 2 (7 Sep): T7 backtest, validator efficacy, capability constraint; T3 only if T2+ marginal.
- Day 3 (8 Sep): T5 active seeking, T1 zero-shot transfer, T10 notary-rule classification.
- Days 4–5 (9–10 Sep): sandbox — 10 variables, hidden non-linear structure, black-box API.
- Days 6–7 (11–12 Sep): T8, T6, T12 in the sandbox; T4 probe in parallel.
- GPU budget: Run A (spent), T2+ (1), Run B (1), sandbox training (1); one reserve for T3.

## CLAUDE'S NOTE
Kimi's "real axis values" in T2+ is satisfied by the rule being the ground truth; the
generator uses synthetic readings (seed 20260905) — confirmed acceptable in (a).
`training/make_positive_control.py` and `tools/RUN_PC_5SEP.cmd` are on disk; the run
refuses while the card is busy (Run A until ~18:40).
