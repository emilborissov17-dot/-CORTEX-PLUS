from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

from core.llm_backend import call_internal_llm  # централен LLM gateway

ROOT = Path(__file__).resolve().parent
PLANETARY_DIR = ROOT / "planetary"
PLANETARY_DIR.mkdir(exist_ok=True)

CORE_ROLE = ROOT / "core_role.txt"
AXES_SPEC = ROOT / "agi_axes_spec.txt"
IDENTITY = ROOT / "IDENTITY.md"
SOUL = ROOT / "SOUL.md"
USER = ROOT / "USER.md"
HEARTBEAT = ROOT / "HEARTBEAT.md"
MEMORY = ROOT / "MEMORY.md"

SNAPSHOT_ROOT = Path("./snapshots/planet")


def safe_read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def load_planetary_snapshots() -> Dict[str, Any]:
    """
    Чете всички *snapshot_latest.json под ./snapshots/planet/* и ги връща като dict:
    { "ENERGY": {...}, "WATER": {...}, ... }
    """
    snapshots: Dict[str, Any] = {}

    print(f"[PLANETARY_POTENTIAL_REVIEW] looking for snapshots in {SNAPSHOT_ROOT}")
    if not SNAPSHOT_ROOT.exists():
        print(f"[PLANETARY_POTENTIAL_REVIEW][WARN] {SNAPSHOT_ROOT} does not exist. Continuing without snapshots.")
        return snapshots

    any_found = False
    for subdir in SNAPSHOT_ROOT.iterdir():
        if not subdir.is_dir():
            continue
        for f in subdir.glob("*_snapshot_latest.json"):
            any_found = True
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            key = subdir.name.upper()
            snapshots[key] = {
                "file": str(f),
                "data": data,
            }
            break

    if not any_found:
        print("[PLANETARY_POTENTIAL_REVIEW][WARN] no *_snapshot_latest.json files found. Continuing with empty snapshots.")

    return snapshots


def next_review_index(today: str) -> int:
    files = sorted(
        PLANETARY_DIR.glob(f"planetary_potential_review-{today}-*.md"),
        key=lambda p: p.name,
    )
    return len(files) + 1


def build_context_block() -> str:
    parts: List[str] = []

    core_role_txt = safe_read_text(CORE_ROLE)
    if core_role_txt:
        parts.append("=== core_role.txt ===\n" + core_role_txt)

    axes_spec_txt = safe_read_text(AXES_SPEC)
    if axes_spec_txt:
        parts.append("=== agi_axes_spec.txt ===\n" + axes_spec_txt)

    id_txt = safe_read_text(IDENTITY)
    if id_txt:
        parts.append("=== IDENTITY.md ===\n" + id_txt)

    soul_txt = safe_read_text(SOUL)
    if soul_txt:
        parts.append("=== SOUL.md ===\n" + soul_txt)

    user_txt = safe_read_text(USER)
    if user_txt:
        parts.append("=== USER.md ===\n" + user_txt)

    heartbeat_txt = safe_read_text(HEARTBEAT)
    if heartbeat_txt:
        parts.append("=== HEARTBEAT.md ===\n" + heartbeat_txt)

    memory_doc = safe_read_text(MEMORY)
    if memory_doc:
        parts.append("=== MEMORY.md ===\n" + memory_doc)

    if not parts:
        return "Няма наличен висококонтекст (core_role, agi_axes_spec, IDENTITY/SOUL/USER/HEARTBEAT/MEMORY)."

    return "\n\n".join(parts)


def format_snapshots_for_prompt(snapshots: Dict[str, Any]) -> str:
    if not snapshots:
        return "Няма налични planetary snapshot-и."

    lines: List[str] = []
    for axis, payload in snapshots.items():
        lines.append(f"=== {axis}_SNAPSHOT ===")
        lines.append(f"FILE: {payload.get('file', 'UNKNOWN')}")
        try:
            pretty = json.dumps(payload.get("data", {}), ensure_ascii=False, indent=2)
        except Exception:
            pretty = str(payload.get("data", {}))
        lines.append(pretty)
        lines.append("")
    return "\n".join(lines)


PLANETARY_SYSTEM_PROMPT = """
RESPOND ONLY IN ENGLISH. DO NOT USE CHINESE OR ANY OTHER LANGUAGE.

Ти си QWEN_PLANETARY_POTENTIAL_REVIEW_AGENT, част от CORTEX++_QWEN.

ЗАДАЧА:
  - ВРЪЩАШ САМО един Markdown документ със СЛЕДНИЯ ТОЧЕН СКЕЛЕТ.
  - НЕ ДОБАВЯШ нищо извън този скелет (никакъв обяснителен текст преди или след него).
  - ЗАДЪЛЖИТЕЛНО включваш секцията ## PLANET_STATE и всички под-секции вътре.
  - Използваш реалните planetary snapshot-и и контекста по-долу за да попълниш LEVEL и SIGNALS, но ако липсват snapshot-и, все пак попълваш осите на база контекста.

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
    if not raw:
        return raw
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# PLANETARY POTENTIAL REVIEW"):
            return "\n".join(lines[i:])
    return raw.strip()


def build_prompt(context_block: str, snapshots_block: str) -> str:
    """
    Ясен, тесен prompt: твърд скелет + контекст + planetary snapshots.
    """
    return (
        PLANETARY_SYSTEM_PROMPT
        + "\n\n=== HIGH_LEVEL_CONTEXT ===\n"
        + context_block
        + "\n\n=== PLANETARY_SNAPSHOTS ===\n"
        + snapshots_block
    )


def wrap_in_protocol(today: str, review_index: int, raw_body: str) -> str:
    """
    Увива Markdown блока в стабилен протоколен header за файловете.
    """
    header = (
        f"# PLANETARY POTENTIAL REVIEW – {today}\n\n"
        "META:\n"
        f"  DATE: {today}\n"
        "  REVIEW_AGENT: QWEN_PLANETARY_POTENTIAL_REVIEW_AGENT\n"
        f"  REVIEW_INDEX: {review_index}\n"
        "  SOURCES:\n"
        "    - snapshots/planet/*/*_snapshot_latest.json\n"
        "    - core_role.txt\n"
        "    - agi_axes_spec.txt\n"
        "    - IDENTITY.md, SOUL.md, USER.md, HEARTBEAT.md\n"
        "    - MEMORY.md\n\n"
    )
    return header + raw_body.strip() + "\n"


def write_planetary_review(today: str, review_index: int, content: str) -> Path:
    out_path = PLANETARY_DIR / f"planetary_potential_review-{today}-{review_index:03d}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[PLANETARY_POTENTIAL_REVIEW] today={today}")

    print("[PLANETARY_POTENTIAL_REVIEW] loading context...")
    context_block = build_context_block()

    print("[PLANETARY_POTENTIAL_REVIEW] loading planetary snapshots...")
    snapshots = load_planetary_snapshots()
    snapshots_block = format_snapshots_for_prompt(snapshots)

    review_index = next_review_index(today)
    print(f"[PLANETARY_POTENTIAL_REVIEW] review_index={review_index}")

    prompt = build_prompt(context_block, snapshots_block)

    print("[PLANETARY_POTENTIAL_REVIEW] calling internal LLM (QWEN)...")
    try:
        raw = call_internal_llm(prompt)
    except Exception as e:
        print(f"[PLANETARY_POTENTIAL_REVIEW][ERROR] {e}")
        return

    cleaned_body = strip_to_planetary_markdown(raw)

    if "## PLANET_STATE" not in cleaned_body:
        print("[PLANETARY_POTENTIAL_REVIEW][ERROR] missing ## PLANET_STATE in LLM output")
        print("===== RAW PLANETARY RESPONSE START =====")
        print(raw[:2000])
        print("===== RAW PLANETARY RESPONSE END =====")
        return

    print("===== RAW PLANETARY RESPONSE START =====")
    print(raw[:2000])
    print("===== RAW PLANETARY RESPONSE END =====")
    print("===== CLEANED PLANETARY RESPONSE START =====")
    print(cleaned_body[:2000])
    print("===== CLEANED PLANETARY RESPONSE END =====")

    wrapped = wrap_in_protocol(today, review_index, cleaned_body)

    out_path = write_planetary_review(today, review_index, wrapped)
    print(f"[PLANETARY_POTENTIAL_REVIEW] done. Wrote: {out_path}")


if __name__ == "__main__":
    main()
