#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/body/body_scanner.py

Телесното сетиво на CORTEX++ — чете всички жизнени показатели
в реално време и ги превежда в структуриран JSON.
"""
from __future__ import annotations
import json, pathlib, subprocess, time
from datetime import datetime, timezone

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

BASE = pathlib.Path(__file__).resolve().parent.parent.parent

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _cpu():
    if HAS_PSUTIL:
        return {
            "percent": psutil.cpu_percent(interval=1),
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "freq_mhz": round(psutil.cpu_freq().current, 1) if psutil.cpu_freq() else None,
            "load_avg_1m": round(psutil.getloadavg()[0], 2),
        }
    # fallback
    try:
        with open("/proc/loadavg") as f:
            load = float(f.read().split()[0])
        return {"load_avg_1m": load}
    except Exception:
        return {}

def _ram():
    if HAS_PSUTIL:
        m = psutil.virtual_memory()
        s = psutil.swap_memory()
        return {
            "total_gb": round(m.total / 1e9, 2),
            "available_gb": round(m.available / 1e9, 2),
            "used_gb": round(m.used / 1e9, 2),
            "percent": m.percent,
            "swap_used_gb": round(s.used / 1e9, 2),
            "swap_percent": s.percent,
        }
    try:
        lines = open("/proc/meminfo").readlines()
        d = {l.split(":")[0]: int(l.split()[1]) for l in lines if ":" in l}
        total = d.get("MemTotal", 0)
        free = d.get("MemAvailable", 0)
        return {
            "total_gb": round(total / 1e6, 2),
            "available_gb": round(free / 1e6, 2),
            "percent": round((total - free) / total * 100, 1) if total else 0,
        }
    except Exception:
        return {}

def _disk():
    if HAS_PSUTIL:
        d = psutil.disk_usage("/")
        io = psutil.disk_io_counters()
        return {
            "total_gb": round(d.total / 1e9, 2),
            "free_gb": round(d.free / 1e9, 2),
            "percent": d.percent,
            "read_mb": round(io.read_bytes / 1e6, 1) if io else None,
            "write_mb": round(io.write_bytes / 1e6, 1) if io else None,
        }
    try:
        r = subprocess.run(["df", "-BG", "/"], capture_output=True, text=True)
        parts = r.stdout.splitlines()[1].split()
        return {
            "total_gb": int(parts[1].replace("G","")),
            "free_gb": int(parts[3].replace("G","")),
            "percent": int(parts[4].replace("%","")),
        }
    except Exception:
        return {}

def _network():
    if HAS_PSUTIL:
        n = psutil.net_io_counters()
        return {
            "bytes_sent_mb": round(n.bytes_sent / 1e6, 1),
            "bytes_recv_mb": round(n.bytes_recv / 1e6, 1),
            "connections": len(psutil.net_connections()),
        }
    return {}

def _temps():
    temps = {}
    # /sys/class/thermal
    thermal_dir = pathlib.Path("/sys/class/thermal")
    if thermal_dir.exists():
        for zone in sorted(thermal_dir.iterdir()):
            temp_file = zone / "temp"
            type_file = zone / "type"
            if temp_file.exists():
                try:
                    val = int(temp_file.read_text().strip()) / 1000
                    zone_type = type_file.read_text().strip() if type_file.exists() else zone.name
                    if val > 0:
                        temps[zone_type] = round(val, 1)
                except Exception:
                    pass
    # psutil fallback
    if not temps and HAS_PSUTIL:
        try:
            for name, entries in psutil.sensors_temperatures().items():
                for e in entries:
                    if e.current > 0:
                        temps[f"{name}_{e.label or 'core'}"] = round(e.current, 1)
        except Exception:
            pass
    return temps

def _processes():
    if HAS_PSUTIL:
        procs = list(psutil.process_iter(['name', 'cpu_percent', 'memory_percent']))
        top = sorted(procs, key=lambda p: p.info.get('cpu_percent', 0) or 0, reverse=True)[:5]
        return {
            "total": len(procs),
            "top_cpu": [{"name": p.info['name'], "cpu_pct": p.info.get('cpu_percent', 0)} for p in top],
        }
    try:
        r = subprocess.run(["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True)
        lines = r.stdout.splitlines()[1:6]
        return {"top_cpu": [{"name": l.split()[10], "cpu_pct": float(l.split()[2])} for l in lines]}
    except Exception:
        return {}

def _network_latency() -> dict:
    """Ping key external servers — measure connectivity health."""
    import socket, time as _time
    targets = {
        "groq_api":   ("api.groq.com",       443),
        "google_dns":  ("8.8.8.8",            53),
        "worldbank":   ("api.worldbank.org",  443),
        "noaa":        ("gml.noaa.gov",       443),
    }
    results = {}
    for name, (host, port) in targets.items():
        try:
            t0 = _time.monotonic()
            with socket.create_connection((host, port), timeout=4):
                pass
            results[name] = round((_time.monotonic() - t0) * 1000, 1)  # ms
        except Exception:
            results[name] = None
    reachable = sum(1 for v in results.values() if v is not None)
    results["reachable_count"] = reachable
    results["connectivity"] = (
        "FULL" if reachable == len(targets) else
        "PARTIAL" if reachable > 0 else "OFFLINE"
    )
    return results


def _battery() -> dict:
    """Battery state — relevant for laptops running the cycle on battery."""
    if not HAS_PSUTIL:
        return {}
    try:
        b = psutil.sensors_battery()
        if b is None:
            return {"present": False}
        return {
            "present":    True,
            "percent":    round(b.percent, 1),
            "plugged_in": b.power_plugged,
            "secs_left":  b.secsleft if b.secsleft != psutil.POWER_TIME_UNKNOWN else None,
        }
    except Exception:
        return {}


def _time_context() -> dict:
    """Time-of-day and seasonal context — affects optimal cycle intensity."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    month = now.month
    time_of_day = (
        "NIGHT"   if hour < 6  else
        "MORNING" if hour < 12 else
        "MIDDAY"  if hour < 14 else
        "AFTERNOON" if hour < 18 else
        "EVENING" if hour < 22 else "NIGHT"
    )
    season = (
        "WINTER" if month in (12, 1, 2) else
        "SPRING" if month in (3, 4, 5) else
        "SUMMER" if month in (6, 7, 8) else "AUTUMN"
    )
    return {
        "utc_hour":    hour,
        "utc_weekday": now.strftime("%A"),
        "time_of_day": time_of_day,
        "season":      season,
        "iso_date":    now.strftime("%Y-%m-%d"),
    }


def _data_freshness() -> dict:
    """How stale is the system's knowledge — in hours since last snapshots."""
    from datetime import timezone as _tz
    import json as _json
    results = {}
    checks = {
        "global_indicators": BASE / "snapshots" / "master" / "global_indicators_latest.json",
        "master_snapshot":   BASE / "snapshots" / "master" / "master_snapshot_latest.json",
        "goal_score":        BASE / "snapshots" / "master" / "goal_score_latest.json",
        "orchestration":     BASE / "memory" / "orchestration_latest.json",
    }
    now = datetime.now(timezone.utc)
    for name, path in checks.items():
        if not path.exists():
            results[name] = None
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=_tz.utc)
            age_h = round((now - mtime).total_seconds() / 3600, 1)
            results[name] = age_h
        except Exception:
            results[name] = None
    oldest = max((v for v in results.values() if v is not None), default=None)
    results["oldest_hours"] = oldest
    results["freshness"] = (
        "FRESH"   if oldest is not None and oldest < 2  else
        "RECENT"  if oldest is not None and oldest < 12 else
        "STALE"   if oldest is not None and oldest < 48 else "VERY_STALE"
    )
    return results


def _derive_directives(cpu: dict, ram: dict, disk: dict,
                        net: dict, battery: dict) -> dict:
    """
    Translate raw vitals into concrete adaptive instructions
    that fast_cycle_runner can apply immediately.
    """
    cpu_pct  = cpu.get("percent", 0) or 0
    ram_pct  = ram.get("percent", 0) or 0
    disk_free = disk.get("free_gb", 100) or 100
    bat_pct  = battery.get("percent", 100) or 100
    plugged  = battery.get("plugged_in", True)
    offline  = net.get("connectivity") == "OFFLINE"

    directives = {}
    reasons    = []

    # ── Parallelism ──────────────────────────────────────────────────────
    if cpu_pct > 85 or ram_pct > 85:
        directives["max_parallel_workers"] = 1
        reasons.append(f"CPU={cpu_pct:.0f}%/RAM={ram_pct:.0f}% critical → single-worker")
    elif cpu_pct > 70 or ram_pct > 70:
        directives["max_parallel_workers"] = 2
        reasons.append(f"CPU={cpu_pct:.0f}%/RAM={ram_pct:.0f}% high → 2 workers")
    else:
        directives["max_parallel_workers"] = 3

    # ── LLM call pacing ──────────────────────────────────────────────────
    if ram_pct > 80 or cpu_pct > 80:
        directives["llm_sleep_secs"] = 4
        reasons.append("High load → slow LLM pacing to 4s")
    elif ram_pct > 65 or cpu_pct > 65:
        directives["llm_sleep_secs"] = 3
        reasons.append("Moderate load → LLM pacing 3s")
    else:
        directives["llm_sleep_secs"] = 2

    # ── Disk ─────────────────────────────────────────────────────────────
    if disk_free < 2:
        directives["skip_heavy_writes"] = True
        directives["cleanup_required"]  = True
        reasons.append(f"Disk critical: {disk_free:.1f}GB free")
    elif disk_free < 10:
        directives["cleanup_required"] = True
        reasons.append(f"Disk low: {disk_free:.1f}GB free")

    # ── Battery ──────────────────────────────────────────────────────────
    if not plugged and bat_pct < 20:
        directives["cycle_mode"] = "MINIMAL"
        reasons.append(f"Battery {bat_pct:.0f}% unplugged → minimal cycle")
    elif not plugged and bat_pct < 40:
        directives["cycle_mode"] = "REDUCED"
        reasons.append(f"Battery {bat_pct:.0f}% unplugged → reduced cycle")

    # ── Connectivity ─────────────────────────────────────────────────────
    if offline:
        directives["skip_web_intel"] = True
        directives["skip_llm_calls"] = True
        reasons.append("No connectivity → offline mode")

    # ── Overall health verdict ───────────────────────────────────────────
    if "cycle_mode" not in directives:
        if cpu_pct > 85 or ram_pct > 85:
            directives["cycle_mode"] = "MINIMAL"
        elif cpu_pct > 70 or ram_pct > 70:
            directives["cycle_mode"] = "REDUCED"
        else:
            directives["cycle_mode"] = "FULL"

    directives["reasons"] = reasons
    return directives


def _ollama_status():
    """Проверява Groq/Gemini API конфигурация (Ollama заменен с cloud backends)."""
    import os
    from pathlib import Path as _P
    def _key(name):
        k = os.environ.get(name, "")
        if not k:
            env = BASE / ".env"
            if env.exists():
                for line in env.read_text(encoding="utf-8").splitlines():
                    if line.startswith(name + "="):
                        k = line.split("=", 1)[1].strip()
        return k
    groq_ok   = bool(_key("GROQ_API_KEY"))
    gemini_ok = bool(_key("GEMINI_API_KEY"))
    backends  = [b for b, ok in [("groq", groq_ok), ("gemini", gemini_ok)] if ok]
    return {
        "running": groq_ok or gemini_ok,
        "backend": "groq+gemini" if (groq_ok and gemini_ok) else (backends[0] if backends else "none"),
        "loaded_models": backends,
    }

def _snapshots_count():
    snap_dir = BASE / "snapshots"
    if snap_dir.exists():
        return len(list(snap_dir.rglob("*.json")))
    return 0

def _uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        return f"{h}h {m}m"
    except Exception:
        return "unknown"

def scan() -> dict:
    """Пълно сканиране на тялото."""
    cpu  = _cpu()
    ram  = _ram()
    disk = _disk()
    net  = _network_latency()
    bat  = _battery()

    # Определи здравния статус
    ram_pct = ram.get("percent", 0)
    cpu_pct = cpu.get("percent", 0)

    if ram_pct > 90 or cpu_pct > 90:
        health = "CRITICAL"
    elif ram_pct > 75 or cpu_pct > 70:
        health = "STRESSED"
    elif ram_pct > 50 or cpu_pct > 40:
        health = "MODERATE"
    else:
        health = "HEALTHY"

    capacity = max(0, 100 - max(ram_pct, cpu_pct * 0.7))

    directives = _derive_directives(cpu, ram, disk, net, bat)

    body = {
        "timestamp":        _utc_now(),
        "health":           health,
        "capacity_pct":     round(capacity, 1),
        "cpu":              cpu,
        "ram":              ram,
        "disk":             disk,
        "network_hw":       _network(),
        "network_latency":  net,
        "temperatures":     _temps(),
        "battery":          bat,
        "time_context":     _time_context(),
        "data_freshness":   _data_freshness(),
        "processes":        _processes(),
        "llm_backends":     _ollama_status(),
        "snapshots_count":  _snapshots_count(),
        "uptime":           _uptime(),
        "bottleneck":       _detect_bottleneck(cpu, ram),
        "adaptive_directives": directives,
    }

    return body

def _detect_bottleneck(cpu: dict, ram: dict) -> str:
    ram_pct = ram.get("percent", 0)
    cpu_pct = cpu.get("percent", 0)
    swap = ram.get("swap_percent", 0)

    if swap > 50:
        return "SWAP — RAM изчерпана, системата е в swap"
    if ram_pct > 85:
        return "RAM — критично малко свободна памет"
    if cpu_pct > 80:
        return "CPU — процесорът е претоварен"
    if ram_pct > 60:
        return "RAM — ограничен капацитет за паралелни задачи"
    return "NONE"

def run():
    """Записва snapshot + adaptive_directives за fast_cycle_runner."""
    body = scan()

    # Snapshot (пълен)
    out_dir = BASE / "snapshots" / "body"
    out_dir.mkdir(parents=True, exist_ok=True)
    body["axis"]        = "BODY_SCAN"
    body["source_type"] = "BODY_SCANNER"
    (out_dir / "body_snapshot_latest.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Adaptive directives — compact file, read by fast_cycle_runner at Step 0
    directives_path = BASE / "memory" / "adaptive_directives.json"
    directives_path.parent.mkdir(parents=True, exist_ok=True)
    directives_path.write_text(
        json.dumps({
            **body["adaptive_directives"],
            "health":          body["health"],
            "capacity_pct":    body["capacity_pct"],
            "connectivity":    body["network_latency"].get("connectivity"),
            "cycle_timestamp": body["timestamp"],
            "data_freshness":  body["data_freshness"].get("freshness"),
            "time_of_day":     body["time_context"].get("time_of_day"),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    d = body["adaptive_directives"]
    nl = body["network_latency"]
    tc = body["time_context"]
    print(f"[BODY] health={body['health']} | capacity={body['capacity_pct']}% | mode={d.get('cycle_mode')}")
    print(f"[BODY] CPU={body['cpu'].get('percent','?')}% | RAM={body['ram'].get('percent','?')}% | disk_free={body['disk'].get('free_gb','?')}GB")
    print(f"[BODY] net={nl.get('connectivity')} | groq_latency={nl.get('groq_api')}ms | time={tc.get('time_of_day')}")
    print(f"[BODY] directives: workers={d.get('max_parallel_workers')} | llm_sleep={d.get('llm_sleep_secs')}s")
    if d.get("reasons"):
        for r in d["reasons"]:
            print(f"[BODY]   ↳ {r}")

    return body

if __name__ == "__main__":
    result = run()
    print("\n── BODY SCAN ──")
    print(json.dumps(result, ensure_ascii=False, indent=2))