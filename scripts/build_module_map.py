#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/build_module_map.py — what every tracked module reads, writes and imports.

WHY THIS EXISTS
---------------
The system has been reasoned about from notes and from summaries. This derives the
same picture from the code itself: for every tracked .py file, what it READS, what it
WRITES, who imports it, whether the nightly cycle can reach it, and how big it is.

AST, NOT GREP. A grep for `open(` finds the word; it cannot tell `open(PATH)` from
`open(f"{d}/{name}")`, and it cannot resolve PATH back to BASE / "memory" / "x.json".
This walks the tree and resolves module-level path constants.

UNRESOLVED IS THE INTERESTING CATEGORY, NOT AN ERROR.
Where a path is built at runtime — an f-string, a loop variable, an attribute — it is
recorded as UNRESOLVED together with the source expression, never guessed and never
dropped. Those are precisely the reads the dependency graph cannot see, and precisely
where core/notary.py's _age_state() finds an empty inputs list and returns FULL trust.
A map that quietly omitted them would reproduce the bug it is meant to expose.

    venv\\Scripts\\python.exe scripts/build_module_map.py
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRY = "fast_cycle_runner.py"
OUT_JSON = REPO / "docs" / "MODULE_MAP.json"
OUT_MD = REPO / "docs" / "MODULE_MAP.md"

READ_METHODS = {"read_text", "read_bytes"}
WRITE_METHODS = {"write_text", "write_bytes"}
WRITE_MODES = ("w", "a", "x", "+")


def tracked_py() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                         capture_output=True, text=True, encoding="utf-8")
    return [p for p in out.stdout.splitlines() if p.strip()]


def read_src(rel: str) -> str:
    # utf-8-sig: at least one tracked file carries a BOM, and plain utf-8 makes
    # ast.parse raise on line 1 — a scanner that treats that as "nothing here"
    # silently drops the file.
    return (REPO / rel).read_text(encoding="utf-8-sig", errors="replace")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _expr(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return f"<{type(node).__name__}>"


# Idioms that all denote the repository root. Every module in this repo opens with
# one of them — Path(__file__).resolve().parents[N], or CORTEX_BASE from the
# environment — and without recognising them NOTHING resolves: `BASE / "memory" /
# "x.json"` fails on its left operand and the whole path is reported UNRESOLVED.
# Measured while writing this: treating them as opaque gave 25 resolved reads out of
# 1038 path operations, which would have described the repo as almost entirely
# dynamic. That was the tool being wrong, not the code.
_ROOT_MARKERS = ("__file__", "CORTEX_BASE")
ROOT = ""          # sentinel: the repo root, joins as a prefix of nothing


def _is_root_idiom(node: ast.AST) -> bool:
    try:
        src = ast.unparse(node)
    except Exception:
        return False
    return any(m in src for m in _ROOT_MARKERS)


def resolve(node: ast.AST, consts: dict, depth: int = 0):
    """Return a literal path string, or None if it cannot be resolved statically.

    The repo root resolves to "" so that `BASE / "memory" / "x.json"` yields
    "memory/x.json" — a repo-relative path, which is what every consumer wants.
    """
    if depth > 8 or node is None:
        return None
    if _is_root_idiom(node):
        return ROOT
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return resolve(consts.get(node.id), consts, depth + 1) if node.id in consts else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = resolve(node.left, consts, depth + 1)
        right = resolve(node.right, consts, depth + 1)
        if left is not None and right is not None:
            if left == ROOT:
                return right.lstrip("/")
            return f"{left.rstrip('/')}/{right.lstrip('/')}"
        return None
    if isinstance(node, ast.Call):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if name in ("Path", "PurePath") and node.args:
            return resolve(node.args[0], consts, depth + 1)
        if name == "join" and node.args:            # os.path.join(a, b, ...)
            parts = [resolve(a, consts, depth + 1) for a in node.args]
            return "/".join(p.strip("/") for p in parts) if all(p is not None for p in parts) else None
        if name in ("resolve", "absolute", "expanduser"):
            return resolve(f.value, consts, depth + 1) if isinstance(f, ast.Attribute) else None
    return None


def norm(p: str | None) -> str | None:
    """Make a resolved path repo-relative and forward-slashed, or drop it if it is
    plainly not a repo path (a URL, a bare format string)."""
    if not p:
        return None
    s = p.replace("\\", "/").strip()
    if s.startswith(("http://", "https://", "ftp://")) or "{" in s:
        return None
    if Path(s).is_absolute():
        try:
            s = Path(s).resolve().relative_to(REPO).as_posix()
        except Exception:
            return None                       # absolute, but outside the repo
    while s.startswith("./"):                 # NOT lstrip("./") — that eats leading
        s = s[2:]                             # chars from a SET and mangles paths
    s = s.strip("/")
    # A bare name with no separator and no extension is a variable's value, not a
    # path we can vouch for.
    if not s or ("/" not in s and "." not in s):
        return None
    return s


def _assigns(nodes) -> dict:
    """NAME = <expr> found anywhere in `nodes`."""
    consts: dict = {}
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = sub.value
            elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name) \
                    and sub.value:
                consts[sub.target.id] = sub.value
    return consts


def module_consts(tree: ast.AST) -> dict:
    """Module-level NAME = <expr>, so BASE / "memory" / "x.json" can be followed."""
    return _assigns(tree.body)


def scopes(tree: ast.AST):
    """(node_list, extra_consts) for module level and for each function body.

    FUNCTION LOCALS MATTER, and leaving them out was measurably wrong: with only
    module-level constants the map reported 705 unresolved paths, 417 of them bare
    local names like `proposals_path` — which are assigned two lines above the write,
    from BASE_DIR and a literal. Calling those "dynamic" would have inflated the one
    category the map exists to make trustworthy.
    """
    yield tree.body, {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n.body, _assigns(n.body)


# ---------------------------------------------------------------------------
# Per-module analysis
# ---------------------------------------------------------------------------

def analyse(rel: str) -> dict:
    try:
        tree = ast.parse(read_src(rel))
    except SyntaxError as e:
        return {"module": rel, "parse_error": f"{e.msg} (line {e.lineno})",
                "reads": [], "writes": [], "unresolved": [], "imports": [], "loc": 0}

    mconsts = module_consts(tree)
    reads, writes = set(), set()
    unresolved_by_line: dict = {}
    imports: set = set()
    state = {"consts": mconsts}

    def record(target: ast.AST, kind: str, how: str):
        got = norm(resolve(target, state["consts"]))
        line = getattr(target, "lineno", None)
        if got:
            (reads if kind == "read" else writes).add(got)
            unresolved_by_line.pop((line, kind), None)   # a later scope resolved it
        elif (line, kind) not in unresolved_by_line:
            unresolved_by_line[(line, kind)] = {
                "kind": kind, "how": how, "expr": _expr(target)[:160], "line": line}

    def scan(nodes):
        for root in nodes:
            for n in ast.walk(root):
                if isinstance(n, ast.Import):
                    imports.update(a.name for a in n.names)
                elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                    imports.add(n.module)
                elif isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Name) and f.id == "open" and n.args:
                        mode = ""
                        if len(n.args) > 1 and isinstance(n.args[1], ast.Constant):
                            mode = str(n.args[1].value)
                        for kw in n.keywords:
                            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                                mode = str(kw.value.value)
                        kind = "write" if any(c in mode for c in WRITE_MODES) else "read"
                        record(n.args[0], kind, f"open(mode={mode or 'r'})")
                    elif isinstance(f, ast.Attribute):
                        if f.attr in READ_METHODS:
                            record(f.value, "read", f".{f.attr}()")
                        elif f.attr in WRITE_METHODS:
                            record(f.value, "write", f".{f.attr}()")
                        elif f.attr == "open" and not (
                                isinstance(f.value, ast.Name)
                                and f.value.id in ("os", "io", "gzip", "codecs")):
                            mode = ""
                            if n.args and isinstance(n.args[0], ast.Constant):
                                mode = str(n.args[0].value)
                            kind = ("write" if any(c in mode for c in WRITE_MODES)
                                    else "read")
                            record(f.value, kind, f"Path.open(mode={mode or 'r'})")
                        elif f.attr in ("replace", "rename") and n.args and                                 isinstance(f.value, ast.Name) and f.value.id == "os":
                            record(n.args[-1], "write", f"os.{f.attr}()")
                        elif f.attr in ("move", "copy2", "copy", "copyfile") and                                 len(n.args) >= 2:
                            record(n.args[1], "write", f"shutil.{f.attr}()")
                    if isinstance(f, ast.Name) and f.id == "__import__" and n.args and                             isinstance(n.args[0], ast.Constant):
                        imports.add(str(n.args[0].value))

    # Module scope first, then each function with its own locals merged in. A path
    # left unresolved by the module pass can be resolved by the function pass; record()
    # drops the earlier UNRESOLVED entry when that happens.
    for body, extra in scopes(tree):
        state["consts"] = {**mconsts, **extra}
        scan(body)

    code_lines = sum(1 for ln in read_src(rel).splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))

    return {"module": rel, "reads": sorted(reads), "writes": sorted(writes),
            "unresolved": sorted(unresolved_by_line.values(),
                                 key=lambda u: (u["line"] or 0, u["kind"])),
            "imports": sorted(imports), "loc": code_lines}


# ---------------------------------------------------------------------------
# Reachability from the nightly entry point
# ---------------------------------------------------------------------------

def mod_to_rel(dotted: str) -> str | None:
    for cand in (dotted.replace(".", "/") + ".py",
                 dotted.replace(".", "/") + "/__init__.py"):
        if (REPO / cand).exists():
            return cand
    return None


def reachable(by_mod: dict) -> set:
    live, frontier = set(), [ENTRY]
    while frontier:
        cur = frontier.pop()
        if cur in live or cur not in by_mod:
            continue
        live.add(cur)
        for imp in by_mod[cur]["imports"]:
            rel = mod_to_rel(imp)
            if rel:
                frontier.append(rel)
    return live


def step_gap(by_mod: dict) -> dict:
    """For each declared cycle step: can the map resolve ANY input for it?

    This is the number the notary turns on. core/notary.py::_age_state() returns FULL
    trust when a step's input list is empty — so a step whose inputs cannot be resolved
    is not merely undocumented, it is maximally trusted.
    """
    import re
    try:
        import sys as _sys
        _sys.path.insert(0, str(REPO))
        from core.cycle_map import STEPS
    except Exception as e:
        return {"error": f"cycle_map unavailable: {type(e).__name__}: {e}"}

    src = read_src(ENTRY)
    beats = [(m.start(), m.group(1)) for m in re.finditer(r'beat\("([^"]+)"', src)]
    region = {}
    for i, (pos, name) in enumerate(beats):
        region[name] = src[pos: beats[i + 1][0] if i + 1 < len(beats) else len(src)]

    rows = []
    for st in STEPS:
        name = st[0]
        reg = region.get(name, "")
        dotted = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", reg, re.M)) | \
            set(re.findall(r"__import__\(\s*['\"]([\w.]+)", reg))
        mods = {p for p in (mod_to_rel(d) for d in dotted) if p}
        reads, unres = set(), 0
        for p in mods:
            reads |= set(by_mod.get(p, {}).get("reads", []))
            unres += len(by_mod.get(p, {}).get("unresolved", []))
        rows.append({"step": name, "products": len(st[3]) if len(st) > 3 else 0,
                     "modules_seen": len(mods), "resolvable_inputs": len(reads),
                     "unresolved_in_those_modules": unres,
                     "inputs": sorted(reads)})

    zero = [r for r in rows if r["resolvable_inputs"] == 0]
    return {
        "steps_declared": len(rows),
        "steps_with_resolvable_inputs": len(rows) - len(zero),
        "steps_with_zero_resolvable_inputs": len(zero),
        "of_those_that_do_read_but_only_dynamically":
            len([r for r in zero if r["unresolved_in_those_modules"] > 0]),
        "note": ("A step with zero resolvable inputs is where core/notary.py's "
                 "_age_state() sees an empty list and returns FULL trust. The count "
                 "is the size of that fail-open surface."),
        "steps": rows,
    }


def main() -> int:
    mods = [analyse(p) for p in tracked_py()]
    by_mod = {m["module"]: m for m in mods}
    live = reachable(by_mod)

    imported_by: dict = {m: [] for m in by_mod}
    for m in mods:
        for imp in m["imports"]:
            rel = mod_to_rel(imp)
            if rel and rel in imported_by:
                imported_by[rel].append(m["module"])

    for m in mods:
        m["on_live_cycle_path"] = m["module"] in live
        m["imported_by"] = sorted(set(imported_by[m["module"]]))

    doc = {
        "generated_from": ENTRY,
        "method": ("AST. Module-level path constants are followed; paths built at "
                   "runtime are recorded as UNRESOLVED with their source expression, "
                   "never guessed and never omitted."),
        "totals": {
            "modules": len(mods),
            "on_live_cycle_path": sum(1 for m in mods if m["on_live_cycle_path"]),
            "resolved_reads": sum(len(m["reads"]) for m in mods),
            "resolved_writes": sum(len(m["writes"]) for m in mods),
            "unresolved_paths": sum(len(m["unresolved"]) for m in mods),
            "modules_with_unresolved": sum(1 for m in mods if m["unresolved"]),
            "parse_errors": sum(1 for m in mods if m.get("parse_error")),
            "total_loc": sum(m["loc"] for m in mods),
        },
        "step_gap": step_gap(by_mod),
        "modules": sorted(mods, key=lambda m: m["module"]),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(render_md(doc), encoding="utf-8")
    print(json.dumps(doc["totals"], indent=1))
    return 0


def render_md(doc: dict) -> str:
    t = doc["totals"]
    L = ["# Module map", "",
         "Generated by `scripts/build_module_map.py` from the AST of every tracked "
         "`.py` file. Do not hand-edit — regenerate.", "",
         "`UNRESOLVED` means the path is built at runtime and cannot be known "
         "statically. It is the interesting column: those are the reads a dependency "
         "graph cannot see, and where `core/notary.py` finds an empty input list and "
         "returns FULL trust.", "",
         "## Totals", "",
         f"- modules: **{t['modules']}** ({t['total_loc']} code lines)",
         f"- on the live nightly cycle path: **{t['on_live_cycle_path']}**",
         f"- resolved reads: **{t['resolved_reads']}** · resolved writes: "
         f"**{t['resolved_writes']}**",
         f"- UNRESOLVED path expressions: **{t['unresolved_paths']}** across "
         f"**{t['modules_with_unresolved']}** modules",
         f"- parse errors: {t['parse_errors']}", "",
         "## Modules on the live cycle path", "",
         "| module | LOC | reads | writes | unresolved | imported by |",
         "|---|---:|---:|---:|---:|---:|"]
    for m in doc["modules"]:
        if m["on_live_cycle_path"]:
            L.append(f"| `{m['module']}` | {m['loc']} | {len(m['reads'])} | "
                     f"{len(m['writes'])} | {len(m['unresolved'])} | "
                     f"{len(m['imported_by'])} |")
    g = doc.get("step_gap") or {}
    if "steps_declared" in g:
        L += ["", "## The notary's fail-open surface", "",
              f"`core/notary.py::_age_state()` returns FULL trust for a step whose "
              f"input list is empty. So this is not a documentation gap — it is the "
              f"size of the surface where provenance is maximally trusted because "
              f"nothing could be resolved.", "",
              f"- cycle steps declared: **{g['steps_declared']}**",
              f"- with at least one resolvable input: **{g['steps_with_resolvable_inputs']}**",
              f"- with ZERO resolvable inputs: **{g['steps_with_zero_resolvable_inputs']}**",
              f"- of those, steps that DO read files but only through unresolvable "
              f"paths: **{g['of_those_that_do_read_but_only_dynamically']}**", "",
              "| step | products | modules seen | resolvable inputs | unresolved |",
              "|---|---:|---:|---:|---:|"]
        for r in g["steps"]:
            L.append(f"| `{r['step']}` | {r['products']} | {r['modules_seen']} | "
                     f"{r['resolvable_inputs']} | {r['unresolved_in_those_modules']} |")
    L += ["", "## Every unresolved path, with its expression", "",
          "| module | line | kind | how | expression |", "|---|---:|---|---|---|"]
    for m in doc["modules"]:
        for u in m["unresolved"]:
            expr = u["expr"].replace("|", "\\|").replace("\n", " ")
            L.append(f"| `{m['module']}` | {u['line']} | {u['kind']} | "
                     f"`{u['how']}` | `{expr}` |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
