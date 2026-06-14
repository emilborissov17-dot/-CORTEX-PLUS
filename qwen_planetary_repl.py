from __future__ import annotations

from pathlib import Path
from core.llm_backend import call_internal_llm

ROOT = Path(__file__).resolve().parent

PLANETARY_SYSTEM_PROMPT = """
Ти си QWEN_PLANETARY_POTENTIAL_REVIEW_AGENT, част от CORTEX++_QWEN.

ЗАДАЧА:
  - ВРЪЩАШ САМО един Markdown документ със СЛЕДНИЯ ТОЧЕН СКЕЛЕТ.
  - НЕ ДОБАВЯШ нищо извън този скелет (никакъв обяснителен текст преди или след него).
  - ЗАДЪЛЖИТЕЛНО включваш секцията ## PLANET_STATE и всички под-секции вътре.

СКЕЛЕТ (ЗАДЪЛЖИТЕЛЕН, КОПИРАЙ ГО И ГО ПОПЪЛНИ):

# PLANETARY POTENTIAL REVIEW – YYYY-MM-DD

## PLANET_STATE
- CLIMATE_GLOBAL_RISK:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- ENERGY:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- WATER:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- FOOD:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- MATERIALS_WASTE:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- ECOSYSTEMS_BIODIVERSITY:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- PLANETARY_POTENTIAL:
  - LEVEL: LOW | MEDIUM | HIGH
  - SUMMARY:
    - ...

## BOTTLENECKS
- ...

## TRADE_OFFS
- ...

## PLANETARY_ACTIONS
- ...

## RISKS_AND_GUARDS
- ...

## RAW_PLANETARY_FOCUS
- ...

ПРАВИЛА:
  - НЕ използвай префикси като "Thinking..." или "done thinking.".
  - НЕ обяснявай формата, просто го следвай.
  - Пиши на български.
"""


def strip_to_planetary_markdown(raw: str) -> str:
    """
    Връща само частта от отговора, която започва от
    '# PLANETARY POTENTIAL REVIEW'.
    Ако не я намери, връща оригиналния текст.
    """
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# PLANETARY POTENTIAL REVIEW"):
            return "\n".join(lines[i:])
    return raw


def main() -> None:
    prompt = PLANETARY_SYSTEM_PROMPT

    print("[QWEN_PLANETARY_REPL] calling internal LLM (QWEN)...")
    raw = call_internal_llm(prompt)
    clean = strip_to_planetary_markdown(raw)
    print("===== QWEN RAW OUTPUT START =====")
    print(clean)
    print("===== QWEN RAW OUTPUT END =====")


if __name__ == "__main__":
    main()
