# FINDING (10 Oct 2026) — fresh-context verifier on C-VERDICT-1 (the 3B verdict becomes a note)

R65: a second instance that did not write the change was told to refute it before it became a command. It ran the tests against the old and the new code in its own copy. Summary of what it verified (its full report is in the session transcript):

1. HIGH — with the verdict a note, nothing frees a sub-goal; once all five hold an open parent the ask is skipped every turn. On the machine this is ALREADY the state: 66 ASK_SKIPPED rows, the last 10 Oct 06:35Z. The fix is not Claude's to choose: sent to Perplexity as round 83C (answer: rotate the ask regardless of open parents; budget per turn; no child without a checkable new detail).
2. MED — tools/stop_after_brain.py could request the stop before the witness brain turn (turns_loop writes no start row); several states never reach STOPPED (same-cause wait, stale pid, TURN_STUCK after the request leaves the stop flag behind).
3. MED — tools/daily_board.py:923 counts event == "SATISFIED", which is no longer written: a permanent 0. Covered by 83C В4.
4. MED — the needs_filled "coverage" field in scripts/turn_brain.py had no test and no mutation.
5. LOW — "status left exactly as it was" tested only from OPEN; mutation minimums in mutate.py were below the observed counts (observed 9/4/8/5/2); "coverage" can only hold UNCONFIRMED and the comment named an evidence path that does not exist (DEFECT-A); one added test passes on old code (a renamed legacy path); run_tests.py returns 0 on a stale xml.

Measured by the verifier: of the new tests, 9 fail on the old core/brain_needs.py and pass on the new one; mutate.py MUTATIONS OK; junit ids match compare.py exactly; apply.py apply / second apply / undo / CRLF all byte-correct.

Not given as a command yet. It is rebuilt with 83C В3 and these fixes, rehearsed again, then given.
