import json
from pathlib import Path
from datetime import datetime, UTC

import requests

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"
INPUT_BRIEF = KNOWLEDGE_DIR / "energy_brief_latest.txt"

GAPS_JSON = KNOWLEDGE_DIR / "energy_data_gaps.json"
GAPS_MD = KNOWLEDGE_DIR / "energy_data_gaps.md"

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "qwen3:8b"


def load_energy_brief() -> str:
    if not INPUT_BRIEF.exists():
        return "[NO_ENERGY_BRIEF]\nenergy_brief_latest.txt not found.\n"
    return INPUT_BRIEF.read_text(encoding="utf-8")


def build_messages(brief_text: str) -> list[dict]:
    system_msg = {
        "role": "system",
        "content": (
            "Ти си AGI агент (Qwen) по ос ENERGY вътре в CORTEX++.\n"
            "Получаваш консолидиран файл energy_brief_latest.txt, който съдържа:\n"
            "- последния ENERGY REVIEW (текстов анализ на глобалната енергийна система)\n"
            "- план със задачи за CORTEX++ по ENERGY.\n\n"
            "Твоята роля ТУК е само една: да извлечеш СТРУКТУРИРАН СПИСЪК ОТ DATA GAPS\n"
            "в стил „къде сме слепи или с недостатъчни данни по ENERGY“.\n\n"
            "Под „data gaps“ имаме предвид пропуски като:\n"
            "- липсващ достъп до важни институции/източници (напр. IEF)\n"
            "- непълни времеви серии или лоша резолюция\n"
            "- липсващи KPI, липсващи полета в данните\n"
            "- политически/организационни ограничения за достъп до данни.\n\n"
            "ФОРМАТ НА ИЗХОДА (ЗАДЪЛЖИТЕЛЕН):\n"
            "Кратък Markdown списък от data gaps, всеки в следния формат:\n"
            "#### N. **Title**\n"
            "**Description:** ...\n"
            "**Data Needed:** ...\n"
            "**Context:** ...\n\n"
            "НЕ пишеш JSON, само Markdown. Пиши на български, освен имената на институции/API.\n"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            "Това е съдържанието на energy_brief_latest.txt:\n\n"
            f"{brief_text}\n\n"
            "На база на това, извлечи ENERGY DATA GAPS в описания по-горе Markdown формат."
        ),
    }

    return [system_msg, user_msg]


def call_qwen(messages: list[dict]) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.3,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_md_to_gaps(md_text: str) -> list[dict]:
    gaps: list[dict] = []
    lines = [l.rstrip() for l in md_text.splitlines()]

    current = None
    desc_lines = []
    data_lines = []
    context_line = ""

    def flush_current():
        nonlocal current, desc_lines, data_lines, context_line
        if current is None:
            return
        gap_id = f"gap_{len(gaps)+1:03d}"
        gap = {
            "id": gap_id,
            "axis": "ENERGY",
            "source_region": "UNSPECIFIED",
            "what_missing": "",
            "why_important": "",
            "impact_if_ignored": "",
            "suggested_sources": [],
            "priority": "MEDIUM",
            "notes": "",
        }

        title = current.get("title", "").strip()
        if title:
            gap["notes"] = title

        desc = " ".join(desc_lines).strip()
        data_needed = " ".join(data_lines).strip()
        ctx = context_line.strip()

        gap["what_missing"] = data_needed or desc
        gap["why_important"] = desc or data_needed

        # сурово определяне на регион
        if "GLOBAL" in ctx.upper():
            gap["source_region"] = "GLOBAL"
        elif "EU" in ctx.upper():
            gap["source_region"] = "EU"

        if "HIGH" in ctx.upper():
            gap["priority"] = "HIGH"

        sources = []
        for token in ["ENTSO-E", "IEA", "NREL", "IEF", "World Bank", "TSO"]:
            if token in data_needed:
                sources.append(token)
        gap["suggested_sources"] = sorted(set(sources))

        gaps.append(gap)

        current = None
        desc_lines = []
        data_lines = []
        context_line = ""

    for line in lines:
        if line.startswith("#### "):
            flush_current()
            # пример: "#### 1. **Title**"
            title = line.split("**")
            if len(title) >= 2:
                title_text = title[1]
            else:
                title_text = line[4:].strip()
            current = {"title": title_text}
        elif line.startswith("**Description:**"):
            desc_lines.append(line.split("**Description:**", 1)[1].strip())
        elif line.startswith("**Data Needed:**"):
            data_lines.append(line.split("**Data Needed:**", 1)[1].strip())
        elif line.startswith("**Context:**"):
            context_line = line.split("**Context:**", 1)[1].strip()
        else:
            if desc_lines and not line.startswith("**"):
                desc_lines.append(line.strip())
            elif data_lines and not line.startswith("**"):
                data_lines.append(line.strip())

    flush_current()
    return gaps


def save_outputs(md_text: str, gaps_list: list[dict]):
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    header_md = f"\n\n=== ENERGY_DATA_GAPS RUN @ {ts} UTC ===\n\n"
    GAPS_MD.parent.mkdir(exist_ok=True)
    with GAPS_MD.open("a", encoding="utf-8") as f_md:
        f_md.write(header_md)
        f_md.write(md_text.strip())
        f_md.write("\n")

    out = {
        "generated_at_utc": ts,
        "axis": "ENERGY",
        "gaps": gaps_list,
    }
    GAPS_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    print("[ENERGY_DATA_GAPS_V2] loading energy_brief_latest.txt...")
    brief = load_energy_brief()

    print("[ENERGY_DATA_GAPS_V2] building prompt...")
    messages = build_messages(brief)

    print("[ENERGY_DATA_GAPS_V2] calling Qwen via Ollama...")
    try:
        md_answer = call_qwen(messages)
    except Exception as e:
        print(f"[ENERGY_DATA_GAPS_V2][ERROR] {e}")
        return

    print("[ENERGY_DATA_GAPS_V2] parsing MD to gaps JSON...")
    gaps_list = parse_md_to_gaps(md_answer)

    print(f"[ENERGY_DATA_GAPS_V2] parsed {len(gaps_list)} gaps.")
    print("[ENERGY_DATA_GAPS_V2] saving outputs...")
    save_outputs(md_answer, gaps_list)

    print("[ENERGY_DATA_GAPS_V2] done.")


if __name__ == "__main__":
    main()
