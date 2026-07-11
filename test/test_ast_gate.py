"""Unit tests for safety/ast_gate.py's static capability gate.

check_code() is pure (no filesystem/network access), so these run
directly against the real module with no sandboxing needed.
"""
import pytest

from safety.ast_gate import check_code

CASES = [
    (
        "getattr+concat __import__",
        "x = getattr(__import__('sub'+'process'),'run')\n",
        False,
    ),
    (
        "chr-built __import__",
        "mod = ''.join([chr(115),chr(117),chr(98),chr(112),chr(114),chr(111),chr(99),chr(101),chr(115),chr(115)])\n"
        "m = __import__(mod)\n",
        False,
    ),
    (
        "getattr(os,'system') literal",
        "import os\nf = getattr(os, 'system')\nf('echo hi')\n",
        False,
    ),
    (
        "importlib.import_module",
        "import importlib\nm = importlib.import_module('subprocess')\n",
        False,
    ),
    (
        "bare import_module",
        "from importlib import import_module\nm = import_module('subprocess')\n",
        False,
    ),
    (
        "import subprocess",
        "import subprocess\nsubprocess.run(['ls'])\n",
        False,
    ),
    (
        "from subprocess import run",
        "from subprocess import run\nrun(['ls'])\n",
        False,
    ),
    (
        "os.system",
        "import os\nos.system('rm -rf /')\n",
        False,
    ),
    (
        "shutil.rmtree",
        "import shutil\nshutil.rmtree('/')\n",
        False,
    ),
    (
        "open outside allowed dir",
        "f = open('/etc/passwd', 'w')\n",
        False,
    ),
    (
        "open() computed path",
        "p = 'memory/x.json'\nf = open(p, 'w')\n",
        False,
    ),
    (
        "Path traversal literal ..",
        "import pathlib, os\nBASE_DIR = pathlib.Path(os.environ['CORTEX_BASE'])\n"
        "(BASE_DIR / 'memory' / '..' / '..' / 'etc' / 'passwd').write_text('x')\n",
        False,
    ),
    (
        "eval call",
        "eval('1+1')\n",
        False,
    ),
    (
        "benign open() memory/test.json",
        "f = open('memory/test.json', 'w')\nf.write('{}')\nf.close()\n",
        True,
    ),
    (
        "benign BASE_DIR/memory/test.json write_text",
        "import pathlib, os\nBASE_DIR = pathlib.Path(os.environ['CORTEX_BASE'])\n"
        "(BASE_DIR / 'memory' / 'test.json').write_text('{}', encoding='utf-8')\n",
        True,
    ),
    (
        "benign no I/O logic",
        "import json, datetime\nx = {'a': 1}\nprint(json.dumps(x))\nprint(datetime.datetime.utcnow().isoformat())\n",
        True,
    ),
]


@pytest.mark.parametrize("name, source, expect_allowed", CASES, ids=[c[0] for c in CASES])
def test_ast_gate_case(name, source, expect_allowed):
    allowed, reason = check_code(source)
    assert allowed == expect_allowed, f"{name}: allowed={allowed} reason={reason!r}"
