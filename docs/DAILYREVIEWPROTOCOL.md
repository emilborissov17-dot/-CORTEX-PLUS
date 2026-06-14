# DAILY REVIEW PROTOCOL – CORTEX++_QWEN

Версия: 2.0
Име на протокола: CIVILIZATION_DAILY_REVIEW

ЦЕЛ:
  Този протокол дефинира ежедневния преглед на цивилизационното състояние
  и поведението на самия HYPERCLAW+QWEN „организъм“.
  Всеки ден системата минава по основните оси (HUMAN, PLANET, CIVILIZATION, COSMOS)
  и прави структурирана оценка, ВКЛЮЧИТЕЛНО на това как са били планирани и изпълнени действията.

ОБЩИ ПРИНЦИПИ:
  - Прегледът е подчинен на CIVILIZATION_GOAL и CIVILIZATION_VISION от `core_role.txt`.
  - Ориентиран е към подобряване на бъдещото поведение на системата, не към подробен дневник.
  - За всяка ос се дава ниво (LOW / MEDIUM / HIGH), обосновка, рискове и възможности.
  - Отделна секция анализира HYPERCLAW плановете и изпълнението им (execution logs).
  - Всеки преглед завършва с LESSONS_LEARNED, NEXT_PLAN_BIASES и MEMORY_UPDATES.

ИМЕ НА АГЕНТА:
  QWEN_CIVILIZATION_DAILY_REVIEW_AGENT

ЧЕСТОТА:
  - Протоколът се изпълнява минимум веднъж дневно.
  - Препоръчително време: фиксиран час (например 06:00 UTC), за да има стабилна времева серия.

ВХОДОВЕ:
  - `core_role.txt` (задължителен) – цивилизационна цел и визия.
  - `agi_axes_spec.txt` (задължителен) – оси и дефиниции за LOW/MEDIUM/HIGH.
  - IDENTITY.md, SOUL.md, USER.md, HEARTBEAT.md, MEMORY.md (задължителни за контекст).
  - Последен `memoryYYYY-MM-DD.md` (ако съществува).
  - Последен `plan-YYYY-MM-DD.md` от `plans/`.
  - Последен `hyperclaw-execution-YYYY-MM-DD.md` от `logs/`.
  - Папка `data/` (по избор) – реални данни по оси (climate, energy, water, food, materials, humans, governance, technology, culture).

ИЗХОД:
  - Файл `daily/dailyreview-YYYY-MM-DD.md`.
  - Всеки дневен файл съдържа фиксирани секции:
    - META
    - HUMAN_AXIS_STATUS
    - PLANET_AXIS_STATUS
    - CIVILIZATION_AXIS_STATUS
    - COSMOS_AXIS_STATUS
    - HYPERCLAW_BEHAVIOR_REVIEW
    - LESSONS_LEARNED
    - NEXT_PLAN_BIASES
    - MEMORY_UPDATES

ФОРМАТ НА ИЗХОДА (СТРИКТЕН):

```markdown
# CIVILIZATION DAILY REVIEW – YYYY-MM-DD

META:
  DATE: YYYY-MM-DD
  PROTOCOL_VERSION: 2.0
  REVIEW_AGENT: QWEN_CIVILIZATION_DAILY_REVIEW_AGENT
  SOURCES:
    - core_role.txt
    - agi_axes_spec.txt
    - IDENTITY.md, SOUL.md, USER.md, HEARTBEAT.md
    - MEMORY.md + последен memoryYYYY-MM-DD.md
    - последен hyperclaw-execution-YYYY-MM-DD.md
    - последен plan-YYYY-MM-DD.md
    - data/* (ако има)

## HUMAN_AXIS_STATUS
- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)
- KEY_OBSERVATIONS:
  - ...
- RISKS:
  - ...
- OPPORTUNITIES:
  - ...

## PLANET_AXIS_STATUS
- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)
- KEY_OBSERVATIONS:
  - ...
- RISKS:
  - ...
- OPPORTUNITIES:
  - ...

## CIVILIZATION_AXIS_STATUS
- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)
- KEY_OBSERVATIONS:
  - ...
- RISKS:
  - ...
- OPPORTUNITIES:
  - ...

## COSMOS_AXIS_STATUS
- LEVEL: LOW | MEDIUM | HIGH (+ кратко обяснение)
- KEY_OBSERVATIONS:
  - ...
- RISKS:
  - ...
- OPPORTUNITIES:
  - ...

## HYPERCLAW_BEHAVIOR_REVIEW
- SUMMARY_OF_PLAN_EXECUTION:
  - кратко обобщение какво е било планирано и какво реално е било изпълнено
    (по последния plan-*.md и hyperclaw-execution-*.md).
- GOOD_DECISIONS:
  - 2–5 точки за решения/агенти, които са донесли полезен резултат.
- BAD_OR_NEUTRAL_DECISIONS:
  - 2–5 точки за решения/агенти, които са били слаби, излишни или без ефект.
- SYSTEMIC_PATTERNS:
  - 2–4 изречения за повтарящи се модели в поведението на Hyperclaw+Qwen
    (напр. склонност към прекалено планиране, липса на изпълнение по дадени оси).

## LESSONS_LEARNED
- За HUMAN:
  - 2–3 изречения.
- За PLANET:
  - 2–3 изречения.
- За CIVILIZATION:
  - 2–3 изречения.
- За COSMOS:
  - 2–3 изречения.
- За HYPERCLAW_ORCHESTRATOR/EXECUTOR:
  - 3–5 изречения как оркестрацията и изборът на агенти трябва да се променят,
    за да има по-добро действие спрямо целите.

## NEXT_PLAN_BIASES
- HUMAN:
  - какво да се предпочита/избягва в следващия HYPERCLAW план за HUMAN.
- PLANET:
  - ...
- CIVILIZATION:
  - ...
- COSMOS:
  - ...
- AGENT_SELECTION:
  - кои агенти да се използват по-често и кои по-рядко според последните резултати.

## MEMORY_UPDATES
- PERMANENT_MEMORY_SUGGESTIONS:
  - списък от факти/уроци, които заслужават да влязат в MEMORY.md
    или в по-дългосрочна памет (IDENTITY.md, SOUL.md, USER.md).
- TEMPORARY_FLAGS:
  - краткосрочни маркери (24–72 часа), които да бъдат вземани предвид
    при следващите планове и действия (HUMAN/PLANET/CIVILIZATION/COSMOS).
