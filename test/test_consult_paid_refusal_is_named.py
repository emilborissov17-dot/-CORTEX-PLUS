# -*- coding: utf-8 -*-
"""test/test_consult_paid_refusal_is_named.py — the third path had no guard at all.

THE DEFECT, verified from the code on 19 September 2026 before anything was
changed. consult.ask_kimi() is the free-only path. It tries three backends:

    1st  _ask_nvidia_kimi   NO GUARD — took whatever `model` the endpoint named
                            and returned ok=True with cost_usd=0.0
    2nd  _ask_groq_kimi     refuses anything outside GROQ_FREE_MODELS
    3rd  the OpenRouter router   refuses anything without ':free'

_ask_nvidia_kimi landed on 11 Sep (5693e23) ABOVE the two guarded paths and is
tried FIRST, so it short-circuits both. NVIDIA_API_KEY is present on this
machine: the path is live. The guard was not removed, it was OVERTAKEN — which
the file's own header already records happening once before, on 10 Sep, when the
Groq path overtook it: "Пазачът не беше махнат, беше заобиколен."

HAS IT EVER SERVED A PAID ANSWER? Unanswerable from the record, and that is its
own finding: consult.py wrote NO provenance at all. memory/llm_provenance.jsonl
holds 9120 rows and not one names this caller. What bounds it: the NVIDIA path
landed 2026-09-11 and the last recorded consult is 2026-09-10, so it has most
likely never served a real request. Nothing contradicts that; nothing proves it.

FREEDOM IS PER PATH, AND THE EVIDENCE FORCED THAT. Read from the live NIM
catalogue on 19 Sep: 82 models, exactly two Kimi ids — moonshotai/kimi-k3 and
moonshotai/kimi-k2.6 — both on the free developer tier. The SAME slug
moonshotai/kimi-k2.6 is PAID on OpenRouter, where every moonshot slug lost its
:free on 10 Sep. One global "is this model free" table would have to be wrong
for one of them. The question is only answerable as (endpoint, plan, model).

THE PREFIX (defect b) was a label, not a route. `backend` is branched on in
exactly two places, both `!= "local"`, which doubling cannot affect. It corrupts
the name a human reads to know who answered, and breaks equality with the slug.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from experiments.kimi_duel import consult   # noqa: E402

PAID = "moonshotai/kimi-k2-0711-preview"     # in nobody's table, nowhere :free
NVIDIA_MODEL = "moonshotai/kimi-k3"          # what the live resolver picks


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _served(model_id, text="мнение"):
    return {"model": model_id, "choices": [{"message": {"content": text}}],
            "usage": {"total_tokens": 10}}


@pytest.fixture
def run_consult(tmp_path, monkeypatch):
    """Drive ask_kimi with a stubbed transport, writing nothing live."""
    prov = tmp_path / "llm_provenance.jsonl"
    monkeypatch.setattr(consult, "PROVENANCE", prov)

    def _go(served_model):
        import requests
        import core.groq_backend as gb
        calls = []

        def fake_post(url, **kw):
            calls.append(kw["json"]["model"])
            return _Resp(200, _served(served_model))

        monkeypatch.setattr(requests, "post", fake_post)
        # Hermetic: _nvidia_model does a real GET and caches in a module global.
        monkeypatch.setattr(gb, "_nvidia_model", lambda key: NVIDIA_MODEL)
        res = consult.ask_kimi("бриф", max_tokens=10)
        rows = []
        if prov.exists():
            rows = [json.loads(l) for l in prov.read_text(encoding="utf-8").splitlines() if l.strip()]
        return res, calls, rows

    return _go


# ── 1. a paid model is refused BY NAME ──────────────────────────────────────

def test_a_paid_model_offered_to_a_free_only_request_is_refused_by_name(run_consult):
    """THE ONE THAT MATTERS. Before the fix the NVIDIA path returned this as a
    free consult, ok=True, cost_usd=0.0."""
    res, calls, _rows = run_consult(PAID)
    assert res["ok"] is False, "a paid model was accepted on the free-only path"
    assert res["backend"] == "none"
    named = [t for t in res["tried"] if PAID in t]
    assert named, (
        "the refusal does not NAME the model that served it: %r" % res["tried"])


def test_all_three_paths_refuse_it_not_just_the_two_that_had_guards(run_consult):
    """The defect was one unguarded path among three, so each is checked."""
    res, calls, _rows = run_consult(PAID)
    tried = "\n".join(res["tried"])
    assert "nvidia:" in tried, "the NVIDIA path did not refuse: %r" % res["tried"]
    assert "GROQ_FREE_MODELS" in tried, "the Groq path did not refuse by declaration"
    assert any(s in tried for s in consult.OPPONENTS), "the router did not refuse"
    assert calls[0] == NVIDIA_MODEL, "NVIDIA is tried first: %r" % calls[:3]
    assert len(calls) == len(consult.OPPONENTS) + 2


def test_a_paid_answer_is_never_returned_as_a_free_one(run_consult):
    """The forbidden fallback in one line: ok=True with cost_usd=0.0 for a model
    nobody declared free."""
    res, _c, _r = run_consult(PAID)
    assert not (res.get("ok") and res.get("cost_usd") == 0.0)


# ── 2. a free model is accepted ─────────────────────────────────────────────

def test_a_free_model_is_accepted(run_consult):
    """Negative control: 'everything is refused' must not pass for correctness."""
    free = consult.OPPONENTS[-1]
    res, _c, _r = run_consult(free)
    assert res["ok"] is True, res
    assert res["cost_usd"] == 0.0


def test_a_model_declared_free_on_the_nvidia_path_is_accepted_there(run_consult):
    """moonshotai/kimi-k3 carries no ':free' and IS free on NIM. A slug-only
    rule would refuse a legitimate answer."""
    res, calls, _r = run_consult(NVIDIA_MODEL)
    assert res["ok"] is True, res
    assert len(calls) == 1, "it should have stopped at the first path: %r" % calls


# ── 3. the refusal is recorded in provenance, with its reason ───────────────

def test_the_refusal_is_recorded_in_provenance_with_its_reason(run_consult):
    """consult.py recorded nothing at all, which is why 'has this ever happened'
    had no answer on 19 Sep."""
    _res, _calls, rows = run_consult(PAID)
    assert rows, "a refusal was not recorded in provenance at all"
    refusals = [r for r in rows if r.get("refused")]
    assert refusals, "rows were written but none is marked as a refusal: %r" % rows[:2]
    for r in refusals:
        assert r.get("caller") == "consult:free_only", r
        assert r.get("model"), "the refused model is not named in the row"
        assert r.get("reason"), "the row carries no reason"
    assert any(r["model"] == PAID for r in refusals), (
        "the paid model that served the request is not in the record")


def test_the_path_that_ACCEPTS_records_no_refusal(run_consult):
    """Mutation guard: if every call recorded a refusal the row would mean
    nothing.

    Checked on the path that accepts. An OpenRouter ':free' slug is a poor
    control here, and my first draft of this test got it wrong: NVIDIA and Groq
    are tried first and legitimately refuse it, because that slug is not
    declared free on THOSE paths. Those refusals are real and belong on the
    record. moonshotai/kimi-k3 is accepted by the first path, so a refusal row
    would have to be spurious.
    """
    res, calls, rows = run_consult(NVIDIA_MODEL)
    assert res["ok"] is True and len(calls) == 1
    assert not [r for r in rows if r.get("refused")], rows


# ── 4. the prefix is built once ─────────────────────────────────────────────

def test_the_backend_label_is_built_once(run_consult):
    """'nvidia:nvidia/nemotron-3-super-120b-a12b:free' — the vendor twice."""
    free = consult.OPPONENTS[-1]
    res, _c, _r = run_consult(free)
    assert res["backend"] == free, res["backend"]
    assert not res["backend"].startswith("nvidia:nvidia/")


@pytest.mark.parametrize("path,served,expected", [
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b:free",
     "nvidia/nemotron-3-super-120b-a12b:free"),          # already carries it
    ("groq", "moonshotai/kimi-k2-instruct-0905",
     "groq:moonshotai/kimi-k2-instruct-0905"),           # different vendor
    ("nvidia", "moonshotai/kimi-k3", "nvidia:moonshotai/kimi-k3"),
])
def test_label_never_repeats_the_vendor(path, served, expected):
    assert consult._label(path, served) == expected


# ── 5. classification never defaults — it raises on an unknown model ────────

def test_an_unknown_model_raises_instead_of_defaulting():
    """THE GUARD THE WHOLE FIX RESTS ON.

    A boolean has a comfortable default and somebody eventually takes it. An
    unraised question cannot be defaulted into 'probably fine'.
    """
    with pytest.raises(consult.UnknownModelFreedom):
        consult.classify_freedom("nvidia", "some/model-nobody-declared")
    with pytest.raises(consult.UnknownModelFreedom):
        consult.classify_freedom("groq", "some/model-nobody-declared")


def test_an_unknown_PATH_raises_too():
    """A fourth backend added above the others is exactly how this happened. A
    path with no table must not be silently treated as free."""
    with pytest.raises(consult.UnknownModelFreedom):
        consult.classify_freedom("some_new_provider", "anything/at-all:free")


def test_classification_is_free_or_paid_and_nothing_else():
    assert consult.classify_freedom("openrouter", "x/y:free") == "free"
    assert consult.classify_freedom("openrouter", "x/y") == "paid"
    assert consult.classify_freedom("nvidia", NVIDIA_MODEL) == "free"
    assert consult.classify_freedom("groq", consult.GROQ_KIMI) == "free"


def test_every_declared_path_has_a_non_empty_table():
    """An empty table would make every model unknown, which reads as 'refuse
    everything' — safe, but it would disable a path without saying so."""
    for path, table in consult.FREE_BY_PATH.items():
        assert table, "FREE_BY_PATH[%r] is empty" % path


def test_no_path_classifies_by_falling_back_to_the_slug():
    """Mutation guard. If the nvidia branch were replaced by the openrouter
    rule, ':free' alone would decide — and moonshotai/kimi-k3, which is free on
    NIM and carries no ':free', would be wrongly refused while an undeclared
    ':free' slug would be wrongly accepted."""
    assert consult.classify_freedom("nvidia", NVIDIA_MODEL) == "free"
    with pytest.raises(consult.UnknownModelFreedom):
        consult.classify_freedom("nvidia", "someone/else:free")
