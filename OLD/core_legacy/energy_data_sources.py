import json
import os
from datetime import datetime, timedelta, UTC
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
RAW_DATA_DIR = ROOT / "raw_data"

# ===================== WORLD BANK =====================

WB_DIR = RAW_DATA_DIR / "world_bank"


def fetch_world_bank_indicator(indicator: str, country: str = "WLD", per_page: int = 2000):
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    params = {"format": "json", "per_page": per_page}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def save_world_bank_json(data, name: str):
    WB_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = WB_DIR / f"{name}_{ts}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def download_world_bank_energy_poverty():
    # Примерен сет индикатори за енергийна бедност / достъп до енергия. [web:414]
    indicators = {
        "access_to_electricity": "EG.ELC.ACCS.ZS",
        "renewable_energy_share": "EG.FEC.RNEW.ZS",
    }
    results = {}
    for key, code in indicators.items():
        data = fetch_world_bank_indicator(code, country="WLD")
        results[key] = data

    path = save_world_bank_json(results, "energy_poverty_global")
    return path


# ===================== ENTSO-E (placeholder, докато нямаш ключ) =====================

ENTSOE_DIR = RAW_DATA_DIR / "entsoe"
ENTSOE_API_KEY = os.environ.get("ENTSOE_API_KEY", "")


def download_basic_entsoe_kpi():
    if not ENTSOE_API_KEY:
        raise RuntimeError("ENTSOE_API_KEY not set; cannot call ENTSO-E API yet")
    # Тук ще влезе реалният ENTSO-E Web API call, когато имаш ключ.
    raise RuntimeError("ENTSO-E downloader not implemented yet")
