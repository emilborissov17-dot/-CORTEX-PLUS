"""Find values copied out of a file that owns them - the copies that cannot know they are copies.

Diagnosis this exists for, 2026-08-29. Every constant that went stale in this repo was a
duplicate of a fact with a real home. 173 lived in config/target_config.json and became
167 there while the literal stayed 173 in prose and in specs. FLAT_EPS = 0.5 was one
absolute number standing in for each series' own scale. F_SELF_PRODUCES retyped a list
that config/cycle_phases.json declares. An import guard restated a split that
test/_script_style.py calls itself the single source of. A glob restated a directory
layout.

Each copy was made once, correctly. Then the original moved. The copy never announced it
had gone stale, because a copy has no way to know it is a copy.

The fix is not to validate copies. It is to have none: read the owner at call time. This
finds the ones that exist so they can be deleted.

Two shapes are caught:
  COPY_OF_CONFIG      a literal in code equal to a value in config/*.json
  FROZEN_AT_IMPORT    a module-level read of a config - correct at import, and a copy
                      for the whole life of the process

READ-ONLY. It never edits anything.
"""

from __future__ import annotations
import argparse, ast, json, pathlib, sys

BASE = pathlib.Path(__file__).resolve().parents[1]
SKIP = {"venv", "venv312_metta", ".git", "__pycache__", "node_modules",
        ".ruff_cache", ".pytest_cache", "site-packages", "backups"}
METHOD_VERSION = "stale_copy_scan/1"

COPY = "COPY_OF_CONFIG"          # the name AND the value line up - real evidence of copying
COINCIDENCE = "VALUE_COINCIDENCE"  # only the value matches; almost always meaningless
FROZEN = "FROZEN_AT_IMPORT"

# Equality of value is NOT evidence of copying. On the first real run this reported
# WEB_INTEL_MAX_AGE_H = 6.0 as "owned by" profiles.day.starts_hour, because both are 6.0,
# and MAX_PROPOSALS = 50 as owned by a web-search maximum. 243 finds, mostly noise.
# A copy is claimed only when the constant's NAME also lines up with the config key, or
# when the value is distinctive enough that coincidence is not a credible explanation.

# Values too common to mean anything. Flagging 0, 1 or "" would bury the real finds.
BORING = {0, 1, -1, 2, 100, 0.0, 1.0, "", "utf-8", "json", True, False, None}
LOADERS = {"load", "loads", "read_text", "read_json", "loadf"}


def _files(root: pathlib.Path):
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if not any(s in rel.split("/") for s in SKIP):
            yield p, rel


def _flatten(doc, trail="") -> dict:
    """{dotted path: value} for every leaf AND every list-of-scalars in a config."""
    out = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.update(_flatten(v, f"{trail}.{k}" if trail else str(k)))
    elif isinstance(doc, list):
        if doc and all(isinstance(x, (str, int, float)) for x in doc):
            out[trail] = doc
        for i, v in enumerate(doc):
            out.update(_flatten(v, f"{trail}[{i}]"))
    else:
        out[trail] = doc
    return out


def config_values(root: pathlib.Path) -> dict:
    """{hashable value: [config paths that own it]}"""
    owners: dict = {}
    for p in sorted((root / "config").glob("**/*.json")) if (root / "config").exists() else []:
        try:
            doc = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            continue          # unreadable config is a blind spot, reported by the caller
        rel = p.relative_to(root).as_posix()
        for path, val in _flatten(doc).items():
            key = tuple(val) if isinstance(val, list) else val
            try:
                hash(key)
            except TypeError:
                continue
            if key in BORING or (isinstance(key, str) and len(key) < 3):
                continue
            owners.setdefault(key, []).append(f"{rel}::{path}")
    return owners


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _name_matches(const_name: str, owner_path: str) -> bool:
    """Does the constant's name line up with the config key it supposedly copies?"""
    key = owner_path.split("::")[-1]
    n = _norm(const_name)
    for seg in key.replace("[", ".").replace("]", ".").split("."):
        if len(seg) >= 4 and (_norm(seg) in n or n in _norm(seg)):
            return True
    return False


def _distinctive(val) -> bool:
    """A value coincidence could not plausibly explain this match."""
    if isinstance(val, (list, tuple)):
        return len(val) >= 2
    if isinstance(val, str):
        return len(val) >= 8
    return False


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return _literal.MISS
_literal.MISS = object()


def _is_config_read(node) -> bool:
    """Does this expression read a FILE at import time?

    A bare load() is not enough - any project function called load() would match, which
    is how the first run reported test placeholders as frozen config. The expression must
    also mention a path or a file, somewhere."""
    has_loader = False
    mentions_file = False
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in LOADERS:
                has_loader = True
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value.lower()
            if v.endswith((".json", ".yaml", ".yml", ".toml", ".txt")) or "/" in v or "\\" in v:
                mentions_file = True
        if isinstance(n, ast.Name) and any(w in n.id.lower() for w in ("path", "file", "cfg", "config", "base")):
            mentions_file = True
        if isinstance(n, ast.Attribute) and any(w in n.attr.lower() for w in ("path", "file", "cfg", "config")):
            mentions_file = True
    return has_loader and mentions_file


def scan(root: pathlib.Path):
    owners = config_values(root)
    rows, unreadable = [], []
    for p, rel in _files(root):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig", errors="replace"), filename=rel)
        except SyntaxError:
            unreadable.append(rel)
            continue
        if rel.startswith("config/"):
            continue
        for node in tree.body:                      # module level only - a copy frozen for the run
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names or node.value is None:
                continue
            if _is_config_read(node.value):
                try:
                    expr = ast.unparse(node.value)
                except Exception:
                    expr = "<expression>"
                rows.append({"verdict": FROZEN, "module": rel, "line": node.lineno,
                             "name": names[0], "owner": "read once at import",
                             "value": expr})     # the real expression, never a fake None
                continue
            val = _literal(node.value)
            if val is _literal.MISS:
                continue
            key = tuple(val) if isinstance(val, list) else val
            try:
                hash(key)
            except TypeError:
                continue
            if key in BORING or (isinstance(key, str) and len(key) < 3):
                continue
            if key in owners:
                paths = owners[key]
                named = [o for o in paths if _name_matches(names[0], o)]
                if named:
                    verdict, owner = COPY, ", ".join(named[:3])
                elif _distinctive(val):
                    verdict, owner = COPY, ", ".join(paths[:3])
                else:
                    verdict, owner = COINCIDENCE, ", ".join(paths[:3])
                rows.append({"verdict": verdict, "module": rel, "line": node.lineno,
                             "name": names[0], "value": val, "owner": owner})
    return rows, unreadable


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(BASE))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = pathlib.Path(a.root).resolve()
    rows, unreadable = scan(root)
    print(f"{METHOD_VERSION}  {root}")
    for v in (COPY, COINCIDENCE, FROZEN):
        n = sum(1 for r in rows if r["verdict"] == v)
        print(f"  {v:<20} {n}")
    if unreadable:
        print(f"  BLIND SPOTS (would not parse): {len(unreadable)}")
    print("\n  VALUE_COINCIDENCE is reported but is NOT a finding - the value matched and\n"
          "  the name did not. Look at COPY_OF_CONFIG and FROZEN_AT_IMPORT.")
    for r in sorted(rows, key=lambda r: (r["verdict"], r["module"])):
        print(f"  {r['verdict']:<20} {r['module']}:{r['line']}  {r['name']} = {r['value']!r}")
        print(f"       owned by {r['owner']}  -> read it at call time, do not keep this copy")
    if not rows:
        print("\n  No copied constants found. Every value is read where it lives.")
    return 0


def selftest() -> int:
    import tempfile
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "config").mkdir()
        (root / "config" / "target_config.json").write_text(json.dumps(
            {"total_weight": 167.0, "axes": ["ENERGY_REVIEW", "WATER_REVIEW"]}), encoding="utf-8")
        (root / "core").mkdir()
        (root / "core" / "a.py").write_text(
            "STARTS_HOUR_UNRELATED = 167.0\n"      # same value, unrelated name
            "TOTAL_WEIGHT = 167.0\n"                       # a copy of a config value
            "AXES = ['ENERGY_REVIEW', 'WATER_REVIEW']\n"    # a copy of a config list
            "TIMEOUT = 45\n"                               # its own number, owned nowhere else
            "RETRIES = 1\n",                               # boring, must not be flagged
            encoding="utf-8")
        (root / "core" / "b.py").write_text(
            "import json, pathlib\n"
            "CFG = json.loads(pathlib.Path('config/target_config.json').read_text())\n",
            encoding="utf-8")
        (root / "core" / "d.py").write_text(
            "def load():\n    return 1\n\nPAGE = load()\n",   # a local load(), no file
            encoding="utf-8")
        (root / "core" / "c.py").write_text(
            "def f():\n    TOTAL_WEIGHT = 167.0\n    return TOTAL_WEIGHT\n",  # inside a function
            encoding="utf-8")
        rows, unreadable = scan(root)
        ids = {(r["module"], r["name"], r["verdict"]) for r in rows}

        want(("core/a.py", "TOTAL_WEIGHT", COPY) in ids,
             "a literal equal to a config value is named as a copy, with its owner")
        want(("core/a.py", "AXES", COPY) in ids,
             "a retyped list is a copy too - this is the F_SELF_PRODUCES shape")
        want(("core/a.py", "TIMEOUT", COPY) not in ids,
             "a number no config owns is left alone")
        want(("core/a.py", "RETRIES", COPY) not in ids,
             "1 is not evidence of anything and is never flagged")
        want(("core/a.py", "STARTS_HOUR_UNRELATED", COINCIDENCE) in ids,
             "same value + unrelated name is VALUE_COINCIDENCE, not a copy - the 243 lesson")
        want(("core/a.py", "STARTS_HOUR_UNRELATED", COPY) not in ids,
             "and it is never counted as a copy")
        want(("core/b.py", "CFG", FROZEN) in ids,
             "a config read at IMPORT time is a copy for the whole process, and is flagged")
        want(not any(r["module"] == "core/d.py" for r in rows),
             "a local function named load() with no file is not a frozen config read")
        want(not any(r["module"] == "core/c.py" for r in rows),
             "a value read inside a function is a call-time read, which is the fix, not the defect")

        (root / "broken.py").write_text("def (:\n", encoding="utf-8")
        _, un2 = scan(root)
        want("broken.py" in un2, "an unparseable file is a named blind spot, not a clean file")

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
