# -*- coding: utf-8 -*-
"""test/test_only_openclaw_carries_its_name.py — nothing that is not OpenClaw
carries OpenClaw's name (C-TURN-1 Part 8c; Emil R34: the finder that "carried
OpenClaw's name" never called OpenClaw).

Every tracked CODE file (.py .bat .ps1 .cmd) whose path contains "openclaw" must
call OpenClaw — its CLI (`openclaw ...` / openclaw.mjs) or its gateway — or, for
a test, import a module that does. Documents and data (reports, docs, JSON) are
not code and cannot call anything.

THE ONE EXCEPTION is openclaw_queue/, the directory the nightly cycle's axis feed
writes to (agents/axis/axis_feed.py) and nine modules read; it is renamed only in
a later command that changes every reader and writer together (C-TURN-1 8b).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODE = (".py", ".bat", ".ps1", ".cmd")
EXCEPT = ("openclaw_queue/",)
CALLS = re.compile(r"openclaw\.mjs|openclaw_cmd\(|\[\"openclaw\"|\"openclaw\",|\bopenclaw (browser|agent|gateway|config|models)\b"
                   r"|127\.0\.0\.1:18789|localhost:18789")


def calls_openclaw(path: Path, seen=None) -> bool:
    src = path.read_text(encoding="utf-8", errors="replace")
    if CALLS.search(src):
        return True
    if path.suffix != ".py":
        return False
    seen = seen or set()
    for n in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(n, ast.ImportFrom) and n.module:
            mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        elif isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        for m in mods:
            f = REPO / (m.replace(".", "/") + ".py")
            if "openclaw" in m and f.exists() and f not in seen:
                seen.add(f)
                if calls_openclaw(f, seen):
                    return True
    return False


def offenders(paths, root: Path = REPO) -> list:
    out = []
    for rel in paths:
        if "openclaw" not in rel.lower() or rel.startswith(EXCEPT) or not rel.endswith(CODE):
            continue
        if not calls_openclaw(root / rel):
            out.append(rel)
    return out


def _tracked():
    return subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.splitlines()


def test_every_code_file_named_openclaw_calls_openclaw():
    assert offenders(_tracked()) == []


def test_mutation_a_file_named_openclaw_that_only_uses_requests_fails(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "openclaw_x.py").write_text("import requests\nrequests.get('https://example.org')\n",
                                                       encoding="utf-8")
    assert offenders(["scripts/openclaw_x.py"], tmp_path) == ["scripts/openclaw_x.py"]


def test_the_searcher_counts_as_calling_openclaw():
    assert calls_openclaw(REPO / "scripts" / "openclaw_search.py")
    assert calls_openclaw(REPO / "test" / "test_openclaw_search.py")


def test_openclaw_queue_is_the_only_exception():
    assert EXCEPT == ("openclaw_queue/",)
