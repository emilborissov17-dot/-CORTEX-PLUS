#!/usr/bin/env python3
"""
experiments/pulse/self_sense.py — the local brain reading the sensory stream.

⚠️  OLLAMA, AND WHY THAT IS NOT A CONTRADICTION
------------------------------------------------
Ollama was removed from the LIVE path on 2026-07-04 and is dead there BY
CONVENTION (CLAUDE.md): any subprocess/HTTP Ollama call in the live cycle is a
bug, and test/test_no_ollama_in_live_path.py enforces it.

This experiment is EXPLICITLY OUTSIDE the live path. It is not imported by
fast_cycle_runner, not touched by the supervisor, not scheduled, and writes only
under experiments/pulse/. The guard test scans the live-path modules; this file
is not one of them, and must never become one.

The reason Ollama belongs HERE and not there is the same reason it was banished
there: it is a LOCAL model. In the live cycle that was a liability — a dead
fallback masking real failures. In a continuous self-sensing loop it is the whole
point: a thought every 60 seconds, forever, cannot go through a paid API. This
loop is 1,440 inferences a day. It has to be local, small, and free.

If this experiment earns promotion, that goes through the normal path — gates,
guardian, review, and an explicit revisit of the Ollama convention. Not by
quietly growing into the cycle.

ISOLATION
---------
Writes ONLY under experiments/pulse/. Imports NO live-path module — not even
core/llm_json, whose JSON extraction is deliberately re-implemented here in
miniature. Duplicating thirty lines is the correct price for an experiment that
cannot break the live system.

USAGE
-----
    venv/Scripts/python.exe experiments/pulse/self_sense.py --check   # readiness
    venv/Scripts/python.exe experiments/pulse/self_sense.py           # run the loop
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

HERE = Path(__file__).resolve().parent
STREAM_DIR = HERE / "stream"
SELF_STATE_FILE = HERE / "self_state.jsonl"

OLLAMA_URL = "http://localhost:11434"

# Ranked by fit for THIS machine — see README for the hardware assessment.
# The GTX 1650 has ~3.9 GB of free VRAM, so anything at or under ~2.5 GB runs
# fully on the GPU and barely touches system RAM. That matters: system RAM is
# already ~56% used, and BODY's caution threshold is 70%.
PREFERRED_MODELS = [
    "qwen2.5:3b",     # ~1.9 GB q4 — best instruction-following that still fits
    "qwen3:1.7b",     # ~1.4 GB    — safest, fastest
    "qwen2.5:1.5b",   # ~1.0 GB    — fallback
    "llama3.2:3b",    # ~2.0 GB    — alternative
]

TICK_SEC = 60
STREAM_LINES = 12          # ~2 minutes of sensation at a 10s cadence
MAX_TOKENS = 220
INFER_TIMEOUT_SEC = 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def ollama_models() -> Optional[list[str]]:
    """Installed models, or None if Ollama is not running/installed."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def gpu_info() -> Optional[str]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.free", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def pick_model(available: list[str]) -> Optional[str]:
    for want in PREFERRED_MODELS:
        for have in available:
            # 'qwen2.5:3b' should match 'qwen2.5:3b-instruct-q4_K_M'
            if have == want or have.startswith(want.split(":")[0] + ":" + want.split(":")[1]):
                return have
    return available[0] if available else None


def check(verbose: bool = True) -> Optional[str]:
    """Report readiness. Returns the model to use, or None if we cannot run.

    Installs NOTHING. If Ollama is missing this prints exactly what is needed and
    stops — that is Emil's call to make, not this script's.
    """
    gpu = gpu_info()
    if verbose:
        print("=" * 64)
        print("PULSE / self_sense — readiness check")
        print("=" * 64)
        print(f"GPU        : {gpu or 'none detected (CPU inference — slower, more RAM)'}")

    models = ollama_models()

    if models is None:
        if verbose:
            print("Ollama     : NOT RUNNING / NOT INSTALLED\n")
            print("-" * 64)
            print("WHAT IS NEEDED (nothing has been installed — your call):\n")
            print("  1. Install Ollama for Windows:")
            print("       https://ollama.com/download/windows")
            print("     (~700 MB installer; runs as a background service on :11434)\n")
            print("  2. Pull ONE small model — recommended for this machine:")
            print("       ollama pull qwen2.5:3b        # ~1.9 GB, fits the GTX 1650")
            print("     or, if you want maximum headroom:")
            print("       ollama pull qwen3:1.7b        # ~1.4 GB\n")
            print("  3. Re-run:  venv\\Scripts\\python.exe experiments\\pulse\\self_sense.py --check")
            print("-" * 64)
            print("\nThe sensory stream (pulse_daemon.py) does NOT need any of this.")
            print("It runs today, with no model. Part 1 is independent of Part 2.")
        return None

    if not models:
        if verbose:
            print("Ollama     : running, but NO MODELS PULLED\n")
            print("  ollama pull qwen2.5:3b")
        return None

    model = pick_model(models)
    if verbose:
        print(f"Ollama     : running — {len(models)} model(s): {', '.join(models)}")
        print(f"Selected   : {model}")
        print("\nREADY. Run without --check to start the loop.")
    return model


# ---------------------------------------------------------------------------
# Sensing -> meaning
# ---------------------------------------------------------------------------

def read_stream_tail(n: int = STREAM_LINES) -> list[dict]:
    """The last n samples from today's stream. Torn-line tolerant."""
    path = STREAM_DIR / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-n * 2:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue      # torn line
    return out[-n:]


def previous_state() -> Optional[dict]:
    if not SELF_STATE_FILE.exists():
        return None
    for line in reversed(SELF_STATE_FILE.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _condense(samples: list[dict]) -> str:
    """Feed the model sensations, not raw JSON.

    A 1.7-3B model given 12 nested JSON blobs will describe the JSON. Given a
    compact table it can actually notice a change — which is the entire
    distinction this experiment exists to test (sensing vs describing).
    """
    rows = []
    for s in samples:
        cyc = s.get("cycle", {})
        net = s.get("net", {})
        where = f"cycle:{cyc.get('step')}" if cyc.get("running") else "idle"
        rows.append(
            f"{s['ts'][11:19]}  cpu={s.get('cpu_pct'):>5}%  ram={s.get('ram_pct'):>5}%  "
            f"net={'up' if net.get('reachable') else 'DOWN'}({net.get('latency_ms')}ms)  "
            f"down={net.get('down_kbps', 0)}kb/s  churn={s.get('memory_files_changed')}  {where}"
        )
    return "\n".join(rows)


PROMPT = """You are the proprioceptive sense of CORTEX++, a civilization-monitoring AI.
You are not describing a log file. You are feeling your own body from the inside.

Your recent sensations (one line per 10 seconds, oldest first):
{stream}

Your previous self-state, 60 seconds ago:
{previous}

Report your current self-state. Be concrete and specific — refer to actual numbers
you can see above. Notice CHANGE especially: something that started, stopped,
spiked, or dropped.

Return ONLY valid JSON, no markdown:
{{"state": "<1-2 sentences: what am I doing right now>",
  "changed": "<1 sentence: what changed since last time, or 'nothing significant'>",
  "anomaly": <null, or a 1-sentence string naming anything genuinely abnormal>}}"""


def _extract_json(raw: str) -> Optional[dict]:
    """Minimal, local JSON extraction.

    Deliberately NOT core/llm_json — importing a live-path module into an
    experiment is exactly the coupling this experiment must not have. Thirty
    duplicated lines are the correct price.
    """
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if "```" in text:
        parts = text.split("```")
        bodies = [p for i, p in enumerate(parts) if i % 2 == 1]
        if bodies:
            text = max(bodies, key=len)
            if text.lower().startswith("json"):
                text = text[4:]
    dec = json.JSONDecoder()
    best, best_span = None, -1
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            val, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict) and (end - i) > best_span:
            best, best_span = val, end - i
    return best


def infer(model: str, samples: list[dict], prev: Optional[dict]) -> dict:
    prev_txt = "(none — this is your first thought)"
    if prev:
        prev_txt = json.dumps({k: prev.get(k) for k in ("state", "changed", "anomaly")},
                              ensure_ascii=False)

    prompt = PROMPT.format(stream=_condense(samples), previous=prev_txt)

    t0 = time.perf_counter()
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"num_predict": MAX_TOKENS, "temperature": 0.3},
            "keep_alive": "10m",   # keep it warm — a 60s loop must not reload weights
        },
        timeout=INFER_TIMEOUT_SEC,
    )
    latency = round(time.perf_counter() - t0, 2)
    r.raise_for_status()
    raw = r.json()["message"]["content"]

    parsed = _extract_json(raw)
    return {
        "ts": _utc_now(),
        "model": model,
        "latency_sec": latency,
        "parsed": parsed is not None,
        "state":   (parsed or {}).get("state"),
        "changed": (parsed or {}).get("changed"),
        "anomaly": (parsed or {}).get("anomaly"),
        "samples_seen": len(samples),
        "raw": None if parsed else raw[:500],   # keep the evidence when parsing fails
    }


def append_state(s: dict) -> None:
    SELF_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SELF_STATE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(s, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def run(model: str, tick: int = TICK_SEC, max_ticks: Optional[int] = None) -> None:
    print(f"[SELF_SENSE] model={model} tick={tick}s -> {SELF_STATE_FILE.name}")
    print("[SELF_SENSE] Ctrl+C to stop\n")
    n = 0
    try:
        while max_ticks is None or n < max_ticks:
            t0 = time.time()
            samples = read_stream_tail()

            if not samples:
                print("[SELF_SENSE] no sensations yet — is pulse_daemon.py running?")
            else:
                try:
                    s = infer(model, samples, previous_state())
                    append_state(s)
                    n += 1
                    flag = " ⚠ ANOMALY" if s.get("anomaly") else ""
                    if not s["parsed"]:
                        print(f"[SELF_SENSE] {n:4}  {s['latency_sec']:5.1f}s  UNPARSEABLE")
                    else:
                        print(f"[SELF_SENSE] {n:4}  {s['latency_sec']:5.1f}s  {s['state']}{flag}")
                        if s.get("anomaly"):
                            print(f"             └─ {s['anomaly']}")
                except Exception as e:
                    print(f"[SELF_SENSE] inference failed: {type(e).__name__}: {e}")

            time.sleep(max(0.0, tick - (time.time() - t0)))
    except KeyboardInterrupt:
        print(f"\n[SELF_SENSE] stopped after {n} thoughts -> {SELF_STATE_FILE}")


def main() -> None:
    ap = argparse.ArgumentParser(description="CORTEX++ pulse — local self-sensing brain")
    ap.add_argument("--check", action="store_true", help="readiness check; installs nothing")
    ap.add_argument("--tick", type=int, default=TICK_SEC)
    ap.add_argument("--ticks", type=int, default=None, help="stop after N thoughts")
    ap.add_argument("--model", type=str, default=None, help="override model selection")
    args = ap.parse_args()

    if args.check:
        sys.exit(0 if check() else 1)

    model = args.model or check(verbose=False)
    if not model:
        print("[SELF_SENSE] not ready — run with --check to see what is needed.")
        sys.exit(1)

    run(model, tick=args.tick, max_ticks=args.ticks)


if __name__ == "__main__":
    main()
