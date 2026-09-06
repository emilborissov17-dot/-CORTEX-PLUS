# SPEC — FIRST BET (Kimi R40, Action 1). Written 2026-09-07 (night of 6→7 Sep) by Cowork Claude.
# The first REALLY-GRADED forecast: the system bets on tomorrow's value of ONE daily indicator,
# reality grades it in 24 h, and it is compared against persistence. This is the seed of the
# creativity loop (generate diversity → reality verifies truth). Archive-imitation is dead (A3
# 0.2611 vs base 0.2667 AT CHANCE); this replaces "imitate the past" with "bet on the future".

## HARD CONSTRAINTS
- STANDALONE. Build tools/first_bet.py as a new script. Do NOT modify fast_cycle_runner.py or
  agents/hyperclaw/* — tonight's 03:04 cycle must run on unchanged code so its gate report stays
  comparable. If A1 proves out, it is folded into hyperclaw LATER, not now.
- BUILD tonight, RUN tomorrow morning AFTER the 03:04 cycle has finished and released the GPU.
- Reuse the SHARED gate, do not reimplement it: route each candidate through the same contract the
  cycle uses — core/gate_contract.py (or core.proposal_intake.judge if that is the canonical entry;
  pick the one the live intake actually calls, and say which in the report).

## WHAT THE BET IS ON
ONE daily-cadence indicator that updates every day and yields a number. Default: GDELT_DAILY (global
daily event count, already fetched by the cycle). Fallback: a FRED daily series. Requirement before
betting: confirm from the LIVE payload that the series moved across the last 3 available days (not
frozen); if the default is frozen, pick another daily series that moved. Record the chosen indicator,
today's value V0, and V0's date.

## THE GENERATION (best-of-N)
- ONE prompt, N=8 completions from the local 3B (via the ladder; local leg is fine), temperature 0.7.
  Do NOT go above T=1.0 — for a numeric delta it only produces impossible numbers the gate discards.
- The prompt asks for a forecast of THAT indicator as EXACTLY three fields, one per line:
    INDICATOR: <name>
    EXPECTED_DELTA: <number>        # signed change from V0 to the deadline
    DEADLINE: <YYYY-MM-DD>          # tomorrow's date
  It also asks the model to state a confidence in [0,1] on a fourth optional line CONFIDENCE: <0..1>.

## THE GATE (filter)
Each of the 8 completions is parsed and passed through the shared gate contract. VALID requires: all
three fields present and resolve (a 2-line completion missing a field is REJECTED), EXPECTED_DELTA is
numeric, DEADLINE is a real future date within the daily-cadence horizon (≤ ~30 d, per the gate's
daily tier). Log every rejection by its exact refusal string. Keep only passing candidates.

## THE SEAL (choose one)
From the passing candidates seal ONE: the candidate with the smallest confidence width if the model
gave confidence, else the one whose EXPECTED_DELTA is closest to V0's own recent daily variation
(the median absolute day-to-day change over the last ~7 days). Write to a NEW ledger, isolated from
the live cycle: memory/first_bet/BET_<YYYY-MM-DD>.json with:
  indicator, V0, V0_date, predicted_delta, predicted_value (= V0 + delta), deadline,
  confidence (or null), chosen_reason, sha256_of_sealed_fields,
  all_8_candidates (raw text + parsed + gate verdict + refusal string if any).
Also seal the PERSISTENCE baseline for the same deadline in the same file:
  persistence_predicted_value = V0  (tomorrow = today). This is the null the bet must beat.

## OUTPUT
Report claude/reports/FIRST_BET_<YYYY-MM-DD>.md: chosen indicator + why, V0 and date, the sealed
forecast (delta, predicted value, deadline, confidence), the persistence baseline, how many of 8
passed the gate, every refusal string, and which gate entry point was used. Do NOT grade yet —
grading is a SEPARATE step +24 h against the real value.

## GRADING (the NEXT day — a separate command, do not build the run into tonight's script)
+24 h: fetch the real value at the deadline, compute |real − predicted_value| (system error) and
|real − persistence_predicted_value| (persistence error). Append the verdict to the same BET file and
to claude/reports/FIRST_BET_GRADED_<date>.md. The honest success signal (Kimi R40, ungameable): TWO
bets on TWO DIFFERENT indicators, both with system error < persistence error. One can be luck; two on
different targets cannot.

## GUARD TESTS (test/test_first_bet.py) — all against a hand-written FAKE payload, no live fetch, no GPU
1. a 2-line completion (missing DEADLINE) is rejected by the gate;
2. a non-numeric EXPECTED_DELTA ("a lot") is refused;
3. a past DEADLINE is refused;
4. the persistence baseline is sealed alongside the bet in the same file;
5. all 8 raw candidates are recorded, each with its gate verdict;
6. exactly ONE candidate is sealed, and its sha256 covers the three forecast fields;
7. (naming) the sealed indicator name is locked to the fetched series id, not a model-invented string —
   a completion naming a different indicator than the one being bet on is refused (guards the project's
   recurring defect: a name asserting a property the code never checks).

## PRE-REGISTERED PREDICTION (seal before the first grading)
Claude's expectation, on the record: the first single bet is roughly a coin-flip against persistence
on a daily event count — P(system error < persistence error on bet #1) ≈ 0.5. The signal that means
something is TWO different indicators beaten, not one. Record this in the first FIRST_BET report.
