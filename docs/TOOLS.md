# TOOLS.md – Local Notes (CORTEX++_QWEN)

Този файл описва конкретни детайли за средата и инструментите при работа по CORTEX++_QWEN. Използвай го, за да не гадаеш пътища, модели и конфигурации.

---

## Workspaces

Основен QWEN проект:

- `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN`

Замразен master (read‑only референт):

- `C:\Users\emilb\Desktop\AGI\CORTEX++`

OpenClaw config:

- `C:\Users\emilb\.openclaw\openclaw.json`

Агенти в OpenClaw (релевантни за този проект):

- `main` – общ локален агент.
- `planetary-agent` – фокусиран върху CORTEX++ и устойчива цивилизация.

Когато път или име се променят, актуализирай този файл, вместо да разчиташ на памет.

---

## Models & LLM Gateway

Локален LLM провайдър: **Ollama**

- API base: `http://127.0.0.1:11434`
- Основен модел: `qwen2.5:7b`
- В OpenClaw: `ollama/qwen2.5:7b`

CORTEX++_QWEN LLM stack:

- `core/llm_backend.py`  
  Единствената позволена точка за извикване на LLM от агенти. Всички агенти трябва да минават през този модул.

- `qwen_cortex_agent.py`  
  Gateway между Qwen и CORTEX++ архитектурата – подготвя prompt-ове (identity, цели, памет), вика `llm_backend.py`, обработва отговорите.

**Правило:**  
Агентите нямат право да викат директно Ollama / Qwen. Винаги използват функции от `core/llm_backend.py` (и при нужда helper-и в `qwen_cortex_agent.py`).

---

## CORTEX++_QWEN директории

Код:

- `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\agents`
- `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\core`
- `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\cortex`

Памет:

- Дългосрочна: `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\MEMORY.md`
- Дневни файлове: `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\memoryYYYY-MM-DD.md` (пример: `memory2026-03-03.md`)

Knowledge / данни:

- Общи: `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\knowledge`
- Енергийни гапове: `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\knowledge\energy_data_gaps.md`
- Снимки за ресурси (ако съществуват): `knowledge\*_snapshots\*.json`

Бележки / дизайн / документация (ако се ползва):

- `C:\Users\emilb\Desktop\AGI\CORTEX++_QWEN\notes`
- Markdown мета: `AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `USER.md`, `HEARTBEAT.md`, `DAILY_REVIEW_PROTOCOL.md`, `ENERGY_REVIEW_RULES.md`

Agent workspace в OpenClaw (ако е отделен):

- `C:\Users\emilb\.openclaw\agents\planetary-agent\agent`

---

## Полезни скриптове / команди

### OpenClaw gateway

Стартиране на OpenClaw gateway:

```powershell
openclaw gateway --port 18789 --verbose
