# OPENCLAW — axis tasks, 13 September 2026

Fourteen blocks, one per axis, each ready to paste into the agent's window at
`http://127.0.0.1:18789` as-is. Nothing here needs editing before it is sent.

**Return exactly this shape, one JSON object per line, nothing else:**

```json
{"card":"A","axis":"...","key":"...","value":0.0,"unit":"...","url":"https://...","quote":"...","observed_date":"YYYY-MM-DD"}
```

`quote` must be the **literal characters from the page or file** that contain the
number — copied, not paraphrased. `core/quote_gate.py` re-fetches the URL on this
machine and looks for that text. A quote that is a summary of what the page said
is refused as `NOT_AN_OBSERVATION`, and two of the nine cards already on disk were
refused for exactly that.

**Empty is an answer.** If an axis has no free daily or weekly source, say so and
name the most frequent one that does exist. A refusal recorded is worth more than
a number invented; the register already carries `AGENT_REFUSED` as a first-class
verdict.

**Save the file as** `openclaw_queue/cards/2026-09-13_cards.jsonl` in
`C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED`.

---

## The wire that is missing, stated so nobody rebuilds the wrong half

Two halves of one machine exist and are not connected:

- `experiments/browser_scout/goal_impact_collector.py` **searches** and issues no
  cards. Measured over the last 7 days: 42 runs, `pages_read` 0 in all 42, its own
  note reading *"the eye failed, not the world. Headless Chromium is blocked by
  the search engines (measured: headful 3 pages, headless 0, same query)."*
- `scripts/openclaw_axis_worker.py` **fetches a number from a known address** and
  does not search. Plain `requests`, no browser, a named refusal when the path
  does not lead to a number. Nothing runs it; its output files were last touched
  on 21 August.

**The missing wire is SEARCH → CARD.** Until it exists, the step below — a human
pasting these blocks into the agent's window — IS the wire. That is why this file
exists rather than a script.

---

## Two axes checked before asking for anything

**GOAL_PROGRESS_REVIEW — measured internally. Dropped from the list.** Its only
source is `memory/goal_score_history.json`, extract `-1.scores.GOAL_PROGRESS_REVIEW`
— the system reading back its own last score. No external sensor is missing,
because none was ever intended. Worth saying once, though: an axis whose only
input is its own previous output is a mirror, not a sensor, and it will agree with
itself forever.

**LONG_TERM_FUTURE_REVIEW — NOT internal. It stays on the list.** Three sources,
all `snapshots/master/global_indicators_latest.json`, all `nuclear.*` from
SIPRI/FAS: warheads total, deployed, on alert. That is real external data and it
is **annual**, stamped into the daily tier every night, where it sits among the 49
series that have never once changed. It does not need a second witness; it needs
the cadence field. No block below.

---

# GROUP A — four axes that look covered and are not

Each of these already has a sensor. The task is a **replacement**, because what is
there now measures something else, something dead, or nothing.

---

## A1. MATERIALS_WASTE_REVIEW — its sensor is CLIMATE's

Verified in `config/composer_specs.json`: its anchor is `gi_co2_materials`,
extract `co2.co2_ppm`, and its daily measurement is
`https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_trend_gl.csv`. Both are
**byte-for-byte the same source CLIMATE_GLOBAL_RISK_REVIEW uses**. Atmospheric CO2
is not a measure of materials and waste; the axis is reading its neighbour's
thermometer.

> **Task.** Find a free public JSON or CSV address, no API key, giving ONE number
> at daily or weekly cadence for **material flow or waste**: municipal waste
> generated, recycling rate, plastic production, e-waste, raw material extraction,
> a commodity-scrap price index — anything that is genuinely about materials, not
> about carbon.
> Use `"axis":"MATERIALS_WASTE_REVIEW"` and choose a `key` that names the
> quantity, e.g. `msw_generated_tonnes_daily`.
> If nothing daily or weekly exists, say so and name the most frequent that does.

---

## A2. ENERGY_REVIEW and FOOD_REVIEW — one storm feed, two axes

Verified: both carry
`https://eonet.gsfc.nasa.gov/api/v3/events?status=all&days=7&category=severeStorms`
(`promoted_69607` in ENERGY, `promoted_40653` in FOOD). Identical URL, identical
category. Two axes are reading one number and calling it two observations.

**Decide which keeps it.** The recommendation, and the reason: **FOOD keeps it.**
FOOD's own daily source is Open-Meteo evapotranspiration — a weather quantity, so
severe storms sit in the same causal family and add little. ENERGY's daily source
is Open-Meteo shortwave radiation, which is supply-side; ENERGY has nothing at all
about demand, price or grid. So ENERGY is the axis that loses more by keeping a
borrowed storm counter than by replacing it.

> **Task.** Find a free public JSON or CSV address, no API key, giving ONE number
> at daily or weekly cadence for **energy**: electricity price, grid load,
> generation mix share, gas or oil spot price, renewable output.
> Use `"axis":"ENERGY_REVIEW"` and a `key` naming the quantity, e.g.
> `grid_load_mw_daily` or `electricity_price_eur_mwh`.

---

## A3. SOCIAL_RELATIONS_REVIEW — two addresses that return definitions

Verified: `promoted_40232` and `promoted_61568` both point at
`https://ghoapi.azureedge.net/api/Indicator?$filter=contains(IndicatorCode,...)`
with extract `value`. That endpoint returns WHO's **catalogue of indicators** — a
list of names and definitions. There is no measurement in it. Whatever number is
being extracted is a property of the catalogue, not of the world.

> **Task.** Find a free public JSON or CSV address, no API key, giving ONE number
> at daily or weekly cadence for **social relations**: conflict events, protest
> counts, displacement flows, homicide or violence counts, a loneliness or trust
> survey release.
> Use `"axis":"SOCIAL_RELATIONS_REVIEW"` and a `key` naming the quantity, e.g.
> `armed_conflict_events_7d`.
> Note: the WHO GHO API *does* serve measurements, but from
> `/api/<IndicatorCode>`, not from `/api/Indicator`. If you use GHO, take a real
> indicator endpoint and quote the row.

---

## A4. GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL — a pinned year and a finished pandemic

Verified two defects. `promoted_78396` is
`https://api.nobelprize.org/2.1/nobelPrizes?category=peace&year=...` with extract
`meta.count` — a **hard-coded year**, so it returns the same integer forever.
`promoted_84957` is the **OWID covid-19 raw GitHub file**, registered in the
`measurement_daily` slot; that dataset stopped being a daily instrument of human
rights, if it ever was one.

> **Task.** Find a free public JSON or CSV address, no API key, giving ONE number
> at daily or weekly cadence for **rights at the human level**: press-freedom
> incidents, journalists detained, internet shutdowns, political prisoners,
> asylum decisions.
> Use `"axis":"GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL"` and a `key` naming the quantity,
> e.g. `internet_shutdowns_7d`.

---

# GROUP B — a second witness for the four load-bearing axes

**Why the key matters more than the number here.** `_peer_for(axis, key)` in
`scripts/openclaw_axis_worker.py` finds a peer by matching **(axis, key)
exactly**. A second sensor filed under a different name is never compared with the
first, the `contradiction` branch of `core/source_lifecycle.py` never executes,
and `DEMOTE_AFTER=3` stays the dead gate it has been: **435 events in
`memory/source_lifecycle_ledger.jsonl` — 109 clean, 326 refusals, zero
contradictions, ever.**

This has already gone wrong. Three names exist today for "how many earthquakes":

| where | key |
|---|---|
| `config/openclaw_sources.json` | `quakes_m45_last_24h` |
| the cards already on disk | `usgs_m5plus_7d_count` |
| `config/composer_specs.json` | extract `metadata.count` on a third feed |

None of them will ever meet. **Use the key given in each block below, exactly.**

---

## B1. CLIMATE_GLOBAL_RISK_REVIEW — second witness on atmospheric CO2

Incumbent: NOAA, `https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_trend_gl.csv`,
daily global CO2. Note that this same file is registered in
`probed_and_failed` of `VERIFIED_SOURCE_PACK.json` with
`ROBOTS_DISALLOWED via the fetch tool` — so a second witness matters more here
than anywhere else: the incumbent cannot be re-verified from this machine.

> **Task.** A free public JSON or CSV address, no API key, giving atmospheric CO2
> concentration, daily or weekly, from an organisation that is **not NOAA**.
> **Use exactly** `"key":"co2_ppm_mauna_loa"` — the key the accepted cards on disk
> already use. `"unit":"ppm"`.

---

## B2. DEEP_TIME_RISKS_REVIEW — second witness on earthquake count

Incumbent: USGS,
`https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`,
extract `metadata.count`.

> **Task.** A free public JSON or CSV address, no API key, giving a count of
> earthquakes above a magnitude threshold in a fixed recent window, from an
> organisation that is **not USGS** — EMSC, GFZ, IRIS, JMA.
> **Use exactly** `"key":"quakes_m45_last_24h"` — the key already registered in
> `config/openclaw_sources.json`, and match its window and threshold: **M ≥ 4.5,
> last 24 hours**. `"unit":"events_24h"`.
> A different window makes the two numbers disagree for a reason that is not a
> disagreement, and the pair would be recorded as a contradiction that is really a
> mismatch of definitions.

---

## B3. WATER_REVIEW — second witness on river discharge

Incumbent: USGS,
`https://waterservices.usgs.gov/nwis/dv/?format=rdb&sites=01646500&parameterCd=...`
— a **single gauge on the Potomac**, standing in for the water axis of the planet.

> **Task.** A free public JSON or CSV address, no API key, giving daily river
> discharge or a water-level index, from an organisation that is **not USGS** —
> GloFAS/Copernicus, a national hydrological service, WMO.
> **No key exists for this quantity yet.** Use
> `"key":"river_discharge_m3s_daily"` and say in your answer that it is new, so a
> matching row can be added to `config/openclaw_sources.json` — without that row
> the two sensors will never be compared.

---

## B4. PLANETARY_POTENTIAL_REVIEW — second witness, and a warning first

Its only daily source is
`https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson`,
extract `metadata.count` — **the same USGS earthquake count DEEP_TIME_RISKS uses**,
on a neighbouring feed. So this axis is in Group A as much as Group B: its daily
sensor is borrowed, and a second earthquake witness would only deepen the
borrowing.

> **Task, and it is a replacement, not a second witness.** A free public JSON or
> CSV address, no API key, daily or weekly, for **planetary potential**: habitable
> land area, soil-carbon or NDVI index, freshwater availability per capita,
> protected-area coverage.
> Use `"axis":"PLANETARY_POTENTIAL_REVIEW"` and a `key` naming the quantity, e.g.
> `ndvi_global_index_weekly`.

---

# GROUP C — the six blind axes

No block here asks for a second witness. These have no daily or weekly sensor of
their own at all; each has one annual number read out of
`snapshots/master/global_indicators_latest.json`, and two of them read **the same**
annual number.

---

## C1. COGNITION_LEARNING_REVIEW

Only source: World Bank `world_bank.literacy_rate_adult_pct`, annual — **and
EDUCATION_CULTURE_REVIEW reads the same field**. One annual number is serving as
the entire sensory apparatus of two axes.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about
> cognition or learning: online-course enrolments, Wikipedia edits or pageviews,
> library or research-paper downloads, a standardised-test release.
> `"axis":"COGNITION_LEARNING_REVIEW"`, key e.g. `wikipedia_edits_daily`.

## C2. COSMIC_RESOURCES_REVIEW

Only source: `exoplanets.confirmed_exoplanets`, and it is filed as
`indirect_proxy` — the axis has no anchor and no daily measurement at all.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about
> cosmic resources: asteroid discoveries, near-Earth objects catalogued, launch
> mass to orbit, space-mining claims, mission counts.
> `"axis":"COSMIC_RESOURCES_REVIEW"`, key e.g. `neo_discovered_7d`.

## C3. EDUCATION_CULTURE_REVIEW

Only source: `world_bank.literacy_rate_adult_pct` — the same field as C1, and
likewise `indirect_proxy` only.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about
> education or culture: school-enrolment releases, cultural-institution
> attendance, book or music releases, UNESCO series.
> `"axis":"EDUCATION_CULTURE_REVIEW"`, key e.g. `unesco_enrolment_index`.

## C4. GOVERNANCE_INSTITUTIONS_REVIEW

Four sources, all annual: one is CORTEX's own `output/wellbeing_globe.json`, the
other three are World Bank WGI `governance.ge_est`, `rl_est`, `cc_est` — all three
among the 49 series that have never changed since they entered the daily tier.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about
> institutions: legislative activity, court filings, corruption prosecutions,
> election events, government-effectiveness incidents.
> `"axis":"GOVERNANCE_INSTITUTIONS_REVIEW"`, key e.g. `elections_held_30d`.

## C5. INEQUALITY_POVERTY_REVIEW

Two sources, both World Bank annual: `world_bank.poverty_190_pct` and
`world_bank.gini_mean`. No daily anything.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about
> inequality or poverty: food-bank demand, unemployment claims, remittance flows,
> a real-wage or food-price index.
> `"axis":"INEQUALITY_POVERTY_REVIEW"`, key e.g. `food_price_index_weekly`.

## C6. TECHNOLOGY_AI_REVIEW

Two sources: `ai_activity.arxiv_ai_papers_total` and
`ai_activity.github_ai_repos_total`. Both **do move** — two of the only six series
in the daily tier that have ever changed — but both are counts of publishing
activity, and both are read from the same snapshot file rather than fetched.

> **Task.** Free public JSON or CSV, no key, ONE number, daily or weekly, about AI
> as a force in the world rather than as a literature: model releases, compute
> price, incidents reported, adoption or traffic.
> `"axis":"TECHNOLOGY_AI_REVIEW"`, key e.g. `ai_incidents_reported_30d`.

---

## After the cards come back

```
venv\Scripts\python.exe core\card_intake.py --dry     # verdicts only, writes nothing
venv\Scripts\python.exe core\card_intake.py           # judge and record
```

Each card is re-fetched and the quote checked against the live page. Accepted
rows go to `memory/verified_observations.jsonl`; everything else is named in
`memory/card_refusals.jsonl` with its verdict. `FETCH_FAILED` is written nowhere
and retried — never accepted on faith, never counted against the agent.
