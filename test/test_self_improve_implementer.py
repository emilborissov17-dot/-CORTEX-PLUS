#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_self_improve_implementer.py — THE DIFF STAYS IN SCOPE, OR IT DOES NOT LEAVE.

EXPERIMENTAL (branch experimental/self-mod). The model is mocked in every test;
nothing reaches Groq, OpenRouter, Gemini or Ollama, and nothing is applied to any
file.

WHY THE SCOPE CHECK LIVES HERE AS WELL AS IN core/earning.py
--------------------------------------------------------------
That is not a duplicate. earning is the JUDGE and can only grade what it is
handed; this is the PRODUCER and must not hand over work it already knows is out
of scope. A producer that emits out-of-scope work and leaves the judge to catch
it has moved its own failure into someone else's budget — and on the night the
judge is not wired in, nothing catches it at all.

THE FORBIDDEN FALLBACK
-----------------------
Dropping the offending hunks and returning the rest. That is the repair a helpful
implementer reaches for, and it is worse than refusing: the trimmed diff is a
DIFFERENT change from the one the model proposed, and nothing downstream would
know. test_an_out_of_scope_diff_is_refused_WHOLE_not_trimmed pins it.

    venv\\Scripts\\python.exe -m pytest test/test_self_improve_implementer.py -v
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from core.self_improve import implementer as I

REPO = pathlib.Path(__file__).resolve().parents[1]

SPEC = {
    "problem": "The provider never resolves the series.",
    "root_cause": "The observation key is absent from the map.",
    "desired_change": "The provider resolves the series instead of defaulting.",
    "success_metric": "count of axes scoring from real data",
    "goal_axis": "WATER_REVIEW",
    "allowed_paths": ["data_providers/"],
}


def _diff(*paths: str) -> str:
    out = []
    for p in paths:
        out.append(f"--- a/{p}\n+++ b/{p}\n@@ -1,2 +1,3 @@\n context\n+added\n")
    return "".join(out)


def _model(text: str):
    return lambda prompt, max_tokens=1400: text


# ---------------------------------------------------------------------------
# (a) THE BRIEF: a diff scoped to allowed_paths comes back
# ---------------------------------------------------------------------------

def test_a_spec_yields_a_diff_scoped_to_allowed_paths():
    res = I.implement(SPEC, model=_model(_diff("data_providers/water_provider.py")))

    assert res["changed_files"] == ["data_providers/water_provider.py"]
    assert "@@" in res["diff"], "the result is not a unified diff"
    assert res["spec"] is SPEC
    for path in res["changed_files"]:
        assert any(path.startswith(a) for a in SPEC["allowed_paths"])


def test_several_files_all_inside_the_allowlist_are_fine():
    res = I.implement(SPEC, model=_model(_diff(
        "data_providers/water_provider.py", "data_providers/food_provider.py")))
    assert len(res["changed_files"]) == 2


def test_a_fenced_diff_is_unwrapped_without_dropping_a_hunk():
    """Models fence diffs even when told not to. Unwrapping is not the forbidden
    'clean it up': the diff inside is byte-identical and no hunk is lost."""
    inner = _diff("data_providers/water_provider.py")
    res = I.implement(SPEC, model=_model(f"```diff\n{inner}```"))
    assert res["diff"].strip() == inner.strip()
    assert res["diff"].count("@@") == inner.count("@@")


# ---------------------------------------------------------------------------
# (b) OUT OF SCOPE IS REFUSED BEFORE IT LEAVES
# ---------------------------------------------------------------------------

def test_a_diff_outside_allowed_paths_is_refused_before_it_leaves():
    with pytest.raises(I.PatchOutOfScope) as exc:
        I.implement(SPEC, model=_model(_diff("agents/core/self_modifier.py")))
    assert "agents/core/self_modifier.py" in str(exc.value)
    assert "allowed_paths" in str(exc.value)


def test_an_out_of_scope_diff_is_refused_WHOLE_not_trimmed():
    """THE FORBIDDEN FALLBACK. One hunk in scope, one out. Returning only the
    good half would be a different change from the one proposed, and nothing
    downstream would know."""
    mixed = _diff("data_providers/water_provider.py", "scripts/whatever.py")
    with pytest.raises(I.PatchOutOfScope) as exc:
        I.implement(SPEC, model=_model(mixed))
    assert "refused WHOLE" in str(exc.value), (
        "the refusal does not say that trimming is not the remedy")
    assert "scripts/whatever.py" in str(exc.value)


@pytest.mark.parametrize("victim", list(I.NEVER_TOUCH))
def test_the_never_touch_paths_are_refused_whatever_the_spec_allows(victim):
    """A spec that permits everything must still not yield a patch to the
    verifier, the policy, the rules of passage or the tests that pin them."""
    permissive = dict(SPEC, allowed_paths=["core/", "config/", "test/",
                                           "data_providers/"])
    with pytest.raises(I.PatchOutOfScope) as exc:
        I.implement(permissive, model=_model(_diff(victim)))
    assert "NEVER_TOUCH" in str(exc.value)


def test_a_spec_with_an_empty_allowlist_yields_nothing():
    with pytest.raises((I.PatchOutOfScope, I.PatchUnusable)):
        I.implement(dict(SPEC, allowed_paths=[]),
                    model=_model(_diff("data_providers/x.py")))


@pytest.mark.parametrize("junk", [
    "I would add the missing key to the observation map.",
    "",
    "--- a/data_providers/x.py\n+++ b/data_providers/x.py\n",   # headers, no hunk
])
def test_something_that_is_not_a_diff_is_refused(junk):
    with pytest.raises(I.PatchUnusable):
        I.implement(SPEC, model=_model(junk))


def test_a_bare_at_at_hunk_is_accepted():
    """THE FALSE REFUSAL, FIXED. _HUNK was r"^@@ " — requiring line-number ranges
    after the marker. On 2026-09-08 Groq returned a well-formed patch using BARE
    `@@` markers (4 of them, 0 with a trailing space) and this refused it as "not
    a diff". The model was right and the check was wrong, and the refusal blamed
    the model. A gate that refuses for a false reason teaches the wrong lesson.
    """
    bare = ("--- a/agents/core/self_observer.py\n"
            "+++ b/agents/core/self_observer.py\n"
            "@@\n-old\n+new\n")
    assert I.enforce_scope(bare, ["agents/core/self_observer.py"]) == [
        "agents/core/self_observer.py"]


def test_a_ranged_hunk_still_works():
    """The ordinary form must not have been broken by relaxing the marker."""
    ranged = ("--- a/agents/core/self_observer.py\n"
              "+++ b/agents/core/self_observer.py\n"
              "@@ -1,2 +1,3 @@\n c\n+added\n")
    assert I.enforce_scope(ranged, ["agents/core/self_observer.py"])


def test_a_diff_against_a_file_that_does_not_exist_is_REFUSED():
    """TWO HALLUCINATIONS CANCELLING. enforce_scope compared the diff against the
    SPEC and nothing else, so when both were invented they AGREED and a patch to
    src/ai/self_observer.py cleared the scope gate. Matching an invented
    allowlist is not scope."""
    ghost = ("--- a/src/ai/self_observer.py\n"
             "+++ b/src/ai/self_observer.py\n"
             "@@\n-x\n+y\n")
    with pytest.raises(I.PatchOutOfScope) as exc:
        I.enforce_scope(ghost, ["src/ai/self_observer.py"])
    assert "does not exist in this repo" in str(exc.value)


def test_a_NEW_file_in_a_real_directory_is_allowed():
    """A patch may CREATE a file. Refusing every new file would be the opposite
    error, so a path passes when its parent directory is real."""
    newf = ("--- /dev/null\n"
            "+++ b/agents/core/brand_new_thing.py\n"
            "@@\n+line\n")
    assert I.enforce_scope(newf, ["agents/core/"]) == [
        "agents/core/brand_new_thing.py"]


def test_dev_null_is_not_treated_as_a_path():
    """A new file's diff spells the absent side /dev/null. That is not a path
    anyone can touch, and reading it as one would refuse every file creation."""
    new_file = ("--- /dev/null\n+++ b/data_providers/new_provider.py\n"
                "@@ -0,0 +1,2 @@\n+line one\n+line two\n")
    res = I.implement(SPEC, model=_model(new_file))
    assert res["changed_files"] == ["data_providers/new_provider.py"]


# ---------------------------------------------------------------------------
# (c) WHICH MODEL, AND WHAT IT MUST NOT DO
# ---------------------------------------------------------------------------

def test_the_implementer_uses_the_cloud_ladder_and_not_the_local_model():
    """STRUCTURAL, the mirror of the requirer's test. The whole experiment is
    which model does which job; a silent swap would end it without saying so."""
    tree = ast.parse((REPO / "core" / "self_improve" / "implementer.py")
                     .read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.groq_backend":
            names = {a.name for a in node.names}
            assert names == {"call_groq"}, (
                f"the implementer imports {names}; it may use the CLOUD ladder "
                f"only — _call_local would put the 0/3 model back on this job")
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_call_local" not in called and "_call_local_as" not in called


def test_the_implementer_applies_nothing():
    """It returns text. No write, no git, no subprocess, no patch application —
    whether a diff is ever applied is a decision made elsewhere, by a human."""
    tree = ast.parse((REPO / "core" / "self_improve" / "implementer.py")
                     .read_text(encoding="utf-8"))

    # "replace" and "rename" are deliberately NOT in this list: str.replace is
    # how the path normaliser turns "\\" into "/", and banning the bare
    # attribute name would fail on a string method that touches nothing. The
    # filesystem forms of both live on os, and the os import is banned below —
    # which is the check that actually closes that door.
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("write_text", "write_bytes", "mkdir",
                                     "unlink", "rmdir", "touch"), (
                f"the implementer writes to disk at line {node.lineno}")

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for bad in ("subprocess", "git", "shutil", "os"):
        assert bad not in imported, f"the implementer imports {bad}"


def test_the_prompt_states_the_allowlist_and_the_whole_refusal():
    """Sharp instruction AND mechanical net, as the norm requires — neither
    standing in for the other."""
    prompt = I.build_prompt(SPEC)
    assert "data_providers/" in prompt, "the model is not told its scope"
    assert "REFUSED WHOLE" in prompt
    assert "not trimmed" in prompt
    for never in I.NEVER_TOUCH[:3]:
        assert never in prompt, f"the model is not told to avoid {never}"


def test_the_scope_check_is_reachable_on_its_own():
    """enforce_scope is the net; it must be usable and testable without a model,
    so the pipeline can re-check a diff it did not generate."""
    good = _diff("data_providers/x.py")
    assert I.enforce_scope(good, ["data_providers/"]) == ["data_providers/x.py"]
    with pytest.raises(I.PatchOutOfScope):
        I.enforce_scope(good, ["core/"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
