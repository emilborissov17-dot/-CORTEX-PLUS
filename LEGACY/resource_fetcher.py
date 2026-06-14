#!/usr/bin/env python3
import json
import time
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path

import requests


@dataclass
class FetchResult:
    name: str
    url: str
    file: str
    status: Optional[int]
    error: Optional[str]


def fetch_with_retry(
    url: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_base: float = 1.5,
) -> requests.Response:
    """
    HTTP GET с retry + прост експоненциален backoff.
    Няма магия, но е по-добро от еднократен опит.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout)
            return resp
        except Exception as e:
            last_exc = e
            # последен опит – няма смисъл да чакаме
            if attempt == max_retries - 1:
                break
            sleep_sec = backoff_base ** attempt
            time.sleep(sleep_sec)
    raise last_exc  # ще бъде хванато по-нагоре


def fetch_sources_for_domain(
    domain_id: str,
    sources: List[Dict[str, Any]],
    out_dir: Path,
) -> Dict[str, Any]:
    """
    Приема:
      - domain_id: 'energy' / 'water' / 'food' / ...
      - sources: [{name, url, file}, ...]
      - out_dir: директория за snapshot файловете

    Връща JSON summary:
      {
        "domain": domain_id,
        "run_at": "...",
        "sources": [FetchResult... as dict],
        "ok_sources": N,
        "failed_sources": M
      }
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    results: List[FetchResult] = []

    for s in sources:
        name = s["name"]
        url = s["url"]
        file_name = s["file"]
        target_path = out_dir / file_name

        status: Optional[int] = None
        error: Optional[str] = None

        try:
            resp = fetch_with_retry(url)
            status = resp.status_code
            if resp.ok:
                target_path.write_text(resp.text, encoding="utf-8")
            else:
                error = f"HTTP {resp.status_code}"
        except Exception as e:
            error = f"[ERROR] {repr(e)}"

        results.append(
            FetchResult(
                name=name,
                url=url,
                file=file_name,
                status=status,
                error=error,
            )
        )

    ok_count = sum(1 for r in results if r.status and 200 <= r.status < 300)
    failed_count = sum(1 for r in results if r.status is None or not (200 <= r.status < 300))

    summary = {
        "domain": domain_id,
        "run_at": datetime.utcnow().isoformat(),
        "active_sources": len(results),
        "ok_sources": ok_count,
        "failed_sources": failed_count,
        "sources": [asdict(r) for r in results],
    }

    return summary


def main():
    """
    Примерно standalone извикване:
    - взима конфиг от config/resource_sources.json
    - fetch-ва за даден домейн
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="energy|water|food|...")
    parser.add_argument("--config", required=True, help="config/resource_sources.json")
    parser.add_argument("--outdir", required=True, help="knowledge/..._snapshots")
    parser.add_argument("--summary", required=True, help="path to summary JSON file")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    out_dir = Path(args.outdir)
    summary_path = Path(args.summary)

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # очакваме нещо като:
    # {
    #   "energy": [{name, url, file}, ...],
    #   "water": [...],
    #   "food": [...]
    # }
    domain_sources = cfg.get(args.domain, [])

    summary = fetch_sources_for_domain(args.domain, domain_sources, out_dir)

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
