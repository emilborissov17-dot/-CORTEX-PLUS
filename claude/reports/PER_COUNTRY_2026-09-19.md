# PER-COUNTRY LAYER — run, diffed, explained, wired. 19 September 2026

The layer had not run since 2 July. Two axes were scored from its output into
every night's composite as if it were current. It now runs at 09:00.

Commits: `99dcf60` provenance · `<wiring>` the 09:00 chain · this report.

---

## 1 — The provenance was a lie, and it is fixed (`99dcf60`)

`goal_score_calculator` reported `observation_where: "last_observations"` for all
sixteen axes. That is the name of a **local dict**, not a file:

```python
last_obs = {**load_last_obs(), **load_governance_globals(),
            **load_global_indicators(), **load_probed_signals()}
```

Four files merged, later wins, one hardcoded literal returned for every key. A
reader following it landed on `data/last_observations.json` — written
2026-06-17, eight bare scalars, no date anywhere in it, missing four of the
sixteen keys.

**A correction to my own report of yesterday.** The *values* were never coming
from that stale file. `load_global_indicators()` overrides it and already
recorded a real date and a reason per key. The numbers were right; only the label
was false. A smaller defect than I implied, and a sharper one — a checkable claim
that failed its own check.

**My first repair was still unfollowable, and the check caught it.** The loaders
recorded the *adapted* key (`wb_SE.ADT.1524.LT.ZS`), which appears nowhere in the
payload — the file holds `world_bank.literacy_rate_youth_pct`. Sixteen of sixteen
still failed. `observation_where_field` is now the path **into** the file:

```
CLIMATE      snapshots/master/global_indicators_latest.json  co2.co2_ppm
ENERGY       snapshots/master/global_indicators_latest.json  world_bank.renewable_energy_pct
SOCIAL       snapshots/master/global_indicators_latest.json  displaced.refugees_millions
GOVERNANCE×2 output/wellbeing_globe.json                     governance_*_score
...
UNFOLLOWABLE provenance entries: 0
```

A key no loader claimed reports `UNCLAIMED` rather than inheriting a
plausible-looking filename — a wrong-but-plausible path is harder to catch than
an obvious gap. The live check is `live_state` (it reads files the cycle
rewrites); four deterministic tests gate, including one pinning `UNCLAIMED` and
one pinning merge precedence.

---

## 2 — The run

### The chain is three scripts, not two

**My own recommendation of yesterday named the wrong entry point**, and so did
the brief. `wellbeing_country.py` is a **single-country CLI**
(`python wellbeing_country.py BG`). The batch driver is `wellbeing_batch.py`, and
`wellbeing_globe.py` says so in its own error path:

```python
if not ALL_CTRY.exists():
    print(f"ERROR: {ALL_CTRY} not found — run wellbeing_batch.py first")
```

Anyone wiring from my report would have wired a script that scores one country.

```
wellbeing_batch.py  ->  output/wellbeing_all_countries.json
wellbeing_globe.py  ->  output/wellbeing_globe.json + wellbeing_continent.json
```

### Runtime and output

| | |
|---|---|
| command | `venv\Scripts\python.exe wellbeing_batch.py --workers 6` |
| runtime | **1817 s (~30 min)**, 217 countries, CPU only, no GPU |
| started | 10:38 local, 19 Sep — deliberately not during the 03:04 cycle |
| output | `output/wellbeing_all_countries.json`, `computed_at 2026-09-19T08:08:45Z`, 217 rows |
| before | same path, `computed_at 2026-07-02T07:16:08Z` — **79 days** |

### The diff

```
countries in both        : 217   (none added, none dropped)
any dep/str/flo change   : 198 of 217
zone changed             :  13
axis coverage changed    :  37   — every one an INCREASE; no country lost an axis

direction, all 217:
  deprivation  up  74  down 117  unchanged  26   mean move -0.0050
  strain       up  74  down 113  unchanged  30   mean move -0.0050
  flourishing  up  67  down  45  unchanged 105   mean move +0.0004
```

**I misread this at first.** The ten largest moves are nearly all `strain` down,
which looked like a systematic one-directional shift. It is not: across all 217
the split is 74/113 with a mean move of −0.005. The top-10 list was a tail, not a
trend.

### The ten largest moves

| iso | country | field | before | after | Δ |
|---|---|---|---:|---:|---:|
| JG | Channel Islands | strain | 0.3320 | 0.1780 | −0.1540 |
| WS | Samoa | strain | 0.3660 | 0.2500 | −0.1160 |
| SR | Suriname | strain | 0.4300 | 0.3160 | −0.1140 |
| EC | Ecuador | strain | 0.6110 | 0.5010 | −0.1100 |
| BJ | Benin | deprivation | 0.6090 | 0.5020 | −0.1070 |
| LC | St. Lucia | strain | 0.3510 | 0.4540 | +0.1030 |
| VU | Vanuatu | strain | 0.3930 | 0.2910 | −0.1020 |
| SK | Slovak Republic | strain | 0.3370 | 0.2350 | −0.1020 |
| DE | Germany | strain | 0.2940 | 0.1930 | −0.1010 |
| TZ | Tanzania | strain | 0.4070 | 0.3180 | −0.0890 |

### The thirteen zone changes, all explained

**Eight are threshold crossings.** Every one sits at `deprivation ≈ 0.40`, which
is a zone boundary, and moved less than 0.025 across it:

```
AG 0.382 -> 0.401   BW 0.411 -> 0.390   FM 0.401 -> 0.399   NA 0.415 -> 0.391
NP 0.412 -> 0.397   PH 0.381 -> 0.397   PS 0.409 -> 0.398   GA 0.348 -> 0.401
```

A flip from a 0.004 move is the boundary doing its job, not the data moving.

**Five moved ≥ 0.06 — and four of those five also gained real axes**, which
changes the set the score is computed over:

```
BO Bolivia    13/17 real -> 15/17   (3 suspect -> 1)
HN Honduras   15/17 real -> 16/17   (2 suspect -> 1)
LC St. Lucia  12/17 real -> 14/17   (3 null,2 suspect -> 2 null,1 suspect)
TC Turks&Cai   9/17 real -> 10/17   (2 suspect -> 1)
```

### Ecuador — the one I could not explain, and then could

`EC` moved `strain` 0.611 → 0.501 with **no** coverage change. That was the one
unexplained move, and the instruction was to stop rather than wire a layer whose
output I cannot explain.

It closes. `output/wb_cache/` is **tracked in git**, so the 2 July cache is
recoverable:

```
$ git show HEAD:output/wb_cache/EC.json   vs   output/wb_cache/EC.json

EG.ELC.ACCS.ZS      98.7   ->  98.5
NY.ADJ.DRES.GN.ZS   None   ->  5.74761865404566
NY.GDP.MKTP.KD.ZG   None   ->  3.72594857272087
NY.GDP.PCAP.PP.KD   13935.5 -> 14319.2
SI.POV.DDAY         None   ->  3.4
VDEM_CORR           None   ->  0.348
VDEM_RULE           None   ->  0.372

unchanged indicators: 28 of 35
```

Five indicators went from `None` to a real value — poverty, GDP growth, natural
resource depletion, and both V-Dem governance measures. Ecuador gained five real
inputs it did not have in July. A 0.11 strain move on that is expected, not
anomalous.

**A limitation this exposed, worth fixing later:** the batch output stores only
`dep/str/flo` plus the null/suspect lists — **no per-axis values**. Without the
tracked `wb_cache` I could not have attributed any move at all. The layer is
auditable today by accident of `wb_cache` being in git, not by design.

### The three hand checks — exact matches

Run `wellbeing_country.py <ISO>` and compared to the batch row:

| | CLI dep/str/flo | batch AFTER | batch BEFORE | zone |
|---|---|---|---|---|
| **BG** Bulgaria | 0.251 / 0.295 / 0.809 | **0.251 / 0.295 / 0.809** | 0.250 / 0.293 / 0.809 | unchanged |
| **SD** Sudan | 0.523 / 0.372 / 0.392 | **0.523 / 0.372 / 0.392** | 0.529 / 0.378 / 0.392 | unchanged |
| **NO** Norway | 0.123 / 0.127 / 0.888 | **0.123 / 0.127 / 0.888** | 0.131 / 0.136 / 0.888 | unchanged |

Three for three, to three decimals. The batch is not doing something different
from the single-country path.

---

## 3 — The wiring, and the trap found while doing it

### The globe must run TWICE, and this is not optional

A plain `wellbeing_globe.py` run **wiped the governance fields to null**:

```
                                before                    after plain run
governance_computed_at          2026-07-09T07:22:47       None
governance_rights_score         0.432078                  None
governance_institutions_score   0.443037                  None
```

`goal_score_calculator.load_governance_globals()` returns `{}` when
`governance_computed_at` is absent, and **both governance axes fall back to 0.5**
with a stderr warning. Running the first command without the second is strictly
worse than running neither — it replaces a 79-day-old real number with no number
at all.

`wellbeing_globe.py --governance-only` restores them. Both are wired.

### What was added to `tools/prophecy_morning.bat`

```bat
call :step "wellbeing_batch"       "%PY% wellbeing_batch.py --workers 6"       no
call :step "wellbeing_globe"       "%PY% wellbeing_globe.py"                   no
call :step "wellbeing_governance"  "%PY% wellbeing_globe.py --governance-only" no
```

Placed **before** `institution0` and `daily_board`, so row 8 reads what they
wrote. `REFUSAL_OK` is `no`: the batch has no refusal path, so a non-zero exit is
a real failure. **Never in the 03:04 cycle** — 30 minutes of many-request fetching
is what the cycle's memory budget dies of.

### The globe, before and after

| | before (2026-07-02) | after (2026-09-19) |
|---|---|---|
| `computed_at` | 2026-07-02T07:19:06 | **2026-09-19T08:12:09** |
| `governance_computed_at` | 2026-07-09T07:22:47 | **2026-09-19T08:12:30** |
| dep / str / flo | 0.33168 / 0.312849 / 0.675248 | 0.344992 / 0.323703 / 0.668202 |
| zones | DL 109, Prec 74, Thr 26, Sec 5, Crisis 3 | DL 107, Prec 71, Thr 30, Sec 6, Crisis 3 |
| governance rights / institutions | 0.432078 / 0.443037 | **0.431231 / 0.452028** |

---

## 4 — Row 8, before and after

```
BEFORE  axes fed 12/24 (world value AND obs date), of which 11 stale >30d;
        4 fed with NO date;
        countries with >=3 measured axes 217/217 as of 2026-07-02 (79 d old)

AFTER   axes fed 12/24 (world value AND obs date), of which  9 stale >30d;
        4 fed with NO date;
        countries with >=3 measured axes 217/217 as of 2026-09-19 (0 d old)
```

| | before | after |
|---|---:|---:|
| `axes_fed_world` | 12/24 | 12/24 |
| **stale > 30 d** | **11** | **9** |
| fed with no date | 4 | 4 |
| `countries_with_3_axes` | 217/217 | 217/217 |
| **country as-of** | **2026-07-02 (79 d)** | **2026-09-19 (0 d)** |

`axes_fed_world` did not move and should not have: no axis gained or lost a
source. What moved is the two governance axes leaving the stale column —
`observed_at` went from `2026-07-09` to `2026-09-19` — and the country file
becoming today's. Composite 0.6246 → **0.6251**; `coverage_of_goal` unchanged at
0.6826.

---

## What this does NOT fix

1. **Four axes still carry no observation date.** ECONOMY_WORK, FOOD,
   INFRASTRUCTURE_CITIES, MATERIALS_WASTE. The date lives in the World Bank API's
   `date` field and the `wb_<CODE>` ingest path does not record it. Untouched —
   it is in `core/global_indicators.py` and affects every axis.
2. **Nine axes remain stale.** ENERGY is scored on a 2020 observation,
   SOCIAL_RELATIONS on 2022. Running the per-country layer does not change what
   the World Bank has published.
3. **The batch stores no per-axis values**, so a future diff will again be
   unattributable unless `wb_cache` stays in git.
4. **`countries_with_3_axes` is a ceiling already.** 217/217 before and after; the
   number that can still move is `>=10 measured axes`, which was 203/217.
5. **The twelve per-country sources are not started**, as instructed.

## One thing to decide

The batch takes **30 minutes every morning**. It is CPU-only and outside the
cycle, so nothing competes with it, but it is now the longest step in the 09:00
task by a wide margin. If that proves too long, `--resume` exists and the natural
next move is a weekly full run with a daily `--governance-only`, since the
governance globals are the only part two axes actually read.
