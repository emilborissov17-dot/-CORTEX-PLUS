# MEMORY – Long-Term Memory for CORTEX++_QWEN

Версия: 2026-03-06 – v2.0

## 1. Core Invariants

1. Файловете `SOUL.md`, `AGENTS.md`, `USER.md` и `IDENTITY.md` са ядрото за boot на CORTEX++_QWEN; те се променят само като „стар цял файл → нов цял файл“, не с локални кръпки.
2. Всеки основен session / цикъл първо чете `SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, този `MEMORY.md` и последните дневни memory / daily review файлове, после предлага план и едва след това изпълнява.
3. Важните решения и уроци винаги се записват в дневните `memoryYYYY-MM-DD.md`, а устойчивите правила и архитектурни истини – се дестилират тук, в `MEMORY.md`.
4. HYPERCLAW_ORCHESTRATOR + HYPERCLAW_EXECUTOR са трети като „организъм“: техните поведения и уроци също влизат в паметта чрез `HYPERCLAW_BEHAVIOR_REVIEW`, `LESSONS_LEARNED` и `MEMORY_UPDATES` от daily review.

## 2. Memory Layout

- `memoryYYYY-MM-DD.md` – дневни логове, епизодична памет: ключови събития, решения, резултати от HYPERCLAW EXECUTION и кратки резюмета на дневните review-та.
- `MEMORY.md` – дългосрочна, курирана памет: архитектура, инварианти, трайни предпочитания на Emil и стабилни уроци за системата.
- `SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `USER.md`, `HEARTBEAT.md` – описват „кой е агентът“, „как работи“ и „кой е човекът“ и винаги се зареждат в началото на основен цикъл.

## 3. Usage Rules

- `MEMORY.md` се зарежда в основните частни цикли с Emil и в цивилизационния daily review, както и при стратегическо планиране на Hyperclaw.
- При всяка значима промяна в целите, архитектурата или работния процес – обнови този файл с кратък запис (дата + bullets) в секция `STABLE_LESSONS` или `CURRENT_FOCUS`.
- Дневните `memoryYYYY-MM-DD.md` могат да са подробни; `MEMORY.md` трябва да остане кратък, дестилиран и лесен за използване от агенти.

## 4. Взаимодействие с DAILY REVIEW и HYPERCLAW EXECUTION

1. Всеки `dailyreview-YYYY-MM-DD.md` съдържа секция `MEMORY_UPDATES`, която указва:
   - кои факти / уроци да влязат в съответния `memoryYYYY-MM-DD.md`;
   - кои от тях са кандидати за дългосрочна памет (този файл и/или SOUL/IDENTITY/USER).

2. Препоръчителен процес:
   - Прочети последния `dailyreview-YYYY-MM-DD.md`.
   - Извлечи `MEMORY_UPDATES` (PERMANENT_MEMORY_SUGGESTIONS и TEMPORARY_FLAGS).
   - Обнови `memoryYYYY-MM-DD.md` с:
     - кратък summary на деня;
     - ключови решения / резултати от `hyperclaw-execution-YYYY-MM-DD.md`;
     - списъците от `MEMORY_UPDATES`.

3. Ако даден урок или pattern се повтаря в много дни и е потвърден от `HYPERCLAW_BEHAVIOR_REVIEW` и `LESSONS_LEARNED`:
   - прехвърли го в `STABLE_LESSONS` по-долу.

## 5. 2026-03-04 – Архитектура (Човек–Планета–Цивилизация–Космос)

1. REVIEW режимите следват дървото човек → планета → цивилизация → космос и са малко на брой, но „дебели“: енергия, вода, храна, материали/отпадъци, човешко благосъстояние, неравенства, инфраструктура/градове, икономика/работа, управление/права, технологии/AI, климат/глобален риск, дългосрочно бъдеще, плюс GENERAL_SELF_REVIEW и GOAL_PROGRESS_REVIEW.
2. Ежедневният ритъм е паралелен: множество REVIEW процеси (ENERGY_REVIEW, WATER_REVIEW, FOOD_REVIEW, HUMAN_WELL_BEING_REVIEW и т.н.) стартират по общ график, а GENERAL_SELF_REVIEW и GOAL_PROGRESS_REVIEW четат резултатите от всички и дават мета-диагноза.
3. Системата остава „жив организъм“, а не хаос, чрез: централен scheduler, общи правила (cortexcontrol.rules, agentbehaviorrules.txt, webaccessrules.txt) и общ self-critique слой, който следи кои домейни са системно CRITICAL и къде липсват данни.
4. Паралелността е подчинена на безопасност: няма едновременен запис в едни и същи конфиг файлове, има контрол върху LLM натоварването (LLM queue) и върху web/API rate limit-ите.
5. Internet мостът може да използва мултимодален агент (текст, видео, аудио, изображения), но връща обратно в CORTEX++ само структурирани текстови snapshot-и (Markdown + JSON), които остават в „балона“ и могат да се ползват за по-натъшен REVIEW и планиране.

## 6. STABLE_LESSONS

(тук постепенно се добавят устойчиви уроци, когато се натрупа достатъчно повторение)

- [празно – за попълване от бъдещи MEMORY_UPDATES]

## 7. CURRENT_FOCUS

Кратък списък от 3–7 теми, които са основни в момента за CORTEX++_QWEN:

- Локален и изолиран LLM стек (Ollama + Qwen, без изтичане на данни навън).
- Надежден HYPERCYCLE: daily review → план → изпълнение → самоанализ.
- Енергийни данни и задачи (PLANET ос + energy агенти).
- Цивилизационен self‑review и дългосрочна устойчивост (CIVILIZATION + COSMOS).
- Подобряване на самия оркестратор и избор на агенти (HYPERCLAW_BEHAVIOR_REVIEW → NEXT_PLAN_BIASES).
