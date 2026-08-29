"""Find organs with no nerve: public entrypoints that no production code ever calls.

The defect this exists for was found by hand on 2026-08-28 and took an afternoon:
core/reaction.py is a complete subsystem - guardrails, floors, its own ledger - and
config/reactions.json carries a flag that turns it on. Nothing in any cycle ever calls
it. The flag was true for six hours that day and could not have produced one reaction,
because no code path reaches the function the flag guards.

Import analysis alone would have MISSED it. cockpit/server.py does import core.reaction,
twice, from production code - but only to READ what was already stored. The module is
imported and still never invoked. So this walks CALLS, not imports.

Four other instances of the same shape were found the same day: cycle_profile.defer()
(11 call sites, all inside its own test), the ARMS harness (written, first executed
weeks later), tools/resolve_ideas.py (429 hypotheses, none resolved for 25 days), and
a cockpit panel rendering memory/deferred_batch.json, a file nothing writes.

The habit is: build the organ, be pleased, move on. Nothing asks "who calls me?".
This asks.

READ-ONLY by default. Writing the baseline needs --write, per the project rule that
anything touching a recorded file dry-runs unless told otherwise.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
BASELINE = BASE / "config" / "orphan_baseline.json"
METHOD_VERSION = "orphan_scan/1"

SKIP_DIRS = {
    "venv", "venv312_metta", ".git", "__pycache__", "node_modules",
    ".ruff_cache", ".pytest_cache", "site-packages", ".openclaw", "backups",
}

# A verdict that is not this one means the entrypoint is an orphan.
LIVE = "CALLED_IN_PRODUCTION"
OWN = "CALLED_ONLY_IN_OWN_MODULE"      # the core/reaction.py shape: _once(), _selftest()
TESTS = "CALLED_ONLY_IN_TESTS"          # green tests around code nothing runs
NEVER = "NEVER_CALLED"
STRING = "NAMED_ONLY_AS_A_STRING"       # subprocess / scheduler; reported, never failed

ORPHAN_VERDICTS = (OWN, TESTS, NEVER)


def _is_test(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return "test" in parts or "tests" in parts or parts[-1].startswith("test_")


def _py_files(root: pathlib.Path):
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if any(seg in SKIP_DIRS for seg in rel.split("/")):
            continue
        yield p, rel


def _module_name(rel: str) -> str:
    return rel[:-3].replace("/", ".")


def _parse(p: pathlib.Path):
    """Return an AST, or None. A file we cannot read is a BLIND SPOT, not a clean file."""
    try:
        return ast.parse(p.read_text(encoding="utf-8-sig", errors="replace"), filename=str(p))
    except SyntaxError:
        return None


def _entrypoints(tree: ast.AST) -> list[str]:
    """Public module-level functions and classes. The things another module could call."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                out.append(node.name)
    return out


def _import_bindings(tree: ast.AST, known: set[str]) -> dict[str, tuple[set, set]]:
    """{module: (names bound from it, aliases the module is bound to)} for this file.

    Computed ONCE per file. The first version recomputed this for every (file, module)
    pair and walked the tree each time - a whole-repo run burned ten CPU-minutes without
    producing output. The scan is one pass now.

    Handles `from core.reaction import react`, `import core.reaction as r`, and plain
    `import core.reaction`, where the callable is reached as core.reaction.react."""
    out: dict[str, tuple[set, set]] = {}

    def resolve(name: str) -> str | None:
        if name in known:
            return name
        for k in known:
            if k.endswith("." + name) or name.endswith("." + k):
                return k
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            m = resolve(node.module)
            if m:
                d, md = out.setdefault(m, (set(), set()))
                for a in node.names:
                    # BOTH bindings, and the pair. An aliased import
                    # (from x import scan as _cortex_scan) binds the LOCAL name at
                    # the call site while the entrypoint is known by its ORIGINAL
                    # name, so recording only one of the two makes live wiring
                    # invisible: on 2026-08-29 this tool reported cortex_scanner.scan
                    # as an orphan while it was wired and running.
                    d.add((a.name, a.asname or a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                m = resolve(a.name)
                if m:
                    d, md = out.setdefault(m, (set(), set()))
                    md.add(a.asname or a.name.split(".")[-1])
                    md.add(a.name.split(".")[-1])
    return out


def _calls(tree: ast.AST) -> tuple[set[str], set[tuple[str, str]]]:
    """Every call in this file, ONCE: bare names, and (head, attribute) pairs."""
    names: set[str] = set()
    attrs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name):
            names.add(f.id)
        elif isinstance(f, ast.Attribute):
            v = f.value
            head = v.id if isinstance(v, ast.Name) else (v.attr if isinstance(v, ast.Attribute) else "")
            attrs.add((head, f.attr))
    return names, attrs


_PY_IN_STRING = re.compile(r"[\w\-.]+\.py")


def _filenames_in_strings(trees: dict) -> set[str]:
    """Every *.py named inside a string literal in production code, collected in one
    pass. A module launched by subprocess or named in a scheduler entry is really wired;
    it is reported, never failed on."""
    found: set[str] = set()
    for rel, (tree, is_test) in trees.items():
        if is_test:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.update(_PY_IN_STRING.findall(node.value))
    return found


def scan(root: pathlib.Path, declared_entrypoints: set[str]) -> tuple[list[dict], list[str]]:
    """Returns (rows, unreadable). One row per public entrypoint. Single pass."""
    trees, unreadable = {}, []
    for p, rel in _py_files(root):
        t = _parse(p)
        if t is None:
            unreadable.append(rel)          # named, never silently skipped
            continue
        trees[rel] = (t, _is_test(rel))

    known = {_module_name(rel): rel for rel in trees}
    eps = {rel: _entrypoints(tree) for rel, (tree, _) in trees.items()}
    calls = {rel: _calls(tree) for rel, (tree, _) in trees.items()}
    binds = {rel: _import_bindings(tree, set(known)) for rel, (tree, _) in trees.items()}
    named_in_strings = _filenames_in_strings(trees)

    # invert once: module -> {entrypoint -> (production callers, test callers)}
    hits: dict[str, dict[str, tuple[list, list]]] = {
        rel: {fn: ([], []) for fn in eps[rel]} for rel in trees
    }
    for caller, bmap in binds.items():
        caller_is_test = trees[caller][1]
        cnames, cattrs = calls[caller]
        for mod, (direct, modal) in bmap.items():
            target = known[mod]
            if target == caller:
                continue
            for fn in eps.get(target, ()):
                called = any(loc in cnames for (orig, loc) in direct
                             if orig == fn) or any(
                    h in modal or (h and any(m.endswith(h) for m in modal))
                    for (h, a) in cattrs if a == fn
                )
                if called:
                    hits[target][fn][1 if caller_is_test else 0].append(caller)

    rows = []
    for rel, (tree, is_test) in trees.items():
        if is_test or rel in declared_entrypoints:
            continue
        if not eps[rel]:
            continue
        own_names, own_attrs = calls[rel]
        filename = rel.split("/")[-1]
        for fn in eps[rel]:
            prod, tests = hits[rel][fn]
            if prod:
                verdict = LIVE
            elif filename in named_in_strings:
                verdict = STRING
            elif fn in own_names or any(a == fn for _, a in own_attrs):
                verdict = OWN
            elif tests:
                verdict = TESTS
            else:
                verdict = NEVER
            rows.append({
                "id": f"{rel}::{fn}",
                "module": rel,
                "entrypoint": fn,
                "verdict": verdict,
                "production_callers": sorted(prod),
                "test_callers": sorted(tests),
            })
    return rows, unreadable


def load_baseline() -> dict:
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(BASE))
    ap.add_argument("--report", action="store_true", help="print every orphan and exit 0")
    ap.add_argument("--baseline", action="store_true", help="record today's orphans")
    ap.add_argument("--write", action="store_true", help="required for --baseline to touch disk")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    root = pathlib.Path(args.root).resolve()
    bl = load_baseline()
    declared = set(bl.get("entrypoint_files", []))
    rows, unreadable = scan(root, declared)

    orphans = [r for r in rows if r["verdict"] in ORPHAN_VERDICTS]
    known = set((bl.get("orphans") or {}).keys())
    new = [r for r in orphans if r["id"] not in known]

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"{METHOD_VERSION}  root {root}")
    print(f"  entrypoints scanned {len(rows)}")
    for v in (LIVE, STRING, OWN, TESTS, NEVER):
        if counts.get(v):
            print(f"    {v:<28} {counts[v]}")
    print(f"  declared entrypoint files exempted: {len(declared)}")
    print(f"  orphans in baseline (known debt):   {len(known)}")
    if unreadable:
        print(f"  BLIND SPOTS - files that would not parse: {len(unreadable)}")
        for u in unreadable[:10]:
            print(f"      {u}")

    if args.baseline:
        payload = {
            "method": METHOD_VERSION,
            "recorded": dt.datetime.now(dt.timezone.utc).isoformat(),
            "why": "Organs already built without a nerve. Recorded so NEW ones fail.",
            "entrypoint_files": sorted(declared),
            "orphans": {r["id"]: {"verdict": r["verdict"], "reason": "RECORDED, NOT DIAGNOSED"}
                        for r in orphans},
        }
        if not args.write:
            print(f"\n  dry run - would record {len(orphans)} orphans. Pass --write.")
            return 0
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  wrote {BASELINE} with {len(orphans)} orphans")
        return 0

    if args.report:
        for r in sorted(orphans, key=lambda r: (r["verdict"], r["id"])):
            mark = " " if r["id"] in known else "NEW"
            print(f"  {mark:<3} {r['verdict']:<28} {r['id']}")
        return 0

    if new:
        print(f"\nFAIL: {len(new)} entrypoint(s) built with no production caller:")
        for r in new:
            print(f"  {r['verdict']:<28} {r['id']}")
            if r["test_callers"]:
                print(f"      called only by: {', '.join(r['test_callers'][:3])}")
        print("\nA module nothing calls is not a feature. Wire it in the change that")
        print("adds it, or record it in config/orphan_baseline.json with a reason.")
        return 1

    print("\nOK - no new organ without a nerve.")
    return 0


# ----------------------------------------------------------------------------- selftest
_FIXTURES = {
    # called by production - the only healthy verdict
    "core/live.py": "def serve():\n    return 1\n",
    "runner.py": (
        "from core.live import serve\n"
        "from core.readonly import STORE\n"          # imported, but its entrypoint is not called
        "import subprocess\n"
        "def go():\n"
        "    serve()\n"
        "    subprocess.run(['python', 'jobs/by_string.py'])\n"
    ),
    # THE cockpit/server.py shape: production imports the module and still never invokes it
    "core/readonly.py": "STORE = {}\n\ndef measure():\n    return 2\n",
    # THE core/reaction.py shape: only its own --once path reaches it
    "core/own_only.py": (
        "def react():\n    return 3\n\n"
        "def _once():\n    return react()\n\n"
        'if __name__ == \"__main__\":\n    _once()\n'
    ),
    # green tests wrapped around code no cycle runs
    "core/tested_only.py": "def helper():\n    return 4\n",
    "test/test_tested_only.py": "from core.tested_only import helper\n\ndef test_it():\n    assert helper() == 4\n",
    # nothing anywhere
    "core/never.py": "def sleeps():\n    return 5\n",
    # wired by subprocess rather than by import - real wiring, must not fail
    "jobs/by_string.py": "def main():\n    return 6\n",
    # ALIASED import: real wiring the scanner used to be blind to. The caller binds
    # a local name; the entrypoint is known by its original one. Aliasing is not
    # exotic - it is what you do when two modules both export scan().
    "core/aliased.py": "def scan():\n    return 7\n",
    "aliased_runner.py": (
        "from core.aliased import scan as _outer_scan\n"
        "def go():\n"
        "    return _outer_scan()\n"
    ),
}


def _verdicts(root: pathlib.Path, declared=frozenset()) -> dict:
    rows, _ = scan(root, set(declared))
    return {r["id"]: r["verdict"] for r in rows}


def selftest() -> int:
    import tempfile
    checks, failed = [], 0

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        for rel, src in _FIXTURES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src, encoding="utf-8")
        v = _verdicts(root)

        def want(vid, expected, why):
            nonlocal failed
            got = v.get(vid, "<missing>")
            ok = got == expected
            if not ok:
                failed += 1
            checks.append((ok, why, f"{vid} -> {got}"))

        want("core/live.py::serve", LIVE, "a function production calls is live")
        want("core/readonly.py::measure", NEVER,
             "imported by production but never invoked is STILL an orphan")
        want("core/own_only.py::react", OWN,
             "reachable only by its own --once path is an orphan")
        want("core/tested_only.py::helper", TESTS,
             "called only by a test is an orphan, however green the test")
        want("core/never.py::sleeps", NEVER, "nothing anywhere is an orphan")
        want("jobs/by_string.py::main", STRING,
             "named in a subprocess string is wiring, not an orphan")
        want("core/aliased.py::scan", LIVE,
             "wiring through an ALIASED import is live, not an orphan")

        # negative control: the baseline must silence a KNOWN orphan and nothing else
        rows, _ = scan(root, set())
        orphans = {r["id"] for r in rows if r["verdict"] in ORPHAN_VERDICTS}
        known = {"core/never.py::sleeps"}
        new = orphans - known
        ok = "core/never.py::sleeps" not in new and "core/tested_only.py::helper" in new
        failed += 0 if ok else 1
        checks.append((ok, "a recorded orphan stops failing; an unrecorded one does not",
                       f"new={sorted(new)}"))

        # a file that will not parse must be NAMED, never quietly skipped
        (root / "broken.py").write_text("def (:\n", encoding="utf-8")
        _, unreadable = scan(root, set())
        ok = "broken.py" in unreadable
        failed += 0 if ok else 1
        checks.append((ok, "an unparseable file is a named blind spot, not a clean file",
                       f"unreadable={unreadable}"))

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok:
            print(f"         {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
