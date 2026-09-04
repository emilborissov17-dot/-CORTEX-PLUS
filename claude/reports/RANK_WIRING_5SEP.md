# GPU WIRING FOR THE RANKING METRIC — code and tests, nothing run
### 5 September 2026, 02:58. GPU at 0 MiB. The 03:04 cycle has the card.

`training/rank_runner.py` + `test/test_rank_runner.py`. **21 passed**, on CPU with a
1-layer GPT-2 built from config — no download, no network, no card.

## THE FOUR FAILURE MODES, NAMED BEFORE THE CODE

### 1. Masking drift — the ranking and the NLL secondary must measure one thing

`make_nll_fn` does not reimplement the masking. It **calls `example_nll`**, so the two
cannot drift apart by construction. The test asserts it anyway, over three prompt/target
shapes, because "by construction" is what people say just before two constructions
diverge. Two more tests check that changing the prompt changes the score (the prompt is
actually reaching the computation) and that a 40× longer prompt does not move the number
by an order of magnitude (prompt tokens have not leaked into the per-token denominator).

### 2. Candidate batching — and a trap that would have looked plausible

Ten candidates share a prompt, so batching is the obvious win and the obvious padding bug.
Two specific traps, both handled:

- **`out.loss` is a batch mean.** HF averages over every unmasked label in the whole batch,
  so reading it per-candidate would give ten identical numbers dominated by the long
  candidates — and ranking ten identical numbers ranks by nothing. `_per_sequence_nll`
  computes from logits per sequence instead, and a test asserts the ten values are not all
  equal.
- **Right padding, with an attention mask.** Real tokens stay at positions 0..n-1, matching
  the unbatched case; left padding would not.

Tests: batched equals unbatched **per candidate** across ten candidates of deliberately
different lengths; the longest (unpadded) row checked separately, since that is the one a
padding bug spares; and reversing the candidate order must not move any score, because a
position bug shows up as order dependence.

**`DEFAULT_BATCH = 1` — unbatched — and there is a test asserting that.** These tests prove
the arithmetic on a CPU stub; only the quantised 3B can prove the kernels. The default is
raised **after** the equality test passes on the real model, not before. If it fails there,
we do not batch and the run costs what it costs.

### 3. Unpaired candidates — frozen before either pass

`rank_metric` already seeds from sha256 of `(prompt, target)` alone. The wiring could still
reorder or redraw between the base and adapter passes, so `build_items()` constructs every
candidate set **once**, before either pass, and both consume the same list. Tested as
object identity, not just equality — and separately that rebuilding from scratch (a resume,
a second process) reproduces the identical draw.

### 4. OOM — falls back to unbatched, never to a shorter sequence

On `torch.cuda.OutOfMemoryError` the runner empties the cache and scores that item
unbatched, recording `how="oom_fallback"`. Three tests: the fallback fires and says so; it
returns **the same numbers** as the batched path (otherwise results would depend on whether
memory happened to be free — irreproducible by construction); and a structural test that
the OOM path contains no `[:max_len]`, `truncation=True` or `max_length=`. Truncating to
survive would change what is being scored and do it silently, which is the defect class
this whole night has been about.

## THE TEST THAT FAILED, AND WHY IT MATTERED

`test_an_empty_candidate_is_refused_by_the_batcher` — **DID NOT RAISE**.

The cause was in my stub, not the code path: `Tok.__call__` ended in `or [1]`, so `""`
tokenised to one token instead of none, and the batcher's guard was never reached. **A stub
kinder than reality tests nothing.** Fixed both ways — the stub now returns `[]` for `""`
as a real tokenizer does, and the batcher additionally refuses blank text outright, before
tokenising, so the guard does not depend on tokenizer behaviour at all.

## THE ESTIMATE — from a measured rate, not a guess

**The measurement:** tonight's NLL eval did 246 examples × 2 passes = **492 forwards** in
**771 s** wall (launch 02:20:3x → report written 02:33:21), *including* model load and
4-bit quantisation. Load time was not separately instrumented, so the rate is given as a
band rather than a point:

| assumed load | s/forward | 4920 forwards |
|---|---|---|
| 0 s (upper bound on rate) | 1.567 | **128 min** |
| 60 s | 1.445 | **118 min** |
| 120 s | 1.323 | **108 min** |

**Forward passes for the new metric: 4920** = 246 items × 10 candidates × 2 passes
(UNSEEN 216 → 4320, SEEN 30 → 600). Computed by `rank_runner.forward_passes()`, which is a
function precisely so the number in this report and the work actually done cannot drift.

**Expected wall time, unbatched: 1h50m – 2h10m**, most likely ~2 h.

Batching all ten candidates would cut it to 492 batched forwards. That is **not** a 10×
saving — each forward carries ~10× the tokens — and the real gain on a 4 GB card is
unknown. It will be **measured, not assumed**: a short probe on a handful of items, timing
and peak memory both ways, before committing.

## THE ORDER, AFTER THE CYCLE RELEASES THE CARD

1. Probe: peak memory + per-item time, batched vs unbatched, on the real model. Verify the
   equality test at batch 10. This is the "measure peak before committing" step.
2. Score the **control** adapter under the ranking metric. Nothing else runs until that
   number exists.

## PRE-REGISTERED, UNCHANGED

- **The control must land AT CHANCE — 0.10, with the CI containing it.** Above chance means
  the new metric is contaminated too, and A and B stay unrun.
- A or B may claim learning only with a CI entirely above 0.10 **and** entirely above the
  control's on the same examples.
- NLL stays in the report as a secondary, labelled *distributional gain, not mapping*.

**Stated in advance so it cannot be read as an excuse afterwards:** only `sig01_plain`
(n=180 UNSEEN) can carry a verdict. `sig02` at 27 and `sig03` at 9 will read UNRESOLVABLE,
and every SEEN stratum (5, 11, 1, 9, 4) will too. **That is the corpus, not the metric** —
`MIN_BUCKET = 30` was fixed before any of these numbers existed.
