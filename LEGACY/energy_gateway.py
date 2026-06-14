import json
import time
from datetime import datetime
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
CANDIDATES_PATH = BASE_DIR / "energy_sources_candidates.json"
ACTIVE_PATH = BASE_DIR / "energy_sources_active.json"


def load_candidates():
    if not CANDIDATES_PATH.exists():
        print(f"ENERGY_GATEWAY: файлът {CANDIDATES_PATH} не съществува.")
        return []

    with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ENERGY_GATEWAY: грешка при парсване на JSON: {e}")
            return []

    if not isinstance(data, list):
        print("ENERGY_GATEWAY: очаквах списък от кандидати в JSON.")
        return []

    return data


def load_active():
    if not ACTIVE_PATH.exists():
        return []

    with ACTIVE_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []

    return data


def save_active(active_list):
    with ACTIVE_PATH.open("w", encoding="utf-8") as f:
        json.dump(active_list, f, ensure_ascii=False, indent=2)


def save_candidates(candidates_list):
    with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
        json.dump(candidates_list, f, ensure_ascii=False, indent=2)


def is_already_active(active_list, candidate):
    c_url = candidate.get("url", "").strip().lower()
    if not c_url:
        return False

    for item in active_list:
        if isinstance(item, dict) and item.get("url", "").strip().lower() == c_url:
            return True
    return False


def test_source(url, timeout=10):
    try:
        response = requests.get(url, timeout=timeout)
        status = response.status_code
        if 200 <= status < 400:
            return True, status
        return False, status
    except Exception as e:
        return False, str(e)


def main():
    print("ENERGY_GATEWAY: старт на проверка на енергийните източници...")

    candidates = load_candidates()
    if not candidates:
        print("ENERGY_GATEWAY: няма кандидати за проверка.")
        return

    active = load_active()
    print(f"ENERGY_GATEWAY: заредени активни източници: {len(active)}")
    print(f"ENERGY_GATEWAY: кандидати за проверка: {len(candidates)}")

    new_active = 0
    checked = 0

    for cand in candidates:
        name = cand.get("name", "UNNAMED")
        url = cand.get("url", "").strip()
        docs = cand.get("docs", "").strip()

        if not url:
            print(f"- Пропускане (липсва URL): {name}")
            cand["status"] = "broken"
            cand["last_checked_status"] = "no_url"
            cand["last_checked_at"] = datetime.utcnow().isoformat()
            continue

        if is_already_active(active, cand):
            print(f"- Вече активен, пропускане: {name} ({url})")
            continue

        print(f"- Тест на {name} ({url})...")
        ok, info = test_source(url)
        checked += 1

        if ok:
            print(f"  -> OK (status: {info})")
            record = {
                "name": name,
                "url": url,
                "docs": docs,
                "notes": cand.get("notes", ""),
                "status": "active",
                "type": cand.get("type", "dataset_or_api"),
                "added_at": datetime.utcnow().isoformat(),
                "last_checked_status": info,
                "last_checked_at": datetime.utcnow().isoformat(),
            }
            active.append(record)
            cand["status"] = "active"
            cand["last_checked_status"] = info
            cand["last_checked_at"] = record["last_checked_at"]
            new_active += 1
        else:
            print(f"  -> FAIL ({info})")
            cand["status"] = "broken"
            cand["last_checked_status"] = info
            cand["last_checked_at"] = datetime.utcnow().isoformat()

        time.sleep(1)

    save_active(active)
    save_candidates(candidates)

    print(f"ENERGY_GATEWAY: проверени {checked} кандидата.")
    print(f"ENERGY_GATEWAY: ново добавени активни източници: {new_active}")
    print(f"ENERGY_GATEWAY: записани в {ACTIVE_PATH.name}")
    print(f"ENERGY_GATEWAY: обновени кандидати в {CANDIDATES_PATH.name}")


if __name__ == "__main__":
    main()
