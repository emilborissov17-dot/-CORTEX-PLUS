# -*- coding: utf-8 -*-
"""test/test_learn_world.py — the learning runs inside the night (task #60, 11 Sep 2026).

Pinned:
  * every part runs; one failing part is recorded and the others still run
  * the artifact memory/learn_world_latest.json is written
  * world_forecast.cmd_predict is idempotent: the morning catch-up does not seal twice
  * the step is registered in cycle_map and beaten in the runner before self_experiment
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
from core import learn_world as LW  # noqa: E402


class _WF:
    class Refused(RuntimeError):
        pass

    def __init__(self, refuse=False):
        self.refuse = refuse

    def cmd_score(self):
        return 3

    def cmd_predict(self):
        if self.refuse:
            raise self.Refused("nothing moves")
        return [1, 2]

    def learner_report(self):
        return {"a": {}, "b": {}}


class _Tier:
    """A stand-in for core/daily_tier.py handed back by the fake _load.

    THE INJECTION DOOR MOVED, 11 Sep 2026, and the reason is a production fix.
    These tests used to patch `core.daily_tier.record`, because _tier() imported
    the sibling as a package. The first real run of the step failed on exactly
    that — `ImportError: cannot import name 'daily_tier' from 'core' (unknown
    location)` — because run as a script sys.path[0] is core/, not the repo root.
    _tier() now uses _load(), like its four siblings, so a fake _load is the only
    thing that can intercept it. The property under test is unchanged: one failing
    part is recorded and the others still run."""

    def __init__(self, result):
        self._result = result

    def record(self):
        return self._result


def test_all_parts_run_and_one_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    def fake_load(name, rel):
        if name == "world_forecast":
            return _WF()
        if name == "daily_tier":
            return _Tier({"error": "snapshot unreadable: x", "written": 0})
        raise ImportError("league missing")
    monkeypatch.setattr(LW, "_load", fake_load)
    out = LW.run(latest=tmp_path / "lw.json")
    assert out["daily_tier"]["ok"] is False and "snapshot unreadable" in out["daily_tier"]["error"]
    assert out["world_score"]["result"] == {"newly_scored": 3}
    assert out["world_predict"]["result"] == {"sealed": 2}
    assert out["learner"]["result"] == {"indicators": 2}
    assert out["backend_league"]["ok"] is False
    assert set(out["failed_parts"]) == {"daily_tier", "backend_league"}
    assert json.loads((tmp_path / "lw.json").read_text(encoding="utf-8"))["ok_parts"] == 3


def test_a_refusal_to_predict_is_a_result_not_a_failure(tmp_path, monkeypatch):
    def fake_load(name, rel):
        if name == "world_forecast":
            return _WF(refuse=True)
        if name == "daily_tier":
            return _Tier({"written": 5, "already_on_file": 10})
        raise ImportError()
    monkeypatch.setattr(LW, "_load", fake_load)
    out = LW.run(latest=tmp_path / "lw.json")
    assert out["daily_tier"]["result"] == {"written": 5, "already_on_file": 10}
    assert out["world_predict"]["ok"] and out["world_predict"]["result"] == {"refused": "nothing moves"}


def test_world_predict_does_not_seal_twice(monkeypatch):
    import world_forecast as wf
    sealed = []
    monkeypatch.setattr(wf.pl, "read_all", lambda: [{"event": wf.pl.PREDICTION, "target_kind": wf.KIND,
                                                     "target_id": "X::after::2026-09-10"}])
    monkeypatch.setattr(wf.pl, "seal_prediction", lambda **kw: sealed.append(kw["target_id"]) or kw)
    monkeypatch.setattr(wf, "_state", lambda: {})
    series = {"X": [(f"2026-09-{d:02d}", float(d % 3)) for d in range(1, 11)],
              "Y": [(f"2026-09-{d:02d}", float(d % 4)) for d in range(1, 11)]}
    wf.cmd_predict(series)
    assert sealed == ["Y::after::2026-09-10"]


def test_the_step_is_in_the_map_and_in_the_runner():
    cm = (REPO / "core" / "cycle_map.py").read_text(encoding="utf-8")
    assert '("learn_world", "25.43"' in cm
    fcr = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    i, j = fcr.index('beat("learn_world", "25.43")'), fcr.index('beat("self_experiment", "25.44")')
    assert i < j


# ── every part loads BY PATH, because a step is not a -c one-liner ───────────

def test_no_part_imports_a_sibling_as_a_package():
    """THE FIRST REAL RUN FAILED ON THIS, 11 Sep 2026:

        "daily_tier": {"ok": false,
          "error": "ImportError: cannot import name 'daily_tier' from 'core' (unknown location)"}

    Four parts used _load() — an absolute path off BASE — and one used
    `from core import daily_tier`. Run as a script, which is how both the cycle
    step and the morning task invoke this file, sys.path[0] is core/ rather than
    the repo root, so the `core` package is not importable and resolves as a
    locationless namespace. It works from `python -c` (cwd is on the path) and
    fails as a step: green by hand, red in the night.

    The forbidden shortcut is to add BASE to sys.path and keep the package import
    — that fixes the symptom and leaves two ways of loading a sibling in one file,
    which is how they drift apart again."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "learn_world.py"
           ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "core":
            offenders.append(f"from {node.module} import "
                             + ", ".join(a.name for a in node.names))
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "core":
                    offenders.append(f"import {a.name}")
    assert not offenders, (
        "core/learn_world.py imports a sibling as a package: " + "; ".join(offenders)
        + ". Use _load(name, 'core/<file>.py') — it takes an absolute path off BASE "
          "and does not depend on sys.path.")


def _real_tier_only(monkeypatch, tmp_path):
    """The REAL daily_tier against the REAL snapshot, with every writer redirected
    into tmp_path.

    The first version of these two tests called lw.run() outright and the repo's
    own _no_live_writes fixture failed them for writing
    memory/learn_world_latest.json and memory/backend_order_measured.json. That
    guard is right and its message says what to do: fix the fixture. So the tier —
    the part under test — stays real, and the league (the other live writer) is
    stubbed away."""
    real_load = LW._load

    def load(name, rel):
        if name == "backend_league":
            raise ImportError("stubbed: writes memory/backend_order_measured.json")
        return real_load(name, rel)
    monkeypatch.setattr(LW, "_load", load)
    return LW.run(latest=tmp_path / "lw.json")


def test_the_tier_part_actually_answers_on_this_repo(tmp_path, monkeypatch):
    """Not a mock: the real record() against the real snapshot. It must report the
    keys learn_world forwards, and must NOT come back as a failed part — which is
    what it did before the by-path fix."""
    r = _real_tier_only(monkeypatch, tmp_path)
    tier = r.get("daily_tier")
    assert tier and tier.get("ok") is True, f"the tier part failed: {tier}"
    assert set(tier["result"]) <= {"written", "already_on_file"}
    assert "daily_tier" not in (r.get("failed_parts") or [])


def test_a_second_run_writes_no_new_tier_rows(tmp_path, monkeypatch):
    """Idempotent, which is what makes it safe as a nightly step AND as a rehearsal
    by hand: the same snapshot must not append the same (indicator, date) twice."""
    _real_tier_only(monkeypatch, tmp_path)
    again = _real_tier_only(monkeypatch, tmp_path)
    assert again["daily_tier"]["result"].get("written") == 0
