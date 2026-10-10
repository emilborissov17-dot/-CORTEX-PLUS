# BN-1 and BN-2 — TERMINATED BY EMIL (10 Oct 2026), not passed, not failed, not naturally closed

## Decision
- **Decided by:** Emil R80, under Perplexity 89 (R73).
- **What Emil decided:** both windows are terminated now, so that the course can turn to the symbolic path (R79, R81).
- **Why:** both windows measured the current text loop, which departs from R23/R36/R40.

## Status of the two preregistrations
- **BN-2 (sealed 599c61f, lineage by rule):** stopped before its closing rule (6 consecutive takes with no new URL) was reached.
- **BN-1 (sealed 80ee307):** stopped likewise. It carried a lineage defect: its lineage was fixed to two ids. The defect is disclosed in the BN-2 prereg.

## The data at termination
- The data are the outputs of the sealed, unchanged measurement scripts, run in the termination commit:
  - BN-2: `Claude outputs/M-BN2/measure.py` (sha cfb9f9edc28a) → claude/reports/BN2_AT_TERMINATION_2026-10-10.json
  - BN-1: `Claude outputs/M-BN1/measure.py` (sha 57ff6768ba60) → claude/reports/BN1_AT_TERMINATION_2026-10-10.json
- Last figures before termination (Claude Code, 16:09Z): BN-2 had 3 takes, a run of 0 of 6, and 0 candidates; BN-1 had 0 takes.

## How to read this
- No claim of PASS or FAIL is made.
- "0 candidates" refutes nothing beyond these takes, in this window, by this count.

## Defects still open
- **The `measurements: 0` literal** in the need path's GAINED rows (Claude, 2f5c7da, 1 Oct). It is replaced by the symbolic path, where the engine records what it accepted.
- **The 3B text verdict (TEXT C).** It is to leave the loop when the symbolic path passes its check (claude/COURSE_2026-10-10.md, step 2).
