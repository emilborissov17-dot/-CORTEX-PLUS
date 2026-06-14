#!/usr/bin/env python3
"""
data_providers/civilization/sdg_progress_provider.py
Реални данни за SDG прогрес от Our World in Data API.
"""
import requests, json
from datetime import datetime, timezone

SDG_INDICATORS = {
    "no_poverty":        ("SI.POV.DDAY", "Крайна бедност под $2.15/ден %"),
    "zero_hunger":       ("SN.ITK.DEFC.ZS", "Недохранване %"),
    "good_health":       ("SP.DYN.LE00.IN", "Средна продължителност на живота"),
    "quality_education": ("SE.ADT.LITR.ZS", "Грамотност на възрастни %"),
    "clean_energy":      ("EG.FEC.RNEW.ZS", "Възобновяема енергия %"),
    "climate_action":    ("EN.ATM.CO2E.PC", "CO2 емисии на глава"),
}

def fetch():
    print("[SDG] Извличам SDG данни от World Bank...")
    metrics = {}
    on_track = 0
    total = 0

    for sdg_name, (indicator, label) in SDG_INDICATORS.items():
        try:
            url = f"https://api.worldbank.org/v2/country/WLD/indicator/{indicator}?format=json&mrv=1&per_page=1"
            r = requests.get(url, timeout=15)
            data = r.json()
            value = data[1][0]["value"] if data[1] and data[1][0]["value"] else None
            if value is not None:
                metrics[sdg_name] = round(float(value), 3)
                metrics[f"{sdg_name}_label"] = label
                total += 1
                # Прост on-track критерий
                if sdg_name == "no_poverty" and value < 10:
                    on_track += 1
                elif sdg_name == "clean_energy" and value > 30:
                    on_track += 1
                elif sdg_name == "quality_education" and value > 90:
                    on_track += 1
                elif sdg_name == "good_health" and value > 75:
                    on_track += 1
        except Exception as e:
            print(f"  [SDG] Грешка за {sdg_name}: {e}")

    pct_on_track = round((on_track / total * 100), 1) if total > 0 else 0
    metrics["sdg_on_track_pct"] = pct_on_track
    metrics["sdg_indicators_measured"] = total

    print(f"[SDG] Измерени: {total} индикатора, на курс: {pct_on_track}%")

    return {
        "metrics": metrics,
        "data_mode": "REAL_WORLD_BANK_SDG",
        "fetched_at": datetime.now(timezone.utc).isoformat()
    }

if __name__ == "__main__":
    result = fetch()
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
