from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import List

from core.llm_backend import call_internal_llm  # централен LLM gateway

ROOT = Path(__file__).resolve().parent
DAILY_DIR = ROOT / "daily"
DAILY_DIR.mkdir(exist_ok=True)

CORE_ROLE = ROOT / "core_role.txt"
AXES_SPEC = ROOT / "agi_axes_spec.txt"
PROTOCOL = ROOT / "DAILYREVIEWPROTOCOL.md"

IDENTITY = ROOT / "IDENTITY.md"
SOUL = ROOT / "SOUL.md"
USER = ROOT / "USER.md"
HEARTBEAT = ROOT / "HEARTBEAT.md"
MEMORY = ROOT / "MEMORY.md"


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def next_review_index(today: str) -> int:
    files = sorted(
        DAILY_DIR.glob(f"dailyreview-{today}-*.md"),
        key=lambda p: p.name,
    )
    return len(files) + 1


def build_context() -> str:
    parts: List[str] = []

    core_role_txt = safe_read(CORE_ROLE)
    if core_role_txt:
        parts.append("=== core_role.txt ===\n" + core_role_txt)

    axes_spec_txt = safe_read(AXES_SPEC)
    if axes_spec_txt:
        parts.append("=== agi_axes_spec.txt ===\n" + axes_spec_txt)

    protocol_txt = safe_read(PROTOCOL)
    if protocol_txt:
        parts.append("=== DAILYREVIEWPROTOCOL.md ===\n" + protocol_txt)

    id_txt = safe_read(IDENTITY)
    if id_txt:
        parts.append("=== IDENTITY.md ===\n" + id_txt)

    soul_txt = safe_read(SOUL)
    if soul_txt:
        parts.append("=== SOUL.md ===\n" + soul_txt)

    user_txt = safe_read(USER)
    if user_txt:
        parts.append("=== USER.md ===\n" + user_txt)

    heartbeat_txt = safe_read(HEARTBEAT)
    if heartbeat_txt:
        parts.append("=== HEARTBEAT.md ===\n" + heartbeat_txt)

    memory_doc = safe_read(MEMORY)
    if memory_doc:
        parts.append("=== MEMORY.md ===\n" + memory_doc)

    if not parts:
        return (
            "НЯМА НАЛИЧЕН КОНТЕКСТ "
            "(core_role, agi_axes_spec, DAILYREVIEWPROTOCOL, "
            "IDENTITY/SOUL/USER/HEARTBEAT/MEMORY)."
        )

    return "\n\n".join(parts)


def build_prompt(context_text: str, today: str, review_index: int) -> str:
    header = (
        "СИСТЕМНИ ЖЕЛЕЗНИ ПРАВИЛА (СПАЗВАЙ БУКВАЛНО):\n"
        "1) ЗАБРАНЕНО: заглавие `# dailyreview-YYYY-MM-DD.md` или подобни.\n"
        f"2) ЗАДЪЛЖИТЕЛНО: изходът започва с точно:\n   # CIVILIZATION DAILY REVIEW – {today}\n"
        "3) ЗАБРАНЕНИ: думите/редовете „Thinking...“, „done thinking“, вътрешен монолог,\n"
        "   описания от вида „Okay, let me think“, „I will now“ и всякакъв meta текст.\n"
        "4) ОТГОВОРЪТ Е САМО MARKDOWN СЪДЪРЖАНИЕТО НА ФАЙЛА, БЕЗ ОБЯСНЕНИЯ.\n"
        "Ако нарушиш някое от тези правила, отговорът ти се счита за НИЩОЖЕН.\n\n"
        "Ти си QWEN_CIVILIZATION_DAILY_REVIEW_AGENT, част от CORTEX++_QWEN.\n"
        "Изпълняваш протокола CIVILIZATION_DAILY_REVIEW от файла DAILYREVIEWPROTOCOL.md (версия 2.0).\n"
        "Разполагаш с core_role.txt, agi_axes_spec.txt, DAILYREVIEWPROTOCOL.md, "
        "IDENTITY/SOUL/USER/HEARTBEAT/MEMORY.\n\n"
        "ТВОЯТА ЕДИНСТВЕНА ЗАДАЧА Е:\n"
        f"- Да генерираш НОВ тип daily review за файла `dailyreview-{today}.md`.\n"
        "- ЗАДЪЛЖИТЕЛНО използвай САМО формата с 4 оси (HUMAN/PLANET/CIVILIZATION/COSMOS)\n"
        "  и под-осите, описани по-долу.\n"
        "- СТАРИТЕ ФОРМАТИ с ENERGY_REVIEW / WATER_REVIEW / FOOD_REVIEW / MATERIALS/WASTE_REVIEW СА ЗАБРАНЕНИ.\n"
        "- Ако се опиташ да използваш стария формат, това се счита за ГРЕШКА.\n"
        "- НЕ добавяй system/tool/meta текст (напр. „browsing the web“, „I can't access the internet“ и подобни).\n\n"
        "ФОРМАТЪТ НА ИЗХОДА ТРЯБВА ДА Е ТОЧНО СЛЕДНИЯТ (заглавията и редът са фиксирани):\n\n"
        f"# CIVILIZATION DAILY REVIEW – {today}\n\n"
        "META:\n"
        f"  DATE: {today}\n"
        "  PROTOCOL_VERSION: 2.0\n"
        "  REVIEW_AGENT: QWEN_CIVILIZATION_DAILY_REVIEW_AGENT\n"
        f"  REVIEW_INDEX: {review_index}\n"
        "  SOURCES:\n"
        "    - core_role.txt\n"
        "    - agi_axes_spec.txt\n"
        "    - IDENTITY.md, SOUL.md, USER.md, HEARTBEAT.md\n"
        "    - MEMORY.md\n"
        "    - data/* (ако има)\n\n"
        "## HUMAN_AXIS_STATUS\n"
        "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
        "- KEY_OBSERVATIONS:\n"
        "  - HEALTH: ...\n"
        "  - COGNITION: ...\n"
        "  - GOVERNANCE: ...\n"
        "- RISKS:\n"
        "  - ...\n"
        "- OPPORTUNITIES:\n"
        "  - ...\n\n"
        "## PLANET_AXIS_STATUS\n"
        "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
        "- KEY_OBSERVATIONS:\n"
        "  - ENERGY: ...\n"
        "  - WATER: ...\n"
        "  - FOOD: ...\n"
        "  - MATERIALS_WASTE: ...\n"
        "- RISKS:\n"
        "  - ...\n"
        "- OPPORTUNITIES:\n"
        "  - ...\n\n"
        "## CIVILIZATION_AXIS_STATUS\n"
        "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
        "- KEY_OBSERVATIONS:\n"
        "  - INEQUALITIES: ...\n"
        "  - INFRASTRUCTURE: ...\n"
        "  - INSTITUTIONS: ...\n"
        "  - TECHNOLOGY: ...\n"
        "- RISKS:\n"
        "  - ...\n"
        "- OPPORTUNITIES:\n"
        "  - ...\n\n"
        "## COSMOS_AXIS_STATUS\n"
        "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
        "- KEY_OBSERVATIONS:\n"
        "  - SPACE_INFRASTRUCTURE: ...\n"
        "  - DEEP_TIME_RISKS: ...\n"
        "  - EXPLORATION: ...\n"
        "- RISKS:\n"
        "  - ...\n"
        "- OPPORTUNITIES:\n"
        "  - ...\n\n"
        "## HYPERCLAW_BEHAVIOR_REVIEW\n"
        "- SUMMARY_OF_PLAN_EXECUTION:\n"
        "  - кратък обзор какво е било планирано и какво реално е било изпълнено "
        "(по наблюдаваното поведение на hyperclaw_orchestrator / hyperclaw_executor).\n"
        "- GOOD_DECISIONS:\n"
        "  - ...\n"
        "- BAD_OR_NEUTRAL_DECISIONS:\n"
        "  - ...\n"
        "- SYSTEMIC_PATTERNS:\n"
        "  - ...\n\n"
        "## LESSONS_LEARNED\n"
        "- За HUMAN:\n"
        "  - ...\n"
        "- За PLANET:\n"
        "  - ...\n"
        "- За CIVILIZATION:\n"
        "  - ...\n"
        "- За COSMOS:\n"
        "  - ...\n"
        "- За HYPERCLAW_ORCHESTRATOR/EXECUTOR:\n"
        "  - ...\n\n"
        "## NEXT_PLAN_BIASES\n"
        "- HUMAN:\n"
        "  - ...\n"
        "- PLANET:\n"
        "  - ...\n"
        "- CIVILIZATION:\n"
        "  - ...\n"
        "- COSMOS:\n"
        "  - ...\n"
        "- AGENT_SELECTION:\n"
        "  - ...\n\n"
        "## MEMORY_UPDATES\n"
        "- PERMANENT_MEMORY_SUGGESTIONS:\n"
        "  - ...\n"
        "- TEMPORARY_FLAGS:\n"
        "  - ...\n\n"
        "КОНТЕКСТ – проект CORTEX++_QWEN:\n"
        f"{context_text}\n\n"
        "Сега генерирай САМО съдържанието на файла `dailyreview-{today}.md` по горния формат.\n"
    )
    return header


def strip_thinking(raw: str) -> str:
    """
    Локален предпазен колан срещу вътрешния монолог (Thinking... / done thinking).
    Ако backend-ът вече го чисти, това ще е no-op.
    """
    if not raw:
        return raw

    # махни начален "Thinking..." блок до първия празен ред
    if "Thinking..." in raw:
        # режем от първото срещане на Thinking... нататък
        before, after = raw.split("Thinking...", 1)
        tail = after.lstrip()
        if "\n\n" in tail:
            tail = tail.split("\n\n", 1)[1]
        raw = tail

    raw = raw.lstrip()
    # махни leading "...done thinking." / "done thinking."
    if raw.startswith("...done thinking.") or raw.startswith("done thinking."):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""

    return raw.lstrip()


def is_valid_new_format(today: str, content: str) -> bool:
    content = content or ""
    if "Thinking..." in content or "done thinking" in content:
        return False
    if "# dailyreview-" in content:
        return False
    if f"# CIVILIZATION DAILY REVIEW – {today}" not in content:
        return False

    required_sections = [
        "## HUMAN_AXIS_STATUS",
        "## PLANET_AXIS_STATUS",
        "## CIVILIZATION_AXIS_STATUS",
        "## COSMOS_AXIS_STATUS",
        "## HYPERCLAW_BEHAVIOR_REVIEW",
        "## LESSONS_LEARNED",
        "## NEXT_PLAN_BIASES",
        "## MEMORY_UPDATES",
    ]
    for sec in required_sections:
        if sec not in content:
            return False

    forbidden_old = [
        "ENERGY_REVIEW",
        "WATER_REVIEW",
        "FOOD_REVIEW",
        "MATERIALS/WASTE_REVIEW",
    ]
    for marker in forbidden_old:
        if marker in content:
            return False

    return True


def write_daily_file(today: str, review_index: int, content: str) -> Path:
    out_path = DAILY_DIR / f"dailyreview-{today}-{review_index:03d}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[CIVILIZATION_DAILY_REVIEW] today={today}")
    print("[CIVILIZATION_DAILY_REVIEW] building context...")
    ctx = build_context()

    review_index = next_review_index(today)
    print(f"[CIVILIZATION_DAILY_REVIEW] review_index={review_index}")

    print("[CIVILIZATION_DAILY_REVIEW] building prompt...")
    full_prompt = build_prompt(ctx, today, review_index)

    print("[CIVILIZATION_DAILY_REVIEW] calling internal LLM (QWEN)...")
    try:
        raw = call_internal_llm(full_prompt)
    except Exception as e:
        print(f"[CIVILIZATION_DAILY_REVIEW][ERROR] {e}")
        return

    review_md = strip_thinking(raw)

    print("===== RAW FIRST RESPONSE START =====")
    print(raw[:2000])
    print("===== RAW FIRST RESPONSE END =====")
    print("===== CLEANED FIRST RESPONSE START =====")
    print(review_md[:2000])
    print("===== CLEANED FIRST RESPONSE END =====")

    if not is_valid_new_format(today, review_md):
        print("[CIVILIZATION_DAILY_REVIEW][WARN] First attempt invalid, using HARD TEMPLATE prompt...")

        hard_template_prompt = (
            "Генерирай САМО съдържанието на файла `dailyreview-{today}.md` "
            "по ТОЧНО следния шаблон. НЕ добавяй никакъв вътрешен монолог, "
            "обяснения или други текстове.\n\n"
            f"# CIVILIZATION DAILY REVIEW – {today}\n\n"
            "META:\n"
            f"  DATE: {today}\n"
            "  PROTOCOL_VERSION: 2.0\n"
            "  REVIEW_AGENT: QWEN_CIVILIZATION_DAILY_REVIEW_AGENT\n"
            f"  REVIEW_INDEX: {review_index}\n"
            "  SOURCES:\n"
            "    - core_role.txt\n"
            "    - agi_axes_spec.txt\n"
            "    - IDENTITY.md, SOUL.md, USER.md, HEARTBEAT.md\n"
            "    - MEMORY.md\n"
            "    - data/* (ако има)\n\n"
            "## HUMAN_AXIS_STATUS\n"
            "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
            "- KEY_OBSERVATIONS:\n"
            "  - HEALTH: ...\n"
            "  - COGNITION: ...\n"
            "  - GOVERNANCE: ...\n"
            "- RISKS:\n"
            "  - ...\n"
            "- OPPORTUNITIES:\n"
            "  - ...\n\n"
            "## PLANET_AXIS_STATUS\n"
            "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
            "- KEY_OBSERVATIONS:\n"
            "  - ENERGY: ...\n"
            "  - WATER: ...\n"
            "  - FOOD: ...\n"
            "  - MATERIALS_WASTE: ...\n"
            "- RISKS:\n"
            "  - ...\n"
            "- OPPORTUNITIES:\n"
            "  - ...\n\n"
            "## CIVILIZATION_AXIS_STATUS\n"
            "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
            "- KEY_OBSERVATIONS:\n"
            "  - INEQUALITIES: ...\n"
            "  - INFRASTRUCTURE: ...\n"
            "  - INSTITUTIONS: ...\n"
            "  - TECHNOLOGY: ...\n"
            "- RISKS:\n"
            "  - ...\n"
            "- OPPORTUNITIES:\n"
            "  - ...\n\n"
            "## COSMOS_AXIS_STATUS\n"
            "- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)\n"
            "- KEY_OBSERVATIONS:\n"
            "  - SPACE_INFRASTRUCTURE: ...\n"
            "  - DEEP_TIME_RISKS: ...\n"
            "  - EXPLORATION: ...\n"
            "- RISKS:\n"
            "  - ...\n"
            "- OPPORTUNITIES:\n"
            "  - ...\n\n"
            "## HYPERCLAW_BEHAVIOR_REVIEW\n"
            "- SUMMARY_OF_PLAN_EXECUTION:\n"
            "  - ...\n"
            "- GOOD_DECISIONS:\n"
            "  - ...\n"
            "- BAD_OR_NEUTRAL_DECISIONS:\n"
            "  - ...\n"
            "- SYSTEMIC_PATTERNS:\n"
            "  - ...\n\n"
            "## LESSONS_LEARNED\n"
            "- За HUMAN:\n"
            "  - ...\n"
            "- За PLANET:\n"
            "  - ...\n"
            "- За CIVILIZATION:\n"
            "  - ...\n"
            "- За COSMOS:\n"
            "  - ...\n"
            "- За HYPERCLAW_ORCHESTRATOR/EXECUTOR:\n"
            "  - ...\n\n"
            "## NEXT_PLAN_BIASES\n"
            "- HUMAN:\n"
            "  - ...\n"
            "- PLANET:\n"
            "  - ...\n"
            "- CIVILIZATION:\n"
            "  - ...\n"
            "- COSMOS:\n"
            "  - ...\n"
            "- AGENT_SELECTION:\n"
            "  - ...\n\n"
            "## MEMORY_UPDATES\n"
            "- PERMANENT_MEMORY_SUGGESTIONS:\n"
            "  - ...\n"
            "- TEMPORARY_FLAGS:\n"
            "  - ...\n"
        )

        try:
            raw_retry = call_internal_llm(hard_template_prompt)
        except Exception as e:
            print(f"[CIVILIZATION_DAILY_REVIEW][ERROR] Hard-template call failed: {e}")
            return

        review_md_retry = strip_thinking(raw_retry)

        print("===== RAW HARD-TEMPLATE RESPONSE START =====")
        print(raw_retry[:2000])
        print("===== RAW HARD-TEMPLATE RESPONSE END =====")
        print("===== CLEANED HARD-TEMPLATE RESPONSE START =====")
        print(review_md_retry[:2000])
        print("===== CLEANED HARD-TEMPLATE RESPONSE END =====")

        if not is_valid_new_format(today, review_md_retry):
            print("[CIVILIZATION_DAILY_REVIEW][ERROR] Hard-template response still invalid; aborting write.")
            return

        review_md = review_md_retry

    print("[CIVILIZATION_DAILY_REVIEW] writing daily file...")
    out_path = write_daily_file(today, review_index, review_md)
    print(f"[CIVILIZATION_DAILY_REVIEW] done. Wrote: {out_path}")


if __name__ == "__main__":
    main()
