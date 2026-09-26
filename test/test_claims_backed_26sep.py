"""
test/test_claims_backed_26sep.py — assertions behind behaviour sentences that had none (C2d, 26 Sep 2026).

Each test names the sentence it backs (file and gist). If one of these goes red, the
sentence it backs is false and must be fixed or deleted with it.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


# Backs: core/groq_backend.py and core/llm_door.py, the one-row-per-path sentence.
def test_post_writes_one_row_on_every_path(tmp_path, monkeypatch):
    import requests
    from core import llm_door
    rows_file = tmp_path / "prov.jsonl"
    monkeypatch.setattr(llm_door, "PROVENANCE", rows_file)

    class R:
        def __init__(self, status, body):
            self.status_code, self._b = status, body

        def json(self):
            return self._b

    def rows():
        return [json.loads(l) for l in rows_file.read_text(encoding="utf-8").splitlines()] if rows_file.exists() else []

    cases = [(R(200, {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}), "ok"),
             (R(500, {}), "error"),
             (R(200, {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}), "error")]
    for resp, want in cases:
        monkeypatch.setattr(requests, "post", lambda url, _r=resp, **kw: _r)
        n = len(rows())
        llm_door.post("t", "Groq", "m", "https://example.invalid/v1")
        got = rows()
        assert len(got) == n + 1 and got[-1]["outcome"] == want and got[-1]["schema"] == 2
        assert isinstance(got[-1]["latency_s"], float)

    def boom(url, **kw):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "post", boom)
    n = len(rows())
    try:
        llm_door.post("t", "Groq", "m", "https://example.invalid/v1")
    except requests.ConnectionError:
        pass
    got = rows()
    assert len(got) == n + 1 and got[-1]["outcome"] == "error" and isinstance(got[-1]["latency_s"], float)


# Backs: core/llm_door.py, the _reply_facts docstring.
def test_reply_facts_read_every_dialect():
    from core.llm_door import _facts_from_dict as f
    o = f({"choices": [{"message": {"content": "abc"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
    assert (o["finish_reason"], o["reply_chars"], o["prompt_tokens"], o["completion_tokens"]) == ("stop", 3, 3, 4)
    g = f({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ab"}]}}],
           "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6}})
    assert (g["finish_reason"], g["reply_chars"], g["prompt_tokens"], g["completion_tokens"]) == ("STOP", 2, 5, 6)
    l = f({"message": {"content": "abcd"}, "done_reason": "stop", "prompt_eval_count": 7, "eval_count": 8})
    assert (l["finish_reason"], l["reply_chars"], l["prompt_tokens"], l["completion_tokens"]) == ("stop", 4, 7, 8)
    assert f({"text": "hello"})["reply_chars"] == 5


# Backs: core/llm_door.py, the TIMEOUTS FROM MEASUREMENT comment (recompute at boot).
def test_the_runner_recomputes_the_timeouts_at_boot():
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8-sig"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "recompute"
               for n in ast.walk(funcs["_classify_cycle_id"])), "_classify_cycle_id no longer recomputes"
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_classify_cycle_id"
               for n in ast.walk(funcs["main"])), "main() no longer classifies the cycle id at boot"


# Backs: core/redact.py, the mask_secrets docstring.
def test_mask_secrets_masks_exactly_what_redact_redacts():
    from core.redact import mask_secrets, redact
    samples = [
        "GET https://api.telegram.org/bot1234567890:AAH" + "x" * 33 + "/sendMessage",
        "https://generativelanguage.googleapis.com/v1/models:generate?key=AIza" + "y" * 35,
        "plain prose with no secret at all", "a number 1234567 and a word key",
    ]
    for s in samples:
        assert (redact(s)[0] != s) == (mask_secrets(s) != s), s[:60]
        if mask_secrets(s) != s:
            assert mask_secrets(s) != redact(s)[0], "same replacement as redact()"
