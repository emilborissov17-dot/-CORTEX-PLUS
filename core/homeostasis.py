#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/homeostasis.py
Хомеостаза на CORTEX++ — самопознание и адаптивно оцеляване.

Не просто мери — решава:
  "Какви са текущите ми възможности?"
  "Какво мога да направя с тях?"
  "Ако не мога сам — как да намеря ресурс отвън?"

Разлика от body_scanner:
  body_scanner = сетива (усеща)
  homeostasis  = нервна система (интерпретира и решава)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SELF_PROFILE_PATH  = BASE / "memory" / "self_profile.json"
DIRECTIVES_PATH    = BASE / "memory" / "adaptive_directives.json"


# ---------------------------------------------------------------------------
# Self-profile — постоянно самопознание
# ---------------------------------------------------------------------------

def _detect_gpu():
    """Detect a real NVIDIA GPU via nvidia-smi (no extra deps). Returns
    {name, vram_total_mb, vram_free_mb} or None. Never raises.
    Added 30 Jul 2026: the profile hard-coded 'No local GPU', but the box actually
    has a GTX 1650 (4GB) — the self-model was lying about its own body, which wrongly
    marked K1b weight-learning as impossible. Now it senses the card."""
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        name, total, free = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "vram_total_mb": int(float(total)),
                "vram_free_mb": int(float(free))}
    except Exception:
        return None


def build_self_profile() -> dict:
    """
    Изгражда пълен профил на системата — хардуер, APIs, възможности, лимити.
    Записва се при всеки цикъл. Чете се от orchestrator и CortexStrategist.
    """
    profile: dict = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "identity":     "CORTEX++ AGI — civilization monitor",
        "hardware":     {},
        "apis":         {},
        "capabilities": [],
        "limitations":  [],
        "current_vitals": {},
    }

    # Хардуер
    try:
        import psutil
        m  = psutil.virtual_memory()
        d  = psutil.disk_usage("/")
        c  = psutil.cpu_count(logical=False)
        profile["hardware"] = {
            "ram_total_gb":   round(m.total / 1e9, 1),
            "ram_free_gb":    round(m.available / 1e9, 1),
            "ram_percent":    m.percent,
            "disk_total_gb":  round(d.total / 1e9, 0),
            "disk_free_gb":   round(d.free / 1e9, 0),
            "cpu_cores":      c,
            "platform":       "windows",
        }
        profile["current_vitals"] = {
            "ram_pressure":  (
                "CRITICAL" if m.percent > 90 else
                "HIGH"     if m.percent > 75 else
                "MODERATE" if m.percent > 50 else "LOW"
            ),
            "can_run_parallel": m.percent < 75,
            "can_run_chromadb": m.available > 2e9,
            "safe_to_start":    m.percent < 85,
        }
        gpu = _detect_gpu()
        if gpu:
            profile["hardware"]["gpu"] = gpu
    except Exception:
        pass

    # APIs
    env_file = BASE / ".env"
    def _has_key(name):
        import os
        if os.environ.get(name):
            return True
        if env_file.exists():
            return any(l.startswith(name + "=") and len(l) > len(name) + 2
                       for l in env_file.read_text(encoding="utf-8").splitlines())
        return False

    profile["apis"] = {
        "groq":    {"available": _has_key("GROQ_API_KEY"),    "limit": "30 req/min, free tier"},
        "gemini":  {"available": _has_key("GEMINI_API_KEY"),  "limit": "1500 req/day, free tier"},
        "youtube": {"available": _has_key("YOUTUBE_API_KEY"), "limit": "10000 units/day"},
        "nasa":    {"available": _has_key("NASA_API_KEY"),     "limit": "1000 req/hr"},
    }

    # Статични възможности
    profile["capabilities"] = [
        "monitor 25 civilization axes via web intelligence",
        "LLM synthesis via Groq (llama-3.3-70b) + Gemini fallback",
        "audio transcription via Groq Whisper API",
        "real data: NOAA CO2, NASA GISTEMP, World Bank WDI, GBIF",
        "self-modification via self_modifier agent",
        "autonomous data discovery via data_scout",
        "snapshot history and trend tracking",
    ]

    # Динамични ограничения (от текущите vitals)
    lims = []
    hw = profile["hardware"]
    vitals = profile["current_vitals"]

    if hw.get("ram_total_gb", 0) < 16:
        lims.append(f"Limited RAM ({hw.get('ram_total_gb','?')}GB) — cannot run local LLMs or ChromaDB at full load")
    if not vitals.get("can_run_parallel"):
        lims.append(f"RAM at {hw.get('ram_percent','?')}% — parallel workers reduced to 1-2")
    if not vitals.get("can_run_chromadb"):
        lims.append("Insufficient free RAM for ChromaDB — semantic memory degraded")
    if not profile["apis"]["groq"]["available"]:
        lims.append("No Groq API key — LLM synthesis unavailable")
    gpu = hw.get("gpu")
    if gpu:
        vram_gb = round(gpu.get("vram_total_mb", 0) / 1024, 1)
        profile["capabilities"].append(
            f"Local GPU: {gpu.get('name')} ({vram_gb}GB VRAM) — small-model LoRA/QLoRA "
            f"fine-tune and neural RL policies feasible on-box (K1b no longer hardware-blocked)")
        if vram_gb < 8:
            lims.append(f"GPU VRAM limited ({vram_gb}GB) — only small models (<=3B) with "
                        f"quantization/LoRA; no full fine-tune of large models")
    else:
        lims.append("No local GPU — all inference via cloud APIs (rate-limited)")
    lims.append("No persistent process — cycle must be triggered manually or via scheduler")

    profile["limitations"] = lims

    # Запис
    SELF_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELF_PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return profile


# ---------------------------------------------------------------------------
# Homeostatic assessment — какво мога да направя сега?
# ---------------------------------------------------------------------------

def assess(verbose: bool = True) -> dict:
    """
    Чете body directives + self_profile и решава:
      - Какъв режим да се използва
      - Какви стъпки да се пропуснат
      - Какви workarounds са налични
      - Дали да се стартира изобщо
    """
    # Зареди директиви от body_scanner
    directives = {}
    if DIRECTIVES_PATH.exists():
        try:
            directives = json.loads(DIRECTIVES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    profile = build_self_profile()
    vitals  = profile.get("current_vitals", {})
    hw      = profile.get("hardware", {})
    apis    = profile.get("apis", {})

    ram_pct    = hw.get("ram_percent", 0)
    ram_free   = hw.get("ram_free_gb", 0)
    groq_ok    = apis.get("groq", {}).get("available", False)
    gemini_ok  = apis.get("gemini", {}).get("available", False)
    connected  = directives.get("connectivity", "FULL") != "OFFLINE"

    assessment = {
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "can_start":      True,
        "abort_reason":   None,
        "cycle_mode":     directives.get("cycle_mode", "FULL"),
        "workarounds":    [],
        "skip_steps":     [],
        "resource_needs": [],
        "self_awareness": [],
    }

    # ── Може ли да стартира? ────────────────────────────────────────────
    if ram_pct > 92:
        assessment["can_start"]    = False
        assessment["abort_reason"] = (
            f"RAM {ram_pct:.0f}% ({ram_free:.1f}GB free) — "
            "insufficient to run safely. Free memory first."
        )
        assessment["resource_needs"].append("Need 2+ GB free RAM to start cycle")
        return assessment

    # ── Workarounds при налягане ────────────────────────────────────────
    if ram_pct > 75:
        assessment["workarounds"].append("Skip ChromaDB — use flat-file memory only")
        assessment["skip_steps"].append("chromadb_operations")
    if ram_pct > 85:
        assessment["workarounds"].append("Process 10 axes instead of 25 — prioritize by xrisk_score")
        assessment["skip_steps"].append("low_priority_axes")
        assessment["workarounds"].append("Disable parallel YouTube fetching — sequential only")

    if not connected:
        assessment["workarounds"].append("Offline — use cached web_intel from last cycle")
        assessment["skip_steps"].extend(["web_intelligence", "youtube", "rss_feeds"])
        assessment["resource_needs"].append("Network connectivity needed for full cycle")

    if not groq_ok and not gemini_ok:
        assessment["workarounds"].append("No LLM APIs — generate rule-based snapshots only")
        assessment["skip_steps"].append("llm_synthesis")
        assessment["resource_needs"].append("Groq or Gemini API key required for LLM synthesis")

    # ── Самопознание ────────────────────────────────────────────────────
    assessment["self_awareness"] = [
        f"I am running on {hw.get('ram_total_gb','?')}GB RAM laptop",
        f"RAM currently {ram_pct:.0f}% used — {ram_free:.1f}GB available",
        f"LLM access: Groq={'yes' if groq_ok else 'no'}, Gemini={'yes' if gemini_ok else 'no'}",
        f"Network: {'connected' if connected else 'OFFLINE'}",
        f"My bottleneck: {'RAM' if ram_pct > 75 else 'LLM rate limits' if groq_ok else 'no LLM'}",
        (
            "I need external compute (Groq/Gemini) because I have no local GPU"
            if not groq_ok else
            "External LLMs available — I can delegate heavy cognition to cloud"
        ),
    ]

    if assessment["workarounds"] and verbose:
        print(f"[HOMEO] RAM={ram_pct:.0f}% — applying {len(assessment['workarounds'])} workarounds:")
        for w in assessment["workarounds"]:
            print(f"[HOMEO]   ↳ {w}")
    elif verbose:
        print(f"[HOMEO] RAM={ram_pct:.0f}% — all systems nominal, full cycle")

    # Запис
    out = BASE / "memory" / "homeostasis_latest.json"
    out.write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    return assessment


def as_prompt_block(assessment: dict | None = None) -> str:
    """
    Форматира самопознанието като текст за инжектиране в LLM промпт.
    CortexStrategist, HyperClaw, orchestrator — всички го виждат.
    """
    if assessment is None:
        try:
            p = BASE / "memory" / "homeostasis_latest.json"
            assessment = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            assessment = {}

    lines = ["── SYSTEM SELF-AWARENESS ──────────────────────────────"]
    for line in assessment.get("self_awareness", []):
        lines.append(f"  {line}")
    if assessment.get("workarounds"):
        lines.append("Current adaptations:")
        for w in assessment["workarounds"]:
            lines.append(f"  ↳ {w}")
    if assessment.get("resource_needs"):
        lines.append("Resource gaps:")
        for r in assessment["resource_needs"]:
            lines.append(f"  ⚠ {r}")
    lines.append("──────────────────────────────────────────────────────")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# THE DEFENDED VARIABLES (23 Aug 2026)
# ═══════════════════════════════════════════════════════════════════════════
#
# WHY THIS LIVES IN THE SAME FILE AS assess(), AND WHAT THE DIFFERENCE IS.
# Everything above is the ADAPTIVE layer: it reads the body once at boot and
# decides what kind of night to have — FULL, MINIMAL, which steps to skip. It
# runs once and its thresholds are inline literals.
#
# This is the HOMEOSTATIC layer. It watches two variables continuously, holds a
# level with hysteresis, acts to move the value back, and notices when its own
# action did not work. Its thresholds are in config/homeostasis.json, which is
# human-approved, hash-stamped and never written by this system.
#
# They are not rivals. assess() answers "what can I do tonight"; this answers
# "am I still able to do anything at all". The second one can stop the first.
#
# TWO VARIABLES ONLY, and the restraint is the design. The review's words:
# building five actuators at once gives you "the disk cleanup causes a CPU
# spike, which raises a thermal alarm, which throttles, which slows the cycle,
# which raises a duration alarm — that is not homeostasis, that is an
# autoimmune disorder".

import hashlib as _hashlib
import os as _os
import shutil as _shutil

HOMEOSTASIS_CONFIG = BASE / "config" / "homeostasis.json"
HOMEOSTASIS_STATE = BASE / "memory" / "homeostasis_state.json"

NOTICE, ACTION, GATE = "notice", "action", "gate"
LEVELS = (NOTICE, ACTION, GATE)          # ordered least -> most severe
CLEAR = "clear"

# Confidence in a TTT is a statement about the SAMPLE, not about the future.
CONF_NONE, CONF_LOW, CONF_HIGH = "none", "low", "high"


class ConfigRefused(Exception):
    """The signed config did not verify. The layer refuses; it does not guess."""


def _canonical_bytes(doc: dict) -> bytes:
    body = {k: v for k, v in doc.items() if k != "sha256"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def load_config(path=None) -> dict:
    """Read config/homeostasis.json and verify its own stamp.

    A MISMATCH IS A HARD REFUSAL, NOT A FALLBACK. Silent defaults here would
    mean the thresholds that decide whether a cycle may start could be changed
    by anything that can write a file, and nobody would see it. The layer
    declines to run and says so.
    """
    p = Path(path or HOMEOSTASIS_CONFIG)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigRefused("cannot read {}: {}".format(p, exc)) from exc
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise ConfigRefused("{} is not valid JSON: {}".format(p, exc)) from exc
    stamped = doc.get("sha256")
    if not stamped:
        raise ConfigRefused("{} carries no sha256".format(p))
    actual = _hashlib.sha256(_canonical_bytes(doc)).hexdigest()
    if actual != stamped:
        raise ConfigRefused(
            "{} sha256 mismatch: stamped {}, computed {} — the approved "
            "thresholds have been edited without being re-approved".format(
                p, stamped[:16], actual[:16]))
    return doc


# ---------------------------------------------------------------------------
# Sensors — two, and no more
# ---------------------------------------------------------------------------

# GUARDED (23 Aug 2026). These two functions are the only places this layer
# touches the machine, so they are where "a subscriber never probes a sensor"
# is enforced. Called from inside an event_bus consumer callback they raise
# SensorProbeInSubscriber rather than quietly returning a second reading that
# disagrees with the one the bus already published.
try:
    from core.event_bus import guard_sensor as _guard_sensor
except Exception:                                          # pragma: no cover
    def _guard_sensor(_name):                              # fail-open
        return lambda fn: fn


@_guard_sensor("ram_free")
def read_ram_free_mb() -> float:
    import psutil
    return psutil.virtual_memory().available / (1024 ** 2)


@_guard_sensor("disk_free_pct")
def read_disk_free_pct(path=None) -> float:
    du = _shutil.disk_usage(str(path or BASE))
    return 100.0 * du.free / du.total


SENSORS = {
    "ram_free": read_ram_free_mb,
    "disk_free_pct": lambda: read_disk_free_pct(),
}


# ---------------------------------------------------------------------------
# The four interoceptive numbers. No affect vocabulary, anywhere.
# ---------------------------------------------------------------------------

def interoception(name: str, value: float, spec: dict, history: list) -> dict:
    """distance, direction, rate and ttt for one defended variable.

    `history` is [(epoch_seconds, value), ...] oldest first.

    TTT IS INFINITE WHEN THE RATE POINTS AWAY. A variable moving to safety has
    no time-to-threshold, and reporting a large finite number there would invite
    somebody to compare it with a real one.
    """
    levels = spec["levels"]
    # The next threshold DOWNWARD is the one that matters for a
    # higher_is_safer variable: the nearest one still below the current value.
    below = sorted((v for v in levels.values() if v <= value), reverse=True)
    target = below[0] if below else min(levels.values())
    distance = value - target

    rate, conf, stderr, significant = _rate_per_second(history, spec)
    if rate is None:
        direction = "unknown"
    elif not significant:
        # The fit does not beat its own noise. "flat" here means "we cannot
        # tell", and the TTT is withheld rather than extrapolated from scatter.
        direction = "flat"
    elif rate > 0:
        direction = "rising"
    elif rate < 0:
        direction = "falling"
    else:
        direction = "flat"

    ttt = None
    if rate is None or not significant:
        ttt = None                # not "inf": inf claims it is not heading there
    elif rate < 0 and distance > 0:
        ttt = distance / abs(rate)
    else:
        ttt = float("inf")        # moving away from the threshold, or not moving

    return {
        "variable": name,
        "value": round(value, 3),
        "unit": spec.get("unit", ""),
        "next_threshold": target,
        "distance": round(distance, 3),
        "direction": direction,
        "rate_per_second": None if rate is None else round(rate, 8),
        "rate_per_hour": None if rate is None else round(rate * 3600.0, 5),
        "rate_stderr_per_second": None if stderr is None else round(stderr, 10),
        "rate_significant": bool(significant),
        "ttt_seconds": (None if ttt is None
                        else ("inf" if ttt == float("inf") else round(ttt, 1))),
        # Confidence in WHAT, when there is no TTT? A "high" beside a withheld
        # number reads as certainty about the withholding. There is no TTT to
        # be confident in, so the label goes with it.
        "ttt_confidence": (conf if ttt is not None else CONF_NONE),
        "samples": len(history),
    }


# A slope has to beat its own noise before it is allowed to be a direction.
# Two standard errors is the bar. Below it the fit is indistinguishable from a
# flat line through scatter, and the honest output is "flat, no TTT".
SLOPE_SIGNIFICANCE_SE = 2.0


def _rate_per_second(history: list, spec: dict):
    """(rate, confidence, stderr, significant).

    Least squares over the window, plus the standard error of the slope.

    WHY THE STANDARD ERROR IS NOT OPTIONAL (23 Aug 2026)
    -----------------------------------------------------
    On 23 Aug, RAM fluctuated between 3628 and 3744 MB with no trend at all.
    Least squares fitted -1652 MB/hour to that scatter, interoception turned it
    into "105 minutes to the gate", and the label on it was
    `confidence: high` — because nine samples is nine samples, and the
    confidence label describes the SAMPLE, not the fit.

    A number with the wrong label is worse than a missing number. Nothing
    mechanical depended on it (the gate compares the instantaneous value against
    its thresholds and never reads a TTT), but a human reading that line would
    have believed the machine had an hour and three quarters to live.

    So the slope must exceed SLOPE_SIGNIFICANCE_SE standard errors before it is
    reported as a direction. Below that bar the caller is told the fit is not
    significant and emits `direction: flat, ttt: none` — "we cannot tell",
    which is a different statement from `ttt: inf`, "it is confidently not
    heading there".

    stderr(b) = sqrt( (SSE / (n-2)) / Sxx )
    """
    cfg = _TTT_CFG
    min_n = int(cfg.get("min_samples_for_rate", 3))
    high_n = int(cfg.get("high_confidence_samples", 8))
    window = float(cfg.get("sample_window_minutes", 60)) * 60.0

    pts = [(t, v) for t, v in history if isinstance(t, (int, float))]
    if pts:
        newest = pts[-1][0]
        pts = [(t, v) for t, v in pts if newest - t <= window]
    n = len(pts)
    if n < min_n:
        return None, CONF_NONE, None, False
    span = pts[-1][0] - pts[0][0]
    if span <= 0:
        return None, CONF_NONE, None, False
    mean_t = sum(t for t, _ in pts) / n
    mean_v = sum(v for _, v in pts) / n
    num = sum((t - mean_t) * (v - mean_v) for t, v in pts)
    den = sum((t - mean_t) ** 2 for t, _ in pts)
    if den == 0:
        return None, CONF_NONE, None, False

    slope = num / den
    conf = CONF_HIGH if n >= high_n else CONF_LOW

    # Residual scatter about the fitted line.
    if n <= 2:
        # Two points define a line exactly; there is no residual to measure and
        # therefore no evidence that the line is real.
        return slope, conf, None, False
    intercept = mean_v - slope * mean_t
    sse = sum((v - (intercept + slope * t)) ** 2 for t, v in pts)
    stderr = ((sse / (n - 2)) / den) ** 0.5
    significant = abs(slope) >= SLOPE_SIGNIFICANCE_SE * stderr
    return slope, conf, stderr, significant


_TTT_CFG = {"min_samples_for_rate": 3, "high_confidence_samples": 8,
            "sample_window_minutes": 60}


# ---------------------------------------------------------------------------
# Hysteresis — a level arms at its threshold and disarms past threshold+h
# ---------------------------------------------------------------------------

def level_for(value: float, spec: dict, armed: str = CLEAR) -> str:
    """The level this value holds, given what is currently armed.

    ARMING IS NOT THE SAME AS CLEARING, and that asymmetry is the whole point.
    A higher_is_safer variable arms a level when it falls TO the threshold, and
    clears it only when it climbs back past threshold + hysteresis. Without the
    gap a value sitting on the line chatters: engage, release, engage, release,
    and for the disk actuator every one of those is a real deletion sweep.
    """
    levels = spec["levels"]
    h = float(spec.get("hysteresis", 0))

    # What would arm right now, ignoring history?
    fresh = CLEAR
    for name in LEVELS:                       # notice, action, gate
        if value <= levels[name]:
            fresh = name
    if armed == CLEAR:
        return fresh

    # Something is armed. It stays armed until the value clears ITS release
    # point; a MORE severe level may arm at any time.
    armed_idx = LEVELS.index(armed) if armed in LEVELS else -1
    fresh_idx = LEVELS.index(fresh) if fresh in LEVELS else -1
    if fresh_idx > armed_idx:
        return fresh                          # escalation is immediate
    if value >= levels[armed] + h:
        # Cleared this level. Fall back to whatever else still holds, which
        # may be a milder level rather than CLEAR.
        return fresh
    return armed                              # still inside the dead band


def release_point(spec: dict, level: str) -> float:
    return float(spec["levels"][level]) + float(spec.get("hysteresis", 0))


# ---------------------------------------------------------------------------
# INSUFFICIENT — the system does not fight a symptom it cannot move
# ---------------------------------------------------------------------------
#
# An actuator that fires and does not move the value is worse than one that
# never fired: it burns the resource it was trying to save, it looks like the
# problem is being handled, and it will do the same thing again in ten minutes.
#
# So an action is judged by its EFFECT, measured after the fact. If the value
# has not come back past the release point, that action is marked INSUFFICIENT:
# it is not repeated for 24 hours, and the NEXT arrival at the action level is
# treated as the GATE level instead. The escalation goes to the human, because
# the machine has just demonstrated it has nothing left to try.


def load_state(path=None) -> dict:
    try:
        blob = json.loads(Path(path or HOMEOSTASIS_STATE).read_text(
            encoding="utf-8"))
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


def save_state(state: dict, path=None) -> bool:
    """Durable: this is what tells the next boot which actions are burnt."""
    try:
        p = Path(path or HOMEOSTASIS_STATE)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.flush()
            _os.fsync(fh.fileno())
        _os.replace(tmp, p)
        return True
    except Exception:
        return False


def _hours_since(ts, now) -> float:
    if not ts:
        return float("inf")
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (now - t).total_seconds() / 3600.0)
    except Exception:
        return float("inf")


def is_insufficient(name: str, state: dict, cfg: dict, now=None) -> bool:
    """Is this variable's action currently burnt?"""
    now = now or datetime.now(timezone.utc)
    rec = (state.get("insufficient") or {}).get(name)
    if not rec:
        return False
    cooldown = float((cfg.get("insufficient") or {}).get("cooldown_hours", 24))
    return _hours_since(rec.get("at"), now) < cooldown


def mark_insufficient(name: str, state: dict, detail: str, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    state.setdefault("insufficient", {})[name] = {
        "at": now.isoformat(),
        "detail": detail,
    }
    return state


def effective_level(name: str, held: str, state: dict, cfg: dict,
                    now=None) -> tuple:
    """(level, why). ACTION becomes GATE when the action is known insufficient.

    This is the escalation the review asked for, and it is mechanical: nothing
    decides to escalate, the level simply IS the gate once the action has been
    shown not to work.
    """
    if held == ACTION and is_insufficient(name, state, cfg, now):
        rec = (state.get("insufficient") or {}).get(name, {})
        return GATE, ("action level reached again while the actuator is marked "
                      "INSUFFICIENT ({}) — escalated to gate".format(
                          str(rec.get("detail"))[:120]))
    return held, ""


# ---------------------------------------------------------------------------
# The whole picture, assembled
# ---------------------------------------------------------------------------

def sample(cfg=None, now=None, sensors=None) -> dict:
    """Read both variables and record the sample. Never raises."""
    now = now or datetime.now(timezone.utc)
    cfg = cfg or load_config()
    sensors = sensors or SENSORS
    out = {}
    for name in cfg["variables"]:
        fn = sensors.get(name)
        if fn is None:
            out[name] = None
            continue
        try:
            out[name] = float(fn())
        except Exception:
            out[name] = None
    return {"ts": now.isoformat(), "epoch": now.timestamp(), "values": out}


def record_sample(reading: dict, state: dict, cfg: dict) -> dict:
    """Keep a bounded history per variable, for the rate and the TTT."""
    window = float((cfg.get("ttt") or {}).get("sample_window_minutes", 60))
    keep_from = reading["epoch"] - window * 60.0
    hist = state.setdefault("history", {})
    for name, value in reading["values"].items():
        if value is None:
            continue
        series = [p for p in hist.get(name, [])
                  if isinstance(p, list) and len(p) == 2 and p[0] >= keep_from]
        series.append([reading["epoch"], value])
        hist[name] = series[-240:]          # ~1 sample/15s over the window
    return state


def evaluate(cfg=None, state=None, now=None, sensors=None) -> dict:
    """The full homeostatic state: level, interoception and escalation, per
    defended variable. Reads sensors; writes nothing."""
    now = now or datetime.now(timezone.utc)
    cfg = cfg or load_config()
    state = state if state is not None else load_state()
    global _TTT_CFG
    _TTT_CFG = dict(cfg.get("ttt") or _TTT_CFG)

    reading = sample(cfg, now, sensors)
    record_sample(reading, state, cfg)

    armed = state.setdefault("armed", {})
    out = {"ts": reading["ts"], "config_sha256": cfg.get("sha256"),
           "variables": {}, "gate": False, "gate_reasons": []}

    for name, spec in cfg["variables"].items():
        value = reading["values"].get(name)
        if value is None:
            out["variables"][name] = {"variable": name, "value": None,
                                      "level": "unknown",
                                      "why": "sensor unreadable"}
            continue
        held = level_for(value, spec, armed.get(name, CLEAR))
        armed[name] = held
        level, why = effective_level(name, held, state, cfg, now)
        info = interoception(name, value, spec, state["history"].get(name, []))
        info.update({
            "level": level,
            "held": held,
            "escalated": level != held,
            "why": why,
            "release_point": (None if level == CLEAR
                              else release_point(spec, level)),
            "insufficient": is_insufficient(name, state, cfg, now),
        })
        out["variables"][name] = info
        if level == GATE:
            out["gate"] = True
            out["gate_reasons"].append(
                "{}={}{} at gate level {} (ttt {}, confidence {}){}".format(
                    name, info["value"], spec.get("unit", ""),
                    spec["levels"][GATE], info["ttt_seconds"],
                    info["ttt_confidence"],
                    " [escalated: " + why + "]" if why else ""))

    out["state"] = state
    return out


# ---------------------------------------------------------------------------
# WITHOUT THIS, EVERYTHING ABOVE IS INERT (23 Aug 2026)
# ---------------------------------------------------------------------------
#
# The rate needs min_samples_for_rate=3 inside a 60-minute window. A sample
# taken only at cycle boot gives ONE sample per night, and consecutive nights
# are hours apart, so the window never holds more than one point. Every rate is
# None, every direction is "unknown", every TTT is None, and
# p_survive_next_cycle is None for ever.
#
# So the sampling has to happen on a cadence the layer can actually measure
# against, and there is already one: the step boundary. fast_cycle_runner.beat()
# fires ~63 times a night, which puts tens of points inside the window and makes
# the rate, the direction and the TTT real numbers instead of placeholders.
#
# Two sensor reads and one small file write per step. FAIL-OPEN and silent: a
# sampler that raises must not cost a step, and a sampler that prints would add
# 63 lines a night to a log that is read by a human.


def tick(now=None, sensors=None, state_path=None) -> dict:
    """Take one sample and keep it. Called from the step boundary. Never raises.

    Returns the reading, or {} when anything at all went wrong.
    """
    try:
        cfg = load_config()
        st = load_state(state_path)
        reading = sample(cfg, now, sensors)
        record_sample(reading, st, cfg)
        save_state(st, state_path)
        return reading
    except Exception:
        return {}
