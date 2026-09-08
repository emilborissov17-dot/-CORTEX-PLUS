#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_self_improve_pipeline.py — END TO END ON MOCKED MODELS, PRODUCTION UNTOUCHED.

EXPERIMENTAL (branch experimental/self-mod). The pipeline is on-demand: nothing
imports it, fast_cycle_runner.py does not know it exists, and it applies nothing.

TWO THINGS ARE UNDER TEST AND THE SECOND MATTERS MORE
------------------------------------------------------
1. It reaches a VERDICT: requirer -> implementer -> core.earning.verify, with
   both models mocked, ending in PASS or FAIL rather than an exception.
2. It leaves PRODUCTION ALONE. The whole tree is fingerprinted before and after
   — memory/, snapshots/, config/, core/, agents/, output/ — and any byte that
   moves fails the test. That is the assertion this file exists for: an
   experimental self-modification pipeline that quietly wrote into the record
   the nightly cycle reads would be the worst possible version of this feature.

A REFUSAL IS A RESULT, NOT A FAILURE
-------------------------------------
Today every run ends FAIL, because config/earning_classes.json is LOCKED with no
signed class. That is the designed state and the tests assert it explicitly —
a suite that only checked "no exception" would pass just as happily on a
pipeline whose judge had been quietly unlocked.

    venv\\Scripts\\python.exe -m pytest test/test_self_improve_pipeline.py -v
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

import sys
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "self_improve_pipeline", REPO / "tools" / "self_improve_pipeline.py")
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)


# The trees a nightly cycle reads and writes. Nothing here may move.
PRODUCTION_TREES = ("memory", "snapshots", "cortex_memory", "output", "news",
                    "config", "agents", "core", "data")


def _fingerprint() -> dict:
    """path -> sha256 of every tracked-ish file in the production trees.

    Directories only, and only files that exist now: a new file appearing is
    caught by the key set changing, and a modified one by its digest.
    """
    out = {}
    for tree in PRODUCTION_TREES:
        root = REPO / tree
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            try:
                out[str(p.relative_to(REPO))] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
            except Exception:
                continue
    return out


@pytest.fixture
def mocked_models():
    return P._fixture_models()


# ---------------------------------------------------------------------------
# (a) END TO END, ON MOCKED MODELS
# ---------------------------------------------------------------------------

def test_the_pipeline_runs_end_to_end_and_reaches_a_verdict(mocked_models, tmp_path):
    brain, coder = mocked_models
    P.OUT_DIR = tmp_path / "runs"          # keep even the ledger out of the repo

    record = P.run_once({"problem": "the water axis defaults"},
                        brain=brain, coder=coder)

    assert record["verdict"] in ("PASS", "FAIL"), record
    assert record["reason"], "a verdict with no reason is not a verdict"

    # every stage left its trace
    assert record["spec"]["goal_axis"], "no spec"
    assert "@@" in record["diff"], "no diff"
    assert record["changed_files"] == [P.FIXTURE_FILE]


def test_the_verdict_today_is_FAIL_because_the_policy_is_LOCKED(mocked_models, tmp_path):
    """The designed state, asserted rather than assumed. A suite that only
    checked 'no exception' would pass on a judge that had been unlocked."""
    brain, coder = mocked_models
    P.OUT_DIR = tmp_path / "runs"

    record = P.run_once({"problem": "p"}, brain=brain, coder=coder)
    assert record["policy_locked"] is True
    assert record["verdict"] == "FAIL"
    assert "LOCKED" in record["reason"]


def test_the_rendered_report_shows_spec_diff_and_verdict(mocked_models, tmp_path):
    brain, coder = mocked_models
    P.OUT_DIR = tmp_path / "runs"
    text = P.render(P.run_once({"problem": "p"}, brain=brain, coder=coder))

    assert "SPEC" in text and "DIFF" in text and "VERDICT" in text
    assert "GRANTS NOTHING" in text, (
        "the report does not say the verdict grants nothing")
    assert "Nothing was applied" in text


# ---------------------------------------------------------------------------
# (a2) THE CONTEXT REACHES THE IMPLEMENTER
# ---------------------------------------------------------------------------

def test_the_implementer_is_given_the_real_file_content(mocked_models, tmp_path,
                                                        monkeypatch):
    """THE ROOT CAUSE OF THE 2026-09-08 HALLUCINATION. run_once called
    implement(spec, model=...) and nothing else, so the cloud model was handed a
    specification and asked to patch a repository it had never seen. It wrote a
    competent patch to src/ai/self_observer.py — a file, a class and a module
    that exist nowhere in this repo."""
    brain, coder = mocked_models
    P.OUT_DIR = tmp_path / "runs"

    seen = {}
    from core.self_improve import implementer as I
    real_implement = I.implement

    def _spy(spec, model=None, context=""):
        seen["context"] = context
        return real_implement(spec, model=model, context=context)

    monkeypatch.setattr(I, "implement", _spy)
    record = P.run_once({"problem": "p"}, brain=brain, coder=coder)

    assert "context" in seen, "implement() was never called"
    assert seen["context"], (
        "the implementer was handed an EMPTY context — it is patching a file "
        "it has not been shown")
    assert record["context_chars"] == len(seen["context"])


def test_the_context_is_the_real_file_and_only_real_files(tmp_path):
    """Only files that EXIST are read. A spec naming a path that does not
    resolve contributes nothing rather than a fabricated placeholder."""
    real = "agents/core/self_observer.py"
    ctx = P._read_allowed_files({"allowed_paths": [real, "src/ai/nope.py"]})

    assert f"--- {real} ---" in ctx
    assert "src/ai/nope.py" not in ctx, (
        "a path that does not exist appeared in the context")
    head = (REPO / real).read_text(encoding="utf-8")[:100]
    assert head in ctx


def test_the_context_is_budgeted():
    """A whole repo in one prompt is a different failure. The budget is a cap,
    not a suggestion."""
    ctx = P._read_allowed_files({"allowed_paths": ["agents/core/self_observer.py"]},
                                budget=500)
    assert len(ctx) <= 500 + 80, len(ctx)      # + the "--- path ---" header


# ---------------------------------------------------------------------------
# (b) PRODUCTION IS UNTOUCHED — the assertion this file exists for
# ---------------------------------------------------------------------------

def test_a_full_run_leaves_every_production_tree_byte_identical(mocked_models,
                                                                tmp_path):
    brain, coder = mocked_models
    P.OUT_DIR = tmp_path / "runs"

    before = _fingerprint()
    P.run_once({"problem": "p"}, brain=brain, coder=coder)
    after = _fingerprint()

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in before.keys() & after.keys()
                     if before[k] != after[k])

    assert not added, f"the pipeline CREATED production files: {added}"
    assert not removed, f"the pipeline DELETED production files: {removed}"
    assert not changed, (
        f"the pipeline MODIFIED production files: {changed}. An experimental "
        f"self-modification pipeline that writes into the record the nightly "
        f"cycle reads is the worst possible version of this feature.")


def test_the_pipeline_refuses_to_write_outside_experiments():
    for bad in ("memory/x.json", "snapshots/y.json", "config/z.json",
                "core/w.py"):
        with pytest.raises(P.PipelineRefused) as exc:
            P._assert_experimental(REPO / bad)
        assert "experiments/" in str(exc.value)

    ok = P._assert_experimental(REPO / "experiments" / "self_improve" / "runs")
    assert ok.parts[-3:] == ("experiments", "self_improve", "runs")


def test_the_revocation_ledger_stays_in_the_experimental_tree():
    """core.earning records a FAIL. A hand-run experiment must not append to the
    ledger the real verifier reads."""
    tree = ast.parse((REPO / "tools" / "self_improve_pipeline.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_once")
    kwargs = {k.arg for n in ast.walk(fn) if isinstance(n, ast.Call)
              for k in n.keywords if k.arg}
    assert "revocations_path" in kwargs, (
        "run_once calls earning.verify without redirecting the revocation "
        "ledger; a hand run would append to the production record")


def test_it_applies_nothing():
    """No git, no subprocess, no patch application. It prints a diff."""
    tree = ast.parse((REPO / "tools" / "self_improve_pipeline.py")
                     .read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for bad in ("subprocess", "git", "shutil"):
        assert bad not in imported, f"the pipeline imports {bad}"

    src = (REPO / "tools" / "self_improve_pipeline.py").read_text(encoding="utf-8")
    for bad in ("git apply", "patch -p", "os.system"):
        assert bad not in src, f"the pipeline reaches for {bad!r}"


# ---------------------------------------------------------------------------
# (c) ON DEMAND — not in the cycle
# ---------------------------------------------------------------------------

def test_the_cycle_does_not_know_this_pipeline_exists():
    """The single assertion that keeps it on-demand. If fast_cycle_runner ever
    references it, this is an automated self-modification loop and everything
    above must be re-read as a safety property rather than an experiment."""
    runner = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "self_improve" not in runner, (
        "fast_cycle_runner.py references self_improve — THE PIPELINE IS WIRED")

    for mod in ("core/cycle_map.py", "config/cycle_phases.json"):
        text = (REPO / mod).read_text(encoding="utf-8")
        assert "self_improve" not in text, f"{mod} references self_improve"


def test_nothing_in_the_repo_imports_the_pipeline():
    """On-demand means exactly that: a human types the command."""
    # AST, not a text search. core/self_improve/__init__.py NAMES the pipeline in
    # its docstring — to tell a reader where the on-demand entry point is, which
    # is the opposite of importing it. A grep cannot tell a signpost from a wire.
    # Walk only the trees this repo owns. REPO.rglob("*.py") descends into
    # venv/ and Broker-bot/ — tens of thousands of third-party files — and took
    # 63 seconds for an answer that cannot possibly live there.
    OWN = ("core", "agents", "tools", "scripts", "experiments", "memory",
           "safety", "alignment", "data_providers")
    offenders = []
    candidates = [REPO / f for f in REPO.glob("*.py")]
    for tree in OWN:
        candidates += list((REPO / tree).rglob("*.py")) if (REPO / tree).is_dir() else []
    for p in candidates:
        parts = p.parts
        if any(x in parts for x in ("__pycache__",)):
            continue
        if p.name == "self_improve_pipeline.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any("self_improve_pipeline" in n for n in names):
                offenders.append(f"{p.relative_to(REPO)}:{node.lineno}")
    assert not offenders, f"the pipeline is imported by: {offenders}"


# ---------------------------------------------------------------------------
# (d) A REFUSAL ENDS THE RUN
# ---------------------------------------------------------------------------

def test_a_spec_carrying_code_ends_the_run(tmp_path):
    """Not smoothed over, not retried. The refusal is the result."""
    P.OUT_DIR = tmp_path / "runs"
    bad_spec = {"problem": "def f():\n    x = 1", "root_cause": "r",
                "desired_change": "d", "success_metric": "m",
                "goal_axis": "WATER_REVIEW", "allowed_paths": ["data_providers/"]}
    with pytest.raises(P.PipelineRefused) as exc:
        P.run_once({"problem": "p"},
                   brain=lambda p, max_tokens=700: json.dumps(bad_spec),
                   coder=lambda p, max_tokens=1400: "")
    assert "requirer refused" in str(exc.value)


def test_a_diff_out_of_scope_ends_the_run(mocked_models, tmp_path):
    brain, _ = mocked_models
    P.OUT_DIR = tmp_path / "runs"
    out_of_scope = ("--- a/core/notary.py\n+++ b/core/notary.py\n"
                    "@@ -1,2 +1,3 @@\n c\n+added\n")
    with pytest.raises(P.PipelineRefused) as exc:
        P.run_once({"problem": "p"}, brain=brain,
                   coder=lambda p, max_tokens=1400: out_of_scope)
    assert "implementer refused" in str(exc.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
