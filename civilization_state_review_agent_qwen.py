from __future__ import annotations

from pathlib import Path
from datetime import date
from core.llm_backend import call_internal_llm
from core.protocol_utils import wrap_in_protocol  # ако е в друг модул, адаптирай path-а


BASE_DIR = Path(__file__).resolve().parent
CIVILIZATION_DIR = BASE_DIR / "civilization"
CIVILIZATION_DIR.mkdir(exist_ok=True)


CIVILIZATION_SYSTEM_PROMPT = """
Ти си QWEN_CIVILIZATION_STATE_REVIEW_AGENT, част от CORTEX++_QWEN.

ТВОЯТА ЗАДАЧА:
  - Правиш дневен CIVILIZATION STATE REVIEW, подравнен с agi_axes_spec.txt (секция CIVILIZATION).
  - Използваш:
    - последния PLANETARY POTENTIAL REVIEW (за контекст от PLANET),
    - civilization/*_snapshot_latest.json (икономика, институции, технологии и др., когато са налични),
    - MEMORY.md, HEARTBEAT.md, USER.md, SOUL.md, IDENTITY.md.

ФОРМАТ НА ИЗХОДА (ЗАДЪЛЖИТЕЛЕН):

# CIVILIZATION STATE REVIEW – YYYY-MM-DD

## CIVILIZATION_STATE
- ECONOMY_WORK:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - конкретни факти/тенденции
- INEQUALITY_POVERTY:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- INFRASTRUCTURE_CITIES:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- GOVERNANCE_INSTITUTIONS:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- EDUCATION_CULTURE:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- TECHNOLOGY_INFRA:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- TECHNOLOGY_AI:
  - LEVEL: LOW | MEDIUM | HIGH
  - SIGNALS:
    - ...
- INTEGRATED_CIVILIZATION_HEALTH:
  - LEVEL: LOW | MEDIUM | HIGH
  - SUMMARY:
    - 2–4 изречения, обобщаващи общото състояние на цивилизацията

## STRUCTURAL_BOTTLENECKS
- изброи 3–7 най-дълбоки структурни bottlenecks (по CIVILIZATION осите)

## CIVILIZATION_ACTIONS
- предложи 3–7 действия (политики, технологични промени, институционални реформи),
  които реалистично биха подобрили състоянието

## RISKS_AND_FAIL_MODES
- изброи основни начини, по които нещата могат да се счупят (fail modes),
  ако нищо не се промени или ако действията се изпълнят зле

## LINKS_TO_PLANET_AND_HUMAN
- 3–5 bullets как текущото цивилизационно състояние:
  - влияе на PLANET (оси от PLANETARY_POTENTIAL_REVIEW)
  - влияе на HUMAN (човешко благосъстояние, култура и медии)

## RAW_CIVILIZATION_FOCUS
- Тук копираш суровото си мислене/обосновка:
  - как използваш agi_axes_spec.txt (CIVILIZATION)
  - как свързваш данните от PLANET и civilization snapshot-ите
  - защо избираш конкретни LEVEL-и и bottlenecks

ПРАВИЛА:
  - НЕ използвай префикси като "Thinking..." или "done thinking." в изхода.
  - НЕ обяснявай формата, просто го следвай.
  - Пиши на български.
"""


def load_latest_planet_review() -> str:
    files = sorted((BASE_DIR / "planetary").glob("planetary_potential_review-*.md"))
    if not files:
        return ""
    return files[-1].read_text(encoding="utf-8")


def build_civilization_prompt() -> str:
    today = date.today().isoformat()
    planet_review = load_latest_planet_review()

    ctx_parts: list[str] = []

    agi_axes = (BASE_DIR / "agi_axes_spec.txt").read_text(encoding="utf-8")
    ctx_parts.append("=== AGI_AXES_SPEC (CIVILIZATION) ===\n" + agi_axes)

    if planet_review:
        ctx_parts.append("=== LATEST_PLANETARY_POTENTIAL_REVIEW ===\n" + planet_review)

    for name in ["MEMORY.md", "HEARTBEAT.md", "USER.md", "SOUL.md", "IDENTITY.md"]:
        p = BASE_DIR / name
        if p.exists():
            ctx_parts.append(f"=== {name} ===\n" + p.read_text(encoding="utf-8"))

    full_context = "\n\n".join(ctx_parts)

    return (
        CIVILIZATION_SYSTEM_PROMPT
        + "\n\nДАТА:\n"
        + today
        + "\n\nКОНТЕКСТ (прочети и после направи ревюто по формата по-горе):\n"
        + full_context
        + "\n\nОТГОВОР:\n"
    )


def main() -> None:
    today = date.today().isoformat()
    print(f"[CIVILIZATION_STATE_REVIEW] today={today}")

    prompt = build_civilization_prompt()
    print("[CIVILIZATION_STATE_REVIEW] calling internal LLM (QWEN)...")

    raw = call_internal_llm(prompt)

    wrapped = wrap_in_protocol(
        axis="CIVILIZATION_STATE_REVIEW",
        today=today,
        review_agent="QWEN_CIVILIZATION_STATE_REVIEW_AGENT",
        review_index=None,
        raw_block=raw,
    )

    out_path = CIVILIZATION_DIR / f"civilization_state_review-{today}-001.md"
    out_path.write_text(wrapped, encoding="utf-8")
    print(f"[CIVILIZATION_STATE_REVIEW] done. Wrote: {out_path}")


if __name__ == "__main__":
    main()
