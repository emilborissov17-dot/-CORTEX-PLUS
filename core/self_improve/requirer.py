#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/requirer.py — THE BRAIN WRITES A SPEC. NEVER CODE.

EXPERIMENTAL, not wired into the cycle. Writes only under
experiments/self_improve/specs/ — never production memory/ or snapshots/.

THE SPLIT POINT, READ OUT OF THE PRODUCTION CODE (2026-09-08)
--------------------------------------------------------------
agents/core/self_modifier.py already separates the two jobs and crosses the line
in exactly one place:

    run()                    lines 254-374
      :299-304   the SPEC is UNPACKED from self_observer's proposal —
                 component / problem / solution / measurable_goal / root_cause
      :313       _problem_already_attempted    still spec-side
      :319       evaluate_proposal_alignment   still spec-side
      :334-335   context = _build_context(...)
                 result  = _generate_solution(...)   <-- THE SPLIT POINT
    _generate_solution()     lines 423-512
      :436-448   the prompt turns from describing the problem to demanding
                 "Напиши Python patch"
      :486       call_groq(prompt, max_tokens=1000)  <-- one model does both

Everything before line 335 is specification. Everything after is code
generation. Today the SAME ladder call serves both, so the model that knows this
system best is also the model asked to write Python — and it is measured at 0/3
on closing the write->test->fix loop.

This module owns the first half only. It emits a SPEC and stops.

WHAT IT REFUSES TO DO, AND THE NET BEHIND THE REFUSAL
------------------------------------------------------
It must not emit code. Saying so in a prompt is not enough — that is precisely
the instruction a helpful model satisfies in letter (a "tiny example") while
breaking in spirit. So there is a mechanical net: _reject_code() parses every
free-text field and REFUSES the spec if it parses as Python or carries the
shapes of it (def/import/fences/assignment). A spec carrying code raises
SpecContainsCode; it is never silently cleaned up, because a stripped-out
snippet would hide that the split failed.

FORBIDDEN FALLBACKS, NAMED
  * do NOT strip code out and keep the spec — refusing loudly is the success
    state here;
  * do NOT invent a goal_axis. It must be one of the 24 in
    config/target_config.json, and a spec naming anything else is refused rather
    than mapped to a near neighbour;
  * do NOT fall back to the cloud ladder when the local brain is down. The
    requirer's whole point is WHICH model does this job; a silent upgrade would
    erase the experiment.

    venv\\Scripts\\python.exe core/self_improve/requirer.py --selftest
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET_CONFIG = REPO / "config" / "target_config.json"
JOURNAL = REPO / "memory" / "development_journal.json"
PROPOSALS = REPO / "memory" / "improvement_proposals.json"

# EXPERIMENTAL TREE. Deliberately not memory/ — nothing here may enter the
# record the nightly cycle reads.
SPEC_DIR = REPO / "experiments" / "self_improve" / "specs"

SPEC_FIELDS = ("problem", "root_cause", "desired_change", "success_metric",
               "goal_axis", "allowed_paths")
_FREE_TEXT = ("problem", "root_cause", "desired_change", "success_metric")


class SpecContainsCode(Exception):
    """The brain emitted code. Refused, never cleaned up."""


class SpecInvalid(Exception):
    """The spec is missing a field, or names an axis that does not exist."""


# ---------------------------------------------------------------------------
# the real axes
# ---------------------------------------------------------------------------

def real_axes(path: Path | None = None) -> set:
    """The 24 axis names out of config/target_config.json.

    They live one level down, inside the five goal groups, so this walks rather
    than assuming a flat list. Never invented, never hardcoded here: a copy of a
    declared list goes stale silently.
    """
    doc = json.loads((path or TARGET_CONFIG).read_text(encoding="utf-8"))
    axes = set()
    for group, body in doc.items():
        if group.startswith("_") or not isinstance(body, dict):
            continue
        sub = body.get("axes") if isinstance(body.get("axes"), dict) else {
            k: v for k, v in body.items() if isinstance(v, dict)}
        axes.update(sub)
    return axes


# ---------------------------------------------------------------------------
# the net: no code, at all
# ---------------------------------------------------------------------------

_CODE_MARKERS = (
    re.compile(r"```"),                       # a fenced block
    re.compile(r"^\s*(def|class|import|from)\s+\w", re.M),
    re.compile(r"\b(json\.loads|read_text|write_text|open\s*\(|subprocess)\b"),
    re.compile(r"^\s*#!\s*/usr/bin/env python", re.M),
)


def _looks_like_code(text: str) -> str:
    """'' if clean, else the reason it is not.

    Two independent checks, because either alone is easy to slip past: the
    regexes catch the SHAPES of Python, and ast.parse catches a snippet with none
    of those shapes that is nonetheless a program. A short prose sentence parses
    as an expression statement, so a bare parse is not enough on its own — the
    parse only counts when the text also contains a statement keyword or an
    assignment.
    """
    if not isinstance(text, str):
        return ""
    for rx in _CODE_MARKERS:
        if rx.search(text):
            return f"matches a code marker: {rx.pattern}"
    if "=" in text and "\n" in text:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.FunctionDef,
                                 ast.ClassDef, ast.Import, ast.ImportFrom,
                                 ast.For, ast.While, ast.If)):
                return f"parses as Python ({type(node).__name__})"
    return ""


def _reject_code(spec: dict) -> None:
    for field in _FREE_TEXT:
        why = _looks_like_code(spec.get(field, ""))
        if why:
            raise SpecContainsCode(
                f"field {field!r} contains code — {why}. The requirer emits a "
                f"SPECIFICATION and never an implementation; the spec is refused "
                f"rather than stripped, because a cleaned-up snippet would hide "
                f"that the split failed.")


def validate(spec: dict, axes: set | None = None) -> dict:
    """Refuse anything that is not a well-formed, code-free spec."""
    if not isinstance(spec, dict):
        raise SpecInvalid(f"spec is {type(spec).__name__}, not an object")
    missing = [f for f in SPEC_FIELDS if f not in spec]
    if missing:
        raise SpecInvalid(f"missing field(s): {', '.join(missing)}")

    known = axes if axes is not None else real_axes()
    if spec["goal_axis"] not in known:
        raise SpecInvalid(
            f"goal_axis {spec['goal_axis']!r} is not one of the "
            f"{len(known)} axes in config/target_config.json. It is refused "
            f"rather than mapped to a near neighbour: a spec aimed at an axis "
            f"that does not exist cannot be measured against anything.")

    paths = spec.get("allowed_paths")
    if not isinstance(paths, list) or not paths:
        raise SpecInvalid("allowed_paths must be a non-empty list")
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            raise SpecInvalid(f"allowed_paths carries {p!r}")

    _reject_code(spec)
    return spec


# ---------------------------------------------------------------------------
# the brain
# ---------------------------------------------------------------------------

def _local_brain(prompt: str, max_tokens: int = 700) -> str:
    """The LOCAL model, and only the local model.

    NO CLOUD FALLBACK, deliberately. core.groq_backend.call_groq would answer
    and the spec would look fine — and the experiment, which is about WHICH model
    does this job, would be silently over. If the local brain is down this
    raises, and that is the honest outcome.
    """
    from core.groq_backend import _call_local
    content, _meta = _call_local(prompt, max_tokens)
    return content


def build_prompt(problem: dict, axes: set) -> str:
    """Short and sharp: a small model reads the first lines and stops."""
    return (
        "You are the CORTEX++ requirer. You produce a SPECIFICATION. "
        "You never write code.\n\n"
        "FORBIDDEN: any Python, any snippet, any fenced block, any import or "
        "def. A spec containing code is REFUSED whole — not cleaned up. "
        "Describing WHAT must change is your job; HOW is someone else's.\n\n"
        f"OBSERVED PROBLEM: {str(problem.get('problem',''))[:400]}\n"
        f"ROOT CAUSE (observed): {str(problem.get('root_cause',''))[:300]}\n"
        f"COMPONENT: {problem.get('component','unknown')}\n\n"
        "Return ONLY this JSON, no prose around it:\n"
        "{\n"
        '  "problem": "<one sentence>",\n'
        '  "root_cause": "<one sentence>",\n'
        '  "desired_change": "<what must be true after, in words>",\n'
        '  "success_metric": "<a number that can be recomputed from a file>",\n'
        f'  "goal_axis": "<EXACTLY one of: {", ".join(sorted(axes))}>",\n'
        '  "allowed_paths": ["<repo-relative prefix the change may touch>"]\n'
        "}\n"
    )


def observations(limit: int = 5, journal: Path | None = None,
                 proposals: Path | None = None) -> list:
    """The problem feed self_observer leaves behind. READ-ONLY.

    memory/improvement_proposals.json is where self_observer writes its HIGH
    proposals; the journal is the fallback. Neither is written by this module.
    """
    out = []
    try:
        raw = json.loads((proposals or PROPOSALS).read_text(encoding="utf-8"))
        items = raw.get("proposals", raw) if isinstance(raw, dict) else raw
        out = [p for p in items if isinstance(p, dict)
               and p.get("priority") == "HIGH"][:limit]
    except Exception:
        out = []
    if out:
        return out
    try:
        j = json.loads((journal or JOURNAL).read_text(encoding="utf-8"))
        for _day, entry in sorted(j.items(), reverse=True):
            for rec in (entry.get("patch_executions") or []):
                if rec.get("verdict") in ("FABRICATED", "ZERO", "UNMEASURED"):
                    out.append({"problem": f"patch {rec.get('patch')} reported "
                                           f"{rec.get('verdict')}",
                                "root_cause": rec.get("measurement_why", ""),
                                "component": "unknown"})
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out[:limit]


def require(problem: dict, brain=None, axes: set | None = None) -> dict:
    """One observation -> one validated SPEC. Raises rather than degrading."""
    known = axes if axes is not None else real_axes()
    raw = (brain or _local_brain)(build_prompt(problem, known))

    text = str(raw or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SpecInvalid(f"the brain returned no JSON object: {text[:200]!r}")
    try:
        spec = json.loads(m.group(0))
    except Exception as exc:
        raise SpecInvalid(f"the brain's JSON did not parse: {exc}") from exc

    validate(spec, known)
    spec["_source"] = "requirer/local_brain"
    spec["_observed_problem"] = str(problem.get("problem", ""))[:200]
    return spec


def write_spec(spec: dict, out_dir: Path | None = None) -> Path:
    """Under the EXPERIMENTAL tree. Never memory/, never snapshots/."""
    d = Path(out_dir) if out_dir else SPEC_DIR
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"spec_{stamp}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/self_improve/requirer.py --selftest")
    try:
        axes = real_axes()
        print(f"  config/target_config.json : LIVE ({len(axes)} axes)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  config/target_config.json : INERT ({type(exc).__name__}: {exc})")
        return 1

    print(f"  problem feed              : {len(observations())} HIGH observation(s)")
    print(f"  spec output dir           : {SPEC_DIR.relative_to(REPO)} "
          f"(experimental, not memory/)")

    try:
        from core.groq_backend import _call_local  # noqa: F401
        print("  local brain entry         : LIVE (core.groq_backend._call_local)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  local brain entry         : INERT ({type(exc).__name__}: {exc})")

    ok = True
    good = {"problem": "p", "root_cause": "r", "desired_change": "d",
            "success_metric": "count of rows", "goal_axis": sorted(axes)[0],
            "allowed_paths": ["data_providers/"]}
    try:
        validate(dict(good), axes)
        print("  a clean spec              : accepted")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  a clean spec              : WRONGLY REFUSED ({exc})")
        ok = False

    for label, bad in (("code in a field", dict(good, desired_change="def f():\n    return 1")),
                       ("fenced block", dict(good, problem="```python\nx=1\n```")),
                       ("invented axis", dict(good, goal_axis="NOT_AN_AXIS"))):
        try:
            validate(dict(bad), axes)
            print(f"  {label:<24} : NOT REFUSED — the net is open")
            ok = False
        except (SpecContainsCode, SpecInvalid):
            print(f"  {label:<24} : refused")

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
