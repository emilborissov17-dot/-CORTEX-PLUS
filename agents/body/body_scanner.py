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
    cpu = _cpu()
    ram = _ram()

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

    # Капацитет (0-100)
    capacity = max(0, 100 - max(ram_pct, cpu_pct * 0.7))

    body = {
        "timestamp": _utc_now(),
        "health": health,
        "capacity_pct": round(capacity, 1),
        "cpu": cpu,
        "ram": ram,
        "disk": _disk(),
        "network": _network(),
        "temperatures": _temps(),
        "processes": _processes(),
        "ollama": _ollama_status(),
        "snapshots_count": _snapshots_count(),
        "uptime": _uptime(),
        "bottleneck": _detect_bottleneck(cpu, ram),
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
    """Записва snapshot на тялото."""
    body = scan()

    out_dir = BASE / "snapshots" / "body"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "body_snapshot_latest.json"
    body["axis"] = "BODY_SCAN"
    body["source_type"] = "BODY_SCANNER"
    out_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[BODY] health={body['health']} | capacity={body['capacity_pct']}% | bottleneck={body['bottleneck']}")
    print(f"[BODY] RAM: {body['ram'].get('available_gb','?')}GB free / {body['ram'].get('total_gb','?')}GB total")
    print(f"[BODY] CPU: {body['cpu'].get('percent','?')}% | temps: {list(body['temperatures'].items())[:3]}")
    print(f"[BODY] Ollama: {body['ollama']}")

    return body

if __name__ == "__main__":
    result = run()
    print("\n── BODY SCAN ──")
    print(json.dumps(result, ensure_ascii=False, indent=2))