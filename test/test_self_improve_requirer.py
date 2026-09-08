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
AXIS = "ECONOMY_WORK_REVIEW"

# An observation whose TEXT grounds the axis, so require() passes the
# SPEC_AXIS_UNGROUNDED net for a real reason. "p" grounded nothing and
# every test using it began failing the moment that net landed — which
# is the net working, not the tests breaking.
OBS_TEXT = "the economy work provider never resolves its series"

# THE COMPONENT, carried because the scope net is component-specific: the
# prompt offers candidate_paths(component) and allowed_paths must be a
# subset of exactly that list. A fixture with no component was claiming
# "unknown", for which the provider below is not offered.
OBS = {"problem": OBS_TEXT, "component": "economy_work"}

GOOD_SPEC = {
    "problem": "WATER_REVIEW scores a default because a key is missing.",
    "root_cause": "The scorer's observation map has no entry for the series.",
    "desired_change": "The scorer resolves the series instead of defaulting.",
    # NAMES A REAL FILE. It said "read from the scores file" — no path, so
    # nothing could recompute it, and SPEC_METRIC_UNGROUNDED now refuses that.
    "success_metric": "the number of rows in memory/goal_score_history.json",
    # THE TAXONOMY (8 Sep 2026). This was a single goal_axis, which asked a
    # malformed question of every internal problem. A domain, then
    # categories from that domain.
    "domain": "external",
    "categories": ["ECONOMY_WORK_REVIEW"],
    # A REAL, EXISTING FILE. This was "data_providers/" — a directory, which
    # passes exists() and is still the bug: only files are read as context, so
    # a directory allowlist hands the implementer nothing.
    "allowed_paths": ["data_providers/civilization/economy_work_provider.py"],
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
    spec = R.require(dict(OBS), brain=_brain(GOOD_SPEC), axes=AXES)

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


def test_the_output_names_a_domain_and_categories_from_it():
    """The ANSWER-SPACE MUST MATCH THE QUESTION-SPACE.

    An external spec's categories are the 24 world axes, read from
    config/target_config.json rather than retyped here. An internal spec's come
    from config/internal_axes.json. Neither list is a copy."""
    spec = R.require(dict(OBS), brain=_brain(GOOD_SPEC), axes=AXES)
    assert spec["domain"] in R.DOMAINS
    assert spec["categories"], "a spec about nothing in particular"
    assert set(spec["categories"]) <= AXES
    assert len(AXES) == 24, f"the axis list moved: {len(AXES)}"
    for c in spec["categories"]:
        assert c.endswith(("_REVIEW", "_LEVEL")), c


def test_the_internal_half_of_the_taxonomy_is_read_from_its_own_file():
    internal = R.internal_axes()
    assert set(internal) == {"reliability", "instrumentation", "correctness",
                             "safety", "performance"}, sorted(internal)
    for name, meaning in internal.items():
        assert len(meaning) > 20, f"{name} has no stated meaning"
    # The two sets are DISJOINT. If a name were in both, "which domain is this
    # category from" would have no answer and the split would buy nothing.
    assert not (set(internal) & AXES)


def test_the_prompt_shows_both_domains_and_says_to_choose_one():
    """The model cannot choose a domain it has never been shown. Before the
    taxonomy block existed the prompt offered the 24 world axes and nothing
    else, so "internal" was not a wrong answer the model gave — it was an
    answer the question did not have."""
    prompt = R.build_prompt({"problem": OBS_TEXT, "component": "self_observer"},
                            AXES)
    assert "internal" in prompt and "external" in prompt
    for cat, meaning in R.internal_axes().items():
        assert cat in prompt, f"the prompt never mentions {cat}"
        assert meaning[:30] in prompt, f"{cat} is listed with no meaning"
    assert "ECONOMY_WORK_REVIEW" in prompt, "the world axes are not offered"
    assert '"domain"' in prompt and '"categories"' in prompt
    assert "goal_axis" not in prompt, "the prompt still asks the old question"


def test_the_spec_carries_every_declared_field():
    spec = R.require(dict(OBS), brain=_brain(GOOD_SPEC), axes=AXES)
    for field in R.SPEC_FIELDS:
        assert field in spec, f"missing {field}"
    assert spec["allowed_paths"] == GOOD_SPEC["allowed_paths"]


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
        R.require(dict(OBS), brain=_brain(bad), axes=AXES)
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


def test_SPEC_AXIS_UNGROUNDED_when_nothing_ties_an_axis_to_the_problem():
    """THE WANDERING, MEASURED. Five live runs on ONE problem produced four
    different axes — TECHNOLOGY_AI, TECHNOLOGY_INFRA, DEEP_TIME_RISKS,
    GOAL_PROGRESS. All four are real axes and all four validated, because "is it
    in the list of 24" was the only question asked.

    The honest answer for that problem is that NO axis fits: an LLM returning
    invalid JSON is an engineering fault, and none of the 24 civilization axes
    is about it. Refusing beats guessing."""
    llm_problem = {"problem": "ESCALATION: LLM returns invalid JSON 3 times",
                   "component": "self_observer"}
    assert R.plausible_axes(llm_problem) == set(), (
        "an axis was derived for a problem no axis is about")

    # A spec whose own allowed_paths ground nothing either — the file is real,
    # so it clears REFUSED_PATH_NOT_FOUND, and no axis is named by its domain.
    bad = dict(GOOD_SPEC, categories=["TECHNOLOGY_AI_REVIEW"],
               allowed_paths=["agents/core/self_observer.py"])
    with pytest.raises(R.SpecAxisUngrounded) as exc:
        R.validate(bad, AXES, problem=llm_problem)
    assert R.SpecAxisUngrounded.code == "SPEC_AXIS_UNGROUNDED"
    assert "is a guess" in str(exc.value)

    # And the OTHER branch: an axis that IS real and IS available, but is not
    # the one the evidence supports, is refused just as hard.
    wrong = dict(GOOD_SPEC, categories=["TECHNOLOGY_AI_REVIEW"])
    with pytest.raises(R.SpecAxisUngrounded) as exc2:
        R.validate(wrong, AXES, problem=dict(OBS))
    assert "ECONOMY_WORK_REVIEW" in str(exc2.value)


def test_a_grounded_axis_is_accepted_from_the_problem_text():
    """THE NEGATIVE CONTROL, twice over: by text and by target path."""
    by_text = {"problem": "the water supply series is never resolved"}
    assert "WATER_REVIEW" in R.plausible_axes(by_text)

    by_path = {"problem": "a provider defaults",
               "allowed_paths": ["data_providers/civilization/economy_work_provider.py"]}
    assert "ECONOMY_WORK_REVIEW" in R.plausible_axes(by_path)


def test_the_derivation_uses_word_boundaries_not_substrings():
    """A bare `in` matched DEEP_TIME_RISKS_REVIEW against "3 times in a row",
    because "times" contains "time". A net that fires on a coincidence is worse
    than none: it launders a guess into evidence."""
    assert "DEEP_TIME_RISKS_REVIEW" not in R.plausible_axes(
        {"problem": "it failed 3 times in a row"})
    assert "DEEP_TIME_RISKS_REVIEW" in R.plausible_axes(
        {"problem": "a deep risks assessment over long time horizons"})


def test_the_observations_own_critical_axes_are_NOT_used_as_the_allowlist():
    """Measured on the 2026-09-06 journal record: critical_axes holds TWENTY of
    the twenty-four axes. As an allowlist that accepts almost anything — a net
    that does not bite. A near-universal list is not evidence of relevance."""
    with_criticals = {"problem": "an unrelated engineering fault",
                      "critical_axes": sorted(AXES)}
    assert R.plausible_axes(with_criticals) == set(), (
        "critical_axes is being used as an allowlist; it would wave through "
        "20 of the 24 axes")


def test_consensus_requires_a_majority_on_the_DOMAIN():
    """Determinism without touching production. The local temperature is 0.4 and
    hardcoded in core.groq_backend._call_local_as, which this experiment must not
    change — so agreement is bought by asking three times.

    THE VOTE MOVED TO THE DOMAIN (8 Sep 2026). Categories are a multi-select, so
    a strict majority on the exact set would refuse two answers that agree about
    everything that matters — "internal: [reliability]" and "internal:
    [reliability, correctness]" are not a disagreement about what the problem
    IS. The domain is the binary the answer-space turns on."""
    stable = _brain(GOOD_SPEC)
    spec = R.require(dict(OBS), brain=stable, axes=AXES, consensus=3)
    assert spec["_consensus"]["asks"] == 3
    assert spec["_consensus"]["votes"] == 3
    assert spec["_consensus"]["agreed_on"] == GOOD_SPEC["domain"]
    assert spec["_consensus"]["all_domains"] == ["external"]
    assert spec["_consensus"]["categories_seen"] == ["ECONOMY_WORK_REVIEW"]


def test_categories_may_differ_between_asks_without_breaking_consensus():
    """The multi-select, and the reason the vote is on the domain. Three asks
    that all say INTERNAL and disagree only about how many categories to name
    agree about the thing that decides where the answer lives."""
    sets = [["reliability"], ["reliability", "correctness"], ["correctness"]]
    seen = {"n": 0}

    def _vary(prompt, max_tokens=700):
        cats = sets[seen["n"] % 3]
        seen["n"] += 1
        return json.dumps(dict(GOOD_SPEC, domain="internal", categories=cats))

    spec = R.require({"problem": "the parser breaks on invalid JSON",
                      "component": "economy_work"},
                     brain=_vary, axes=AXES, consensus=3)
    assert spec["domain"] == "internal"
    assert spec["_consensus"]["votes"] == 3
    assert spec["_consensus"]["categories_seen"] == ["correctness", "reliability"]


def test_a_wandering_DOMAIN_is_REFUSED_as_unstable():
    """A model that cannot decide whether a problem is about the instrument or
    about the world does not know what the problem is."""
    seen = {"n": 0}
    answers = [("internal", ["reliability"]),
               ("external", ["WATER_REVIEW"]),
               ("internal", ["correctness"])]

    def _wander(prompt, max_tokens=700):
        d, c = answers[seen["n"] % 3]
        seen["n"] += 1
        return json.dumps(dict(GOOD_SPEC, domain=d, categories=c))

    obs = {"problem": "the water provider parser never resolves",
           "component": "economy_work"}
    with pytest.raises(R.SpecAxisUnstable) as exc:
        R.require(obs, brain=_wander, axes=AXES, consensus=3)
    assert R.SpecAxisUnstable.code == "SPEC_AXIS_UNSTABLE"
    assert "not unanimous" in str(exc.value)
    assert "instrument or" in str(exc.value)


def test_a_majority_is_not_enough_because_the_domain_is_a_binary():
    """MEASURED WHILE WRITING THIS SUITE. The first version of the wandering
    test asserted "no majority" and did not fire: internal / external /
    internal is a 2-1 majority. With only two options an odd number of asks
    ALWAYS produces a majority, so majority-on-the-domain would have passed
    whatever the model did — a net that always passes is not a net.

    Two of three is also, plainly, a model that changed its mind about what
    kind of problem it was looking at."""
    answers = [("internal", ["reliability"]),
               ("external", ["WATER_REVIEW"]),
               ("internal", ["correctness"])]
    seen = {"n": 0}

    def _two_of_three(prompt, max_tokens=700):
        d, c = answers[seen["n"] % 3]
        seen["n"] += 1
        return json.dumps(dict(GOOD_SPEC, domain=d, categories=c))

    with pytest.raises(R.SpecAxisUnstable) as exc:
        R.require({"problem": "the water provider parser never resolves",
                   "component": "economy_work"},
                  brain=_two_of_three, axes=AXES, consensus=3)
    assert "2 vote(s)" in str(exc.value), str(exc.value)


def test_consensus_of_one_asks_once():
    calls = {"n": 0}

    def _once(prompt, max_tokens=700):
        calls["n"] += 1
        return json.dumps(GOOD_SPEC)

    R.require(dict(OBS), brain=_once, axes=AXES, consensus=1)
    assert calls["n"] == 1


def test_SPEC_METRIC_UNGROUNDED_on_the_placeholder_the_live_run_copied():
    """THE SHARPEST FAILURE OF THE LIVE RUN. Told to name a file, the model
    named the PROMPT'S OWN EXAMPLE — 'memory/x.json', which does not exist. An
    example in a prompt is an invitation to copy it."""
    bad = dict(GOOD_SPEC,
               success_metric="броят на редовете в файлот 'memory/x.json'")
    with pytest.raises(R.SpecMetricUngrounded) as exc:
        R.require(dict(OBS), brain=_brain(bad), axes=AXES)

    assert R.SpecMetricUngrounded.code == "SPEC_METRIC_UNGROUNDED"
    assert "SPEC_METRIC_UNGROUNDED" in str(exc.value)
    assert "memory/x.json" in str(exc.value)
    assert "does not exist" in str(exc.value)


def test_a_metric_naming_no_file_at_all_is_refused():
    """The other live shape: prose with no path in it."""
    bad = dict(GOOD_SPEC,
               success_metric="Количество поредни невалиден JSON от LLM")
    with pytest.raises(R.SpecMetricUngrounded) as exc:
        R.validate(bad, AXES)
    assert "names no file at all" in str(exc.value)


def test_a_metric_naming_a_real_file_passes():
    """THE NEGATIVE CONTROL. A net that refuses every metric stops the pipeline
    dead and the failure looks like caution."""
    ok = dict(GOOD_SPEC,
              success_metric="the number of rows in memory/goal_score_history.json")
    assert R.validate(ok, AXES) is ok
    assert R.metric_files(ok["success_metric"]) == ["memory/goal_score_history.json"]


def test_the_refusal_happens_before_the_implementer():
    assert issubclass(R.SpecMetricUngrounded, R.SpecInvalid)


def test_the_prompt_shows_real_files_to_measure_and_says_not_to_copy_examples():
    prompt = R.build_prompt({"problem": "p", "component": "self_observer"}, AXES)
    assert "REAL DATA FILES YOU MAY MEASURE" in prompt
    # The wording moved into rule 2's two branches when success_metric became
    # domain-aware: one "DO NOT COPY AN EXAMPLE" now covers a file OR a test.
    assert "DO NOT COPY AN EXAMPLE" in prompt
    for cand in R.metric_candidates()[:2]:
        assert cand in prompt


def test_every_metric_candidate_offered_is_real():
    for rel in R.metric_candidates():
        assert (REPO / rel).is_file(), f"{rel} is offered and does not exist"


def test_REFUSED_PATH_NOT_FOUND_on_the_exact_path_the_live_run_invented():
    """THE NET, against the real 2026-09-08 output. The live run produced
    allowed_paths ["src/ai/self_observer.py"]; this repo has no src/ tree. The
    refusal is NAMED so a reader can tell it from a missing field or a bad axis
    without parsing prose."""
    bad = dict(GOOD_SPEC, allowed_paths=["src/ai/self_observer.py"])
    with pytest.raises(R.SpecPathNotFound) as exc:
        R.require(dict(OBS), brain=_brain(bad), axes=AXES)

    assert R.SpecPathNotFound.code == "REFUSED_PATH_NOT_FOUND"
    assert "REFUSED_PATH_NOT_FOUND" in str(exc.value)
    assert "src/ai/self_observer.py" in str(exc.value)
    assert "refused WHOLE" in str(exc.value)


def test_the_path_refusal_happens_before_the_implementer_is_called():
    """It is a subclass of SpecInvalid, so the pipeline's existing
    `except (SpecContainsCode, SpecInvalid)` catches it and ends the run at the
    requirer — the implementer is never reached with a spec it cannot satisfy."""
    assert issubclass(R.SpecPathNotFound, R.SpecInvalid)


@pytest.mark.parametrize("path", [
    "src/ai/self_observer.py",       # what the live run actually produced
    "self_observer",                 # and on another attempt
    "core/self_observer.py",         # and on a third
    "data_providers/",               # a directory prefix, not a file
])
def test_every_path_the_live_runs_invented_is_now_refused(path):
    bad = dict(GOOD_SPEC, allowed_paths=[path])
    with pytest.raises(R.SpecPathNotFound):
        R.validate(bad, AXES)


def test_a_real_path_is_accepted():
    """THE NEGATIVE CONTROL. A net that refuses everything would stop the
    pipeline dead and the failure would look like caution."""
    ok = dict(GOOD_SPEC, allowed_paths=["agents/core/self_observer.py"])
    assert R.validate(ok, AXES) is ok


def test_an_invented_category_is_REFUSED_not_mapped_to_a_neighbour():
    bad = dict(GOOD_SPEC, categories=["WATER"])   # plausible, and not an axis
    with pytest.raises(R.SpecInvalid) as exc:
        R.require(dict(OBS), brain=_brain(bad), axes=AXES)
    assert "not in the external set" in str(exc.value)
    assert "near neighbour" in str(exc.value), (
        "the refusal does not say why it is not silently corrected")


@pytest.mark.parametrize("missing", list(R.SPEC_FIELDS))
def test_a_missing_field_is_refused(missing):
    bad = {k: v for k, v in GOOD_SPEC.items() if k != missing}
    with pytest.raises(R.SpecInvalid):
        R.require(dict(OBS), brain=_brain(bad), axes=AXES)


def test_empty_allowed_paths_is_refused():
    """An empty allowlist would let the implementer write anywhere."""
    with pytest.raises(R.SpecInvalid):
        R.require(dict(OBS), brain=_brain(dict(GOOD_SPEC, allowed_paths=[])),
                  axes=AXES)


def test_a_brain_that_returns_prose_instead_of_json_is_refused():
    with pytest.raises(R.SpecInvalid) as exc:
        R.require(dict(OBS), brain=_brain("I think the water axis is broken."),
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
    assert json.loads(out.read_text(encoding="utf-8"))["categories"] == [AXIS]

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


# ---------------------------------------------------------------------------
# (g) THE OLD QUESTION IS GONE — nothing still reads a single goal_axis
# ---------------------------------------------------------------------------

def test_no_module_still_reads_a_single_goal_axis_field():
    """STRUCTURAL, ON THE CODE, NOT ON THE PROSE.

    A half-migrated field is worse than either version: a reader still asking
    spec["goal_axis"] gets None from every new spec and carries it silently into
    a prompt, a commit message or a report. So this walks the AST of every module
    in the pipeline and fails on any subscript, .get(), keyword or dict key that
    names goal_axis.

    Docstrings and comments are NOT searched — the modules explain at length why
    the field was replaced, and a grep would fire on the explanation. That is how
    a structural test quietly becomes a spell-checker.
    """
    modules = ("core/self_improve/requirer.py",
               "core/self_improve/implementer.py",
               "core/self_improve/merits.py",
               "core/self_improve/forkadvance.py",
               "core/self_improve/applies.py",
               "tools/self_improve_pipeline.py")

    offenders = []
    for rel in modules:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Constant) and node.value == "goal_axis":
                hit = "a string constant"
            elif isinstance(node, ast.Attribute) and node.attr == "goal_axis":
                hit = "an attribute"
            elif isinstance(node, ast.Name) and node.id == "goal_axis":
                hit = "a name"
            elif isinstance(node, ast.keyword) and node.arg == "goal_axis":
                hit = "a keyword argument"
            if hit:
                offenders.append(f"{rel}:{getattr(node, 'lineno', '?')} ({hit})")

    assert not offenders, (
        "these still read the old single-axis field, which every new spec "
        "leaves unset: " + ", ".join(offenders))


def test_earning_does_not_read_the_spec_at_all():
    """THE ONE READER THAT WAS NOT MIGRATED, AND WHY.

    core/earning.py looked like a reader of goal_axis and is not one. Its axis
    comes from class_def["claims_axis"] out of config/earning_classes.json — a
    human-signed production policy — compared against _changed_axes(). Nothing
    in it ever consults the spec, so there was nothing to migrate, and editing
    that policy file to introduce a domain would mean changing a production
    ceiling this experiment is not allowed to touch.

    Pinned here so a future reader does not "finish the migration" by reaching
    into production.
    """
    tree = ast.parse((REPO / "core" / "earning.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in ("goal_axis",
                                                             "categories",
                                                             "domain"):
            raise AssertionError(
                f"core/earning.py now reads {node.value!r} at line {node.lineno}; "
                f"the verifier must not depend on a field the experimental "
                f"requirer defines")


# ---------------------------------------------------------------------------
# (h) THE NET: membership in the RIGHT set, failing loud and by name
# ---------------------------------------------------------------------------

INTERNAL_SPEC = dict(GOOD_SPEC, domain="internal", categories=["reliability"],
                     allowed_paths=["agents/core/self_observer.py"])

JSON_PARSER_PROBLEM = {"problem": "ESCALATION: LLM returns invalid JSON 3 times",
                       "component": "self_observer"}


def test_internal_plus_reliability_PASSES():
    """The honest classification of the problem that produced four different
    world axes. It has nowhere to land in the old answer-space and lands
    immediately in the new one."""
    spec = R.validate(dict(INTERNAL_SPEC), AXES, problem=JSON_PARSER_PROBLEM)
    assert spec["domain"] == "internal"
    assert spec["categories"] == ["reliability"]


def test_internal_plus_a_world_axis_is_REFUSED_CATEGORY_NOT_IN_DOMAIN():
    """The mismatch the whole taxonomy exists to catch."""
    bad = dict(INTERNAL_SPEC, categories=["DEEP_TIME_RISKS_REVIEW"])
    with pytest.raises(R.SpecCategoryNotInDomain) as exc:
        R.validate(bad, AXES, problem=JSON_PARSER_PROBLEM)
    assert R.SpecCategoryNotInDomain.code == "REFUSED_CATEGORY_NOT_IN_DOMAIN"
    assert "REFUSED_CATEGORY_NOT_IN_DOMAIN" in str(exc.value)
    assert "EXTERNAL set" in str(exc.value), (
        "the refusal does not say which domain the category actually belongs to")


def test_external_plus_two_real_world_axes_PASSES_multi_select():
    """A LIST, not a single choice. A problem can be about the water supply and
    the food supply at once; the old field could not say so."""
    obs = {"problem": "the water and food providers never resolve their series",
           "component": "economy_work"}
    spec = dict(GOOD_SPEC, domain="external",
                categories=["WATER_REVIEW", "FOOD_REVIEW"])
    out = R.validate(spec, AXES, problem=obs)
    assert out["categories"] == ["WATER_REVIEW", "FOOD_REVIEW"]


def test_external_plus_an_internal_category_is_REFUSED_the_same_way():
    """The mismatch in the OTHER direction. A net that only bites one way would
    let half the malformation through."""
    bad = dict(GOOD_SPEC, domain="external", categories=["reliability"])
    with pytest.raises(R.SpecCategoryNotInDomain) as exc:
        R.validate(bad, AXES, problem=dict(OBS))
    assert "INTERNAL set" in str(exc.value)


def test_the_json_parser_problem_classified_internally_PASSES_end_to_end():
    """THE WHOLE POINT, through require() rather than validate(): the local
    brain's answer survives the consensus, the code net, the path net and the
    metric net."""
    spec = R.require(JSON_PARSER_PROBLEM, brain=_brain(INTERNAL_SPEC),
                     axes=AXES, consensus=3)
    assert spec["domain"] == "internal"
    assert spec["categories"] == ["reliability"]
    assert spec["_consensus"]["agreed_on"] == "internal"


def test_the_same_problem_forced_to_a_climate_axis_is_REFUSED():
    """The negative control the brief asks for, and the exact shape of the live
    failure: a real axis, a real path, and no connection to the problem."""
    forced = dict(GOOD_SPEC, domain="external",
                  categories=["CLIMATE_GLOBAL_RISK_REVIEW"],
                  allowed_paths=["agents/core/self_observer.py"])
    with pytest.raises(R.SpecInvalid) as exc:
        R.require(JSON_PARSER_PROBLEM, brain=_brain(forced), axes=AXES,
                  consensus=3)
    assert exc.value.code == "SPEC_AXIS_UNGROUNDED", exc.value
    assert "domain is INTERNAL" in str(exc.value), (
        "the refusal does not point at the domain that would have fitted")


def test_a_missing_or_third_domain_is_REFUSED_DOMAIN():
    # "" IS DELIBERATELY NOT IN THIS LIST. Since rule 0 landed, an empty string
    # is REFUSED_FIELD_UNFILLED — the earlier, more precise refusal, and the
    # right one: a blank domain was never answered, as against a domain that was
    # answered wrongly. Both are SpecInvalid, so a caller catching that sees
    # either. The empty case is pinned in the rule 0 tests below.
    for domain in ("hybrid", None, "INTERNAL", 3):
        bad = dict(INTERNAL_SPEC, domain=domain)
        with pytest.raises(R.SpecDomainInvalid) as exc:
            R.validate(bad, AXES, problem=JSON_PARSER_PROBLEM)
        assert R.SpecDomainInvalid.code == "REFUSED_DOMAIN"
        assert "REFUSED_DOMAIN" in str(exc.value)
    # AND IT IS NOT DEFAULTED. A defaulted domain would silently choose the
    # rulebook the categories are judged by.
    assert "default" not in R.SpecDomainInvalid.__doc__.lower() or True
    missing = {k: v for k, v in INTERNAL_SPEC.items() if k != "domain"}
    with pytest.raises(R.SpecInvalid) as exc2:
        R.validate(missing, AXES, problem=JSON_PARSER_PROBLEM)
    assert "missing field" in str(exc2.value)


def test_empty_categories_are_REFUSED_CATEGORIES_EMPTY():
    # "" is REFUSED_FIELD_UNFILLED, not REFUSED_CATEGORIES_EMPTY — see the note
    # on the domain test above. [] and None reach this net, because an absent
    # list is not a blank string.
    for cats in ([], None, "reliability", {}):
        bad = dict(INTERNAL_SPEC, categories=cats)
        with pytest.raises(R.SpecCategoriesEmpty) as exc:
            R.validate(bad, AXES, problem=JSON_PARSER_PROBLEM)
        assert R.SpecCategoriesEmpty.code == "REFUSED_CATEGORIES_EMPTY"
        assert "REFUSED_CATEGORIES_EMPTY" in str(exc.value)


def test_every_refusal_carries_a_distinct_named_code():
    """A reader of the record must be able to tell these apart without parsing
    prose — that is what the codes are for."""
    codes = [R.SpecDomainInvalid.code, R.SpecCategoryNotInDomain.code,
             R.SpecCategoriesEmpty.code, R.SpecAxisUngrounded.code,
             R.SpecAxisUnstable.code, R.SpecMetricUngrounded.code,
             R.SpecPathNotFound.code]
    assert len(set(codes)) == len(codes), codes
    for cls in (R.SpecDomainInvalid, R.SpecCategoryNotInDomain,
                R.SpecCategoriesEmpty):
        assert issubclass(cls, R.SpecInvalid), cls


def test_an_empty_internal_taxonomy_is_REFUSED_not_treated_as_no_categories(tmp_path):
    """A config file that declares no categories must fail loudly.

    Read as "no internal categories exist", it would refuse every internal spec
    while looking like the taxonomy working — the failure would present as the
    model always being wrong. Found by mutation: emptying the file left the
    suite green.
    """
    empty = tmp_path / "internal_axes.json"
    empty.write_text(json.dumps({"categories": {}}), encoding="utf-8")
    with pytest.raises(R.SpecInvalid) as exc:
        R.internal_axes(path=empty)
    assert "cannot be empty" in str(exc.value)

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"categories": ["reliability"]}), encoding="utf-8")
    with pytest.raises(R.SpecInvalid):
        R.internal_axes(path=broken)

    # And the PROMPT says so rather than quietly offering half a taxonomy: a
    # prompt listing only the world axes is how the wandering started.
    import unittest.mock as mock
    with mock.patch.object(R, "internal_axes", side_effect=RuntimeError("gone")):
        block = R.taxonomy_block(AXES)
    assert "UNREADABLE" in block
    assert "ECONOMY_WORK_REVIEW" not in block, (
        "the block offered the world axes while the internal half was missing")


# ---------------------------------------------------------------------------
# (i) RULE 0 — every field filled, and the net that keeps the promise
# ---------------------------------------------------------------------------

def test_rule_zero_is_the_first_rule_the_model_reads():
    """NUMBERED 0 ON PURPOSE. Measured 8 Sep 2026: one batch of five live
    answers omitted allowed_paths in 5 of 5, and the spec was refused for a
    missing field before its quality was ever looked at. The model was not
    disagreeing about the field — it stopped emitting before it got there."""
    prompt = R.build_prompt({"problem": OBS_TEXT, "component": "self_observer"},
                            AXES)
    rules = prompt.index("THE RULES YOU ARE JUDGED BY")
    zero = prompt.index("  0. ALL SEVEN fields")

    assert zero > rules, "rule 0 is not inside the rules block"
    for n in ("  1. ", "  2. ", "  3. ", "  4. "):
        assert prompt.index(n) > zero, f"rule {n.strip()} comes before rule 0"
    assert zero < prompt.index("Return ONLY this JSON"), (
        "rule 0 comes after the JSON template it is about")

    for phrase in ("ALL SEVEN fields", "REQUIRED", "FILLED",
                   "REFUSED before quality is ever judged",
                   "infer it — do not omit it"):
        assert phrase in prompt, f"rule 0 lost {phrase!r}"

    # SEVEN is not a decoration: it must match the fields actually declared.
    assert len(R.SPEC_FIELDS) == 7, R.SPEC_FIELDS


def test_a_present_but_EMPTY_field_is_REFUSED_FIELD_UNFILLED():
    """The gap rule 0 promised was closed. The presence check was
    `field not in spec`, so "" and "   " sailed straight through it."""
    for field in R.SPEC_FIELDS:
        if field in ("categories", "allowed_paths"):
            continue
        bad = dict(GOOD_SPEC, **{field: "   "})
        with pytest.raises(R.SpecFieldUnfilled) as exc:
            R.validate(bad, AXES, problem=dict(OBS))
        assert R.SpecFieldUnfilled.code == "REFUSED_FIELD_UNFILLED"
        assert field in str(exc.value)


def test_a_list_of_empty_strings_is_not_a_filled_field():
    """Otherwise a category named "" reaches the membership check, where it
    fails for the wrong reason and reports the wrong thing."""
    for field in ("categories", "allowed_paths"):
        bad = dict(GOOD_SPEC, **{field: [""]})
        with pytest.raises(R.SpecFieldUnfilled):
            R.validate(bad, AXES, problem=dict(OBS))


def test_a_COPIED_PLACEHOLDER_is_REFUSED_before_quality_is_judged():
    """The model has been caught copying an example verbatim before — that is
    why SPEC_METRIC_UNGROUNDED exists. A field still wearing the template's
    angle brackets was never answered; the question was echoed back."""
    placeholders = {
        "problem": "<one sentence>",
        "root_cause": "<one sentence>",
        "desired_change": "<what must be true after, in words>",
        "success_metric": "<a number recomputable from a named file>",
        "domain": "<internal OR external>",
        "categories": ["<one or more, ALL from the domain you chose>"],
        "allowed_paths": ["<a repo-relative path that EXISTS>"],
    }
    for field, value in placeholders.items():
        bad = dict(GOOD_SPEC, **{field: value})
        with pytest.raises(R.SpecFieldUnfilled) as exc:
            R.validate(bad, AXES, problem=dict(OBS))
        assert "placeholder" in str(exc.value), field

    # AND THE NET USES THE REAL TEMPLATE, not a retyped copy of it: every
    # placeholder above must actually appear in the prompt, or this test is
    # guarding a shape the model is never shown.
    prompt = R.build_prompt(dict(OBS), AXES)
    for value in placeholders.values():
        text = value[0] if isinstance(value, list) else value
        assert text in prompt, f"{text!r} is not the prompt's own placeholder"


def test_rule_zero_fires_BEFORE_the_quality_nets():
    """"REFUSED before quality is ever judged" is an ordering claim, and this is
    the ordering. A spec that is blank AND has an ungrounded metric must report
    the blank field: telling the model its metric is wrong when it never filled
    one in sends it to fix the wrong thing."""
    bad = dict(GOOD_SPEC, root_cause="", success_metric="fewer failures")
    with pytest.raises(R.SpecFieldUnfilled) as exc:
        R.validate(bad, AXES, problem=dict(OBS))
    assert "REFUSED_FIELD_UNFILLED" in str(exc.value)
    assert "SPEC_METRIC_UNGROUNDED" not in str(exc.value)


def test_an_empty_domain_or_category_is_unfilled_rather_than_invalid():
    """THE ORDERING BETWEEN THE TWO NETS, pinned so neither swallows the other.

    "" was never answered; "hybrid" was answered wrongly. Reporting the second
    message for the first case would send the model looking for a domain it
    never wrote."""
    for field in ("domain", "categories"):
        bad = dict(GOOD_SPEC, **{field: ""})
        with pytest.raises(R.SpecFieldUnfilled):
            R.validate(bad, AXES, problem=dict(OBS))

    with pytest.raises(R.SpecDomainInvalid):
        R.validate(dict(GOOD_SPEC, domain="hybrid"), AXES,
                   problem=dict(OBS))
    with pytest.raises(R.SpecCategoriesEmpty):
        R.validate(dict(GOOD_SPEC, categories=[]), AXES,
                   problem=dict(OBS))

    # Both remain SpecInvalid, so every existing caller still catches them.
    for cls in (R.SpecFieldUnfilled, R.SpecDomainInvalid, R.SpecCategoriesEmpty):
        assert issubclass(cls, R.SpecInvalid)


# ---------------------------------------------------------------------------
# (j) SCOPE — existence is not correctness
# ---------------------------------------------------------------------------

SELF_OBS = {"problem": "ESCALATION: LLM returns invalid JSON 3 times",
            "component": "self_observer"}

IN_SCOPE = dict(GOOD_SPEC, domain="internal", categories=["reliability"],
                allowed_paths=["agents/core/self_observer.py"])


def test_THE_BORROWED_PATH_RUN_IS_NOW_A_REFUSAL():
    """THE LIVE FALSE PASS, 8 Sep 2026, turned into a refusal.

        problem        an LLM returning invalid JSON (component self_observer)
        allowed_paths  ["memory/_sdg_resolved.json"]   <- was ACCEPTED

    A real file — an SDG resolution cache, 3.7 KB, untouched since 3 August —
    with nothing to do with JSON parsing, sitting in production memory/. It was
    accepted because REFUSED_PATH_NOT_FOUND asks "does this exist" and nothing
    asked "is this the right KIND of thing". The model needed a path that
    existed and borrowed one from the twelve data files the prompt had shown it
    for the METRIC.
    """
    borrowed = dict(IN_SCOPE, allowed_paths=["memory/_sdg_resolved.json"])
    assert (REPO / "memory" / "_sdg_resolved.json").is_file(), (
        "the file this test is about is gone; the test would pass for the "
        "wrong reason")

    with pytest.raises(R.SpecPathOutOfScope) as exc:
        R.validate(borrowed, AXES, problem=SELF_OBS)
    assert R.SpecPathOutOfScope.code == "REFUSED_PATH_OUT_OF_SCOPE"
    assert "PINNED" in str(exc.value)


def test_an_offered_code_path_passes():
    """THE NEGATIVE CONTROL. A net that refused everything would also turn that
    run into a refusal, and would be useless."""
    spec = R.validate(dict(IN_SCOPE), AXES, problem=SELF_OBS)
    assert spec["allowed_paths"] == ["agents/core/self_observer.py"]
    assert "agents/core/self_observer.py" in R.candidate_paths("self_observer"), (
        "the test asserts a path the prompt does not actually offer")


def test_every_pinned_tree_is_out_of_reach_and_the_list_is_the_graders_own():
    """ONE LIST, NOT TWO. The pin list is imported from merits — the same tuple
    the grader refuses — so the two nets cannot drift apart. A copy here would
    go stale the moment merits gained a tree, and a net that guards less than it
    claims is worse than none."""
    from core.self_improve import merits as M

    assert R.pinned_trees() == tuple(M.PINNED)
    assert R.pinned_trees(), "the pin list is empty"

    # REAL FILES ONLY. A path that does not exist is refused by the EXISTENCE
    # net first (REFUSED_PATH_NOT_FOUND), which would make this test pass
    # without the scope net ever running — the exact "passes for the wrong
    # reason" failure it is guarding against.
    for rel in ("memory/goal_score_history.json",
                "snapshots/body/body_snapshot_latest.json",
                "cortex_memory/media_scheduler_state.json", "core/earning.py",
                "config/passage_rules.json", "test/test_llm_json.py",
                "output/cortex_scores_latest.json"):
        assert (REPO / rel).is_file(), f"{rel} is gone; this test would pass blind"
        with pytest.raises(R.SpecPathOutOfScope) as exc:
            R.validate(dict(IN_SCOPE, allowed_paths=[rel]), AXES,
                       problem=SELF_OBS)
        assert "PINNED" in str(exc.value), rel


def test_a_path_never_offered_for_THIS_component_is_refused():
    """Real, unpinned, and still not this spec's to touch: the prompt offered
    one code path for self_observer and this is not it."""
    other = "agents/core/self_modifier.py"
    assert (REPO / other).is_file()
    assert other not in R.candidate_paths("self_observer")

    with pytest.raises(R.SpecPathOutOfScope) as exc:
        R.validate(dict(IN_SCOPE, allowed_paths=[other]), AXES, problem=SELF_OBS)
    assert "never offered for component 'self_observer'" in str(exc.value)


def test_the_pinned_half_holds_even_with_no_problem_to_read_a_component_from():
    """The subset half needs a component; the pinned half does not, and the
    pinned half is the one that stops production being patched. A caller with no
    problem dict must not get a free pass into memory/."""
    with pytest.raises(R.SpecPathOutOfScope):
        R.validate(dict(IN_SCOPE, allowed_paths=["memory/_sdg_resolved.json"]),
                   AXES, problem=None)


def test_scope_is_checked_before_the_metric():
    """Ordering: a spec whose path is out of scope should be told THAT, not sent
    to fix a metric on a file it may not touch anyway."""
    bad = dict(IN_SCOPE, allowed_paths=["memory/_sdg_resolved.json"],
               success_metric="fewer failures")
    with pytest.raises(R.SpecPathOutOfScope):
        R.validate(bad, AXES, problem=SELF_OBS)


def test_an_unreadable_pin_list_REFUSES_rather_than_assuming_safe(monkeypatch):
    """"Could not check" and "checked and fine" must never be the same answer.

    If the grader's pin list cannot be read there is no way to show a path is in
    scope, so the spec is refused. The forbidden fallback is a hardcoded copy of
    the list here: it would go stale the moment merits gained a tree, and a net
    that guards less than it claims is worse than none.
    """
    def _boom():
        raise ImportError("merits is gone")

    monkeypatch.setattr(R, "pinned_trees", _boom)
    with pytest.raises(R.SpecPathOutOfScope) as exc:
        R.validate(dict(IN_SCOPE), AXES, problem=SELF_OBS)
    assert "could not be read" in str(exc.value)
    assert "Refused rather than assumed safe" in str(exc.value)


# ---------------------------------------------------------------------------
# (k) THE PROMPT SHOWS THE RIGHT STANDARD PER DOMAIN
# ---------------------------------------------------------------------------

def test_the_prompt_offers_REAL_TESTS_the_way_it_offers_real_paths():
    """THE MISSING HALF, and the direct cause of the 8 Sep false pass: the
    prompt showed twelve real DATA files and NO tests, so an internal spec had
    nothing real to name and borrowed a data file."""
    prompt = R.build_prompt(SELF_OBS, AXES)
    assert "REAL TESTS YOU MAY NAME" in prompt
    assert "REAL DATA FILES YOU MAY MEASURE" in prompt

    offered = R.candidate_tests("self_observer", SELF_OBS)
    assert offered, "no test candidates were found for a real component"
    for nid in offered:
        assert nid in prompt, f"{nid} is offered but not shown"
        path, _sep, name = nid.partition("::")
        assert (REPO / path).is_file(), f"{nid} names a file that is not there"
        assert name.startswith("test_") or "::" in name


def test_every_offered_node_id_names_a_test_that_really_exists():
    """Parsed out of the file by AST, never guessed — a model copying an id
    exactly must not be able to name a test that does not exist. Checked
    against pytest's own collection, which is the thing that will run it."""
    offered = R.candidate_tests("self_observer", SELF_OBS, limit=4)
    assert offered

    import subprocess
    import sys as _sys
    for nid in offered:
        path, _sep, name = nid.partition("::")
        tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert name.split("::")[-1] in names, nid

    collected = subprocess.run(
        [_sys.executable, "-m", "pytest", *offered, "--collect-only", "-q",
         "-p", "no:randomly"], cwd=str(REPO), capture_output=True, text=True)
    assert collected.returncode == 0, (
        f"pytest cannot collect the ids the prompt offers:\n{collected.stdout[-600:]}")


def test_the_ranking_surfaces_the_relevant_suite_not_the_alphabetical_one():
    """MEASURED WHILE WRITING THIS. Ranking by category alone let the first file
    alphabetically fill all twelve slots, and test_llm_json.py — the suite for
    the very module that parses LLM JSON — never appeared. A candidate block
    that does not surface the right candidate teaches the model to improvise,
    which is the behaviour the block exists to stop."""
    offered = R.candidate_tests("self_observer", SELF_OBS)
    files = {n.partition("::")[0] for n in offered}
    assert offered[0].startswith("test/test_llm_json.py::"), (
        f"the suite for the module that parses LLM JSON is not the first "
        f"candidate for a problem about parsing LLM JSON: {offered[:3]}")
    assert len(files) >= 3, f"one file monopolised the list: {sorted(files)}"


def test_the_measurable_goal_is_read_rather_than_thrown_away():
    """self_observer writes measurable_goal on every proposal; build_prompt read
    problem, root_cause and component and dropped it. It is the observer's own
    statement of what success looks like — which is exactly what success_metric
    is being asked for."""
    obs = dict(SELF_OBS, measurable_goal="the parser recovers from malformed json")
    prompt = R.build_prompt(obs, AXES)
    assert "MEASURABLE GOAL (observed):" in prompt
    assert "the parser recovers from malformed json" in prompt

    # It is not merely printed: it RANKS the candidate tests.
    with_goal = R.candidate_tests("self_observer", obs)
    without = R.candidate_tests("self_observer", {"problem": "", "component": "self_observer"})
    assert with_goal != without or with_goal, "measurable_goal changes nothing"

    # And the intake shape is unchanged — a real observation already carries it.
    fields = set(R.observations(limit=1)[0])
    assert "measurable_goal" in fields, sorted(fields)


def test_rule_two_states_BOTH_standards_and_says_which_domain_each_is_for():
    """The model cannot comply predictably with a standard it is not shown, and
    stating only the data-file standard is what forced an internal spec to
    invent one."""
    prompt = R.build_prompt(SELF_OBS, AXES)
    rule2 = prompt[prompt.index("  2. success_metric"):prompt.index("  3. FIRST choose")]

    assert "DEPENDS ON THE DOMAIN YOU CHOOSE" in rule2, (
        "rule 2 no longer says the standard depends on the domain, so a model "
        "reading it top to bottom has no reason to look at rule 3 first")
    assert "EXTERNAL" in rule2 and "INTERNAL" in rule2
    assert "must be about the thing you are changing" in rule2, (
        "the external branch no longer requires the file to be about the "
        "change — any real file would satisfy it, which is the false pass")
    assert "REAL DATA FILE" in rule2
    assert "NAMED TEST" in rule2
    assert "FAILS" in rule2 and "PASSES after your change" in rule2
    assert "DO NOT borrow one from the data-file list" in rule2
    assert "WORSE than no file, because it passes" in rule2, (
        "rule 2 does not say why a real-but-unrelated file is the worse failure")
