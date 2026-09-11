# Консулт — 2026-09-10_next_learning_hypothesis

_2026-09-10T06:34:20.451795+00:00 · nvidia/nemotron-3-ultra-550b-a55b:free · цена: $0.0_

> **ОПОНЕНТЪТ НЕ Е KIMI.** Отговорил е `nvidia/nemotron-3-ultra-550b-a55b:free`.
> Безплатният Kimi вече не съществува в OpenRouter (HTTP 404,
> „unavailable for free“), а платеният не се вика. Отговорът
> по-долу е безплатен и НЕЗАВИСИМ, но НЕ е на Kimi.

## Отговор

### A. Хипотеза за учене: **(b)** — без обучение на тегла, разширяване на предсказванията и не-невронни learner-и.

**Защо не (a):**  
Пропециетат (prophecy ledger) е **единственият верифициран сигнален цикъл** в системата (hash-верига, Brier score, валидни прогнози). Но обучението на предпочитания (fulfilled vs unfulfilled) върху 3B модел с QLoRA r=8 е архитектурно грешно за три причини:
1.  **Няма grounding:** Факта 6 доказва, че системата халюцинира факти при 100% увереност (24/24 UP, измислени цитати). Обучаване на собствени прогнози без R43 (дословен цитат) заkeyва халюцинациите в теглата.
2.  **Проблемът е калибрация, не политика:** Прогнозите са скаларни (P(failure), axis_score). Те не изискват policy optimization (DPO/RLHF), а isotonic regression / temperature scaling / conformal prediction. Невронната мрежа е оръдие за reprezentation learning, а не за скаларна калибрация.
3.  **Проверката от факт 3:** `axis_next` learner (екстраполация) загубва от persistence (MAE 18.7 vs 8.5). Системата **не умее да екстраполира**. Научаване на preference двойки от прогнозите ще учи модела да подражава лоша екстраполация.

**Защо (b) е единственият инженерен път:**
-   Fact 3 показва, че **simple frequency (recent 5-cycle rate)** бие всичко за `self_failure`.
-   Fact 3 показва, че **persistence (t+1 = t)** бие екстраполацията за `axis_next`.
-   **Действие:** Заменете екстраполацията с EWMA / Holt-Winters / conformal intervals. Добавете предиктори: „коя стъпка ще падне“, „degraded flag“, „duration“. Логнете feature importance. Не треньвайте тегла.

**Пропуснатият въпрос (който не е зает):**  
**Какво е input distribution shift на `axis_next` между клоновете?** Ако `experimental/self-mod` променя осите/нормализацията, persistence baseline се чупи. Нямате drift detection на входните сигнали на learner-а.

---

### B. Нощният цикъл: **Върнете работното копие на `feature/lidaction-guard` (ac013e4). Експериментите — в отделен worktree.**

**Докази:**
1.  **Production drift:** Нощните цикли 9 и 10 септ. са минали през `experimental/self-mod` (checkout 8 септ., 1 комит назад от origin). Това е **unpinned, mutable, divergence-prone** код в production pipeline.
2.  **Счупен pipeline:** `merkle_to_training` пада с `TypeError: cannot unpack non-iterable Mapping object` на две последователни нощи. Този код е в experimental клона. Ако беше в worktree, production циклите не биха се счупили.
3.  **QUEUE.md е explicit:** Нарича `feature/lidaction-guard` „работен клон“. Документацията и реалността са в конфликт — реалността печели (циклите тръгват), но реалността е грешна.

**Решение:**  
`git worktree add ../exp-self-mod experimental/self-mod` — експериментите тук.  
`git checkout feature/lidaction-guard` — основно работно копие за нощни цикли.  
`merkle_to_training` се фиксира в worktree, тества се дневно, merge-ва се през PR след зелени тестове.

---

### C. Теглата (PROGRESS 1.3): **Приемете текущото per-axis състояние като baseline decision (v0), нормализирайте до 100% по подцели за отчетност, ЗАБРАНЕТЕ промени в `goal_score_calculator` до человешко решение.**

**Разбор:**
- **Сума 167% и доминиране на CIVILIZATIONAL_STABILITY (35.9%)** идва от **брой оси (8)**, не от важност. `goal_score_calculator` сумира по оси → всеки нов axis = глас. Това е **bug, не feature**.
- **Нормализация по клон** скрива бъга (прави теглото да изглежда „правилно“ за клона), но пренася политиката в branch topology. Лош precedent.
- **Оставило „отворено“** (статус от 20 авг.) е пасивна агресия към Емил. Системата има нужда от число днес, за да сметна `goal_score` за нощния цикъл.

**Конкретно решение (commit-ready):**
1.  **Freeze:** Записвате текущите axis weights в `config/axis_weights_v0_baseline.json` (commit message: „Baseline v0: raw axis weights, sum=167%, Civilizational=8 axes. NOT normalized. Human decision required for subgoal weights.“).
2.  **Normalize for reporting:** В `goal_score_calculator` добавете `--normalize-subgoals` флаг (default off). Когато е on — теглото на подцел = сума(axis_weights) / 167 * 100. Използвайте го **само за дашборди/отчети**.
3.  **Blocker:** Добавете CI проверка: `assert sum(subgoal_weights) == 100` или `assert len(axes_per_subgoal) == expected`. Не пускайте нощен цикъл, ако теглата не са explicitно нормализирани от човек.

**Най-слабото място на цялата архитектура (непосочено в брифа):**  
**Нямате signal provenance.** Факта 1 (`merkle_to_training` FAILED), Факт 2 (corpus = LLM hallucinations), Факт 6 (R43 not enforced) — всички сочат към едно: **нямате гаранция, че input signal = extracted fact**. Докато не наложите `signal = verbatim_quote(span)` на ниво ingestion (не на ниво spec), всичко останало — тегла, learner-и, LoRA, prophecy — е построено на quicksand.

---

## Брифът, който му беше даден (дословно)

# БРИФ ЗА KIMI — 10 септември 2026: какво учи системата, след като архивният LoRA е мъртъв

Суров вход. Без извод. Отговори на трите въпроса накрая; ако решението ти
е друго от изброените, кажи го.

## ФАКТИ (измерени на машината, не преразказани)

1. Нощните цикли: 8, 9 и 10 септ. са запечатани CYCLE_FINISHED без kill
   (8393 s / 8908 s / 6330 s; degraded 1 / 1 / 0; integrity 92.5 / 90.2 / 97.6 %).
   Стъпката merkle_to_training казва „FAILED: cannot unpack non-iterable
   Mapping object" и двете последни нощи.

2. K1B (учене от собствения архив): корпус = 1077 двойки
   {сигнали на осите + essence} -> {решение от cortex_memory/archive/*/decisions.json}.
   Решенията са генерирани от LLM (пример: component "unknown", problem "To enable
   full system functionality", solution "Update fast_cycle_runner.py to include
   missing agents"). QLoRA r=8 върху Qwen2.5-3B, 3 епохи, loss 2.83 -> 1.00.
   Eval на невиждан сплит (избери вярното решение от 4 кандидата от същия пул):
   адаптер 0.2611 [0.1913, 0.3334], база 0.2667 [0.1921, 0.3441], шанс 0.20.
   Правило „прочети името на оста в prompt-а и избери кандидата, който я споменава":
   0.7778 [0.7174, 0.8356]. Положителен контрол (изкуствено 12-way правило, 3 епохи):
   0.33 срещу база 0.14 — бенчът вижда учене, когато го има.
   Предрегистрирано правило: delta <= 0 -> DEAD, STOP. Delta = -0.0056.

3. Самопредсказания (experiments/prophecy/prophecy_ledger.jsonl, hash-верига, валидна):
   - self_failure (P(следващият цикъл завършва)): 52 оценени. Brier learner
     (recent 5-cycle rate) 0.171; baseline (all-time rate) 0.331; климатология
     (константен base rate 0.712) 0.205. Learner печели 40/52.
   - axis_next (скор на ос следващ цикъл): 736 оценени, 609 дегенерирали
     (learner == baseline == 50.0). В 127 недегенерирали: learner (екстраполация
     на последната стъпка) MAE 18.7; baseline (persistence) MAE 8.5. Learner
     печели 12/127.

4. Клонове: работното копие е на experimental/self-mod (checkout 8 септ. 15:00
   местно; origin/experimental/self-mod съществува, 1 комит назад). Нощните цикли
   на 9 и 10 септ. са минали през това работно копие, т.е. през експерименталния
   клон. feature/lidaction-guard (ac013e4) е клонът, който docs/QUEUE.md нарича
   работен.

5. Тегла (config/target_config.json, mtime 21 авг, непроменен): по подцели
   SUSTAINABLE_RESOURCES 22.8 %, HEALTHY_ENVIRONMENTS 15.0 %,
   CIVILIZATIONAL_STABILITY 35.9 %, KNOWLEDGE 8.4 %, SAFETY 18.0 % (сума 167).
   weight_principles в същия файл: „Climate/CO2 and basic needs highest". По
   ОСИ climate=10, water/food=9. Разликата по клонове идва от БРОЯ оси в клона
   (CIVILIZATIONAL_STABILITY има 8 оси), не от тегло на ос.
   goal_score_calculator сумира по оси, не по клонове. PROGRESS 1.3 („решение
   по теглата — човешко, чака Емил") стои отворено от 20 август.

6. Първи залог (7 септ., пазари): 24 от 24 семпъла казаха UP; всеки цитиран
   факт беше измислен; R43 (сигналът трябва да е дословен цитат от извлечен
   документ) е спецификация, не е доказано пуснат.

## ВЪПРОСИ

А. Каква е следващата хипотеза за учене (т. 2 и 11 от определението: учене
   от опит, което остава в системата), при положение че архивът от собствени
   решения не съдържа сигнал? Кандидати, без предпочитание:
   (a) корпус от СОБСТВЕНИТЕ ЗАПЕЧАТАНИ ПРЕДСКАЗАНИЯ + изход (prophecy ledger),
       preference двойки = сбъднати срещу несбъднати;
   (b) без обучение на тегла изобщо — само разширяване на предсказванията
       (продължителност, degraded, коя стъпка пада, стойност на индикатор) и
       по-добри НЕ-невронни learner-и (напр. EWMA вместо екстраполация);
   (c) друго.
Б. Трябва ли нощният цикъл да върви от experimental/self-mod, или работното
   копие да се върне на feature/lidaction-guard, а експериментите — в отделен
   worktree?
В. Теглата (1.3): да се приеме текущото per-axis състояние и да се запише като
   решение, да се нормализира по клон, или да остане отворено?

