"""One guarded door, and the GPU is clean when it closes.

Reaction and perplexity each make a model call at EVERY phase boundary — about
63 a night, each — which is the shape that produced AllBackendsFailedError.
Before this, both built their own Ollama request and NEITHER PASSED keep_alive
AT ALL. Ollama does not cancel inference when the HTTP request times out, so a
timed-out extra call left the model resident and the GPU busy for whatever
regular step ran next: the timeout protected the caller and handed the cost to
the cycle.

Four guards, and no others. The tests below are mostly about the guards NOT
being reachable around — a door with a way past it is a corridor.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import extra_calls as ec  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_breaker(monkeypatch):
    """A clean breaker AND a machine with room.

    The resource guard reads THIS laptop. Without pinning it, every test below
    that expects a call to go out is really asking "is Emil running anything
    right now" — nine of them failed under a concurrent test run, with the door
    behaving perfectly. The three tests that are about resources set their own
    values inside the test body, which overrides this.
    """
    ec.reset_cycle()
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 8000.0)
    monkeypatch.setattr(ec, "_vram_free_mb", lambda: (8000.0, None))
    monkeypatch.setattr(ec, "_models_running", lambda *a, **k: (0, None))
    yield
    ec.reset_cycle()


def _boom(exc):
    def _open(*_a, **_k):
        raise exc
    return _open


def _answer(payload_sink, response="hello"):
    class _R:
        def __enter__(self_):
            return self_
        def __exit__(self_, *a):
            return False
        def read(self_):
            return json.dumps({"response": response}).encode("utf-8")

    def _open(req, timeout=None):
        payload_sink.append(json.loads(req.data.decode("utf-8")))
        payload_sink.append({"_timeout": timeout})
        return _R()
    return _open


# ── (c) the call carries all three, and keep_alive is the load-bearing one ──

def test_the_call_passes_num_predict_keep_alive_and_a_timeout():
    sink = []
    r = ec.guarded_extra_call("reaction", "hi", opener=_answer(sink),
                              sleep=lambda *_: None)
    assert r["outcome"] == ec.COMPLETED, r
    body = sink[0]
    assert body["keep_alive"] == 0, (
        "keep_alive is missing or non-zero — a timed-out call would leave the "
        "model resident and the GPU busy for the next regular step")
    assert body["options"]["num_predict"] == 128
    assert sink[1]["_timeout"] == 15.0


def test_a_caller_cannot_override_the_guards():
    """extra_body exists for logprobs, not for widening the door."""
    for field in ("keep_alive", "stream", "model", "prompt"):
        sink = []
        r = ec.guarded_extra_call("x", "hi", extra_body={field: "anything"},
                                  opener=_answer(sink), sleep=lambda *_: None)
        assert r["outcome"] == ec.FAILED, (
            f"a caller overrode {field!r} and the call still went out")
        assert field in r["why"]


def test_extra_body_may_add_but_not_replace_num_predict():
    sink = []
    ec.guarded_extra_call("perplexity", "hi",
                          extra_body={"logprobs": True,
                                      "options": {"temperature": 0,
                                                  "num_predict": 99999}},
                          opener=_answer(sink), sleep=lambda *_: None)
    body = sink[0]
    assert body["logprobs"] is True, "extra_body could not add a field"
    assert body["options"]["temperature"] == 0
    assert body["options"]["num_predict"] == 128, (
        "a caller raised num_predict past the guard")


# ── (d) the breaker ─────────────────────────────────────────────────────────

def test_two_consecutive_failures_open_the_breaker():
    a = ec.guarded_extra_call("x", "hi", opener=_boom(OSError("down")),
                              sleep=lambda *_: None)
    b = ec.guarded_extra_call("x", "hi", opener=_boom(OSError("down")),
                              sleep=lambda *_: None)
    c = ec.guarded_extra_call("x", "hi", opener=_boom(OSError("down")),
                              sleep=lambda *_: None)
    assert a["outcome"] == ec.FAILED
    assert b.get("breaker_opened") is True
    assert c["outcome"] == ec.BREAKER_OFF
    assert "REST OF" in b["why"] or "rest of this cycle" in c["why"].lower()


def test_a_success_between_two_failures_resets_the_count():
    """CONSECUTIVE, not cumulative. A flaky night is not a broken one."""
    ec.guarded_extra_call("x", "hi", opener=_boom(OSError("down")),
                          sleep=lambda *_: None)
    ec.guarded_extra_call("x", "hi", opener=_answer([]), sleep=lambda *_: None)
    b = ec.guarded_extra_call("x", "hi", opener=_boom(OSError("down")),
                              sleep=lambda *_: None)
    assert b.get("breaker_opened") is not True
    assert ec.breaker_state()["open"] is False


def test_the_breaker_lives_in_the_process_and_never_on_disk():
    """A breaker that persists is a switch, and the switches are Emil's."""
    ec.guarded_extra_call("x", "hi", opener=_boom(OSError("d")), sleep=lambda *_: None)
    ec.guarded_extra_call("x", "hi", opener=_boom(OSError("d")), sleep=lambda *_: None)
    assert ec.breaker_state()["open"] is True

    strays = [p.name for p in (REPO / "memory").glob("*breaker*")]
    assert not strays, f"the breaker wrote itself to disk: {strays}"

    ec.reset_cycle()
    assert ec.breaker_state()["open"] is False, (
        "the next cycle does not start fresh")


def test_a_timeout_is_recorded_as_timeout_not_a_generic_failure():
    r = ec.guarded_extra_call("x", "hi", opener=_boom(TimeoutError("timed out")),
                              sleep=lambda *_: None)
    assert r["outcome"] == ec.TIMEOUT


# ── (a) resources: declining is not failing ─────────────────────────────────

def test_low_ram_skips_without_calling_and_without_counting_as_a_failure(monkeypatch):
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 100.0)
    called = []
    r = ec.guarded_extra_call("x", "hi", opener=lambda *a, **k: called.append(1),
                              sleep=lambda *_: None)
    assert r["outcome"] == ec.SKIPPED_RESOURCES
    assert not called, "a call went out below the RAM floor"
    assert ec.breaker_state()["consecutive_failures"] == 0, (
        "declining for lack of room counted against the breaker — a busy "
        "machine would disable extra calls it never actually attempted")


def test_low_vram_skips(monkeypatch):
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 4000.0)
    monkeypatch.setattr(ec, "_vram_free_mb", lambda: (100.0, None))
    r = ec.guarded_extra_call("x", "hi", opener=_answer([]), sleep=lambda *_: None)
    assert r["outcome"] == ec.SKIPPED_RESOURCES
    assert "VRAM" in r["why"]


def test_unreadable_vram_falls_back_to_ram_and_says_so(monkeypatch):
    monkeypatch.setattr(ec, "_ram_free_mb", lambda: 4000.0)
    monkeypatch.setattr(ec, "_vram_free_mb",
                        lambda: (None, "nvidia-smi is not on PATH"))
    sink = []
    r = ec.guarded_extra_call("x", "hi", opener=_answer(sink), sleep=lambda *_: None)
    assert r["outcome"] == ec.COMPLETED, "a readable-RAM machine was blocked"
    assert r["vram_check"] == "unavailable", (
        "an unreadable GPU was recorded as if it had been checked and passed")


# ── (b) busy waits, but never for ever ──────────────────────────────────────

def test_a_busy_model_is_waited_for_at_most_five_seconds(monkeypatch):
    monkeypatch.setattr(ec, "_models_running", lambda *a, **k: (1, None))
    slept = []
    r = ec.guarded_extra_call("x", "hi", opener=_answer([]),
                              sleep=lambda s: slept.append(s))
    assert r["outcome"] == ec.SKIPPED_BUSY
    assert sum(slept) <= ec.BUSY_WAIT_MAX_SEC + 0.01, (
        f"waited {sum(slept)}s — an unbounded wait at a phase boundary is a "
        f"deadlock with extra steps")


def test_ollama_not_answering_is_not_treated_as_busy(monkeypatch):
    """It will fail on its own, and FAILED is the honest outcome."""
    monkeypatch.setattr(ec, "_models_running",
                        lambda *a, **k: (None, "ConnectionRefused"))
    r = ec.guarded_extra_call("x", "hi", opener=_boom(OSError("refused")),
                              sleep=lambda *_: None)
    assert r["outcome"] == ec.FAILED
    assert r["queue_wait_ms"] == 0


# ── nothing builds an Ollama request for these purposes outside the door ────

def test_nothing_outside_extra_calls_builds_an_ollama_request_for_these():
    """ast: reaction and perplexity must not hand-roll a request any more."""
    offenders = []
    for rel in ("core/reaction.py", "core/perplexity.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8-sig"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                name = (f.attr if isinstance(f, ast.Attribute)
                        else getattr(f, "id", None))
                if name == "urlopen":
                    offenders.append(f"{rel}:{n.lineno} urlopen")
                if name == "Request":
                    offenders.append(f"{rel}:{n.lineno} Request")
    assert not offenders, (
        "these still build their own Ollama request, so they bypass the four "
        f"guards: {offenders}")


def test_both_callers_go_through_the_door():
    for rel in ("core/reaction.py", "core/perplexity.py"):
        src = (REPO / rel).read_text(encoding="utf-8-sig")
        assert "guarded_extra_call" in src, f"{rel} does not use the door"


def test_nothing_anywhere_writes_the_switch_file():
    """config/reactions.json is human-written. No code may flip it."""
    offenders = []
    for p in sorted(REPO.rglob("*.py")):
        if any(x in p.parts for x in ("venv", "venv312_metta", ".git",
                                      "__pycache__", "patches")):
            continue
        try:
            src = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if "reactions.json" not in src:
            continue
        tree = ast.parse(src)
        for n in ast.walk(tree):
            # a write is open(..., 'w'), write_text, or json.dump to that path
            if isinstance(n, ast.Call):
                f = n.func
                name = (f.attr if isinstance(f, ast.Attribute)
                        else getattr(f, "id", None))
                if name in ("write_text", "dump", "writelines"):
                    seg = src[max(0, n.lineno - 6) * 0:]
                    line_ctx = "\n".join(src.splitlines()[max(0, n.lineno - 4):n.lineno])
                    if "reactions.json" in line_ctx or "CONFIG" in line_ctx:
                        offenders.append(f"{p.relative_to(REPO)}:{n.lineno} {name}")
    assert not offenders, (
        "code writes config/reactions.json; that file is human-written and no "
        f"code or action may flip it: {offenders}")


def test_the_switch_file_is_still_protected_and_still_off():
    from safety.protected_paths import is_protected
    assert is_protected("config/reactions.json") is True
    d = json.loads((REPO / "config" / "reactions.json").read_text(encoding="utf-8"))
    assert d["reaction"]["enabled"] is False
    assert d["perplexity"]["enabled"] is False
