# SESSION STATE — 2026-06-21

## DONE

### hyperclaw silent-failure → needs_reanalysis marker
**Файл:** `agents/hyperclaw/hyperclaw_orchestrator.py`

Разделен `except Exception` на два клона:
- `AllBackendsFailedError` → пише `snapshots/hyperclaw/hyperclaw_snapshot_latest.json`
  с `needs_reanalysis: True` (подхваща се от `_scan_needs_reanalysis()` в следващия цикъл)
- generic `Exception` → само логва, без raise

Предпоставки потвърдени преди редакция:
- `BASE` е на ред 13 (`pathlib.Path(__file__).resolve().parents[2]`)
- `_utc_now()` е дефинирана на ред 19
- `json` и `pathlib` са импортирани на ред 10

---

## TODO СЛЕДВАЩО (по приоритет)

### 1. Parser fix в `_hyperclaw_to_proposals()` — ВАРИАНТ A (regex)
**Файл:** `fast_cycle_runner.py`, функция `_hyperclaw_to_proposals()`

**Проблем:** Парсерът връща 0 proposals защото търси точни стрингове:
- `"- STEP"` — но LLM пише `"1. **bold text**"` или `"N. action"`
- `"OBJECTIVE:"` — но LLM пише `"**OBJECTIVE**:"` или `"**Objective:**"`

**Вариант A (regex):** Замени string-matching с regex:
```python
import re
# за OBJECTIVE
re.match(r'\*{0,2}OBJECTIVE\*{0,2}\s*:', line, re.IGNORECASE)
# за STEP
re.match(r'[-\d]+[.)]\s+\*{0,2}', line)
```

**Регресионен тест:** `plans/plan-2026-06-20.md` трябва да върне >0 стъпки.
Провери с:
```python
# в Python shell
from fast_cycle_runner import _hyperclaw_to_proposals
# или тествай директно парсерния цикъл срещу plan файла
```

### 2. Регресионен тест на новия парсер
Отвори `plans/plan-2026-06-20.md`, погледни реалния LLM формат,
потвърди че regex-ът го хваща преди да commit-неш.

### 3. Full cycle run за верификация
```
python fast_cycle_runner.py
```
Провери в лога:
- `[FAST_CYCLE] hyperclaw_orchestrator -> OK`
- `[FAST_CYCLE] hyperclaw_to_proposals -> N proposals injected` (N > 0)
- При симулиран backend failure: `snapshots/hyperclaw/hyperclaw_snapshot_latest.json` съществува с `needs_reanalysis: true`

---

## КОНТЕКСТ ОТ СЕСИЯТА

Пълното описание на системата е генерирано в тази сесия и покрива:
- 25 review оси, 4 домейна (HUMAN/PLANET/CIVILIZATION/COSMOS)
- Цикъл стъпки 0→25 в `fast_cycle_runner.py`
- 5-way LLM fallback chain (Groq→Cerebras→OpenRouter→Gemini→Ollama)
- MerkleMemory архитектура (FAST/MEDIUM/DEEP режими)
- PatchGuardian + CivilizationGuard safety слоеве
- 20 live API-та в `global_indicators.py`, 12 в `self_observer.py`
