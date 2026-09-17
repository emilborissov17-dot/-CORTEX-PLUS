#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/step_callmap.py — WHAT DOES EACH STEP ACTUALLY RUN?

WHY
----
The cycle is 53 beat() calls in one linear main(). When a step dies, the only
thing on disk is its name. Nothing says which modules that step reaches, so an
autopsy starts by reading 900 lines of runner to find out what "daily_analysis"
even calls.

Fifteen steps dispatch through __import__("mod", fromlist=["fn"]) — including
every step that has died so far. That form is invisible to grep for an import
of the module, which is why this reads the AST instead of the text.

WHAT IT EXTRACTS, per beat() region (from one beat to the next):
  * local imports        import X / from X import Y inside the step body
  * top-level aliases    a name bound by a module-level import and then called
  * __import__ dispatch  __import__("mod", fromlist=["fn"])

Each substep is resolved to a file on disk when possible. A step with NO
resolvable substep is reported OPAQUE: the map cannot say what it runs, and
that is a finding, not a blank.

STATIC ONLY. It reads what the file says, not what runs. A step whose work
happens inside a helper defined elsewhere in the runner shows the helper's
imports only if they are in the step's own lines. Under-reporting is the
deliberate direction: an OPAQUE step is a question, an invented substep would
be an answer nobody checked.

    venv/Scripts/python.exe scripts/step_callmap.py --write
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
RUNNER = BASE / "fast_cycle_runner.py"
OUT = BASE / "memory" / "step_callmap.json"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(module: str) -> str | None:
    """Map a dotted module name to a file in this repo, or None."""
    if not module:
        return None
    parts = module.split(".")
    for candidate in (BASE.joinpath(*parts).with_suffix(".py"),
                      BASE.joinpath(*parts) / "__init__.py"):
        if candidate.exists():
            return str(candidate.relative_to(BASE)).replace("\\", "/")
    return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

# Names bound at module level that are NOT substeps of anything: beat() is the
# step marker itself, and the rest are this file's own plumbing.
NOT_A_SUBSTEP = {"beat", "clear", "_clear_heartbeat"}


def is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def module_level_aliases(tree: ast.Module) -> dict[str, tuple[str, str | None]]:
    """{bound_name: (module, symbol)} for imports at module level only.

    Module and symbol are kept APART. Folding them into one dotted string made
    `from memory.heartbeat import beat` resolve as module "memory.heartbeat.beat",
    which is a function, so every one of the 53 regions reported an unresolved
    import that was really the beat marker.
    """
    aliases: dict[str, tuple[str, str | None]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = (a.name, None)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = (node.module, a.name)
    return aliases


def beats(tree: ast.Module) -> list[dict]:
    """Every beat("name", "index") call, in line order."""
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "beat"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Constant)):
            found.append({"name": str(node.args[0].value),
                          "index": str(node.args[1].value),
                          "line": node.lineno})
    return sorted(found, key=lambda b: b["line"])


def _dunder_import(node: ast.Call) -> str | None:
    """__import__("mod", fromlist=["fn"]) -> "mod". This is how 15 steps
    dispatch, and it is invisible to a grep for `import mod`."""
    if not (isinstance(node.func, ast.Name) and node.func.id == "__import__"):
        return None
    if node.args and isinstance(node.args[0], ast.Constant):
        return str(node.args[0].value)
    return None


def substeps_in_region(tree: ast.Module, lo: int, hi: int,
                       aliases: dict[str, tuple[str, str | None]]) -> list[dict]:
    """Everything the lines [lo, hi) reach that we can name."""
    out: list[dict] = []
    seen: set[tuple] = set()

    def add(kind: str, module: str, symbol: str | None, line: int) -> None:
        key = (kind, module, symbol)
        if key in seen:
            return
        seen.add(key)
        out.append({"kind": kind, "module": module, "symbol": symbol,
                    "line": line, "file": resolve(module),
                    "stdlib": is_stdlib(module)})

    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is None or not (lo <= line < hi):
            continue

        if isinstance(node, ast.Import):
            for a in node.names:
                add("local_import", a.name, None, line)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                add("local_import", node.module, a.name, line)
        elif isinstance(node, ast.Call):
            mod = _dunder_import(node)
            if mod:
                fromlist = []
                for kw in node.keywords:
                    if kw.arg == "fromlist" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        fromlist = [e.value for e in kw.value.elts
                                    if isinstance(e, ast.Constant)]
                add("dunder_import", mod, ",".join(fromlist) or None, line)
            elif (isinstance(node.func, ast.Name)
                  and node.func.id in aliases
                  and node.func.id not in NOT_A_SUBSTEP):
                mod, sym = aliases[node.func.id]
                add("toplevel_alias", mod, sym or node.func.id, line)
            elif (isinstance(node.func, ast.Attribute)
                  and isinstance(node.func.value, ast.Name)
                  and node.func.value.id in aliases
                  and node.func.value.id not in NOT_A_SUBSTEP):
                mod, _sym = aliases[node.func.value.id]
                add("toplevel_alias", mod, node.func.attr, line)
    return out


def runner_local_functions(tree: ast.Module) -> dict[str, int]:
    """{name: line} for functions defined in the runner itself."""
    return {n.name: n.lineno for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def delegates_in_region(tree: ast.Module, lo: int, hi: int,
                        local_fns: dict[str, int]) -> list[dict]:
    """Calls to functions defined in the runner itself.

    This is what an OPAQUE step turns out to be doing. web_intelligence(1) has
    no import of its own — it calls run_web_intelligence(), defined at module
    level in the same file. So "opaque" means "the work is one hop away and
    here is the hop", not "unknown".
    """
    out, seen = [], set()
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is None or not (lo <= line < hi):
            continue
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in local_fns and node.func.id not in seen
                and node.func.id not in NOT_A_SUBSTEP):
            seen.add(node.func.id)
            out.append({"function": node.func.id,
                        "defined_at": local_fns[node.func.id],
                        "called_at": line})
    return out


def silent_excepts(tree: ast.Module, source: list[str]) -> list[dict]:
    """except ...: pass — a handler that discards the reason.

    NOT fixed here, by instruction. Listed because a step that dies inside one
    of these leaves nothing behind, which is exactly the shape of the four
    silent deaths.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            found.append({
                "line": node.lineno,
                "catches": (ast.unparse(node.type) if node.type else "bare except"),
                "source": source[node.lineno - 1].strip(),
            })
    return sorted(found, key=lambda h: h["line"])


# ---------------------------------------------------------------------------

def build() -> dict:
    source_text = RUNNER.read_text(encoding="utf-8")
    lines = source_text.splitlines()
    tree = ast.parse(source_text)
    aliases = module_level_aliases(tree)
    local_fns = runner_local_functions(tree)
    found = beats(tree)

    steps = []
    for i, b in enumerate(found):
        hi = found[i + 1]["line"] if i + 1 < len(found) else len(lines) + 1
        subs = substeps_in_region(tree, b["line"], hi, aliases)
        steps.append({**b, "ends_line": hi, "substeps": subs,
                      "delegates_to": delegates_in_region(tree, b["line"], hi,
                                                          local_fns),
                      "opaque": not subs})

    total = sum(len(s["substeps"]) for s in steps)
    # stdlib is not "unresolved" — it is resolved, just not in this repo.
    unresolved = [
        {"step": s["name"], "index": s["index"], "line": sub["line"],
         "kind": sub["kind"], "module": sub["module"], "symbol": sub["symbol"]}
        for s in steps for sub in s["substeps"]
        if sub["file"] is None and not sub["stdlib"]
    ]
    opaque = [{"step": s["name"], "index": s["index"], "line": s["line"],
               "delegates_to": s["delegates_to"]}
              for s in steps if s["opaque"]]

    return {
        "_what_this_is": (
            "Static map of what each beat() step reaches, extracted from the AST "
            "of fast_cycle_runner.py by scripts/step_callmap.py. Static only: it "
            "reports what the file says, not what runs."),
        "_opaque_means": (
            "No local import, no top-level alias call and no __import__ dispatch "
            "appears between this beat and the next. The map cannot say what the "
            "step runs. That is a question to answer, not an empty result."),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "runner": str(RUNNER.relative_to(BASE)).replace("\\", "/"),
        "beats": len(steps),
        "total_substeps": total,
        "unresolved_imports": unresolved,
        "opaque_steps": opaque,
        "silent_excepts": silent_excepts(tree, lines),
        "steps": steps,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    data = build()

    print(f"beats                 : {data['beats']}")
    print(f"total substeps        : {data['total_substeps']}")
    by_kind: dict[str, int] = {}
    for s in data["steps"]:
        for sub in s["substeps"]:
            by_kind[sub["kind"]] = by_kind.get(sub["kind"], 0) + 1
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<16} {n}")

    print(f"\nunresolved imports    : {len(data['unresolved_imports'])}")
    for u in data["unresolved_imports"]:
        print(f"  line {u['line']:>5}  {u['step']}({u['index']})  "
              f"{u['kind']}  {u['module']}"
              f"{'.' + u['symbol'] if u['symbol'] else ''}")

    print(f"\nOPAQUE steps          : {len(data['opaque_steps'])}")
    for o in data["opaque_steps"]:
        hops = ", ".join(f"{d['function']}()@{d['defined_at']}"
                         for d in o["delegates_to"]) or "NOTHING NAMEABLE"
        print(f"  line {o['line']:>5}  {o['step']:<32} (index {o['index']:>5})"
              f"  -> {hops}")

    first = min(s["line"] for s in data["steps"])
    last = max(s["ends_line"] for s in data["steps"])
    inside = [h for h in data["silent_excepts"] if first <= h["line"] < last]
    print(f"\nsilent excepts (NOT fixed here): {len(data['silent_excepts'])} in the "
          f"file, {len(inside)} inside step bodies")
    for h in data["silent_excepts"]:
        where = next((s["name"] for s in data["steps"]
                      if s["line"] <= h["line"] < s["ends_line"]), "-")
        print(f"  line {h['line']:>5}  in {where:<30} {h['source'][:44]}")

    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"\n-> {OUT.relative_to(BASE)}")
    else:
        print("\n(dry run — pass --write to save)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
