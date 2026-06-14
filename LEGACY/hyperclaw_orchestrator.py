from pathlib import Path
from datetime import datetime

from core.llm_backend import call_internal_llm

ROOT = Path(__file__).resolve().parent
DAILY_DIR = ROOT / "daily"
PLAN_DIR = ROOT / "plans"
AXES_SPEC = ROOT / "agi_axes_spec.txt"
PLAN_DIR.mkdir(exist_ok=True)

def read_latest_daily_review() -> tuple[Path, str]:
    if not DAILY_DIR.exists():
        raise FileNotFoundError("daily/ directory not found")

    files = sorted(
        DAILY_DIR.glob("dailyreview-*.md"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("no dailyreview-*.md files found in daily/")

    latest = files[0]
    text = latest.read_text(encoding="utf-8")
    return latest, text

def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

def build_hyperclaw_prompt(daily_text: str, axes_spec: str, today: str) -> str:
    return (
        "Ти си CORTEX++_QWEN в ролята на HYPERCLAW_ORCHESTRATOR.\n"
        "Имаш достъп до:\n"
        "- последния CIVILIZATION DAILY REVIEW (по всички оси),\n"
        "- `agi_axes_spec.txt` с четирите топ оси: HUMAN, PLANET, CIVILIZATION, COSMOS и техните под-оси.\n\n"
        "ТВОЯТА ЗАДАЧА:\n"
        f"- Да генерираш съдържанието на файла `plan-{today}.md`.\n"
        "- Планът трябва да е ГЛОБАЛЕН, НЕ ЛОКАЛЕН: да включва действия\n"
        "  по поне една под-ос от всяка от четирите главни оси (HUMAN, PLANET, CIVILIZATION, COSMOS).\n"
        "- За всяка главна ос трябва да избереш една или повече под-оси, върху които да се действа сега,\n"
        "  като се съобразиш със статуса им в daily review (LOW/MEDIUM/HIGH или еквивалент).\n\n"
        "СТРИКТНИ ИЗИСКВАНИЯ КЪМ ИЗХОДА:\n"
        f"- Изходът ти е САМО съдържанието на Markdown файл `plan-{today}.md`.\n"
        "- НЕ добавяй системни или meta-коментари (\"Thinking...\", обяснения и т.н.).\n"
        "- НЕ копирай целия daily review; позовавай се на него само в обясненията.\n\n"
        "ФОРМАТ НА ИЗХОДА (СТРУКТУРАТА Е ЗАДЪЛЖИТЕЛНА):\n\n"
        f"# HYPERCLAW MULTI-AXIS PLAN – {today}\n\n"
        "META:\n"
        f"  DATE: {today}\n"
        "  ORCHESTRATOR: HYPERCLAW_ORCHESTRATOR\n"
        "  SOURCE_DAILY_REVIEW: последния `dailyreview-YYYY-MM-DD.md`\n\n"
        "HUMAN_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES:\n"
        "    - NAME: <AXIS_NAME>\n"
        "      LABEL: <AXIS_LABEL>\n"
        "      REPORTED_LEVEL: <LOW/MEDIUM/HIGH или статус от daily review>\n"
        "      REASON_FOR_SELECTION: 2–4 изречения защо тази под-ос е критична сега.\n"
        "  OBJECTIVE:\n"
        "    Едно ясно формулирано целево подобрение за HUMAN за следващите 24–72 часа.\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие за HUMAN осите>\n"
        "    - STEP 2: ...\n"
        "  CROSS_AXIS_EFFECTS:\n"
        "    2–4 изречения как действията по HUMAN влияят на PLANET / CIVILIZATION / COSMOS.\n\n"
        "PLANET_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES:\n"
        "    - NAME: <AXIS_NAME>\n"
        "      LABEL: <AXIS_LABEL>\n"
        "      REPORTED_LEVEL: <LOW/MEDIUM/HIGH>\n"
        "      REASON_FOR_SELECTION: 2–4 изречения.\n"
        "  OBJECTIVE:\n"
        "    Едно целево подобрение за PLANET (ресурси/климат) за 24–72 часа.\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие>\n"
        "    - STEP 2: ...\n"
        "  CROSS_AXIS_EFFECTS:\n"
        "    2–4 изречения как тези стъпки влияят на HUMAN / CIVILIZATION / COSMOS.\n\n"
        "CIVILIZATION_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES:\n"
        "    - NAME: <AXIS_NAME>\n"
        "      LABEL: <AXIS_LABEL>\n"
        "      REPORTED_LEVEL: <LOW/MEDIUM/HIGH>\n"
        "      REASON_FOR_SELECTION: 2–4 изречения.\n"
        "  OBJECTIVE:\n"
        "    Целево подобрение в икономика/институции/технологии за 24–72 часа.\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие>\n"
        "    - STEP 2: ...\n"
        "  CROSS_AXIS_EFFECTS:\n"
        "    2–4 изречения за ефект върху HUMAN / PLANET / COSMOS.\n\n"
        "COSMOS_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES:\n"
        "    - NAME: LONG_TERM_FUTURE_REVIEW\n"
        "      LABEL: Дългосрочно бъдеще и космически контекст\n"
        "      REPORTED_LEVEL: <LOW/MEDIUM/HIGH>\n"
        "      REASON_FOR_SELECTION: 2–4 изречения.\n"
        "  OBJECTIVE:\n"
        "    Малка, но реална стъпка за подобряване на дългосрочната устойчивост / намаляване на екзистенциален риск.\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие>\n"
        "    - STEP 2: ...\n"
        "  CROSS_AXIS_EFFECTS:\n"
        "    2–4 изречения как тази стъпка се свързва с HUMAN / PLANET / CIVILIZATION.\n\n"
        "GLOBAL_RISKS_AND_CHECKS:\n"
        "  - Изброй 3–6 ключови риска/ограничения за целия план (по всичките оси).\n"
        "  - За всеки риск добави по един прост check/метрика за следващия daily review.\n\n"
        "NEXT_REVIEW_SIGNALS:\n"
        "  - За HUMAN: <кратък индикатор>\n"
        "  - За PLANET: <кратък индикатор>\n"
        "  - За CIVILIZATION: <кратък индикатор>\n"
        "  - За COSMOS: <кратък индикатор>\n\n"
        "КОНТЕКСТ – AGI AXES SPEC (HUMAN / PLANET / CIVILIZATION / COSMOS):\n\n"
        f"{axes_spec}\n\n"
        "КОНТЕКСТ – ПОСЛЕДЕН DAILY REVIEW:\n\n"
        f"{daily_text}\n\n"
        "Сега генерирай САМО съдържанието на `plan-{today}.md` по горния формат.\n"
    )

def write_plan_file(today: str, content: str) -> Path:
    out_path = PLAN_DIR / f"plan-{today}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path

def main() -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    print(f"[HYPERCLAW] today={today}")
    print("[HYPERCLAW] reading latest daily review...")
    try:
        latest_path, daily_text = read_latest_daily_review()
    except Exception as e:
        print(f"[HYPERCLAW][ERROR] {e}")
        return

    print(f"[HYPERCLAW] using daily review: {latest_path.name}")
    axes_spec = safe_read(AXES_SPEC)

    print("[HYPERCLAW] building prompt...")
    prompt = build_hyperclaw_prompt(daily_text, axes_spec, today)

    print("[HYPERCLAW] calling internal LLM (QWEN)...")
    try:
        plan_md = call_internal_llm(prompt)
    except Exception as e:
        print(f"[HYPERCLAW][ERROR] {e}")
        return

    print("[HYPERCLAW] writing plan file...")
    out_path = write_plan_file(today, plan_md)
    print(f"[HYPERCLAW] done. Wrote: {out_path}")

if __name__ == "__main__":
    main()
