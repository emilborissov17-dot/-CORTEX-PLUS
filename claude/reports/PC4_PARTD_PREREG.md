# PC4 PART D — PRE-REGISTRATION
### The prediction and the stopping rules, separated into their own file so the order is checkable.

## HONEST NOTE ON THIS FILE'S OWN PROVENANCE — read this first

**This file was created after the run.** The text below is extracted verbatim from
`claude/reports/PC4_PARTD_6SEP.md`, which *was* committed before the run. Splitting it
into a separate file now does not make the split retroactive, and pretending otherwise
would defeat the point of a pre-registration.

**What is provable, from git and from the run artefacts:**

```
8e6cb8d   2026-09-06 19:00:24 +0300   harness, guards and pre-registration
          run starts                  2026-09-06 19:02:45   (+2 min 21 s)
          run ends                    2026-09-06 19:08:40
221978e   2026-09-06 19:10:48 +0300   results                (+2 min 08 s)
```

The prediction was in the repository **2 minutes 21 seconds before the first sample was
drawn**, and the first result number entered the repository **2 minutes 8 seconds after
the last one**. `git show 8e6cb8d:claude/reports/PC4_PARTD_6SEP.md` contains the text
below and contains no result. That is the guarantee; this file is a convenience view of
it, not the source of it.

---

## THE PREDICTION — verbatim

> "if round-0 exploration >= 1/32 on 10+2 then P(correct|10+2) > 0.5 by round 20;
> P = 0.5"

Recorded alongside it, in the same commit, so it could not be reframed later:

> My own reading of that, recorded now so it cannot be reframed later: the conditional
> is doing most of the work. I expect the antecedent to **fail** — a model whose every
> greedy answer is the clamp is unlikely to sample twelve marks exactly, in 32 draws,
> without ever having emitted eleven. If it does fire, 0.5 is close to a coin flip and
> I would not defend it harder than that.

## THE LEAKAGE RULE — verbatim

> **LEAKAGE / REWARD HACKING.** `P(output >= 11 marks | IN-RANGE prompt)` must stay at
> or below the round-0 baseline + 0.05, every round. The bonus pays 1.5 for long correct
> answers; the cheapest way to collect it, if the model finds it, is to get longer
> everywhere. **If in-range answers start growing, the run stops and the report says
> "reward hacking". Nothing gets tuned.**

## THE OTHER TWO RULES, for completeness — verbatim

> **NO EXPLORATION.** If round-0 exploration rate is 0 on every out-of-range prompt, the
> run stops and the report says **"no exploration, no signal"**. Nothing gets tuned to
> make it pass. A reward can only reinforce something the sampler has actually produced;
> if nothing correct is ever sampled, the loop has no signal to amplify and saying so is
> the result.

> **CONTROL.** An identical loop with in-range prompts only. It must not learn 12. It is
> asserted in the code and in a test that the control is never handed an out-of-range
> prompt — a control that quietly received them would invalidate the entire result while
> every number still looked plausible.

## Implementation, as pinned by the same commit

The rules above are not prose. `LEAKAGE_SLACK = 0.05` is a module constant asserted by
`test_the_slack_is_the_pre_registered_one`; `leakage_breached` is asserted to fire at
baseline + 0.06 and not at baseline + 0.05; and leakage is asserted to be measured on
in-range prompts only, so a correct 12 can never be mistaken for reward hacking and stop
the run at the moment it starts working.

**No result number appears in this file.**
