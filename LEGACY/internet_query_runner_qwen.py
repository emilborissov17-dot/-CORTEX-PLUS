import re
import json
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"
QUERIES_FILE = Path(BASE_DIR) / "internet_queries.txt"


def call_qwen(prompt: str, model: str = "qwen3:8b") -> str:
    result = subprocess.run(
        ["ollama", "run", model],
        input=prompt,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ollama returned code {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout


def read_query_cards() -> list[str]:
    if not QUERIES_FILE.exists():
        print(f"[QWEN RUNNER] Няма {QUERIES_FILE}")
        return []

    text = QUERIES_FILE.read_text(encoding="utf-8")
    blocks = text.split("=== INTERNET QUERY CARD START ===")
    cards = []
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        cards.append("=== INTERNET QUERY CARD START ===\n" + b)

    print(f"[QWEN RUNNER] Намерени са {len(cards)} INTERNET QUERY CARD блока.")
    return cards


def parse_meta_from_card(card: str) -> dict:
    axis = None
    task_id = None
    suggested_path = None
    query_lines = []
    in_query = False
    pending_path = False

    for line in card.splitlines():
        s = line.rstrip()

        if s.startswith("AXIS_NAME:"):
            axis = s.split(":", 1)[1].strip()
        elif s.startswith("TASK_ID:"):
            task_id = s.split(":", 1)[1].strip()
        elif s.strip().startswith("SUGGESTED_OUTPUT_PATH"):
            pending_path = True
            continue
        elif pending_path:
            suggested_path = s.strip()
            pending_path = False
        elif s.strip().startswith("QUERY_FOR_EXTERNAL_AGENT_BG:"):
            in_query = True
            continue
        elif in_query:
            query_lines.append(line)

    query_text = "\n".join(query_lines).strip()

    if not axis or not task_id or not suggested_path or not query_text:
        raise ValueError(
            f"Липсват ключови полета в CARD (axis={axis}, task_id={task_id}, "
            f"path={suggested_path}, query_len={len(query_text)})"
        )

    return {
        "axis": axis,
        "task_id": task_id,
        "suggested_path": suggested_path,
        "query_text": query_text,
    }


def extract_json_block(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Не е намерен JSON обект в изхода на модела")
    return raw[start : end + 1]


def clean_json_text(txt: str) -> str:
    txt = txt.replace("TACT,003", "TACTIC-003")
    txt = re.sub(r"\n\s+", " ", txt)
    return txt


def parse_model_json(raw: str) -> dict:
    jtxt = extract_json_block(raw)
    jtxt = clean_json_text(jtxt)
    data = json.loads(jtxt)
    return data


def save_snapshot(meta: dict, data: dict):
    suggested_path = Path(meta["suggested_path"])
    out_dir = suggested_path.parent
    task_id = meta["task_id"]

    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob(f"{task_id}_snapshot_v*.json"))
    versions = []
    for p in existing:
        m = re.search(r"_v(\d+)\.json$", p.name)
        if m:
            versions.append(int(m.group(1)))
    next_v = (max(versions) + 1) if versions else 1

    v_path = out_dir / f"{task_id}_snapshot_v{next_v}.json"
    latest_path = out_dir / f"{task_id}_snapshot_latest.json"

    serialized = json.dumps(data, ensure_ascii=False, indent=2)

    v_path.write_text(serialized, encoding="utf-8")
    latest_path.write_text(serialized, encoding="utf-8")

    print(f"[QWEN RUNNER] Записан е snapshot {v_path}")
    print(f"[QWEN RUNNER] Обновен е latest {latest_path}")


def main():
    cards = read_query_cards()
    if not cards:
        return

    for idx, card in enumerate(cards, start=1):
        print(f"[QWEN RUNNER] Обработка на CARD #{idx}")
        try:
            meta = parse_meta_from_card(card)
        except Exception as e:
            print(f"[QWEN RUNNER] Пропускам CARD #{idx} (грешка при парсване на мета): {e}")
            continue

        print(
            f"[QWEN RUNNER] AXIS={meta['axis']} TASK_ID={meta['task_id']} "
            f"OUT={meta['suggested_path']}"
        )

        try:
            raw_output = call_qwen(meta["query_text"])
        except Exception as e:
            print(f"[QWEN RUNNER] Грешка при извикване на Qwen за CARD #{idx}: {e}")
            continue

        try:
            data = parse_model_json(raw_output)
        except Exception as e:
            print(f"[QWEN RUNNER] Грешка при парсване на JSON за CARD #{idx}: {e}")
            debug_dir = Path(BASE_DIR) / "logs" / "qwen_raw"
            debug_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dbg_path = debug_dir / f"qwen_raw_CARD{idx}_{ts}.txt"
            dbg_path.write_text(raw_output, encoding="utf-8")
            print(f"[QWEN RUNNER] Суровият отговор е записан в {dbg_path}")
            continue

        try:
            save_snapshot(meta, data)
        except Exception as e:
            print(f"[QWEN RUNNER] Грешка при запис на snapshot за CARD #{idx}: {e}")
            continue


if __name__ == "__main__":
    main()
