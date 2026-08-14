# CORTEX++ RUNBOOK — как се оперира системата (за Емил и Иван)

Една страница. Ако операторът изчезне за седмица, този файл е системата.
(Написан от Claude, 14 авг 2026. Английските команди са за копиране в CMD.)

## Къде живее всичко
- Репо: `C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED` (GitHub: emilborissov17-dot/-CORTEX-PLUS, публично)
- Python: ВИНАГИ `venv\Scripts\python.exe` (системният python НЕ е на PATH)
- Ключове: `.env` в корена (план: премести в `%USERPROFILE%\.cortex\.env` — кодът вече търси първо там)
- Telegram бот: конфиг в `memory\notify_channel.json` (token + chat_id на Емил)
- Одобрения: отговори в Telegram чата — `OK <id>` приема, `NO <id>` отказва

## Пулс на системата (проверка за 30 секунди)
```
venv\Scripts\python.exe supervisor.py --status
type memory\scheduler_state.json
```
Здраво = днешна дата в last_run, failure: null. Цикълът върви в 03:00 (или catch-up до 20ч закъснение при спрян лаптоп).

## Стартиране / спиране
- Планировчикът е Windows Scheduled Task **CORTEX_Supervisor** (тик на 5 мин):
  - Спиране:  `schtasks /Delete /TN "CORTEX_Supervisor" /F`
  - Проверка: `schtasks /Query /TN "CORTEX_Supervisor"`
- Ръчен цикъл (само за тест): `venv\Scripts\python.exe fast_cycle_runner.py`
- Заклещен lock: НЕ трий на ръка — supervisor-ът сам чисти доказано-мъртви lock-ове.

## Къде да гледаш, когато нещо не е наред
| Симптом | Файл |
|---|---|
| Цикълът не е минал | `logs\supervisor.log` (опашката) + `memory\existence_ledger.jsonl` |
| Стъпка умира | `memory\cycle_logs\cycle_<дата>.log` + `config\scheduler.json` (тавани) |
| LLM мълчи | `memory\llm_provenance.jsonl` (кой backend отговаря) + грешки в cycle лога |
| „Болка"/самомодел | `memory\existence_latest.json` |
| Какво чака човек | `memory\pending_approvals.json` + `notes\next_actions.txt` |
| Карантина | `venv\Scripts\python.exe scripts\review_quarantine.py` |

## Твърди правила (не се нарушават и от хора)
1. BOUNDARIES.md не се пипа (canon hash — цикълът отказва при промяна).
2. V-Dem CSV файлове НЕ се комитват (лиценз).
3. Churn-ът (memory/, snapshots/, news/) НЕ се комитва — само код.
4. Промени в scoring се проверяват на познати държави преди 217.
5. config/scheduler.json и config/pulse.json са човешка територия.

## Дневен надзор (автоматичен, от Claude)
- 12:00 Атина — доказателствен доклад (push+email до Емил)
- 19:00 Атина — ремонтен обход (поправя код, докладва само при находка)
- Протокол: проект CORTEX++, `claude/DAILY_PROOF_PROTOCOL.md`

## Ключове и достъпи (кой какво държи)
- Емил: лаптопът, .env ключовете (Groq/Cerebras/OpenRouter/Gemini/YouTube/NASA/UCDP), Telegram чатът с бота, GitHub акаунтът, SFF кореспонденция (негова поща).
- Иван: Claude акаунтът (мостът, дневните обходи), krastev111@gmail.com (получава Netriva+магазинни известия), maintainer-вото по BOUNDARIES (втори глас при amendment).
- Загубен .env → ключовете се преиздават от съответните конзоли (безплатни tier-ове), нищо не е невъзстановимо.

## Ако системата трябва да се спре ЗАВИНАГИ
`schtasks /Delete /TN "CORTEX_Supervisor" /F`, после архивирай `memory\` + `cortex_memory\` (Merkle историята е биографията — тя е незаменимата част; кодът е в GitHub).
