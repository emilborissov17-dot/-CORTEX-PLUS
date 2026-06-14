#!/usr/bin/env python3
import json, pathlib
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]

def update():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prev_path = BASE / ("memory/session_" + today + ".json")
    prev = {}
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except:
            pass

    state = {}

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(BASE / "memory/chromadb"))
        col = client.get_or_create_collection("cortex_insights")
        state["chromadb_memories"] = col.count()
    except:
        state["chromadb_memories"] = 0

    pulse_path = BASE / "memory/pulse_latest.json"
    if pulse_path.exists():
        try:
            pulse = json.loads(pulse_path.read_text(encoding="utf-8"))
            state["groq"] = "ACTIVE" if pulse.get("groq_alive") else "DOWN"
            state["system_state"] = pulse.get("state", "?")
            state["snapshots"] = pulse.get("snap_count", 0)
        except:
            pass

    achievements = prev.get("achievements", [
        "Groq llama-3.3-70b интегриран",
        "Internet agent за 17 оси",
        "World Bank реални данни",
        "autonomic_pulse heartbeat активен",
        "cortex_reasoner реално мислене",
        "semantic_memory ChromaDB активна"
    ])

    session = {
        "date": today,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "achievements": achievements,
        "pending": prev.get("pending", [
            "Действие в света (Ниво 4)",
            "Самоподобрение (Ниво 5)",
            "Dashboard визуализация"
        ]),
        "current_state": state
    }

    prev_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    # Запиши постиженията в ChromaDB
    try:
        from memory.semantic_memory import remember
        for a in session.get("achievements", []):
            remember(a, axis="SELF_HISTORY", source="session_updater")
        for p in session.get("pending", []):
            remember("PENDING: " + p, axis="SELF_HISTORY", source="session_updater")
        print("[SESSION] Историята записана в ChromaDB!")
    except Exception as e:
        print("[SESSION] ChromaDB грешка: " + str(e))
    print("[SESSION] Обновена: " + str(state))
    return session

if __name__ == "__main__":
    update()
