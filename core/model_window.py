#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/model_window.py — THE TWO LOCAL MODELS DO NOT SHARE THIS GPU. THEY TAKE TURNS.

WHAT WAS MEASURED (22 August 2026, this machine, /api/ps around four calls)
---------------------------------------------------------------------------
    resident before        qwen3:8b     5.75GB total, 3.57GB VRAM (62.1% GPU)
    -> call qwen2.5:3b     qwen2.5:3b   2.31GB total, 2.31GB VRAM (100.0% GPU)   10.2s
    -> call qwen3:8b       qwen3:8b     5.75GB total, 3.32GB VRAM ( 57.8% GPU)   13.8s
    -> call qwen2.5:3b     qwen2.5:3b   2.31GB total, 2.31GB VRAM (100.0% GPU)    7.2s
    -> call qwen3:8b       qwen3:8b     5.75GB total, 3.32GB VRAM ( 57.8% GPU)   13.5s

Two facts, and neither is a guess:

  1. /api/ps NEVER shows two models. On 4GB of VRAM the pair cannot coexist, so
     every call to one FULLY EVICTS the other. There is no partial sharing to tune.
  2. 8b never fits even alone — 3.32GB of 5.75GB resident, the remaining 42% run
     from system RAM on the CPU. 3b fits whole, every time, at 100% GPU.

So the cost of mixing them is a full reload per alternation (7-14s measured warm,
minutes cold), paid out of the ceiling of whichever step happens to be running.
That is what took `internet_intelligence` past 3600s and killed the cycle.

THE RULE
---------
8b is legal only inside ONE contiguous window per cycle. Outside it, a caller that
asks for the big model is SERVED THE SMALL ONE — quietly in capability, loudly in
the record: every downgrade is counted and named, because a silent downgrade is the
same lie as a silent DEGRADED.

    inside the window    8b may load. 3b is not called, so it cannot evict it.
    outside the window   3b only, held with keep_alive=-1 (never expires, so no
                         reload is paid between steps).
    on close             8b is released and 3b is EXPLICITLY reloaded, so the first
                         step after the window does not pay a cold start.

WHY A WINDOW AND NOT A PER-STEP CHOICE
---------------------------------------
Per-step choice is what the cycle does today, and it is why the models alternate
many times a night. A window is the only shape that makes the reload count bounded:
two transitions per cycle, not one per step that disagrees with its neighbour.

WHERE THE WINDOW SITS, AND WHY THAT IS ARGUABLE
------------------------------------------------
config/model_window.json, human-tunable like the other ceilings. The default is the
REASONING TAIL — `brain_reconsider` (step 34) through `cycle_report` (step 54) — on
the argument that the front half of the cycle ACQUIRES data (cloud + 3b are enough)
and the tail REASONS ABOUT IT, which is the work the bigger model is actually for.
`daily_analysis`, one of the two steps the ledger blames for kills, is inside it.
`internet_intelligence`, the other, is deliberately OUTSIDE: it is a fetch step, and
it will get 3b. If that turns out to be the wrong call, this is the file to argue
with — the boundary is data, not architecture.

    venv\\Scripts\\python.exe core/model_window.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time
import urllib.request
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "model_window.json"
STATE = BASE / "memory" / "model_window.json"

OLLAMA_URL = os.environ.get("CORTEX_OLLAMA_URL", "http://localhost:11434")

# keep_alive values. -1 means "never expire" to Ollama; it is the whole point of
# the outside-the-window regime — a model that expires is a model that reloads.
FOREVER = -1
BIG_KEEP_ALIVE = "30m"

SMALL_DEFAULT = "qwen2.5:3b"
BIG_DEFAULT = "qwen3:8b"

_lock = threading.Lock()
_open = False
_open_reason = ""
_downgrades: list = []
_transitions: list = []
_cursor = -1                     # how far through cycle_map.STEPS the walk has got


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def config() -> dict:
    """The window definition. Missing file = a CLOSED window, not an open one.

    Fail-safe direction matters here. If this config is deleted, the safe reading
    is 'no step may load 8b', because that costs capability; the unsafe reading is
    'every step may', which costs the cycle.
    """
    cfg = _load_json(CONFIG)
    return {
        "small": cfg.get("small_model", SMALL_DEFAULT),
        "big": cfg.get("big_model", BIG_DEFAULT),
        "start": cfg.get("window_opens_at_step"),
        "end": cfg.get("window_closes_after_step"),
        "enabled": bool(cfg.get("enabled", True)),
    }


def small_model() -> str:
    return config()["small"]


def big_model() -> str:
    return config()["big"]


# ---------------------------------------------------------------------------
# Ollama residency — observation, then control
# ---------------------------------------------------------------------------

def ps(url: str = OLLAMA_URL, timeout: float = 10.0) -> list:
    """What Ollama currently holds. [] when it holds nothing OR is unreachable —
    the caller cannot tell those apart from here, and neither case should raise.
    """
    try:
        with urllib.request.urlopen(url + "/api/ps", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")).get("models") or []
    except Exception:
        return []


def residency(url: str = OLLAMA_URL) -> list:
    """ps() reduced to the four numbers that matter, for logs and the selftest."""
    out = []
    for m in ps(url):
        total = m.get("size") or 0
        vram = m.get("size_vram") or 0
        out.append({
            "model": m.get("name"),
            "total_gb": round(total / 1e9, 2),
            "vram_gb": round(vram / 1e9, 2),
            "gpu_pct": round(100.0 * vram / total, 1) if total else 0.0,
        })
    return out


def _set_keep_alive(model: str, keep_alive, url: str = OLLAMA_URL,
                    timeout: float = 300.0) -> bool:
    """Load (or unload, with keep_alive=0) a model without generating anything.

    An /api/chat with an empty message list is Ollama's documented way to change
    residency alone. Returns True on HTTP 200. Never raises: residency management
    must not be able to kill a cycle.
    """
    body = json.dumps({"model": model, "keep_alive": keep_alive,
                       "messages": []}).encode("utf-8")
    req = urllib.request.Request(url + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
        return True
    except Exception:
        return False


def pin_small(url: str = OLLAMA_URL) -> bool:
    """Hold 3b resident with no expiry. The outside-the-window steady state."""
    return _set_keep_alive(small_model(), FOREVER, url)


def release_big(url: str = OLLAMA_URL) -> bool:
    """Unload 8b immediately (keep_alive=0) rather than waiting out its 30m."""
    return _set_keep_alive(big_model(), 0, url)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def is_open() -> bool:
    with _lock:
        return _open


def open_window(reason: str = "", url: str = OLLAMA_URL,
                touch_ollama: bool = True) -> dict:
    """Enter the 8b window. Idempotent."""
    global _open, _open_reason
    with _lock:
        if _open:
            return {"changed": False, "open": True, "reason": _open_reason}
        _open = True
        _open_reason = reason
    before = residency(url)
    if touch_ollama:
        # 3b is released FIRST. Letting Ollama discover the conflict on its own
        # means the 8b load races an eviction it could have been told about.
        _set_keep_alive(small_model(), 0, url)
    _transitions.append({"event": "open", "reason": reason, "at": time.time(),
                         "residency_before": before})
    _persist()
    return {"changed": True, "open": True, "reason": reason}


def close_window(url: str = OLLAMA_URL, touch_ollama: bool = True) -> dict:
    """Leave the window: release 8b, reload 3b pinned. Idempotent."""
    global _open, _open_reason
    with _lock:
        if not _open:
            return {"changed": False, "open": False}
        _open = False
        _open_reason = ""
    reloaded = False
    if touch_ollama:
        release_big(url)
        reloaded = pin_small(url)
    _transitions.append({"event": "close", "at": time.time(),
                         "small_reloaded": reloaded,
                         "residency_after": residency(url)})
    _persist()
    return {"changed": True, "open": False, "small_reloaded": reloaded}


def resolve_step(step: str) -> str:
    """Runner LABEL -> cycle_map STEP NAME.

    fast_cycle_runner calls _run() with labels (`internet_agent`), while cycle_map
    and this window's config speak step names (`internet_intelligence`).
    core/cycle_map.ALIASES is the existing table between them; core/step_budget.py
    inverts it for the same reason. Without this the window would simply never
    match a label, and would be silently closed all night — the exact shape of
    failure this repo keeps finding, so it gets a name rather than a lookup that
    quietly returns False.
    """
    try:
        from core.cycle_map import ALIASES
        return ALIASES.get(step, step)
    except Exception:
        return step


def step_names() -> list:
    try:
        from core.cycle_map import STEPS
        return [s[0] for s in STEPS]
    except Exception:
        return []


def window_bounds(names: Optional[list] = None):
    """(start_index, end_index) into cycle_map.STEPS, or None when there is no window.

    Both endpoints are resolved by LAST occurrence for the end and FIRST for the
    start, so a window whose endpoint name repeats still spans the widest sensible
    range rather than collapsing.
    """
    cfg = config()
    if not cfg["enabled"] or not cfg["start"]:
        return None
    if names is None:
        names = step_names()
    if not names:
        return None
    try:
        start = names.index(cfg["start"])
    except ValueError:
        return None
    end = len(names) - 1
    if cfg["end"]:
        for i in range(len(names) - 1, -1, -1):
            if names[i] == cfg["end"]:
                end = i
                break
    return (start, end)


def step_is_in_window(step: str, index: Optional[int] = None) -> bool:
    """Is `step` inside the configured window, by POSITION in core.cycle_map.STEPS?

    Position, not a name set, so a step inserted between the endpoints joins the
    window automatically instead of being forgotten.

    WHY `index` EXISTS — found by probing, not by reading. `body_scan` appears TWICE
    in STEPS (index 1, before everything, and index 35, in the tail). A plain
    names.index() returns the FIRST match, so the second body_scan read as "outside",
    the window slammed shut at step 35 and reopened at 36 — a spurious 8b unload and
    reload in the middle of the window, which is the exact churn this module exists
    to remove. When the caller knows WHICH occurrence it is at, it passes the index
    and the ambiguity disappears.
    """
    bounds = window_bounds()
    if bounds is None:
        return False
    start, end = bounds
    if index is None:
        names = step_names()
        try:
            index = names.index(resolve_step(step))
        except ValueError:
            return False
    return start <= index <= end


def reset_cursor() -> None:
    """Start of a cycle: forget where the last walk got to."""
    global _cursor
    with _lock:
        _cursor = -1


def _advance(step: str) -> Optional[int]:
    """Where in the step list this call is, given how far the cycle has already got.

    Scans FORWARD from the last matched position, so a repeated step name resolves
    to the occurrence the cycle is actually at. Never moves backwards: if the name
    is not found ahead, the cursor stays put and the earlier occurrence is reported
    rather than pretending the cycle rewound.
    """
    global _cursor
    names = step_names()
    if not names:
        return None
    want = resolve_step(step)
    with _lock:
        for i in range(_cursor + 1, len(names)):
            if names[i] == want:
                _cursor = i
                return i
    try:
        return names.index(want)
    except ValueError:
        return None


def on_step(step: str, url: str = OLLAMA_URL, touch_ollama: bool = True) -> dict:
    """Called by the runner as each step begins. Opens or closes the window so the
    transition follows the cycle's real position rather than a caller remembering.
    """
    index = _advance(step)
    want = step_is_in_window(step, index=index)
    if want and not is_open():
        return open_window("step {} (index {}) is inside the window".format(step, index),
                           url, touch_ollama)
    if not want and is_open():
        return close_window(url, touch_ollama)
    return {"changed": False, "open": is_open()}


# ---------------------------------------------------------------------------
# What a caller is actually allowed to run
# ---------------------------------------------------------------------------

def local_model(want_big: bool = False, purpose: str = "",
                critical: bool = False) -> str:
    """THE ONE FUNCTION EVERY LOCAL CALLER SHOULD ASK.

    Returns the model id the caller may use right now. Asking for the big model
    outside the window returns the small one and RECORDS the downgrade — the caller
    is not told it got what it asked for.
    """
    cfg = config()
    if not want_big:
        return cfg["small"]
    if is_open():
        return cfg["big"]
    _downgrades.append({"purpose": purpose or "unnamed", "critical": bool(critical),
                        "at": time.time(), "asked": cfg["big"],
                        "served": cfg["small"]})
    _persist()
    return cfg["small"]


def keep_alive_for(model: str):
    """3b outside the window is pinned forever; everything else gets a normal TTL."""
    if model == config()["small"] and not is_open():
        return FOREVER
    return BIG_KEEP_ALIVE


def downgrades() -> list:
    return list(_downgrades)


def transitions() -> list:
    return list(_transitions)


def _persist() -> None:
    """Write the window's record. Never raises — a failed write must not stop a step."""
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "open": _open,
            "reason": _open_reason,
            "config": config(),
            "downgrades": _downgrades[-200:],
            "transitions": _transitions[-50:],
            "updated": time.time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/model_window.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    cfg = config()
    print("  config               {} exists={}".format(CONFIG.name, CONFIG.exists()))
    print("    small={}  big={}".format(cfg["small"], cfg["big"]))
    print("    window {} .. {}  enabled={}".format(cfg["start"], cfg["end"],
                                                   cfg["enabled"]))
    if not CONFIG.exists():
        print("  config               INERT — no window defined, 8b denied everywhere")
        ok = False

    try:
        from core.cycle_map import STEPS
        names = [s[0] for s in STEPS]
        inside = [n for n in names if step_is_in_window(n)]
        print("  cycle_map            LIVE ({} steps, {} inside the window)".format(
            len(names), len(inside)))
        if inside:
            print("    {} .. {}".format(inside[0], inside[-1]))
    except Exception as e:
        print("  cycle_map            INERT ({}: {})".format(type(e).__name__, e))
        ok = False

    try:
        runner = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                           errors="replace")
        wired = "model_window" in runner
    except OSError:
        wired = False
    print("  fast_cycle_runner    {}".format(
        "WIRED" if wired else "NOT WIRED — the models still alternate per step"))
    if not wired:
        ok = False

    try:
        gb = (BASE / "core" / "groq_backend.py").read_text(encoding="utf-8",
                                                           errors="replace")
        gb_wired = "model_window" in gb
    except OSError:
        gb_wired = False
    print("  groq_backend         {}".format(
        "WIRED" if gb_wired
        else "NOT WIRED — the local last resort still picks 8b directly"))
    if not gb_wired:
        ok = False

    live = residency()
    if live:
        print("  ollama /api/ps       LIVE")
        for r in live:
            print("    {:<12} total={:>5.2f}GB vram={:>5.2f}GB ({:>5.1f}% GPU)".format(
                r["model"], r["total_gb"], r["vram_gb"], r["gpu_pct"]))
        if len(live) > 1:
            print("    NOTE: more than one model resident — this box measured "
                  "single-occupancy on 4GB")
    else:
        print("  ollama /api/ps       nothing resident (or Ollama unreachable)")

    # Pure-decision smoke: no network, no residency changes.
    global _open
    was = _open
    _open = False
    m_closed = local_model(want_big=True, purpose="selftest")
    _open = True
    m_open = local_model(want_big=True, purpose="selftest")
    _open = was
    assert m_closed == cfg["small"], m_closed
    assert m_open == cfg["big"], m_open
    print("  downgrade smoke      closed->{}  open->{}  ({} downgrade recorded)".format(
        m_closed, m_open, len([d for d in _downgrades if d["purpose"] == "selftest"])))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(json.dumps({"open": is_open(), "config": config(),
                      "residency": residency()}, ensure_ascii=False, indent=2))
