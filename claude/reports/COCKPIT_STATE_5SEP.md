# THE COCKPIT — can Emil actually see the system react?
### 5 September 2026, 12:00. Read-only. No fixes.

**Short answer: no, because nothing starts it.** Everything behind it works — 25 of 26
endpoints return 200 with real data, the three contradiction sites are fixed, and the
panels read fresh sources. But no scheduled task, no service and no running process launches
`cockpit/server.py`. It is a file, not a window.

---

## 1. IS IT RUNNING? — NO, AND NOTHING WOULD EVER START IT

```
listening ports (127.0.0.1)     : 11434 only  — that is Ollama
python.exe processes            : 3, none of them the cockpit
port the cockpit would use      : 5055  (cockpit/server.py:53)
```

Nine CORTEX scheduled tasks exist and are all `Ready`:

```
CORTEX_Approvals   CORTEX_Collector   CORTEX_HyperCortex   CORTEX_Intel
CORTEX_Prophecy    CORTEX_Pulse       CORTEX_Supervisor    CORTEX_TriggerWatchdog
CORTEX_WebIntel
```

**Not one of them mentions the cockpit.** Every scheduled action was searched for the string
`cockpit`; there are no matches. Started by: **nothing**. It runs only if a human types

```
venv\Scripts\python.exe -m cockpit.server --port 5055
```

That is the whole answer to "can he see it": not unless he starts it by hand, every time.

---

## 2. EVERY `GET /api/*`, EXERCISED

Run through Flask's test client — real handler code, no port bound, nothing left running.

| endpoint | status | ms | reading |
|---|---:|---:|---|
| `/api/ask` | 200 | 6 | DATA — queue with answered rows |
| `/api/axis/<name>` | 200 | 9 | honest empty: `empty_because: "no score and no history"` |
| `/api/blocked` | 200 | 2 | `available: false`, counters empty — firewall log not readable |
| `/api/brain` | 200 | 3 | DATA — but `ts 2026-08-28`, eight days old |
| `/api/brain/matrices` | 200 | 2 | DATA — W1 shape [2059, 256] |
| `/api/columns` | 200 | 3 | DATA — five columns |
| `/api/cycles` | 200 | 10 | DATA |
| `/api/entropy` | 200 | 41 | partial: ambient light `built: false, readable: false` |
| `/api/expression` | 200 | 123 | DATA (see §4) |
| `/api/flow` | 200 | 6 | DATA — `cycle_id 2026-09-05T03…`, **last night** |
| `/api/forks` | 200 | 1 | stale cache: `count 0`, `ts 2026-08-22`, two weeks old |
| `/api/free` | 200 | 7 | `count: 0` — empty, and says why |
| `/api/glass` | 200 | 23 | composite; inherits `blocked`'s unavailability |
| `/api/goal` | 200 | 5 | DATA — composite history present |
| `/api/panels` | 200 | 3 | DATA — and honest: `live: false, missing: [memory/heartbeat.json]` |
| `/api/pending` | 200 | 5 | DATA — 28 open improvement proposals |
| `/api/proposals` | 200 | 0 | DATA — 12 rows, `(unattributed)` |
| `/api/reaction` | 200 | 1 | DATA — `enabled: false` |
| `/api/region/<rid>` | 200 | 3 | `aggregate: null`, computed 2026-07-02 — **two months old** |
| `/api/run/<key>` | **404** | 0 | correct: `not an allowlisted read-only command` + the allowlist |
| `/api/somatic` | 200 | **5953** | DATA — 31 live sensors (see §4) |
| `/api/somatic/selftest` | 200 | 3800 | 31 PASS, 3 SKIP, 8 N/A |
| `/api/stream` | 200 | 2 | DATA — receptor buffer |
| `/api/thoughts` | 200 | 25 | DATA — debriefs |
| `/api/timeline` | 200 | 219 | DATA — 71 brain_stance, 7 expression, 4 digest |
| `/api/toggle` | 200 | 2 | DATA — mic and camera both false |

**25 of 26 return 200. The one 404 is correct behaviour** — `/api/run/<key>` refuses a key
that is not on the read-only allowlist and returns the allowlist with the refusal. I probed
it with an invented key.

**Nothing errored. Nothing returned a 500.** Where a panel has no data it mostly says so in
a named field (`empty_because`, `why`, `available: false`, `missing: [...]`) rather than
rendering a plausible zero — which is the opposite of the defect being hunted elsewhere in
this repo.

**Three panels are quietly OLD rather than empty**, and this is the one place a reader could
be misled: `/api/brain` (2026-08-28), `/api/forks` (2026-08-22, `from_cache: true`), and
`/api/region` (2026-07-02). They return `DATA` and a panel would render them as current.

---

## 3. THE THREE CONTRADICTION SITES — ALL FIXED

| site | state |
|---|---|
| `server.py:1025-1027` → now `/api/reaction` `why_off` | **FIXED** — derived from `rx.enabled()` |
| `server.py:1059-1061` → now `/api/free` `empty_why` | **FIXED** — derived from `_rx_enabled()` |
| `cockpit.html:1209-1212` | **GONE** — that line is now audio code; `reactions.json` appears nowhere in the template |

Both Python fixes carry the incident in a comment: on 2026-08-28 the panel rendered
*"ENABLED: reaction.enabled is false in config/reactions.json"* — the status word re-read
the file, the sentence beside it was frozen at the moment somebody wrote it. `_rx_enabled()`
now fails **closed**: a panel that cannot read the flag must not claim it is on.

### Any OTHER live-flag-beside-frozen-prose?

AST scan over all of `cockpit/`: every dict literal holding a **computed** value under a
flag key (`enabled`, `live`, `available`, `ok`, `built`, `readable`, `validated`, …) **and**
a **string constant** over 25 chars under a prose key (`why`, `note`, `reason`,
`empty_because`, `hint`, `label`, …).

**One candidate, and on reading it is a false positive.** `cockpit/glass.py:126` pairs
`available: raw["available"]` with a constant `note`. But the flag already has its own
derived explanation on the line above — `"why": raw["why"]` — and the `note` is a caption
about what the panel *contains* ("Most of this is internet background noise… It is not an
attack log"), not a claim about the flag's state. A static caption is not the defect.

**So: no remaining instances of the class in the cockpit.**

---

## 4. THE EXPRESSION WINDOW AND THE SOMATIC MAP

### Expression — reads `memory/expression_stream.jsonl`, and it HAS last night

```
memory/expression_stream.jsonl   3,066,669 bytes   8,252 rows
rows per day: 08-31:27  09-01:7  09-02:7  09-03:20  09-04:19  09-05:8
2026-09-05 rows: 8, from 00:12:11Z to 02:08:13Z
```

The cycle ran 00:04:03Z–02:08:17Z, so **all of last night's rows fall inside the cycle
window.** The newest before my probe: `model | "QUERY sensor_log_errors_24h:4.0"` at
02:08:13Z, seconds before the cycle sealed. This panel is live.

Its two other sources are not:

```
memory/pending_expression.json          mtime 2026-08-28 18:56   — 8 days
memory/expression_quarantine/  6 files  newest rejected_2026-08-29.jsonl
```

### Somatic — a LIVE hardware probe, not a stored file

`/api/somatic` calls `som.probe(mic_enabled, camera_enabled)` directly. It does not read a
cycle artifact at all, which is why it took **5.9 seconds** and returned
`available_count: 31`. It is always "now" and does not depend on the cycle having run.
`memory/state_vectors.jsonl` has one row per day including **2026-09-05T02:08:16Z**, written
as the cycle sealed.

### AND READING IT WRITES

Probing `/api/somatic` **appended a row to `memory/expression_stream.jsonl`**:

```
2026-09-05T08:49:25Z | env | aggregate | "31 sensors moved, largest: battery_percent — TRUNCATED: over 20 pulse…"
```

That is my own read, recorded as an observation of the system. The panel is not read-only in
the sense a reader would assume: opening the somatic tab writes into the same stream the
expression window displays. Noted rather than judged — but it means **I perturbed the thing
I was measuring**, and anyone reading the expression window after opening the somatic tab is
partly reading their own visit.

---

## 5. DEBRIEF (what the model SAID) vs PHASE REPORT (what the check MEASURED)

Vocabularies: the model says `OK / DEGRADED / BROKEN`; the check measures
`DONE / PARTIAL / FAILED`. **No field anywhere records whether they agree.**

Across all 36 cycle dirs, 197 phase reports, 186 with a debrief verdict:

```
OK        vs DONE        79
DEGRADED  vs PARTIAL     50
DEGRADED  vs DONE        46      cautious, not a contradiction
OK        vs PARTIAL     11      <-- CONTRADICTION
-         vs PARTIAL     11      no debrief at all
```

**11 contradictions in 11 of 36 cycles** — the model reported `OK` for a phase the check
measured `PARTIAL`, i.e. said fine about a phase that did not produce what it promised.

```
by phase: E_PROPOSE 7 · G_LEARN 2 · A_ORIENT 1 · B_SENSE 1
```

E_PROPOSE is two thirds of them, and E_PROPOSE is also the phase whose promised
`memory/runtime_experiences.json` has been stale since 28 August.

Debrief state overall: **167 accepted, 20 REJECTED, 10 missing.**

### Last night — zero contradictions

```
A_ORIENT     said=OK        measured=DONE      accepted
B_SENSE      said=OK        measured=DONE      accepted
C_SNAPSHOT   said=OK        measured=DONE      accepted
D_SCORE      said=OK        measured=DONE      accepted
E_PROPOSE    said=DEGRADED  measured=PARTIAL   accepted
F_SELF       said=DEGRADED  measured=PARTIAL   accepted
G_LEARN      said=OK        measured=DONE      REJECTED
```

The model caught both PARTIAL phases and said DEGRADED for each. `G_LEARN`'s debrief was
**rejected** by the debrief validator — so the cockpit would show no G_LEARN sentence at
all, for a phase that in fact completed DONE.

---

## WHAT WOULD ACTUALLY LET EMIL SEE THE SYSTEM REACT

1. **Something has to start it.** A tenth scheduled task, or a shortcut. Until then the
   answer to "can he see it" is "only if he remembers the command".
2. **The three stale panels need an age on them.** `/api/brain` at 8 days, `/api/forks` at
   14, `/api/region` at 2 months all render as current data. Every other panel here names
   its own emptiness; these name nothing.
3. **The debrief/report agreement is computable and is computed nowhere.** 11 historical
   contradictions exist and no field records one. The cockpit shows the model's sentence;
   the disagreement with the measured verdict is exactly what a human should see.

Not fixed, per instruction. Recorded.
