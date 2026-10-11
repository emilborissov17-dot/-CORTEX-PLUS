# SYM-1 — CORRECTION of the 8B arm (10 Oct 2026); found by Claude reading the result files after commit b321961

## 1. The 8B arm in b321961 is INVALID, not "37 of 40"
- 41 of the 8B arm's 42 translator calls gave no reply.
- In memory/llm_provenance.jsonl the 41 calls show `ReadTimeout … (read timeout=10.6)`. The first call was a cold load of 165.9 s and the only one that returned.
- The cause is core/llm_door.timeout_for. It applies ONE measured read timeout, 10.6 s, to every local model. That value was learned from the 3B. qwen3:8b on this GPU (38 % CPU / 62 % GPU) needs longer.
- The keep_alive 0 policy outside a cycle also unloads the model after every call. On this point claude/FINDING_2026-10-10_8B_RELOADS_EVERY_CALL.md was right. It named the wrong main cause: the timeout is the main cause.

## 2. Claude's scorer counted silence as a correct "NO" (DEFECT-B)
- score_sym1.py c5bafa132e0c treated a statement whose translator gave no reply like a statement it judged empty. 41 silences therefore became 37 "correct" answers.
- The corrected scorer is ce2d2591a1cd:
  - every silent statement counts as WRONG;
  - each arm reports TRANSLATOR SILENCE;
  - an arm with any silence is marked INVALID as a measure of translation.

## 3. The fix for the 8B rerun (engine_ops.py 118acd65fa93, run_sym1.py 924f4ff17c29)
- Two process-local overrides apply for the experiment's model only. No system file changes.
  - The read timeout is 600 s.
  - keep_alive is "30m", so the model stays loaded for its phase and is not reloaded per call. The phases alternate, not the calls (Emil, R82).
- The RUN line prints the effective overrides and the no-reply count.

## 4. What stood in b321961 and still stands
- In every arm the engine accepted nothing without provenance and refused all 6 corruptions.
- The 3B arm answered all 42 calls.
  - It found none of the 3 real measures.
  - It accepted one table row (Equatorial Guinea 660) that the labeller marked NO. Its spans are literal, so the engine's checks cannot see the wrong meaning.
- The rules arm found 2 of the 3 real measures and accepted 14 rows that are not measures.

## 5. Addendum (11 Oct 07:10Z): the 8B rerun answers but is slow — a second per-call swap, found in llm_provenance
- The first rerun calls are answered (outcome ok, finish stop, 26 completion tokens). Latency per call is 101–239 s.
- The model's own work is about 26 s per call: load 14.4 s, prompt 9.4 s, generation 2.4 s.
- The rest is a swap. After every non-core call, core/llm_door._restore_core_after loads the "warm core" (cortex-l1b-3b) back in, and that evicts the 8B; on 10 Oct the run log said "warm core restored after qwen3:8b: cortex-l1b-3b in 8.8 s". The next 8B call then loads the 8B again.
- First left to finish; on Emil's order (11 Oct, 10:22 local) it is KILLED unfinished (about 8 of 42 calls done, at 51–251 s each) and rerun with the fix in §6.
- The fix for the phases (R82):
  - inside a phase, the door must not restore the core after each call, only at the phase's end;
  - in an experiment, a process-local override;
  - in the system, part of the symbolic-path build.

## 6. The fix, run (C-SYM1-RUN-3, 11 Oct): "Claude outputs/SYM1v2"
- Claude's miss: the line "warm core restored after qwen3:8b" was in the 10 Oct run log; C-SYM1-RUN-2 fixed the timeout and keep_alive and left the swap (CLAUDE_ERRORS n 51, caught by Emil).
- engine_ops.py (process-local, no system file changes):
  - the door's `_restore_core_after` is a no-op for the experiment's model; the core is restored ONCE, at the phase's end;
  - the phase STARTS by unloading the warm core (pinned keep_alive -1 on a 4 GB card), so the 8B has the card alone; not for the 3B arm, which is the core.
- The witness, printed as `PHASE 8b: {...}` and stored as "phase" in the result: from memory/llm_provenance.jsonl, the door's own rows, every call after the first must load nothing (load_duration_s < 1), and the core must be off the card at the phase start. Otherwise `PHASE BROKEN`.
- Rehearsed in a twin with the door's real restore logic and a fake Ollama holding one model: the old code gives 41 reloads in 42 calls (the machine's defect, reproduced); the new code 0 and `PHASE HELD`; removing either fix gives `PHASE BROKEN`.
