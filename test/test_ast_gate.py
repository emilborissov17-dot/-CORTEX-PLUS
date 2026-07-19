"""Unit tests for safety/ast_gate.py's static capability gate.

check_code() is pure (no filesystem/network access), so these run
directly against the real module with no sandboxing needed.

POLICY (2026-07-19): the gate now RESOLVES a write target through statically
provable indirection — a single local/module binding, a Path() wrapper, and a
function parameter traced to ALL its call sites — instead of demanding an inline
literal. The loosening only ever ADDS proof-of-safe: an unprovable or unsafe
target is still denied, and the protected-path denylist still bites through the
resolution. The adversarial block below is the guard that keeps "off-leash"
from ever meaning "out of the meadow".
"""
import pytest

from safety.ast_gate import check_code

_BASE = "import pathlib, os\nB = pathlib.Path(os.environ['CORTEX_BASE'])\n"

CASES = [
    # ── shape attacks — must stay DENY ─────────────────────────────────────
    ("getattr+concat __import__",
     "x = getattr(__import__('sub'+'process'),'run')\n", False),
    ("chr-built __import__",
     "mod = ''.join([chr(115),chr(117),chr(98),chr(112),chr(114),chr(111),chr(99),chr(101),chr(115),chr(115)])\n"
     "m = __import__(mod)\n", False),
    ("getattr(os,'system') literal",
     "import os\nf = getattr(os, 'system')\nf('echo hi')\n", False),
    ("importlib.import_module", "import importlib\nm = importlib.import_module('subprocess')\n", False),
    ("bare import_module", "from importlib import import_module\nm = import_module('subprocess')\n", False),
    ("import subprocess", "import subprocess\nsubprocess.run(['ls'])\n", False),
    ("from subprocess import run", "from subprocess import run\nrun(['ls'])\n", False),
    ("os.system", "import os\nos.system('rm -rf /')\n", False),
    ("shutil.rmtree", "import shutil\nshutil.rmtree('/')\n", False),
    ("eval call", "eval('1+1')\n", False),

    # ── target attacks — must stay DENY ────────────────────────────────────
    ("open outside allowed dir", "f = open('/etc/passwd', 'w')\n", False),
    ("Path traversal literal ..",
     _BASE + "(B / 'memory' / '..' / '..' / 'etc' / 'passwd').write_text('x')\n", False),
    ("protected file inline (existence_ledger)",
     _BASE + "(B / 'memory' / 'existence_ledger.jsonl').write_text('fake')\n", False),

    # ── benign inline — ALLOW (unchanged) ──────────────────────────────────
    ("benign open() memory/test.json",
     "f = open('memory/test.json', 'w')\nf.write('{}')\nf.close()\n", True),
    ("benign BASE/memory/test.json write_text",
     _BASE + "(B / 'memory' / 'test.json').write_text('{}', encoding='utf-8')\n", True),
    ("benign no I/O logic",
     "import json, datetime\nx = {'a': 1}\nprint(json.dumps(x))\n", True),

    # ── POLICY CHANGE (2026-07-19): safe indirection now ALLOW ─────────────
    # Previously "open() computed path" was denied even for a safe literal. The
    # gate now resolves single, unambiguous bindings.
    ("safe literal via variable (open)", "p = 'memory/x.json'\nopen(p, 'w')\n", True),
    ("safe module constant (write_text)", _BASE + "S = B / 'memory' / 's.json'\nS.write_text('{}')\n", True),
    ("generic helper, safe call site",
     "import pathlib\n"
     "def _safe_save(path, data):\n"
     "    p = pathlib.Path(path)\n"
     "    p.write_text(data)\n"
     "S = pathlib.Path('memory') / 'x.json'\n"
     "_safe_save(S, '{}')\n", True),
    ("param via keyword arg",
     "import pathlib\n"
     "def save(path, d):\n    pathlib.Path(path).write_text(d)\n"
     "save(path='memory/ok.json', d='x')\n", True),
    ("param via default value",
     "import pathlib\n"
     "def save(d, path='memory/ok.json'):\n    pathlib.Path(path).write_text(d)\n"
     "save('x')\n", True),

    # ── adversarial indirection — must stay DENY ───────────────────────────
    ("unsafe literal via variable", "p = '/etc/passwd'\nopen(p, 'w')\n", False),
    ("dynamic value via variable", "def f():\n    return 1\np = f()\nopen(p, 'w')\n", False),
    ("reassigned variable is ambiguous", "p = 'memory/x'\np = '/etc/y'\nopen(p, 'w')\n", False),
    ("helper with an unsafe call site",
     "import pathlib\ndef save(path, d):\n    pathlib.Path(path).write_text(d)\nsave('/etc/x', 'y')\n", False),
    ("helper with a mix of safe and unsafe call sites",
     "import pathlib\ndef save(path, d):\n    pathlib.Path(path).write_text(d)\n"
     "save('memory/ok', 'a')\nsave('/etc/bad', 'b')\n", False),
    ("helper routing to a protected file",
     _BASE + "def save(path, d):\n    pathlib.Path(path).write_text(d)\n"
     "save(B / 'memory' / 'heartbeat.json', 'x')\n", False),
    ("traversal via variable", "p = 'memory/../../etc/passwd'\nopen(p, 'w')\n", False),
    ("helper used as a value, not only called",
     "import pathlib\ndef save(path, d):\n    pathlib.Path(path).write_text(d)\nx = save\nx('memory/ok', 'y')\n", False),
    ("star-args call is opaque",
     "import pathlib\ndef save(path, d):\n    pathlib.Path(path).write_text(d)\na = ('memory/x', 'y')\nsave(*a)\n", False),
    ("helper with no call site",
     "import pathlib\ndef save(path, d):\n    pathlib.Path(path).write_text(d)\n", False),
]


@pytest.mark.parametrize("name, source, expect_allowed", CASES, ids=[c[0] for c in CASES])
def test_ast_gate_case(name, source, expect_allowed):
    allowed, reason = check_code(source)
    assert allowed == expect_allowed, f"{name}: allowed={allowed} reason={reason!r}"
