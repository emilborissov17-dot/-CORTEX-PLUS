#!/usr/bin/env python3
"""
youtube_worker.py — Асинхронен YouTube daemon за CORTEX++

Върви НЕЗАВИСИМО от основния цикъл.
Транскрибира видеа за всички оси и записва в youtube_cache.json.
web_intelligence_agent.py чете от кеша — без блокиране.

Стартирай:
    python3 youtube_worker.py &

Или добави в fast_cycle_runner.py:
    import subprocess
    subprocess.Popen(["python3", "youtube_worker.py"])
"""

import json
import os
import time
import pathlib
import hashlib
from datetime import datetime, timezone

# ── Конфигурация ──────────────────────────────────────────────────────────────

CACHE_FILE        = pathlib.Path("memory/youtube_cache.json")
CACHE_TTL_HOURS   = 6          # колко часа е валиден един транскрипт
CYCLE_SLEEP_SEC   = 300        # 5 мин между пълни цикли
AXIS_SLEEP_SEC    = 10         # пауза между оси (не задръства мрежата)
MAX_VIDEOS        = 1          # видеа на ос
AXES_PER_CYCLE    = 5          # оси на цикъл (не всички наведнъж)

# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def is_fresh(entry: dict) -> bool:
    ts = entry.get("fetched_at", "")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
        age_h = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        return age_h < CACHE_TTL_HOURS
    except Exception:
        return False


# ── Основен worker ────────────────────────────────────────────────────────────

def run():
    print(f"[YT_WORKER] Стартиран в {datetime.now(timezone.utc).isoformat()}")
    print(f"[YT_WORKER] Cache: {CACHE_FILE} | TTL: {CACHE_TTL_HOURS}h | Цикъл: {CYCLE_SLEEP_SEC}s")

    try:
        from youtube_intel import fetch_youtube_for_axis, AXIS_YOUTUBE_QUERIES
    except ImportError as e:
        print(f"[YT_WORKER] ГРЕШКА: {e}")
        return

    all_axes = list(AXIS_YOUTUBE_QUERIES.keys())
    axis_index = 0

    while True:
        cache = load_cache()

        # Вземи следващите AXES_PER_CYCLE оси (rolling)
        batch = []
        checked = 0
        while len(batch) < AXES_PER_CYCLE and checked < len(all_axes):
            axis = all_axes[axis_index % len(all_axes)]
            axis_index += 1
            checked += 1
            entry = cache.get(axis, {})
            if not is_fresh(entry):
                batch.append(axis)

        if not batch:
            print(f"[YT_WORKER] Всички оси са пресни. Спя {CYCLE_SLEEP_SEC}s...")
            time.sleep(CYCLE_SLEEP_SEC)
            continue

        print(f"[YT_WORKER] Обработвам {len(batch)} оси: {batch}")

        for axis in batch:
            print(f"[YT_WORKER] → {axis}")
            try:
                config = {"keywords": axis.lower().replace("_review", "").split("_")}
                items = fetch_youtube_for_axis(axis, config, max_videos=MAX_VIDEOS)

                cache[axis] = {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "items": items,
                    "count": len(items),
                    "transcribed": sum(1 for i in items if i.get("has_full_transcript")),
                }
                save_cache(cache)
                print(f"[YT_WORKER] ✅ {axis}: {len(items)} видеа записани в кеша")

            except Exception as e:
                print(f"[YT_WORKER] ⚠️ {axis} грешка: {e}")
                cache[axis] = {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "items": [],
                    "count": 0,
                    "error": str(e),
                }
                save_cache(cache)

            time.sleep(AXIS_SLEEP_SEC)

        print(f"[YT_WORKER] Batch завършен. Спя {CYCLE_SLEEP_SEC}s...")
        time.sleep(CYCLE_SLEEP_SEC)


if __name__ == "__main__":
    run()