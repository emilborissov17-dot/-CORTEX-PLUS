from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(r"C:\Users\emilb\Desktop\AGI\CORTEX++")

CIVILIZATION_GOAL_PATH = BASE_DIR / "civilization_goal.txt"
CIVILIZATION_VISION_PATH = BASE_DIR / "civilization_vision.txt"
GOAL_SUMMARY_PATH = BASE_DIR / "goal_summary.txt"
NEXT_ACTIONS_PATH = BASE_DIR / "next_actions.txt"


# =========================
# SAFE FILE READ HELPERS
# =========================

def _safe_read(path: Path, label: str) -> str:
    try:
        if not path.exists():
            return f"[{label}] MISSING: {path.name} не съществува."
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return f"[{label}] EMPTY: {path.name} е празен."
        return text
    except Exception as e:
        return f"[{label}] ERROR reading {path.name}: {e}"


def load_global_goal() -> str:
    return _safe_read(CIVILIZATION_GOAL_PATH, "GLOBAL_GOAL")


def load_civilization_vision() -> str:
    return _safe_read(CIVILIZATION_VISION_PATH, "CIVILIZATION_VISION")


def load_goal_summary() -> str:
    return _safe_read(GOAL_SUMMARY_PATH, "GOAL_SUMMARY")


def load_next_actions() -> str:
    return _safe_read(NEXT_ACTIONS_PATH, "NEXT_ACTIONS")


# =========================
# CIVILIZATION TREE (ЧОВЕК–ПЛАНЕТА–ЦИВИЛИЗАЦИЯ–КОСМОС)
# =========================

def get_civilization_tree() -> Dict[str, Any]:
    """
    Официалната структура на дървото:

    ЧОВЕК – ум, дух/смисъл, тяло, отношения
    ПЛАНЕТА – енергия, вода, храна, материали/отпадъци, екосистеми, климат
    ЦИВИЛИЗАЦИЯ – инфраструктура/градове, икономика/разпределение, здраве,
                  образование, неравенства/права, институции/управление,
                  култура/медия, технологии/AGI-ASI
    КОСМОС – глобални рискове, космически ресурси и заселване,
             дългосрочно оцеляване
    """
    return {
        "human": {
            "label_bg": "ЧОВЕК",
            "axes": [
                "ум",
                "дух/смисъл",
                "тяло",
                "отношения",
            ],
        },
        "planet": {
            "label_bg": "ПЛАНЕТА",
            "axes": [
                "енергия",
                "вода",
                "храна",
                "материали/отпадъци",
                "екосистеми",
                "климат",
            ],
        },
        "civilization": {
            "label_bg": "ЦИВИЛИЗАЦИЯ",
            "axes": [
                "инфраструктура/градове",
                "икономика/разпределение",
                "здраве",
                "образование",
                "неравенства/права",
                "институции/управление",
                "култура/медия",
                "технологии/AGI-ASI",
            ],
        },
        "cosmos": {
            "label_bg": "КОСМОС",
            "axes": [
                "глобални рискове",
                "космически ресурси и заселване",
                "дългосрочно оцеляване",
            ],
        },
        "ultimate_goal": (
            "Устойчива общочовешка цивилизация, достоен живот за всеки, "
            "разгърнат ум–дух–тяло, AGI в прозрачен „балон“ в служба на тази цел."
        ),
    }


def format_civilization_tree() -> str:
    """
    Човешко-четимо представяне на дървото, за използване в промптове и логи.
    """
    tree = get_civilization_tree()
    lines: list[str] = []

    lines.append("CIVILIZATION TREE (ЧОВЕК–ПЛАНЕТА–ЦИВИЛИЗАЦИЯ–КОСМОС):")
    lines.append("")

    for key in ("human", "planet", "civilization", "cosmos"):
        node = tree[key]
        label = node["label_bg"]
        axes = node["axes"]
        lines.append(f"{label}:")
        for ax in axes:
            lines.append(f"  - {ax}")
        lines.append("")

    lines.append("ULTIMATE GOAL:")
    lines.append(tree["ultimate_goal"])

    return "\n".join(lines)


# =========================
# MAIN GOAL CONTEXT FOR AGENTS
# =========================

def format_goal_context() -> str:
    """
    Връща пълния контекст за целите на CORTEX++:

    - глобална цел,
    - визия за цивилизацията,
    - summary и next actions,
    - дървото ЧОВЕК–ПЛАНЕТА–ЦИВИЛИЗАЦИЯ–КОСМОС и крайната цел.
    """
    global_goal = load_global_goal()
    vision = load_civilization_vision()
    summary = load_goal_summary()
    next_actions = load_next_actions()
    tree_str = format_civilization_tree()

    lines: list[str] = []
    lines.append("GLOBAL GOAL:")
    lines.append(global_goal)
    lines.append("")
    lines.append("CIVILIZATION VISION:")
    lines.append(vision)
    lines.append("")
    lines.append("CORTEX++ GOAL SUMMARY:")
    lines.append(summary)
    lines.append("")
    lines.append("CURRENT NEXT_ACTIONS:")
    lines.append(next_actions)
    lines.append("")
    lines.append(tree_str)

    return "\n".join(lines)
