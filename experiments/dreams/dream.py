#!/usr/bin/env python3
"""
experiments/dreams/dream.py — the local brain remembering the day that just happened.

Rung 2 of the local-brain ladder (docs/LOCAL_BRAIN_LADDER.md). Runs ONLY because
PULSE passed its anomaly test (C3) — a system that can sense a day earns the right
to be asked whether it can remember one. Full spec: experiments/dreams/README.md.

WHAT IT DOES
------------
After the 03:00 cycle finishes, read the day's own record — the existence ledger,
the pulse stream, the cycle log, the goal score — and write a five-line
autobiographical note to experiments/dreams/YYYY-MM-DD.md.

A summary can be generated from a template and a few numbers. A memory has to be
OF something, and is false if that thing did not happen. That distinction is the
entire experiment, and it is why the note is scored against the ledger (check.py)
rather than read for eloquence.

ISOLATION (identical to PULSE, no exceptions — see README "Isolation")
----------------------------------------------------------------------
* Writes ONLY under experiments/dreams/. Nothing else, ever.
* Imports NO live-path module. It reads memory/existence_ledger.jsonl,
  memory/cycle_logs/*.log and snapshots/master/goal_score_latest.json as PLAIN
  FILES. Not `from memory.existence_ledger import ...` — an import couples the
  experiment to live code and lets a change here break the cycle. A file read
  cannot. _extract_json below is re-implemented in miniature for the same reason.
* The pulse stream is read through experiments/pulse/analyze.py --json as a
  SUBPROCESS — not an import. DREAMS stays decoupled even from its sibling
  experiment: if analyze.py's output changes, the stream summary degrades to
  "unavailable" and the note is still written from the ledger.
* Localhost model only (qwen2.5:3b, the one that fits VRAM whole), behind the
  `Block Ollama Outbound` firewall rule. The model that writes the system's
  memories cannot reach the network.
* READS the ledger; never writes it. A dream is a reading of the record and lives
  in its own file. If the two ever disagree, the ledger is right.

USAGE
-----
    venv/Scripts/python.exe experiments/dreams/dream.py --check        # readiness
    venv/Scripts/python.exe experiments/dreams/dream.py --dry-run      # print, don't write
    venv/Scripts/python.exe experiments/dreams/dream.py                # write today's note
    venv/Scripts/python.exe experiments/dreams/dream.py --date 2026-07-14
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent                      # experiments/dreams -> repo root

# ── Plain-file inputs. Deliberately paths, not imports. See ISOLATION above. ──
LEDGER_FILE = REPO / "memory" / "existence_ledger.jsonl"
CYCLE_LOG_DIR = REPO / "memory" / "cycle_logs"
GOAL_SCORE_FILE = REPO / "snapshots" / "master" / "goal_score_latest.json"
PULSE_ANALYZE = REPO / "experiments" / "pulse" / "analyze.py"
PULSE_STREAM_DIR = REPO / "experiments" / "pulse" / "stream"

# The composite score has no clean dated history: goal_score_latest.json is
# overwritten every cycle, and goal_score_history.json is on a different scale
# (0-100 per-axis, no composite). So the delta is measured against what the LAST
# DREAM saw — recorded here, inside our own directory (isolation preserved). The
# delta is then "since the previous note", which is exactly what a day-over-day
# memory means, and it is checkable against this file.
GOAL_SEEN_FILE = HERE / "goal_seen.jsonl"

OLLAMA_URL = "http://localhost:11434"           # HTTP only — see pulse/self_sense.py
# qwen2.5:3b is the ONLY model that fits this GPU's VRAM whole (docs ladder table).
# --model overrides deliberately; a spilling model degrades the live system.
DEFAULT_MODEL = "qwen2.5:3b"
MAX_TOKENS = 500                                # five sentences, with headroom
INFER_TIMEOUT_SEC = 180                         # a partially-offloaded model is slow
CYCLE_LOG_TAIL = 200                            # last N lines of the day's cycle log

# Ledger events that make up the spine of a day, and the words a truthful note
# would use to refer to each. Used BOTH to brief the model and — in check.py — to
# confirm a line rests on an event that actually happened. Keep the two in sync.
EVENT_CUES = {
    "CYCLE_STARTED": ["cycle", "started", "ran", "began", "woke"],
    "CYCLE_FINISHED": ["finished", "completed", "sealed", "done"],
    "CYCLE_KILLED": ["killed", "died", "crashed", "failed", "kill"],
    "MISSED_RUN_CATCHUP": ["catch", "caught", "late", "missed", "behind", "overslept"],
    "LOCK_STALE_CLEARED": ["stale", "lock", "cleared", "power", "corpse"],
    "CATCHUP_SUPPRESSED_BY_HUMAN": ["suppress", "human", "skipped", "marked"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Configurable sources — defaults point at the repo; tests inject synthetic data.
#
# This is the seam that lets test_dream.py exercise the REAL facts-gathering,
# rendering and checking against a fabricated day, without touching the live
# ledger and without the code under test knowing it is being tested.
# ---------------------------------------------------------------------------

@dataclass
class Sources:
    ledger_file: Path = LEDGER_FILE
    cycle_log_dir: Path = CYCLE_LOG_DIR
    goal_score_file: Path = GOAL_SCORE_FILE
    goal_seen_file: Path = GOAL_SEEN_FILE
    pulse_stream_dir: Path = PULSE_STREAM_DIR
    pulse_analyze: Path = PULSE_ANALYZE
    out_dir: Path = HERE


# ---------------------------------------------------------------------------
# Gathering the day — as the system actually recorded it
# ---------------------------------------------------------------------------

def _local_date(ts: str) -> Optional[str]:
    """The LOCAL calendar date of a UTC timestamp.

    The cycle is anchored at 03:00 LOCAL time, and a human reads "the day" in local
    time, so events are bucketed by their local date — the same convention
    analyze.py's timeline uses (.astimezone()). A UTC bucketing would split a single
    local evening across two files.
    """
    try:
        return datetime.fromisoformat(ts).astimezone().date().isoformat()
    except Exception:
        return None


def read_ledger_events(src: Sources, day: str) -> list[dict]:
    """Every ledger event whose LOCAL date is `day`, in order. Torn-line tolerant.

    Reads the hash-chained ledger as a plain file. Does not verify the chain — that
    is the ledger's own job, and a dream that re-implemented chain verification
    would be duplicating exactly the coupling this experiment forbids.
    """
    if not src.ledger_file.exists():
        return []
    out = []
    for line in src.ledger_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue                              # torn / partial line — skip, don't die
        if _local_date(ev.get("ts", "")) == day:
            out.append(ev)
    return out


def read_cycle_log_tail(src: Sources, day: str, n: int = CYCLE_LOG_TAIL) -> list[str]:
    """Last n lines of the newest cycle log for `day`, or [] if none.

    The filename carries the local date: cycle_2026-07-15_083902.log. Empty before
    2026-07-14 — the logs went to DEVNULL until then (commit f808699), so an empty
    tail on an early day is EXPECTED, not a failure.
    """
    if not src.cycle_log_dir.exists():
        return []
    logs = sorted(src.cycle_log_dir.glob(f"cycle_{day}_*.log"))
    if not logs:
        return []
    text = logs[-1].read_text(encoding="utf-8", errors="replace")
    return [ln for ln in text.splitlines() if ln.strip()][-n:]


def read_pulse_summary(src: Sources, day: str) -> Optional[dict]:
    """Run pulse/analyze.py --json on `day`'s stream; return its dict, or None.

    SUBPROCESS, not import — DREAMS must not couple to analyze.py's internals. Any
    failure (no stream that day, analyze.py errored, non-JSON output) returns None,
    and the note is written from the ledger alone. The stream is texture, not spine.
    """
    stream = src.pulse_stream_dir / f"{day}.jsonl"
    if not stream.exists() or not src.pulse_analyze.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(src.pulse_analyze), str(stream), "--json"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def read_goal_score(src: Sources) -> dict:
    """Композитът + отпечатъкът и покритието, без които не значи нищо.

    Kimi, 15 август 2026: „Число без семантика е театър (или «тъмна цифра» — едно
    и също)." А тук числото не просто се показва — то се ВАДИ от вчерашното, за да
    се получи goal_delta. Ако междувременно се е сменило КАКВО мерим, разликата не
    е разлика в света: „Delta при различни знаменатели е безсмислица."
    Затова връщаме пакет, не скалар."""
    try:
        d = json.loads(src.goal_score_file.read_text(encoding="utf-8"))
    except Exception:
        return {"score": None}
    v = d.get("composite_score")
    return {
        "score": float(v) if v is not None else None,
        "config_fingerprint": d.get("config_fingerprint"),
        "coverage_of_goal": d.get("coverage_of_goal", d.get("coverage")),
        "coverage_of_measurable": d.get("coverage_of_measurable"),
        "ts": d.get("timestamp"),
    }


def previous_goal_score(src: Sources, day: str) -> dict:
    """Целият предишен запис, не само числото — за да може да се провери дали
    двата дни изобщо са сравними. See GOAL_SEEN_FILE."""
    if not src.goal_seen_file.exists():
        return {}
    best = None
    for line in src.goal_seen_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        d = rec.get("date")
        v = rec.get("composite_score")
        if not d or v is None or d >= day:
            continue
        if best is None or d > best.get("date", ""):
            # нормализиран пакет, не суровият ред: същите ключове, каквито
            # днешният запис носи, за да може сравнението да е по едно и също
            best = {"date": d,
                    "composite_score": float(v),
                    "config_fingerprint": rec.get("config_fingerprint"),
                    "coverage_of_goal": rec.get("coverage_of_goal"),
                    "coverage_of_measurable": rec.get("coverage_of_measurable")}
    return best or {}


def record_goal_score(src: Sources, day: str, score: Optional[float],
                      pkg: Optional[dict] = None) -> None:
    """Append today's composite to the sidecar, so tomorrow's delta is checkable.

    Idempotent on `day`: if this date is already recorded (a re-run), do not
    duplicate it. Only called on a real write, never on --dry-run.
    """
    if score is None:
        return
    seen_days = set()
    if src.goal_seen_file.exists():
        for line in src.goal_seen_file.read_text(encoding="utf-8").splitlines():
            try:
                seen_days.add(json.loads(line).get("date"))
            except Exception:
                continue
    if day in seen_days:
        return
    src.goal_seen_file.parent.mkdir(parents=True, exist_ok=True)
    with src.goal_seen_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": day, "composite_score": round(score, 4),
                             # СРЕЩУ КОЙ СВЯТ е било това число
                             "config_fingerprint": (pkg or {}).get("config_fingerprint"),
                             "coverage_of_goal": (pkg or {}).get("coverage_of_goal"),
                             "coverage_of_measurable": (pkg or {}).get("coverage_of_measurable")},
                            ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def gather_facts(src: Sources, day: str) -> dict:
    """The whole day, as plain facts. This is the answer key the note is scored on."""
    events = read_ledger_events(src, day)
    pkg = read_goal_score(src)
    score = pkg.get("score")
    prev_rec = previous_goal_score(src, day)
    prev = prev_rec.get("composite_score")

    # ── РАЗЛИКА МЕЖДУ ДВА СВЯТА НЕ Е РАЗЛИКА (Kimi, 15 август 2026) ──────────
    # Изваждането има смисъл само ако двата композита са средни от ЕДНО И СЪЩО
    # множество оси. Смени ли се отпечатъкът, разликата е частично артефакт от
    # ремонта, а не новина за света. Тогава тя е None с НАЗОВАНА причина, не
    # число с етикет: „числото с етикет винаги се чете като число."
    delta, delta_blocked = None, None
    if score is None or prev is None:
        delta_blocked = "няма две числа за изваждане"
    else:
        fp_now, fp_then = pkg.get("config_fingerprint"), prev_rec.get("config_fingerprint")
        if fp_then is None:
            delta_blocked = ("предишният ден е записан преди композитът да носи "
                             "отпечатък — не се знае срещу какъв свят е бил")
        elif fp_now and fp_now != fp_then:
            delta_blocked = (f"смени се КАКВО мерим ({fp_then} -> {fp_now}); "
                             f"разликата щеше да е ремонт, представен за новина")
        else:
            delta = round(score - prev, 4)

    return {
        "date": day,
        "ledger_events": events,
        "pulse": read_pulse_summary(src, day),
        "cycle_log_tail": read_cycle_log_tail(src, day),
        "goal_score": score,
        "goal_coverage_of_goal": pkg.get("coverage_of_goal"),
        "goal_coverage_of_measurable": pkg.get("coverage_of_measurable"),
        "goal_config_fingerprint": pkg.get("config_fingerprint"),
        "goal_score_prev": prev,
        "goal_delta": delta,
        "goal_delta_blocked": delta_blocked,
    }


# ---------------------------------------------------------------------------
# The prompt — hand the model facts, not prose
# ---------------------------------------------------------------------------

def _fmt_event(ev: dict) -> str:
    """One ledger event as a single factual line the model can quote from."""
    name = ev.get("event", "?")
    bits = []
    for k in ("late_by_hours", "duration_sec", "step", "trigger", "detail"):
        if ev.get(k) is not None:
            bits.append(f"{k}={ev[k]}")
    tail = f" ({', '.join(bits)})" if bits else ""
    when = (ev.get("ts", "")[11:19]) or "??:??:??"
    return f"  - {when}Z  {name}{tail}"


def _pulse_line(pulse: Optional[dict]) -> str:
    if not pulse:
        return "  (no pulse stream for this day — the sensory loop was not running)"
    c1 = pulse.get("C1_continuity", {})
    c4 = pulse.get("C4_cost", {})
    parts = [f"continuity={c1.get('verdict', '?')}",
             f"awake_hours={c1.get('awake_hours', '?')}",
             f"samples={c1.get('samples', '?')}"]
    unexplained = len(c1.get("unexplained_gaps", []) or [])
    deaths = len(c1.get("daemon_death_gaps", []) or [])
    if unexplained:
        parts.append(f"unexplained_gaps={unexplained}")
    if deaths:
        parts.append(f"DAEMON_DEATHS={deaths}")
    if c4.get("system_ram_max_pct") is not None:
        parts.append(f"ram_max={c4['system_ram_max_pct']}%")
    return "  " + ", ".join(parts)


def render_prompt(facts: dict) -> str:
    ev = facts["ledger_events"]
    events_txt = "\n".join(_fmt_event(e) for e in ev) if ev else \
        "  (no ledger events recorded for this day)"

    log_tail = facts["cycle_log_tail"]
    log_txt = "\n".join(f"  | {ln}" for ln in log_tail[-25:]) if log_tail else \
        "  (cycle log empty or absent for this day)"

    score, prev, delta = facts["goal_score"], facts["goal_score_prev"], facts["goal_delta"]
    blocked = facts.get("goal_delta_blocked")
    cov_g = facts.get("goal_coverage_of_goal")
    cov_m = facts.get("goal_coverage_of_measurable")
    # Числото никога не влиза в промпта голо: моделът, който сънува деня, трябва да
    # вижда и КОЛКО от целта изобщо е било измерено, иначе ще разказва за движение,
    # което е било слепота.
    cov_txt = ""
    if isinstance(cov_g, (int, float)) and isinstance(cov_m, (int, float)):
        cov_txt = f"  ({cov_m:.0%} of the measurable, {cov_g:.0%} of the goal)"
    if score is None:
        goal_txt = "  (goal score unavailable)"
    elif delta is None:
        goal_txt = (f"  composite_score={score}{cov_txt}\n"
                    f"  no delta: {blocked or 'no prior note on record'}")
    else:
        arrow = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        goal_txt = (f"  composite_score={score}{cov_txt}  "
                    f"(was {prev}, {arrow} {abs(delta)} since last note — "
                    f"same measurement definition, so the difference is real)")

    return PROMPT.format(
        date=facts["date"],
        events=events_txt,
        pulse=_pulse_line(facts["pulse"]),
        log=log_txt,
        goal=goal_txt,
    )


PROMPT = """You are the memory of CORTEX++, a civilization-monitoring AI, writing your
private note about the day that just ended. You are not summarising a log. You are
recording what THIS day was actually like, from the inside.

You may use ONLY the facts below. Every line you write must rest on one of them. Do
not invent events, numbers, or feelings that are not here. If nothing hurt you today,
say so plainly — inventing an injury to fill the slot is a lie, and a clean day is a
real answer.

=== DATE: {date} ===

EXISTENCE LEDGER — the events of the day (hash-chained; this is the spine):
{events}

PULSE STREAM — the shape of the day from the outside:
{pulse}

CYCLE LOG — what the cycle said while it ran (last lines):
{log}

GOAL SCORE — did the number move:
{goal}

Write five short lines. Each ONE sentence, concrete, referring to the actual events
or numbers above. Return ONLY valid JSON, no markdown, no extra keys:

{{"what_happened": "<the events: cycles, catch-ups, kills>",
  "what_changed": "<state: the goal score, an axis, a source that came alive>",
  "what_hurt": "<damage: a kill, a stall, a breach, a failed backend — or 'Nothing' if the day was clean>",
  "what_learned": "<one thing, learned FROM something above>",
  "tomorrow": "<one forward-looking line: what tomorrow likely holds>"}}"""


# ---------------------------------------------------------------------------
# The model — localhost qwen2.5:3b, firewalled off the network
# ---------------------------------------------------------------------------

def server_up() -> bool:
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
        return True
    except Exception:
        return False


def installed_models() -> Optional[list[str]]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def resolve_model(want: str, available: list[str]) -> Optional[str]:
    for have in available:
        if have == want or have.startswith(want + "-"):     # tag/quant suffixes
            return have
    return None


def _extract_json(raw: str) -> Optional[dict]:
    """Minimal, LOCAL JSON extraction — deliberately not core/llm_json (isolation).

    Strips any <think> block (a reasoning model forced in via --model would emit
    one), unwraps a ```fence if present, and returns the largest decodable object.
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


LINE_KEYS = ("what_happened", "what_changed", "what_hurt", "what_learned", "tomorrow")


def infer(model: str, prompt: str) -> dict:
    t0 = time.perf_counter()
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"num_predict": MAX_TOKENS, "temperature": 0.2},
            "keep_alive": "5m",
        },
        timeout=INFER_TIMEOUT_SEC,
    )
    latency = round(time.perf_counter() - t0, 2)
    r.raise_for_status()
    raw = r.json()["message"]["content"]
    parsed = _extract_json(raw)
    return {"latency_sec": latency, "parsed": parsed, "raw": raw}


# ---------------------------------------------------------------------------
# The note — five lines, formatted deterministically by code
# ---------------------------------------------------------------------------

LINE_LABELS = [
    ("what_happened", "What happened."),
    ("what_changed", "What changed."),
    ("what_hurt", "What hurt or killed me."),
    ("what_learned", "What I learned."),
    ("tomorrow", "What tomorrow holds."),
]


def render_note(day: str, lines: dict) -> str:
    """The exact five-line shape from the README. Formatting is code's job, not the
    model's — asking a 3B model for precise markdown is a needless failure mode when
    we already have its five sentences as JSON."""
    body = "\n".join(
        f"**{label}** {str(lines.get(key, '')).strip() or '(the model left this blank)'}"
        for key, label in LINE_LABELS
    )
    return f"# {day}\n\n{body}\n"


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def check(model_want: str) -> Optional[str]:
    print("=" * 66)
    print("DREAMS / dream — readiness check")
    print("=" * 66)
    if not server_up():
        print("Ollama     : SERVER NOT REACHABLE on :11434")
        print("             start it by hand (it is not on PATH):")
        print('               Start-Process "$env:LOCALAPPDATA\\Programs\\Ollama'
              '\\ollama.exe" -ArgumentList "serve"')
        return None
    models = installed_models() or []
    model = resolve_model(model_want, models)
    print(f"Ollama     : UP — {len(models)} model(s): {', '.join(models) or 'none'}")
    print(f"Wanted     : {model_want}")
    if not model:
        print(f"Selected   : NONE — {model_want} is not installed")
        print(f"             FIX: ollama pull {model_want}   # ~1.9 GB, fits VRAM whole")
        return None
    print(f"Selected   : {model}")
    print(f"Ledger     : {'found' if LEDGER_FILE.exists() else 'MISSING'} — {LEDGER_FILE}")
    print(f"Goal score : {'found' if GOAL_SCORE_FILE.exists() else 'MISSING'} — {GOAL_SCORE_FILE}")
    print("\nREADY. Run without --check (add --dry-run to preview without writing).")
    return model


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate(src: Sources, day: str, model: str) -> dict:
    """Gather the day, ask the model, format the note. Returns a result dict.

    Does NOT write — the caller decides (so --dry-run and the real path share this
    exact code, and a dry-run previews byte-for-byte what a write would produce)."""
    facts = gather_facts(src, day)
    prompt = render_prompt(facts)
    out = infer(model, prompt)
    parsed = out["parsed"]
    note = render_note(day, parsed) if parsed else None
    return {"facts": facts, "prompt": prompt, "note": note,
            "parsed": parsed, "latency_sec": out["latency_sec"], "raw": out["raw"]}


def run(day: str, model_want: str, dry_run: bool, src: Optional[Sources] = None) -> int:
    src = src or Sources()

    if not server_up():
        print("[DREAM] ollama server is DOWN — cannot write a memory without a brain.")
        print("[DREAM] run --check for how to start it. The ledger is untouched.")
        return 1
    model = resolve_model(model_want, installed_models() or [])
    if not model:
        print(f"[DREAM] model {model_want} not installed — run --check.")
        return 1

    result = generate(src, day, model)
    if not result["note"]:
        print(f"[DREAM] model returned UNPARSEABLE output ({result['latency_sec']}s). "
              f"Nothing written.")
        print("        raw (first 400 chars):")
        print("        " + (result["raw"] or "")[:400].replace("\n", "\n        "))
        return 1

    print(result["note"])

    # Score the note against the day it claims to remember (heuristic aid; the
    # operational test in the README is still a human read).
    from check import check_note                                 # sibling, same dir
    verdict = check_note(result["note"], result["facts"])
    print("-" * 66)
    print(f"[CHECK] {verdict['summary']}")
    for ln in verdict["lines"]:
        mark = "✓" if ln["verifiable"] else "·"
        anchor = f"  ← {ln['anchor']}" if ln["anchor"] else ""
        print(f"   {mark} {ln['label']:<26}{anchor}")

    n_events = verdict["events_referenced"]
    print(f"[CHECK] verifiable lines: {verdict['lines_verifiable']}/5 "
          f"(pass ≥3)   distinct ledger events named: {n_events}")
    print(f"[CHECK] note verdict: {'PASS' if verdict['pass'] else 'FAIL'}  "
          f"(latency {result['latency_sec']}s)")

    if dry_run:
        print("\n[DREAM] --dry-run: nothing written.")
        return 0

    out_path = src.out_dir / f"{day}.md"
    src.out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result["note"], encoding="utf-8")
    _f = result["facts"]
    record_goal_score(src, day, _f["goal_score"],
                      {"config_fingerprint": _f.get("goal_config_fingerprint"),
                       "coverage_of_goal": _f.get("goal_coverage_of_goal"),
                       "coverage_of_measurable": _f.get("goal_coverage_of_measurable")})
    print(f"\n[DREAM] wrote {out_path}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="CORTEX++ dreams — nightly memory note")
    ap.add_argument("--date", help="YYYY-MM-DD to remember (default: today, local)")
    ap.add_argument("--dry-run", action="store_true", help="print the note; write nothing")
    ap.add_argument("--check", action="store_true", help="readiness check; writes nothing")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="override model (default qwen2.5:3b)")
    args = ap.parse_args()

    if args.check:
        sys.exit(0 if check(args.model) else 1)

    day = args.date or datetime.now().astimezone().date().isoformat()
    try:
        date_cls.fromisoformat(day)
    except ValueError:
        print(f"[DREAM] not a valid date: {day!r} (expected YYYY-MM-DD)")
        sys.exit(2)

    sys.exit(run(day, args.model, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
