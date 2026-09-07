# FIRST BET — MARKETS, 2026-09-07
### Sealed, NOT graded. **PREDICTION ONLY — no trade was placed, sized or recommended (§VI).**

## The bets

```
asset  sealed  baseline   last close (2026-09-04)   graded session   sha256
SPY    UP      DOWN       770.19                    2026-09-08       5582d717b4f7c9a1…
GLD    UP      UP         406.77                    2026-09-08       f9194264a006733f…
UUP    UP      UP          28.08                    2026-09-08       ee8068684cda7767…
```

`memory/first_bet/BET_2026-09-07_markets.json` · model **`qwen2.5:3b` pinned** ·
8 completions per asset · T = 0.7 · 22 of 24 passed the gate.

**Baseline sealed before any bet** (`BASELINE_2026-09-07_markets.json`): 20-trading-day
momentum sign — SPY DOWN, GLD UP, UUP UP.

**Today is Labor Day**, so there is no 2026-09-07 close. The reference is Friday
2026-09-04 and the graded session is Tuesday 2026-09-08. The ledger also carries a
`grading_rule`: grade against the **first bar strictly after 2026-09-04**, whatever date
it carries, so a wrong holiday guess cannot corrupt the grade.

---

# THE RESULT IS A FINDING ABOUT THE METHOD, NOT A FORECAST

## 1. All 24 completions said UP

```
ALL 24 directions: {'UP': 24}
```

Zero variance. **"Majority direction" is meaningless when there is no minority**, and
best-of-N over a constant is not a selection — it is the same answer eight times. The
prompt fix worked exactly as specified (one prompt, one pinned model, N sampled draws)
and what it revealed is that **this model has no directional variance on this task at
T = 0.7**. The mechanism is now honest enough to show that.

A constant "UP" predictor also cannot beat persistence for a *reason*. It will be right
on whichever assets rose and wrong on the rest, and the pre-registered criterion — 2 of
3 correct on two consecutive nights — could be met by luck with no forecasting at all.

## 2. The SIGNALs are fabricated, and my gate let them through

The model was given **prices only**. It has no news access. Every "external fact" it
cited is invented. Three classes, all mechanically checkable:

**A signal dated AFTER the session it is supposed to explain:**
```
[UUP] Fed releases September Jackson Hole Symposium transcript, Sept 21
```
Sept 21 is thirteen days after the graded session. It cannot have driven it.

**Earnings cited as the driver for gold and the dollar index** — five of them:
```
[GLD] Q4 Earnings Preview Positive Outlook, Wall Street Journal 5 Sep
[GLD] Q4 earnings consensus upgrade, Bloomberg 5 Sep
[UUP] Q4 Earnings Preview Positive Outlook, Bloomberg 7 Sep
```
Corporate earnings do not price a gold ETF or a dollar-index fund. The **sealed GLD and
UUP rationales are both of this kind** — the two bets that agree with their baseline are
justified by something irrelevant to the asset.

**A release that does not happen in September:**
```
[SPY] Q1 GDP beat expectations, US Bureau of Economic Analysis 7 Sep
[SPY] Q1 GDP report release, White House, 07 Sep
```
BEA publishes Q1 GDP in spring, on a fixed schedule.

**This is not a surprise and it is not an excuse.** I wrote the signal check to require
"a date or a named source", tested that *a fabricated but well-shaped signal still
passes*, and said so in the docstring: *"it filters interpretation dressed as evidence,
not lies."* That test now reads as a prediction that came true within the hour.
**A shape check cannot do the job the rationale was added for.** The rationale exists so
a wrong bet can be diagnosed against a named event; a fabricated event is not
diagnosable, it is only decorated.

## 3. What the gate did catch

2 of 24 refused, both on the signal rule:
```
[SPY] 'VIX ends week lower, last @ 17.34 - CME'          -> interpretation, no date
[SPY] 'Q4 earnings season begins, market liquidity tightens' -> interpretation, no date
```
Ironically the two refused signals are **more plausible** than several that passed. The
check rewards *format*, and the model learned the format immediately.

---

## Scoring the pre-registration

> "2 consecutive nights, 2 of 3 assets correct, with a repeating DRIVER+SIGNAL naming an
> external fact."

**The second half already fails, before grading.** No SIGNAL here names a real external
fact. Whatever tomorrow's directions do, **this run cannot satisfy the criterion**, and
recording that now — rather than after seeing whether 2 of 3 came out right — is the
whole point of a pre-registration.

**My expectation for the direction half, on record:** SPY, GLD and UUP rising together
on the same session is not the common case — equities and the dollar often move against
each other, and gold against the dollar more so. A blanket UP across all three is
therefore unlikely to score 3/3. **P(2 of 3 correct) ≈ 0.4**; P(3 of 3) ≈ 0.15.

## What would make the next one mean something

Three changes, none of them a tuning knob:

1. **Give the model real news, or drop the SIGNAL requirement.** A rationale citing
   events the model cannot see will always be fiction. Either a headline feed goes into
   the prompt, or the rationale should be limited to what it *can* see — the price
   history — and be honest that it is technical, not fundamental.
2. **Reject signals dated after the graded session.** That is mechanically checkable
   and would have caught the Jackson Hole entry.
3. **Require directional variance before sealing.** If all N agree, best-of-N selected
   nothing; that should be recorded as `NO_DISAGREEMENT` rather than dressed as a
   majority.

## Not graded

The 2026-09-08 session has not happened. Nothing here is an outcome.

**One gap in this run's provenance:** bypassing `brain.think()` to fix best-of-N also
bypassed `memory/llm_provenance.jsonl`, so there is no independent log of the 24 calls.
The one-prompt property is asserted by test, not by evidence from this run. The prompt
hash should be written into the ledger next time.
