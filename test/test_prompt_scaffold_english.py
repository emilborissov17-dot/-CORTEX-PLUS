#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_prompt_scaffold_english.py — THE ROOM, NOT JUST THE ORDER.

COMMAND 24 put a language pin on the wire and cut the self-poisoning exemplar
loop. It did not change the room: nine of the ten prompt blocks were still
Bulgarian, so one English sentence was arguing with ~2,700 characters of
context. A 3B model does not resolve that in favour of the sentence.

Measured before COMMAND 25:

    think()  kind=constancy          4232 chars   Cyrillic 35.77%
    attend() step=scoring_engine     2913 chars   Cyrillic 48.08%

This file asserts what the model actually receives, by capturing the request
body. No model is contacted.

    venv/Scripts/python.exe -m pytest test/test_prompt_scaffold_english.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import brain  # noqa: E402

_REAL_ATTEND = brain.attend      # conftest neutralises the module attribute


def cyrillic_fraction(text):
    lat = cyr = 0
    for ch in text:
        if not ch.isalpha():
            continue
        if 0x0400 <= ord(ch) <= 0x052F:
            cyr += 1
        elif ord(ch) < 0x0250:
            lat += 1
    return cyr / max(1, lat + cyr)


def cyrillic_runs(text):
    import re
    return [m.group() for m in re.finditer(r"[Ѐ-ԯ]+[Ѐ-ԯ |\-]*",
                                           text) if len(m.group().strip()) > 1]


class _Recorder:
    def __init__(self):
        self.prompts = []

    def post(self, url, timeout=None, json=None):
        for msg in (json or {}).get("messages", []):
            self.prompts.append(msg.get("content", ""))
        raise RuntimeError("no model is contacted in this test")


@pytest.fixture
def captured(monkeypatch):
    rec = _Recorder()
    monkeypatch.setitem(sys.modules, "requests", rec)
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(brain, "_pick_model",
                        lambda: ("qwen2.5:3b", "http://127.0.0.1:11434"))
    monkeypatch.setattr(brain, "_fast_model", lambda: "qwen2.5:3b")
    monkeypatch.setattr(brain, "_smaller", lambda m: None)
    return rec


THREE_KINDS = [
    ("constancy", "interpreter of an indicator",
     "In what regime should this indicator be, by its nature?",
     {"expected_regime": "what YOU call the regime", "reading": "what it tells you"}),
    ("autopsy", "duty engineer at the cycle",
     "Why did the cycle die on this step?",
     {"failure": "true/false", "cause": "you name it"}),
    ("cycle_plan", "owner of the cycle",
     "What is your focus this cycle?",
     {"focus": "in a word or two", "success_test": "how you will know"}),
]


@pytest.mark.parametrize("kind,role,question,schema", THREE_KINDS,
                         ids=[k[0] for k in THREE_KINDS])
def test_the_assembled_prompt_has_no_cyrillic(captured, kind, role, question,
                                              schema):
    brain.think(role=role, question=question,
                evidence='{"axis": "CLIMATE_GLOBAL_RISK_REVIEW"}',
                schema=schema, kind=kind, remember_it=False)
    prompt = captured.prompts[0]
    frac = cyrillic_fraction(prompt)
    assert frac == 0.0, "kind={} still carries Cyrillic: {}".format(
        kind, cyrillic_runs(prompt)[:6])


def test_the_stance_prompt_carries_only_the_enum(captured, monkeypatch):
    """attend() is clean apart from the stance enum, which is Part 5's job."""
    monkeypatch.setattr(brain, "_AVAILABLE", True)
    monkeypatch.setattr(brain, "_prev_step_output", lambda: (None, None))
    monkeypatch.setattr(brain, "current_plan", lambda: {})
    monkeypatch.setattr(brain, "_record_silence", lambda *a, **k: None)
    _REAL_ATTEND("scoring_engine")
    prompt = captured.prompts[0]
    runs = [r.strip() for r in cyrillic_runs(prompt)]
    assert set(runs) <= {"върви|следи|пропусни", "go|watch|skip"}, runs


# ── the individual blocks, so a regression names the one that broke ─────────

def test_every_scaffold_block_is_english():
    from core import canon
    blocks = {
        "_body()": brain._body(),
        "_self_state()": brain._self_state(),
        "_spirit()": brain._spirit(),
        "canon as_frame()": canon.as_frame(),
        "_memory('constancy')": brain._memory("constancy", n=5),
        "LANGUAGE_PIN": brain.LANGUAGE_PIN,
    }
    dirty = {name: cyrillic_runs(text)[:3]
             for name, text in blocks.items() if cyrillic_fraction(text) > 0}
    assert not dirty, dirty


def test_the_five_interoception_rows_are_english_labels():
    from core import interoception as io
    assert io.ROWS == ("FALSE_ALARMS", "OPEN_PROPOSALS", "LAST_CYCLE",
                       "FREE_MEMORY", "RESTARTS_TODAY")
    assert io.UNKNOWN == "unknown"
    rendered = io.block()
    assert [line.split(":")[0] for line in rendered.splitlines()] == list(io.ROWS)
    assert cyrillic_fraction(rendered) == 0.0


def test_the_mirror_read_prompt_no_longer_permits_bulgarian():
    """It used to end 'Български или английски' — a licence to ignore the pin."""
    from core import interoception as io
    assert cyrillic_fraction(io.READ_PROMPT) == 0.0
    assert "Български или английски" not in io.READ_PROMPT
    assert "Do not invent a number that is not there." in io.READ_PROMPT, (
        "the anti-fabrication rule was dropped along with the language licence")


def test_every_schema_description_reaching_the_model_is_english():
    """Field NAMES were already ASCII everywhere — see COMMAND 25 Part 0.2 —
    so nothing here renames a key, and no consumer had to be chased."""
    import ast
    dirty = []
    for rel in ("core/brain.py", "core/constancy.py", "core/cycle_report.py",
                "core/reconsider.py", "core/self_diagnosis.py",
                "core/interoception.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name not in ("think", "thinker"):
                continue
            for kw in node.keywords:
                if kw.arg != "schema" or not isinstance(kw.value, ast.Dict):
                    continue
                for k, v in zip(kw.value.keys, kw.value.values):
                    key = k.value if isinstance(k, ast.Constant) else "?"
                    assert cyrillic_fraction(str(key)) == 0.0, (
                        "{}: Cyrillic FIELD NAME {!r} — that is a contract, not "
                        "text".format(rel, key))
                    try:
                        desc = ast.literal_eval(v)
                    except Exception:
                        continue
                    if cyrillic_fraction(str(desc)) > 0:
                        dirty.append("{}:{} {}".format(rel, node.lineno, key))
    # THE EXCEPTION LIST IS EMPTY AND STAYS EMPTY. For one commit it held
    # reconsider's "action" description — "напред или връщане", the two words
    # the model had to EMIT and three places compared against. Part 5 migrated
    # the enum to forward|rollback and this assertion went red the moment it
    # did, which is what an equality is for.
    assert not dirty, dirty
