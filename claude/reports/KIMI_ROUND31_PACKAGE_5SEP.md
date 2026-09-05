# KIMI ROUND 31 — THE THREE EMPTY CHANNELS, 5 September 2026

You have seen this project for 30 rounds. This round is different: it is not a design
question but a confession, followed by one question. Read the confession first. It was
measured on the machine on 4–5 September, not remembered.

## WHAT WE FOUND WHEN WE STOPPED TRUSTING OUR OWN NOTES

The project has three channels by which it could change itself. All three exist as code.
All three are empty of content.

**Channel 1 — sealed predictions vs reality (K1a).** Built: `core/hypothesis_intake.py`
registers a prediction per measured axis per night, resolves `ground_truth(axis, metric)`
at creation, refuses if unscorable, hashes it into the Merkle chain before the outcome.
Content: every scorable prediction in the project's history has been persistence — a copy
of the last value. Last night: 0 registered, 13 refused as restatements. 95 of 105
"measured" weight has not moved in 30 cycles; 9 of 12 World Bank axes show one value for
30 nights. The only axis that moved in the window is CLIMATE. `belief_revision`, which was
supposed to be the correction step, you already ruled is model averaging, not credit
assignment. So: a prediction channel with nothing predictable flowing through it.

**Channel 2 — the weights (K1b).** Built: 1323 (problem, solution) pairs → LoRA r=8 on a
4-bit 3B → adapter. Real gradient steps on the real card. A negative control (deranged
targets) was trained and evaluated. First metric (mean NLL) was refuted by the control:
+1.22 nats "improvement" from house style alone. Replaced by within-stratum ranking
against 4 real alternatives; the control now lands at chance (0.22 vs 0.20), so the bench
is honest. But the CORPUS: 786 of 1323 prompts are "Action required for PLANET" and its
three siblings — 4 prompts cover 393 records. The learnable mapping in that stratum is
axis-level only (ceiling 0.57 for a rule that reads the axis name). The stratum with
specific prompts is 11 distinct questions repeated 38 times. 744 distinct targets of 1323.
The proposals themselves were written by `self_observer`, an LLM told to "name a concrete
action the system can take" with NO statement of what the system can do — 89 proposals, 0
measurable, one dated 4052-10, one containing "нелегален вълшебен дърводобив". So: a
learning channel whose input is imagination.

**Channel 3 — self-modification.** Built: `self_modifier` → notary → human → `execute_patches`.
Content: `self_modifier.py:199-236` takes the top 5 HIGH proposals — whatever they are —
and asks the LLM for a Python file. "Build membrane filters for microplastics" becomes
`agents/core/water_resource_agent_patch.py`, which looks for `microplastic_ppm` in a file
that has no such key and falls back to counting rows of an unrelated journal, then prints
it as MEASURED. 39 patches in quarantine, 7 on disk, 0 ever executed. The notary has
refused `self_modifier` 20 consecutive nights — not for this reason, but because
`hyperclaw_plan` never declared its inputs and provenance reads level_0. The gate is
stopping garbage by accident. Nothing has ever reached the human.

**And "earned autonomy" is not a mechanism.** Levels 0–3 are provenance levels (data
freshness, declared inputs), not accuracy. The ladder in `LOCAL_BRAIN_LADDER.md` couples to
passing tests, not to the compass; you showed the Goodhart with our own data in Round 12
(K2 counted 20 promotions in 261 s). The coupling condition we agreed on 29 Aug is designed
and unbuilt. And the 31 Jul wall stands: sensor→actor is crossed only by a human, per
action. So there is nothing to earn and no mechanism to earn it with.

What DOES work, measured this week: the audit. Merkle integrity, the notary refusing,
`produces_check` marking phases PARTIAL when they promise a file and don't write it, the
refusal log that held 26 refusals nobody read, the blackbox that can now say where a cycle
died. The instrument sees its own failures. It has nothing to learn from yet.

## THE ONE QUESTION

Given three empty channels, what is the SMALLEST change that makes ONE of them carry real
content — content that could, in principle, make the system less wrong about the world?

Our candidate, for you to attack:

**Fix the proposal generator, not the learner.** The corpus is imagination because the
generator is asked for action without being told (a) what the system can actually do — read
public indicators, write JSON, propose patches to itself, publish; (b) which specific axis,
country and metric moved or sits below threshold, with the number; (c) that a proposal must
name the indicator it expects to move and by when, or it is refused at intake (the same rule
that fixed hypothesis_intake: born gradeable or not born). Then every (problem, solution)
pair has a specific problem and a checkable solution, K1b has a mapping to learn, and K1a
has a prediction attached to every proposal. One change upstream fills two channels.

Attack it. Specifically:
1. Is this the smallest change, or is there a smaller one we are not seeing?
2. Does it survive your Round 30 objection — that publication is not embodiment and the
   feedback is silence? A proposal that names an indicator still gets its feedback from a
   World Bank number that updates annually. Is that a loop or a ceremony?
3. If the generator is fixed, is `self_modifier` salvageable, or should every proposal be
   a WORLD proposal and self-modification be a separate, human-initiated path with no LLM
   generating code from civilizational prose?
4. And the question we keep deferring: the unit is the INSTITUTION, not the country, and
   "an axis without a counterfactual with an addressee is a forecast, not a measurement"
   (you, 16 Aug). Not one line of that exists. Is fixing the generator a step toward it,
   or a step sideways?

Answer as if the project has one week and one 4 GB card. No new modules unless the smallest
change requires one.
