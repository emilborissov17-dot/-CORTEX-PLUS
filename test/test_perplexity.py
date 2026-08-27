#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_perplexity.py — AN INTERNAL QUANTITY, TREATED LIKE AN EXTERNAL ONE.

Every threshold in this repo is a number I chose. This is the first that comes
out of the weights. The tests hold three things:

  * it is DISABLED by default and makes no call from any path when off;
  * the perplexity is real arithmetic over real logprobs, not a stand-in;
  * both numbers are recorded for every emission — what the code threshold said
    and what the model said — which is the mediation ratio.

No test here calls the model. The one real call is in --once and in the report.

    venv/Scripts/python.exe -m pytest test/test_perplexity.py -v
"""
from __future__ import annotations

import ast
import json
import math
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import event_bus as eb          # noqa: E402
from core import perplexity as px         # noqa: E402
from core import extra_calls as ec  # noqa: E402

@pytest.fixture(autouse=True)
def a_machine_with_room(monkeypatch):
    """The four guards read THIS laptop; these tests are not about it.

    COMMAND 33 part 5 routed this module through core/extra_calls.py, and the
    resource guard declines when free RAM is under 600MB or free VRAM under
    400MB. So every test below silently became a question about whether Emil
    had a browser open: with the GPU at 282MB free, seven of them failed while
    the door was working perfectly and the reaction logic was untouched.

    Tests that ARE about the guards live in test_extra_calls.py and set their
    own values there.
    """
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 8000.0)
    monkeypatch.setattr(ec, "_vram_free_mb", lambda: (8000.0, None))
    monkeypatch.setattr(ec, "_models_running", lambda *a, **k: (0, None))

from core import receptors as rc          # noqa: E402


@pytest.fixture
def bank(tmp_path):
    return rc.ReceptorBank(bus=eb.EventBus(), seed_path=tmp_path / "s.json")


# ═══ OFF BY DEFAULT ═════════════════════════════════════════════════════════

def test_it_is_disabled_in_the_committed_config():
    assert px.enabled() is False
    d = json.loads((REPO / "config" / "reactions.json").read_text(
        encoding="utf-8"))
    assert d["perplexity"]["enabled"] is False


def test_a_missing_or_broken_config_means_disabled(tmp_path):
    assert px.enabled(tmp_path / "absent.json") is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert px.enabled(bad) is False


def test_the_flag_file_is_on_the_protected_denylist():
    """The system must never be able to switch its own model calls on."""
    from safety.protected_paths import is_protected
    assert is_protected("config/reactions.json") is True


def test_the_flag_file_carries_no_hash():
    """Unstamped on purpose: a hash re-cut every time a switch is flipped is a
    hash nobody checks. The denylist is what guards it instead."""
    d = json.loads((REPO / "config" / "reactions.json").read_text(
        encoding="utf-8"))
    assert "sha256" not in d
    assert "_README" in d


def test_no_module_calls_measure_unconditionally():
    """With the flag off, no model call is made from any path. Parsed: every
    call to measure() outside this module must sit under an enabled() check."""
    import subprocess
    r = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                       capture_output=True, text=True)
    offenders = []
    for rel in r.stdout.splitlines():
        if rel in ("core/perplexity.py",) or rel.startswith("test/"):
            continue
        try:
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8",
                                                    errors="replace"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "measure":
                offenders.append((rel, n.lineno))
    assert not offenders, offenders


# ── the arithmetic is real ──────────────────────────────────────────────────

def test_perplexity_is_exp_of_the_negative_mean_logprob(monkeypatch):
    """Not a stand-in. The number is the definition, computed over the logprobs
    the endpoint actually returned."""
    lps = [-0.10, -0.20, -0.30, -0.40]
    payload = {"response": "steady", "eval_count": 4,
               "prompt_eval_count": 40,
               "logprobs": [{"token": "t{}".format(i), "logprob": v}
                            for i, v in enumerate(lps)]}
    _fake_endpoint(monkeypatch, payload)
    r = px.measure(vector={"fields": ["ram_percent"], "vector": [80.0]})
    assert r["n_tokens"] == 4
    assert abs(r["mean_logprob"] - (sum(lps) / 4)) < 1e-12
    assert abs(r["perplexity"] - math.exp(-sum(lps) / 4)) < 1e-12


def test_certainty_is_one_and_uncertainty_is_larger(monkeypatch):
    _fake_endpoint(monkeypatch, {"response": "x", "logprobs":
                                 [{"token": "a", "logprob": 0.0}] * 5})
    assert abs(px.measure()["perplexity"] - 1.0) < 1e-9
    _fake_endpoint(monkeypatch, {"response": "x", "logprobs":
                                 [{"token": "a", "logprob": -2.0}] * 5})
    assert px.measure()["perplexity"] > 7.0


def _fake_endpoint(monkeypatch, payload):
    import io
    import urllib.request

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(req, timeout=None):
        return _R(json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(urllib.request, "urlopen", _open)


def test_a_response_with_no_logprobs_is_reported_not_guessed(monkeypatch):
    """The honest failure. A fabricated internal quantity is worse than an
    honest external one."""
    _fake_endpoint(monkeypatch, {"response": "hello", "eval_count": 3})
    r = px.measure()
    assert r["perplexity"] is None
    assert "logprobs" in r["why"]


def test_an_unreachable_model_never_raises(monkeypatch):
    import urllib.request

    def _boom(req, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    r = px.measure()
    assert r["perplexity"] is None
    assert "OSError" in r["why"]


def test_the_request_asks_for_logprobs(monkeypatch):
    """The exact option name this Ollama version needs."""
    seen = {}
    import io
    import urllib.request

    class _R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(req, timeout=None):
        seen.update(json.loads(req.data.decode("utf-8")))
        return _R(json.dumps({"response": "", "logprobs": []}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", _open)
    px.measure()
    assert seen["logprobs"] is True
    assert seen["stream"] is False
    assert seen["options"]["temperature"] == 0


# ── the sentence comes from the vector ──────────────────────────────────────

def test_the_sentence_is_built_from_the_cycle_vector():
    """The same object the lexicon fits on, not a second prettier summary."""
    v = {"fields": ["ram_percent", "cpu_percent"], "vector": [82.5, 6.0]}
    s = px.state_sentence(v)
    assert "ram_percent 82.5" in s and "cpu_percent 6.0" in s


def test_a_dimension_that_was_not_measured_is_not_described():
    v = {"fields": ["ram_percent", "gpu_temp_c"], "vector": [82.5, None]}
    s = px.state_sentence(v)
    assert "gpu_temp_c" not in s


def test_no_adjectives_are_put_in_the_model_s_mouth():
    v = {"fields": ["ram_percent"], "vector": [99.9]}
    s = px.state_sentence(v).lower()
    for word in ("critical", "high", "low", "healthy", "bad", "good",
                 "urgent", "dangerous"):
        assert word not in s, word


def test_an_empty_vector_says_so_rather_than_inventing():
    assert px.state_sentence({"fields": [], "vector": []}) == \
        "No readings are available."


# ── it is an ordinary receptor ──────────────────────────────────────────────

def test_it_calibrates_like_every_other_receptor(bank):
    pr = px.PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=4)
    for x in (1.30, 1.31, 1.29, 1.30):
        assert pr.feed({"perplexity": x, "model": "t"}) is None
    assert pr.receptor.emitted == 0


def test_a_jump_in_its_own_uncertainty_emits(bank):
    pr = px.PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=3)
    for x in (1.3, 1.3, 1.3):
        pr.feed({"perplexity": x, "model": "t"})
    ev = pr.feed({"perplexity": 6.0, "model": "t"})
    assert ev is not None
    assert ev.channel == eb.CHANNEL_R
    assert ev.topic == "receptor.model_perplexity"


def test_it_is_tagged_source_model_directed_self(bank):
    pr = px.PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=2)
    pr.feed({"perplexity": 1.3, "model": "t"})
    pr.feed({"perplexity": 1.3, "model": "t"})
    ev = pr.feed({"perplexity": 9.0, "model": "qwen2.5:3b"})
    assert ev.meta["source"] == "model"
    assert ev.meta["directed"] == "self"
    assert ev.meta["reflexivity"] == 1, (
        "a model pass over a state it just read is reflexivity 1 by the "
        "cockpit/timeline.py ladder")
    assert ev.meta["model"] == "qwen2.5:3b"


def test_the_tick_receptor_stays_reflexivity_zero():
    """This one IS a model pass. The tick is not, and the two must not blur."""
    from core import proprioception as pp
    assert pp.REFLEXIVITY == 0
    assert px.SOURCE == "model" and pp.DIRECTED == "self"


def test_a_failed_measurement_is_counted_not_published(bank):
    pr = px.PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=1)
    assert pr.feed({"perplexity": None, "why": "no logprobs"}) is None
    assert pr.failures == 1 and pr.measurements == 0


def test_it_has_its_own_anchor_like_any_receptor(bank):
    pr = px.PerplexityReceptor(bank=bank, eps=0.5, calibration_ticks=2)
    assert pr.receptor.anchor_band == 0.5 * rc.ANCHOR_K


# ── the mediation ratio ─────────────────────────────────────────────────────

def test_both_numbers_are_recorded_for_every_emission(tmp_path):
    log = tmp_path / "m.jsonl"
    px.record_mediation({"perplexity": 2.0}, code_said=True, model_said=False,
                        path=log)
    r = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert r["code_said"] is True and r["model_said"] is False
    assert r["agree"] is False
    assert r["perplexity"] == 2.0


def test_the_ratio_is_model_over_code(tmp_path):
    log = tmp_path / "m.jsonl"
    for c, m in ((True, True), (True, False), (True, True), (False, False)):
        px.record_mediation({"perplexity": 1.0}, code_said=c, model_said=m,
                            path=log)
    got = px.mediation_ratio(log)
    assert got["n"] == 4 and got["code_said"] == 3 and got["model_said"] == 2
    assert abs(got["ratio"] - 2 / 3) < 1e-9
    assert got["agreed"] == 3 and got["agreement"] == 0.75


def test_an_empty_log_reports_zero_rather_than_dividing_by_it(tmp_path):
    got = px.mediation_ratio(tmp_path / "absent.jsonl")
    assert got["n"] == 0 and got["ratio"] is None
    assert "disabled by default" in got["why"]


def test_the_mediation_log_is_durable():
    tree = ast.parse((REPO / "core" / "perplexity.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "record_mediation")
    names = {a.name for n in ast.walk(fn)
             if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "append_json" in names


def test_nothing_consults_the_mediation_ratio():
    """It is a metric. The moment anything reads it back into a decision it
    stops measuring how much of the speech is the model's and starts shaping
    it."""
    import subprocess
    r = subprocess.run(["git", "grep", "-l", "mediation_ratio"], cwd=str(REPO),
                       capture_output=True, text=True)
    readers = [f for f in r.stdout.splitlines()
               if f not in ("core/perplexity.py", "test/test_perplexity.py")]
    assert not readers, readers


def test_the_selftest_passes():
    assert px._selftest() == 0
