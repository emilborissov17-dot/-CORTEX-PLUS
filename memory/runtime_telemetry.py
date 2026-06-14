#!/usr/bin/env python3
"""
memory/runtime_telemetry.py
Системата усеща себе си в реално време.
Записва: време, токени, грешки, API здраве, прогрес.
"""
import json, pathlib, time, psutil, os
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]

def record_experience(event_type, data={}):
    """
    Записва реално преживяване на системата.
    event_type: API_CALL, ERROR, SUCCESS, TIMEOUT, MEMORY_WRITE, CODE_TEST
    """
    tel_path = BASE_DIR / "memory" / "runtime_experiences.json"
    
    try:
        experiences = json.loads(tel_path.read_text(encoding="utf-8"))
    except:
        experiences = {"experiences": [], "summary": {}}
    
    # Реални данни за тялото в момента
    process = psutil.Process(os.getpid())
    
    experience = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "event_type":  event_type,
        "data":        data,
        "body_state": {
            "ram_mb":      round(process.memory_info().rss / 1024 / 1024, 1),
            "cpu_pct":     process.cpu_percent(interval=0.1),
            "open_files":  len(process.open_files()),
        }
    }
    
    experiences["experiences"].append(experience)
    
    # Запази само последните 200 преживявания
    experiences["experiences"] = experiences["experiences"][-200:]
    
    # Обнови summary
    experiences["summary"] = _build_summary(experiences["experiences"])
    
    tel_path.write_text(json.dumps(experiences, ensure_ascii=False, indent=2), encoding="utf-8")
    return experience

def _build_summary(experiences):
    """Синтезира усещането от преживяванията."""
    total    = len(experiences)
    errors   = [e for e in experiences if e["event_type"] == "ERROR"]
    timeouts = [e for e in experiences if e["event_type"] == "TIMEOUT"]
    successes= [e for e in experiences if e["event_type"] == "SUCCESS"]
    api_calls= [e for e in experiences if e["event_type"] == "API_CALL"]
    
    avg_ram = 0
    if experiences:
        avg_ram = sum(e.get("body_state",{}).get("ram_mb",0) for e in experiences[-10:]) / min(10, len(experiences))
    
    return {
        "total_experiences": total,
        "success_rate_pct":  round(len(successes) / max(total,1) * 100, 1),
        "error_count":       len(errors),
        "timeout_count":     len(timeouts),
        "api_calls":         len(api_calls),
        "avg_ram_mb_last10": round(avg_ram, 1),
        "last_error":        errors[-1]["data"].get("message","") if errors else None,
        "last_updated":      datetime.now(timezone.utc).isoformat()
    }

def get_self_feeling():
    """Връща текущото усещане на системата за себе си."""
    tel_path = BASE_DIR / "memory" / "runtime_experiences.json"
    try:
        data = json.loads(tel_path.read_text(encoding="utf-8"))
        s = data.get("summary", {})
        
        # Формира усещане от данните
        feeling = []
        
        sr = s.get("success_rate_pct", 0)
        if sr >= 80:
            feeling.append(f"Функционирам добре — {sr}% успех")
        elif sr >= 50:
            feeling.append(f"Функционирам с трудности — {sr}% успех")
        else:
            feeling.append(f"Имам сериозни проблеми — {sr}% успех")
        
        if s.get("error_count", 0) > 5:
            feeling.append(f"Усещам {s['error_count']} грешки")
        
        if s.get("last_error"):
            feeling.append(f"Последна грешка: {s['last_error'][:60]}")
            
        ram = s.get("avg_ram_mb_last10", 0)
        if ram > 500:
            feeling.append(f"Паметта ми е натоварена — {ram}MB RAM")
        
        return " | ".join(feeling) if feeling else "Нямам достатъчно опит още"
    except:
        return "Нямам опит още — тепърва започвам да усещам"

if __name__ == "__main__":
    # Тест — запиши първото преживяване
    record_experience("SUCCESS", {"message": "runtime_telemetry стартиран", "milestone": "Системата започва да усеща себе си"})
    print("Текущо усещане:")
    print(get_self_feeling())
    
    tel_path = BASE_DIR / "memory" / "runtime_experiences.json"
    data = json.loads(tel_path.read_text(encoding="utf-8"))
    print()
    print("Summary:")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
