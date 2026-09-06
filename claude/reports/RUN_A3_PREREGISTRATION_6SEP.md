# RUN A3 — pre-registration, written BEFORE launch
### 6 September 2026, 13:0x. Nothing had been trained when this was written.

## The prediction, on record

**A3 UNSEEN sig01 → AT CHANCE, accuracy 0.19–0.27, P(above base with a clean CI) = 0.20.**

A corpus with **44% duplicate targets** does not become lessons at three epochs.
PC3 showed the RECIPE can learn a rule — a synthetic 12-way mapping, adapter
0.3333 CI [0.2500, 0.4167] against base 0.1417 AT CHANCE. It did **not** show that
this CORPUS holds one. A3 is the test of the second claim.

If A3 lands above base with an interval clear of it, this prediction was wrong and
the corpus is richer than its duplicate rate suggested. That is a good outcome and
a measured one; it is written here so it cannot be reframed afterwards.

## What A3 is

The Run A recipe, with **one** thing changed:

```
rank 8 · targets q_proj,k_proj,v_proj,o_proj · max-len 256 · 1077 rows
corpus sha256 079a9d1472511aa790e94320067f3ae3890c5c53a3170596c00eb16b2ec6259e
epochs: 1  ->  3
```

That sha is **byte-identical to the one Run A recorded** (`K1B_TRAIN_A.md:7`), so a
difference in outcome has one candidate cause. The launcher checks it and says so
if it ever stops matching.

**The confound this closes**, named 4 Sep: Run A at one epoch landed AT CHANCE, and
that single number cannot separate *"this corpus has no learnable mapping"* from
*"one epoch was not enough to fit it"*. Both produce the same reading. Kimi R34's
rule — no archive run below 3 epochs — is the same point from the other side.

## A correction made before launch, not after

The first draft of the launcher checked the corpus against
`2622e01a08972d62431152cfa8022b8bea779c8efaf05383e664a6e782470c6c`. That is the
**control's deranged corpus**, not Run A's. It would have printed "not
like-for-like" about a corpus that is in fact unchanged, and the report would have
carried a caveat that was false. Corrected to Run A's own recorded sha.

## The control is re-scored FIRST, in the same chain

`--control-items` was asked for so `LEARNED` would not read UNKNOWN again. The file
does not exist: the V2 control run (10:01–10:59 today) **predates the per-item
output**, which was added at ~10:55. So the chain is:

```
1. re-score the deranged control  -> K1B_CONTROL_RANK_V3.md + .items.json   ~55 min
2. train A3, 3 epochs                                                       ~6 h
3. eval A3 --control-items <the file from step 1>                           ~55 min
```

Step 1 must precede step 3 because step 3 reads its output. Total ≈ 7.7 h from
~13:05, finishing ≈ 20:50 — well clear of the 03:04 cycle.

## How the result will be read

| label | condition |
|---|---|
| `LEARNED` | A3's CI entirely above the CONTROL's, on the same items |
| `BEYOND_TRIVIAL` | A3's CI entirely above the AXIS RULE's (0.7778, CI [0.7174, 0.8356]) |

Both are reported separately and are never merged. On sig01 the axis rule is very
strong, so `BEYOND_TRIVIAL` is the demanding label and `LEARNED` the weaker one.
Only `sig01_plain` (n=180, 157 distinct pairs) can carry a verdict; sig02 UNSEEN is
27 rows from **3** distinct pairs and will read UNRESOLVABLE, which is the corpus,
not the metric.
