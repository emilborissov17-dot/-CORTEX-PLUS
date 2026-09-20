#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/ask.py — READ-ONLY answers to three questions that keep being answered wrong.

WHY THIS EXISTS (20 September 2026)
-----------------------------------
Twice in one day a question about this repo was answered with an ad-hoc grep for
ONE literal string, and the empty result was reported as the answer to a BROADER
question. "Does this file contain the string extracted_at" is not "does this
record carry an observation date" — memory/browse_sources/*.json carry data_date,
and the World Bank sections carry a whole map of per-indicator years under
_observed_years. The repo has at least thirteen spellings for that one concept.
A grep for one of them is wrong by construction, and it fails in the most
expensive direction: it returns nothing, and nothing reads like an answer.

The fix is not to grep more carefully. It is to make the class of wrong answer
impossible by having exactly one implementation of each question:

    ask.py observation-date <path>      does this record carry an observation
                                        date, under ANY registered spelling
    ask.py readers <path>               which code READS this file
    ask.py callers <dotted.name>        every call site, and whether any live
                                        caller exists outside test/

WHAT EVERY SUBCOMMAND PRINTS, AND WHY IT IS NOT DECORATION
----------------------------------------------------------
Each one states WHAT IT SEARCHED and HOW MANY candidates it examined, before the
answer. An empty answer and a question that could never have returned anything
look identical otherwise, and telling them apart is the entire point:

    SEARCHED: 6 .json files under memory/browse_sources, 13 registered spellings
    EXAMINED: 412 json nodes
    ...
    0 record(s) with no observation date

says something. "(no output)" does not.

THREE THINGS THIS TOOL REFUSES TO DO
------------------------------------
1. It never falls back to a file's mtime for an observation date. An mtime says
   when the bytes were last touched — by a fetch, by a git restore, by a backup
   sweep. A record with no observation date is reported as having none, in words.
2. It never counts a mention in a docstring or a comment as a reader. That exact
   defect was fixed in the quarantine scanner the same day and is not being
   reintroduced here: docstrings are skipped by AST position, comments never
   reach the AST at all.
3. It never matches a path by substring. Segments are compared whole, so
   registry.json does not match feature_registry.json.

READ-ONLY, and structurally so: this module imports nothing that writes, opens
no file for writing, and every path it touches goes through _read().

    venv/Scripts/python.exe tools/ask.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FIELD_NAMES = BASE / "config" / "field_names.json"

# Aligned with pytest.ini norecursedirs and test/test_ci_contract.SKIP_PARTS. A
# scanner that walks a vendored virtualenv reports somebody else's code as ours;
# that already happened here on 19 Sep 2026.
SKIP_PARTS = {"venv", "venv_train", "venv312_metta", "__pycache__", ".git",
              ".claude", "OLD", "LEGACY", "_to_delete_gitlock", "quarantine",
              "Broker-bot", "_ARCHIVE", "node_modules"}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _py_files(base: Path):
    for f in sorted(base.rglob("*.py")):
        if any(part in SKIP_PARTS for part in f.parts):
            continue
        yield f


def _rel(p: Path, base: Path | None = None) -> str:
    try:
        return str(p.relative_to(base or BASE)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


# ── the registry ────────────────────────────────────────────────────────────

def load_spellings(concept: str = "OBSERVATION_DATE", path: Path | None = None) -> list:
    """The registered spellings of a concept, from config/field_names.json.

    RAISES rather than returning [] when the registry is missing or unreadable.
    An empty spelling list would make every record answer "no observation date"
    — a confident wrong answer of exactly the shape this tool exists to prevent.
    """
    p = path or FIELD_NAMES
    try:
        doc = json.loads(_read(p))
    except Exception as exc:
        raise SystemExit(f"ask.py: cannot read the field registry {_rel(p)}: "
                         f"{type(exc).__name__}: {exc}")
    try:
        entries = doc["concepts"][concept]["spellings"]
    except (KeyError, TypeError):
        raise SystemExit(f"ask.py: {_rel(p)} registers no concept {concept!r}")
    if not entries:
        raise SystemExit(f"ask.py: {concept} has no spellings in {_rel(p)}")
    return entries


# ── dates ───────────────────────────────────────────────────────────────────

def parse_value(value, shape: str):
    """(datetime, how) for a registered value, or (None, why not).

    Every shape is parsed explicitly. An unrecognised value is None and says so;
    it is never guessed at and never replaced by a file's mtime.
    """
    if value is None:
        return None, "value is null"
    if shape == "year_map":
        if not isinstance(value, dict):
            return None, "year_map is not an object"
        parsed = [parse_value(v, "year")[0] for v in value.values()]
        parsed = [d for d in parsed if d]
        if not parsed:
            return None, "no readable year in the map"
        # The oldest, because a composite is as old as its oldest number.
        return min(parsed), f"oldest of {len(parsed)} year(s)"
    if shape == "year":
        m = re.fullmatch(r"\s*(\d{4})(\.0+)?\s*", str(value))
        if not m:
            return None, f"not a year: {value!r}"
        # 31 December: a year-resolution observation is not more precise.
        return datetime(int(m[1]), 12, 31, tzinfo=timezone.utc), "year -> 31 Dec"
    if shape == "year_fraction":
        m = re.fullmatch(r"\s*(\d{4})\.(\d+)\s*", str(value))
        if not m:
            return None, f"not a year fraction: {value!r}"
        frac = float("0." + m[2])
        day = min(365, int(frac * 365))
        return (datetime(int(m[1]), 1, 1, tzinfo=timezone.utc)
                + _days(day)), "year fraction"
    if shape in ("iso_date", "iso_datetime"):
        s = str(value).strip()
        if not s:
            return None, "empty string"
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
            if not m:
                return None, f"not an ISO date: {value!r}"
            dt = datetime(int(m[1]), int(m[2]), int(m[3]))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, shape
    return None, f"unknown shape {shape!r}"


def _days(n: int):
    from datetime import timedelta
    return timedelta(days=n)


def _age_days(dt: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


# ── observation-date ────────────────────────────────────────────────────────

def _walk(node, path=""):
    """Every (json-path, key, value) pair in a document, depth first."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}/{k}"
            yield here, k, v
            yield from _walk(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            here = f"{path}[{i}]"
            yield from _walk(v, here)


def observation_date(target: Path, concept: str = "OBSERVATION_DATE",
                     registry: Path | None = None, now: datetime | None = None) -> dict:
    spellings = {e["spelling"]: e for e in load_spellings(concept, registry)}
    if target.is_dir():
        files = [f for f in sorted(target.rglob("*.json"))
                 if not any(p in SKIP_PARTS for p in f.parts)]
        searched = f"{len(files)} .json file(s) under {_rel(target)}"
    else:
        files = [target]
        searched = _rel(target)

    nodes = 0
    records = []
    for f in files:
        try:
            doc = json.loads(_read(f))
        except Exception as exc:
            records.append({"file": _rel(f), "unreadable":
                            f"{type(exc).__name__}: {exc}", "hits": []})
            continue
        hits = []
        for jpath, key, value in _walk(doc):
            nodes += 1
            if key not in spellings:
                continue
            entry = spellings[key]
            dt, how = parse_value(value, entry.get("shape", "iso_date"))
            hits.append({"spelling": key, "at": jpath or "/", "value": value,
                         "parsed": how if dt else None,
                         "age_days": round(_age_days(dt, now), 1) if dt else None,
                         "observed": dt.date().isoformat() if dt else None,
                         "unparsable": None if dt else how,
                         "caveat": entry.get("caveat")})
        records.append({"file": _rel(f), "hits": hits})

    return {"concept": concept, "searched": searched,
            "spellings": sorted(spellings), "nodes_examined": nodes,
            "records": records}


def print_observation_date(res: dict) -> None:
    print(f"SEARCHED: {res['searched']}, "
          f"{len(res['spellings'])} registered spelling(s) of {res['concept']}")
    print(f"          {', '.join(res['spellings'])}")
    print(f"EXAMINED: {res['nodes_examined']} json node(s) in "
          f"{len(res['records'])} file(s)")
    print()
    without = 0
    for rec in res["records"]:
        if rec.get("unreadable"):
            print(f"  {rec['file']}\n      UNREADABLE: {rec['unreadable']}")
            without += 1
            continue
        if not rec["hits"]:
            without += 1
            print(f"  {rec['file']}")
            print(f"      NO OBSERVATION DATE under any registered spelling.")
            print(f"      Its mtime is NOT used as one, and is not reported here.")
            continue
        print(f"  {rec['file']}")
        for h in rec["hits"]:
            if h["age_days"] is None:
                print(f"      {h['spelling']} at {h['at']} = {h['value']!r} "
                      f"-> UNPARSABLE ({h['unparsable']}); no age")
            else:
                print(f"      {h['spelling']} at {h['at']} = {h['value']!r} "
                      f"-> observed {h['observed']}, {h['age_days']} days old")
            if h["caveat"]:
                print(f"          CAVEAT: {h['caveat'][:200]}")
    print()
    print(f"{len(res['records']) - without} file(s) carry an observation date; "
          f"{without} do not.")


# ── readers ─────────────────────────────────────────────────────────────────

def _segments(s: str) -> list:
    return [seg for seg in str(s).replace("\\", "/").split("/") if seg]


def _matches_path(literal: str, want: list, directory: bool = False) -> bool:
    """True when `literal` names the wanted path, segment for segment.

    WHOLE SEGMENTS ONLY. 'registry.json' must not match 'feature_registry.json',
    which a substring test does and which is how a reader list quietly acquires
    files that read something else.

    For a FILE the wanted segments must end the literal, or the literal must be
    the bare basename — a file is named, not descended into. For a DIRECTORY the
    run may appear anywhere, because a literal naming a file INSIDE the directory
    is a use of the directory.
    """
    got = _segments(literal)
    if not got or not want:
        return False
    n = len(want)
    if not directory and got == want[-1:]:
        return True                  # the bare basename, e.g. "x.jsonl"
    if len(got) < n:
        return False
    if directory:
        return any(got[i:i + n] == want for i in range(len(got) - n + 1))
    return got[-n:] == want


def _scope_nodes(scope):
    """Every node of one scope, not descending into a nested function or class.

    A module's own statements are its scope; a function's body is another. The
    two are walked separately so that a name bound in one cannot classify a use
    in the other.
    """
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            continue
        yield child
        yield from _scope_nodes(child)


def _expr_segments(node) -> list | None:
    """The path segments a single expression names, or None if it names none.

    A path in this repo is rarely one string. It is usually built a segment at a
    time — `REPO / "memory" / "browse_sources"` — so a matcher that only looks at
    individual string literals sees "memory" and "browse_sources" separately and
    matches neither. That was this tool's own first answer for
    `readers memory/browse_sources`: zero readers, for a directory five modules
    write to. The empty result looked exactly like an answer, which is the defect
    this file exists to prevent, reproduced inside the fix for it.

    Constant leaves contribute their own segments in order; a non-constant
    operand (BASE, REPO, self.root) contributes nothing, which is right — it is
    the repo root under a different name.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _segments(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _expr_segments(node.left) or []
        right = _expr_segments(node.right) or []
        return (left + right) or None
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "joinpath"):
        out = []
        for a in node.args:
            out += _expr_segments(a) or []
        return out or None
    return None


def _path_nodes(tree, skip: set, want: list, directory: bool):
    """Every expression in the tree that names the wanted path, outermost first.

    Docstrings are skipped by position, so prose that happens to quote a path is
    never a reader. A node inside an already-matched chain is not yielded twice.
    """
    claimed = set()
    for node in ast.walk(tree):
        if id(node) in claimed:
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                continue
            if (node.lineno, node.col_offset) in skip:
                continue
        elif not isinstance(node, (ast.BinOp, ast.Call)):
            continue
        segs = _expr_segments(node)
        if not segs or not _matches_path("/".join(segs), want, directory):
            continue
        for inner in ast.walk(node):
            claimed.add(id(inner))
        claimed.discard(id(node))
        yield node


def _docstring_positions(tree) -> set:
    """(lineno, col_offset) of every docstring node, so they can be skipped.

    Comments never reach the AST, so they need no handling; docstrings do, and a
    path named in prose is the single most common false reader.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                c = body[0].value
                out.add((c.lineno, c.col_offset))
        # A bare string statement anywhere is prose too, not a path expression.
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            out.add((node.value.lineno, node.value.col_offset))
    return out


_READ_ATTRS = {"read_text", "read_bytes", "readlines", "readline", "read"}
_WRITE_ATTRS = {"write_text", "write_bytes", "write", "writelines", "unlink",
                "touch", "rename", "replace"}
_NEUTRAL_ATTRS = {"exists", "is_file", "is_dir", "stat", "mkdir", "parent",
                  "name", "resolve", "relative_to", "glob", "rglob", "suffix",
                  "stem", "with_suffix", "as_posix"}


def _mode_of(call: ast.Call) -> str:
    if call.args and len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"


class _Use:
    __slots__ = ("kind", "line", "why")

    def __init__(self, kind, line, why):
        self.kind, self.line, self.why = kind, line, why


def _classify_uses(nodes, names: set, funcs: dict, depth: int = 0) -> list:
    """How ONE SCOPE uses the names bound to the target path.

    SCOPE MATTERS, and the tool learned it the hard way on its own test file.
    Tracking names across a whole module attributes a read to any function that
    happens to reuse the name: `f` is bound to the target in one test and to a
    tmp_path file in another, and a module-wide pass reported the second one's
    `f.read_text()` as a read of the first one's path. A line number that points
    at the wrong line is the rot CLAUDE.md names as the fastest of all.

    Resolves ONE level of indirection inside the same file: a path handed to a
    local helper is classified by what that helper does to its parameter. That
    single level is what separates `_jsonl(REPO / "memory" / "x.jsonl")` — a
    read — from a constant that is only ever written.
    """
    uses = []
    nodes = list(nodes)

    def is_target(node) -> bool:
        """The expression IS the target, or is the target with more path on it.

        `OUT_DIR / f"{key}.json"` is the directory OUT_DIR names, one level down.
        Without this, a module that writes every one of its records through a
        directory constant reads as naming the path and never touching it, which
        is how experiments/browser_scout/scout.py first came back as neither a
        reader nor a writer of the directory it fills every night.
        """
        if isinstance(node, ast.Name):
            return node.id in names
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return is_target(node.left)
        return False

    for node in nodes:
        if isinstance(node, ast.Attribute) and is_target(node.value):
            if node.attr in _READ_ATTRS:
                uses.append(_Use("read", node.lineno, f".{node.attr}()"))
            elif node.attr in _WRITE_ATTRS:
                uses.append(_Use("write", node.lineno, f".{node.attr}()"))
            elif node.attr == "open":
                pass                       # handled at the Call below
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "open" and is_target(f.value):
                mode = _mode_of(node)
                kind = "write" if any(c in mode for c in "wax+") else "read"
                uses.append(_Use(kind, node.lineno, f".open({mode!r})"))
            elif isinstance(f, ast.Name) and f.id == "open" and node.args and is_target(node.args[0]):
                mode = _mode_of(node)
                kind = "write" if any(c in mode for c in "wax+") else "read"
                uses.append(_Use(kind, node.lineno, f"open(..., {mode!r})"))
            elif isinstance(f, ast.Name) and f.id in funcs and depth < 1:
                for i, arg in enumerate(node.args):
                    if not is_target(arg):
                        continue
                    fn = funcs[f.id]
                    if i < len(fn.args.args):
                        pname = fn.args.args[i].arg
                        inner = _classify_uses(ast.walk(fn), {pname}, funcs,
                                               depth + 1)
                        for u in inner:
                            uses.append(_Use(u.kind, node.lineno,
                                             f"{f.id}(...) -> {u.why}"))
    return uses


def _direct_hits(py: Path, want: list, directory: bool = False) -> dict | None:
    """What this file does with the wanted path, or None if it never names it."""
    try:
        src = _read(py)
        tree = ast.parse(src)
    except Exception:
        return None
    skip = _docstring_positions(tree)

    literal_lines, names, params = [], set(), set()
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    matching = list(_path_nodes(tree, skip, want, directory))
    literal_lines = [n.lineno for n in matching]
    matching_ids = {id(n) for n in matching}

    if not literal_lines:
        return None

    def holds_match(expr) -> bool:
        return any(id(c) in matching_ids for c in ast.walk(expr))

    # Names bound to an expression that contains one of those literals — and
    # then, to a fixed point, names bound to an expression mentioning one of
    # THOSE. The second round is not a refinement: core/alarm_bands.py binds the
    # constant at module level and reads through a local rebinding,
    # `p = path or VERIFIED`, so a single pass sees a file that names the path
    # and never reads it, which is precisely the wrong answer.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and holds_match(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    # The fixed point still runs over the whole module, and only to find which
    # PARAMETER DEFAULTS name a target — the uses themselves are scoped below.
    for _round in range(4):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            if not any(isinstance(c, ast.Name) and c.id in names
                       for c in ast.walk(value)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id not in names:
                    names.add(t.id)
                    grew = True
        if not grew:
            break
    # Parameters whose DEFAULT is one of those names: the path reaches the body
    # under a different name, which is how core/card_intake.py reads and writes.
    for fn in funcs.values():
        defaults = list(fn.args.defaults)
        positional = list(fn.args.args)
        # defaults line up with the TAIL of the positional parameters
        for arg, default in zip(positional[len(positional) - len(defaults):],
                                defaults):
            if isinstance(default, ast.Name) and default.id in names:
                params.add(arg.arg)
        for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults):
            if isinstance(default, ast.Name) and default.id in names:
                params.add(arg.arg)

    # ONE PASS PER SCOPE. Module level sees only module-level bindings; each
    # function sees those plus its own, which is what Python does and what stops
    # a name reused in two functions from carrying a read between them.
    def _scope_targets(nodes, seed: set) -> set:
        """Names in ONE scope that hold the target path.

        Seeded with what the scope can see from outside (module constants, a
        parameter whose default is one), then grown to a fixed point over
        rebindings: core/alarm_bands.py reads through `p = path or VERIFIED`, so
        a pass that stops at the constant sees a module that names the path and
        never opens it.
        """
        nodes = list(nodes)
        names_ = set(seed)
        for _round in range(4):
            grew = False
            for node in nodes:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                value = node.value
                if value is None:
                    continue
                if not (holds_match(value)
                        or any(isinstance(c, ast.Name) and c.id in names_
                               for c in ast.walk(value))):
                    continue
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for t in targets:
                    if isinstance(t, ast.Name) and t.id not in names_:
                        names_.add(t.id)
                        grew = True
            if not grew:
                break
        return names_

    module_names = _scope_targets(_scope_nodes(tree), set())
    uses = _classify_uses(_scope_nodes(tree), module_names, funcs)
    for fn in funcs.values():
        fn_params = {a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)
                     if a.arg in params}
        visible = _scope_targets(ast.walk(fn), module_names | fn_params)
        uses += _classify_uses(ast.walk(fn), visible, funcs)
    names = module_names

    # A literal passed straight into a call, with no name in between.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        for i, arg in enumerate(node.args):
            if not holds_match(arg):
                continue
            if isinstance(f, ast.Name) and f.id in funcs:
                fn = funcs[f.id]
                if i < len(fn.args.args):
                    pname = fn.args.args[i].arg
                    for u in _classify_uses(ast.walk(fn), {pname}, funcs, 1):
                        uses.append(_Use(u.kind, node.lineno,
                                         f"{f.id}(...) -> {u.why}"))
            elif isinstance(f, ast.Name) and f.id == "open":
                mode = _mode_of(node)
                uses.append(_Use("write" if any(c in mode for c in "wax+") else "read",
                                 node.lineno, f"open(..., {mode!r})"))
        if isinstance(f, ast.Attribute) and f.attr in (_READ_ATTRS | _WRITE_ATTRS):
            if holds_match(f.value):
                uses.append(_Use("read" if f.attr in _READ_ATTRS else "write",
                                 node.lineno, f".{f.attr}()"))

    return {"file": _rel(py), "literal_lines": sorted(set(literal_lines)),
            "reads": sorted({(u.line, u.why) for u in uses if u.kind == "read"}),
            "writes": sorted({(u.line, u.why) for u in uses if u.kind == "write"})}


def _reading_functions(py: Path, want: list, directory: bool = False) -> set:
    """The names of functions in this file whose body reads the wanted path."""
    try:
        tree = ast.parse(_read(py))
    except Exception:
        return set()
    hit = _direct_hits(py, want, directory)
    if not hit or not hit["reads"]:
        return set()
    lines = {ln for ln, _why in hit["reads"]}
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            if any(node.lineno <= ln <= end for ln in lines):
                out.add(node.name)
    return out


def readers(path: str, base: Path | None = None) -> dict:
    base = base or BASE
    want = _segments(path)
    directory = (base / path).is_dir()
    files = list(_py_files(base))

    direct, writers_only = [], []
    for py in files:
        hit = _direct_hits(py, want, directory)
        if hit is None:
            continue
        hit["file"] = _rel(py, base)
        if hit["reads"]:
            direct.append(hit)
        else:
            writers_only.append(hit)

    # INDIRECT, one level: a module that imports a direct reader and calls the
    # very function whose body does the reading. Not "imports it" — calls it.
    by_module = {}
    for hit in direct:
        py = base / hit["file"]
        fns = _reading_functions(py, want, directory)
        if fns:
            by_module[Path(hit["file"]).stem] = (hit["file"], fns)

    indirect = []
    direct_files = {h["file"] for h in direct}
    for py in files:
        rel = _rel(py, base)
        if rel in direct_files:
            continue
        try:
            tree = ast.parse(_read(py))
        except Exception:
            continue
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name in by_module:
                        imported[a.asname or a.name] = a.name
            elif isinstance(node, ast.Import):
                for a in node.names:
                    tail = a.name.split(".")[-1]
                    if tail in by_module:
                        imported[a.asname or tail] = tail
        if not imported:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in imported):
                mod = imported[node.func.value.id]
                srcfile, fns = by_module[mod]
                if node.func.attr in fns:
                    indirect.append({"file": rel, "line": node.lineno,
                                     "via": f"{srcfile}::{node.func.attr}()"})
                    break

    return {"path": path, "segments": want, "directory": directory,
            "files_searched": len(files),
            "direct": direct, "indirect": indirect, "writers_only": writers_only}


def print_readers(res: dict) -> None:
    kind = "directory" if res.get("directory") else "file"
    print(f"SEARCHED: {res['files_searched']} .py file(s) under {_rel(BASE)}, "
          f"for the whole-segment {kind} path {'/'.join(res['segments'])}")
    print( "          docstrings skipped by AST position; comments never reach "
           "the AST; substrings never match")
    print( "          CODE ONLY: a path reached through a config file — a spec, a "
           "route table — is named nowhere in .py and cannot appear below")
    print(f"EXAMINED: {res['files_searched']} parsed module(s)")
    print()
    print(f"READERS — code that reads it ({len(res['direct'])}):")
    for h in res["direct"] or []:
        where = ", ".join(f"{ln}: {why}" for ln, why in h["reads"][:4])
        print(f"  {h['file']}   [{where}]")
    if not res["direct"]:
        print("  (none)")
    print()
    print(f"READERS, INDIRECT — calls a reading function of a direct reader "
          f"({len(res['indirect'])}):")
    for h in res["indirect"] or []:
        print(f"  {h['file']}:{h['line']}   via {h['via']}")
    if not res["indirect"]:
        print("  (none)")
    print()
    print(f"NAMES IT BUT DOES NOT READ IT ({len(res['writers_only'])}) — "
          f"writers and unclassified uses, listed so the answer can be audited:")
    for h in res["writers_only"] or []:
        w = ", ".join(f"{ln}: {why}" for ln, why in h["writes"][:3]) or "no read/write use found"
        print(f"  {h['file']}   [{w}]")
    if not res["writers_only"]:
        print("  (none)")


# ── callers ─────────────────────────────────────────────────────────────────

def callers(dotted: str, base: Path | None = None) -> dict:
    base = base or BASE
    *mod_parts, func = dotted.split(".")
    module = ".".join(mod_parts)
    mod_file = base.joinpath(*mod_parts).with_suffix(".py") if mod_parts else None

    defined = None
    if mod_file and mod_file.exists():
        try:
            tree = ast.parse(_read(mod_file))
            for node in ast.walk(tree):
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == func):
                    defined = f"{_rel(mod_file, base)}:{node.lineno}"
        except Exception:
            pass

    files = list(_py_files(base))
    hits = []
    for py in files:
        try:
            tree = ast.parse(_read(py))
        except Exception:
            continue
        rel = _rel(py, base)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = (f.attr if isinstance(f, ast.Attribute)
                    else f.id if isinstance(f, ast.Name) else None)
            if name != func:
                continue
            qual = (f"{f.value.id}.{f.attr}" if isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name) else name)
            hits.append({"file": rel, "line": node.lineno, "as": qual,
                         "in_test": rel.startswith("test/") or
                                    Path(rel).name.startswith("test_")})
    # THREE GROUPS, NOT TWO, and the third one produced a false verdict before it
    # existed. `callers core.cadence.audit_specs` answered "every call site is a
    # test, so this function enforces nothing in the running system" while
    # core/cadence.py:265 — load_specs, the live gate — calls it one line away.
    # A call from inside the defining module is not an outside caller and it is
    # not a test; it is the function being used by its own module, and saying so
    # is different from saying nobody uses it.
    home = (defined or "").split(":")[0]
    live = [h for h in hits if not h["in_test"] and h["file"] != home]
    internal = [h for h in hits if not h["in_test"] and h["file"] == home]
    return {"dotted": dotted, "module": module, "function": func,
            "defined_at": defined, "files_searched": len(files),
            "hits": hits, "live_outside_test": live,
            "live_inside_own_module": internal}


def print_callers(res: dict) -> None:
    print(f"SEARCHED: {res['files_searched']} .py file(s) under {_rel(BASE)}, "
          f"for calls named {res['function']!r} (AST call nodes, not text)")
    where = res["defined_at"] or "NOT FOUND — the module or the name does not exist"
    print(f"          definition: {where}")
    print(f"EXAMINED: {res['files_searched']} parsed module(s), "
          f"{len(res['hits'])} matching call site(s)")
    print()
    for h in res["hits"]:
        tag = "test" if h["in_test"] else "LIVE"
        print(f"  [{tag}] {h['file']}:{h['line']}   {h['as']}(...)")
    if not res["hits"]:
        print("  (no call sites at all)")
    print()
    n = len(res["live_outside_test"])
    inside = res.get("live_inside_own_module") or []
    if n:
        print(f"{n} live caller(s) outside test/.")
    elif inside:
        where = ", ".join(f"{h['file']}:{h['line']}" for h in inside[:3])
        print(f"NO caller outside its own module, and {len(inside)} inside it "
              f"({where}). It is reached only through {res['module']}, so ask "
              f"whether THAT entry point is called before concluding anything "
              f"about this one.")
    else:
        print("NO live caller outside test/. Every call site is a test, so this "
              "function enforces nothing in the running system.")


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    rep = {"registry": _rel(FIELD_NAMES), "exists": FIELD_NAMES.exists(),
           "integrations": {}}
    try:
        sp = load_spellings()
        rep["spellings"] = [e["spelling"] for e in sp]
        rep["integrations"]["config/field_names.json"] = (
            f"LIVE - {len(sp)} spelling(s) of OBSERVATION_DATE")
    except SystemExit as exc:
        rep["integrations"]["config/field_names.json"] = f"INERT - {exc}"
    anchor = BASE / "memory" / "browse_sources" / "CLIMATE_GLOBAL_RISK_REVIEW.json"
    rep["integrations"]["memory/browse_sources"] = (
        "LIVE - the anchor record is on disk" if anchor.exists() else
        "INERT - the anchor record is missing; observation-date has nothing to "
        "answer about here")
    return rep


# ── cli ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="ask.py", description="read-only answers about this repo")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("observation-date")
    p1.add_argument("path")
    p1.add_argument("--concept", default="OBSERVATION_DATE")

    p2 = sub.add_parser("readers")
    p2.add_argument("path")

    p3 = sub.add_parser("callers")
    p3.add_argument("dotted")

    args = ap.parse_args(argv)
    if args.selftest:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "observation-date":
        target = Path(args.path)
        if not target.is_absolute():
            target = BASE / args.path
        if not target.exists():
            print(f"ask.py: no such path: {args.path}")
            return 2
        print_observation_date(observation_date(target, args.concept))
        return 0
    if args.cmd == "readers":
        print_readers(readers(args.path))
        return 0
    if args.cmd == "callers":
        print_callers(callers(args.dotted))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
