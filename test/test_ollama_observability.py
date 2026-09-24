"""
test/test_ollama_observability.py — Ollama leaves a record, and there is one keep_alive policy.

Task #19 (e), 24 Sep 2026. Phase 1 could not measure a model switch: the server
had no log file and provenance carried no load_duration; keep_alive was chosen by
each caller (30m, 0, -1).

Failure shapes: a load_duration in the reply that never reaches the row; a local
request that goes out with its caller's keep_alive instead of the policy's; a
starter that launches `ollama serve` itself, without the log; the cycle's model
left on the card after the cycle.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import llm_door, model_window  # noqa: E402


class _R:
    status_code = 200

    @staticmethod
    def json():
        return {"message": {"content": "ok"}, "done_reason": "stop",
                "load_duration": 7_250_000_000, "prompt_eval_duration": 1_500_000_000,
                "eval_duration": 900_000_000, "prompt_eval_count": 40, "eval_count": 12}


def _sent(monkeypatch):
    bodies = []
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **k: bodies.append(k.get("json")) or _R())
    return bodies


def test_load_and_prompt_eval_durations_reach_the_row(monkeypatch):
    _sent(monkeypatch)
    llm_door.post("t", "local:m", "m", "http://x/api/chat", json={"model": "m"})
    row = json.loads(llm_door.PROVENANCE.read_text(encoding="utf-8").splitlines()[-1])
    assert row["load_duration_s"] == 7.25 and row["prompt_eval_duration_s"] == 1.5
    assert row["eval_duration_s"] == 0.9


def test_one_keep_alive_policy_is_applied_to_every_local_request(monkeypatch):
    bodies = _sent(monkeypatch)
    local = model_window.cycle_local_model()
    monkeypatch.setenv("CORTEX_IN_CYCLE", "c")
    llm_door.post("t", f"local:{local}", local, "http://x/api/chat", json={"model": local, "keep_alive": "30m"})
    llm_door.post("t", "local:other", "other", "http://x/api/chat", json={"model": "other", "keep_alive": "30m"})
    monkeypatch.delenv("CORTEX_IN_CYCLE")
    monkeypatch.delenv("CORTEX_CYCLE_ID", raising=False)
    llm_door.post("t", f"local:{local}", local, "http://x/api/chat", json={"model": local, "keep_alive": -1})
    assert [b["keep_alive"] for b in bodies] == [-1, 0, 0], bodies


def test_every_starter_goes_through_tools_ollama_serve():
    pulse = (REPO / "experiments" / "pulse" / "pulse_continuum.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(pulse)):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.List):
            items = [ast.get_source_segment(pulse, e) for e in node.args[0].elts]
            assert '"serve"' not in items, "pulse_continuum starts `ollama serve` itself, with no log"
    assert "ollama_serve.ps1" in pulse
    collector = (REPO / "experiments" / "collector" / "run_collector.ps1").read_text(encoding="utf-8")
    code = [ln for ln in collector.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("-ArgumentList 'serve'" in ln for ln in code)
    assert any("ollama_serve.ps1" in ln for ln in code)


def test_the_runner_unloads_the_cycle_model_at_the_end():
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_mw.unload_cycle_model" in calls
