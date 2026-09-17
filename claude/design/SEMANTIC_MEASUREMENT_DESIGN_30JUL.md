# Measuring concepts, not just numbers — the semantic layer

_Copied into the repo on 17 Sep 2026 from the Claude project (claude/SEMANTIC_MEASUREMENT_DESIGN_30JUL.md),
because agents/…/semantic_scout.py cites it and the citation was the only trace of it in the repo._

Emil, 30 Jul 2026: "What number will you put on dignity, social justice... good and evil,
authoritarianism and democracy? These are all CONCEPTS." Correct, and it corrects a real
over-fixation on scalars. A number on dignity is not just insufficient — it distorts.

Restated by Emil on 17 Sep 2026: NOTHING IS DROPPED. Criteria decide how a statement is
CHECKED, never whether it is KEPT. The purpose of gathering from the world is UNDERSTANDING —
how things work, who does what and why, what has been tried and with what result — not
filling score cells.

## Principle
Two complementary indicator kinds per axis:
- QUANTITATIVE — for the countable (conflicts, deaths, prices, rates, indices). Scalars.
- SEMANTIC — for the conceptual (dignity, justice, democratic health, authoritarian drift).
  NOT a scalar. A structured, evidence-grounded, multi-perspective assessment that PRESERVES
  meaning and is tracked over time as a semantic trajectory.

The LLM's real strength is reading and comprehending meaning, not counting. So concepts are
measured by grounded qualitative assessment, and numbers by deterministic extraction — each
tool to what it is actually good at.

## Semantic indicator record
{
  "concept": "e.g. democratic health / authoritarian drift on axis X",
  "assessment": "<grounded qualitative judgment, a few sentences>",
  "direction": "improving | stable | deteriorating",
  "key_evidence": [{"claim": "...", "source_url": "...", "quote": "<verbatim from source>"}],
  "strongest_counterview": "<the best opposing interpretation — MANDATORY>",
  "what_would_change_it": "...",
  "confidence": "low|medium|high",
  "contested": true|false,
  "note": "assessment, not verdict; human + moral-core supervised"
}
Tracked over time -> a semantic trajectory (is dignity being upheld more or less?), not a point.

## Hard guards (because these concepts are value-laden and contested)
1. NO verdict on good/evil or a single ideological truth. The system ASSESSES; the human and the
   moral core supervise. This is the project's core: verification over assertion, human dignity,
   human-supervised, earned bounded autonomy.
2. Evidence-grounded: every claim carries a VERBATIM quote that must appear in the cited source
   (anti-fabrication — the semantic analogue of the numeric "digits must be in the page text"
   guard). A claim with no locatable quote is refused, loudly. (17 Sep: the STATEMENT it came
   from is still kept — only the unsupported claim about it is refused.)
3. Multi-perspective by construction: the strongest counterview is MANDATORY, never optional.
   For contested political concepts the record foregrounds the contest rather than resolving it.
4. Moral gate applies: the same calibrated local judge that guards proposals guards semantic
   assessments against coercion/domination/dehumanising framings.

## Relation to existing pieces
- V-Dem already quantifies democracy via expert-coded judgments — the semantic layer complements
  it with a live, evidence-cited narrative assessment + trajectory, not another index.
- The autonomous_scout (numeric: decide->search->extract, grounded-in-text) gets a twin:
  semantic_scout (decide the concept -> read multiple sources -> assess with evidence + counterview).
- Both feed the same human-approval + grounding-ledger discipline. Neither acts on the world.

## Build status
30 Jul: autonomous_scout (numeric) built + guarded; semantic_scout was "the next build".
17 Sep: semantic_scout.py is dormant (untouched since 30 Jul). Its role is taken over by the
statements layer (core/statements.py): every sentence kept, typed, and routed to its own lane of
verification; the concept_value lane produces the record above.
