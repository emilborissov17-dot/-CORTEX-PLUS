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

import psutil
import requests

RAM_CAUTION_PCT = 70.0     # BODY's caution threshold — above this it cuts cycle workers

HERE = Path(__file__).resolve().parent
STREAM_DIR = HERE / "stream"
SELF_STATE_FILE = HERE / "self_state.jsonl"

# HTTP ONLY — never the CLI.
#
# ollama.exe is NOT on PATH on this machine (it lives in
# %LOCALAPPDATA%\Programs\Ollama\), and the server must be started by hand. If we
# shelled out to `ollama`, this script would fail with "command not found" while
# a perfectly healthy server was answering on :11434. The HTTP API is the real
# interface; the CLI is just another client of it. So PATH is irrelevant to us.
OLLAMA_URL = "http://localhost:11434"

# Ranked by fit for THIS machine. See README for the hardware assessment.
#
# NOTE ON SIZE: both installed models EXCEED the GTX 1650's ~3.9 GB of free VRAM
# (qwen2.5:7b = 4.68 GB, qwen3:8b = 5.23 GB), so Ollama will split them between
# GPU and CPU. That is a real cost against criterion C4, and it is measured — not
# assumed — by `--check`, which reports latency and the VRAM/RAM split.
#
# qwen2.5:7b is the DEFAULT: it is a plain instruct model, so a tick is one
# straight answer. qwen3:8b is a REASONING model — it emits <think>...</think>
# before answering, which costs tokens and latency on every tick and must be
# stripped (see _extract_json). Available via --model, but not the default: a
# self-sensing loop wants a fast reflex, not a deliberation.
PREFERRED_MODELS = [
    "qwen2.5:7b",     # 4.68 GB — DEFAULT. Non-reasoning, direct answers.
    "qwen3:8b",       # 5.23 GB — reasoning model; slower per tick, needs <think> stripping
    "qwen2.5:3b",     # ~1.9 GB — would fit VRAM entirely; not installed
    "qwen3:1.7b",     # ~1.4 GB — smallest viable; not installed
]

TICK_SEC = 60
STREAM_LINES = 12          # ~2 minutes of sensation at a 10s cadence
MAX_TOKENS = 220
INFER_TIMEOUT_SEC = 120    # generous: a partially CPU-offloaded 7b is not fast

# Where Ollama lives when it is not on PATH (this machine).
OLLAMA_EXE_HINT = r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def server_up() -> bool:
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
        return True
    except Exception:
        return False


def ollama_models() -> Optional[list[dict]]:
    """Installed models (name + size), or None if the server is not reachable."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2)}
                for m in r.json().get("models", [])]
    except Exception:
        return None


def loaded_split() -> Optional[str]:
    """How the loaded model is split between VRAM and system RAM.

    This is the number that decides criterion C4. Both installed models are larger
    than the free VRAM, so Ollama offloads the remainder to system RAM — and system
    RAM is exactly what BODY's 70% caution threshold protects.
    """
    try:
        r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        if not models:
            return None
        m = models[0]
        total = m.get("size", 0)
        vram = m.get("size_vram", 0)
        ram = max(0, total - vram)
        pct = (vram / total * 100) if total else 0
        return (f"{m['name']}: {total/1e9:.2f} GB total — "
                f"{vram/1e9:.2f} GB VRAM ({pct:.0f}%), {ram/1e9:.2f} GB system RAM")
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


def gpu_free_mb() -> Optional[str]:
    info = gpu_info()
    if not info or "," not in info:
        return None
    return info.split(",")[-1].strip()


def pick_model(available: list[dict]) -> Optional[str]:
    names = [m["name"] for m in available]
    for want in PREFERRED_MODELS:
        for have in names:
            # 'qwen2.5:7b' should also match 'qwen2.5:7b-instruct-q4_K_M'
            if have == want or have.startswith(want + "-"):
                return have
    return names[0] if names else None


def _server_down_help() -> None:
    print("Ollama     : SERVER NOT REACHABLE on :11434\n")
    print("-" * 66)
    print("The server must be started BY HAND on this machine — ollama.exe is")
    print("installed but NOT on PATH.\n")
    print("  Start it (PowerShell):")
    print(f'    Start-Process "$env:LOCALAPPDATA\\Programs\\Ollama\\ollama.exe" '
          f'-ArgumentList "serve"\n')
    print("  Then re-run:")
    print("    venv\\Scripts\\python.exe experiments\\pulse\\self_sense.py --check")
    print("-" * 66)
    print("\nPART 2 REQUIRES THE SERVER RUNNING. If it goes down mid-loop,")
    print("self_sense logs one line and waits — it does not crash.")
    print("\nThe sensory stream (pulse_daemon.py) does NOT need any of this.")
    print("Part 1 is independent of Part 2 and runs with no model at all.")


def test_generation(model: str, verbose: bool = True) -> Optional[float]:
    """One real generation. Returns latency in seconds, or None on failure.

    A readiness check that only pings /api/tags proves the server is up, not that
    it can actually think. A model that is present but cannot load (out of VRAM,
    corrupt blob) would pass that check and then fail on every tick of the real
    loop. So we make it produce a token before declaring READY.
    """
    try:
        t0 = time.perf_counter()
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user",
                              "content": 'Reply with exactly this JSON and nothing else: {"ok": true}'}],
                "stream": False,
                "think": False,
                "options": {"num_predict": 32, "temperature": 0},
                "keep_alive": "10m",
            },
            timeout=INFER_TIMEOUT_SEC,
        )
        latency = time.perf_counter() - t0
        r.raise_for_status()
        content = r.json()["message"]["content"]
        parsed = _extract_json(content)

        if verbose:
            ok = "parsed OK" if parsed else "UNPARSEABLE"
            print(f"Test gen   : {latency:.2f}s — {ok}")
            print(f"             reply: {content.strip()[:80]!r}")
        return latency
    except Exception as e:
        if verbose:
            print(f"Test gen   : FAILED — {type(e).__name__}: {e}")
        return None


def check(verbose: bool = True) -> Optional[str]:
    """Report readiness. Returns the model to use, or None if we cannot run.

    Installs NOTHING and starts NOTHING. If the server is down it prints how to
    start it and stops — that is Emil's call, not this script's.
    """
    if verbose:
        print("=" * 66)
        print("PULSE / self_sense — readiness check")
        print("=" * 66)
        print(f"GPU        : {gpu_info() or 'none detected (CPU inference)'}")

    models = ollama_models()
    if models is None:
        if verbose:
            _server_down_help()
        return None

    if not models:
        if verbose:
            print("Ollama     : running, but NO MODELS PULLED")
        return None

    model = pick_model(models)
    if verbose:
        listed = ", ".join(f"{m['name']} ({m['size_gb']} GB)" for m in models)
        print(f"Ollama     : server UP — {len(models)} model(s): {listed}")
        print(f"Selected   : {model}")
        if model and model.startswith("qwen3"):
            print("             ⚠ reasoning model — emits <think> blocks; stripped, but")
            print("               it costs latency on every tick. qwen2.5:7b is faster.")

    latency = test_generation(model, verbose=verbose)
    if latency is None:
        return None

    if verbose:
        split = loaded_split()
        if split:
            print(f"Split      : {split}")

        ram = psutil.virtual_memory().percent
        print(f"System RAM : {ram:.1f}%  (BODY caution threshold {RAM_CAUTION_PCT:.0f}%)")
        print()

        # ── C2 ──
        if latency > 30:
            print(f"C2  ✗ AT RISK — test gen took {latency:.1f}s against a 30s ceiling,")
            print(f"       and a real tick has a longer prompt than this test.")
        else:
            print(f"C2  ✓ test gen {latency:.1f}s, ceiling 30s (first call is slower: cold load)")

        # ── C4 ──
        # Measured 2026-07-13: qwen2.5:7b costs +3.86 GB system RAM (45.6% -> 71.5%).
        # It does not fit the 3.9 GB VRAM, so ~1.9 GB of weights spill to RAM and the
        # runtime + KV cache take the rest.
        if ram > RAM_CAUTION_PCT:
            print(f"C4  ✗ BREACHED — system RAM is {ram:.1f}%, above BODY's "
                  f"{RAM_CAUTION_PCT:.0f}% caution threshold.")
            print(f"       {model} does not fit entirely in the GPU's 4 GB of VRAM, so it")
            print(f"       spills into system RAM. At >70% BODY cuts the live cycle's")
            print(f"       workers from 3 to 2 — this experiment would be DEGRADING the")
            print(f"       live system, which is exactly what its isolation rules forbid.")
            print()
            print(f"       FIX — pull a model that fits entirely in VRAM:")
            print(f"           ollama pull qwen2.5:3b     # ~1.9 GB, fits; ~1-2s per tick")
            print(f"       Then self_sense will select it automatically.")
            print()
            print(f"       Or run the loop only while NO cycle is running (the daily cycle")
            print(f"       is at 03:00), accepting that C4 is not met as declared.")
        else:
            print(f"C4  ✓ system RAM {ram:.1f}%, under BODY's {RAM_CAUTION_PCT:.0f}% threshold")

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
    n = 0            # thoughts actually produced
    attempts = 0     # loop iterations, INCLUDING ones where the server was down
    server_was_down = False

    try:
        # Bound on ATTEMPTS, not on thoughts. Bounding on thoughts alone means a
        # `--ticks 2` run with the server down waits forever, because a tick that
        # produced no thought never advances the counter. The real daemon (max_ticks
        # is None) still waits indefinitely, which is what we want — but a bounded
        # run must actually be bounded.
        while max_ticks is None or attempts < max_ticks:
            t0 = time.time()
            attempts += 1

            # The server is started BY HAND on this machine and can be closed at any
            # time. A self-sensing loop that dies because its brain went away is a
            # bad sense: the STREAM keeps running regardless, and we should be able
            # to resume thinking the moment the server comes back. So: log ONE line
            # on the transition, wait, retry. Never crash, and never spam.
            if not server_up():
                if not server_was_down:
                    print(f"[SELF_SENSE] ollama server is DOWN — waiting. "
                          f"Start it with:\n"
                          f'             Start-Process "$env:LOCALAPPDATA\\Programs\\Ollama'
                          f'\\ollama.exe" -ArgumentList "serve"')
                    server_was_down = True
                time.sleep(max(0.0, tick - (time.time() - t0)))
                continue

            if server_was_down:
                print("[SELF_SENSE] ollama server is back — resuming")
                server_was_down = False

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
                    # An inference failure loses one thought, not the loop.
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
