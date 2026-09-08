#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_refusal_cites_the_rule.py — A REFUSAL NAMES THE RULE, NOT JUST THE VERDICT.

THE DEFECT THIS GUARDS
-----------------------
The refusal record carried step, gate, level, reason and timestamp. It said what
level was scored and never what STANDARD produced that level — the verdict
without the law. And before c4a0d30 there was nothing stable to cite: the rules
lived as constants inside core/notary.py, so an actor could not look one up even
if the record had pointed at it.

Now config/passage_rules.json is the one ruleset, with a version, and every
refusal cites it. A record written under one version of the rules can no longer
be misread under a later one.

THE FORBIDDEN FALLBACK
-----------------------
Do NOT copy the rule text into the record. A refusal carrying its own copy of
the rules is exactly the second copy core/passage_rules.py exists to prevent —
it would drift the moment the ruleset changed, and every archived night would
then disagree with every other. The record CITES: version plus scale entry. The
one piece of prose it carries (`earns`) is read out of the ruleset at write time
and is stamped with the version that produced it.

    venv\\Scripts\\python.exe -m pytest test/test_refusal_cites_the_rule.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

NOTARY_WHY = ("level_1 (минимално) — explicit ceiling for 'self_modifier': capped "
              "by core/notary.MAX_LEVEL regardless of its own vector")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """The runner's gate with every live write redirected into tmp_path."""
    import fast_cycle_runner as runner
    from memory import runtime_telemetry as rt
    from core import phase_tracker

    tel = tmp_path / "memory" / "runtime_experiences.json"
    tel.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rt, "TEL_PATH", tel)
    monkeypatch.setattr(runner, "_refusal_event", lambda *a, **k: None)
    monkeypatch.setattr(phase_tracker, "note_refusal", lambda *a, **k: None)
    return runner, tel


def _last(tel: pathlib.Path) -> dict:
    return json.loads(tel.read_text(encoding="utf-8"))["experiences"][-1]


# ---------------------------------------------------------------------------
# (a) THE MUTATION TEST — remove the field and this goes red
# ---------------------------------------------------------------------------

def test_a_refusal_cites_the_rule_it_applied(gate):
    """Delete rule_cited from record_refusal and this fails: the record would
    again carry the verdict with no way back to the standard."""
    runner, tel = gate
    runner._refused("self_modifier", "notary", NOTARY_WHY)

    rec = _last(tel)
    cited = rec["data"].get("rule_cited")
    assert cited, (
        "\n  THE REFUSAL NAMES NO RULE.\n"
        "  The record says what level was scored and not what standard produced\n"
        "  it. An actor reading this cannot look up what it failed, which is the\n"
        "  state that left self_modifier refused 35 nights running against a\n"
        "  rubric it had never been shown.\n")

    assert cited["source"] == "config/passage_rules.json"
    assert cited["cited"] == "scale.1", cited
    assert cited["irreversible_min"] == 2


def test_the_citation_carries_the_ruleset_version(gate):
    """A record written under one version of the rules must not be readable as
    though it were written under a later one."""
    runner, tel = gate
    runner._refused("self_modifier", "notary", NOTARY_WHY)

    cited = _last(tel)["data"]["rule_cited"]
    doc = json.loads((REPO / "config" / "passage_rules.json").read_text(
        encoding="utf-8"))
    assert cited["version"] == doc["version"], (
        "the citation's version does not match the ruleset it claims to cite")
    assert cited["version"], "the ruleset has no version to cite"


def test_the_cited_entry_resolves_in_the_ruleset(gate):
    """A citation that points at nothing is worse than none: it looks checkable
    and is not."""
    runner, tel = gate
    runner._refused("execute_patches", "notary",
                    "level_2 (намалено) — something reduced")

    cited = _last(tel)["data"]["rule_cited"]
    key = cited["cited"].split(".")[1]
    doc = json.loads((REPO / "config" / "passage_rules.json").read_text(
        encoding="utf-8"))
    assert key in doc["scale"], f"{cited['cited']} does not exist in the ruleset"
    assert cited["level_name"] == doc["scale"][key]["name"]
    assert cited["earns"] == doc["scale"][key]["earns"]


# ---------------------------------------------------------------------------
# (b) the failure paths, asked for before the happy one
# ---------------------------------------------------------------------------

def test_a_gate_with_no_level_says_no_scale_entry_applies_rather_than_nothing(gate):
    """human_channel and metta_witness report no level. 'No rule cited' and 'this
    gate has no scale entry' are different facts; the second must be said."""
    runner, tel = gate
    runner._refused("github_publish", "human_channel", "the channel is dead")

    cited = _last(tel)["data"]["rule_cited"]
    assert cited is not None, "the field vanished for a gate with no level"
    assert cited["cited"] is None
    assert "no level" in cited["note"]
    assert cited["irreversible_min"] == 2, (
        "even with no scale entry, the threshold that was applied is a fact the "
        "record should carry")


def test_an_unreadable_ruleset_is_recorded_as_such_not_as_no_rule(monkeypatch):
    """'No rule cited' and 'the rule could not be looked up' must never collapse
    into the same record."""
    from memory import runtime_telemetry as rt
    import core.passage_rules as PR

    monkeypatch.setattr(PR, "RULES", dict(PR.RULES, unreadable="boom"))
    cited = rt._cite_rule(1)
    assert cited["cited"] is None
    assert "unreadable" in cited["note"]


def test_the_lookup_failing_never_costs_the_record(monkeypatch, gate):
    """The citation is an addition to the record, never a precondition for it.
    If it could raise, a broken ruleset would destroy the only evidence the
    refusal happened."""
    runner, tel = gate
    import core.passage_rules as PR

    class _Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("exploded")

    monkeypatch.setattr(PR, "RULES", _Boom())
    runner._refused("self_modifier", "notary", NOTARY_WHY)

    rec = _last(tel)
    assert rec["event_type"] == "REFUSAL", "the refusal record was lost"
    assert rec["data"]["reason"] == NOTARY_WHY
    assert "failed" in rec["data"]["rule_cited"]["note"]


# ---------------------------------------------------------------------------
# (c) THE FORBIDDEN FALLBACK — cite, never copy
# ---------------------------------------------------------------------------

def test_the_record_cites_the_ruleset_and_does_not_reimplement_it():
    """STRUCTURAL, on the AST. _cite_rule must read core.passage_rules; a
    hardcoded scale table here would drift from the gate the first time the
    ruleset changed, and every archived night would then disagree."""
    tree = ast.parse((REPO / "memory" / "runtime_telemetry.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_cite_rule")

    imports = {a.name for n in ast.walk(fn)
               if isinstance(n, ast.ImportFrom) and n.module == "core.passage_rules"
               for a in n.names}
    assert "RULES" in imports, (
        "_cite_rule no longer reads the one ruleset; it is now carrying its own "
        "copy of the rules")

    src = ast.dump(fn)
    for literal in ("level_3", "level_2", "level_1", "level_0"):
        assert repr(literal) not in src, (
            f"_cite_rule hardcodes {literal!r}; the citation must resolve names "
            f"out of config/passage_rules.json, never restate them")

    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
        "_cite_rule is not fail-open; a rule lookup must never cost the record")


def test_the_field_is_wired_into_record_refusal():
    """Being defined is not being written."""
    tree = ast.parse((REPO / "memory" / "runtime_telemetry.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "record_refusal")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_cite_rule" in called, "record_refusal does not cite the rule"


def test_the_older_fields_are_untouched(gate):
    """One field added. The record's existing contract must not move under its
    readers."""
    runner, tel = gate
    runner._refused("self_modifier", "notary", NOTARY_WHY, prev_step="self_observer")

    d = _last(tel)["data"]
    for key in ("step", "gate", "reason", "level", "level_source", "prev_step"):
        assert key in d, f"{key} disappeared from the refusal record"
    assert d["level"] == 1 and d["level_source"] == "parsed_from_gate_reason"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
