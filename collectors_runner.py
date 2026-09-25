#!/usr/bin/env python3
"""
collectors_runner.py — the collectors, run BEFORE the spine (task #8 B.B, 25 Sep 2026).

web_intelligence and data_scout used to be spine steps 1 and 22.5. Both ask a model
(the ladder, the local core), so the spine reached the LLM stack through them, and a
night whose model was absent sealed their output with no word on its footing. They run
here now, in their own process with their own witness rows (role "collectors"), and
end in one manifest (core/collectors_manifest.py): what each wrote, when it fetched,
and its level. A collector that ran without its model is written UNVERIFIED with the
reason - never an unknown origin. The spine's two steps only validate and read that
manifest.

    venv\\Scripts\\python.exe collectors_runner.py --run-id <id>
    venv\\Scripts\\python.exe collectors_runner.py --selftest
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from core import collectors_manifest as cm  # noqa: E402

# Everything each collector may write; a file counts as this run's only if it was
# written after the run began.
OUTPUT_GLOBS = {
    "web_intelligence": ["memory/web_intelligence/**/*.json"],
    "data_scout": ["memory/discovered_data_sources.json", "memory/composer_needs.json"],
}


def _written_since(name: str, t0: float, base: Path = BASE) -> list:
    out = set()
    for g in OUTPUT_GLOBS.get(name, []):
        for p in base.glob(g):
            try:
                if p.is_file() and p.stat().st_mtime >= t0:
                    out.add(p.relative_to(base).as_posix())
            except OSError:
                continue
    return sorted(out)


def _ceiling(name: str, default: int) -> int:
    try:
        import json
        cfg = json.loads((BASE / "config" / "scheduler.json").read_text(encoding="utf-8"))
        return int((cfg.get("step_ceilings_sec") or {}).get(name, default))
    except Exception:
        return default


def _web_intel_order():
    """The axes the brain's plan named go first - a priority, not a filter (moved
    here from fast_cycle_runner with the step)."""
    try:
        from web_intelligence_agent import AXES
        allx = list(AXES.keys())
    except BaseException:          # the module sys.exits without feedparser
        return None
    try:
        from core.brain import current_plan
        plan = current_plan() or {}
        if plan.get("_stale"):
            return None
        want = " ".join(str(plan.get(k, "")) for k in ("focus", "watch")).lower()
    except Exception:
        return None
    first = [a for a in allx if any(w and w in a.lower() for w in want.replace(",", " ").split())]
    if not first:
        return None
    return first + [a for a in allx if a not in first]


def _spawn(name: str, code: str, budget: int, env: dict) -> tuple[str, str]:
    """Run one collector in a child process. (status, detail)."""
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(BASE), timeout=budget,
                           env={**env, "CORTEX_STEP": name})
        return ("ok", "") if r.returncode == 0 else ("failed", f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return "timeout", f"budget {budget}s ran out; what reached the disk stays"
    except Exception as exc:  # noqa: BLE001
        return "failed", f"{type(exc).__name__}: {exc}"


def web_intelligence(env: dict) -> tuple[str, str]:
    budget = max(300, _ceiling("web_intelligence", 3600) - 300)
    code = ("import sys; sys.path.insert(0, %r);"
            "import web_intelligence_agent as w; w.run(axes_filter=%r)"
            % (str(BASE), _web_intel_order()))
    return _spawn("web_intelligence", code, budget, env)


def data_scout(env: dict) -> tuple[str, str]:
    budget = _ceiling("data_scout", 1200)
    code = ("import sys; sys.path.insert(0, %r);"
            "from core.data_scout import run; s = run(max_axes=2);"
            "print('[COLLECTORS] data_scout scanned=%%s validated=%%s' %% "
            "(s.get('scanned', 0), s.get('validated', 0)))" % str(BASE))
    return _spawn("data_scout", code, budget, env)


RUNNERS = {"web_intelligence": web_intelligence, "data_scout": data_scout}


def run(run_id: str, runners: dict | None = None, base: Path = BASE,
        provenance: Path | None = None) -> dict:
    runners = runners or RUNNERS
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "CORTEX_COLLECTORS": str(run_id),
           "CORTEX_IN_CYCLE": str(run_id)}     # the warm core only; no model loads
    manifest = {"collector_run_id": str(run_id), "collectors": {}}
    for name in cm.COLLECTORS:
        started = datetime.now(timezone.utc)
        t0 = time.time()
        try:
            status, detail = runners[name](env)
        except Exception as exc:  # noqa: BLE001
            status, detail = "failed", f"{type(exc).__name__}: {exc}"
        calls = cm.model_calls(name, started, provenance)
        e = cm.entry(name, started, status, _written_since(name, t0, base), calls, detail)
        manifest["collectors"][name] = e
        print(f"[COLLECTORS] {name}: {status} level={e['level']} outputs={len(e['outputs'])}"
              + (f" reason={e['reason']}" if e.get("reason") else ""))
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = cm.write(manifest, base if base != BASE else None)
    print(f"[COLLECTORS] manifest -> {path}")
    return manifest


def main(argv: list) -> int:
    if "--selftest" in argv:
        print("collectors_runner.py --selftest")
        for mod in ("web_intelligence_agent", "core.data_scout", "core.collectors_manifest"):
            try:
                __import__(mod)
                print(f"  LIVE   {mod}")
            except BaseException as exc:  # noqa: BLE001 - the agent may sys.exit
                print(f"  INERT  {mod} ({type(exc).__name__}: {exc})")
        v = {n: cm.validate(n) for n in cm.COLLECTORS}
        for n, r in v.items():
            print(f"  manifest[{n}]: ok={r['ok']} level={r['level']} "
                  f"fetched_at={r['fetched_at']} problems={r['problems']}")
        return 0
    rid = argv[argv.index("--run-id") + 1] if "--run-id" in argv else datetime.now().astimezone().isoformat()
    m = run(rid)
    return 0 if all(e["status"] == "ok" for e in m["collectors"].values()) else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
