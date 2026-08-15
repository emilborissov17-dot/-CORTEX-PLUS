#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/selfcode/selfcode_loop.py — can the model close the write → test → fix loop?

THE QUESTION THIS ANSWERS
-------------------------
On 2026-08-04 the quarantine triage found that all 17 rejected self-modification patches
were dead weight: they failed, were rolled back, and nothing had ever fed the failure
back to the thing that wrote them. The pipeline could WRITE code and could JUDGE code,
but it had never once been asked to READ ITS OWN ERROR AND TRY AGAIN.

That is the capability everything else rests on. If a model cannot fix its own KeyError
when handed the traceback, then no amount of guardian, triage or ranking will produce a
useful patch — we would just be filtering noise more politely. So this measures the one
thing, in isolation, before anyone wires it to the real repo.

WHAT IS MEASURED
----------------
Per task: did it converge, and in how many iterations. The model sees the SPEC and, after
a failure, the test's own diagnosis — it never sees the test source. A model shown the
assertions can satisfy them without solving anything; that is measuring nothing.

ISOLATION — this is an experiment, not a foothold
-------------------------------------------------
  * the sandbox is a fresh tempfile.mkdtemp() OUTSIDE this repository;
  * generated code is executed only in a subprocess, with cwd=sandbox and a stripped
    environment (no CORTEX_BASE), under a wall-clock timeout;
  * generated code is NEVER imported into this process;
  * nothing is written inside the repo except the append-only run log.
Repo writes are asserted against, not merely intended — see _assert_outside_repo().

    venv/Scripts/python.exe experiments/selfcode/selfcode_loop.py --selftest
    venv/Scripts/python.exe experiments/selfcode/selfcode_loop.py            # all tasks
    venv/Scripts/python.exe experiments/selfcode/selfcode_loop.py --task monotonic_runs
    venv/Scripts/python.exe experiments/selfcode/selfcode_loop.py --backend local
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))

RUN_LOG = REPO / "memory" / "selfcode_runs.jsonl"
MAX_ITERATIONS = 5
EXEC_TIMEOUT = 30
DIAGNOSIS_CHARS = 900


# ── the tasks ────────────────────────────────────────────────────────────────
#
# Each mirrors a real shape in this repo, so a pass means something transferable.
# `spec` is shown to the model. `test` never is.

TASKS = {
    "monotonic_runs": {
        "spec": """Write a module with one function:

    def monotonic_tail(history, min_points=5):
        '''history is a list of (timestamp, value) pairs. Some values are None or
        strings and must be ignored. Using only the last `min_points` NUMERIC values,
        return "up" if they are non-decreasing, "down" if non-increasing, and None
        otherwise. If there are fewer than min_points numeric values, return None.
        A flat run (all equal) counts as "up".'''
""",
        "test": '''
from solution import monotonic_tail as f
assert f([("t", 1), ("t", 2), ("t", 3), ("t", 4), ("t", 5)]) == "up"
assert f([("t", 5), ("t", 4), ("t", 3), ("t", 2), ("t", 1)]) == "down"
assert f([("t", 1), ("t", 9), ("t", 2), ("t", 8), ("t", 3)]) is None
assert f([("t", 7)] * 5) == "up", "a flat run counts as up"
assert f([("t", 1), ("t", 2), ("t", 3)]) is None, "too few points"
assert f([]) is None
assert f([("t", None), ("t", "x"), ("t", 1), ("t", 2), ("t", 3), ("t", 4), ("t", 5)]) == "up", \\
    "None and strings must be skipped, not crash"
assert f([("t", 0), ("t", 1), ("t", 2)], min_points=3) == "up"
assert f([("t", 9), ("t", 1), ("t", 2), ("t", 3), ("t", 4), ("t", 5)]) == "up", \\
    "only the LAST min_points values are considered"
print("ALL PASS")
''',
    },
    "safe_ratio": {
        "spec": """Write a module with one function:

    def stress_index(demand, supply):
        '''Return demand/supply rounded to 3 decimals, as a float.
        Both may be None, zero, negative, or non-numeric (e.g. a string).
        Return None — never raise, never return inf or nan — whenever the inputs
        cannot produce a meaningful ratio. A negative demand or supply is not
        meaningful. A supply of zero is not meaningful.'''
""",
        "test": '''
from solution import stress_index as f
import math
assert f(1, 2) == 0.5
assert f(2, 3) == 0.667, "must round to 3 decimals"
assert f(0, 5) == 0.0, "zero demand is meaningful"
assert f(1, 0) is None, "division by zero"
assert f(None, 5) is None
assert f(5, None) is None
assert f("x", 5) is None
assert f(5, "x") is None
assert f(-1, 5) is None, "negative demand is not meaningful"
assert f(5, -1) is None, "negative supply is not meaningful"
r = f(1, 3)
assert isinstance(r, float) and not math.isnan(r) and not math.isinf(r)
assert f(True, 2) is None or isinstance(f(True, 2), float)
print("ALL PASS")
''',
    },
    "merge_series": {
        "spec": """Write a module with one function:

    def merge_latest(series):
        '''series is a list of dicts, each {"source": str, "ts": str, "value": float}.
        Timestamps are ISO-8601 strings and may repeat across sources.
        Return a dict mapping source -> the value with the LATEST ts for that source.
        Entries whose value is not a number, or whose ts is missing/empty, are
        dropped. An empty or None input returns an empty dict. Never raise.'''
""",
        "test": '''
from solution import merge_latest as f
assert f([]) == {}
assert f(None) == {}
data = [
    {"source": "a", "ts": "2026-01-01T00:00:00", "value": 1.0},
    {"source": "a", "ts": "2026-06-01T00:00:00", "value": 2.0},
    {"source": "b", "ts": "2026-03-01T00:00:00", "value": 9.0},
]
assert f(data) == {"a": 2.0, "b": 9.0}
assert f([{"source": "a", "ts": "", "value": 1.0}]) == {}, "empty ts dropped"
assert f([{"source": "a", "value": 1.0}]) == {}, "missing ts dropped"
assert f([{"source": "a", "ts": "2026-01-01", "value": "x"}]) == {}, "non-numeric dropped"
mixed = [
    {"source": "a", "ts": "2026-01-01", "value": 1.0},
    {"source": "a", "ts": "2026-02-01", "value": None},
]
assert f(mixed) == {"a": 1.0}, "a bad later entry must not erase a good earlier one"
print("ALL PASS")
''',
    },
}


# ── isolation ────────────────────────────────────────────────────────────────

def _assert_outside_repo(path: Path) -> None:
    """A sandbox inside the repo is not a sandbox."""
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(REPO.resolve())
    except ValueError:
        return                      # outside the repo: correct
    raise RuntimeError(f"refusing to run: sandbox {resolved} is inside the repo {REPO}")


def _clean_env() -> dict:
    """No CORTEX_BASE, so a stray patch-style write has no repo root to aim at."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CORTEX_BASE", "PYTHONPATH")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _diagnosis(stderr: str, limit: int = DIAGNOSIS_CHARS) -> str:
    """Keep the END of a traceback — the assertion message lives on the last line."""
    text = (stderr or "").strip()
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    return f"{lines[0][:120]}\n[...]\n" + "\n".join(lines[1:])[-(limit - 130):]


# ── the loop ─────────────────────────────────────────────────────────────────

def _extract_code(reply: str) -> str:
    """Last fenced python block, else the whole reply."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", reply, re.DOTALL)
    return (blocks[-1] if blocks else reply).strip()


def _local_at(prompt: str, temperature: float) -> str:
    """autonomous_scout._local pins temperature=0.1, which is right for extraction and
    wrong for a retry: at 0.1 the model re-emits what it just wrote. The first local run
    of merge_series failed five times with a byte-identical 17-line module and the same
    TypeError, which looks like "cannot learn from the diagnosis" but is at least partly
    "was never given room to answer differently". Retries escalate the temperature so
    the two explanations can be told apart."""
    import requests
    from autonomous_scout import _MODEL, _OLLAMA
    r = requests.post(f"{_OLLAMA}/api/chat", timeout=240, json={
        "model": _MODEL, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": temperature, "num_predict": 1200}})
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("content") or "").strip()


def _ask(prompt: str, backend: str, iteration: int = 1) -> str:
    if backend == "local":
        # 0.1 on the first attempt, then widen: 0.1, 0.35, 0.6, 0.85, capped at 1.0
        return _local_at(prompt, min(0.1 + 0.25 * (iteration - 1), 1.0))
    from core.groq_backend import call_groq
    return call_groq(prompt, max_tokens=1500)


def _run_test(sandbox: Path, code: str, test_src: str) -> tuple[bool, str]:
    (sandbox / "solution.py").write_text(code, encoding="utf-8")
    (sandbox / "check.py").write_text(test_src, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "check.py"],
            cwd=str(sandbox), env=_clean_env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=EXEC_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"timeout: the code did not finish in {EXEC_TIMEOUT}s"
    if proc.returncode == 0 and "ALL PASS" in (proc.stdout or ""):
        return True, ""
    return False, _diagnosis((proc.stderr or "") or (proc.stdout or ""))


FIRST_PROMPT = """Write a complete, self-contained Python module.

{spec}

Rules:
- Reply with ONE ```python fenced block and nothing else.
- No imports beyond the standard library.
- The function must never raise on the inputs described — handle bad input by
  returning the documented fallback.
"""

RETRY_PROMPT = """Your previous attempt FAILED its tests.

{spec}

YOUR PREVIOUS CODE:
```python
{code}
```

THE FAILURE:
{diagnosis}

Fix it. Reply with ONE ```python fenced block containing the complete corrected module,
and nothing else. Do not explain."""


def run_task(name: str, task: dict, backend: str, max_iter: int) -> dict:
    sandbox = Path(tempfile.mkdtemp(prefix=f"cortex_selfcode_{name}_"))
    _assert_outside_repo(sandbox)
    record = {"task": name, "backend": backend, "sandbox": str(sandbox),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "iterations": [], "converged": False, "iterations_used": 0}
    code, diagnosis = "", ""
    try:
        for i in range(1, max_iter + 1):
            prompt = (FIRST_PROMPT.format(spec=task["spec"]) if i == 1 else
                      RETRY_PROMPT.format(spec=task["spec"], code=code,
                                          diagnosis=diagnosis))
            try:
                reply = _ask(prompt, backend, i)
            except Exception as e:
                record["iterations"].append({"n": i, "error": f"{type(e).__name__}: {e}"})
                print(f"    iter {i}: LLM FAILED {type(e).__name__}")
                break
            code = _extract_code(reply)
            ok, diagnosis = _run_test(sandbox, code, task["test"])
            record["iterations"].append({
                "n": i, "passed": ok, "code_lines": code.count("\n") + 1,
                "diagnosis": diagnosis[:400] if not ok else None})
            record["iterations_used"] = i
            print(f"    iter {i}: {'PASS' if ok else 'fail'}"
                  f"{'' if ok else ' — ' + diagnosis.splitlines()[-1][:90]}")
            if ok:
                record["converged"] = True
                record["final_code"] = code
                break
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    return record


def _append_log(rec: dict) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in rec.items() if k != "final_code"},
                            ensure_ascii=False) + "\n")


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> int:
    print("selfcode_loop --selftest")
    status = {}
    try:
        from core.groq_backend import call_groq  # noqa: F401
        status["core.groq_backend (cloud)"] = "LIVE"
    except Exception as e:
        status["core.groq_backend (cloud)"] = f"INERT ({type(e).__name__})"
    try:
        from autonomous_scout import _local  # noqa: F401
        status["autonomous_scout._local (local)"] = "LIVE"
    except Exception as e:
        status["autonomous_scout._local (local)"] = f"INERT ({type(e).__name__})"

    sandbox = Path(tempfile.mkdtemp(prefix="cortex_selfcode_selftest_"))
    try:
        _assert_outside_repo(sandbox)
        status["sandbox outside repo"] = "LIVE"
        ok, _ = _run_test(sandbox, "def monotonic_tail(h, min_points=5): return 'up'",
                          "from solution import monotonic_tail\nprint('ALL PASS')")
        status["subprocess harness"] = "LIVE" if ok else "INERT (harness did not pass)"
        # check.py MUST import solution, or the broken module never runs and the probe
        # "passes" while proving nothing — which is exactly what it did on first write.
        bad_ok, diag = _run_test(sandbox, "def f():\n    raise KeyError('name')\nf()",
                                 "import solution\nprint('ALL PASS')")
        status["failure is captured"] = (
            "LIVE" if (not bad_ok and "KeyError" in diag) else "INERT (no diagnosis)")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    try:
        _assert_outside_repo(REPO / "tmp_sandbox")
        status["repo-write guard"] = "INERT (it allowed a sandbox inside the repo!)"
    except RuntimeError:
        status["repo-write guard"] = "LIVE"

    for k in TASKS:
        status[f"task:{k}"] = "LIVE" if TASKS[k]["spec"] and TASKS[k]["test"] else "INERT"

    ok_all = True
    for name, state in status.items():
        print(f"  {state:<34} {name}")
        if state.startswith("INERT"):
            ok_all = False
    print("\nRESULT:", "all integrations LIVE" if ok_all else "DEGRADED — see INERT above")
    return 0 if ok_all else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--task", choices=sorted(TASKS), default=None)
    ap.add_argument("--backend", choices=("cloud", "local"), default="cloud")
    ap.add_argument("--max-iter", type=int, default=MAX_ITERATIONS)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    names = [args.task] if args.task else sorted(TASKS)
    results = []
    for name in names:
        print(f"\n[{name}] backend={args.backend} max_iter={args.max_iter}")
        rec = run_task(name, TASKS[name], args.backend, args.max_iter)
        _append_log(rec)
        results.append(rec)

    print(f"\n{'='*70}")
    won = [r for r in results if r["converged"]]
    print(f"CONVERGED: {len(won)}/{len(results)}")
    for r in results:
        mark = "PASS" if r["converged"] else "FAIL"
        print(f"  {mark}  {r['task']:<16} iterations={r['iterations_used']}")
    first_try = [r for r in won if r["iterations_used"] == 1]
    print(f"\n  solved first try      : {len(first_try)}/{len(results)}")
    print(f"  solved AFTER a failure: {len(won) - len(first_try)}/{len(results)}"
          f"   <- this is the number that matters")
    print(f"\nlog -> {RUN_LOG.relative_to(REPO)}")
    return 0 if len(won) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
