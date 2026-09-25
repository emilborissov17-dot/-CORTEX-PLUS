"""
test/test_llm_text.py — task #29 (25 Sep 2026): model words as a type, and the consumers that refuse it.

What a refusal looks like: LLMTextRefused, naming the field, raised BEFORE the
consumer acts (nothing published, nothing sealed, no gate verdict). The forbidden
fallback is a consumer that accepts the words because they look like a value.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from core import llm_door, llm_parse
from core.llm_text import LLMText, LLMTextRefused, refuse_llm_text

REPO = Path(__file__).resolve().parents[1]
W = LLMText("  3.5 ", "Groq", "m", "step_x", "2026-09-25T00:00:00+00:00")


# ── the type ─────────────────────────────────────────────────────────────────

def test_the_mark_survives_cleanup_and_carries_its_origin():
    for v in (W.strip(), W[2:5], W.replace("3", "4"), W.lower(), W + "x", "x" + W,
              W.split()[0], W.splitlines()[0], W.partition(".")[0]):
        assert isinstance(v, LLMText), repr(v)
        assert (v.backend, v.model, v.step) == ("Groq", "m", "step_x")


def test_what_launders_it_is_stated_not_hidden():
    """Decision: str(), f-strings and json.loads are left to launder; the
    structural test below is the net for them, not this type."""
    assert type(str(W)) is str and type(f"{W}") is str
    assert type(json.loads(LLMText('{"a": "b"}'))["a"]) is str


# ── the door marks every answer ──────────────────────────────────────────────

@pytest.mark.parametrize("reply,path", [
    ({"choices": [{"message": {"content": "a"}, "finish_reason": "stop"}]},
     ("choices", 0, "message", "content")),
    ({"candidates": [{"content": {"parts": [{"text": "a"}]}}]},
     ("candidates", 0, "content", "parts", 0, "text")),
    ({"message": {"content": "a"}, "done_reason": "stop"}, ("message", "content")),
    ({"response": "a", "done_reason": "stop"}, ("response",)),
])
def test_call_returns_the_answer_as_llm_text(reply, path, monkeypatch):
    monkeypatch.setenv("CORTEX_STEP", "s1")
    d = llm_door.call("t", "Groq", "m", lambda: reply)
    for k in path:
        d = d[k]
    assert isinstance(d, LLMText) and d.backend == "Groq" and d.model == "m" and d.step == "s1"


def test_post_hands_back_a_response_whose_json_is_marked(monkeypatch):
    import requests

    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(requests, "post", lambda url, **kw: R())
    r = llm_door.post("t", "Groq", "m", "https://example.invalid/v1")
    assert isinstance(r.json()["choices"][0]["message"]["content"], LLMText)


# ── every consumer refuses by type, naming the field ─────────────────────────

def test_the_notary_refuses_a_model_named_step():
    from core import notary
    with pytest.raises(LLMTextRefused, match="prev_step"):
        notary.may_act("github_publish", LLMText("goal_score_calculator", "local:c", "c"))
    # attest() is replaced by a recorder in every test (conftest._NEUTRALISED);
    # vector() carries the same guard and is not.
    with pytest.raises(LLMTextRefused, match="notary.vector step"):
        notary.vector(LLMText("github_publish", "Groq", "m"), None)


def test_the_goal_score_refuses_model_words_in_its_inputs():
    import goal_score_calculator as g
    with pytest.raises(LLMTextRefused, match="last_obs"):
        g.compute_goal_score(trends={}, last_obs={"CLIMATE": {"v": W}}, targets={})


def test_the_publisher_refuses_before_any_request(monkeypatch):
    import github_publisher as gp
    sent = []
    monkeypatch.setattr(gp.requests, "put", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(gp.requests, "get", lambda *a, **k: sent.append(a))
    with pytest.raises(LLMTextRefused, match="github_publisher content"):
        gp._push_file("x.md", LLMText("words", "Groq", "m"), "msg")
    assert sent == []


def test_the_merkle_archive_refuses_and_seals_nothing(tmp_path, monkeypatch):
    import merkle_memory as mm
    monkeypatch.chdir(tmp_path)
    m = mm.MerkleMemory()
    with pytest.raises(LLMTextRefused, match="merkle_memory.commit decisions"):
        asyncio.run(m.commit(cycle_id="c1", signals=[], decisions=[{"d": W}],
                             results=[], goal_score=None))
    assert not list(mm.ARCHIVE.glob("cycle_*"))


@pytest.mark.parametrize("field", ["indicator", "expected_delta", "deadline"])
def test_proposal_intake_refuses_each_field_by_name(field):
    from core import proposal_intake as pi
    p = {"indicator": "CLIMATE", "expected_delta": 1.0, "deadline": "2026-12-01"}
    p[field] = LLMText(str(p[field]), "Groq", "m")
    with pytest.raises(LLMTextRefused, match=field.upper()):
        pi.judge(p, today=date(2026, 9, 25), resolver=lambda *a: (1.0, None),
                 cadence_check=lambda *a: None, scale_check=lambda *a: (None, None))


# ── the one way through ──────────────────────────────────────────────────────

def test_parse_returns_plain_typed_values():
    assert llm_parse.number(W, "x") == 3.5 and type(llm_parse.number(W, "x")) is float
    d = llm_parse.iso_date(LLMText(" 2026-12-01\n", "Groq", "m"), "deadline")
    assert d == date(2026, 12, 1) and type(d) is date
    allowed = ("KEPT", "NOT_KEPT")
    v = llm_parse.enum(LLMText("KEPT", "Groq", "m"), "verdict", allowed)
    assert v == "KEPT" and type(v) is str and not isinstance(v, LLMText)
    ind = llm_parse.indicator(LLMText("CLIMATE__co2", "Groq", "m"))
    assert ind == "CLIMATE__co2" and not isinstance(ind, LLMText)


@pytest.mark.parametrize("fn,arg", [
    (llm_parse.number, "about 3"), (llm_parse.number, "3.5 degrees"), (llm_parse.number, "nan"),
    (llm_parse.iso_date, "next Tuesday"), (llm_parse.iso_date, "2026-13-01"),
    (llm_parse.indicator, "climate"),
])
def test_parse_refuses_anything_that_is_not_exactly_one_value(fn, arg):
    with pytest.raises(llm_parse.LLMParseError):
        fn(LLMText(arg, "Groq", "m"), "f")


def test_a_parsed_proposal_is_admitted_by_type():
    from core import proposal_intake as pi
    raw = {"indicator": LLMText("CLIMATE", "Groq", "m"),
           "expected_delta": LLMText("+1.5", "Groq", "m"),
           "deadline": LLMText("2026-12-01", "Groq", "m"), "component": "x"}
    p = llm_parse.proposal_fields(raw)
    refuse_llm_text({k: p[k] for k in pi.REQUIRED}, "proposal")
    v = pi.judge(p, today=date(2026, 9, 25), resolver=lambda *a: (1.0, None),
                 cadence_check=lambda *a: None, scale_check=lambda *a: (None, None))
    assert v["verdict"] == "ADMITTED", v


# ── structure: no path from the door to a consumer except through llm_parse ──

CONSUMERS = ["core.notary", "goal_score_calculator", "github_publisher",
             "merkle_memory", "core.proposal_intake"]


def _graph():
    spec = importlib.util.spec_from_file_location("reach", REPO / "test" / "test_spine_llm_reach.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m._graph()


def _reaches_door(src, imports, removed=("core.llm_parse",)):
    seen, stack = set(), [src]
    while stack:
        x = stack.pop()
        if x in seen or x in removed:
            continue
        seen.add(x)
        for d in imports.get(x, ()):
            if d == "core.llm_door":
                return x
            stack.append(d)
    return None


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_no_consumer_reaches_the_door_except_through_llm_parse(consumer):
    files, imports = _graph()
    assert consumer in files, consumer
    via = _reaches_door(consumer, imports)
    assert via is None, f"{consumer} reaches core.llm_door (last hop from {via})"


def test_llm_parse_and_llm_text_do_not_import_the_door():
    for rel in ("core/llm_parse.py", "core/llm_text.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith("core.llm_door") for m in mods), (rel, mods)
    tree = ast.parse((REPO / "core/llm_text.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                and n.module and n.module.startswith("core")], "llm_text must import nothing from the repo"
