# -*- coding: utf-8 -*-
"""test/test_no_outside_language_model.py — a test keeps outside language models out
(C-CLOUD-1 Step 4, 3 Oct 2026).

THE RULE (Emil, R45): no file of the system names the host of an outside language model or
imports an outside model SDK. A REFUSAL looks like this test failing with the file and the
line. The forbidden fallback is a flag that switches a backend off while its code stays.

SCOPE, decided: every tracked *.py and config file (json, yaml, toml, bat, ps1, cmd) outside
venvs, test/, claude/reports/, docs/ and runtime data. test/ is out on purpose: the refusal
tests and the secret-redaction tests must name a host to prove they refuse or mask it.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

QUOTE = ("„Нали нямаше да имаме външни LLM-и… и щяхме да работим само с OpenClaw?\" — "
         "„Защо някой друг да мисли вместо мозъкът на системата?\"")

# host -> (ruling, Emil's words)
HOSTS = {h: ("R45", QUOTE) for h in (
    "api.groq.com", "openrouter.ai", "generativelanguage.googleapis.com", "integrate.api.nvidia.com",
    "api.cerebras.ai", "api.openai.com", "api.anthropic.com", "api.mistral.ai")}
SDKS = {m: ("R45", QUOTE) for m in ("openai", "anthropic", "groq", "google.generativeai", "mistralai")}

CONFIG = (".json", ".yaml", ".yml", ".toml", ".bat", ".ps1", ".cmd")
EXCLUDED = ("test/", "claude/reports/", "docs/", "memory/", "output/", "data/", "cortex_memory/", "snapshots/",
            "news/", "logs/")
HOST_RE = re.compile("|".join(re.escape(h) for h in HOSTS))


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split("\n")
    keep = []
    for f in out:
        if not f or f.startswith(EXCLUDED) or not (REPO / f).exists():
            continue
        if f.endswith(".py") or f.endswith(CONFIG):
            keep.append(f)
    # tracked .py under memory/ is code, not data
    keep += [f for f in out if f.startswith("memory/") and f.endswith(".py") and (REPO / f).exists()]
    return keep


def findings(rel: str, text: str) -> list[str]:
    hits = [f"{rel}:{i}: names {m.group(0)} ({HOSTS[m.group(0)][0]})"
            for i, line in enumerate(text.splitlines(), 1) for m in HOST_RE.finditer(line)]
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return hits
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods = [n.module]
            for m in mods:
                for sdk in SDKS:
                    if m == sdk or m.startswith(sdk + "."):
                        hits.append(f"{rel}:{n.lineno}: imports {m} ({SDKS[sdk][0]})")
    return hits


def scan(files) -> list[str]:
    out = []
    for f in files:
        out += findings(f, (REPO / f).read_text(encoding="utf-8-sig", errors="replace"))
    return out


def test_no_file_names_an_outside_model_host_or_imports_its_sdk():
    bad = scan(tracked())
    assert not bad, "outside language model in the system (R45):\n  " + "\n  ".join(bad)


def test_the_scan_examines_the_system():
    files = tracked()
    assert len(files) > 300 and "core/groq_backend.py" in files and "config/network_allowlist.json" in files


def test_every_pattern_carries_the_ruling_and_the_quote():
    assert all(v == ("R45", QUOTE) for v in list(HOSTS.values()) + list(SDKS.values()))


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_an_outside_url_in_a_core_file_fails():
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    src += '\nGROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"\n'
    assert findings("core/groq_backend.py", src), "the line above must be found"


def test_mutation_an_sdk_import_fails():
    assert findings("core/x.py", "import openai\n")
    assert findings("core/x.py", "from anthropic import Anthropic\n")
    assert findings("core/x.py", "import google.generativeai as genai\n")
    assert not findings("core/x.py", "import json\nfrom core import llm_door\n")
