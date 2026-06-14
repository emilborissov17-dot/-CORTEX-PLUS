from __future__ import annotations

from typing import Callable, Dict, Any, List

from . import tools
from core import goals


def load_axes_spec() -> str:
    """
    Чете agi_axes_spec.txt и го връща като текстов блок за контекст.
    Ако файлът липсва или има грешка, връща кратко съобщение.
    """
    try:
        with open("agi_axes_spec.txt", "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return "AGI ОСИ: файлът agi_axes_spec.txt е празен."
        return (
            "AGI ОСИ (СПЕЦИФИКАЦИЯ):\n"
            "По-долу са описани осите на AGI/цивилизацията, включително PLANETARY_POTENTIAL_REVIEW.\n"
            "Използвай ги като карта за ориентация и за да сверяваш плановете и анализите си.\n\n"
            + content
        )
    except Exception as e:
        return f"AGI ОСИ: не успях да прочета agi_axes_spec.txt (грешка: {e})."


def build_system_prompt() -> str:
    """
    Сглобява системния контекст за агента:
    - глобални цели + визия + дървото ЧОВЕК–ПЛАНЕТА–ЦИВИЛИЗАЦИЯ–КОСМОС,
    - AGI оси (вкл. PLANETARY_POTENTIAL_REVIEW),
    - налични умения (tools/skills).
    ВРЪЩА ЕДИН ЕДИНСТВЕН ТЕКСТОВ PROMPT.
    """
    goal_ctx = goals.format_goal_context()
    axes_ctx = load_axes_spec()
    skills_desc = tools.SKILLS_DOC

    parts: List[str] = []
    parts.append("ТИ СИ ВЪТРЕШЕН AGI АГЕНТ НА CORTEX++.")
    parts.append("")
    parts.append("КОНТЕКСТ ЗА ЦЕЛИТЕ И ДЪРВОТО НА ЦИВИЛИЗАЦИЯТА:")
    parts.append(goal_ctx)
    parts.append("")
    parts.append("КОНТЕКСТ ЗА AGI ОСИТЕ (ВКЛЮЧИТЕЛНО PLANETARY_POTENTIAL_REVIEW):")
    parts.append(axes_ctx)
    parts.append("")
    parts.append("НАЛИЧНИ УМЕНИЯ (SKILLS / TOOLS):")
    parts.append(skills_desc)
    parts.append("")
    parts.append(
        "Когато планираш отговор или действие, мисли през дървото ЧОВЕК–ПЛАНЕТА–ЦИВИЛИЗАЦИЯ–КОСМОС, "
        "през AGI осите (особено PLANETARY_POTENTIAL_REVIEW) и крайната цел: устойчива общочовешка цивилизация "
        "и достоен живот за всеки, без да се нарушават планетарните граници."
    )

    return "\n".join(parts)


def build_full_prompt(user_input: str) -> str:
    """
    Строи ЕДИН комбиниран prompt за LLM:
    - системен контекст
    - + задачата от човека.
    Това съответства на llm_call(prompt: str) в test_agent_loop.py.
    """
    system_block = build_system_prompt()
    user_block = "ЗАДАЧА ОТ ЧОВЕКА:\n" + user_input.strip()
    return system_block + "\n\n" + user_block


def agent_iteration(
    user_input: str,
    llm_call_fn: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Една итерация на агента:
    - сглобява единствен комбиниран prompt,
    - вика LLM с един аргумент (както очаква test_agent_loop.llm_call),
    - връща целия отговор.
    """
    full_prompt = build_full_prompt(user_input)
    response = llm_call_fn(full_prompt)
    return response
