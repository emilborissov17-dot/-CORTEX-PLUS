#!/usr/bin/env python3
"""DEFECT-C (Kimi R56): a step must run AFTER the step that writes the file it reads,
or it judges last night's value under tonight's stamp. Pairs, not rising indices:
the runner's indices are labels and two pairs elsewhere are out of numeric order."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BEAT = re.compile(r'^\s*beat\("([^"]+)",\s*"([^"]+)"', re.M)

PAIRS = [
    ("update_master", "trend_tracker"),          # snapshots/master/master_snapshot_latest.json
    ("scoring_engine", "trend_tracker"),         # output/cortex_scores_latest.json
    ("goal_score_calculator", "alarm_bands"),    # snapshots/master/goal_score_latest.json
    ("auto_levels", "level_reconcile"),          # memory/auto_levels.json (the word it corrects)
    ("goal_score_calculator", "level_reconcile"),  # snapshots/master/goal_score_latest.json (the number)
    ("alarm_bands", "deduction"),                # memory/alarm_bands_latest.json
    ("level_reconcile", "deduction"),            # memory/auto_levels.json, corrected
    ("merkle_verify", "output_contracts"),       # memory/merkle_verify_latest.json
    ("learn_world", "output_contracts"),         # the learner state learn_world writes
]


def _order():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    return [m.group(1) for m in BEAT.finditer(src)]


def test_every_named_step_is_beaten_exactly_once():
    names = _order()
    for a, b in PAIRS:
        for n in (a, b):
            assert names.count(n) == 1, f"{n} beaten {names.count(n)} times"


def test_each_producer_runs_before_its_reader():
    names = _order()
    late = [(a, b) for a, b in PAIRS if names.index(a) > names.index(b)]
    assert not late, f"reader before producer (DEFECT-C): {late}"
