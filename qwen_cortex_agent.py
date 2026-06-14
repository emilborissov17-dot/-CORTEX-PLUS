import json
from pathlib import Path
from datetime import datetime, UTC

from core.llm_backend import call_internal_llm  # централизиран LLM gateway

# === Основни пътища (в пясъчника CORTEX++_QWEN) ===
ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"
JOURNAL_DIR = ROOT / "journal"
JOURNAL_DIR.mkdir(exist_ok=True)

QWEN_JOURNAL = JOURNAL_DIR / "journal_qwen_energy.txt"


def load_recent_context() -> str:
    parts: list[str] = []

    # 1) Основни цели / визия, ако ги имаме
    for fname in [
        "civilization_goal.txt",
        "civilization_vision.txt",
        "goal_summary.txt",
        "goal_summary_short.txt",
        "core_role.txt",
    ]:
        p = ROOT / fname
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8").strip()
            except Exception:
                txt = ""
            if txt:
                parts.append(f"=== {fname} ===\n{txt}\n")

    # 2) Последни енергийни snapshots (ако има)
    energy_snap_dir = KNOWLEDGE_DIR / "energy_snapshots"
    if energy_snap_dir.exists():
        snap_files = sorted(energy_snap_dir.glob("*.json"))
        for f in snap_files[-5:]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            parts.append(f"=== SNAPSHOT {f.name} ===\n")
            parts.append(json.dumps(data, ensure_ascii=False)[:2000] + "\n")

    # 3) Последни редове от journal_resource_act.txt (ако съществува)
    old_journal = ROOT / "journal_resource_act.txt"
    if old_journal.exists():
        try:
            lines = old_journal.read_text(encoding="utf-8").splitlines()
            tail = "\n".join(lines[-80:])
            parts.append("=== LAST journal_resource_act.txt (tail) ===\n" + tail)
        except Exception:
            pass

    if not parts:
        return "НЯМА НАЛИЧЕН КОНТЕКСТ (ГОЛ, ВИЗИЯ, SNAPSHOTS, JOURNAL)."

    return "\n\n".join(parts)


def build_prompt(context_text: str) -> str:
    """
    Строи единен текстов prompt за вътрешния LLM (QWEN),
    който ще бъде подаден към call_internal_llm().
    """
    header = (
        "Ти си локален AGI агент (Qwen) вътре в проекта CORTEX++.\n"
        "Четеш състоянието на системата от текстов контекст (цели, визия, snapshots, стари журнали)\n"
        "и правиш кратък, но структуриран ENERGY REVIEW.\n\n"
        "Формат на отговора (точно в този ред):\n"
        "=== OVERVIEW ===\n"
        "- 2–4 изречения общ обзор на глобалната енергийна система.\n\n"
        "=== KEY RISKS ===\n"
        "- по точки, най-важните рискове и проблеми.\n\n"
        "=== RECOMMENDED ACTIONS (CIVILIZATION, 10 YEARS) ===\n"
        "- 3–5 стратегически стъпки за следващите 10 години.\n\n"
        "=== TASKS FOR CORTEX++ (ENERGY AXIS) ===\n"
        "- 5–10 задачи в стил:\n"
        "  [TASK]: кратко описание\n"
        "  [WHY]: защо е важна\n"
        "  [DATA_NEEDED]: какви данни/файлове/източници трябват\n"
        "Пиши изцяло на български.\n\n"
    )
    body = (
        "Контекст от CORTEX++ (цели, визия, снимки на енергийния домейн, стари журнали):\n\n"
        f"{context_text}\n\n"
        "На база на това, направи ENERGY REVIEW в описания формат.\n"
    )
    return header + body


def append_to_qwen_journal(review_text: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n\n=== QWEN ENERGY REVIEW @ {ts} UTC ===\n"
    QWEN_JOURNAL.parent.mkdir(exist_ok=True)
    with QWEN_JOURNAL.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write(review_text)
        f.write("\n")


def main() -> None:
    print("[QWEN_CORTEX_AGENT] loading context...")
    ctx = load_recent_context()

    print("[QWEN_CORTEX_AGENT] building prompt...")
    prompt = build_prompt(ctx)

    print("[QWEN_CORTEX_AGENT] calling internal LLM (QWEN)...")
    try:
        review = call_internal_llm(prompt)
    except Exception as e:
        print(f"[QWEN_CORTEX_AGENT][ERROR] {e}")
        return

    print("[QWEN_CORTEX_AGENT] writing to journal_qwen_energy.txt...")
    append_to_qwen_journal(review)
    print("[QWEN_CORTEX_AGENT] done.")


if __name__ == "__main__":
    main()
