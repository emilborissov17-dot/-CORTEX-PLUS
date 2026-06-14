import json
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path("/mnt/c/Users/emilb/Desktop/AGI/CORTEX++")
CONFIG_FILE = BASE_DIR / "materials_sources_active.json"
SNAPSHOT_DIR = BASE_DIR / "knowledge" / "materials_snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def load_active_sources():
    if not CONFIG_FILE.exists():
        print(f"MATERIALS_QUERY: няма файл {CONFIG_FILE}")
        return []

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"MATERIALS_QUERY: грешка при четене на {CONFIG_FILE}: {e}")
        return []

    active = [src for src in data if src.get("status") == "active"]
    print(f"MATERIALS_QUERY: активни източници: {len(active)}")
    return active


def fetch_url(url: str):
    try:
        resp = requests.get(url, timeout=30)
        return resp.status_code, resp.text
    except Exception as e:
        return None, f"[ERROR] {e}"


def main():
    print("MATERIALS_QUERY: старт на заявка към всички активни източници...")

    sources = load_active_sources()
    if not sources:
        print("MATERIALS_QUERY: няма активни източници.")
        return

    summary = {
        "run_at": datetime.utcnow().isoformat(),
        "active_sources": len(sources),
        "ok_sources": 0,
        "failed_sources": 0,
        "sources": [],
    }

    for src in sources:
        name = src.get("name", "UNKNOWN")
        url = src.get("url")
        if not url:
            print(f"- Пропускам {name}: няма URL.")
            continue

        print(f"- Заявка към {name} ({url})...")
        status, body = fetch_url(url)

        safe_name = (
            url.replace("https://", "")
               .replace("http://", "")
               .replace("/", "_")
        )
        out_file = SNAPSHOT_DIR / f"{safe_name}.json"

        entry = {
            "name": name,
            "url": url,
            "file": str(out_file.name),
            "status": status,
        }

        if status is None:
            print(f"  -> грешка при заявката: {body}")
            summary["failed_sources"] += 1
            entry["error"] = body
        else:
            try:
                out_file.write_text(
                    json.dumps(
                        {
                            "fetched_at": datetime.utcnow().isoformat(),
                            "url": url,
                            "status_code": status,
                            "raw_body": body[:50000],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"  -> записано в {out_file.name} (OK {status})")
                if 200 <= status < 300:
                    summary["ok_sources"] += 1
                else:
                    summary["failed_sources"] += 1
            except Exception as e:
                print(f"  -> грешка при запис в {out_file}: {e}")
                summary["failed_sources"] += 1
                entry["error"] = str(e)

        summary["sources"].append(entry)

    summary_path = SNAPSHOT_DIR / "materials_query_summary.json"
    try:
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"MATERIALS_QUERY: обобщение записано в {summary_path}")
    except Exception as e:
        print(f"MATERIALS_QUERY: грешка при запис на summary: {e}")


if __name__ == "__main__":
    main()
