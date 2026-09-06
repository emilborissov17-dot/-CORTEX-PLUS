# GATE LOOP — what the gate does, as of 6 September 2026
### Written to be read AGAINST the 03:04 cycle. Every refusal string below is the literal string the code emits.

## What changed today

Before this morning the gate checked three fields — indicator, expected_delta,
deadline — and a single global 365-day cap on how far a deadline could reach. It now
does seven things, and the four new ones exist because the old gate admitted
predictions that could never be settled.

| | what it refuses | where |
|---|---|---|
| 1 | contract | a proposal naming an axis the machine cannot measure | `core/gate_contract.py` |
| 2 | cadence | a deadline before the next possible observation | `core/cadence.py` |
| 3 | overdue | a deadline on a series whose next publication date is unknown | `core/cadence.py` |
| 4 | horizon | a deadline beyond what that cadence supports | `core/cadence.py` |
| 5 | scale | a delta larger than the series has ever moved | `core/proposal_intake.py` |
| 6 | units | — (it does not refuse; it puts units and direction IN the prompt) | `core/gate_contract.py` |
| 7 | refusals in prompt | — (last night's refusals are shown to tonight's generator) | `core/gate_contract.py` |

## 1. The contract, as the generator will see it tonight

`core/gate_contract.contract_block()` renders **6,269 characters**. It opens with what
the machine can and cannot do, so a proposal to "fund", "deploy" or "contact" is
refused by the generator's own reading rather than by the gate:

```
CORTEX++ CAN: read public indicators (World Bank, NOAA, USGS, WHO, UNHCR, ACLED,
arXiv, GitHub) once a night; write JSON snapshots and scores; register a prediction
about an indicator and grade it later; publish a Markdown/JSON report to GitHub;
propose a patch to its own code for a HUMAN to review.
CORTEX++ CANNOT: send email, run surveys, fund, build, deploy, contact anyone, or
change anything in the world without a human acting on its output.
```

## 2. Units, meaning and direction — item 6, in the prompt rather than in a refusal

Every gradeable indicator now carries its unit, a five-word meaning, and which way is
good:

```
EXPECTED_DELTA MUST BE IN THE UNITS SHOWN, and signed in real terms: GOOD_DIRECTION
says which way counts as improvement, so on a 'down' indicator an improvement is a
NEGATIVE delta.

DAILY-TIER - a new observation arrives constantly, so a DEADLINE up to 30 days out is fine:
  CLIMATE_GLOBAL_RISK_REVIEW: 427.15  [unit: ppm; means: co2 ppm mauna loa;
                                       GOOD_DIRECTION: down]  (updates daily)

SLOW-TIER - these update rarely. A DEADLINE BEFORE the next expected observation is
REFUSED, because nothing could arrive to settle it:
  COGNITION_LEARNING_REVIEW: 87.74  [unit: percent; means: literacy rate youth pct;
                                     GOOD_DIRECTION: up]
    (annual, last observed 2024-12-31, OVERDUE, next publication date unknown -
     ANY deadline is refused)
```

**The generator is told which indicators are unusable before it writes anything.** That
is the difference between a gate and a trap.

## 3. The exact refusal strings

These are literal, from `core/cadence.py` and `core/proposal_intake.py`. Match against
tonight's `memory/proposal_intake_refusals.jsonl` verbatim.

**Cadence — no last observation:**
```
cadence: {INDICATOR} is {cadence} and its last observation date is unknown,
so no deadline can be checked against it
```

**Overdue — the one added today:**
```
overdue: {INDICATOR} {cadence}, last observed {date}, next publication date unknown
```

**Cadence — deadline before the next observation:**
```
cadence: {INDICATOR} is {cadence}, last observed {date}, next expected {date};
deadline {date} is before any new observation
```

**Horizon — daily tier:**
```
horizon: {INDICATOR} is {cadence}, so a deadline may reach {N} days ({date});
{deadline} is further out
```

**Horizon — slow tier:**
```
horizon: {INDICATOR} is {cadence}, so a deadline may reach {date};
{deadline} is further out
```

**Scale — delta larger than the series moves:**
```
scale: delta {D} exceeds 2x the {N}-day range {R} ({min}..{max})
```

**Scale — the series never moves at all:**
```
no_scale: {INDICATOR} flat over {N} days (every observation {value})
```

**Scale unknown — NOT a refusal, a mark that travels with the proposal:**
```
unverified: {N} observations, need 7
```

**A check that cannot answer must say so, never wave the proposal through:**
```
cadence: check unavailable ({ExceptionType}: {message})
scale: check unavailable ({ExceptionType}: {message})
```

**Field refusals:**
```
indicator must be AXIS or AXIS__metric (got {value})
indicator {name!r} does not resolve today: {why_not}
expected_delta must be a number (got {value})
expected_delta of 0 predicts nothing
deadline {date} is not after today {today}
deadline must be an ISO date (got {value})
```

## 4. Events on every outcome

Every refused proposal is appended to `memory/proposal_intake_refusals.jsonl` as one
JSON line naming the injector, with **every** missing field, not just the first:

```json
{"ts": "...", "source": "hyperclaw_to_proposals", "component": "...",
 "solution": "...", "missing": ["indicator"], "why": "indicator 'LONG_TERM_FUTURE_REVIEW'
 does not resolve today: trends.json has no series 'LONG_TERM_FUTURE_REVIEW';
 axis_observations has no axis 'LONG_TERM_FUTURE_REVIEW'; metric_details has no
 metric 'LONG_TERM_FUTURE_REVIEW'"}
```

And the summary line is printed on **both** outcomes, so a clean run is visible rather
than silent:

```
[FAST_CYCLE] {source} -> {N} proposals admitted, 0 refused
[FAST_CYCLE] {source} -> {N} admitted, {M} REFUSED ungradeable (missing indicator:3,
             deadline:1); see memory/proposal_intake_refusals.jsonl
```

with `; {N} with scale UNVERIFIED` appended when any admitted delta was never scale-checked.

## 5. Last night's refusals are shown to tonight's generator

`refusals_block()` puts up to ten of the most recent refusals into the prompt. Tonight's
generator opens with a list of the ways last night's proposals failed — including its own:

```
hyperclaw_to_proposals: missing [expected_delta] - expected_delta must be a number
  (got '0.0 (snapshot only, без директна промяна)')
growth_to_proposals: missing [indicator, expected_delta, deadline] - ...
```

## 6. WHAT TO EXPECT AT 03:04 — the number that matters

**Thirteen indicators resolve today. With a 14-day deadline, exactly ONE is usable:**

```
usable: ['CLIMATE_GLOBAL_RISK_REVIEW']          1 of 13
```

Twelve are annual and **OVERDUE** — nine of them last observed in 2023 or 2024, two
with no last-observation date at all. For those, **any** deadline is refused by name.

**This is not a bug and the cycle should not be read as broken when it happens.** A
prediction about an annual series that last published in 2024 cannot be settled by a
date in September 2026, and a ledger that scores it scores noise. The refusal is the
gate working.

**But one usable indicator out of thirteen is a real constraint on the night's work**,
and the fix is not a looser gate — it is the daily tier. L1-DAILY exists to make more
of the thirteen publish often enough to be predictable, and until it lands, most
proposals should be expected to be refused with `overdue:` and that expectation should
not be mistaken for failure.

## 7. Two things to check against tonight's run

1. **The four OBJECTIVE-line proposals will be refused by name.** They carry no
   indicator triple, so they refuse with `missing [indicator, expected_delta, deadline]`.
   That is expected and correct — before this morning's `parse_plan` fix, they were
   silently absorbing the STEP blocks' triples instead.
2. **A generator that raises must land as a step REFUSAL, not as a crash.** The
   `check unavailable` strings above exist for exactly this: a layer that cannot answer
   says so and the proposal is refused, rather than being admitted on silence.
