import os
from pathlib import Path
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"
LOGS_DIR = Path(BASE_DIR) / "logs"
EXECUTOR_LOG = LOGS_DIR / "AXIS_TASK_EXECUTOR_LOG.txt"


def find_latest_session_log() -> Path | None:
    if not LOGS_DIR.exists():
        print(f"[EXECUTOR] Няма logs/ директория: {LOGS_DIR}")
        return None

    session_logs = sorted(
        p for p in LOGS_DIR.iterdir()
        if p.is_file() and p.name.startswith("SESSION_") and p.name.endswith("_LOG.txt")
    )
    if not session_logs:
        print("[EXECUTOR] Няма SESSION_..._LOG.txt файлове в logs/.")
        return None

    return session_logs[-1]


def parse_task_candidates(log_path: Path) -> list[dict]:
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[EXECUTOR] Грешка при четене на {log_path}: {e}")
        return []

    lines = text.splitlines()
    in_plan = False
    in_tasks = False
    tasks = []
    current = {}

    for line in lines:
        s = line.rstrip()

        if s.strip().startswith("PLAN:"):
            in_plan = True
            in_tasks = False
            continue

        if in_plan and s.strip().startswith("NO_TASK_CANDIDATES_FOUND"):
            print("[EXECUTOR] Няма TASK_CANDIDATES в този SESSION лог.")
            return []

        if in_plan and s.strip().startswith("TASK_CANDIDATES:"):
            in_tasks = True
            continue

        if in_plan and in_tasks:
            t = s.strip()
            if t.startswith("- TASK_ID:"):
                if current:
                    tasks.append(current)
                    current = {}
                current["TASK_ID"] = t.split(":", 1)[1].strip()
            elif t.startswith("AXIS_NAME:"):
                current["AXIS_NAME"] = t.split(":", 1)[1].strip()
            elif t.startswith("PRIORITY:"):
                current["PRIORITY"] = t.split(":", 1)[1].strip().upper()
            elif t.startswith("ALIGNMENT_SCORE:"):
                current["ALIGNMENT_SCORE"] = t.split(":", 1)[1].strip()
            elif t.startswith("TASK_DESCRIPTION:"):
                current["TASK_DESCRIPTION"] = t.split(":", 1)[1].strip()

    if current:
        tasks.append(current)

    return tasks


def priority_rank(p: str) -> int:
    p = (p or "").upper()
    if p == "HIGH":
        return 0
    if p == "MEDIUM":
        return 1
    if p == "LOW":
        return 2
    return 3


def pick_one_task_per_axis(tasks: list[dict]) -> list[dict]:
    # групиране по ос
    by_axis: dict[str, list[dict]] = {}
    for t in tasks:
        axis = t.get("AXIS_NAME", "UNKNOWN")
        by_axis.setdefault(axis, []).append(t)

    chosen = []
    for axis, axis_tasks in by_axis.items():
        # сортираме по приоритет (HIGH, MEDIUM, LOW) и по TASK_ID
        axis_tasks_sorted = sorted(
            axis_tasks,
            key=lambda x: (priority_rank(x.get("PRIORITY")), x.get("TASK_ID", ""))
        )
        chosen.append(axis_tasks_sorted[0])

    return chosen


def append_executor_log(chosen: list[dict], source_log: Path):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("=== AXIS TASK EXECUTION STEP START ===")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append(f"SOURCE_SESSION_LOG: {source_log.name}")
    lines.append(f"TASKS_PICKED_COUNT: {len(chosen)}")
    lines.append("TASKS_PICKED:")

    for t in chosen:
        tid = t.get("TASK_ID", "?")
        axis = t.get("AXIS_NAME", "?")
        pr = t.get("PRIORITY", "?")
        sc = t.get("ALIGNMENT_SCORE", "?")
        desc = t.get("TASK_DESCRIPTION", "")
        lines.append(f"- TASK_ID: {tid}")
        lines.append(f"  AXIS_NAME: {axis}")
        lines.append(f"  PRIORITY: {pr}")
        lines.append(f"  ALIGNMENT_SCORE: {sc}")
        lines.append(f"  TASK_DESCRIPTION: {desc}")
    lines.append("=== AXIS TASK EXECUTION STEP END ===")
    lines.append("")

    try:
        with EXECUTOR_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[EXECUTOR] Грешка при писане в {EXECUTOR_LOG}: {e}")
        return

    print("\n=== AXIS TASK EXECUTOR – ONE STEP ===")
    print(f"SESSION_LOG: {source_log.name}")
    print(f"ИЗБРАНИ ЗАДАЧИ (по 1 на ос): {len(chosen)}")
    for t in chosen:
        tid = t.get("TASK_ID", "?")
        axis = t.get("AXIS_NAME", "?")
        pr = t.get("PRIORITY", "?")
        desc = t.get("TASK_DESCRIPTION", "")
        print(f"- {tid} | {pr:6s} | {axis} | {desc}")
    print("Резултатът е записан в AXIS_TASK_EXECUTOR_LOG.txt")
    print("=======================================")


def main():
    session_log = find_latest_session_log()
    if session_log is None:
        return

    tasks = parse_task_candidates(session_log)
    if not tasks:
        print("[EXECUTOR] Няма задачи за изпълнение (TASK_CANDIDATES).")
        return

    chosen = pick_one_task_per_axis(tasks)
    if not chosen:
        print("[EXECUTOR] Не бяха избрани задачи (по оси).")
        return

    append_executor_log(chosen, session_log)


if __name__ == "__main__":
    main()
