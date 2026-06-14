import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

def parse_review_file(path: Path):
    """
    Връща речник с:
    - axis_name
    - score_alignment (str или None)
    - next_steps (list of lines в секцията NEXT_STEPS)
    - cortex_actions (list of RECOMMENDED_ACTIONS_FOR_CORTEX)
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    axis_name = None
    score_alignment = None
    next_steps_lines = []

    # AXIS_NAME:
    for line in lines:
        if line.strip().startswith("AXIS_NAME:"):
            axis_name = line.split("AXIS_NAME:", 1)[1].strip()
            break

    # SCORE_ALIGNMENT:
    for i, line in enumerate(lines):
        if line.strip().startswith("SCORE_ALIGNMENT:"):
            value = line.split("SCORE_ALIGNMENT:", 1)[1].strip()
            score_alignment = value if value else None
            break

    # NEXT_STEPS секция:
    in_next_steps = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("6) NEXT_STEPS"):
            in_next_steps = True
            continue
        if in_next_steps and stripped.startswith("META:"):
            in_next_steps = False
        elif in_next_steps:
            next_steps_lines.append(line)

    # Вътре в NEXT_STEPS, извадим RECOMMENDED_ACTIONS_FOR_CORTEX
    cortex_actions = []
    in_cortex_block = False
    for line in next_steps_lines:
        s = line.strip()
        if s.startswith("RECOMMENDED_ACTIONS_FOR_CORTEX"):
            in_cortex_block = True
            continue
        if in_cortex_block:
            if s.startswith("RECOMMENDED_ACTIONS_FOR_HUMANS"):
                in_cortex_block = False
                continue
            if s.startswith("- "):
                cortex_actions.append(s[2:].strip())

    return {
        "axis_name": axis_name or path.name,
        "score_alignment": score_alignment,
        "next_steps": [l for l in next_steps_lines if l.strip() != ""],
        "cortex_actions": cortex_actions,
    }

def priority_from_score(score: str | None) -> str:
    """
    Мапваме ALIGNMENT_SCORE към PRIORITY:
    -2 -> HIGH
    -1 -> MEDIUM
     0,+1,+2 или None -> LOW
    """
    if score is None:
        return "LOW"
    s = score.strip()
    if s.startswith("-2"):
        return "HIGH"
    if s.startswith("-1"):
        return "MEDIUM"
    return "LOW"

def build_status_and_plan():
    now = datetime.now()
    session_id = now.strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"SESSION_{session_id}_LOG.txt"

    review_files = sorted(KNOWLEDGE_DIR.glob("*REVIEW_2024_2026.txt"))

    status_lines = []
    status_lines.append(f"SESSION_ID: {session_id}")
    status_lines.append(f"TIMESTAMP_START: {now.isoformat(timespec='seconds')}")
    status_lines.append("FOCUS_AXES: ALL")
    status_lines.append("SESSION_GOAL: INITIAL_STATUS_SCAN")
    status_lines.append("")
    status_lines.append("STEPS:")
    status_lines.append("STATUS_SUMMARY_PER_AXIS:")

    task_candidates = []

    for path in review_files:
        info = parse_review_file(path)
        axis = info["axis_name"]
        score = info["score_alignment"]
        score_str = score if score is not None else "N/A"

        status_lines.append("")
        status_lines.append(f"AXIS_NAME: {axis}")
        status_lines.append(f"  REVIEW_FILE: {path.name}")
        status_lines.append(f"  ALIGNMENT_SCORE: {score_str}")
        if info["next_steps"]:
            status_lines.append("  NEXT_STEPS:")
            for l in info["next_steps"]:
                status_lines.append(f"    {l}")
        else:
            status_lines.append("  NEXT_STEPS: (none found)")

        prio = priority_from_score(score)
        for action in info["cortex_actions"]:
            task_id = f"TASK_{len(task_candidates)+1:03d}"
            task_candidates.append({
                "task_id": task_id,
                "axis": axis,
                "priority": prio,
                "score": score_str,
                "description": action,
            })

    status_lines.append("")
    status_lines.append(f"TIMESTAMP_END: {datetime.now().isoformat(timespec='seconds')}")
    status_lines.append("SESSION_STATUS: COMPLETED_STATUS_SCAN")

    # PLAN / TASK_CANDIDATES
    plan_lines = []
    plan_lines.append("")
    plan_lines.append("PLAN:")
    if not task_candidates:
        plan_lines.append("  NO_TASK_CANDIDATES_FOUND")
    else:
        plan_lines.append("  TASK_CANDIDATES:")
        for t in task_candidates:
            plan_lines.append(f"    - TASK_ID: {t['task_id']}")
            plan_lines.append(f"      AXIS_NAME: {t['axis']}")
            plan_lines.append(f"      PRIORITY: {t['priority']}")
            plan_lines.append(f"      ALIGNMENT_SCORE: {t['score']}")
            plan_lines.append(f"      TASK_DESCRIPTION: {t['description']}")

    full_text = "\n".join(status_lines + plan_lines)
    log_path.write_text(full_text, encoding="utf-8")
    print(f"Written session status & plan log: {log_path}")

    return log_path

def main():
    build_status_and_plan()

if __name__ == "__main__":
    main()
