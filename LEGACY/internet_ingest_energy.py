#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(r"C:\Users\emilb\Desktop\AGI\CORTEX++")
SNAP_DIR = BASE_DIR / "knowledge" / "internet_snapshots" / "ENERGY_REVIEW"
SNAP_FILE = SNAP_DIR / "TASK_001_snapshot.json"

OUT_DIR = BASE_DIR / "knowledge" / "internet_ingested"
OUT_FILE = OUT_DIR / "internet_context_energy.txt"


def main():
    if not SNAP_FILE.exists():
        print(f"[INET_INGEST] Липсва snapshot файл: {SNAP_FILE}")
        return

    try:
        data = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[INET_INGEST] Грешка при парсване на JSON: {e}")
        return

    summary = data.get("summary_bg", "")
    key_findings = data.get("key_findings_bg", []) or []
    proposed_actions = data.get("proposed_actions", []) or []

    lines = []
    lines.append("=== INTERNET CONTEXT: ENERGY_REVIEW / TASK_001 ===")
    lines.append(f"INGEST_TIMESTAMP_UTC: {datetime.utcnow().isoformat()}")
    lines.append("")

    if summary:
        lines.append("SUMMARY_BG:")
        lines.append(summary)
        lines.append("")

    if key_findings:
        lines.append("KEY_FINDINGS_BG:")
        for k in key_findings:
            lines.append(f"- {k}")
        lines.append("")

    if proposed_actions:
        lines.append("PROPOSED_ACTIONS:")
        for a in proposed_actions:
            aid = a.get("id", "")
            level = a.get("level", "")
            actor = a.get("actor", "")
            horizon = a.get("time_horizon", "")
            desc = a.get("description_bg", "")
            effect = a.get("expected_effect_bg", "")
            lines.append(f"- ID: {aid}")
            lines.append(f"  LEVEL: {level}")
            lines.append(f"  ACTOR: {actor}")
            lines.append(f"  TIME_HORIZON: {horizon}")
            lines.append(f"  DESCRIPTION_BG: {desc}")
            lines.append(f"  EXPECTED_EFFECT_BG: {effect}")
            lines.append("")
    text = "\n".join(lines)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(text, encoding="utf-8")

    print(f"[INET_INGEST] Записан е интернет контекст за ENERGY в {OUT_FILE}")


if __name__ == "__main__":
    main()
