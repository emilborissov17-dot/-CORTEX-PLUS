# -*- coding: utf-8 -*-
"""The numeric-judge ROLE: chosen by name in a config, never by renaming a model.

core/brain.numeric_judge() returns the model config/model_roles.json names, but ONLY
if it is installed. Everything else — no config, broken config, model absent — is
None, and None obliges the caller to fall back AND say so. A guard that silently
substitutes the small model would put weak verdicts under the judge's name, which is
the whole failure this role exists to prevent.
"""
import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import brain  # noqa: E402


def _roles(tmp_path, doc):
    p = tmp_path / "model_roles.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_the_named_model_is_returned_when_it_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "ROLES", _roles(tmp_path, {"numeric_judge": "cortex-l1b-3b:latest"}))
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b", "cortex-l1b-3b:latest"])
    assert brain.numeric_judge() == "cortex-l1b-3b:latest"


def test_a_missing_model_is_none_and_never_a_substitute(monkeypatch, tmp_path):
    """THE ONE THAT MATTERS. The config names a model this machine does not have.
    The forbidden answer is any other model's name — silently judging numbers with
    qwen2.5:3b (measured 0/9) under the judge's role is worse than not judging."""
    monkeypatch.setattr(brain, "ROLES", _roles(tmp_path, {"numeric_judge": "cortex-l1b-3b:latest"}))
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b", "qwen3:8b"])
    assert brain.numeric_judge() is None


def test_a_bare_name_resolves_to_the_latest_tag(monkeypatch, tmp_path):
    """ollama lists what you create as '<name>:latest'; the probe lost 23 calls to a
    fallback for exactly this reason on 12 Sep."""
    monkeypatch.setattr(brain, "ROLES", _roles(tmp_path, {"numeric_judge": "cortex-l1b-3b"}))
    monkeypatch.setattr(brain, "models", lambda: ["cortex-l1b-3b:latest"])
    assert brain.numeric_judge() == "cortex-l1b-3b:latest"


def test_no_config_and_broken_config_are_none_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "models", lambda: ["cortex-l1b-3b:latest"])
    monkeypatch.setattr(brain, "ROLES", tmp_path / "does_not_exist.json")
    assert brain.numeric_judge() is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setattr(brain, "ROLES", bad)
    assert brain.numeric_judge() is None
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(brain, "ROLES", empty)
    assert brain.numeric_judge() is None


def test_a_non_string_role_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(brain, "models", lambda: ["cortex-l1b-3b:latest"])
    monkeypatch.setattr(brain, "ROLES", _roles(tmp_path, {"numeric_judge": ["a", "list"]}))
    assert brain.numeric_judge() is None


def test_the_repo_config_names_an_installed_model_or_says_none():
    """The config as it ships. This must never raise, whatever is installed here."""
    out = brain.numeric_judge()
    assert out is None or isinstance(out, str)
    doc = json.loads((BASE / "config" / "model_roles.json").read_text(encoding="utf-8"))
    assert doc["numeric_judge"] == "cortex-l1b-3b:latest"
    assert doc.get("_why"), "a role with no recorded reason is a guess wearing a config"


def test_constancy_falls_back_out_loud(monkeypatch, capsys):
    """When there is no judge, core/constancy.py must SAY which model it used instead.
    A silent fallback puts qwen2.5:3b's verdicts under the judge's name."""
    spec = importlib.util.spec_from_file_location("_constancy", BASE / "core" / "constancy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(brain, "numeric_judge", lambda: None)
    line = mod._judge_banner(None)
    assert "fast" in line.lower() or "smallest" in line.lower()
    assert "0/9" in line, "the fallback must carry the number that makes it a warning"
    named = mod._judge_banner("cortex-l1b-3b:latest")
    assert "cortex-l1b-3b:latest" in named
