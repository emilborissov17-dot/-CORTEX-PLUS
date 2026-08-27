#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/extra_calls.py — ONE GUARDED DOOR, AND THE GPU IS CLEAN WHEN IT CLOSES.

Reaction and perplexity each make a model call at EVERY phase boundary — about
63 a night, each. That is the shape that produced AllBackendsFailedError, and it
is why both switches in config/reactions.json are still false.

Four guards, from Kimi round 24, and no others. Adding a fifth here without a
decision behind it is how a guard becomes a ritual.

  (a) RESOURCES. RAM free < 600 MB, or GPU VRAM free < 400 MB -> SKIPPED_RESOURCES.
      Not a failure: the cycle was right to decline. Where VRAM cannot be read at
      all — no NVIDIA GPU, no driver, nvidia-smi absent — RAM alone decides and
      the record says vram_check="unavailable" rather than pretending it passed.

  (b) BUSY. Poll Ollama /api/ps; if a model is mid-generation, wait AT MOST 5
      seconds, then SKIPPED_BUSY. Never longer. An unbounded wait inside a phase
      boundary is a deadlock with extra steps.

  (c) THE CALL. num_predict=128, keep_alive=0, HTTP timeout 15s. BOTH OPTIONS
      ARE MANDATORY AND keep_alive IS THE LOAD-BEARING ONE: Ollama does not
      cancel inference when the HTTP request times out. Without keep_alive=0 the
      model stays resident and the GPU stays busy into the next regular step —
      the timeout protects the caller and hands the cost to whatever runs next.
      0.3 found neither reaction.py nor perplexity.py passed keep_alive at all.

  (d) BREAKER. Two consecutive FAILED/TIMEOUT outcomes disable extra calls FOR
      THE REMAINDER OF THIS CYCLE ONLY. The state lives in this process and
      never on disk: a breaker that persists is a switch, and the switches are
      Emil's, in a file no code may write.

    venv/Scripts/python.exe core/extra_calls.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_PS = "http://localhost:11434/api/ps"

# (a) the floors
MIN_RAM_FREE_MB = 600.0
MIN_VRAM_FREE_MB = 400.0
# (b) the ceiling on waiting
BUSY_WAIT_MAX_SEC = 5.0
BUSY_POLL_SEC = 0.5
# (c) the call
NUM_PREDICT = 128
KEEP_ALIVE = 0
HTTP_TIMEOUT_SEC = 15.0
# (d) the breaker
BREAKER_AFTER = 2

COMPLETED = "COMPLETED"
TIMEOUT = "TIMEOUT"
FAILED = "FAILED"
SKIPPED_RESOURCES = "SKIPPED_RESOURCES"
SKIPPED_BUSY = "SKIPPED_BUSY"
BREAKER_OFF = "BREAKER_OFF"

# IN THIS PROCESS ONLY. Reset by reset_cycle() at boot; never written to disk.
_consecutive_failures = 0
_breaker_open = False


def reset_cycle() -> dict:
    """Forget the breaker. Called once per cycle, from the runner's boot step."""
    global _consecutive_failures, _breaker_open
    was = {"consecutive_failures": _consecutive_failures,
           "breaker_open": _breaker_open}
    _consecutive_failures, _breaker_open = 0, False
    return was


def breaker_state() -> dict:
    return {"open": _breaker_open, "consecutive_failures": _consecutive_failures}


# ── (a) resources ───────────────────────────────────────────────────────────

def _ram_free_mb() -> Optional[float]:
    try:
        from core.homeostasis import read_ram_free_mb
        return float(read_ram_free_mb())
    except Exception:
        return None


def _vram_free_mb() -> tuple:
    """(free_mb, note). free_mb is None when the GPU cannot be read at all."""
    try:
        from core.body_sensorium import _gpu
        reading, why = _gpu()
    except Exception as exc:                              # noqa: BLE001
        return None, "vram unreadable ({})".format(type(exc).__name__)
    if reading is None:
        return None, why or "vram unreadable"
    used, total = reading
    return float(total - used), None


def check_resources() -> dict:
    """Whether there is room to make a call at all. Never raises."""
    ram = _ram_free_mb()
    vram, vram_note = _vram_free_mb()

    if ram is not None and ram < MIN_RAM_FREE_MB:
        return {"ok": False, "ram_free_mb": ram, "vram_free_mb": vram,
                "vram_check": "unavailable" if vram is None else "read",
                "why": "RAM free {:.0f}MB is under the {:.0f}MB floor"
                       .format(ram, MIN_RAM_FREE_MB)}
    if vram is not None and vram < MIN_VRAM_FREE_MB:
        return {"ok": False, "ram_free_mb": ram, "vram_free_mb": vram,
                "vram_check": "read",
                "why": "GPU VRAM free {:.0f}MB is under the {:.0f}MB floor"
                       .format(vram, MIN_VRAM_FREE_MB)}
    return {"ok": True, "ram_free_mb": ram, "vram_free_mb": vram,
            # NOT a silent pass: a machine with no readable GPU says so, so a
            # reader of the log can tell "VRAM was fine" from "VRAM was never
            # checked".
            "vram_check": "unavailable" if vram is None else "read",
            "why": vram_note or ""}


# ── (b) busy ────────────────────────────────────────────────────────────────

def _models_running(url: str = OLLAMA_PS, timeout: float = 3.0) -> tuple:
    """(count, why). count is None when Ollama could not be asked."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        return len(d.get("models") or []), None
    except Exception as exc:                              # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, exc)


def wait_until_free(max_wait: float = BUSY_WAIT_MAX_SEC, ps_url: str = OLLAMA_PS,
                    sleep=time.sleep) -> dict:
    """Wait for a resident model to finish, but never past the ceiling.

    An unbounded wait at a phase boundary is a deadlock with extra steps: the
    cycle would stall behind an extra call that is, by definition, optional.
    """
    waited = 0.0
    running, why = _models_running(ps_url)
    if running is None:
        # Ollama is not answering. That is not "busy" — the CALL will fail on
        # its own and be recorded as FAILED, which is the honest outcome.
        return {"free": True, "waited_ms": 0, "why": "could not poll /api/ps ({})"
                .format(why), "running": None}
    while running and waited < max_wait:
        sleep(BUSY_POLL_SEC)
        waited += BUSY_POLL_SEC
        running, _ = _models_running(ps_url)
        if running is None:
            break
    return {"free": not running, "waited_ms": int(waited * 1000),
            "why": ("" if not running else
                    "a model was still generating after {:.0f}s".format(max_wait)),
            "running": running}


# ── (c) + (d) the one door ──────────────────────────────────────────────────

def guarded_extra_call(kind: str, prompt: str, model: str = "qwen2.5:3b",
                       url: str = OLLAMA_GENERATE, ps_url: str = OLLAMA_PS,
                       num_predict: int = NUM_PREDICT,
                       timeout: float = HTTP_TIMEOUT_SEC,
                       extra_body: Optional[dict] = None,
                       sleep=time.sleep, opener=None) -> dict:
    """The only way an extra model call is made. Never raises.

    Returns a record: outcome is one of COMPLETED, TIMEOUT, FAILED,
    SKIPPED_RESOURCES, SKIPPED_BUSY, BREAKER_OFF.
    """
    global _consecutive_failures, _breaker_open

    t0 = time.monotonic()
    rec = {"extra_kind": kind, "model": model, "outcome": None, "text": None,
           "extra_time_ms": 0, "queue_wait_ms": 0, "why": "",
           "num_predict": num_predict, "keep_alive": KEEP_ALIVE,
           "http_timeout_sec": timeout}

    if _breaker_open:
        rec.update(outcome=BREAKER_OFF,
                   why="two consecutive failures already disabled extra calls "
                       "for the rest of this cycle")
        return rec

    res = check_resources()
    rec["ram_free_mb"] = res.get("ram_free_mb")
    rec["vram_free_mb"] = res.get("vram_free_mb")
    rec["vram_check"] = res.get("vram_check")
    if not res["ok"]:
        # NOT A FAILURE. Declining for lack of room is the guard working, and
        # counting it against the breaker would disable extra calls on a busy
        # machine that was never actually asked anything.
        rec.update(outcome=SKIPPED_RESOURCES, why=res["why"])
        return rec

    busy = wait_until_free(ps_url=ps_url, sleep=sleep)
    rec["queue_wait_ms"] = busy["waited_ms"]
    if not busy["free"]:
        rec.update(outcome=SKIPPED_BUSY, why=busy["why"])
        return rec

    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # BOTH MANDATORY. keep_alive=0 is the one that matters: Ollama does not
        # cancel inference when the HTTP request times out, so without it a
        # timed-out extra call leaves the model resident and the GPU busy for
        # whatever regular step runs next.
        "keep_alive": KEEP_ALIVE,
        "options": {"num_predict": num_predict},
    }
    # extra_body exists so perplexity can ask for logprobs WITHOUT a second
    # door. It may add fields; it may NOT override the three guards, because a
    # caller that can raise its own keep_alive is a caller outside the guard.
    for k, v in (extra_body or {}).items():
        if k in ("keep_alive", "stream", "model", "prompt"):
            rec.update(outcome=FAILED,
                       why="a caller tried to override {!r}, which is one of "
                           "the guards".format(k))
            return rec
        if k == "options" and isinstance(v, dict):
            merged = dict(body["options"])
            merged.update({ok_: ov for ok_, ov in v.items()
                           if ok_ != "num_predict"})
            body["options"] = merged
        else:
            body[k] = v
    payload = json.dumps(body).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"})
        _open = opener or urllib.request.urlopen
        with _open(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        rec.update(outcome=COMPLETED, text=d.get("response"), raw=d)
        _consecutive_failures = 0
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
        rec.update(outcome=TIMEOUT if is_timeout else FAILED,
                   why="{}: {}".format(type(exc).__name__, exc))
        _consecutive_failures += 1
    except Exception as exc:                              # noqa: BLE001
        rec.update(outcome=FAILED, why="{}: {}".format(type(exc).__name__, exc))
        _consecutive_failures += 1

    if _consecutive_failures >= BREAKER_AFTER:
        _breaker_open = True
        rec["breaker_opened"] = True
        rec["why"] = (rec["why"] + " ; " if rec["why"] else "") + (
            "{} consecutive failures — extra calls are off for the REST OF "
            "THIS CYCLE. The next cycle starts fresh.".format(_consecutive_failures))

    rec["extra_time_ms"] = int((time.monotonic() - t0) * 1000)
    return rec


def _selftest() -> int:
    print("core/extra_calls.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    reset_cycle()
    check("the breaker starts closed", breaker_state()["open"] is False)

    r = check_resources()
    print("    RAM free {} MB | VRAM {} ({})".format(
        None if r["ram_free_mb"] is None else round(r["ram_free_mb"]),
        r["vram_free_mb"], r["vram_check"]))
    check("resources answer without raising", "ok" in r)

    n, why = _models_running()
    print("    /api/ps -> {} model(s) resident{}".format(
        n, "" if why is None else " ({})".format(why)))

    # a call that always fails, to exercise the breaker without a live Ollama
    def boom(*_a, **_k):
        raise OSError("no ollama here")

    reset_cycle()
    a = guarded_extra_call("selftest", "hi", opener=boom, sleep=lambda *_: None)
    b = guarded_extra_call("selftest", "hi", opener=boom, sleep=lambda *_: None)
    c = guarded_extra_call("selftest", "hi", opener=boom, sleep=lambda *_: None)
    check("a failure is recorded as FAILED", a["outcome"] in (FAILED, TIMEOUT,
                                                              SKIPPED_RESOURCES))
    if a["outcome"] not in (SKIPPED_RESOURCES,):
        check("two failures open the breaker", b.get("breaker_opened") is True)
        check("the third is refused by the breaker", c["outcome"] == BREAKER_OFF)
        check("the breaker is in memory only",
              not (BASE / "memory" / "extra_calls_breaker.json").exists())
    reset_cycle()
    check("reset_cycle closes it again", breaker_state()["open"] is False)

    print("  RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
