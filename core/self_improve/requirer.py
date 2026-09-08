#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/requirer.py — THE BRAIN WRITES A SPEC. NEVER CODE.

EXPERIMENTAL, not wired into the cycle. Writes only under
experiments/self_improve/specs/ — never production memory/ or snapshots/.

THE SPLIT POINT, READ OUT OF THE PRODUCTION CODE (2026-09-08)
--------------------------------------------------------------
agents/core/self_modifier.py already separates the two jobs and crosses the line
in exactly one place:

    run()                    lines 254-374
      :299-304   the SPEC is UNPACKED from self_observer's proposal —
                 component / problem / solution / measurable_goal / root_cause
      :313       _problem_already_attempted    still spec-side
      :319       evaluate_proposal_alignment   still spec-side
      :334-335   context = _build_context(...)
                 result  = _generate_solution(...)   <-- THE SPLIT POINT
    _generate_solution()     lines 423-512
      :436-448   the prompt turns from describing the problem to demanding
                 "Напиши Python patch"
      :486       call_groq(prompt, max_tokens=1000)  <-- one model does both

Everything before line 335 is specification. Everything after is code
generation. Today the SAME ladder call serves both, so the model that knows this
system best is also the model asked to write Python — and it is measured at 0/3
on closing the write->test->fix loop.

This module owns the first half only. It emits a SPEC and stops.

WHAT IT REFUSES TO DO, AND THE NET BEHIND THE REFUSAL
------------------------------------------------------
It must not emit code. Saying so in a prompt is not enough — that is precisely
the instruction a helpful model satisfies in letter (a "tiny example") while
breaking in spirit. So there is a mechanical net: _reject_code() parses every
free-text field and REFUSES the spec if it parses as Python or carries the
shapes of it (def/import/fences/assignment). A spec carrying code raises
SpecContainsCode; it is never silently cleaned up, because a stripped-out
snippet would hide that the split failed.

FORBIDDEN FALLBACKS, NAMED
  * do NOT strip code out and keep the spec — refusing loudly is the success
    state here;
  * do NOT invent a category, and do NOT reach across the domains. An
    internal spec's categories come from config/internal_axes.json and an
    external spec's from config/target_config.json; a category from the other
    domain is refused rather than mapped to a near neighbour, because it is not
    a near miss but the wrong question;
  * do NOT fall back to the cloud ladder when the local brain is down. The
    requirer's whole point is WHICH model does this job; a silent upgrade would
    erase the experiment.

    venv\\Scripts\\python.exe core/self_improve/requirer.py --selftest
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET_CONFIG = REPO / "config" / "target_config.json"
JOURNAL = REPO / "memory" / "development_journal.json"
PROPOSALS = REPO / "memory" / "improvement_proposals.json"

# EXPERIMENTAL TREE. Deliberately not memory/ — nothing here may enter the
# record the nightly cycle reads.
SPEC_DIR = REPO / "experiments" / "self_improve" / "specs"

INTERNAL_AXES = REPO / "config" / "internal_axes.json"

# THE ANSWER-SPACE MUST MATCH THE QUESTION-SPACE (ratified 8 Sep 2026).
#
# This was ("...", "goal_axis", "allowed_paths") — ONE field, single-select over
# the 24 world axes. That question is malformed for half the problems the feed
# carries. A self-improvement is either INTERNAL (it improves the instrument) or
# EXTERNAL (it improves how the instrument measures the world), and an internal
# fix — a JSON parser that breaks on a model's output — maps to NO world axis.
# Asked to name one anyway, the model wanders: five live runs on that exact
# problem produced FOUR different world axes, every one real, every one a guess.
#
# So the field is replaced, not patched: a DOMAIN, and one or MORE categories
# drawn from that domain's own set.
SPEC_FIELDS = ("problem", "root_cause", "desired_change", "success_metric",
               "domain", "categories", "allowed_paths")

DOMAINS = ("internal", "external")
_FREE_TEXT = ("problem", "root_cause", "desired_change", "success_metric")


class SpecContainsCode(Exception):
    """The brain emitted code. Refused, never cleaned up."""


class SpecInvalid(Exception):
    """The spec is missing a field, or names an axis that does not exist."""


class SpecAxisUngrounded(SpecInvalid):
    """SPEC_AXIS_UNGROUNDED — the axis is not plausibly tied to the problem.

    Live on 2026-09-08, five runs on ONE problem produced four different axes:
    TECHNOLOGY_AI_REVIEW, TECHNOLOGY_INFRA_REVIEW, DEEP_TIME_RISKS_REVIEW,
    GOAL_PROGRESS_REVIEW. Every one is a real axis and the field passed
    validation, because "is it in the list" was the only question being asked.
    Wandering across four answers for one problem is the signature of a model
    guessing, and a guess that validates is worse than a refusal.
    """
    code = "SPEC_AXIS_UNGROUNDED"


class SpecAxisUnstable(SpecInvalid):
    """SPEC_AXIS_UNSTABLE — repeated asks did not agree on an axis.

    The local model's temperature is 0.4 and fixed in production
    (groq_backend._call_local_as), which this experiment must not change. So
    determinism is bought with CONSENSUS instead: ask N times and require a
    majority. No majority means the model does not know, and saying so is the
    honest output.
    """
    code = "SPEC_AXIS_UNSTABLE"


class SpecDomainInvalid(SpecInvalid):
    """REFUSED_DOMAIN — the spec names no domain, or one that does not exist.

    The domain is the field the whole answer-space turns on: it decides WHICH
    SET the categories are checked against. A spec with no domain cannot be
    checked against anything, and one with a third domain is asking to be judged
    by a rulebook that does not exist. Neither is defaulted to "external" —
    defaulting here would reintroduce the exact malformation the taxonomy was
    built to end, silently and with no record that a guess was made.
    """
    code = "REFUSED_DOMAIN"


class SpecCategoryNotInDomain(SpecInvalid):
    """REFUSED_CATEGORY_NOT_IN_DOMAIN — a category from the OTHER domain.

    The sharpest failure the taxonomy can catch, and the one it exists for: an
    internal fix labelled with a world axis. It is not a near miss to be mapped
    to a neighbour — a JSON parser is not 12% about DEEP_TIME_RISKS. It is the
    wrong question, and the refusal says so by name so a reader of the record
    can tell it from an invented category or a missing field without parsing
    prose.
    """
    code = "REFUSED_CATEGORY_NOT_IN_DOMAIN"


class SpecCategoriesEmpty(SpecInvalid):
    """REFUSED_CATEGORIES_EMPTY — the list is missing, empty or not a list.

    A spec about nothing in particular cannot be judged against anything in
    particular. The forbidden fallback is accepting [] and treating the domain
    alone as the classification: "internal" is where the problem lives, not what
    the problem is.
    """
    code = "REFUSED_CATEGORIES_EMPTY"


class SpecFieldUnfilled(SpecInvalid):
    """REFUSED_FIELD_UNFILLED — a field is present, empty, or still a placeholder.

    RULE 0 IN THE PROMPT SAYS ALL SEVEN FIELDS MUST BE FILLED IN, and an
    instruction the net does not keep is worse than no instruction: it teaches a
    reader that something is checked when it is not. The presence check was
    `field not in spec`, so "" and "   " sailed through, and so did the
    template's own angle-bracket placeholders — the model has already been
    caught copying an example verbatim once, which is why
    SPEC_METRIC_UNGROUNDED exists.

    Refused BEFORE quality is judged, exactly as the rule promises: there is no
    point asking whether a root_cause is well grounded when it is the empty
    string.
    """
    code = "REFUSED_FIELD_UNFILLED"


class SpecMetricUngrounded(SpecInvalid):
    """SPEC_METRIC_UNGROUNDED — the success_metric names no file that exists.

    Measured live on 2026-09-08, after the path net landed and the paths came
    back real. The metric did not:

        "Количество поредни невалиден JSON от LLM"     — names no file at all
        "броят на редовете в файлот 'memory/x.json'"   — copied the PROMPT'S OWN
                                                         placeholder verbatim;
                                                         memory/x.json does not
                                                         exist

The second is the sharper failure: told to name a file, the model named the
    example. A metric nobody can recompute cannot be checked, and an unchecked
    claim is the FABRICATED verdict execute_patches already learned to refuse —
    "a number that came from no file is not a measurement, it is a decoration".
    """
    code = "SPEC_METRIC_UNGROUNDED"


class SpecPathNotFound(SpecInvalid):
    """REFUSED_PATH_NOT_FOUND — allowed_paths names something that is not there.

    A NAMED refusal, raised BEFORE the implementer is ever called. On 2026-09-08
    a live run produced allowed_paths ["src/ai/self_observer.py"] and the cloud
    model then wrote a competent patch to it. The scope check passed, because it
    compared the diff against the SPEC and the two hallucinations agreed with
    each other. Only the ceiling stood between that and a "clean" run.

    The refusal carries its own name so a reader of the record can tell THIS
    failure from a missing field or a bad axis without parsing prose.
    """
    code = "REFUSED_PATH_NOT_FOUND"


# ---------------------------------------------------------------------------
# the real axes
# ---------------------------------------------------------------------------

def real_axes(path: Path | None = None) -> set:
    """The 24 axis names out of config/target_config.json.

    They live one level down, inside the five goal groups, so this walks rather
    than assuming a flat list. Never invented, never hardcoded here: a copy of a
    declared list goes stale silently.
    """
    doc = json.loads((path or TARGET_CONFIG).read_text(encoding="utf-8"))
    axes = set()
    for group, body in doc.items():
        if group.startswith("_") or not isinstance(body, dict):
            continue
        sub = body.get("axes") if isinstance(body.get("axes"), dict) else {
            k: v for k, v in body.items() if isinstance(v, dict)}
        axes.update(sub)
    return axes


def internal_axes(path: Path | None = None) -> dict:
    """{category: one-line meaning} out of config/internal_axes.json.

    The INTERNAL half of the taxonomy: what an improvement to the INSTRUMENT can
    be about, as against the 24 axes that describe the WORLD it measures. Read
    from the file for the same reason real_axes() is — a copy of a declared list
    goes stale silently, and this one is shown to the model verbatim.
    """
    doc = json.loads((path or INTERNAL_AXES).read_text(encoding="utf-8"))
    cats = doc.get("categories")
    if not isinstance(cats, dict) or not cats:
        raise SpecInvalid(
            f"{(path or INTERNAL_AXES).name} declares no categories. The "
            f"internal half of the taxonomy cannot be empty: a spec would have "
            f"nowhere valid to land and every internal problem would be refused.")
    return {str(k): str(v) for k, v in cats.items()}


def domain_categories(domain: str, axes: set | None = None) -> set:
    """The set a category must belong to, for THIS domain. The whole point of
    the split: membership is checked against the right set, not against a union
    of both, because a union would accept exactly the mismatch that is malformed.
    """
    if domain == "external":
        return set(axes if axes is not None else real_axes())
    if domain == "internal":
        return set(internal_axes())
    return set()


# ---------------------------------------------------------------------------
# the net: no code, at all
# ---------------------------------------------------------------------------

_CODE_MARKERS = (
    re.compile(r"```"),                       # a fenced block
    re.compile(r"^\s*(def|class|import|from)\s+\w", re.M),
    re.compile(r"\b(json\.loads|read_text|write_text|open\s*\(|subprocess)\b"),
    re.compile(r"^\s*#!\s*/usr/bin/env python", re.M),
)


def _looks_like_code(text: str) -> str:
    """'' if clean, else the reason it is not.

    Two independent checks, because either alone is easy to slip past: the
    regexes catch the SHAPES of Python, and ast.parse catches a snippet with none
    of those shapes that is nonetheless a program. A short prose sentence parses
    as an expression statement, so a bare parse is not enough on its own — the
    parse only counts when the text also contains a statement keyword or an
    assignment.
    """
    if not isinstance(text, str):
        return ""
    for rx in _CODE_MARKERS:
        if rx.search(text):
            return f"matches a code marker: {rx.pattern}"
    if "=" in text and "\n" in text:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.FunctionDef,
                                 ast.ClassDef, ast.Import, ast.ImportFrom,
                                 ast.For, ast.While, ast.If)):
                return f"parses as Python ({type(node).__name__})"
    return ""


def _reject_code(spec: dict) -> None:
    for field in _FREE_TEXT:
        why = _looks_like_code(spec.get(field, ""))
        if why:
            raise SpecContainsCode(
                f"field {field!r} contains code — {why}. The requirer emits a "
                f"SPECIFICATION and never an implementation; the spec is refused "
                f"rather than stripped, because a cleaned-up snippet would hide "
                f"that the split failed.")


# The template's own placeholders. A field still wearing one was never
# answered — the model echoed the question back.
_PLACEHOLDER = re.compile(r"^\s*<.*>\s*$", re.S)


def _require_filled(spec: dict) -> None:
    """REFUSED_FIELD_UNFILLED — every declared field carries an actual answer.

    Lists (categories, allowed_paths) are checked element by element: a list of
    one empty string is not a filled field, and it would otherwise reach the
    membership checks as a category named "".
    """
    empty, placeheld = [], []
    for field in SPEC_FIELDS:
        value = spec.get(field)
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str):
                if not item.strip():
                    empty.append(field)
                elif _PLACEHOLDER.match(item):
                    placeheld.append(f"{field}={item.strip()[:40]!r}")
    if empty or placeheld:
        parts = []
        if empty:
            parts.append(f"empty: {sorted(set(empty))}")
        if placeheld:
            parts.append(f"still the template placeholder: {placeheld}")
        raise SpecFieldUnfilled(
            f"{SpecFieldUnfilled.code}: {'; '.join(parts)}. Rule 0 says all "
            f"seven fields are required and must be FILLED IN, and this is that "
            f"rule's net: a field that is present but blank, or that still "
            f"carries the angle-bracket example from the prompt, was never "
            f"answered. It is refused before quality is judged, because there "
            f"is nothing to judge.")


def validate(spec: dict, axes: set | None = None,
             problem: dict | None = None) -> dict:
    """Refuse anything that is not a well-formed, code-free spec."""
    if not isinstance(spec, dict):
        raise SpecInvalid(f"spec is {type(spec).__name__}, not an object")
    missing = [f for f in SPEC_FIELDS if f not in spec]
    if missing:
        raise SpecInvalid(f"missing field(s): {', '.join(missing)}")

    # RULE 0'S NET. Present is not the same as filled: "" and "   " passed the
    # check above, and so did the prompt's own "<one sentence>" placeholders.
    _require_filled(spec)

    known = axes if axes is not None else real_axes()

    # THE TAXONOMY. A domain first, then categories from THAT domain's set.
    # Checking against a union of both sets would accept the exact mismatch the
    # split exists to catch — an internal fix labelled with a world axis.
    domain = spec.get("domain")
    if domain not in DOMAINS:
        raise SpecDomainInvalid(
            f"{SpecDomainInvalid.code}: domain {domain!r} is not one of "
            f"{list(DOMAINS)}. Every self-improvement is either INTERNAL (it "
            f"improves the instrument) or EXTERNAL (it improves how the "
            f"instrument measures the world); there is no third place for one "
            f"to be, and nothing is defaulted — a defaulted domain would pick "
            f"the rulebook the categories are judged by, silently.")

    cats = spec.get("categories")
    if not isinstance(cats, list) or not cats:
        raise SpecCategoriesEmpty(
            f"{SpecCategoriesEmpty.code}: categories is {cats!r}; it must be a "
            f"non-empty list. A spec about nothing in particular cannot be "
            f"judged against anything in particular, and the domain alone is "
            f"where the problem lives, not what the problem is.")

    allowed = domain_categories(domain, known)
    wrong = [c for c in cats if c not in allowed]
    if wrong:
        other = "internal" if domain == "external" else "external"
        crossed = [c for c in wrong if c in domain_categories(other, known)]
        detail = (f" {crossed} belong{'s' if len(crossed) == 1 else ''} to the "
                  f"{other.upper()} set — that is not a near miss, it is the "
                  f"wrong question."
                  if crossed else " No domain declares them.")
        raise SpecCategoryNotInDomain(
            f"{SpecCategoryNotInDomain.code}: {wrong} "
            f"{'is' if len(wrong) == 1 else 'are'} not in the {domain} set "
            f"{sorted(allowed)}.{detail} Refused rather than mapped to a near "
            f"neighbour: a parser bug is not twelve per cent about "
            f"DEEP_TIME_RISKS.")

    paths = spec.get("allowed_paths")
    if not isinstance(paths, list) or not paths:
        raise SpecInvalid("allowed_paths must be a non-empty list")
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            raise SpecInvalid(f"allowed_paths carries {p!r}")

    # ── THE NET (8 Sep 2026): REFUSED_PATH_NOT_FOUND ──────────────────────
    # The instruction says the paths must exist and the prompt now shows the
    # real ones. Neither can stop a model that writes a plausible path anyway,
    # and on 2026-09-08 three runs out of three did exactly that. So the spec is
    # REFUSED here, by name, before the implementer is ever called — because a
    # patch written against a file that does not exist cannot be judged, only
    # believed.
    # is_file(), NOT exists(): a DIRECTORY passes exists() and is still the
    # bug. _read_allowed_files() only reads files, so a directory allowlist
    # hands the implementer an EMPTY context and puts it straight back to
    # inventing code that fits the words. Requiring a file is what makes the
    # grounding guaranteed rather than likely — "data_providers/" was the
    # fixture that quietly did exactly this until 5b0bcd5.
    missing = [p for p in paths if not (REPO / p).is_file()]
    if missing:
        raise SpecPathNotFound(
            f"{SpecPathNotFound.code}: allowed_paths names "
            f"{', '.join(repr(m) for m in missing)}, which do not exist in this "
            f"repo. The spec is refused WHOLE and the implementer is never "
            f"called: a patch written against a file that is not there cannot be "
            f"judged, only believed. Choose from the real paths the prompt "
            f"listed.")

    _reject_code(spec)
    _require_grounded_metric(spec)
    _require_grounded_axis(spec, problem)
    return spec


# Words that appear in an axis name and carry no meaning about a problem.
_AXIS_STOP = {"review", "at", "human", "level", "and", "the", "of"}


def plausible_axes(problem: dict, axes: set | None = None) -> set:
    """The axes a problem is PLAUSIBLY about, derived from evidence.

    Two signals, both grounded in something real:

      1. TOKEN OVERLAP with the problem text — an axis named WATER_REVIEW is
         plausible for a problem that says "water".
      2. THE TARGET FILE'S DOMAIN — data_providers/<domain>/<axis>_provider.py
         and snapshots/<domain>/ name their axis directly, so a spec whose
         allowed_paths points at one is about that axis.

    DELIBERATELY NOT USED: the observation's own `critical_axes`. Measured on
    the 2026-09-06 journal record, that list holds TWENTY of the twenty-four
    axes — as an allowlist it would accept almost anything, which is a net that
    does not bite. A near-universal list is not evidence of relevance.

    An EMPTY result is a real answer, not a failure of the function: some
    problems are engineering faults that no civilization axis is about.
    """
    known = axes if axes is not None else real_axes()
    text = " ".join(str(problem.get(k, "")) for k in
                    ("problem", "root_cause", "component", "desired_change")).lower()
    out = set()

    # WORD BOUNDARIES, not substrings. A bare `in` matched DEEP_TIME_RISKS_REVIEW
    # against "returns invalid JSON 3 times in a row" — because "times" contains
    # "time" — and produced exactly the kind of spurious tie this net exists to
    # refuse. A net that fires on a coincidence is worse than none: it launders
    # a guess into evidence.
    for axis in known:
        toks = [t.lower() for t in axis.split("_")
                if t.lower() not in _AXIS_STOP and len(t) >= 4]
        if any(re.search(r"\b" + re.escape(t) + r"\b", text) for t in toks):
            out.add(axis)

    for rel in (problem.get("allowed_paths") or []):
        stem = str(rel).replace("\\", "/").split("/")[-1]
        for axis in known:
            head = axis.replace("_REVIEW", "").lower()
            if head and (head in stem.lower() or head in str(rel).lower()):
                out.add(axis)
    return out


def _require_grounded_axis(spec: dict, problem: dict | None) -> None:
    """SPEC_AXIS_UNGROUNDED unless an EXTERNAL category is tied to the problem.

    EXTERNAL ONLY, and that restriction is the taxonomy earning its keep. This
    net was written to stop a model wandering across four world axes for one
    problem, and it worked — but applied to every spec it also refused the
    honest answer, because an internal fix has no world axis to be grounded in.
    Refusing a correct classification is the same failure as accepting a guess,
    pointed the other way.

    An internal category needs no token overlap with the problem text: it is
    grounded by the domain itself, and its membership is checked against
    config/internal_axes.json in validate().
    """
    if problem is None or spec.get("domain") != "external":
        return
    candidates = plausible_axes({**problem, **{"allowed_paths":
                                               spec.get("allowed_paths")}})
    cats = list(spec.get("categories") or [])
    axis = cats[0] if len(cats) == 1 else cats
    if not candidates:
        raise SpecAxisUngrounded(
            f"{SpecAxisUngrounded.code}: no world axis is plausibly tied to this "
            f"problem, so {axis!r} is a guess. Nothing in the problem text names "
            f"an axis and no allowed_path resolves to one. If this problem is a "
            f"fault in the system rather than a gap in how it measures the "
            f"world, the domain is INTERNAL and no world axis applies to it at "
            f"all — say that instead of picking one, which is how five runs "
            f"produced four different axes for the same problem.")
    ungrounded = [c for c in cats if c not in candidates]
    if ungrounded:
        raise SpecAxisUngrounded(
            f"{SpecAxisUngrounded.code}: {ungrounded} "
            f"{'is a real axis' if len(ungrounded) == 1 else 'are real axes'} "
            f"but not tied to this problem. The evidence supports "
            f"{sorted(candidates)}. Being in the list of 24 is not the same as "
            f"being about this.")


# Anything that looks like a repo-relative data file. Deliberately narrow: the
# point is to find a file the metric can be RECOMPUTED from, and core/earning.py
# recomputes from JSON only.
_METRIC_PATH = re.compile(r"[\w./\\-]+\.(?:json|jsonl|csv|txt|md)")


def metric_files(metric: str) -> list:
    """Every path-like token in the metric text that IS a real file."""
    out = []
    for cand in _METRIC_PATH.findall(str(metric or "")):
        rel = cand.replace("\\", "/").strip("'\"` ")
        if (REPO / rel).is_file() and rel not in out:
            out.append(rel)
    return out


def _require_grounded_metric(spec: dict) -> None:
    """SPEC_METRIC_UNGROUNDED unless the metric names a real, readable file.

    Raised BEFORE the implementer, like the path net: a run whose success can
    never be measured is not worth a cloud call.
    """
    metric = str(spec.get("success_metric", ""))
    if metric_files(metric):
        return
    named = _METRIC_PATH.findall(metric)
    detail = (f"it names {', '.join(repr(n) for n in named)}, which "
              f"{'does' if len(named) == 1 else 'do'} not exist"
              if named else "it names no file at all")
    raise SpecMetricUngrounded(
        f"{SpecMetricUngrounded.code}: success_metric {metric!r} cannot be "
        f"recomputed — {detail}. Name a real file the number can be read from, "
        f"e.g. 'the number of rows in memory/goal_score_history.json'. A metric "
        f"nobody can recompute cannot be checked, and an unchecked claim is the "
        f"FABRICATED verdict execute_patches already refuses.")


# ---------------------------------------------------------------------------
# the brain
# ---------------------------------------------------------------------------

def _local_brain(prompt: str, max_tokens: int = 700) -> str:
    """The LOCAL model, and only the local model.

    NO CLOUD FALLBACK, deliberately. core.groq_backend.call_groq would answer
    and the spec would look fine — and the experiment, which is about WHICH model
    does this job, would be silently over. If the local brain is down this
    raises, and that is the honest outcome.
    """
    from core.groq_backend import _call_local
    content, _meta = _call_local(prompt, max_tokens)
    return content


def candidate_paths(component: str, limit: int = 25) -> list:
    """REAL, EXISTING repo-relative paths the spec may choose from.

    The three locations are the SAME ones agents/core/self_modifier._build_context
    resolves for a component, so the requirer offers exactly the files the
    production self-modifier would have found. Every path returned is checked
    with .exists() — this list is the ground truth the model is told to choose
    from, so a single stale entry in it would re-open the hole it closes.

    Falls back to a listing of agents/core/ and core/ when the component matches
    nothing, so the model always has real options rather than an empty list and
    an invitation to improvise.
    """
    hits = []
    for rel in (f"data_providers/civilization/{component.lower()}_provider.py",
                f"data_providers/planet/{component.lower()}_provider.py",
                f"agents/core/{component.lower()}.py",
                f"core/{component.lower()}.py"):
        if (REPO / rel).exists():
            hits.append(rel)
    if hits:
        return hits
    for d in ("agents/core", "core"):
        for p in sorted((REPO / d).glob("*.py")):
            if p.name.startswith("_"):
                continue
            hits.append(p.relative_to(REPO).as_posix())
            if len(hits) >= limit:
                return hits
    return hits


def metric_candidates(limit: int = 12) -> list:
    """REAL data files a success_metric could be recomputed from.

    Shown to the model for the same reason candidate_paths is: told to name a
    file without being shown any, it named the prompt's own placeholder
    ('memory/x.json'). An example in a prompt is an invitation to copy it.
    """
    out = []
    for d in ("memory", "output"):
        root = REPO / d
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.json")):
            out.append(p.relative_to(REPO).as_posix())
            if len(out) >= limit:
                return out
    return out


def real_code_context(component: str, problem: str) -> str:
    """The production self-modifier's own context builder, reused not copied.

    agents/core/self_modifier._build_context already reads the real file for a
    component and the live web-intelligence for the axis. Calling it means the
    requirer sees exactly what the production step sees; a second implementation
    would drift from it the first time either changed.

    Fail-open with a NAMED empty result: grounding that silently vanishes would
    put the model straight back to imagining a codebase, which is the defect
    this commit exists to close, so it prints.
    """
    try:
        from agents.core.self_modifier import _build_context
        return _build_context(component, problem) or ""
    except Exception as exc:                                     # noqa: BLE001
        print(f"[REQUIRER] real repo context UNAVAILABLE "
              f"({type(exc).__name__}: {exc}) — the model is being asked to "
              f"specify against a repo it cannot see")
        return ""


def passage_standard() -> str:
    """The rules of passage, verbatim, from config/passage_rules.json.

    The actor is SHOWN the measure it is judged by — the same object
    core/notary.py reads, not a paraphrase. self_modifier already does this
    (agents/core/self_modifier.PASSAGE_RULES_BLOCK); the requirer was writing
    specs against a standard it had never been told.

    Fail LOUD if it cannot be read: a prompt quietly missing its rules looks
    exactly like one that has them.
    """
    try:
        from core.passage_rules import actor_block
        return actor_block()
    except Exception as exc:                                     # noqa: BLE001
        print(f"[REQUIRER] THE RULES OF PASSAGE could not be loaded "
              f"({type(exc).__name__}: {exc}) — the model is being asked to "
              f"work without the standard it will be judged by")
        return ""


def build_prompt(problem: dict, axes: set, grounded: bool = True) -> str:
    """Short and sharp: a small model reads the first lines and stops.

    THE RULES ARE STATED, NOT IMPLIED (8 Sep 2026). A live run on 2026-09-08
    produced three specs in three attempts, every one naming an axis that
    exists and a path that does NOT: "self_observer", "core/self_observer.py",
    "src/ai/self_observer.py". This repo has no src/ tree at all. The model was
    never told that allowed_paths must be real, so it wrote a plausible one.

    An instruction alone will not fix that — COMMIT 3 adds the mechanical net
    that REFUSES a spec whose paths do not resolve. Both, per the norm: a sharp
    instruction AND a check behind it, neither standing in for the other.
    """
    standard = passage_standard()
    component = str(problem.get("component", "unknown"))

    # ── THE GROUNDING (8 Sep 2026) ─────────────────────────────────────────
    # The root cause of every invented path: the model was never shown the repo.
    # It is shown it now — real paths, checked with .exists(), and the real file
    # the production self-modifier would have read.
    paths, code = [], ""
    if grounded:
        paths = candidate_paths(component)
        code = real_code_context(component, str(problem.get("problem", "")))
    ground = ""
    if paths:
        ground += ("REAL PATHS IN THIS REPO — allowed_paths MUST be one of "
                   "these, copied exactly:\n"
                   + "".join(f"  {p}\n" for p in paths) + "\n")
    if code:
        ground += f"THE REAL CODE YOU ARE SPECIFYING AGAINST:\n{code[:1800]}\n\n"
    if grounded:
        metrics = metric_candidates()
        if metrics:
            ground += ("REAL DATA FILES YOU MAY MEASURE — success_metric MUST "
                       "name one of these, copied exactly:\n"
                       + "".join(f"  {m}\n" for m in metrics) + "\n")

    return (
        (f"{standard}\n\n" if standard else "")
        + ground
        + taxonomy_block(axes)
        + "You are the CORTEX++ requirer. You produce a SPECIFICATION. "
        "You never write code.\n\n"
        "THE RULES YOU ARE JUDGED BY — read these before writing anything:\n"
        "  0. ALL SEVEN fields below are REQUIRED and must be FILLED "
        "IN. A missing field, an empty string, or a copied placeholder "
        "is REFUSED before quality is ever judged. If you must infer "
        "root_cause from the problem, infer it — do not omit it.\n"
        "  1. allowed_paths MUST be files that ALREADY EXIST in this repo. A "
        "path that does not exist is a FAILURE, not an approximation. Do not "
        "invent a plausible-looking path; do not guess a conventional layout. "
        "If you are unsure which file, say the one you were shown.\n"
        "  2. success_metric MUST name a REAL FILE from the list below and be "
        "computable from it — e.g. \"the number of rows in "
        "memory/goal_score_history.json\", not \"fewer failures\". DO NOT COPY "
        "AN EXAMPLE PATH: a spec naming a file that does not exist is REFUSED as "
        "SPEC_METRIC_UNGROUNDED before any code is written.\n"
        "  3. FIRST choose the DOMAIN this problem belongs to, THEN one or more "
        "CATEGORIES FROM THAT DOMAIN. A category from the other domain is "
        "REFUSED — it is not a near miss, it is the wrong question. If the "
        "problem is a fault in this system (a parser, a retry, a log, a guard), "
        "the domain is \"internal\" and the world axes do not apply to it at "
        "all; do not reach for one.\n"
        "  4. No Python, no snippet, no fenced block, no import or def. A spec "
        "containing code is REFUSED WHOLE — not cleaned up. Describing WHAT "
        "must change is your job; HOW is someone else's.\n\n"
        f"OBSERVED PROBLEM: {str(problem.get('problem',''))[:400]}\n"
        f"ROOT CAUSE (observed): {str(problem.get('root_cause',''))[:300]}\n"
        f"COMPONENT: {problem.get('component','unknown')}\n\n"
        "Return ONLY this JSON, no prose around it:\n"
        "{\n"
        '  "problem": "<one sentence>",\n'
        '  "root_cause": "<one sentence>",\n'
        '  "desired_change": "<what must be true after, in words>",\n'
        '  "success_metric": "<a number recomputable from a named file>",\n'
        '  "domain": "<internal OR external>",\n'
        '  "categories": ["<one or more, ALL from the domain you chose>"],\n'
        '  "allowed_paths": ["<a repo-relative path that EXISTS>"]\n'
        "}\n"
    )


def taxonomy_block(axes: set) -> str:
    """BOTH sets, shown in full, with the internal ones explained.

    The model cannot choose a domain it has never been shown. Before this block
    existed the prompt offered the 24 world axes and nothing else, so "internal"
    was not a wrong answer the model gave — it was an answer the question did
    not have. The meanings come from config/internal_axes.json rather than being
    retyped here, so the file the net reads is the file the model is shown.
    """
    try:
        internal = internal_axes()
    except Exception as exc:                                     # noqa: BLE001
        # Loud and unusable rather than quietly half a taxonomy: a prompt
        # offering only the world axes is how the wandering started.
        return (f"THE TAXONOMY IS UNREADABLE ({exc}). Do not answer; say the "
                f"categories cannot be listed.\n\n")
    return (
        "THE TWO DOMAINS — choose ONE, then one or more categories FROM IT:\n\n"
        "  internal = you are improving THIS SYSTEM (the instrument itself).\n"
        + "".join(f"      {k:<16} {v}\n" for k, v in sorted(internal.items()))
        + "\n  external = you are improving how the system measures THE WORLD.\n"
        + "".join(f"      {a}\n" for a in sorted(axes))
        + "\n")


def observations(limit: int = 5, journal: Path | None = None,
                 proposals: Path | None = None) -> list:
    """The problem feed self_observer leaves behind. READ-ONLY.

    memory/improvement_proposals.json is where self_observer writes its HIGH
    proposals; the journal is the fallback. Neither is written by this module.
    """
    out = []
    try:
        raw = json.loads((proposals or PROPOSALS).read_text(encoding="utf-8"))
        items = raw.get("proposals", raw) if isinstance(raw, dict) else raw
        out = [p for p in items if isinstance(p, dict)
               and p.get("priority") == "HIGH"][:limit]
    except Exception:
        out = []
    if out:
        return out
    try:
        j = json.loads((journal or JOURNAL).read_text(encoding="utf-8"))
        for _day, entry in sorted(j.items(), reverse=True):
            for rec in (entry.get("patch_executions") or []):
                if rec.get("verdict") in ("FABRICATED", "ZERO", "UNMEASURED"):
                    out.append({"problem": f"patch {rec.get('patch')} reported "
                                           f"{rec.get('verdict')}",
                                "root_cause": rec.get("measurement_why", ""),
                                "component": "unknown"})
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out[:limit]


def _ask_once(problem: dict, brain, known: set) -> dict:
    """One ask, validated. Raises the named refusal the answer earned."""
    raw = (brain or _local_brain)(build_prompt(problem, known))
    text = str(raw or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SpecInvalid(f"the brain returned no JSON object: {text[:200]!r}")
    try:
        spec = json.loads(m.group(0))
    except Exception as exc:
        raise SpecInvalid(f"the brain's JSON did not parse: {exc}") from exc

    validate(spec, known, problem)
    spec["_source"] = "requirer/local_brain"
    spec["_observed_problem"] = str(problem.get("problem", ""))[:200]
    return spec


def require(problem: dict, brain=None, axes: set | None = None,
            consensus: int = 3) -> dict:
    """One observation -> one validated SPEC. Raises rather than degrading.

    RETRY-TO-CONSENSUS, and why it is consensus rather than a temperature knob:
    the local model runs at temperature 0.4, hardcoded in
    core.groq_backend._call_local_as, which is PRODUCTION and not this
    experiment's to change. So determinism is bought by asking N times and
    requiring a majority on goal_axis — the field that wandered across four
    different answers in five live runs on one problem.

    No majority means the model does not know, and SPEC_AXIS_UNSTABLE says so.
    A guess that validates is worse than a refusal, because it looks like an
    answer.

    consensus=1 asks once and skips the vote — for tests, and for a caller who
    has decided the variance does not matter.
    """
    known = axes if axes is not None else real_axes()
    if consensus <= 1:
        return _ask_once(problem, brain, known)

    specs, errors = [], []
    for _ in range(consensus):
        try:
            specs.append(_ask_once(problem, brain, known))
        except SpecInvalid as exc:
            errors.append(exc)

    if not specs:
        # Every ask was refused. Re-raise the FIRST refusal rather than a
        # summary: its code names what actually went wrong, and a caller that
        # catches SpecAxisUngrounded must still see it.
        raise errors[0]

    # THE VOTE IS ON THE DOMAIN, not on the categories. Categories are a
    # multi-select, so a strict majority on the exact set would refuse two
    # answers that agree about everything that matters — "internal:
    # [reliability]" and "internal: [reliability, correctness]" are not a
    # disagreement about what the problem IS. The domain is the binary the
    # answer-space turns on, and it is the thing that must hold still.
    tally = {}
    for sp in specs:
        tally.setdefault(sp["domain"], []).append(sp)
    axis, winners = max(tally.items(), key=lambda kv: len(kv[1]))

    # UNANIMOUS, NOT MERELY A MAJORITY — and the difference is the whole net.
    # The domain is a BINARY. With an odd number of asks a majority is free: a
    # model flipping a coin produces one every single time, so "majority on the
    # domain" would pass whatever the model did, and a net that always passes is
    # not a net. Measured while writing this: internal/external/internal is a
    # 2-1 "majority" and is also a model that changed its mind about what kind
    # of problem it was looking at.
    #
    # The message reports asks, VALID asks and votes separately, because they
    # fail differently: asks that disagree is a wandering model, while three
    # asks of which two were REFUSED is a model that mostly could not produce a
    # spec at all. Collapsing them into "no majority" sent me looking for the
    # wrong problem the first time this fired.
    if len(winners) < 2 or len(winners) != len(specs):
        raise SpecAxisUnstable(
            f"{SpecAxisUnstable.code}: {consensus} ask(s), {len(specs)} valid, "
            f"best domain {axis!r} with {len(winners)} vote(s) — not unanimous "
            f"(a binary needs every valid ask to agree; a majority on a coin "
            f"flip is free). Domains seen: {', '.join(sorted(tally))}. The model "
            f"cannot decide whether this problem is about the instrument or "
            f"about the world; saying so is the honest output.")

    chosen = winners[0]
    chosen["_consensus"] = {
        "asks": consensus, "valid": len(specs), "agreed_on": axis,
        "votes": len(winners), "all_domains": sorted(tally),
        # Every category any ask offered, kept because the domain vote
        # deliberately ignores them: a reader deciding whether the categories
        # were stable needs to see them rather than take the domain's word.
        "categories_seen": sorted({c for sp in specs
                                   for c in (sp.get("categories") or [])}),
    }
    return chosen


def write_spec(spec: dict, out_dir: Path | None = None) -> Path:
    """Under the EXPERIMENTAL tree. Never memory/, never snapshots/."""
    d = Path(out_dir) if out_dir else SPEC_DIR
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"spec_{stamp}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/self_improve/requirer.py --selftest")
    try:
        axes = real_axes()
        print(f"  config/target_config.json : LIVE ({len(axes)} axes)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  config/target_config.json : INERT ({type(exc).__name__}: {exc})")
        return 1

    print(f"  problem feed              : {len(observations())} HIGH observation(s)")
    print(f"  spec output dir           : {SPEC_DIR.relative_to(REPO)} "
          f"(experimental, not memory/)")

    try:
        from core.groq_backend import _call_local  # noqa: F401
        print("  local brain entry         : LIVE (core.groq_backend._call_local)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  local brain entry         : INERT ({type(exc).__name__}: {exc})")

    ok = True
    # A fixture the live nets ACCEPT: a real target file, a metric that names
    # a real file, and an axis the target path itself grounds. Each of those
    # was a placeholder here once ("data_providers/", "count of rows"), and
    # the selftest printed OK while the pipeline refused every real spec.
    problem = {"problem": "the economy work provider never resolves its series"}
    good = {"problem": "the provider never resolves the series",
            "root_cause": "the observation map has no entry for the key",
            "desired_change": "the provider resolves the series",
            "success_metric": "the number of rows in memory/goal_score_history.json",
            "domain": "external",
            "categories": ["ECONOMY_WORK_REVIEW"],
            "allowed_paths": ["data_providers/civilization/economy_work_provider.py"]}
    try:
        validate(dict(good), axes, problem)
        print("  a clean spec              : accepted")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  a clean spec              : WRONGLY REFUSED ({exc})")
        ok = False

    # An engineering fault no civilization axis is about — the live problem
    # that made five runs produce four different axes.
    ungrounded = {"problem": "ESCALATION: LLM returns invalid JSON 3 times"}
    for label, bad, prob in (
            ("code in a field",
             dict(good, desired_change="def f():\n    return 1"), problem),
            ("fenced block",
             dict(good, problem="```python\nx=1\n```"), problem),
            ("invented category", dict(good, categories=["NOT_AN_AXIS"]), problem),
            ("an internal category on an external spec",
             dict(good, categories=["reliability"]), problem),
            ("no domain at all", dict(good, domain="whatever"), problem),
            ("empty categories", dict(good, categories=[]), problem),
            ("metric names no file",
             dict(good, success_metric="count of rows"), problem),
            ("axis nothing supports",
             dict(good, allowed_paths=["agents/core/self_observer.py"]),
             ungrounded)):
        try:
            validate(dict(bad), axes, prob)
            print(f"  {label:<24} : NOT REFUSED — the net is open")
            ok = False
        except (SpecContainsCode, SpecInvalid):
            print(f"  {label:<24} : refused")

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
