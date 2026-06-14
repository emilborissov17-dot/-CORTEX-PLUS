import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests


BASE_DIR = Path(__file__).resolve().parent
ACTIVE_PATH = BASE_DIR / "energy_sources_active.json"
OUTPUT_DIR = BASE_DIR / "knowledge" / "energy_snapshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_active_sources():
    if not ACTIVE_PATH.exists():
        print(f"ENERGY_QUERY: няма файл {ACTIVE_PATH}")
        return []

    with ACTIVE_PATH.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ENERGY_QUERY: грешка при парсване на active JSON: {e}")
            return []

    if not isinstance(data, list):
        print("ENERGY_QUERY: очаквах списък от активни източници.")
        return []

    return [s for s in data if s.get("status") == "active"]


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "unknown").replace(":", "_")
    path = (parsed.path or "/").strip("/").replace("/", "_")
    if not path:
        path = "root"
    return f"{host}_{path}.json"


def fetch_generic(url: str, timeout: int = 15):
    try:
        resp = requests.get(url, timeout=timeout)
        ct = resp.headers.get("Content-Type", "").lower()

        # ще запишем както raw текст, така и евентуален JSON
        result = {
            "status_code": resp.status_code,
            "content_type": ct,
            "text_sample": resp.text[:5000],
            "fetched_at": datetime.utcnow().isoformat()
        }

        try:
            result["json"] = resp.json()
        except Exception:
            result["json"] = None

        return True, result
    except Exception as e:
        return False, {"error": str(e), "fetched_at": datetime.utcnow().isoformat()}


def main():
    print("ENERGY_QUERY: старт на заявка към всички активни източници...")

    active_sources = load_active_sources()
    print(f"ENERGY_QUERY: активни източници: {len(active_sources)}")

    if not active_sources:
        return

    summary = []
    for src in active_sources:
        name = src.get("name", "UNNAMED")
        url = src.get("url", "").strip()

        if not url:
            print(f"- Пропускане (няма URL): {name}")
            continue

        print(f"- Заявка към {name} ({url})...")
        ok, data = fetch_generic(url)

        filename = safe_filename_from_url(url)
        out_path = OUTPUT_DIR / filename

        snapshot_record = {
            "source_name": name,
            "source_url": url,
            "docs": src.get("docs", ""),
            "notes": src.get("notes", ""),
            "ok": ok,
            "data": data,
        }

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(snapshot_record, f, ensure_ascii=False, indent=2)

        status_desc = f"OK {data.get('status_code')}" if ok else f"FAIL {data.get('error')}"
        print(f"  -> записано в {out_path.name} ({status_desc})")

        summary.append({
            "name": name,
            "url": url,
            "file": out_path.name,
            "ok": ok,
            "status": status_desc,
        })

    summary_path = OUTPUT_DIR / "energy_query_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump({
            "run_at": datetime.utcnow().isoformat(),
            "sources": summary,
        }, f, ensure_ascii=False, indent=2)

    print(f"ENERGY_QUERY: обобщение записано в {summary_path}")


if __name__ == "__main__":
    main()
