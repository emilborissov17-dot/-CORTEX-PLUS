# THE NEGATIVE CONTROL — THE BENCH IS INDICTED
### 5 September 2026, 02:33. Everything below the fold is the harness's own output, verbatim.

## VERDICT: IMPROVED on UNSEEN. Under the pre-registered rule, that indicts the bench.

```
sig01_plain   n=180   base 3.9541 -> adapter 2.7337   delta +1.2204
                      95% CI [+1.1117, +1.3285]       IMPROVED
```

**This adapter was trained on deranged data.** Every prompt was paired with another
record's target by a seeded permutation rotated by one, so no record kept its own target
(`unchanged_target_string: 0`, seed 20260904). It cannot have learned any problem→solution
mapping, because none was present. It nevertheless improves held-out NLL on **novel**
targets by 1.22 nats, with a confidence interval nowhere near zero.

**The criterion was fixed before the run and it is met: IMPROVED on UNSEEN indicts the
bench by itself.** No effect or worse would have passed. It did not.

### What is indicted is the METRIC, not the code

The harness measures exactly what it was asked to measure, correctly (28/28 tests below).
The problem is what that quantity means. Mean per-token NLL of the target, teacher-forced,
answers *"how probable is this text?"* — and a model lowers that on any corpus by learning
the **target distribution**: format, vocabulary, sentence shape, the house style of a
CORTEX proposal. A derangement destroys the mapping and **leaves that distribution
perfectly intact**, which is precisely why the control captures the whole gain.

So the measurement cannot separate:

- *"the adapter learned which solution follows which problem"* — the claim, from
- *"the adapter learned what a solution looks like around here"* — the artefact.

**Runs A and B would report IMPROVED under this metric and it would mean nothing.** They
are not worth running until the metric can tell the two apart. That is what a negative
control is for, and this is the first night it was ever run.

### Counts, as asked

```
held-out read : 246        skipped (empty or too long) : 0
SEEN (target verbatim in train)  : 30
UNSEEN (novel)                   : 216
```

The UNSEEN bucket is **216**, far above `MIN_HOLDOUT = 30`, so the headline is resolvable
and is not the corpus-size finding. Within it, only `sig01_plain` (n=180) is individually
gradeable; `sig02` (n=27) and `sig03` (n=9) are correctly refused as UNRESOLVABLE rather
than averaged in.

Note the SEEN/UNSEEN labels remain valid for a control: the derangement permutes pairings
but preserves the **set** of target strings, so a holdout target absent from `train.jsonl`
was equally absent from `shuffled_control.jsonl`. The control genuinely never saw these
216 strings.

## THE HARNESS ITSELF — 28/28, verified before the number was read as anything

`test/test_eval_harness.py`, run on CPU with no GPU and no network:

```
venv_train\Scripts\python.exe -m pytest test/test_eval_harness.py -q
28 passed, 1 warning in 9.16s
```

| # | area | result |
|---|---|---|
| 1 | `disable_adapter()` really disables — differs from adapted, **equals a separately built model holding the pristine state_dict**, and restores on exit | **PASS** (3 tests) |
| 2 | SEEN/UNSEEN: trailing whitespace → SEEN | **PASS** |
| 2 | SEEN/UNSEEN: a single full stop, or a capital letter → **UNSEEN** | **PASS as asserted — and this is a real weakness, see below** |
| 3 | `verdict_for`: constant positive → IMPROVED, constant negative → WORSE, symmetric noise → NO EFFECT | **PASS** |
| 3 | boundary exact: n=29 → `UNRESOLVABLE (n<30)` with CI `-`; n=30 → a verdict, same data | **PASS** |
| 3 | bootstrap is seed-deterministic | **PASS** |
| 4 | missing `record_kind` raises naming the file, the index, and the observed keys | **PASS** (3 tests) |
| 5 | empty/whitespace target never reaches `example_nll` — at both layers | **PASS** (5 tests) |
| 6 | exit 2 on all four refusals; 0 only when an UNSEEN stratum IMPROVED; 1 on NO EFFECT, WORSE and UNRESOLVABLE | **PASS** (7 tests) |
| 6 | **a pure memoriser cannot earn exit 0** — all gain in SEEN, UNSEEN reads NO DATA, exit 1 | **PASS** |

**Test 1 is also confirmed empirically by tonight's own numbers.** A leaking
`disable_adapter()` produces `base ≈ adapted`, i.e. a delta near zero. The observed delta is
+1.22. The adapter is genuinely being toggled; the gain is real and is not an artefact of
measuring one model against itself.

Two things about the tests that should not be skimmed:

- **`lora_B` is re-initialised non-zero on purpose.** peft zero-inits it, which makes a
  fresh adapter a mathematical identity — a test on default weights would pass whether or
  not `disable_adapter()` works and would prove nothing.
- **The file is INERT in the main suite.** `eval_adapter.py` imports torch at module level;
  `venv/` has numpy only, so the whole file SKIPS there and runs only under
  `venv_train/`. Recorded here because a test that silently does not run is worse than one
  that does not exist. `pytest` was installed into `venv_train` at 02:34 to run it — after
  the eval finished, so no package was written while a process from that venv was live.

### The one harness weakness the tests confirmed rather than cleared

`norm()` is `" ".join(text.split())` — whitespace only, no punctuation, no case folding. A
memorised training target differing by a single appended full stop is classified **UNSEEN**
and graded in the bucket that *is* the verdict. Tonight that does not change the reading —
the control never saw the correct pairings at all, so its gain is distributional either way
— but it must be fixed before any real run is graded, or memorisation leaks into the
headline through punctuation alone.

## WHAT THIS CHANGES

1. **Runs A and B do not run under this metric.** They would report IMPROVED for the same
   reason the control did.
2. The metric needs to isolate the mapping. The natural candidate, and it costs one more
   forward pass per example: score the correct target **against a mismatched target under
   the same adapter**, and take the difference. A style gain applies to both and cancels;
   only knowledge of the pairing survives. Not designed tonight, and it should be
   pre-registered before it is run, exactly as this one was.
3. `norm()` gets punctuation and case folding.
4. The control is the reference point from now on: any future run must beat **the control's
   UNSEEN delta**, not the base model's.

**Written before any of this was known, and it held:** *"NO EFFECT on UNSEEN with changed
weights means we changed weights and learned nothing. That is a real result and it closes
the day honestly."* The design was right to insist the criterion be fixed first. What the
night actually bought is better than a result — it is the discovery that the instrument
could not have produced one.

---

# The harness output, verbatim

# K1b eval - adapter vs base

## Adapter provenance
- corpus sha256: `2622e01a08972d62431152cfa8022b8bea779c8efaf05383e664a6e782470c6c`
- trained on: 1077 examples
- git commit: `94b14a1842a390274d2d7c1ac90420eeb1d032c0`
- hyperparams: `{"epochs": 1, "max_len": 256, "accum": 8, "lr": 0.0002, "rank": 8, "alpha": 16, "targets": "q_proj,k_proj,v_proj,o_proj", "compute_dtype": "torch.float16", "compute_capability": "7.5", "bf16_flag_reported": true, "bf16_hardware_real": false}`

Held-out read: 246  ·  skipped (empty or too long): 0
Targets already present verbatim in train: 30  ·  novel: 216

## UNSEEN targets - this is the verdict

| stratum | n | base NLL | adapter NLL | delta | 95% CI | verdict |
|---|---|---|---|---|---|---|
| sig01_plain | 180 | 3.9541 | 2.7337 | +1.2204 | [+1.1117, +1.3285] | IMPROVED |
| sig02_approved_with_impact | 27 | 2.1852 | 1.6265 | +0.5587 | - | UNRESOLVABLE (n<30) |
| sig03_experiment_authored | 9 | 2.9705 | 2.5867 | +0.3838 | - | UNRESOLVABLE (n<30) |

## SEEN targets - memorisation check, NOT a result

| stratum | n | base NLL | adapter NLL | delta | 95% CI | verdict |
|---|---|---|---|---|---|---|
| sig01_plain | 5 | 3.8993 | 2.7199 | +1.1794 | - | UNRESOLVABLE (n<30) |
| sig02_approved_with_impact | 11 | 2.2208 | 1.6284 | +0.5924 | - | UNRESOLVABLE (n<30) |
| sig03_experiment_authored | 1 | 3.0626 | 2.6581 | +0.4045 | - | UNRESOLVABLE (n<30) |
| sig04_moral_checked | 9 | 3.2109 | 2.2814 | +0.9295 | - | UNRESOLVABLE (n<30) |
| sig07_dependency_check | 4 | 2.7376 | 2.2476 | +0.4900 | - | UNRESOLVABLE (n<30) |

## How to read this
- Lower NLL means the model assigns more probability to what actually happened.
- Gains on SEEN with none on UNSEEN = memorisation of a repeated string.
  That is a finding about the corpus (43.76% duplicate targets), not a success.
- `NO EFFECT` on UNSEEN with changed weights means we changed weights and
  learned nothing. That is a real result and it closes the day honestly.
- `UNRESOLVABLE` is the corpus being too small to grade that bucket. Fix it by
  waiting for cycles, not by lowering the bar.
---

# TOMORROW'S TOP ITEM — ABOVE THE DECLARATIONS THEMSELVES
### Recorded 5 September 2026, 02:2x. NOT fixed tonight, deliberately.

## A missing stamp reads as a clean one

`core/notary.attest()` initialises inheritance at the top of the lattice and only ever
lowers it:

```python
inherited, from_who = FULL, None
for rel in inputs:
    s = stamps.get(rel)
    if s and s.get("level") is not None and s["level"] < inherited:
        inherited, from_who = s["level"], rel
```

`stamps` is built from the attestation log's `products` field, which comes from
`core/cycle_map.STEPS`. **If no step claims an artifact as a product, `stamps.get(rel)` is
`None`, the loop skips it, and `inherited` stays `FULL`.** An input whose provenance is
entirely unknown contributes the maximum possible confidence.

## It is the same defect that was fixed on the age dimension on 17 August

`_age_state([])` used to return `FULL, "the step reads no inputs"`. The 17 August change
(`core/notary.py:301-312`) replaced it with `UNKNOWN, "no declared inputs - provenance
unknown"`, under a comment that states the principle exactly:

> *"An empty list does not mean 'reads no inputs'; it means 'we do not know what it reads.'
> Absence of evidence was being scored as maximal evidence."*

That principle was applied to **age** and never to **inheritance**. The age dimension now
fails closed on ignorance; the inheritance dimension still fails open on it. One module, two
opposite answers to the same question, fourteen lines apart.

## Why it blocks Phase 1 rather than merely accompanying it

Declaring `hyperclaw_plan`'s inputs points it at `plans/plan-*.md`. **Nothing claims
`plans/` as a product** — `hyperclaw` (idx 15.6), which writes it, declares `products: []`.
So the declaration would:

- fix the **age** dimension (a real mtime replaces `UNKNOWN`), and
- leave inheritance at **`FULL`**, because the stamp it should inherit from does not exist.

The step would move from *honestly blind* to *confidently wrong*: a real age, an unearned
`inherited = FULL`, and a level that looks measured. **That is precisely the
"a wrong declaration makes a blind step look verified" failure**, arrived at by writing a
declaration that is itself entirely correct.

The same holds for `auto_levels` → `snapshots/master/master_snapshot_latest.json`, which
also has no registered producer (only the *phase* `D_SCORE` declares it), and for
`memory/self_awareness.json`, which nothing produces at all.

## The order tomorrow

1. **Decide the inheritance default for an unstamped input.** `UNKNOWN` matches the 17
   August principle; anything else needs an argument for why ignorance is safe here and was
   not safe there. This changes the gate's behaviour and must be measured before it runs
   unattended — it will lower levels across the cycle, not just for these two steps.
2. **Register products in `cycle_map.STEPS`** for `plans/`, the master snapshot, and
   whatever else the closure names. 20 of 71 steps declare no products today.
3. **Then** declare `hyperclaw_plan` and `auto_levels` inputs, and re-run the closure trace.
4. Then extend `test/test_verifier_inputs.py` to the named closure.

**Not tonight.** Changing the notary's default hours before an unattended run is the wrong
order — the same reason `self_modifier` was left refusing rather than unblocked at 01:15.
