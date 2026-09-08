#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_self_improve_requirer.py — THE BRAIN EMITS A SPEC AND NEVER CODE.

EXPERIMENTAL (branch experimental/self-mod). Nothing under test here is wired
into the cycle. Every test mocks the model; none reaches Ollama or a cloud API,
and none writes outside tmp_path.

WHY THE NET AND NOT JUST THE INSTRUCTION
-----------------------------------------
"You produce a specification, you never write code" is exactly the instruction a
helpful model satisfies in letter and breaks in spirit — a "tiny illustrative
snippet", a fenced block "just to be clear". The prompt says it; _reject_code()
enforces it; and the refusal is WHOLE, because a spec with the code stripped out
would look clean and hide that the split had failed.

That refusal is the SUCCESS state of this module. A test suite that only checked
the happy path would pass on a requirer that had quietly become a second
implementer.

    venv\\Scripts\\python.exe -m pytest test/test_self_improve_requirer.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from core.self_improve import requirer as R

REPO = pathlib.Path(__file__).resolve().parents[1]

AXES = R.real_axes()
AXIS = sorted(AXES)[0]

GOOD_SPEC = {
    "problem": "WATER_REVIEW scores a default because a key is missing.",
    "root_cause": "The scorer's observation map has no entry for the series.",
    "desired_change": "The scorer resolves the series instead of defaulting.",
    "success_metric": "count of axes scoring from real data, read from the scores file",
    "goal_axis": AXIS,
    "allowed_paths": ["data_providers/"],
}


def _brain(payload) -> callable:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda prompt, max_tokens=700: text


# ---------------------------------------------------------------------------
# (a) THE TWO THINGS THE BRIEF ASKS FOR
# ---------------------------------------------------------------------------

def test_the_output_contains_no_python():
    """THE POINT. Every free-text field must be prose, checked by the same net
    the module applies — not by eye."""
    spec = R.require({"problem": "p"}, brain=_brain(GOOD_SPEC), axes=AXES)

    for field in ("problem", "root_cause", "desired_change", "success_metric"):
        assert R._looks_like_code(spec[field]) == "", (
            f"{field} reads as code: {spec[field]!r}")

    blob = json.dumps(spec)
    for marker in ("```", "def ", "import ", "write_text", "subprocess"):
        assert marker not in blob, f"the spec carries {marker!r}"

    # And nothing in it parses as a Python program.
    for field in ("problem", "root_cause", "desired_change", "success_metric"):
        try:
            tree = ast.parse(spec[field])
        except SyntaxError:
            continue
        assert not any(isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import,
                                      ast.ImportFrom, ast.Assign))
                       for n in ast.walk(tree)), f"{field} is a program"


def test_the_output_names_a_real_goal_axis():
    """One of the 24 in config/target_config.json, read from the file rather
    than retyped here."""
    spec = R.require({"problem": "p"}, brain=_brain(GOOD_SPEC), axes=AXES)
    assert spec["goal_axis"] in AXES
    assert len(AXES) == 24, f"the axis list moved: {len(AXES)}"
    assert spec["goal_axis"].endswith(("_REVIEW", "_LEVEL")), spec["goal_axis"]


def test_the_spec_carries_every_declared_field():
    spec = R.require({"problem": "p"}, brain=_brain(GOOD_SPEC), axes=AXES)
    for field in R.SPEC_FIELDS:
        assert field in spec, f"missing {field}"
    assert spec["allowed_paths"] == ["data_providers/"]


# ---------------------------------------------------------------------------
# (b) THE NET — refusing is the success state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["problem", "root_cause", "desired_change",
                                   "success_metric"])
def test_code_in_any_free_text_field_is_REFUSED_not_stripped(field):
    """Whole-spec refusal. A cleaned-up snippet would look correct and hide that
    the split failed."""
    bad = dict(GOOD_SPEC, **{field: "import json\ndata = json.loads(x)"})
    with pytest.raises(R.SpecContainsCode) as exc:
        R.require({"problem": "p"}, brain=_brain(bad), axes=AXES)
    assert field in str(exc.value)
    assert "refused rather than stripped" in str(exc.value)


@pytest.mark.parametrize("snippet", [
    "```python\nx = 1\n```",
    "def fix():\n    return 1",
    "from pathlib import Path",
    "#!/usr/bin/env python3",
    "p.write_text(json.dumps(d))",
])
def test_the_shapes_of_python_are_caught(snippet):
    assert R._looks_like_code(snippet), f"not caught: {snippet!r}"


def test_ordinary_prose_is_not_mistaken_for_code():
    """THE NEGATIVE CONTROL. A net that refuses everything is not a net — the
    requirer would emit nothing and the failure would look like caution."""
    for prose in (
        "The scorer defaults because the observation key is absent.",
        "Count the axes that score from real data, not from a default.",
        "Water availability is not being read from the provider at all.",
        "The value should equal the number of rows in the history file.",
    ):
        assert R._looks_like_code(prose) == "", f"false positive: {prose!r}"


def test_an_invented_axis_is_REFUSED_not_mapped_to_a_neighbour():
    bad = dict(GOOD_SPEC, goal_axis="WATER")     # plausible, and not an axis
    with pytest.raises(R.SpecInvalid) as exc:
        R.require({"problem": "p"}, brain=_brain(bad), axes=AXES)
    assert "not one of" in str(exc.value)
    assert "near neighbour" in str(exc.value), (
        "the refusal does not say why it is not silently corrected")


@pytest.mark.parametrize("missing", list(R.SPEC_FIELDS))
def test_a_missing_field_is_refused(missing):
    bad = {k: v for k, v in GOOD_SPEC.items() if k != missing}
    with pytest.raises(R.SpecInvalid):
        R.require({"problem": "p"}, brain=_brain(bad), axes=AXES)


def test_empty_allowed_paths_is_refused():
    """An empty allowlist would let the implementer write anywhere."""
    with pytest.raises(R.SpecInvalid):
        R.require({"problem": "p"}, brain=_brain(dict(GOOD_SPEC, allowed_paths=[])),
                  axes=AXES)


def test_a_brain_that_returns_prose_instead_of_json_is_refused():
    with pytest.raises(R.SpecInvalid) as exc:
        R.require({"problem": "p"}, brain=_brain("I think the water axis is broken."),
                  axes=AXES)
    assert "no JSON object" in str(exc.value)


# ---------------------------------------------------------------------------
# (c) WHICH MODEL — the experiment is about this and nothing else
# ---------------------------------------------------------------------------

def test_the_requirer_never_reaches_for_the_cloud_ladder():
    """STRUCTURAL, on the AST. A silent upgrade to call_groq when the local brain
    is down would make the spec look fine and end the experiment without saying
    so. If the local brain is unavailable this module must RAISE."""
    tree = ast.parse((REPO / "core" / "self_improve" / "requirer.py")
                     .read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.groq_backend":
            names = {a.name for a in node.names}
            assert names == {"_call_local"}, (
                f"the requirer imports {names} from the ladder; it may use the "
                f"LOCAL brain only")
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "call_groq" not in called and "call_groq_meta" not in called


def test_the_prompt_states_the_rules_it_will_be_judged_by():
    """THE CLEAR INSTRUCTION. A live run on 2026-09-08 produced three specs in
    three attempts, every one naming a real axis and a path that does NOT exist:
    "self_observer", "core/self_observer.py", "src/ai/self_observer.py". This
    repo has no src/ tree. The model was never told the paths had to be real."""
    prompt = R.build_prompt({"problem": "p"}, AXES)
    low = prompt.lower()

    assert "already exist" in low, "the path rule is not stated"
    assert "does not exist is a failure" in low, (
        "the prompt does not say what an invented path COSTS")
    assert "do not invent" in low
    assert "computable from a named file" in low, (
        "the success_metric rule is not stated")
    assert "judged by" in low, "the model is not told these are the rules"


def test_the_prompt_shows_the_passage_standard_verbatim():
    """The actor is shown the measure it is judged by — the SAME object
    core/notary.py reads, byte for byte, not a paraphrase. A second copy would
    drift, which is what core/passage_rules.py exists to prevent."""
    from core.passage_rules import actor_block

    prompt = R.build_prompt({"problem": "p"}, AXES)
    assert actor_block() in prompt, (
        "the passage standard is not carried verbatim into the requirer prompt")
    assert R.passage_standard() == actor_block()


def test_the_standard_failing_to_load_is_loud_not_silent(monkeypatch, capsys):
    """A prompt quietly missing its rules looks exactly like one that has them."""
    import core.passage_rules as PR

    monkeypatch.setattr(PR, "actor_block",
                        lambda: (_ for _ in ()).throw(RuntimeError("gone")))
    assert R.passage_standard() == ""
    out = capsys.readouterr().out
    assert "RULES OF PASSAGE" in out and "could not be loaded" in out


# ---------------------------------------------------------------------------
# (c2) THE GROUNDING — the model is SHOWN the repo, not asked to imagine it
# ---------------------------------------------------------------------------

def test_candidate_paths_are_all_real():
    """This list is the ground truth the model is told to copy from. One stale
    entry re-opens the exact hole it closes."""
    for component in ("self_observer", "self_modifier", "nonexistent_widget"):
        paths = R.candidate_paths(component)
        assert paths, f"no real candidates offered for {component}"
        for rel in paths:
            assert (REPO / rel).exists(), f"{rel} does not exist"
            assert not rel.startswith("/") and ":" not in rel, rel


def test_the_prompt_shows_real_paths_and_says_to_copy_them():
    prompt = R.build_prompt({"problem": "invalid JSON",
                             "component": "self_observer"}, AXES)
    assert "agents/core/self_observer.py" in prompt, (
        "the real file is not offered; the model has nothing to copy and will "
        "invent a path, which is what it did on 2026-09-08")
    assert "REAL PATHS IN THIS REPO" in prompt
    assert "copied exactly" in prompt


def test_the_prompt_shows_the_real_code():
    """Reusing agents/core/self_modifier._build_context, so the requirer sees
    exactly what the production self-modifier sees."""
    prompt = R.build_prompt({"problem": "invalid JSON",
                             "component": "self_observer"}, AXES)
    head = (REPO / "agents" / "core" / "self_observer.py").read_text(
        encoding="utf-8")[:120]
    assert head in prompt, "the real file content does not reach the prompt"


def test_the_grounding_is_the_production_builder_not_a_copy():
    """A second implementation would drift from the one the cycle runs."""
    import ast

    tree = ast.parse((REPO / "core" / "self_improve" / "requirer.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "real_code_context")
    imported = {a.name for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom)
                and n.module == "agents.core.self_modifier" for a in n.names}
    assert "_build_context" in imported, (
        "real_code_context no longer reuses the production context builder")


def test_grounding_that_fails_is_loud_not_silent(monkeypatch, capsys):
    """Grounding that silently vanishes puts the model straight back to
    imagining a codebase."""
    import agents.core.self_modifier as SM

    monkeypatch.setattr(SM, "_build_context",
                        lambda c, p: (_ for _ in ()).throw(RuntimeError("gone")))
    assert R.real_code_context("self_observer", "x") == ""
    out = capsys.readouterr().out
    assert "repo context UNAVAILABLE" in out


def test_ungrounded_is_possible_but_must_be_asked_for():
    """The default is grounded. A caller that wants the bare prompt has to say
    so, so grounding cannot be lost by omission."""
    bare = R.build_prompt({"problem": "p", "component": "self_observer"},
                          AXES, grounded=False)
    full = R.build_prompt({"problem": "p", "component": "self_observer"}, AXES)
    assert "REAL PATHS IN THIS REPO" not in bare
    assert len(full) > len(bare)


def test_the_prompt_forbids_code_in_as_many_words():
    """The instruction and the net are both required — the norm asks for a sharp
    instruction AND a mechanical net, not one standing in for the other."""
    prompt = R.build_prompt({"problem": "p"}, AXES)
    low = prompt.lower()
    assert "never write code" in low
    # The SUBSTANCE, not one word: the ban was spelled "FORBIDDEN:" until the
    # rules were numbered on 2026-09-08 and it became rule 4. Asserting the word
    # would have failed on a prompt that says the same thing more sharply.
    assert "no python" in low and "no snippet" in low
    assert "refused whole" in low
    assert "not cleaned up" in low
    for axis in sorted(AXES)[:3]:
        assert axis in prompt, "the model is not shown the real axis list"


# ---------------------------------------------------------------------------
# (d) IT WRITES ONLY UNDER THE EXPERIMENTAL TREE
# ---------------------------------------------------------------------------

def test_the_spec_is_written_outside_production_memory(tmp_path):
    out = R.write_spec(dict(GOOD_SPEC), out_dir=tmp_path / "specs")
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["goal_axis"] == AXIS

    assert "experiments" in str(R.SPEC_DIR), (
        f"the default spec directory is {R.SPEC_DIR}, which is not under the "
        f"experimental tree")
    assert "memory" not in R.SPEC_DIR.parts
    assert "snapshots" not in R.SPEC_DIR.parts


def test_the_problem_feed_is_read_only():
    """It reads self_observer's output; it must never write there."""
    tree = ast.parse((REPO / "core" / "self_improve" / "requirer.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "observations")
    writes = {n.attr for n in ast.walk(fn)
              if isinstance(n, ast.Attribute)
              and n.attr in ("write_text", "write_bytes", "mkdir", "unlink")}
    assert not writes, f"observations() writes: {writes}"


def test_only_write_spec_writes_at_all():
    """Every write in the module must be inside write_spec, which takes an
    out_dir. Nothing else may touch the filesystem."""
    tree = ast.parse((REPO / "core" / "self_improve" / "requirer.py")
                     .read_text(encoding="utf-8"))
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if fn.name in ("write_spec", "_selftest"):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("write_text", "write_bytes", "mkdir"), (
                    f"{fn.name} writes to disk at line {node.lineno}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
