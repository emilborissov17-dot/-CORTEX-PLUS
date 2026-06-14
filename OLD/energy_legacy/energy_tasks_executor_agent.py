import re
from pathlib import Path
from datetime import datetime, UTC

from energy_data_sources import (
    download_world_bank_energy_poverty,
    download_basic_entsoe_kpi,
)

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"

TASKS_FILE = KNOWLEDGE_DIR / "energy_tasks_from_gaps.txt"
EXEC_LOG = KNOWLEDGE_DIR / "energy_tasks_executor_log.txt"

TASK_BLOCK_RE = re.compile(
    r"\[AXIS:\s*(?P<axis>[^\]]+)\]\s*"
    r"\[TASK\]:\s*(?P<task>.+?)\s*"
    r"\[WHY\]:\s*(?P<why>.+?)\s*"
    r"\[DATA_NEEDED\]:\s*(?P<data_needed>.+?)\s*"
    r"\[DATA_SOURCES\]:\s*(?P<data_sources>.+?)\s*(?=\[AXIS:|\Z)",
    re.DOTALL | re.IGNORECASE
)


def load_tasks_text() -> str:
    if not TASKS_FILE.exists():
        raise FileNotFoundError(f"{TASKS_FILE} not found")
    return TASKS_FILE.read_text(encoding="utf-8")


def parse_tasks(text: str):
    tasks = []
    for m in TASK_BLOCK_RE.finditer(text):
        tasks.append(
            {
                "axis": m.group("axis").strip(),
                "task": m.group("task").strip(),
                "why": m.group("why").strip(),
                "data_needed": m.group("data_needed").strip(),
                "data_sources": [s.strip() for s in m.group("data_sources").split(",")],
            }
        )
    return tasks


def classify_source(source: str) -> str:
    s = source.lower()
    if "entso-e" in s or "entso" in s:
        return "ENTSOE"
    if "world bank" in s or "energydata.info" in s:
        return "WORLD_BANK"
    if "iea" in s:
        return "IEA"
    if "nrel" in s:
        return "NREL"
    if "eia" in s:
        return "EIA"
    if "tso" in s:
        return "TSO"
    return "OTHER"


def execute_task(task: dict):
    axis = task["axis"]
    title = task["task"]
    data_sources = task["data_sources"]

    lines = []
    lines.append(f"[EXEC] AXIS={axis} TASK={title}")
    lines.append(f"       DATA_SOURCES={'; '.join(data_sources)}")

    for src in data_sources:
        src_type = classify_source(src)
        if src_type == "ENTSOE":
            try:
                path = download_basic_entsoe_kpi()
                lines.append(
                    f"       -> OK: downloaded ENTSO-E basic KPI to '{path}'"
                )
            except Exception as e:
                lines.append(f"       -> ERROR: ENTSO-E download failed for '{src}': {e}")
        elif src_type == "WORLD_BANK":
            path = download_world_bank_energy_poverty()
            lines.append(
                f"       -> OK: downloaded World Bank energy poverty indicators to '{path}'"
            )
        elif src_type == "IEA":
            lines.append(f"       -> TODO: call iea_downloader for '{src}'")
        elif src_type == "NREL":
            lines.append(f"       -> TODO: call nrel_downloader for '{src}'")
        elif src_type == "EIA":
            lines.append(f"       -> TODO: call eia_downloader for '{src}'")
        elif src_type == "TSO":
            lines.append(f"       -> TODO: call tso_downloader for '{src}'")
        else:
            lines.append(f"       -> TODO: manual/web scrape for '{src}'")

    return "\n".join(lines)


def append_log(text: str):
    EXEC_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n=== RUN @ {ts} UTC ===\n"
    with EXEC_LOG.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write(text)
        f.write("\n")


def main():
    print("[ENERGY_TASKS_EXECUTOR] loading tasks...")
    tasks_text = load_tasks_text()

    print("[ENERGY_TASKS_EXECUTOR] parsing tasks...")
    tasks = parse_tasks(tasks_text)
    print(f"[ENERGY_TASKS_EXECUTOR] found {len(tasks)} task blocks")

    all_logs = []
    for t in tasks:
        log_block = execute_task(t)
        all_logs.append(log_block)

    print("[ENERGY_TASKS_EXECUTOR] writing log...")
    append_log("\n".join(all_logs))

    print("[ENERGY_TASKS_EXECUTOR] done.")


if __name__ == "__main__":
    main()
