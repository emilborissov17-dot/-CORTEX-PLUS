#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_passage_rules.py — THE STATED RULE AND THE ENFORCED RULE ARE ONE.

THE DEFECT THIS GUARDS
-----------------------
The gate's rules lived as constants inside core/notary.py and nowhere else. Two
faces of one defect:

  1. self_modifier was refused 35 nights running (2026-08-17 .. 2026-09-08, zero
     passes) on an origin level its prompt never mentioned. It was marked against
     a rubric it had never seen and then asked to do better.
  2. Any prose describing the rules — docstring, report, prompt — was a second
     copy, free to say something the code did not do, with nothing but human
     attention to catch it.

config/passage_rules.json is now the one object. core/notary.py READS it to
judge; every gated actor is SHOWN its actor_block. This file fails if those two
ever stop being the same bytes.

THE FORBIDDEN FALLBACK
-----------------------
Making the ceiling configurable must not make it quietly editable.
test_the_ratified_values_have_not_moved pins every number, so raising a ceiling
takes an edit to the config AND to this test in one diff, where a human sees it.
A config that can be edited to open the gate would be strictly worse than the
constants it replaced.

    venv\\Scripts\\python.exe -m pytest test/test_passage_rules.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from core import notary as N
from core import passage_rules as PR

REPO = pathlib.Path(__file__).resolve().parents[1]
RULES_FILE = REPO / "config" / "passage_rules.json"


def _raw() -> dict:
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) THE ANTI-DRIFT NET — enforcement == statement
# ---------------------------------------------------------------------------

def test_the_notary_enforces_exactly_what_the_file_states():
    """THE WHOLE POINT. Change a value in the file and the gate changes with it;
    change the gate without the file and this goes red."""
    rules = PR.load(strict=True)

    assert N.IRREVERSIBLE_MIN == rules["irreversible_min"], (
        "the gate's threshold is not the one the file states, so the rules a "
        "human reads are not the rules being applied")
    assert N.MAX_LEVEL == rules["ceilings"]
    assert tuple(N._STALE_DAYS) == rules["stale_days"]
    assert N.LEVEL_NAMES == rules["level_names"]
    assert N.VERIFIERS == rules["verifiers"]


def test_the_notary_holds_no_second_copy_of_the_rules():
    """STRUCTURAL, on the AST. A literal left behind next to the loaded value is
    exactly the drift this commit removes — it would keep working, and keep being
    wrong, the first time the file changed."""
    tree = ast.parse((REPO / "core" / "notary.py").read_text(encoding="utf-8"))

    for name in ("IRREVERSIBLE_MIN", "MAX_LEVEL", "LEVEL_NAMES", "VERIFIERS",
                 "_STALE_DAYS"):
        assigns = [n for n in tree.body
                   if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == name for t in n.targets)]
        assert len(assigns) == 1, f"{name} is assigned {len(assigns)} times"
        src = ast.dump(assigns[0].value)
        assert "_RULES" in src, (
            f"{name} is still a literal in core/notary.py; it must be read from "
            f"config/passage_rules.json or the stated rule can drift from the "
            f"enforced one")


def test_the_actor_is_shown_the_same_bytes_the_gate_applies():
    """BYTE-IDENTICAL. Not 'equivalent', not 'a summary of'."""
    from agents.core.self_modifier import PASSAGE_RULES_BLOCK

    assert PASSAGE_RULES_BLOCK == _raw()["actor_block"], (
        "the text shown to self_modifier is not the text in "
        "config/passage_rules.json. A paraphrase is a second copy and will drift.")
    assert PASSAGE_RULES_BLOCK == PR.actor_block()
    assert PASSAGE_RULES_BLOCK.strip(), "the actor is shown nothing"


def test_the_block_actually_reaches_the_built_prompt():
    """Being importable is not being sent. The block must appear, verbatim, in
    the prompt string the model receives — otherwise the constant exists and the
    model still cannot read the rules."""
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_generate_solution")
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "PASSAGE_RULES_BLOCK" in used, (
        "_generate_solution builds its prompt without the rules block; the "
        "constant is defined and never sent")

    prompt_assign = next(
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "prompt" for t in n.targets))
    assert "PASSAGE_RULES_BLOCK" in ast.dump(prompt_assign), (
        "the block is referenced somewhere in the function but not in the "
        "prompt itself")


def test_one_accessor_so_a_second_actor_cannot_paraphrase():
    """SHARED BY DESIGN. hyperclaw and any future gated producer must import the
    same function, not write their own version of the rules."""
    tree = ast.parse((REPO / "core" / "passage_rules.py").read_text(encoding="utf-8"))
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "actor_block" in fns, "the shared accessor is gone"

    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    assert "from core.passage_rules import" in src, (
        "self_modifier no longer imports the shared block; it is now carrying "
        "its own copy of the rules")
    # The rules text itself must NOT be pasted into the actor's module.
    body = _raw()["actor_block"].splitlines()[0]
    assert body not in src, (
        "the rules text is pasted into self_modifier.py as a literal; that is "
        "the second copy this commit exists to prevent")


# ---------------------------------------------------------------------------
# (b) TRANSPARENCY ONLY — no value moved
# ---------------------------------------------------------------------------

def test_the_ratified_values_have_not_moved():
    """THE RATCHET. These are the values core/notary.py enforced before the
    extraction, copied out unchanged on 2026-09-08.

    Raising a ceiling is AMENDMENT_001's business and its cooling-off ends
    19 Oct 2026. Moving any number below requires editing this test in the same
    diff — which is the point: configurable, never quietly editable.
    """
    rules = PR.load(strict=True)
    assert rules["irreversible_min"] == 2, "IRREVERSIBLE_MIN was REDUCED(2)"
    assert rules["stale_days"] == (2, 30, 365)
    assert rules["ceilings"] == {"execute_patches": 1}, (
        "execute_patches was capped at MINIMAL(1), BELOW irreversible_min, so "
        "may_act() refuses it. Raising this is AMENDMENT_001's business.")
    assert rules["verifiers"] == {"global_indicators", "sensorium_ingest",
                                  "browser_scout", "internet_intelligence",
                                  "web_intelligence"}
    assert set(rules["level_names"]) == {0, 1, 2, 3}
    assert rules["level_names"][3].startswith("level_3")
    assert rules["level_names"][0].startswith("level_0")


def test_the_cooling_off_is_still_stated_where_the_refusal_is_built():
    src = (REPO / "core" / "notary.py").read_text(encoding="utf-8")
    assert "cooling-off ends 19 Oct 2026" in src
    assert "AMENDMENT_001" in src


# ---------------------------------------------------------------------------
# (c) FAIL CLOSED — an unreadable ruleset is never permission
# ---------------------------------------------------------------------------

def test_an_unreadable_file_closes_the_gate_instead_of_opening_it(tmp_path):
    """The failure path, asked for before the happy one. A missing ruleset must
    refuse everything irreversible, not fall back to a permissive default."""
    rules = PR.load(path=tmp_path / "nope.json")
    assert rules["irreversible_min"] == PR.UNREACHABLE
    assert rules["irreversible_min"] > 3, (
        "the failsafe threshold is reachable on the 0..3 scale, so an unreadable "
        "ruleset would still let irreversible steps act")
    assert rules["ceilings"] == {}
    assert rules["unreadable"]


@pytest.mark.parametrize("mutate,why", [
    (lambda d: d.pop("irreversible_min"), "missing key"),
    (lambda d: d.update(scale={"0": {"name": "x"}}), "truncated scale"),
    (lambda d: d.update(stale_days=[365, 30, 2]), "thresholds not ascending"),
    (lambda d: d.update(ceilings={"execute_patches": 9}), "ceiling off the scale"),
    (lambda d: d.update(actor_block="   "), "the actor would be shown nothing"),
])
def test_a_malformed_ruleset_is_refused_not_half_applied(tmp_path, mutate, why):
    """Half a ruleset is more dangerous than none: it would enforce whatever
    happened to parse and silently drop the rest."""
    doc = _raw()
    mutate(doc)
    bad = tmp_path / "passage_rules.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(PR.RulesUnreadable):
        PR.load(path=bad, strict=True)
    assert PR.load(path=bad)["irreversible_min"] == PR.UNREACHABLE, why


def test_the_failsafe_block_tells_the_actor_the_gate_is_shut(tmp_path):
    """If the actor is shown anything at all when the rules are unreadable, it
    must be the truth: nothing it writes can pass."""
    rules = PR.load(path=tmp_path / "nope.json")
    assert "closed" in rules["actor_block"].lower()
    assert "nothing you write can pass" in rules["actor_block"].lower()


# ---------------------------------------------------------------------------
# (d) the rules the actor reads describe the gate it will actually meet
# ---------------------------------------------------------------------------

def test_the_actor_block_states_the_threshold_the_gate_applies():
    """A rulebook that omits the one number that decides is not transparency."""
    block = PR.actor_block()
    for token in ("0", "1", "2", "3", "UNKNOWN", "REDUCED", "FULL", "MINIMAL"):
        assert token in block, f"the scale is not stated: {token} missing"
    assert "LOWEST level that may act irreversibly" in block, (
        "the block never says which level actually passes")
    assert "REFUSED before" in block, (
        "the block does not say that origin is judged BEFORE quality — the one "
        "fact that explains 35 nights of refusal to the actor")


def test_the_actor_block_names_the_forbidden_fallback():
    """The model must be told that granting itself provenance is the worst move
    available to it, not left to infer it."""
    block = PR.actor_block().lower()
    assert "cannot grant yourself" in block
    assert "faking provenance" in block
    assert "no trusted flag" in block or "no override" in block


def test_every_dimension_the_gate_measures_is_described():
    """core/notary.vector() returns five dimensions. If one is missing from the
    file, the actor is being judged on something the rulebook never mentions."""
    described = set(_raw()["dimensions"])
    measured = {"witness", "human", "thought", "age", "promise"}
    assert measured <= described, f"undescribed dimensions: {measured - described}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
