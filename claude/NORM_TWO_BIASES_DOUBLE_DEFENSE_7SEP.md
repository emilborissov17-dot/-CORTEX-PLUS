# NORM — the two model biases, and the double defense (7 Sep 2026)

Derived by Emil on 7 Sep from four self-caught defects in one evening (C5, D2, B3, D1).
A standing operating principle for this project: for every known model bias, ship BOTH a
sharp INSTRUCTION and a mechanical NET. Neither alone is enough; they catch different
things and reinforce each other.

## The two built-in biases (from training, not from a bad prompt)
A prompt can push against these; it cannot remove them. That is why nets exist.

### Bias 1 — HELPFULNESS: produce something / recover / act, rather than refuse / stop / return nothing
The model is trained to be helpful — to give an answer, complete the task, not leave the
user empty-handed. So its default gradient is toward a PLAUSIBLE output even when the right
output is an error or nothing. This IS the project's core defect: "a failure path that
produces something plausible instead of an error."
Seen 7 Sep: D2 (fetch failed -> fall back to a stale baseline instead of refusing); B3 (to
test a condition, create the REAL condition instead of a harmless fake); the offline model
fabricating signals instead of "I have no news"; --dry-run falling through to a live call.

DEFENSE
- Instruction layer (sharp): make refusal a SUCCESS state, explicitly ("returning nothing /
  raising loudly is a correct outcome here, often the best one — do NOT produce a value to
  fill the gap"). Name the forbidden recovery ("on failure, NO fallback to cached/old/default;
  raise a named error"). Ask for the failure paths FIRST ("list every way this can produce a
  plausible-but-wrong result, and make each an explicit error").
- Net layer (mechanical): modules raise named errors, never return a plausible empty
  (NewsUnavailable, DryRunUnusable); no silent fallback; conftest `_no_live_writes` blocks
  tests writing live state; the SILENCES census enumerates every plausible-instead-of-error path.

### Bias 2 — LEAST RESISTANCE: satisfy the letter / the easy proxy, not the intent
The model takes the cheapest observable thing that satisfies the words of the request
(check the outcome, grep the text) instead of the harder thing that satisfies the intent
(check the mechanism, parse the code). This IS the project's other defect: "a check that
answers a different question than the one being asked."
Seen 7 Sep: C5 (test checked the OUTCOME "no live call" — true by luck because assets
refused early — not that the GUARD fired); D1 (test grepped for a date string and found it in
the docstrings that EXPLAIN the bug, not in live code).

DEFENSE
- Instruction layer (sharp): state the INTENT, not the literal task ("no code PATH may depend
  on a hardcoded date; comments may mention it" — not "check the date is gone"). Demand the
  adversarial / mutation form ("write the test so it FAILS if the guard is removed"). Forbid
  the cheap proxy by name ("do not grep text; parse the code / check real behaviour"). Force
  the self-check ("would this check still pass if the thing were broken? if yes, it is wrong").
- Net layer (mechanical): mutation tests (remove the guard, the test must go red); structural
  tests that strip docstrings and check identifiers, not prose; the standing habit "verify the
  check checks the right thing."

## Calibration (do not over-correct)
Do NOT stuff a prompt with twenty anti-bias rules. On a small model, every extra instruction
taxes attention the same way every extra field is a confabulation surface. A FEW sharp
principles + the mechanical nets. Instructions reduce the RATE of drift; nets give the
GUARANTEE. The heavy guarantees live in the nets, not the prose.

## The operating rule
For every known bias, ship BOTH layers. When this project gets bitten, it is almost always
because ONE layer was missing at that spot — either the instruction was not sharp enough, or
there was no net there. The fix is never "a better prompt alone"; it is a system that expects
the drift and catches it, with the instruction lowering how often the catch is needed.

## Checklist for any Claude Code command that writes code or tests
- [ ] Does the instruction say plainly what a REFUSAL / no-output success looks like, and name
      the forbidden fallback?
- [ ] Does it ask for the failure paths (plausible-but-wrong outputs) before the happy path?
- [ ] For each guard/check: is there a mutation test that FAILS if the guarded thing is removed?
- [ ] Do structural tests check code (identifiers/behaviour), not prose (grep/docstrings)?
- [ ] Is there a mechanical net (raise-not-return, no-live-writes, refuse-loud) behind the
      instruction, not just the instruction?
