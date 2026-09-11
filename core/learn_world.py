# -*- coding: utf-8 -*-
"""
core/learn_world.py — THE LEARNING, INSIDE THE NIGHT (11 Sep 2026, task #60).

The table "cycle x 14 points" said it plainly: of 67 nightly steps only six served
learning in parameters, and the real learning — learner_state, the world loop —
lived in a 9-step morning task, six hours after the data it learns from was fetched.
The body was 67 steps; the mind was an app that ran at breakfast.

This step runs in G_LEARN, after tonight's fetch (2.5) and before the mirror, the
debrief and the report, so all three see what was learned tonight:

  1. daily_tier.record()           keep tonight's fetch as dated observations
  2. world_forecast.cmd_score()    score every prediction whose next value just arrived,
                                   refit alpha per indicator  (learning in a parameter)
  3. world_forecast.cmd_predict()  seal tomorrow's predictions (idempotent)
  4. backend_league                which cloud mind goes first, from tonight's calls

The morning task keeps the same commands as an idempotent catch-up for a night that
failed before this step. Self-forecast scoring stays in the morning on purpose: it
scores the night itself, which cannot be judged from inside it.

Fail-open per part: one part failing is written down and the others still run.
Writes memory/learn_world_latest.json (the step's promised artifact).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
LATEST = BASE / "memory" / "learn_world_latest.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, BASE / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _part(out: dict, key: str, fn):
    try:
        out[key] = {"ok": True, "result": fn()}
    except Exception as exc:  # noqa: BLE001
        out[key] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def run(latest: Path | None = None) -> dict:
    out: dict = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def _tier():
        # BY PATH, LIKE ITS FOUR SIBLINGS (fixed 11 Sep 2026). This part alone used
        # `from core import daily_tier`, and the first real run of the step failed:
        #     ImportError: cannot import name 'daily_tier' from 'core' (unknown location)
        # Run as a script — which is how the cycle and the morning task invoke it —
        # sys.path[0] is core/, not the repo root, so the `core` PACKAGE is not
        # importable and `core` resolves as a locationless namespace. It works from
        # a `-c` one-liner (cwd is on the path) and fails as a step, which is the
        # worst shape for a bug: green by hand, red in the night.
        # _load() takes an absolute path off BASE and does not care about sys.path.
        daily_tier = _load("daily_tier", "core/daily_tier.py")
        r = daily_tier.record()
        if isinstance(r, dict) and r.get("error"):
            raise RuntimeError(r["error"])
        return {k: r.get(k) for k in ("written", "already_on_file") if k in r}
    _part(out, "daily_tier", _tier)

    wf = None
    try:
        wf = _load("world_forecast", "experiments/prophecy/world_forecast.py")
    except Exception as exc:  # noqa: BLE001
        out["world_forecast"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if wf is not None:
        _part(out, "world_score", lambda: {"newly_scored": wf.cmd_score()})

        def _predict():
            try:
                return {"sealed": len(wf.cmd_predict())}
            except wf.Refused as why:
                return {"refused": str(why)}
        _part(out, "world_predict", _predict)
        _part(out, "learner", lambda: {"indicators": len(wf.learner_report())})

    def _league():
        bl = _load("backend_league", "scripts/backend_league.py")
        lg = bl.league(bl._rows(bl.PROVENANCE), bl._reads(bl.PROBE))
        bl.ORDER.parent.mkdir(parents=True, exist_ok=True)
        bl.ORDER.write_text(json.dumps({"ts": lg["ts"], "order": lg["order"], "source": "core/learn_world.py"},
                                       indent=1), encoding="utf-8")
        return {"order": lg["order"]}
    _part(out, "backend_league", _league)

    out["ok_parts"] = sum(1 for v in out.values() if isinstance(v, dict) and v.get("ok"))
    out["failed_parts"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("ok") is False]
    try:
        p = latest or LATEST
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except OSError as exc:
        out["write_error"] = str(exc)
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if not r["failed_parts"] else 1)
