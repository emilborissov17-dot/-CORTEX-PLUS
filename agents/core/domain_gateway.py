import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"


def load_domains_tree():
    path = CONFIG_DIR / "domains_tree.json"
    if not path.exists():
        print(f"DOMAIN_GATEWAY: няма domains_tree.json в {CONFIG_DIR}")
        return None

    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"DOMAIN_GATEWAY: грешка при парсване на domains_tree.json: {e}")
            return None
    return data


def get_domain_info(tree, domain_id: str):
    domains = tree.get("domains", [])
    for d in domains:
        if d.get("id") == domain_id:
            return d
    return None


def candidates_path_for(domain_id: str) -> Path:
    return BASE_DIR / f"{domain_id}_sources_candidates.json"


def active_path_for(domain_id: str) -> Path:
    return BASE_DIR / f"{domain_id}_sources_active.json"


def load_candidates(path: Path):
    if not path.exists():
        print(f"DOMAIN_GATEWAY: файлът {path} не съществува.")
        return []

    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"DOMAIN_GATEWAY: грешка при парсване на JSON: {e}")
            return []

    if not isinstance(data, list):
        print("DOMAIN_GATEWAY: очаквах списък от кандидати в JSON.")
        return []

    return data


def load_active(path: Path):
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return []

    if not isinstance(data, list):
        return []

    return data


def save_active(path: Path, active_list):
    with path.open("w", encoding="utf-8") as f:
        json.dump(active_list, f, ensure_ascii=False, indent=2)


def save_candidates(path: Path, candidates_list):
    with path.open("w", encoding="utf-8") as f:
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


def run_domain_gateway(domain_id: str):
    print(f"DOMAIN_GATEWAY[{domain_id}]: старт на проверка на източниците...")

    domains_tree = load_domains_tree()
    if domains_tree is None:
        return

    domain_info = get_domain_info(domains_tree, domain_id)
    if domain_info is None:
        print(f"DOMAIN_GATEWAY[{domain_id}]: неизвестен домейн (няма го в domains_tree.json).")
        return

    cand_path = candidates_path_for(domain_id)
    act_path = active_path_for(domain_id)

    candidates = load_candidates(cand_path)
    if not candidates:
        print(f"DOMAIN_GATEWAY[{domain_id}]: няма кандидати за проверка.")
        return

    active = load_active(act_path)
    print(f"DOMAIN_GATEWAY[{domain_id}]: заредени активни източници: {len(active)}")
    print(f"DOMAIN_GATEWAY[{domain_id}]: кандидати за проверка: {len(candidates)}")

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
                "domain": domain_id,
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

    save_active(act_path, active)
    save_candidates(cand_path, candidates)

    print(f"DOMAIN_GATEWAY[{domain_id}]: проверени {checked} кандидата.")
    print(f"DOMAIN_GATEWAY[{domain_id}]: ново добавени активни източници: {new_active}")
    print(f"DOMAIN_GATEWAY[{domain_id}]: записани в {act_path.name}")
    print(f"DOMAIN_GATEWAY[{domain_id}]: обновени кандидати в {cand_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Domain gateway за различни сфери (energy, water, ...).")
    parser.add_argument(
        "--domain",
        required=True,
        help="ID на домейна (например: planet, human, civilization, cosmos или по-конкретен като energy)."
    )
    args = parser.parse_args()
    run_domain_gateway(args.domain)


if __name__ == "__main__":
    main()
