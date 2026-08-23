#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_prompt_census.py — THE INSTRUMENT, AND WHETHER IT CAN FAIL.

A census that only ever prints PASS is a decoration. These tests break the room
on purpose and check that it says so, and that it NAMES THE BLOCK — "the prompt
has Cyrillic in it" is not actionable; "_spirit() has Cyrillic in it" is.

    venv/Scripts/python.exe -m pytest test/test_prompt_census.py -v
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCRIPT = REPO / "scripts" / "prompt_census.py"

# Captured at import, before conftest's autouse fixture neutralises it. The
# census assembles attend()'s prompt too, and measuring the stub would report an
# empty prompt as a pass.
from core import brain as _brain          # noqa: E402
_REAL_ATTEND = _brain.attend


def _load():
    spec = importlib.util.spec_from_file_location("prompt_census", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the measurement itself ──────────────────────────────────────────────────

def test_the_profile_counts_letters_not_characters():
    mod = _load()
    p = mod.profile('{"n": 42, "text": "hello"}')
    assert p["letters"] == 10 and p["chars"] == 26
    assert p["latin"] == 1.0 and p["cyrillic"] == 0.0


def test_it_separates_cyrillic_from_han():
    mod = _load()
    assert mod.profile("Показател")["cyrillic"] == 1.0
    assert mod.profile("已评分")["han"] == 1.0


def test_the_runs_name_the_actual_words():
    mod = _load()
    found = mod.runs("The indicator оставя без изменений for 48 days")
    assert found and "оставя" in " ".join(found)


# ── the real room ───────────────────────────────────────────────────────────

def test_the_live_room_passes():
    mod = _load()
    assert mod.census("constancy") == 0


def test_every_kind_passes():
    mod = _load()
    failed = [k for k in mod.KINDS
              if mod.census(k, attend=_REAL_ATTEND) != 0]
    assert not failed, failed


def test_the_stance_prompt_is_included():
    """attend() is a different builder and drifted furthest; a census that
    silently skipped it would be measuring the wrong half."""
    mod = _load()
    assert "step_stance" in mod.KINDS
    prompt, _ = mod.assemble("step_stance", attend=_REAL_ATTEND)
    assert "NOW STARTING:" in prompt


# ── can it fail? ────────────────────────────────────────────────────────────

def test_a_bulgarian_block_makes_it_fail_and_names_the_block(capsys,
                                                             monkeypatch):
    mod = _load()
    from core import brain
    monkeypatch.setattr(brain, "_body",
                        lambda: "процесорът е на 40 процента натоварване")
    assert mod.census("constancy") == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "_body()" in out
    assert "процесорът" in out


def test_a_chinese_block_makes_it_fail_too(capsys, monkeypatch):
    mod = _load()
    from core import brain
    monkeypatch.setattr(brain, "_self_state", lambda: "已评分25个轴")
    assert mod.census("constancy") == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "_self_state()" in out


def test_cyrillic_outside_a_named_block_is_still_caught(capsys, monkeypatch):
    """The scaffold and the caller's role/question are not named blocks. The
    census must not report PASS just because every block it lists is clean."""
    mod = _load()
    from core import brain
    real = brain.LANGUAGE_PIN
    monkeypatch.setattr(brain, "LANGUAGE_PIN", real)

    original = mod.assemble

    def _dirty(kind, attend=None):
        prompt, blocks = original(kind)
        return prompt + "\n\nВЪПРОС: нещо на български", blocks

    monkeypatch.setattr(mod, "assemble", _dirty)
    assert mod.census("constancy") == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "not in any named block" in out


def test_it_contacts_no_model():
    """The whole point of being runnable without starting a cycle."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "prompt_census contacts no model" in src
    mod = _load()
    prompt, _ = mod.assemble("constancy")
    assert prompt, "the recorder captured nothing"


def test_it_writes_nothing():
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in (
                "write_text", "write_bytes", "mkdir", "unlink", "touch"):
            raise AssertionError(
                "prompt_census.py calls .{}() — it is a measurement".format(
                    node.attr))
