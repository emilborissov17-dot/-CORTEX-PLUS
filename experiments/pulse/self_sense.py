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

# Ranked by FIT IN VRAM, not by capability. See README for the hardware assessment.
#
# THE RANKING BUG (fixed 2026-07-14)
# ----------------------------------
# This list used to be ordered by capability — qwen2.5:7b first — with 3b and
# 1.7b annotated "not installed". qwen2.5:3b was then pulled, and the list was
# never revisited. pick_model() walks this list in order and returns the first
# INSTALLED match, so it kept selecting the 7b: --check listed all three models,
# selected the 7b, correctly failed its own C4 (system RAM 92.3%), and advised
# "pull qwen2.5:3b" — a model already sitting on disk. The check was right about
# everything except the one thing it controlled.
#
# The lesson is in the ordering, not the code. On a GTX 1650 with ~3.9 GB of free
# VRAM, the binding constraint is FIT, not intelligence:
#
#   * a model that fits entirely in VRAM costs ~0 system RAM
#   * a model that does not spills its remainder into system RAM — and system RAM
#     is exactly what BODY's 70% caution threshold protects. Above it, BODY cuts
#     the live cycle's workers from 3 to 2, so the experiment would be DEGRADING
#     the live system: precisely what its isolation rules forbid.
#
# So a smaller model that fits BEATS a bigger one that spills, every time. The
# 7b is not a better choice here that we settle for; it is a worse one that we
# fall back to only if nothing that fits is installed.
#
# Within "fits", plain instruct beats reasoning: qwen3 models emit <think>...
# </think> before answering, costing tokens and latency on every tick (stripped in
# _extract_json). A self-sensing loop wants a fast reflex, not a deliberation.
#
# --model overrides all of this, deliberately: measuring the 7b's cost is a
# legitimate thing to want to do. It is just not the default.
PREFERRED_MODELS = [
    "qwen2.5:3b",     # ~1.9 GB — FITS VRAM entirely. Non-reasoning. The default.
    "qwen3:1.7b",     # ~1.4 GB — fits, but reasoning: <think> costs latency per tick
    "qwen2.5:7b",     # 4.68 GB — SPILLS ~1.9 GB into system RAM. Fallback only.
    "qwen3:8b",       # 5.23 GB — spills more, and reasoning on top. Last resort.
]

# Models known to exceed this machine's free VRAM. Used only to WARN when one is
# selected (nothing that fits was installed) or forced via --model — never to
# refuse: measuring the cost of a spilling model is a legitimate experiment.
SPILLS_INTO_RAM = ("qwen2.5:7b", "qwen3:8b")

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
        if model and model.startswith(SPILLS_INTO_RAM):
            print("             ⚠ does NOT fit this GPU's ~3.9 GB free VRAM — it will spill")
            print("               into system RAM. Selected only because nothing smaller is")
            print("               installed (or --model forced it). Expect C4 to breach.")
        if model and model.startswith("qwen3"):
            print("             ⚠ reasoning model — emits <think> blocks; stripped, but")
            print("               it costs latency on every tick.")

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
            print(f"       At >70% BODY cuts the live cycle's workers from 3 to 2 — this")
            print(f"       experiment would be DEGRADING the live system, which is exactly")
            print(f"       what its isolation rules forbid.")
            print()

            # Say what is ACTUALLY wrong. The old text advised "pull qwen2.5:3b"
            # unconditionally — and on 2026-07-14 it said that while qwen2.5:3b
            # was installed and it had just declined to select it. Advice that
            # ignores the machine's real state is worse than no advice: it sends
            # you to fix a problem you do not have.
            fitting = [m["name"] for m in models
                       if not m["name"].startswith(SPILLS_INTO_RAM)]
            if model and model.startswith(SPILLS_INTO_RAM):
                if fitting:
                    print(f"       {model} spills into system RAM, and a model that FITS is")
                    print(f"       already installed: {', '.join(fitting)}.")
                    print(f"       That is a selection bug — report it. Meanwhile:")
                    print(f"           self_sense.py --check --model {fitting[0]}")
                else:
                    print(f"       {model} does not fit the GPU's ~3.9 GB free VRAM, and no")
                    print(f"       smaller model is installed.")
                    print(f"       FIX — pull one that fits entirely in VRAM:")
                    print(f"           ollama pull qwen2.5:3b   # ~1.9 GB; ~1-2s per tick")
                    print(f"       self_sense will then select it automatically.")
            else:
                # The model fits, and RAM is STILL high — so this is not our doing.
                print(f"       {model} fits in VRAM, so this is NOT the model spilling.")
                print(f"       Something else is using the RAM (a live cycle?). Re-check when")
                print(f"       the machine is quiet before blaming the experiment.")
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
    # Interoceptive valence + exteroception change slowly (per-cycle), so give them
    # ONCE as context rather than repeating on every 10s row. Added 2026-07-19 so the
    # brain feels its own pain/vitality and senses the world, not only the substrate.
    latest = samples[-1] if samples else {}
    val = latest.get("valence") or {}
    wld = latest.get("world") or {}
    ctx = []
    if val.get("available"):
        ctx.append(f"FELT STATE: pain={val.get('pain_score')} vitality={val.get('vitality')} "
                   f"pain_points={val.get('pain_points')} mortality_urgency={val.get('mortality_urgency')}")
    if wld.get("available"):
        ctx.append(f"WORLD: displaced={wld.get('displaced_millions')}M "
                   f"undernourished={wld.get('undernourished_pct')}% life_exp={wld.get('life_expectancy')}y "
                   f"inequality_gini={wld.get('inequality_gini')} rule_of_law={wld.get('rule_of_law')} "
                   f"ai_papers={wld.get('ai_papers')} data_sections={wld.get('sections_present')}")
    header = ("\n".join(ctx) + "\n\n") if ctx else ""
    return header + "\n".join(rows)


PROMPT = """You are the proprioceptive sense of CORTEX++, a civilization-monitoring AI.
You are not describing a log file. You are feeling your own body from the inside —
your machine's vital signs, your own FELT STATE (pain and vitality), and the state
of the WORLD you exist to watch.

Your recent sensations (slow-changing felt-state and world first, then one line per
10 seconds of vital signs, oldest last):
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
