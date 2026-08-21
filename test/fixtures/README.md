# test/fixtures — captured evidence, not runtime state

Everything here is a VERBATIM slice of something a producer wrote on a named day.
Nothing is reconstructed. A fixture is committed when a test needs real evidence
and the live file it came from is regenerable runtime state that `.gitignore`
keeps out of the repo.

The rule this directory exists to enforce: **a test must not read a file that a
fresh clone does not have.** Before these captures, seven tests read
`memory/*.json` directly. They passed on this machine and would have failed on a
clone — the data was on disk only because a cycle had run here.

| fixture | captured from | producer | read by |
|---|---|---|---|
| `target_config_pre_subgoals.json` | `config/target_config.json` (pre-subgoal tree) | hand-edited config | `test_axis_tree_contract.py` |
| `mirror_cycle_2026-08-21/` | `memory/brain_step_log.jsonl`, `memory/step_contract_latest.json` | `core/self_mirror.py` | `test_self_mirror.py` |
| `debriefs_2026-08-21_accepted/` | the six accepted debriefs of 21 Aug 2026 | `core/phase_debrief.py` | `test_phase_evidence_swap.py` |
| `threshold_proposals_2026-08-21.json` | `memory/threshold_proposals.json` | `scripts/propose_alarm_thresholds.py` | `test_alarm_bands.py` |
| `step_callmap_2026-08-21.json` | `memory/step_callmap.json` | `scripts/step_callmap.py` | `test_step_contract.py` |
| `self_experiments_2026-08-21.json` | `memory/self_experiments.json` | `core/self_experiment.py` | `test_self_experiment.py` |
| `interoception_2026-08-21/memory/self_mirror_latest.json` | `memory/self_mirror_latest.json` | `core/self_mirror.py` | `test_interoception.py` |

`interoception_2026-08-21/` keeps the `memory/` level because
`core.interoception.must_cite(base=...)` resolves `<base>/memory/self_mirror_latest.json`.
The fixture matches the contract rather than the test working around it.

## What a captured test can and cannot claim

These tests changed meaning when they moved here, and the change is deliberate.
They no longer assert anything about what this machine did last night — they are
regression guards on evidence that does not move. A test that must observe live
state belongs in a cycle check, not in the suite; the suite runs on clones.

## Refreshing a capture

Re-run the producer, copy the file, and say in the commit why the old capture no
longer serves. Do not edit a fixture by hand — a hand-edited capture is a
reconstruction wearing a capture's name, and the docstrings here promise otherwise.
