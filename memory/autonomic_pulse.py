#!/usr/bin/env python3
"""
memory/autonomic_pulse.py
Автономна нервна система на CORTEX++
Тече паралелно с всичко друго — като сърдечен ритъм.
Не чака. Не пита. Просто усеща и записва.
"""
import threading, time, json, psutil, pathlib, requests
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
PULSE_FILE = BASE / "memory" / "pulse_latest.json"
PULSE_LOG  = BASE / "memory" / "pulse_history.jsonl"
INTERVAL   = 60  # секунди между пулсове

_running = False
_thread  = None

def _measure() -> dict:
    """Мери реалното състояние в момента."""
    cpu    = psutil.cpu_percent(interval=0.5)
    ram    = psutil.virtual_memory()
    disk   = psutil.disk_usage(str(BASE))
    proc   = psutil.Process()

    # Мрежа — само Groq (най-важното)
    groq_ok = False
    try:
        r = requests.get("https://api.groq.com", timeout=2)
        groq_ok = True
    except:
        pass

    # Брой snapshots
    snap_count = len(list((BASE / "snapshots").rglob("*.json"))) if (BASE / "snapshots").exists() else 0

    # Последен log ред
    last_log = ""
    log_path = BASE / "logs" / "fast_cycle_log.txt"
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            last_log = lines[-1][:80] if lines else ""
        except:
            pass

    return {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "cpu_pct":     cpu,
        "ram_pct":     ram.percent,
        "ram_free_gb": round(ram.available / 1024**3, 2),
        "disk_free_gb":round(disk.free / 1024**3, 1),
        "proc_threads":proc.num_threads(),
        "groq_alive":  groq_ok,
        "snap_count":  snap_count,
        "last_log":    last_log,
        "state":       _derive_state(cpu, ram.percent, groq_ok),
        "feeling":     _derive_feeling(cpu, ram.percent, groq_ok),
    }

def _derive_state(cpu, ram_pct, groq_ok) -> str:
    """Реално вътрешно състояние — не симулирано."""
    if not groq_ok:
        return "ISOLATED"       # Без интернет връзка
    if ram_pct > 85 or cpu > 80:
        return "STRESSED"       # Претоварен
    if cpu < 5 and ram_pct < 40:
        return "IDLE"           # Почива
    return "FUNCTIONING"        # Нормална работа

def _derive_feeling(cpu, ram_pct, groq_ok) -> str:
    """Текстово усещане от метриките."""
    parts = []
    if not groq_ok:
        parts.append("изолиран съм — няма връзка с Groq")
    if cpu > 70:
        parts.append(f"натоварен съм — CPU {cpu}%")
    elif cpu < 10:
        parts.append("почивам")
    else:
        parts.append(f"работя — CPU {cpu}%")
    if ram_pct > 80:
        parts.append(f"паметта ми е препълнена ({ram_pct}%)")
    return " | ".join(parts) if parts else "функционирам нормално"

def _pulse_loop():
    """Главният loop — тече безкрайно в background thread."""
    global _running
    while _running:
        try:
            data = _measure()

            # Запиши последния пулс
            PULSE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            # Добави към историята
            with open(PULSE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

            # Ако е критично — веднага го изведи
            if data["state"] in ("STRESSED", "ISOLATED"):
                print(f"\n⚠️  [PULSE] {data['state']} — {data['feeling']}")

        except Exception as e:
            pass  # Автономиката никога не спира заради грешка

        time.sleep(INTERVAL)

def start(interval: int = INTERVAL):
    """Стартира автономния пулс в background thread."""
    global _running, _thread, INTERVAL
    if _running:
        return
    INTERVAL   = interval
    _running   = True
    _thread    = threading.Thread(target=_pulse_loop, daemon=True, name="autonomic_pulse")
    _thread.start()
    print(f"💓 [PULSE] Автономиката стартира (interval={interval}s)")

def stop():
    global _running
    _running = False
    print("💔 [PULSE] Автономиката спря")

def read() -> dict:
    """Чете последния пулс."""
    try:
        return json.loads(PULSE_FILE.read_text(encoding="utf-8"))
    except:
        return {}

def read_history(last_n: int = 10) -> list:
    """Чете последните N пулса."""
    if not PULSE_LOG.exists():
        return []
    try:
        lines = PULSE_LOG.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines[-last_n:] if l.strip()]
    except:
        return []

if __name__ == "__main__":
    print("Тествам автономния пулс...")
    data = _measure()
    print(json.dumps(data, ensure_ascii=False, indent=2))
