# -*- coding: utf-8 -*-
"""test/test_no_outside_language_model.py — a test keeps outside language models out
(C-CLOUD-1 Step 4, 3 Oct 2026).

THE RULE (Emil, R45): no file of the system names the host of an outside language model or
imports an outside model SDK. A REFUSAL looks like this test failing with the file and the
line. The forbidden fallback is a flag that switches a backend off while its code stays.

SCOPE, decided: every tracked *.py and config file (json, yaml, toml, bat, ps1, cmd) outside
venvs, test/, claude/reports/, docs/ and runtime data. test/ is out on purpose: the refusal
tests and the secret-redaction tests must name a host to prove they refuse or mask it.

NAMES (C-CLOUD-2 Step 7, R46): an identifier — def, class, assignment target, or a key of a
config JSON — that contains groq / gemini / openrouter / cerebras is refused as well. Exempt by
name, decided: core/redact.py (masks key shapes still on disk), the class-P readers of rows
written before C-CLOUD-1 (NAME_EXEMPT below), the dated record experiments/kimi_duel/results.json
(a past duel is not rewritten), and test/.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

QUOTE = ("„Нали нямаше да имаме външни LLM-и… и щяхме да работим само с OpenClaw?\" — "
         "„Защо някой друг да мисли вместо мозъкът на системата?\"")

# host -> (ruling, Emil's words)
QUOTE_R46 = ("„Ако това е излишно, да се махне… и защо изобщо се ползват имена, които имитират известни "
             "търсачки — това е нелепо.\"")

# host -> (ruling, Emil's words); api.deepseek.com and the deepseek SDK added by Emil's decision on
# C-CLOUD-2 Step 0 (DEEPSEEK_API_KEY stays in .env until he revokes it; nothing may use it)
HOSTS = {h: ("R45", QUOTE) for h in (
    "api.groq.com", "openrouter.ai", "generativelanguage.googleapis.com", "integrate.api.nvidia.com",
    "api.cerebras.ai", "api.openai.com", "api.anthropic.com", "api.mistral.ai", "api.deepseek.com")}
SDKS = {m: ("R45", QUOTE) for m in ("openai", "anthropic", "groq", "google.generativeai", "mistralai",
                                    "deepseek")}
# identifier fragment -> (ruling, Emil's words)
NAMES = {n: ("R46", QUOTE_R46) for n in ("groq", "gemini", "openrouter", "cerebras")}
NAME_EXEMPT = ("core/redact.py", "cockpit/server.py", "core/answered_by.py", "core/cycle_integrity.py",
               "tools/step_audit.py", "experiments/kimi_duel/results.json")
NAME_RE = re.compile("|".join(NAMES), re.I)

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


def _json_keys(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            out.append(str(k))
            _json_keys(v, out)
    elif isinstance(o, list):
        for v in o:
            _json_keys(v, out)
    return out


def name_findings(rel: str, text: str) -> list[str]:
    if rel in NAME_EXEMPT or rel.startswith("test/"):
        return []
    found = []                                   # (line, identifier)
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.append((n.lineno, n.name))
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    for s in ast.walk(t):
                        if isinstance(s, ast.Name):
                            found.append((n.lineno, s.id))
                        elif isinstance(s, ast.Attribute):
                            found.append((n.lineno, s.attr))
    elif rel.endswith(".json"):
        try:
            keys = _json_keys(json.loads(text), [])
        except ValueError:
            return []
        lines = text.splitlines()
        for k in keys:
            line = next((i for i, l in enumerate(lines, 1) if f'"{k}"' in l), 0)
            found.append((line, k))
    out = []
    for line, ident in found:
        m = NAME_RE.search(ident)
        if m:
            out.append(f"{rel}:{line}: identifier {ident} names {m.group(0).lower()} "
                       f"({NAMES[m.group(0).lower()][0]})")
    return out


def scan(files) -> list[str]:
    out = []
    for f in files:
        text = (REPO / f).read_text(encoding="utf-8-sig", errors="replace")
        out += findings(f, text) + name_findings(f, text)
    return out


def test_no_file_names_an_outside_model_host_or_imports_its_sdk():
    bad = scan(tracked())
    assert not bad, "outside language model in the system (R45):\n  " + "\n  ".join(bad)


def test_the_scan_examines_the_system():
    files = tracked()
    assert len(files) > 300 and "core/local_llm.py" in files and "config/network_allowlist.json" in files


def test_every_pattern_carries_the_ruling_and_the_quote():
    assert all(v == ("R45", QUOTE) for v in list(HOSTS.values()) + list(SDKS.values()))
    assert NAMES and all(v == ("R46", QUOTE_R46) for v in NAMES.values())


def test_every_name_exemption_is_a_tracked_file():
    files = set(subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                               check=True).stdout.splitlines())
    assert [f for f in NAME_EXEMPT if f not in files] == []


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_an_outside_url_in_a_core_file_fails():
    src = (REPO / "core" / "local_llm.py").read_text(encoding="utf-8")
    src += '\nGROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"\n'
    assert findings("core/local_llm.py", src), "the line above must be found"


def test_mutation_a_def_named_after_a_provider_in_a_core_file_fails():
    src = (REPO / "core" / "local_llm.py").read_text(encoding="utf-8") + "\n\ndef _groq(prompt):\n    return prompt\n"
    bad = name_findings("core/local_llm.py", src)
    assert bad and "_groq" in bad[-1] and "R46" in bad[-1], bad


def test_mutation_other_identifier_shapes_fail():
    assert name_findings("core/x.py", "class GeminiClient:\n    pass\n")
    assert name_findings("core/x.py", "OPENROUTER_URL = 1\n")
    assert name_findings("core/x.py", "self.cerebras_key = 1\n")
    assert name_findings("config/x.json", '{"a": {"groq_model": 1}}')
    assert not name_findings("core/x.py", "def ask_local_model():\n    pass\n")
    assert not name_findings("core/redact.py", "GROQ_SHAPE = 1\n")


def test_mutation_the_deepseek_host_and_sdk_fail():
    assert findings("core/x.py", 'URL = "https://api.deepseek.com/chat/completions"\n')
    assert findings("core/x.py", "import deepseek\n")


def test_mutation_an_sdk_import_fails():
    assert findings("core/x.py", "import openai\n")
    assert findings("core/x.py", "from anthropic import Anthropic\n")
    assert findings("core/x.py", "import google.generativeai as genai\n")
    assert not findings("core/x.py", "import json\nfrom core import llm_door\n")
