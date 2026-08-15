"""The self-coding experiment must stay an experiment, not become a foothold.

experiments/selfcode/selfcode_loop.py asks a model to write code, runs it, feeds the
failure back, and repeats. Everything it produces is untrusted by construction, so the
isolation is the whole safety story and it is tested here rather than trusted:

  * the sandbox is outside the repository — a sandbox inside the repo is not a sandbox;
  * generated code is executed only in a subprocess and NEVER imported here;
  * the child gets no CORTEX_BASE, so patch-style code has no repo root to aim at;
  * the model is never shown the test source — a model shown the assertions can satisfy
    them without solving anything, which measures nothing.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "selfcode"))

import selfcode_loop as S  # noqa: E402


def test_a_sandbox_inside_the_repo_is_refused():
    with pytest.raises(RuntimeError, match="inside the repo"):
        S._assert_outside_repo(REPO / "scratch")
    with pytest.raises(RuntimeError):
        S._assert_outside_repo(REPO / "memory" / "deep" / "nested")


def test_a_sandbox_outside_the_repo_is_allowed(tmp_path):
    S._assert_outside_repo(tmp_path)   # must not raise


def test_the_child_gets_no_repo_root():
    env = S._clean_env()
    assert "CORTEX_BASE" not in env
    assert "PYTHONPATH" not in env


def test_generated_code_is_never_imported_into_this_process():
    src = (REPO / "experiments" / "selfcode" / "selfcode_loop.py").read_text(encoding="utf-8")
    for forbidden in ("exec(", "eval(", "importlib.import_module", "__import__("):
        assert forbidden not in src, f"generated code must stay in a subprocess: {forbidden}"


def test_the_model_never_sees_the_test_source():
    """Both prompts are built from `spec` only. A leak here silently invalidates every
    result the experiment has ever produced."""
    for template in (S.FIRST_PROMPT, S.RETRY_PROMPT):
        assert "{test}" not in template
        assert "test" not in [f for f in ("{test}", "{test_src}") if f in template]
    for name, task in S.TASKS.items():
        rendered = S.FIRST_PROMPT.format(spec=task["spec"])
        assert "ALL PASS" not in rendered, f"{name}: the test leaked into the prompt"
        assert "assert " not in rendered, f"{name}: assertions leaked into the prompt"


def test_every_task_has_a_spec_and_a_hidden_test():
    assert S.TASKS
    for name, task in S.TASKS.items():
        assert task["spec"].strip(), name
        assert "ALL PASS" in task["test"], f"{name}: the harness detects success by this"


def test_a_passing_solution_is_recognised(tmp_path):
    ok, diag = S._run_test(tmp_path, "def f():\n    return 1",
                           "import solution\nprint('ALL PASS')")
    assert ok and diag == ""


def test_a_failing_solution_yields_a_usable_diagnosis(tmp_path):
    """The whole loop depends on the error text being informative — a truncated or empty
    diagnosis is why the real pipeline never learned from its own rejected patches."""
    ok, diag = S._run_test(tmp_path, "def f():\n    raise KeyError('name')\nf()",
                           "import solution\nprint('ALL PASS')")
    assert not ok
    assert "KeyError" in diag and "name" in diag


def test_a_silent_solution_does_not_count_as_a_pass(tmp_path):
    """Exit code 0 is not enough — the harness requires the marker."""
    ok, _ = S._run_test(tmp_path, "x = 1", "import solution")
    assert not ok


def test_an_infinite_loop_is_killed(tmp_path):
    S.EXEC_TIMEOUT_SAVED = S.EXEC_TIMEOUT
    S.EXEC_TIMEOUT = 3
    try:
        ok, diag = S._run_test(tmp_path, "while True:\n    pass",
                               "import solution\nprint('ALL PASS')")
        assert not ok and "timeout" in diag.lower()
    finally:
        S.EXEC_TIMEOUT = S.EXEC_TIMEOUT_SAVED


def test_code_extraction_takes_the_last_fenced_block():
    reply = "blah\n```python\nold = 1\n```\ntext\n```python\nnew = 2\n```\n"
    assert S._extract_code(reply) == "new = 2"
    assert S._extract_code("no fences here") == "no fences here"
