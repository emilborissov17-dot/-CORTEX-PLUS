# SESSION STATE — 2026-06-21

## DONE

### hyperclaw silent-failure → needs_reanalysis marker
**Файл:** `agents/hyperclaw/hyperclaw_orchestrator.py`  
**Commit:** `c0f75a6`

Разделен `except Exception` на два клона:
- `AllBackendsFailedError` → пише `snapshots/hyperclaw/hyperclaw_snapshot_latest.json`
  с `needs_reanalysis: True` (подхваща се от `_scan_needs_reanalysis()` в следващия цикъл)
- generic `Exception` → само логва, без raise

---

## TODO СЛЕДВАЩО (по приоритет)

### 1. Parser fix в `_hyperclaw_to_proposals()` — ГОТОВ КОД

> **ГОТОВ КОД — само за прилагане + изолиран тест. НЕ пренаписвай.**
>
> Тест преди commit:
> ```
> python -c "import sys; sys.path.insert(0,'.'); from fast_cycle_runner import _hyperclaw_to_proposals; _hyperclaw_to_proposals()"
> ```
> → чакай `12 proposals injected`. Чак тогава commit. НЕ пълен цикъл при изчерпана quota.
>
> Дребно почистване в `hyperclaw_orchestrator.py`: махни дублирания import (ред 2)
> и дублирания print в generic except.

**Проблем:** Текущият парсер връща 0 proposals защото търси точни стрингове:
- `line.startswith("OBJECTIVE:")` — но LLM пише `**OBJECTIVE**: text`
- `line.startswith("- STEP")` — но LLM пише `1. **bold** – description`

**Реален LLM формат** (от `plans/plan-2026-06-20.md`):
```
## HUMAN_AXIS_FOCUS
**OBJECTIVE**: Подобряване на...

**PLAN_STEPS**
1. **Стартиране на...** – описание
2. **Дневен модерационен цикъл** – описание

**CROSS_AXIS_EFFECTS**
...
```

**Готовата функция** (заменя изцяло `_hyperclaw_to_proposals` в `fast_cycle_runner.py`):

```python
def _hyperclaw_to_proposals():
    """Convert the latest HyperClaw markdown plan to improvement proposals."""
    import re as _re

    _AXIS_RE    = _re.compile(r'(HUMAN|PLANET|CIVILIZATION|COSMOS)_AXIS_FOCUS')
    _OBJ_RE     = _re.compile(r'\*{0,2}OBJECTIVE\*{0,2}\s*:\s*(.+)', _re.IGNORECASE)
    _STEP_START = _re.compile(r'\*{0,2}PLAN_STEPS\*{0,2}', _re.IGNORECASE)
    _STEP_END   = _re.compile(r'\*{0,2}CROSS_AXIS', _re.IGNORECASE)
    _STEP_RE    = _re.compile(r'^\d+[.)]\s+(.+)')

    plans_dir = BASE / "plans"
    proposals_path = BASE / "memory" / "improvement_proposals.json"
    if not plans_dir.exists():
        return
    plan_files = sorted(plans_dir.glob("plan-*.md"), key=lambda p: p.name, reverse=True)
    if not plan_files:
        print("[FAST_CYCLE] hyperclaw_to_proposals -> no plan file found")
        return
    plan_text = plan_files[0].read_text(encoding="utf-8", errors="ignore")
    new_proposals = []
    current_axis = None
    in_steps = False
    for line in plan_text.splitlines():
        stripped = line.strip()

        m = _AXIS_RE.search(stripped)
        if m:
            current_axis = m.group(1)
            in_steps = False
            continue

        if _STEP_START.search(stripped):
            in_steps = True
            continue

        if _STEP_END.search(stripped):
            in_steps = False
            continue

        m = _OBJ_RE.match(stripped)
        if m and current_axis:
            objective = _re.sub(r'\*+', '', m.group(1)).strip()
            if objective and objective != "<цел>" and len(objective) > 10:
                new_proposals.append({
                    "component":        current_axis,
                    "problem":          f"{current_axis} axis needs progress",
                    "solution":         objective,
                    "measurable_goal":  objective[:80],
                    "root_cause":       f"HyperClaw plan — {plan_files[0].name}",
                    "priority":         "MEDIUM",
                    "real_world_signal": True,
                    "generated_by":     "HYPERCLAW",
                    "timestamp":        _utc_now(),
                })
            continue

        if in_steps and current_axis:
            m = _STEP_RE.match(stripped)
            if m:
                step = _re.sub(r'\*+', '', m.group(1)).strip()
                if step and "<" not in step and len(step) > 10:
                    new_proposals.append({
                        "component":        current_axis,
                        "problem":          f"Action required for {current_axis}",
                        "solution":         step,
                        "measurable_goal":  step[:80],
                        "root_cause":       f"HyperClaw step — {plan_files[0].name}",
                        "priority":         "MEDIUM",
                        "real_world_signal": True,
                        "generated_by":     "HYPERCLAW",
                        "timestamp":        _utc_now(),
                    })

    if not new_proposals:
        print("[FAST_CYCLE] hyperclaw_to_proposals -> 0 concrete steps extracted")
        return
    try:
        existing = json.loads(proposals_path.read_text(encoding="utf-8"))
        existing_list = existing.get("proposals", existing) if isinstance(existing, dict) else existing
    except Exception:
        existing_list = []
    merged = new_proposals + [p for p in existing_list if p.get("generated_by") != "HYPERCLAW"]
    proposals_path.write_text(
        json.dumps({"proposals": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[FAST_CYCLE] hyperclaw_to_proposals -> {len(new_proposals)} proposals injected")
```

**Защо дава 12 proposals срещу plan-2026-06-20.md:**
- 4 оси × 1 OBJECTIVE = 4
- 4 оси × 2 PLAN_STEPS = 8
- Общо = 12 ✓

GLOBAL_RISKS_AND_CHECKS и NEXT_REVIEW_SIGNALS не са оси → не се хващат.

---

### 2. Регресионен тест преди commit
```
python -c "
import sys, json
sys.path.insert(0, '.')
from fast_cycle_runner import _hyperclaw_to_proposals
_hyperclaw_to_proposals()
props = json.loads(open('memory/improvement_proposals.json', encoding='utf-8').read())
p = props.get('proposals', props)
hc = [x for x in p if x.get('generated_by') == 'HYPERCLAW']
print(f'HYPERCLAW proposals: {len(hc)}')
assert len(hc) >= 12, f'FAIL: got {len(hc)}'
print('OK')
"
```

### 3. Full cycle run за верификация (само при налична quota)
```
python fast_cycle_runner.py
```
Провери в лога:
- `[FAST_CYCLE] hyperclaw_to_proposals -> 12 proposals injected`
- `[FAST_CYCLE] hyperclaw_orchestrator -> OK`

---

## КОНТЕКСТ ОТ СЕСИЯТА

Пълното описание на системата (генерирано в тази сесия) покрива:
- 25 review оси, 4 домейна (HUMAN/PLANET/CIVILIZATION/COSMOS)
- Цикъл стъпки 0→25 в `fast_cycle_runner.py`
- 5-way LLM fallback chain (Groq→Cerebras→OpenRouter→Gemini→Ollama)
- MerkleMemory архитектура (FAST/MEDIUM/DEEP режими)
- PatchGuardian + CivilizationGuard safety слоеве
- 20 live API-та в `global_indicators.py`, 12 в `self_observer.py`
