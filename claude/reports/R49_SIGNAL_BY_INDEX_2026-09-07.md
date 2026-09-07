# R49 — the SIGNAL becomes an index

**PREDICTION ONLY (§VI).** Nothing here places, sizes or recommends a trade. Not run
live: this is for the next bet.

## The diagnosis, before any code

R48 shipped an exact-substring gate and it worked exactly as designed — live, it
admitted 1 of 8 candidates. The instinct was that the 3B model paraphrases. Replaying
the seven refusals says something more useful:

| # | what actually went wrong |
|---|---|
| 3 | **the quote was verbatim.** The model wrote `SIGNAL <sentence> LOGIC: <sentence>` with no pipe, so the SIGNAL field swallowed the LOGIC and never matched |
| 4, 5, 6 | spliced two *different* bullets into one sentence no document contains — "Following the first close in correction territory" welded onto "have usually fallen into…" from a separate bullet. 4 and 5 also spilled `LOGIC:` |
| 1, 2 | true paraphrase — dropped a prefix, changed `have gained` to `has gained` |
| 7 | reworded a photo caption |
| 0 | admitted |

**Five of seven were transcription accidents, not fabrications.** The gate was
measuring copying ability. Copying is the wrong task for this model, and the fix is to
remove the task rather than to relax the check.

## What changed

**Piece 1 — SIGNAL by index.** Snippets are split into numbered sentences; the model
returns a number. The SIGNAL text is the sentence at that number, verbatim *by
construction* — there is no copy step left to get wrong. On the real 7 Sep evidence,
two snippets become 26 numbered segments, of which `[7]` is what the one passing
candidate quoted and `[9]` is exactly what candidate 3 was reaching for.

The invariant everything rests on: **a segment is a contiguous slice of its source.**
Edge noise is stripped, nothing in the middle, no character rewritten. Tested.

One table is rendered into the prompt *and* handed to the gate. Building it twice would
let the prompt's `[4]` and the gate's `[4]` drift apart, which is the one way index
selection could quietly stop being verbatim. The table is sealed with the bet, because
`SIGNAL 7` means nothing a month from now without it.

**Piece 2 — normalise before comparing.** NFKC, then every dash and quote variant folded
to one form, then whitespace and case as before. Under R48 a curly apostrophe against a
straight one was a refusal reading "not an exact substring" — true of the bytes, false
of the sentence. The line: canonicalising a glyph is *spelling*; stemming, synonyms and
edit distance are *meaning*, and only the second turns "quoted the document" back into
"said something like it". A test holds that line from the other side.

**Piece 3 — one worked example**, and a test that lifts the example out of the prompt,
runs it through the real gate against the real segmentation of its own evidence block,
and requires `ADMITTED`. A worked example the gate would refuse teaches the model to
fail.

**Piece 4 — coherence LOGGED, not gated.** The R48 bet sealed `UP` while its signal said
a downturn is only a matter of time. The obvious fix — gate on direction matching the
rationale — is the wrong one: it teaches the model to write a rationale that matches the
direction it already picked. That is rationalisation, and it poisons the only artefact
this exercise exists to produce. So `{direction, signal_polarity, rationale}` is
recorded on every admitted candidate, sealed with the bet, appended to
`memory/first_bet/POLARITY_LEDGER.jsonl`, and a mismatch is **flagged and still
admitted**.

Two things make it hard to game: polarity is scored on the *selected span* — text this
module put there, not text the model wrote — and the ledger takes every admitted
candidate rather than only the sealed one.

Replaying the actual R48 sealed bet:

```
sealed direction : UP
signal polarity  : NEGATIVE   {positive: 0, negative: 1}   terms: downturn
FLAG             : DIRECTION_POLARITY_MISMATCH
```

## Unchanged

Hygiene blacklist, three date states, class-as-metadata, the sealed snapshot, majority
vote, momentum baseline.

## Two things a test caught that reasoning did not

`-1` had its minus silently dropped and was read as segment 1 — **admitted**. `1-3`
would have been read as 1 and 3 rather than the range meant. Both now refuse: deciding
what the model meant is the habit this gate exists to break.

I mapped `″` (DOUBLE PRIME) to a double quote in the glyph table. NFKC runs first and
decomposes it into two PRIMEs, so the entry never fired. Removed rather than left in
place reading as if it did something.

## Verification

- `test/test_market_bet.py`, `test/test_grounded_gate.py`, `test/test_market_news.py` —
  **87 passed**.
- `test_first_bet.py`, `test_gdelt_daily.py`, `test_usgs_quakes.py`,
  `test_orchestrator_grounded.py` — **73 passed**. These are every remaining file that
  imports the changed modules.
- The 22 `f41a7fd` fabrications are still refused, now a step *earlier*: they are free
  text, and free text is no longer a citation at all.
### The full suite — a correction

An earlier draft of this report said `test/` "hangs on pre-existing network-touching
tests." **That was wrong.** It does not hang; it takes about 29 minutes, and a 590-second
tool timeout was misread as a hang. Two independent full runs agree exactly:

```
35 failed, 4036 passed, 14 skipped, 6 xfailed, 1 error in 1713s (0:28:33)
35 failed, 4036 passed, 14 skipped, 6 xfailed          in 1727s (0:28:46)
```

**None of the 35 is caused by R49**, and the argument is causal rather than statistical.
The whole diff is three files — `tools/market_bet.py`, `test/test_grounded_gate.py` and
this report — so a test can only be affected if it reads one of them or scans the tree
they sit in. Both sets were enumerated and run:

| set | result |
|---|---|
| every file importing the changed modules (`test_grounded_gate`, `test_market_bet`, `test_market_news`, `test_first_bet`, `test_gdelt_daily`, `test_usgs_quakes`, `test_orchestrator_grounded`) | **160 passed** |
| every repo-scanning test that walks `tools/` (`test_compass_wired`, `test_launch_detached_encoding`, `test_resolve_ideas_*`, `test_seed_boundary`, `test_verifier_inputs`) | **70 passed, 1 failed** — `test_every_verifier_declares_what_it_reads`, on undeclared `core.notary.VERIFIERS` steps (`browser_scout`, `global_indicators`, …). Unrelated, and long-standing by its own error text. |
| `test_script_suite` (repo-wide style scan) | 21 passed, 5 failed — all on other people's files; **`tools/market_bet.py` and `test/test_grounded_gate.py` are not in its parametrisation at all** |

**Still UNVERIFIED:** the *identity* of every one of the 35. Both full runs truncated
their captured output to the last ten `FAILED` lines, and `-rf` prints only on
completion. The ten that were visible are all unrelated (`test_proposal_sla`,
`test_scanner_never_invents_a_score`, `test_script_suite`, `test_small_truths`,
`test_verifier_inputs`). To enumerate the rest:

```
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe -m pytest test/ -v --tb=no | grep FAILED
```

Two files in `test/` are scripts, not pytest modules: `test_grounding_locate.py` and
`test_origin_honesty.py` both call `sys.exit()` at import and break collection with
`INTERNALERROR` when named directly. Confirmed present on the commit before this work by
stashing. Run them as scripts instead.

## Dry run

Real 7 Sep evidence, staged completions exercising every path. Not live; the sealed
`BET_2026-09-07_markets_grounded.json` was not touched.

```
SPY  2 snippet(s), 26 numbered segment(s)  last 2026-09-04 770.19
  SEALED 0 ADMITTED  UP     seg [7]  polarity NEGATIVE  [FLAG direction<->polarity mismatch — ADMITTED anyway]
         1 ADMITTED  UP     seg [6]  polarity POSITIVE
         2 ADMITTED  DOWN   seg [9]  polarity NEGATIVE
         3 REFUSED   UP     — signal_index: segment [99] is out of range — offered 1..26
         4 REFUSED   UP     — signal_index: 'The S&P 500 has gained an average of 18%...' is prose
         5 REFUSED   UP     — signal_date: segment [13] — 'Nike leaves the S&P 100 on September 21...'
         6 ADMITTED  UP     seg [3, 10]  polarity NEUTRAL
         7 REFUSED   DOWN   — signal_index: '7 LOGIC: a downturn is coming' is prose
  -> majority direction UP (3 UP / 1 DOWN of 4 passing)   [DISAGREEMENT]
  [POLARITY] 4 row(s), 1 flagged (dry run — ledger not written)

UUP  REFUSED_NO_EVIDENCE — no snippets staged
```

Candidate 4 is the live R48 paraphrase replayed verbatim; candidate 7 is the live format
spill. Candidate 5 is a **genuine** sentence from a **real** document — being truly
printed does not make a future event a driver of the last session, so it still refuses.

The sealed citation re-verifies offline against the sealed snapshot, without the
network:

```
segment_indices : [7]
segment_text    : 'But the next stock market downturn is only a matter of time.'
host / class    : fool.com / adversarial   dated True
substring of the sealed snapshot -> True
```

## Observed, not fixed

`parse_completion` splits the RATIONALE on `|` only. When the model omits the pipe and
writes `SIGNAL 7 LOGIC: …`, the LOGIC is lost and the candidate refuses on
`signal_index`. Under R48 this destroyed a genuinely verbatim quote (candidate 3).
Index selection makes it much less likely — there is no long sentence to lose the pipe
after — and the worked example now shows the pipe. Teaching the parser to also split on
a bare `LOGIC:` marker would recover it, but that is a parser change outside R49's four
pieces. Flagged for a decision rather than done.
