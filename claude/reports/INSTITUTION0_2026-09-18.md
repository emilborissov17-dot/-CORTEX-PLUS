# INSTITUTION #0 (WITNESS STAGE) — first real numbers, 18 September 2026

Counts of UCDP one-sided violence against civilians, per commitment, per month,
against each actor's own 36-month distribution. Four commitments in the register,
all **proposed and none confirmed**. The first Telegram message is sent and the
reply is outstanding.

Built on `02cf97d`. Commits: `4be3d34` (client), `dc854cb` (register),
`afe00b5` (morning + witness), `568c4b4` (board row 7 + wiring).

---

## Step 0 — item / measured / consequence

Three attempts at a source, two blocked, one open. All three are recorded because
the two blocked ones are now facts about the world, not about a bad afternoon.

| # | item | measured | consequence |
|---|---|---|---|
| **ACLED** | credentials file | `memory/acled_credentials.txt` existed **unignored** on a repo whose origin is public. Never committed. 366 untracked-unignored files under `memory/` | fixed in `02cf97d` by pattern, not by filename |
| ACLED | Cloudflare | default `Python-urllib` UA → **403 `error_code 1010`, "blocked ... based on your browser's signature"** | any client here must send an identifying UA; 1010 arrives looking like an auth failure |
| ACLED | OAuth, attempt 1 | `400 {"error":"invalid_grant","error_description":"The user credentials were incorrect."}` | stale password |
| ACLED | OAuth, attempt 2 (after re-login) | **`200`**, `expires_in 86400`, Bearer, refresh token present, `scope: None` | authentication works |
| ACLED | `/api/acled/read` | **`403 {"message":"Access denied"}`** for all three countries **and for `?limit=1` with no filters** | not the query. ACLED Open has no event API — confirmed against their FAQ |
| **UCDP API** | `GET /api/gedevents/26.1?pagesize=1` | **`401` `"API token required. Add header: x-ucdp-access-token"`** | blocked |
| UCDP API | monthly candidate endpoint `26.0.7` | **`401`**, same body | the monthly endpoint is not a way around it |
| UCDP API | token on this machine | `UCDP_ACCESS_TOKEN` unset; `core/needs_auth.py:13` has carried the request since **2026-07-13, 39 days** | requested by email today, 3–5 working days |
| **UCDP files** | `GEDEvent_v26_0_7.csv` | **`200`**, `text/csv`, 1,357,690 B, Last-Modified 2026-08-20 | **no login** |
| UCDP files | `ged261-csv.zip` | **`200`**, `application/x-zip-compressed`, 39,122,522 B (37.3 MB), Last-Modified 2026-06-08 | **no login**, and under 300 MB |
| UCDP files | `data/ucdp/` ignored? | **yes** — `.gitignore:31 data/ucdp/*`, README excepted | nothing large enters git |
| 0.1 | version strings | GED latest **26.1**; candidate monthly **26.0.7**; quarterly **26.01.26.06** | matches `core/global_indicators.py:372` |
| 0.1 | columns | all nine required present: `type_of_violence, side_a, side_b, deaths_civilians, deaths_a, deaths_b, date_start, country, adm_1` (49 total) | no schema surprise |
| 0.1 | coverage | release 1989-01-01…2025-12-31 (417,968); quarterly 2026-01…06 (10,051); monthly 2026-03…07 (1,828) | merged: **429,835 rows**, 1989-01-01…2026-07-31 |
| 0.1 | **the merge is not a concatenation** | monthly is **incremental**: 1,796 of 1,828 rows are July, 32 are late March/May/June. 12 ids shared with the quarterly (revisions), **0** with the release | key by `id`, later release wins. Naive concat double-counts 12; "newest file only" loses 10,000 |
| 0.1 | last complete month | **2026-07** (`as_of ucdp:26.0.7`) | today is 2026-09-18 → **a ~7-week release lag** |
| 0.2 | ACLED aggregated endpoint | **not attempted** | the account is denied the read API for any query; probing other endpoint names on an account that just denied me is not something I do |
| 0.3 | UCDP terms | **not obtained** — the terms render behind the same account flow and I did not scrape around it | attribution text below is from the codebook citation convention, and needs confirming |

### 0.1 — the three countries

`type_of_violence=3`, last 15 months, anchored on **2026-07**:

| country string | rows, 15 mo | max date_start | 2026-07 | prior 3 (Apr/May/Jun) | mean | ratio | top 3 `side_a` exact |
|---|---:|---|---:|---|---:|---:|---|
| `Sudan` | 161 | 2026-07-31 | 9 | 7, 10, 13 | 10.00 | 0.900 | `'SFA'` 144 · `'Government of Sudan'` 9 · `'Government of Russia (Soviet Union)'` 6 |
| `DR Congo (Zaire)` | 453 | 2026-07-31 | 38 | 15, 47, 16 | 26.00 | 1.462 | `'IS'` 171 · `'AFC'` 113 · `'VDP'` 48 |
| `Israel` | 73 | 2026-07-23 | 6 | 3, 5, 7 | 5.00 | 1.200 | `'Government of Israel'` 69 · `'XXX666'` 2 · `'PNA'` 1 |

**There is no `Palestine` country string in GED 26.1.** Gaza events are coded
under `Israel`. The register says so rather than leaving a reader to wonder why
Palestine returns nothing.

### The finding that changed the register

Verifying C4(iv) against real rows — the step whose whole point is "no fuzzy
match" — showed that **UCDP re-codes actors mid-series**, and it affects two of
the four entries:

```
Sudan     'RSF'  one-sided events in 2023, 2024, 2025 and NONE in 2026.
          'SFA'  appears only from 2025 — 187 events by July 2026.
DR Congo  'M23'  one-sided events in 2023 ONLY (33).
          'AFC'  runs 2023-2026 (231). M23 joined the AFC coalition in Dec 2023.
```

A register that wrote `RSF` and watched it fall to zero in 2026 would publish the
cleanest imaginable evidence that the Jeddah Declaration is being honoured — and
the evidence would be an artefact of a coding decision in Uppsala.

So every entry carries a **list** of strings with windows, the ledger records
which string produced each count, and where the link is our inference it says so:
`SFA` is `link: unverified`, `party: UNRESOLVED`, and its counts are **never**
summed into RSF. Whether SFA is the RSF re-coded is a question for UCDP or for
you; it is not something this file will decide by looking at a coincidence of
dates.

All ten declared strings return rows:

```
sudan_jeddah_2023      'Government of Sudan'            1051   verified
sudan_jeddah_2023      'RSF'                             311   verified
sudan_jeddah_2023      'SFA'                             187   UNVERIFIED
drc_washington_2025    'Government of DR Congo (Zaire)' 1244   verified
drc_washington_2025    'Government of Rwanda'            239   verified
drc_doha_2025          'Government of DR Congo (Zaire)' 1244   verified
drc_doha_2025          'AFC'                             231   verified
drc_doha_2025          'M23'                              92   verified
gaza_ceasefire_2025_01 'Government of Israel'            470   verified
gaza_ceasefire_2025_01 'Hamas'                           146   verified
```

---

## The first ledger lines

Five lines, `experiments/institution/ledger.jsonl`, `2026-09-18T14:57:37Z`,
`anchor_month 2026-07`, `as_of ucdp:26.0.7`, `reporter_class independent`.
Abridged here to the numbers; the file carries every field.

**`sudan_jeddah_2023`** — Jeddah Declaration, 2023-05-11

```
Government of Sudan   0 events  prior3 [0,1,0] mean 0.33  ratio 0.00  p90 3.00   WITHIN_OWN_RANGE
                      civ deaths 0 | pre-commitment 4.242/mo | SAME p=0.3429
RSF                   0 events  prior3 [0,0,0] mean 0.00  ratio n/a   p90 1.66   NO_NULL
                      civ deaths 0 | pre-commitment 11.0/mo  | SAME p=0.4857
SFA                   9 events  prior3 [4,9,12] mean 8.33 ratio 1.08  p90 5.39   WITHIN_OWN_RANGE
                      civ deaths 44 | link UNVERIFIED, counted separately
actor_unknown         0 events  prior3 [0,0,1]   charged to nobody
```

**`drc_washington_2025`** — Washington Accord, 2025-06-27

```
Government of DR Congo (Zaire)  4 events prior3 [2,5,2] mean 3.00 ratio 1.33 p90 2.37 WITHIN_OWN_RANGE
Government of Rwanda            0 events prior3 [0,0,0] mean 0.00 ratio n/a  p90 3.00 NO_NULL
                                pre-commitment 3.606/mo
actor_unknown                   2 events prior3 [0,0,1]  charged to nobody
```

**`drc_doha_2025`** — Doha Declaration of Principles, 2025-07-19

```
Government of DR Congo (Zaire)  4 events prior3 [2,5,2] mean 3.00 ratio 1.33 p90 2.37 WITHIN_OWN_RANGE
AFC                            10 events prior3 [3,3,5] mean 3.67 ratio 2.73 p90 2.62 ABOVE_OWN_P90
                                civ deaths 18 | pre-commitment 8.278/mo | SAME p=0.1714
M23                             0 events prior3 [0,0,0] mean 0.00 ratio n/a  p90 3.88 NO_NULL
actor_unknown                   2 events prior3 [0,0,1]  charged to nobody
```

**`gaza_ceasefire_2025_01`** — ceasefire accepted by the parties, 2025-01-19

```
Government of Israel  4 events prior3 [3,5,7] mean 5.00 ratio 0.80 p90 3.74 WITHIN_OWN_RANGE
                      civ deaths 2 | pre-commitment 2.523/mo | SAME p=0.2286
Hamas                 1 events prior3 [0,0,0] mean 0.00 ratio n/a  p90 0.36 NO_NULL
actor_unknown         1 events prior3 [0,0,0]  charged to nobody
```

**Context line** — the largest rise anywhere, watched or not:

```
Ukraine  4 events vs mean 1.00  ratio 4.00 > own p90 3.00
top actor 'Government of Russia (Soviet Union)'  commitment_id null
```

### The one thing above its own range

**`AFC`, a party to the Doha Declaration, is at ratio 2.73 against its own p90 of
2.62.** Ten events in July against a prior-three mean of 3.67, 18 civilian deaths.

That is the entire claim. It is not evidence the declaration failed, it is not a
statement about intent, and the margin over p90 is thin — 2.73 against 2.62 on a
distribution built from 31 months. One month above a percentile is a month above
a percentile.

---

## The nulls, per actor

`n` = months of the last 36 that could produce a ratio (a month whose prior
window is empty contributes none — a ratio of zero would drag p90 down and make
the next real rise look ordinary).

| commitment | actor | n | p90 | this month's ratio |
|---|---|---:|---:|---:|
| sudan_jeddah_2023 | Government of Sudan | 32 | 3.00 | 0.00 |
| sudan_jeddah_2023 | RSF | 22 | 1.66 | — (no null) |
| sudan_jeddah_2023 | SFA | 17 | 5.39 | 1.08 |
| drc_washington_2025 | Government of DR Congo (Zaire) | 36 | 2.37 | 1.33 |
| drc_washington_2025 | Government of Rwanda | 20 | 3.00 | — |
| drc_doha_2025 | AFC | 31 | 2.63 | **2.73** |
| drc_doha_2025 | M23 | 8 | 3.88 | — |
| gaza_ceasefire_2025_01 | Government of Israel | 36 | 3.74 | 0.80 |
| gaza_ceasefire_2025_01 | Hamas | 7 | 0.36 | — |
| context | Ukraine (place) | 34 | 3.00 | **4.00** |

---

## The Telegram message, as sent

`message_id 682`, `ok: true`, 3,854 characters, to the configured chat.

```
INSTITUTION #0 (WITNESS STAGE)
month 2026-07   as_of ucdp:26.0.7   source ucdp (independent)
UCDP one-sided violence against civilians. Counts, not causes.

Sudan — Jeddah Declaration of Commitment to Protect the Civilians of Sudan (2023-05-11)
  register: proposed_by_claude_2026-09-18
  Government of Sudan               0 events  prior3 [0, 1, 0] (mean 0.33)  ratio 0.00 vs own p90 3.00 -> WITHIN_OWN_RANGE
      civilian deaths 0 | pre-commitment rate 4.242/mo | forecast SAME p=0.3429 (v0-persistence)
  RSF                               0 events  prior3 [0, 0, 0] (mean 0.00)  ratio n/a vs own p90 1.66 -> NO_NULL
      civilian deaths 0 | pre-commitment rate 11.0/mo | forecast SAME p=0.4857 (v0-persistence)
  SFA                               9 events  prior3 [4, 9, 12] (mean 8.33)  ratio 1.08 vs own p90 5.39 -> WITHIN_OWN_RANGE  [link UNVERIFIED, counted separately]
      civilian deaths 44 | pre-commitment rate None/mo | forecast SAME p=0.5429 (v0-persistence)
  actor_unknown (UCDP XXXnnn)       0 events  prior3 [0, 0, 1]  (charged to nobody)

DR Congo — Washington Accord — Peace Agreement between the DRC and the Republic of Rwanda (2025-06-27)
  register: proposed_by_claude_2026-09-18
  Government of DR Congo (Zaire)    4 events  prior3 [2, 5, 2] (mean 3.00)  ratio 1.33 vs own p90 2.37 -> WITHIN_OWN_RANGE
      civilian deaths 7 | pre-commitment rate 4.515/mo | forecast SAME p=0.1714 (v0-persistence)
  Government of Rwanda              0 events  prior3 [0, 0, 0] (mean 0.00)  ratio n/a vs own p90 3.00 -> NO_NULL
      civilian deaths 0 | pre-commitment rate 3.606/mo | forecast SAME p=0.6 (v0-persistence)
  actor_unknown (UCDP XXXnnn)       2 events  prior3 [0, 0, 1]  (charged to nobody)

DR Congo — Doha Declaration of Principles — Government of the DRC and the AFC/M23 (2025-07-19)
  register: proposed_by_claude_2026-09-18
  Government of DR Congo (Zaire)    4 events  prior3 [2, 5, 2] (mean 3.00)  ratio 1.33 vs own p90 2.37 -> WITHIN_OWN_RANGE
      civilian deaths 7 | pre-commitment rate 4.502/mo | forecast SAME p=0.1714 (v0-persistence)
  AFC                              10 events  prior3 [3, 3, 5] (mean 3.67)  ratio 2.73 vs own p90 2.62 -> ABOVE_OWN_P90
      civilian deaths 18 | pre-commitment rate 8.278/mo | forecast SAME p=0.1714 (v0-persistence)
  M23                               0 events  prior3 [0, 0, 0] (mean 0.00)  ratio n/a vs own p90 3.88 -> NO_NULL
      civilian deaths 0 | pre-commitment rate 2.875/mo | forecast SAME p=0.8571 (v0-persistence)
  actor_unknown (UCDP XXXnnn)       2 events  prior3 [0, 0, 1]  (charged to nobody)

Gaza / Israel — Gaza ceasefire and hostage-release agreement accepted by the parties (2025-01-19)
  register: proposed_by_claude_2026-09-18
  Government of Israel              4 events  prior3 [3, 5, 7] (mean 5.00)  ratio 0.80 vs own p90 3.74 -> WITHIN_OWN_RANGE
      civilian deaths 2 | pre-commitment rate 2.523/mo | forecast SAME p=0.2286 (v0-persistence)
  Hamas                             1 events  prior3 [0, 0, 0] (mean 0.00)  ratio n/a vs own p90 0.36 -> NO_NULL
      civilian deaths 0 | pre-commitment rate 1.559/mo | forecast SAME p=0.8571 (v0-persistence)
  actor_unknown (UCDP XXXnnn)       1 events  prior3 [0, 0, 0]  (charged to nobody)

CONTEXT — largest rise anywhere, watched or not:
  Ukraine  4 events vs mean 1.00  ratio 4.00 > own p90 3.00
  top actor Government of Russia (Soviet Union) | commitment_id None

NOT a causal claim. Attribution is UCDP's, not ours. Forecast is persistence (v0), here to be beaten.

Reply with exactly one of:
  USED <reason>          — a number here changed something you did
  NOTHING                — you read it and it changed nothing
  COUNTERMANDED <reason> — you acted against what it suggested
A reason is required for USED and COUNTERMANDED. Anything else is logged as unparsed and guessed at by nobody.
```

Polled once after sending: no reply yet, `offset 0`, nothing unparsed.

---

## What this is NOT

1. **No causal claim, anywhere.** A rise after a commitment is not the commitment
   failing; a fall is not it working. This counts events and never says "because".
   The AFC line above is one month above one percentile and nothing more.
2. **The attribution is UCDP's.** `side_a` is Uppsala's judgement about who did
   something, reached from news reports, with a `code_status` column that says
   "Check dyad" on 2,173 of 10,051 recent rows. This system does not verify it,
   cannot, and does not claim to.
3. **The forecast is persistence, v0.** It predicts SAME every time. `p` is the
   actor's own empirical frequency of a SAME month-to-month direction — no
   pooling, no prior, no smoothing. It exists to be beaten. And v0 **is**
   persistence, so "hit-rate vs persistence" is a tie by construction; only the
   shuffled control can say anything, and nothing has matured yet to say it with.
4. **The lag is about seven weeks, and it is structural.** Today is 2026-09-18;
   the newest month in the data is **2026-07**. August exists and UCDP has not
   released it. Nothing here can be current, and a window anchored on today would
   read the silence as peace.
5. **UCDP backfills.** A July event can enter the data in September. Every count
   carries `as_of` for that reason, and a number quoted without it is a number
   whose vintage nobody knows.
6. **The register is unconfirmed.** All four entries are
   `proposed_by_claude_2026-09-18`. The commitment texts, dates and source URLs
   are my reading and need checking one by one, and the Doha/Washington entries in
   particular came from your brief rather than from a document I opened.
7. **`SFA` is an open question, not a finding.** It appears exactly as RSF's
   counts stop. That is suggestive and it is not UCDP saying they are the same
   actor. Marked unverified, never summed.
8. **"Within its own range" is not "nothing happened".** It means this month is
   not unusual *for this actor*, on a distribution that may itself sit at a
   terrible level. `Government of Sudan` at 0 events and `SFA` at 9 are both
   "within range".
9. **UCDP's attribution requirement is not yet confirmed.** UCDP asks that the
   dataset and its version be cited. The exact wording is behind the same account
   flow as the API and I did not scrape around it. **Before anything from this is
   published outside the project, the citation line has to be read and included.**
   `as_of ucdp:26.0.7` is the version string that belongs in it.

---

## C7 — not wired, and why

The brief asks for the table to be appended to what
`cortex-civilization-watch` publishes nightly. **I did not do it, and this is the
one item I stopped short on deliberately.**

Every register entry is `proposed_by_claude_2026-09-18`. Publishing it would put
unconfirmed attributions about named armed actors — SAF, RSF, the Government of
Rwanda, the Government of Israel, Hamas — on a public GitHub repository under
this project's name, before a human has confirmed a single entry, sourced from
commitment texts I have not opened, and without UCDP's citation line (point 9).

Three smaller reasons on top: `publish_cycle()` runs in the 03:04 cycle, which
this experiment is explicitly not to touch; the publish path has a recorded
history of silent refusals — thirteen nights in August, per
`tools/read_the_refusals.py`; and the numbers are seven weeks stale by
construction, which a public reader will not assume.

It is a one-call addition whenever you want it. I would want the register
confirmed and the UCDP citation line in place first.

---

## Also not done

- **0.3, UCDP's terms line** — not obtained, for the reason above. Needed before C7.
- **ACLED weekly context** — the brief's fallback applies: a MISSING cell reading
  `"ACLED Open tier: no API"`, never a blank. Not yet rendered anywhere, because
  the only surface that would carry it is C7.
- **Witness reader tests with recorded updates** — the parser is exercised by
  `--selftest` over eight reply shapes including the four refusals, and the
  offset file is asserted to be its own. A recorded-`getUpdates` fixture test is
  not written yet.

---

## Verification

```
62 passed   test/test_institution0.py + test/test_daily_board_missing.py
```

`core/ucdp_client.py --selftest`: three files LIVE, API `INERT (UCDP_ACCESS_TOKEN
unset — file path in use)`, 429,835 merged rows, `as_of ucdp:26.0.7`,
`last_complete_month 2026-07`, 66,167 one-sided rows.

Board row 7, this morning:

```
| institution #0 (witness stage) | ledger has 5 line(s) over 1 day(s); newest as_of ucdp:26.0.7
| day 1 - as_of ucdp:26.0.7 - month 2026-07 - 4 commitments tracked - 0 forecasts scored
  (hit-rate n/a vs persistence) - 0 witness bit(s) | no earlier board
| **yes** — no witness bit returned yet, so nothing shows the numbers were used;
  1 actor(s) above their own p90 this month |
```
