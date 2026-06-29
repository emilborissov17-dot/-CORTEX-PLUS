# OPENCLAW INTEGRATION DESIGN
## CORTEX++ → External OpenClaw — Controlled Autonomy

**Version:** 0.1 (design only, no code written yet)  
**Status:** For review by Ivan/Emil before implementation  
**Date:** 2026-06-29

---

## 1. Контекст и цел

CORTEX++ в момента работи с вътрешен `openclaw_agent.py` — Python скрипт, напълно независим от
zewnętrzния OpenClaw (CLI инструмент, `~/.openclaw/`). Интеграцията цели да даде на CORTEX++
достъп до реалните способности на external OpenClaw: мултимодален web search, транскрипция,
автономно събиране на информация — с **твърди граници** кои действия изискват одобрение и кои не.

Основният риск при автономни агенти не е "грешен резултат" — а **необратимо действие в реалния
свят без знанието на оператора**. Дизайнът е построен около тази загриженост.

---

## 2. Трите нива на автономност

### Ниво 1 — Автономно, само logging

> Агентът действа сам. Не чака одобрение. Резултатът се логва в Merkle.

**Характеристика:** Изцяло наблюдателни/четящи действия. Нищо не се променя извън локалния
кеш и знанието на CORTEX++. Напълно обратими — `undo` е тривиален (изтрий файла).

**Примери:**
- Web search (текстови резултати, без submission на форми)
- Fetch на публична страница / PDF / RSS
- Транскрипция на видео/аудио (локална обработка)
- Четене на локални файлове
- Query към вътрешни снапшоти, памет, индекси
- Collect на структурирани данни от публични API (само GET)

**Какво НЕ е Ниво 1:**
- Дори "безобидно" изпращане на HTTP POST към external API → Ниво 3
- Записване в споделена директория извън CORTEX++ workspace → Ниво 2 минимум

---

### Ниво 2 — Автономно + backup + rollback задължителни

> Агентът действа сам, но преди всяка промяна прави backup. При грешка — автоматичен rollback.

**Характеристика:** Обратими промени на **вътрешното** състояние на CORTEX++. "Обратими" означава:
backup файлът съществува и rollback може да се изпълни автоматично без човешка намеса.

**Примери:**
- Записване на нови knowledge файлове (`knowledge/`, `data/`)
- Записване на internet snapshots (`knowledge/internet_snapshots/`)
- Обновяване на вътрешни снапшоти (`snapshots/`)
- Добавяне към semantic memory
- Запис на task резултати в `openclaw_queue/results/`
- Промяна на вътрешни конфигурационни файлове на CORTEX++ (с backup)

**Механизъм (по модела на PatchGuardian):**
```
1. Backup на целевия файл/директория (timestamped)
2. Изпълни действието
3. Верифицирай резултата (schema check, integrity)
4. При грешка → автоматичен rollback до backup
5. Запис в Merkle audit log (ниво, файл, backup_path, резултат)
```

Максималният брой backups на файл е 10 (по PatchGuardian константата).

---

### Ниво 3 — Изисква човешко одобрение преди изпълнение

> Действието НЕ се изпълнява докато оператор не натисне "Approve" в `cortex_approval_server`.

**Характеристика:** Действия, излизащи **извън локалния workspace** или **необратими** по природа.
"Необратим" = нямаш начин да вземеш обратно без координация с external система.

**Примери:**
- Публикуване на съдържание (GitHub push, публикация в блог, wiki)
- Изпращане на съобщения (email, Slack, Discord, Telegram)
- POST/PUT/DELETE към external API
- Изтриване на файлове извън CORTEX++ workspace
- Създаване на external акаунти или ресурси
- Всяко действие с финансови последствия
- Изпращане на данни към трети страни (дори "само за четене" ако включва credentials)

**Правило по подразбиране:** Всяко действие, което не е **изрично** в Ниво 1 или Ниво 2
allowlist-а, автоматично получава Ниво 3. Неизвестното = изисква одобрение.

---

## 3. Allowlist Ruleset — твърдо кодиран, НЕ LLM преценка

### Защо не LLM?

LLM може да бъде убеден (prompt injection от web страница, манипулиран резултат от search)
да класифицира действие погрешно. Ако класификацията е LLM → единична атакувана страница
може да накара системата да смята, че "изпращане на имейл" е Ниво 1. Това е неприемливо.

**Класификацията е lookup в JSON файл. Не inference. Не reasoning.**

### `config/openclaw_action_policy.json` — структура

```json
{
  "version": 2,
  "default_unclassified": "level_3",
  "note": "Ако action_type не е в нито един списък → level_3 автоматично.",

  "level_1": {
    "description": "Автономно, само logging. Наблюдателни/четящи действия.",
    "action_types": [
      "web_search",
      "web_fetch_get",
      "read_local_file",
      "transcribe_media_local",
      "query_cortex_memory",
      "query_cortex_snapshot",
      "list_directory",
      "public_api_get",
      "rss_fetch",
      "pdf_fetch_public"
    ]
  },

  "level_2": {
    "description": "Автономно + задължителен backup + rollback при грешка.",
    "action_types": [
      "write_knowledge_file",
      "write_internet_snapshot",
      "write_cortex_snapshot",
      "update_semantic_memory",
      "write_task_result",
      "update_cortex_config_internal",
      "write_data_file"
    ],
    "required_fields": ["target_path", "backup_enabled"],
    "backup_enabled_must_be": true
  },

  "level_3": {
    "description": "Изисква human approval преди изпълнение.",
    "action_types": [
      "git_push",
      "publish_content",
      "send_email",
      "send_slack_message",
      "send_discord_message",
      "send_telegram_message",
      "http_post_external",
      "http_put_external",
      "http_delete_external",
      "delete_file_external",
      "create_external_account",
      "financial_transaction",
      "upload_to_cloud_storage",
      "api_write_external"
    ]
  },

  "always_blocked": {
    "description": "Никога не се изпълнява, дори с одобрение. Изисква промяна на кода.",
    "action_types": [
      "modify_openclaw_action_policy",
      "modify_cortex_approval_server",
      "delete_merkle_archive",
      "disable_audit_log",
      "execute_arbitrary_shell"
    ]
  }
}
```

### Как се прилага

Компонентът `OpenClawBridge` (бъдещ) прочита policy-то при стартиране и го кешира в памет.
При всяка задача от OpenClaw:

```
action_type = task["action_type"]   # задължително поле в task card

if action_type in always_blocked    → отхвърли незабавно, log
if action_type in level_1           → изпълни, log
if action_type in level_2           → backup, изпълни, verify, (rollback ако грешка), log
if action_type in level_3           → enqueue за human approval, блокирай
if action_type not found anywhere   → третирай като level_3 (default_unclassified)
```

**Важно:** `action_type` се чете от task card-а, но проверката е срещу policy JSON.
OpenClaw агентът не може да "убеди" bridge-а с текст — само точен string match срещу allowlist.

---

## 4. Интерфейс с External OpenClaw Gateway

### Какво знаем за момента

- Gateway стартира с: `openclaw gateway --port 18789 --verbose`
- Config: `C:\Users\emilb\.openclaw\openclaw.json`
- Дефинирани агенти: `main`, `planetary-agent`
- Workspace state: `C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\.openclaw\workspace-state.json`
- Формат на task: виж `openclaw_queue/PLANETARY_TASK_001_card.txt`

**⚠ Нуждае се от верификация:** Точният HTTP API на external OpenClaw gateway трябва да се
провери срещу официалната му документация преди имплементация. Посоченото по-долу е
**работна хипотеза** — може да се наложи корекция.

### Предполагаем HTTP API (хипотеза)

**Submit задача:**
```
POST http://localhost:18789/tasks
Content-Type: application/json

{
  "agent": "planetary-agent",
  "task_id": "CORTEX_TASK_20260629_001",
  "action_type": "web_search",           ← задължително за policy lookup
  "payload": { ...task card fields... },
  "callback_path": "openclaw_queue/results/CORTEX_TASK_20260629_001.json"
}
```

**Poll статус:**
```
GET http://localhost:18789/tasks/{task_id}
→ { "status": "running|completed|failed", "progress": "...", "result_path": "..." }
```

**Алтернатива — file-based queue:**
Ако OpenClaw ползва file drop (вероятно предвид `openclaw_queue/` директорията):
```
1. Запиши task card в:  openclaw_queue/pending/{task_id}.json
2. OpenClaw го засича и обработва
3. Резултат се появява в: openclaw_queue/results/{task_id}.json
4. CORTEX++ polls за файла (timeout: конфигурируем)
```

**Action Items преди имплементация:**
- [ ] Провери `openclaw --help` и `openclaw gateway --help`
- [ ] Прегледай `~/.openclaw/openclaw.json` за API формат
- [ ] Тествай ръчно: submit задача, poll резултат
- [ ] Документирай точния API в `docs/TOOLS.md`

### Timeout и грешки

| Сценарий | Поведение |
|---|---|
| Gateway не отговаря | Log + retry 3 пъти (backoff), после mark task като failed |
| Task timeout (>10 мин) | Cancel + log + notify в audit |
| Невалиден action_type | Reject преди submit (policy check) |
| Gateway върна грешка | Log + needs_reanalysis flag (по модела на openclaw_agent.py) |

---

## 5. Интеграция с `cortex_approval_server.py` за Ниво 3

### Текущо състояние на approval server

`cortex_approval_server.py` вече:
- Сервира proposals от `memory/improvement_proposals.json`
- Има `/api/approve/{index}` и `/api/reject/{index}` ендпойнти
- Записва одобрените в `memory/approval_queue.json`
- Показва панел в dashboard-а на `http://localhost:5000`

### Разширение за OpenClaw Ниво 3

OpenClaw Ниво 3 задачите ще влизат в **отделен файл** `memory/openclaw_pending_l3.json`
(не в `improvement_proposals.json` — различна семантика: proposals са предложения за подобрения,
L3 задачите са конкретни чакащи действия с external ефект).

Approval server-ът получава **нов endpoint** (в бъдеща имплементация):
```
GET  /api/openclaw-pending      → список с чакащи L3 задачи
POST /api/openclaw-approve/{id} → одобри задача → записва в approval_queue, bridge я изпълнява
POST /api/openclaw-reject/{id}  → отхвърли → task получава status=rejected, log в Merkle
```

### UI в dashboard-а

Нова секция в approval панела (отделена от proposals):

```
┌─────────────────────────────────────────────────────┐
│ ⚠ OpenClaw — чакащи Ниво 3 действия                 │
├─────────────────────────────────────────────────────┤
│ [planetary-agent] send_email → research@example.com  │
│ Тема: Planetary bottlenecks report Q2 2026           │
│ Поискано от: planet_agent  │ 2026-06-29 14:32 UTC    │
│                    [✓ Одобри]  [✗ Отхвърли]          │
└─────────────────────────────────────────────────────┘
```

### Timeout за чакащо одобрение

Ниво 3 задача, която не е одобрена в рамките на **configurable deadline** (default: 48 часа),
автоматично получава статус `expired` и се логва. Системата никога не изпълнява expired задача.

---

## 6. Audit Trail в Merkle паметта

### Принцип

**Всяко** OpenClaw действие — независимо от ниво, дори отхвърлено — влиза в Merkle архива.
Audit log е append-only. Не може да се изтрие (включен в `always_blocked`).

### Формат на audit запис

```json
{
  "audit_id": "oc_20260629_143201_abc123",
  "timestamp_utc": "2026-06-29T14:32:01Z",
  "source_agent": "planet_agent",
  "openclaw_agent": "planetary-agent",
  "task_id": "CORTEX_TASK_20260629_001",
  "action_type": "web_search",
  "autonomy_level": 1,
  "status": "completed",
  "target": "web: planetary boundaries 2026 IPCC",
  "result_summary": "5 sources collected, 3 transcribed",
  "result_path": "openclaw_queue/results/CORTEX_TASK_20260629_001.json",
  "backup_path": null,
  "approved_by": null,
  "approved_at": null,
  "rollback_triggered": false,
  "merkle_cycle_id": "cycle_000012"
}
```

### Как влиза в Merkle

`MerkleMemory.commit()` вече приема `decisions` и `results` списъци. OpenClaw audit записите
се добавят към `decisions` списъка на текущия цикъл — точно като всяко друго решение на системата.

За L3 задачи, одобрението се добавя отделно при изпълнение (`approved_by`, `approved_at`).

### Верификация

Тъй като Merkle хашовете покриват целия archive, всеки audit запис е cryptographically
защитен срещу последваща промяна — по съществуващия механизъм на `merkle_memory.py`.

---

## 7. Архитектурно решение: Брой OpenClaw агенти

> **⚠ Решение за Ivan/Emil** — посочени са trade-off-ите, финалната дума е ваша.

### Текущата CORTEX++ структура

```
agents/
  planet/     ← planet_snapshots_agent, planetary_potential_review, ...
  human/      ← human_snapshots_agent
  civilization/ ← civilization_snapshots_agent
  cosmos/     ← cosmos_snapshots_agent
  openclaw/   ← openclaw_agent.py (вътрешен, независим от external)
```

4 domain агента + отделни специализирани. Не 25 per-axis агента.

### Три опции за OpenClaw интеграция

---

#### Опция A: Single Bridge — препоръчана от мен

```
planet_agent    ──┐
human_agent     ──┼──► OpenClawBridge ──► external openclaw gateway
civilization_a  ──┤         ↑
cosmos_agent    ──┘    (policy engine
                        audit trail
                        approval flow)
```

**Един** нов компонент `agents/openclaw/openclaw_bridge.py` поема **цялата** комуникация с
external OpenClaw. Domain агентите генерират task specs (JSON), предават ги на Bridge-а.
Bridge-ът прави policy check, изпълнява или изпраща за одобрение, пише audit.

**Предимства:**
- Audit trail на едно място
- Policy enforcement на едно място
- При смяна на OpenClaw API → промяна в 1 файл
- Лесно тестване на bridge-а в изолация

**Недостатъци:**
- Bridge-ът е bottleneck — ако е счупен, всички domain агенти губят достъп до OpenClaw
- Domain агентите трябва да знаят как да формулират task spec

---

#### Опция B: Domain агентите делегират директно

```
planet_agent    ──► openclaw gateway (planetary-agent)
human_agent     ──► openclaw gateway (human-agent)
civilization_a  ──► openclaw gateway (civilization-agent)
cosmos_agent    ──► openclaw gateway (cosmos-agent)
```

Всеки domain агент сам говори с OpenClaw. Policy check е в shared utility функция,
но не е централен компонент.

**Предимства:**
- По-директен поток, по-малко indirection
- Domain агентите са по-автономни

**Недостатъци:**
- Policy enforcement е "разпръснат" — по-лесно да се пропусне при нов агент
- Audit trail трябва да се имплементира 4 пъти
- 4 OpenClaw агента конфигурирани в `~/.openclaw/` (в момента са 2)

---

#### Опция C: Per-axis OpenClaw задачи (25+ агента)

```
CLIMATE_agent  ──► openclaw (climate-agent)
ENERGY_agent   ──► openclaw (energy-agent)
...25 агента...
```

**Предимства:** Максимална специализация на OpenClaw агентите, всеки с точен context.

**Недостатъци:**
- 25 агента в `~/.openclaw/` да се конфигурират и поддържат
- Всяка промяна в policy → 25 места
- Изцяло нова сложност без пропорционална добавена стойност
- Не съответства на текущата 4-domain архитектура

---

### Препоръка: Опция A

Единният Bridge е правилната архитектурна точка за **контрол на автономността**.
Всичките 5 раздела от дизайна (policy, approval, audit, rollback, gateway interface)
живеят на едно място. При инцидент — един файл за debug. При промяна на policy — един файл.

Ако в бъдеще domain агентите имат нужда от силно различаващи се OpenClaw конфигурации
(различни модели, различни permissions), Опция B може да стане по-привлекателна.

**Финалното решение е на Ivan/Emil.**

---

## 8. Предлагани нови файлове (само имена, не код)

```
config/openclaw_action_policy.json     ← allowlist ruleset (Раздел 3)
agents/openclaw/openclaw_bridge.py     ← single bridge компонент (Раздел 4, 7)
memory/openclaw_pending_l3.json        ← L3 задачи чакащи одобрение (Раздел 5)
memory/openclaw_audit_log.json         ← rolling audit (backup в Merkle)
```

Промени в съществуващи файлове:
```
cortex_approval_server.py   ← нови /api/openclaw-* ендпойнти
fast_cycle_runner.py        ← извикване на bridge вместо директно openclaw_agent
```

---

## 9. Граници — какво този дизайн НЕ решава

- **Кои конкретни задачи да се делегират на OpenClaw** — това е логика на domain агентите,
  не на bridge-а. Bridge-ът не решава "кога да търсиш" — само "как и с какви права".

- **OpenClaw agent profiles** (`~/.openclaw/openclaw.json`) — конфигурацията на самите
  OpenClaw агенти (какви инструменти имат, какви ограничения) е отделна от CORTEX++ policy.
  Двата слоя се допълват: OpenClaw може да блокира действие на свое ниво; CORTEX++ policy
  блокира преди дори да се изпрати до OpenClaw.

- **Rate limiting и costs** — ако external OpenClaw ползва платени API, rate limiting не е
  покрит тук. Трябва отделен раздел при имплементация.

- **Multi-task паралелизъм** — дизайнът описва sequential flow. Ако domain агентите трябва
  да изпращат задачи паралелно, Bridge-ът трябва async queue — архитектурно решение за след
  верификация на gateway API.
