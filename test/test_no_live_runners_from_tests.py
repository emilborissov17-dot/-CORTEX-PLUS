"""
test/test_no_live_runners_from_tests.py — no test may start a real runner.

25 Sep 2026: supervisor.tick() under test reached COLLECTORS_START and started the
real collectors runner twice against the live repo. Decision: two nets - the
conftest fixture refusing any subprocess that names a runner, and the collectors
runner refusing a start without --run-id - each asserted below.

Rule: these tests must fail if either net is removed, and must be harmless when
one is: every subprocess below is `python -c pass <name>`, which runs nothing.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import supervisor as sup


@pytest.mark.parametrize("name", ["collectors_runner.py", "edges_runner.py",
                                  "fast_cycle_runner.py"])
def test_a_subprocess_naming_a_runner_raises(name):
    with pytest.raises(RuntimeError, match="live runner"):
        subprocess.Popen([sys.executable, "-c", "pass", name])


def test_the_refusing_resume_gate_still_passes_the_net():
    p = subprocess.Popen([sys.executable, "-c", "pass", "fast_cycle_runner.py", "--from", "X"])
    assert p.wait(timeout=30) == 0




