#!/usr/bin/env python3
import argparse
import json
import csv
from pathlib import Path
from datetime import datetime, timezone

try:
    from .groq_backend import call_groq
except ImportError:
    from groq_backend import call_groq

ENERGY_DATA_PATH = Path("data/energy/owid-energy-data.csv")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ======================================================================
#  REAL DATA: ENERGY (OWID CSV)
# ======================================================================

def load_energy_data():
    """
    Зарежда целия OWID energy CSV като list[dict] или връща None, ако липсва.
    """
    if not ENERGY_DATA_PATH.exists():
        return None
    rows = []
    with ENERGY_DATA_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def summarize_energy_indicator(rows, column: str, country: str = "World"):
    """
    Връща последната налична стойност за дадена метрика и държава.
    """
    filtered = [r for r in rows if r.get("country") == country and r.get(column)]
    if not filtered:
        return None
    latest = max(filtered, key=lambda r: int(r["year"]))
    try:
        value = float(latest[column])
    except ValueError:
        return None
    return {
        "metric": column,
        "year": int(latest["year"]),
        "country": country,
        "value": value,
    }


# ======================================================================
#  FALLBACK JSON КОГАТО LLM СЕ СЧУПИ
# ======================================================================

def build_dummy_json_energy(raw_context: str, error_message: str) -> dict:
    """
    Fallback за ENERGY: новият формат с оси + action_plan.
    """
    return {
        "status": "CRITICAL",
        "summary_bg": (
            "ENERGY_REVIEW не успя да завърши успешно LLM анализа "
            "(липсват ключови полета в JSON изхода или парсването се провали)."
        ),
        "key_findings_bg": [
            "Имаше грешка при извикването или парсването на cortex_llm_resource.py за домейна energy."
        ],
        "axes_assessment": [
            {
                "axis": "basic_needs_energy",
                "status": "UNKNOWN",
                "comment_bg": "Оценката не е налична заради грешка в LLM слоя."
            },
            {
                "axis": "justice_equity",
                "status": "UNKNOWN",
                "comment_bg": "Оценката не е налична заради грешка в LLM слоя."
            },
            {
                "axis": "climate_environment",
                "status": "UNKNOWN",
                "comment_bg": "Оценката не е налична заради грешка в LLM слоя."
            },
            {
                "axis": "future_generations",
                "status": "UNKNOWN",
                "comment_bg": "Оценката не е налична заради грешка в LLM слоя."
            },
            {
                "axis": "space_expansion",
                "status": "UNKNOWN",
                "comment_bg": "Оценката не е налична заради грешка в LLM слоя."
            }
        ],
        "metrics_interpretation_bg": [
            "Няма интерпретация на метрики, защото ENERGY_REVIEW не успя да получи валиден изход от LLM."
        ],
        "data_quality_bg": [
            f"Грешка от LLM слоя: {error_message}"
        ],
        "recommendations_bg": [
            "Да се провери cortex_llm_resource.py за домейна energy.",
            "Да се анализират контекстният файл в history/ и journal_resource_act.txt за детайли.",
            "Да се подсигури, че LLM prompt-ът и схемата за изход са коректни и стабилни."
        ],
        "action_plan": [
            {
                "id": "ENERGY-TACTIC-FAILSAFE-001",
                "level": "TECHNICAL",
                "actor": "CORTEX++",
                "scope": "ENERGY_SYSTEM",
                "time_horizon": "short",
                "description_bg": "Диагностика на LLM слоя за ENERGY_REVIEW и възстановяване на нормалната работа.",
                "expected_effect_bg": "Възстановява се способността за ежедневна оценка по осите и генериране на действия към целта."
            }
        ]
    }


def build_dummy_json_generic(domain: str, raw_context: str, error_message: str) -> dict:
    """
    Старият generic fallback за не-ENERGY домейни (диагноза/рискове/действия).
    """
    return {
        "diagnosis": {
            "status": "CRITICAL",
            "short_summary_bg": (
                f"LLM изходът за домейна {domain} не е валиден JSON "
                "или изобщо липсва. Анализът за този домейн е провален в този цикъл."
            ),
            "key_metrics": []
        },
        "risks": [],
        "opportunities": [],
        "recommended_actions": [],
        "notes_for_cortex_self_improvement": [
            "Да се диагностицира защо LLM не връща валиден JSON за този домейн.",
            "Да се прегледат raw LLM файловете в history/ и да се подобрят prompt-овете/моделът."
        ],
        "error_info": {
            "type": "llm_failure",
            "message": error_message,
            "timestamp_utc": utc_iso(),
        }
    }


# ======================================================================
#  GROQ API ВИКАНЕ + JSON ЕКСТРАКЦИЯ (Groq → Gemini → Ollama fallback)
# ======================================================================

def _llm_run(prompt: str) -> str:
    """
    Вика LLM чрез groq_backend (fallback chain: Groq → Gemini → Ollama).
    """
    return call_groq(prompt, max_tokens=2048)


def _extract_json_object(text: str) -> str:
    """
    Вади първия балансиран JSON обект `{ ... }` от text (може да има мисли преди/след него).
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("No '{' found in text")

    balance = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            balance += 1
        elif ch == "}":
            balance -= 1
            if balance == 0:
                end = i
                break

    if end == -1 or balance != 0:
        raise ValueError("Could not find balanced JSON object in text")

    return text[start: end + 1]


# ======================================================================
#  PROMPT ЗА ENERGY (ОСИ + КОНСТИТУЦИЯ + ACTION_PLAN)
# ======================================================================

def build_energy_system_prompt(raw_context: str) -> str:
    system_prompt = (
        "You are an internal civilization-scale ENERGY REVIEW agent inside the CORTEX++ system. "
        "Your job is to evaluate the GLOBAL ENERGY SYSTEM in a way that serves our long-term constitutional goals, "
        "not just data availability.\n\n"
        "CONSTITUTIONAL ORDER OF PRIORITIES (from highest to lower, but all important):\n"
        "1) Preserve and improve human life and basic wellbeing for everyone, now and in the future.\n"
        "2) Ensure justice and equity, especially for vulnerable and frontline communities.\n"
        "3) Protect climate and ecosystems and avoid catastrophic or irreversible damage.\n"
        "4) Safeguard the interests of future generations over short-term gains.\n"
        "5) Enable safe and sustainable space expansion of civilization when possible.\n\n"
        "AXES YOU MUST EVALUATE (think through them one by one):\n"
        "- basic_needs_energy: Can current and projected energy supply reliably cover basic human needs\n"
        "  (food, water, shelter, health, communication) for everyone?\n"
        "- justice_equity: Who benefits and who pays the cost of the energy system? Consider energy poverty,\n"
        "  regional inequalities, frontline communities, just transition.\n"
        "- climate_environment: What is the climate and ecological impact (GHG emissions, pollution,\n"
        "  ecosystem damage) of the energy mix and trajectory?\n"
        "- future_generations: Are we locking future generations into dangerous infrastructures, debts,\n"
        "  or irreversible risks, or are we expanding their option space?\n"
        "- space_expansion: Does the trajectory of the energy system increase or decrease our ability to safely\n"
        "  expand and operate beyond Earth in the long run?\n\n"
        "OUTPUT REQUIREMENTS (IMPORTANT):\n"
        "- Return a SINGLE JSON OBJECT.\n"
        "- All free text fields MUST be in Bulgarian.\n"
        "- Do NOT include explanations outside the JSON.\n"
        "- Use ONLY this structure:\n"
        "{\n"
        '  \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\",\n'
        '  \"summary_bg\": \"...\",\n'
        '  \"key_findings_bg\": [\"...\"],\n'
        '  \"axes_assessment\": [\n'
        "    {\"axis\": \"basic_needs_energy\", \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\", \"comment_bg\": \"...\"},\n"
        "    {\"axis\": \"justice_equity\", \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\", \"comment_bg\": \"...\"},\n"
        "    {\"axis\": \"climate_environment\", \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\", \"comment_bg\": \"...\"},\n"
        "    {\"axis\": \"future_generations\", \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\", \"comment_bg\": \"...\"},\n"
        "    {\"axis\": \"space_expansion\", \"status\": \"OK | STRESSED | CRITICAL | UNKNOWN\", \"comment_bg\": \"...\"}\n"
        "  ],\n"
        '  \"metrics_interpretation_bg\": [\"...\"],\n'
        '  \"data_quality_bg\": [\"...\"],\n'
        '  \"recommendations_bg\": [\"...\"],\n'
        '  \"action_plan\": [\n'
        "    {\n"
        "      \"id\": \"ENERGY-TACTIC-001\",\n"
        "      \"level\": \"TECHNICAL | ORGANIZATIONAL | POLITICAL | CIVILIZATIONAL\",\n"
        "      \"actor\": \"CORTEX++ | human_individual | human_collective | diplomacy_agent\",\n"
        "      \"scope\": \"например ENERGY_SYSTEM / CLIMATE / JUSTICE / FUTURE_GENERATIONS / SPACE\",\n"
        "      \"time_horizon\": \"short | medium | long\",\n"
        "      \"description_bg\": \"Конкретна стъпка или ход на български.\",\n"
        "      \"expected_effect_bg\": \"Как това придвижва системата по конституционните оси към визията.\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "DATA RULES / ЧИСЛА И ДАННИ:\n"
        "1) Когато имаш реални данни (например подадени метрики, CSV/JSON таблици): използвай ги точно и\n"
        "   изрично казвай, че са от реални данни.\n"
        "2) Когато НЯМА реални данни за дадена метрика: НЕ си измисляй числа, НЕ давай фалшиви точни оценки.\n"
        "   Обясни, че липсват данни и как това ограничава преценката.\n"
        "3) Когато ти липсват ключови данни: формулирай какви индикатори ти трябват и какви източници\n"
        "   трябва да се добавят; запиши това в data_quality_bg и/или recommendations_bg.\n\n"
        "ACTION PLAN RULES:\n"
        "- Минимум 3 и максимум 10 елемента в action_plan.\n"
        "- Разпредели действията по различни нива (TECHNICAL / ORGANIZATIONAL / POLITICAL / CIVILIZATIONAL).\n"
        "- Ясно посочи actor (кой реално е субектът на действието: CORTEX++, човешки индивид, колектив, diplomacy_agent).\n"
        "- В description_bg опиши конкретна, изпълнима стъпка, не общи пожелания.\n"
        "- В expected_effect_bg обясни как тази стъпка подобрява състоянието по една или повече оси отгоре.\n\n"
        "INTERNET DATA REQUEST RULES:\n"
        "- Ако ти липсват ключови количествени данни за енергийната система (например по държави, по човек, по източник),\n"
        "  не си измисляй числа.\n"
        "- Вместо това формулирай конкретни заявки за сваляне на OWID CSV данни, които човек или външен bridge ще изпълни.\n"
        "- Формат на всяка заявка (като отделен ред текст, който да бъде добавен в файл):\n"
        "  PENDING | OWID_CSV | energy | URL | кратко_обяснение_на_български\n"
        "- Когато имаш такива заявки, ги включи ясно в 'data_quality_bg' и/или 'recommendations_bg',\n"
        "  така че вътрешният AGI да може да ги запише в internet_requests/energy.txt чрез append-file.\n"
    )

    user_prompt = (
        "Следва контекст за ресурсни review (summary + описание на snapshot файловете). "
        "Използвай го, за да попълниш горния JSON.\n\n"
        "=== RAW_CONTEXT_START ===\n"
        f"{raw_context}\n"
        "=== RAW_CONTEXT_END ===\n"
    )

    return system_prompt + "\n\n" + user_prompt


def build_generic_prompt(domain: str, raw_context: str) -> str:
    """
    Старият generic prompt за не-ENERGY домейни (diagnosis/risks/...).
    """
    system_prompt = (
        "You are an internal AGI resource review agent in the CORTEX++ system. "
        f"Your domain is: {domain.upper()}.\n"
        "Your task is to return a single JSON object with the exact structure below.\n"
        "It is ALLOWED to think internally, but your final visible output MUST contain a valid JSON object.\n\n"
        "JSON structure:\n"
        "{\n"
        '  \"diagnosis\": {\n'
        '    \"status\": \"OK / STRESSED / CRITICAL\",\n'
        '    \"short_summary_bg\": \"...\",\n'
        '    \"key_metrics\": [\n'
        '      {\"name\": \"...\", \"value\": \"...\", \"interpretation_bg\": \"...\"}\n'
        "    ]\n"
        "  },\n"
        '  \"risks\": [\n'
        '    {\"name\": \"...\", \"description_bg\": \"...\", \"time_horizon\": \"short/medium/long\"}\n'
        "  ],\n"
        '  \"opportunities\": [\n'
        '    {\"name\": \"...\", \"description_bg\": \"...\"}\n'
        "  ],\n"
        '  \"recommended_actions\": [\n'
        '    {\"id\": \"...\", \"title_bg\": \"...\", \"description_bg\": \"...\", \"priority\": \"low/medium/high\"}\n'
        "  ],\n"
        '  \"notes_for_cortex_self_improvement\": [\n'
        '    \"...\"\n'
        "  ]\n"
        "}\n\n"
        "All Bulgarian text (fields *_bg) must be clear and concise.\n"
    )

    user_prompt = (
        "Следва контекст за ресурсни review (summary + описание на snapshot файловете). "
        "Използвай го, за да попълниш горния JSON.\n\n"
        "=== RAW_CONTEXT_START ===\n"
        f"{raw_context}\n"
        "=== RAW_CONTEXT_END ===\n"
    )

    return system_prompt + "\n\n" + user_prompt


# ======================================================================
#  ОБЩА ФУНКЦИЯ ЗА LLM С JSON
# ======================================================================

def call_ollama_json(domain: str, raw_context: str) -> dict:
    """
    Вика LLM (Groq → Gemini → Ollama fallback) със system+user prompt.
    ENERGY: новият формат с оси + action_plan; други домейни: старият generic формат.
    """
    base_dir = Path(__file__).resolve().parent
    history_dir = base_dir / "history"
    history_dir.mkdir(exist_ok=True)

    if domain.lower() == "energy":
        full_prompt = build_energy_system_prompt(raw_context)
    else:
        full_prompt = build_generic_prompt(domain, raw_context)

    # --- Първи опит ---
    content = _llm_run(full_prompt)

    ts = utc_iso().replace(":", "").replace("-", "")
    raw_path_1 = history_dir / f"llm_resource_raw_{domain}_{ts}_v1.txt"
    try:
        raw_path_1.write_text(content, encoding="utf-8")
    except Exception:
        pass

    try:
        json_str_1 = _extract_json_object(content)
        data = json.loads(json_str_1)
        if not isinstance(data, dict):
            raise RuntimeError("Top-level JSON is not an object (v1)")
    except Exception as e_first:
        # --- Втори опит: JSON repair agent ---
        repair_system = (
            "You are a strict JSON repair agent. "
            "Your ONLY job is to take possibly malformed text and output a single valid JSON object.\n"
            "Rules:\n"
            "- Ignore any text before or after the JSON object.\n"
            "- If JSON is inside markdown or other wrappers, extract just the JSON.\n"
            "- Output MUST be exactly one JSON object. No explanations, no markdown.\n"
        )
        repair_user = (
            "Here is the original model output that FAILED JSON parsing. "
            "Return ONLY a valid JSON object based on it.\n\n"
            "=== BROKEN_OUTPUT_START ===\n"
            f"{content}\n"
            "=== BROKEN_OUTPUT_END ===\n"
        )
        repair_prompt = repair_system + "\n\n" + repair_user

        content_repaired = _llm_run(repair_prompt)

        raw_path_2 = history_dir / f"llm_resource_raw_{domain}_{ts}_v2_repaired.txt"
        try:
            raw_path_2.write_text(content_repaired, encoding="utf-8")
        except Exception:
            pass

        try:
            json_str_2 = _extract_json_object(content_repaired)
            data = json.loads(json_str_2)
            if not isinstance(data, dict):
                raise RuntimeError("Repaired JSON top-level is not an object (v2)")
        except Exception as e_second:
            raise RuntimeError(
                f"JSON parsing failed (v1: {e_first}; v2(repair): {e_second})"
            )

    # --- STRICT SCHEMA VALIDATION FOR ENERGY ---
    if domain.lower() == "energy":
        required_keys = ["status", "summary_bg", "axes_assessment", "action_plan"]
        if not all(k in data for k in required_keys):
            raise RuntimeError("ENERGY JSON missing required keys for constitutional review")

    # --- INJECTION НА РЕАЛНИ МЕТРИКИ ЗА ENERGY ---
    if domain.lower() == "energy":
        energy_rows = load_energy_data()
        if energy_rows:
            available_cols = list(energy_rows[0].keys())
            if "energy_per_capita" in available_cols:
                energy_col = "energy_per_capita"
            elif "primary_energy_consumption" in available_cols:
                energy_col = "primary_energy_consumption"
            else:
                energy_col = None

            summary = None
            if energy_col is not None:
                summary = summarize_energy_indicator(
                    energy_rows,
                    column=energy_col,
                    country="World",
                )

            if summary:
                explanation = (
                    f"Реална стойност за {summary['country']} "
                    f"за {summary['year']} според файла owid-energy-data.csv "
                    f"за метрика {summary['metric']}."
                )
                metrics_interp = data.get("metrics_interpretation_bg") or []
                metrics_interp.append(explanation)
                data["metrics_interpretation_bg"] = metrics_interp

    return data


# ======================================================================
#  MAIN: ЧЕТЕ PROMPT ФАЙЛ, ПИШЕ JSON + test_resource_output.json
# ======================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    input_path = base_dir / args.input
    output_path = base_dir / args.output

    if not input_path.exists():
        text = json.dumps(
            {
                "error": f"Input prompt file not found: {input_path}",
                "timestamp_utc": utc_iso(),
            },
            ensure_ascii=False,
            indent=2,
        )
        output_path.write_text(text, encoding="utf-8")
        try:
            (base_dir / "test_resource_output.json").write_text(text, encoding="utf-8")
        except Exception:
            pass
        return

    raw_context = input_path.read_text(encoding="utf-8")

    try:
        data = call_ollama_json(args.domain, raw_context)
    except Exception as e:
        if args.domain.lower() == "energy":
            data = build_dummy_json_energy(raw_context, str(e))
        else:
            data = build_dummy_json_generic(args.domain, raw_context, str(e))

    text = json.dumps(data, ensure_ascii=False, indent=2)
    output_path.write_text(text, encoding="utf-8")

    try:
        (base_dir / "test_resource_output.json").write_text(text, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
