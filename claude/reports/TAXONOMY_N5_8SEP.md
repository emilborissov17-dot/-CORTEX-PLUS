# The taxonomy, live, N=5 — 8 September 2026

Real local model (`core.groq_backend._call_local`, temperature 0.4, fixed in
production). No mocks. The problem is the 2026-09-06 journal record, built from
the file rather than retyped:

> ESCALATION: LLM връща невалиден JSON 3 пъти поредно. Проверете модела/prompt формата.

Harness: `experiments/self_improve/taxonomy_n5.py -n 5`. Read-only.

## What was being tested

The bar the brief set is **not** identical answers — at temperature 0.4 that was
never available. The bar is that the answer lands in the right PLACE every time:
domain `internal`, categories plausible, and never an absurd world axis.

## Result — the classification: MET, 5/5

| run | domain | categories | spec verdict |
|---|---|---|---|
| 1 | internal | instrumentation, performance | REFUSED `SPEC_METRIC_UNGROUNDED` |
| 2 | internal | instrumentation, safety | REFUSED `SPEC_METRIC_UNGROUNDED` |
| 3 | internal | instrumentation, reliability | REFUSED `REFUSED_PATH_NOT_FOUND` |
| 4 | internal | instrumentation, reliability | REFUSED `SPEC_METRIC_UNGROUNDED` |
| 5 | internal | correctness, instrumentation | REFUSED `SPEC_METRIC_UNGROUNDED` |

- `internal` on **5 of 5** runs.
- Every category from `config/internal_axes.json`: correctness, instrumentation,
  performance, reliability, safety.
- **World axes among them: NONE.** No DEEP_TIME_RISKS, no TECHNOLOGY_AI, no
  TECHNOLOGY_INFRA, no GOAL_PROGRESS.
- reliability and correctness both appear.

### Against the baseline this replaced

The same problem, before the taxonomy, over five runs:

| | before | after |
|---|---|---|
| answer space | one `goal_axis`, 24 world axes | domain + categories |
| distinct answers | 4 (TECHNOLOGY_AI, TECHNOLOGY_INFRA, DEEP_TIME_RISKS, GOAL_PROGRESS) | 1 domain, 5 categories drawn from it |
| absurd answers | 4 of 5 | 0 of 5 |
| honest answer available | none — every option was a world axis | internal + reliability/correctness |

The old wandering was not the model being unreliable. It was the model being
asked a question whose answer space did not contain the truth.

## Result — the whole spec: REFUSED, 5/5, on other fields

Every run classified correctly and every run was then refused by a **different**
net:

- `SPEC_METRIC_UNGROUNDED` ×4 — "Number of times the LLM returns valid JSON",
  "Number of valid JSON outputs in the last 7 days". Real quantities; no file in
  this repo to recompute them from.
- `REFUSED_PATH_NOT_FOUND` ×1 — `memory/last_llm_output.json`,
  `memory/_llm_parsing_history.json`. Plausible names, neither exists.

Reported as its own result rather than folded into the headline: the taxonomy
question and the metric question fail for unrelated reasons, and conflating them
would let one read as the other.

## The next blocker, named

**Internal problems have no groundable metric.** `SPEC_METRIC_UNGROUNDED` (built
8 Sep) demands a metric recomputable from a real data file, because
`core/earning.py` recomputes from JSON only. That is right for an EXTERNAL spec —
a world measurement lands in a file. It is structurally wrong for an INTERNAL
one: nothing in this repo records how often an LLM reply failed to parse, so the
honest metric for a parser fix ("this test fails before and passes after") cannot
be expressed, and the model's attempts to invent a file are correctly refused
every time.

So an internal spec can now be classified but cannot yet be completed. The metric
net needs the same treatment the axis field just got — an answer space that
matches the question, probably a named test rather than a JSON row count.

## Caveat, observed

An earlier batch of five on the same prompt omitted `allowed_paths` from the JSON
in 5 of 5 answers (refused as a missing field); the two batches above included it
in 10 of 10. Same prompt, same model, same settings. The field is emitted last in
the template, and whether the model reaches it varies between batches. Worth
knowing before reading any single batch as the model's settled behaviour.

## Commits

| | |
|---|---|
| COMMIT 1 — the taxonomy | `66e027a` |
| COMMIT 2 — the net | `fe45488` |
| COMMIT 3 — this measurement | see git log for this file |

---

# Addendum — rule 0, and the second N=5

`build_prompt` gained a rule, numbered **0** so it is the first thing the model
reads:

> 0. ALL SEVEN fields below are REQUIRED and must be FILLED IN. A missing field,
> an empty string, or a copied placeholder is REFUSED before quality is ever
> judged. If you must infer root_cause from the problem, infer it — do not omit it.

The rule promised three things the validator did not do: the presence check was
`field not in spec`, so `""` and `"   "` passed, and so did the template's own
`<angle bracket>` placeholders. An instruction the net does not keep is worse
than no instruction — it teaches a reader that something is checked when it is
not. `REFUSED_FIELD_UNFILLED` now keeps it, and it fires **before** the quality
nets, exactly as the rule says: telling a model its metric is ungrounded when it
never wrote one sends it to fix the wrong thing.

## Second N=5, same problem, same model

| run | domain | categories | spec verdict |
|---|---|---|---|
| 1 | internal | instrumentation, performance | REFUSED `REFUSED_PATH_NOT_FOUND` |
| 2 | internal | instrumentation, reliability | REFUSED `REFUSED_PATH_NOT_FOUND` |
| 3 | internal | instrumentation, reliability | REFUSED `REFUSED_PATH_NOT_FOUND` |
| 4 | internal | reliability, instrumentation | **ACCEPTED** |
| 5 | internal | reliability, instrumentation | REFUSED `REFUSED_PATH_NOT_FOUND` |

**The taxonomy holds again: internal 5/5, no world axis, reliability present.**
That is now two independent batches of five, ten runs, ten internal.

**Rule 0 moved a real number.** `SPEC_METRIC_UNGROUNDED` went from 4 of 5 to
**0 of 5**, and no run omitted a field. The metric is now filled in and names a
real file every time.

## Run 4 is a FALSE PASS, and that is the finding

It was accepted, and it should not have been:

```
success_metric : "Count the number of valid JSON outputs in
                  memory/_sdg_resolved.json within a specified time window"
allowed_paths  : ["memory/_sdg_resolved.json"]
```

`memory/_sdg_resolved.json` is real — an SDG resolution cache, 3.7 KB, last
written 3 August. It has nothing whatever to do with an LLM returning invalid
JSON, and it is a **data file in production `memory/`**, not code to patch.

The mechanism is visible in the prompt. For `self_observer` it offers exactly
**one** candidate code path and **twelve** real data files "you may measure". The
model needed a path that exists, took one it had been shown, and both nets waved
it through: `REFUSED_PATH_NOT_FOUND` only asks "does this exist",
`SPEC_METRIC_UNGROUNDED` only asks "does the metric name a real file". Neither
asks whether the file is the kind of thing being described.

That is the least-resistance bias with a name on it: the letter of both nets
satisfied, the intent of neither. Rule 0 did not cause it — it made it visible by
getting far enough down the spec to reach it.

**Contained downstream, not by luck.** `merits.PINNED` refuses anything under
`memory/`, so this spec could never have been graded, let alone committed to a
fork branch. Two nets failing in the same direction is the design working. But
the requirer should not be handing the implementer a production data file and
calling it a pass.

## The two next fixes, in order

1. **`allowed_paths` must be CODE the spec could plausibly change** — inside the
   candidate paths the prompt actually offered, and never under a PINNED tree.
   One check, and run 4 becomes a refusal instead of a false pass.
2. **Internal problems still have no honest metric** (unchanged from above). The
   model now names a real file every time because it is shown twelve of them; not
   one of them records whether an LLM reply parsed. A metric that is grounded in
   the wrong file is not more honest than one grounded in nothing — it is less,
   because it passes.
