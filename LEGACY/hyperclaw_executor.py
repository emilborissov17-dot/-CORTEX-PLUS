from __future__ import annotations

from pathlib import Path
from datetime import datetime
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parent
PLAN_DIR = ROOT / "plans"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def read_latest_plan() -> tuple[Path, str]:
    if not PLAN_DIR.exists():
        raise FileNotFoundError("plans/ directory not found")

    files = sorted(
        PLAN_DIR.glob("plan-*.md"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("no plan-*.md files found in plans/")

    latest = files[0]
    text = latest.read_text(encoding="utf-8")
    return latest, text


def extract_axis_block(plan_text: str, axis_header: str) -> str:
    lines = plan_text.splitlines()
    result: list[str] = []
    in_block = False

    for line in lines:
        if line.strip().startswith(axis_header):
            in_block = True
            result.append(line)
            continue
        if in_block and line.strip().endswith("AXIS_FOCUS:") and line.strip() != axis_header:
            # започва следващата AXIS секция
            break
        if in_block:
            result.append(line)

    return "\n".join(result).strip()


def log(msg: str) -> None:
    print(f"[HYPEREXEC] {msg}")


def run_agent(script: Path, args: list[str] | None = None) -> int:
    if args is None:
        args = []
    cmd = ["python3", str(script), *args]  # важно: python3 за WSL
    log(f"RUN: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def write_execution_log(today: str, content: str) -> Path:
    out_path = LOG_DIR / f"hyperclaw-execution-{today}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def main() -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    log(f"today={today}")

    try:
        plan_path, plan_text = read_latest_plan()
    except Exception as e:
        log(f"[ERROR] {e}")
        return

    log(f"using plan: {plan_path.name}")

    # Извличане на блоковете за осите
    human_block = extract_axis_block(plan_text, "HUMAN_AXIS_FOCUS:")
    planet_block = extract_axis_block(plan_text, "PLANET_AXIS_FOCUS:")
    civ_block = extract_axis_block(plan_text, "CIVILIZATION_AXIS_FOCUS:")
    cosmos_block = extract_axis_block(plan_text, "COSMOS_AXIS_FOCUS:")

    exec_log_parts: list[str] = []
    exec_log_parts.append(f"# HYPERCLAW EXECUTION LOG – {today}\n")
    exec_log_parts.append(f"PLAN_SOURCE: {plan_path.name}\n")

    # HUMAN axis – тук можеш да вържеш агенти, свързани с лични/когнитивни цели
    exec_log_parts.append("## HUMAN_AXIS_EXECUTION\n")
    exec_log_parts.append("```markdown\n")
    exec_log_parts.append(textwrap.indent(human_block or "(no HUMAN block found)", ""))
    exec_log_parts.append("\n```\n")
    # TODO: run concrete HUMAN agents when имаш такива

    # PLANET axis – пример: енергийни агенти
    exec_log_parts.append("## PLANET_AXIS_EXECUTION\n")
    exec_log_parts.append("```markdown\n")
    exec_log_parts.append(textwrap.indent(planet_block or "(no PLANET block found)", ""))
    exec_log_parts.append("\n```\n")

    # пример: енергиен gap-to-tasks агент
    energy_agent = ROOT / "energy_gaps_to_tasks_agent.py"
    if energy_agent.exists():
        rc = run_agent(energy_agent, [])
        exec_log_parts.append(f"- energy_gaps_to_tasks_agent.py -> return code {rc}\n")

    # CIVILIZATION axis – пример: civilization daily review / cortex агент
    exec_log_parts.append("## CIVILIZATION_AXIS_EXECUTION\n")
    exec_log_parts.append("```markdown\n")
    exec_log_parts.append(textwrap.indent(civ_block or "(no CIVILIZATION block found)", ""))
    exec_log_parts.append("\n```\n")

    civ_agent = ROOT / "qwen_civilization_daily_review_agent.py"
    if civ_agent.exists():
        rc = run_agent(civ_agent, [])
        exec_log_parts.append(f"- qwen_civilization_daily_review_agent.py -> return code {rc}\n")

    # COSMOS axis – засега само логваме блока
    exec_log_parts.append("## COSMOS_AXIS_EXECUTION\n")
    exec_log_parts.append("```markdown\n")
    exec_log_parts.append(textwrap.indent(cosmos_block or "(no COSMOS block found)", ""))
    exec_log_parts.append("\n```\n")

    out_path = write_execution_log(today, "".join(exec_log_parts))
    log(f"done. Wrote execution log: {out_path}")


if __name__ == "__main__":
    main()
