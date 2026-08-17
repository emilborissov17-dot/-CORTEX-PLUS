"""The cycle log must survive the abrupt kill it exists to record.

THE BUG (2026-07-15)
--------------------
This morning's catch-up cycle ran ~20 minutes, then died at 99% RAM inside
web_intelligence. Its cycle log — memory/cycle_logs/cycle_2026-07-15_083902.log —
was 0 bytes. Not truncated: empty. Redirected to a file (not a tty) the child's
stdout is BLOCK-buffered, so every line it printed sat in an in-process buffer
that never reached disk, and an OOM kill took the buffer with it. The one run the
log most needed to explain explained nothing.

THE FIX
-------
spawn_cycle() runs the child with PYTHONUNBUFFERED=1, so output lands line by line
and a death cannot erase what came before it. These tests pin that: one behavioural
(a real child, hard-killed, whose earlier lines are on disk anyway) and one static
(the env var is actually set), so the fix holds even on a machine too fast or slow
for timing alone to discriminate.
"""
import time

import pytest

import supervisor as sup


def test_child_output_survives_a_hard_kill(tmp_path, monkeypatch):
    """PYTHONUNBUFFERED=1 is load-bearing, not cosmetic.

    A child whose stdout is redirected to a file (not a tty) is BLOCK-buffered:
    output sits in an in-process buffer until it fills (~8 KB) or the process
    exits cleanly. An abrupt kill — OOM under memory pressure, taskkill /F — does
    NEITHER, so that buffer dies with the process and the log is 0 bytes for the
    one run it most needed to explain (observed 2026-07-15).

    Spawn a REAL child through spawn_cycle, watch its lines reach disk WHILE IT IS
    STILL ALIVE (which only happens because the env forces unbuffered writes — a
    block-buffered child would leave the file empty for the whole test), then
    hard-kill it and prove those lines survived the kill. Without PYTHONUNBUFFERED
    the mid-flight poll below would time out and this test would fail.
    """
    runner = tmp_path / "chatty.py"
    runner.write_text(
        "import time\n"
        "for i in range(300):\n"
        "    print(f'line {i}')\n"          # deliberately NO flush=True — relies on the env
        "    time.sleep(0.02)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sup, "RUNNER", runner)
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    # spawn_cycle also starts a detached reaper; keep its two sinks in the sandbox.
    monkeypatch.setattr(sup, "CYCLE_EXIT_PATH", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")

    pid = sup.spawn_cycle("hard-kill-test")
    assert pid, "the child failed to spawn"

    try:
        logs = list((tmp_path / "cycle_logs").glob("cycle_*.log"))
        assert len(logs) == 1, f"expected one cycle log, got {logs}"
        log_file = logs[0]

        # Unbuffered: early lines land within ~100 ms while the child is ALIVE.
        # Block-buffered (env var missing): the ~8 KB buffer never fills in this
        # test's lifetime and the file stays empty — so this poll would time out.
        deadline = time.monotonic() + 6.0
        seen = ""
        while time.monotonic() < deadline:
            seen = log_file.read_text(encoding="utf-8", errors="replace")
            if "line 3" in seen:
                break
            time.sleep(0.05)
        assert "line 3" in seen, (
            "no output reached disk while the child was alive — is PYTHONUNBUFFERED set "
            "in the child env? A block-buffered child loses everything on a hard kill."
        )

        # Now HARD-kill it — the abrupt way an OOM does, no chance to flush.
        assert sup.kill_tree(pid), "failed to kill the child"
    finally:
        sup.kill_tree(pid)      # never leak the child if an assert above fired

    # The lines printed BEFORE the kill are on disk despite it.
    final = log_file.read_text(encoding="utf-8", errors="replace")
    assert "line 0" in final and "line 3" in final, (
        "lines printed before the kill did not survive it"
    )


def test_spawn_passes_pythonunbuffered_to_the_child():
    """A static guard on the env, independent of timing: the child MUST inherit
    PYTHONUNBUFFERED. This pins the fix even on a machine too fast or too slow for
    the behavioural test above to discriminate."""
    import ast
    src = open(sup.__file__, encoding="utf-8").read()
    tree = ast.parse(src)

    # Find the env dict literal in spawn_cycle and assert the key is set to "1".
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "PYTHONUNBUFFERED":
                    assert isinstance(v, ast.Constant) and v.value == "1"
                    found = True
    assert found, "spawn_cycle must set PYTHONUNBUFFERED=1 in the child env"
