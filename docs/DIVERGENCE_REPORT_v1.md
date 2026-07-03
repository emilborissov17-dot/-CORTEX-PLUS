# Divergence Report v1: Where Official Data Overstates Governance Reality

**Status:** Draft for review. Mechanism validated on a defined slice of evidence; explicitly not a complete map. See Section 4 for what this report does and does not support.

**Date:** 2026-07-03
**Data vintage:** World Bank wellbeing batch (217 countries, 2026-06-28) · V-Dem Core v16 (2018+ observations) · live web-signal pilot (7 countries, 2026-07-02)
**Reproduction:** every number in this report is read from `output/divergence_latest.json` and `output/phase3_pilot/*.json`, both committed to this repository. See Section 5.

---

## Executive Summary

Countries are routinely assessed by how they look on quantitative development metrics — infrastructure access, poverty rates, health and education coverage. This report tests a narrower, harder question: how often does that quantitative picture diverge from a country's *observed political practice* — freedom of expression, corruption, rule of law — as independently coded by domain experts (V-Dem)?

**Method.** For 175 countries with complete data in both sources, we compute `divergence = percentile(quantitative wellbeing) − percentile(V-Dem political practice)`. A country is flagged **FACADE** when divergence ≥ 0.20 — it ranks meaningfully better on material metrics than on how it is actually governed. The threshold and the formula were fixed before the full run; a 4-country pre-registered test (Bulgaria, Hungary, Russia expected FACADE; Germany expected not) passed before any broader claim was made.

**Findings.** 33 of 175 countries (18.9%) are flagged FACADE. The top of the list — China (divergence 0.534), Serbia (0.412), Russia (0.397), Turkiye (0.383), Bosnia and Herzegovina (0.372) — is a coherent match to known hybrid or authoritarian regimes with strong economic optics and weak observed governance. The opposite tail — Gambia, Vanuatu, Niger, Timor-Leste, Benin (divergence −0.40 to −0.48) — is poor-but-functioning democracies whose material conditions understate how well they are actually governed. No absurd outliers appear in either tail.

**Independent corroboration.** A separate pilot cross-checked the top of the FACADE list against live web search + LLM-classified media coverage, independent of both input datasets. China, Serbia, Russia, and Turkiye were strongly corroborated (12–20 informative sources each, 76–95% agreement with the FACADE classification, confidence HIGH/MEDIUM). The fifth case, Bosnia and Herzegovina, and both clean-control checks (Estonia, Denmark) returned too little usable data to confirm or deny — a pipeline defect, not a finding (Section 4.2).

**Honest limits.** This mechanism catches *gross* facades — large, economically visible divergence — not subtle or partial ones. The live-signal layer is not yet validated for borderline or control cases. The underlying wellbeing-profile confidence system reports 0 of 217 countries at HIGH confidence, by structural design (Section 4.3), not because this specific result is weak. All code, data, and thresholds are in this repository and reproducible from a clean checkout.

---

## 1. Thesis

Aggregate wellbeing scores built from official quantitative data (GDP-adjusted poverty measures, infrastructure access, health/education coverage) tell you how a population is *materially provisioned*. They do not tell you how a population is *governed*. A state can fund infrastructure and services while suppressing the press, capturing courts, and running a functionally closed political system — the two facts are produced by different mechanisms and are not guaranteed to move together.

The working hypothesis: **official data systematically overstates the realized quality of governance in a specific class of countries** — those with enough centralized capacity and resource base to deliver visible material outcomes, but without the constraints (free press, independent judiciary, electoral accountability) that would force governance quality to catch up with material quality. This report does not claim official data is wrong or fabricated. It claims the two dimensions are conflated when a single "development" or "wellbeing" number is read as a proxy for how well a country is governed, and it produces a specific, falsifiable list of where that conflation is largest.

---

## 2. Method

### 2.1 Data sources

| Side | Source | Coverage | What it measures |
|---|---|---|---|
| Quantitative | World Bank wellbeing batch (`output/wellbeing_all_countries.json`, 2026-06-28) | 217 countries | `deprivation`, `strain`, `flourishing` — composite indices built from WB development indicators |
| Qualitative | V-Dem Core v16 (`data/V-Dem-CY-Core-v16.csv`), most recent year ≥ 2018 per country | 179 countries with all three variables present | `v2x_freexp_altinf` (freedom of expression/alt. information), `v2x_corr` (political corruption, inverted below), `v2x_rule` (rule of law) — expert-coded observed practice, not law-on-paper |

Both are restricted to their intersection: 175 countries with usable data on both sides (42 World Bank countries excluded for missing V-Dem coverage).

### 2.2 Formula

```
quantitative_goodness = mean(1 − deprivation, 1 − strain, flourishing)
qualitative_goodness  = mean(percentile(freexp), percentile(1 − corruption), percentile(rule_of_law))

quantitative_percentile = percentile_rank(quantitative_goodness) across the 175-country universe
qualitative_percentile  = percentile_rank(qualitative_goodness)  across the same universe

divergence = quantitative_percentile − qualitative_percentile
FACADE     = divergence ≥ 0.20   [threshold fixed before the full run, see 2.3]
```

Both sides are percentile-ranked, not raw-scored, so the measure is relative position within the same 175-country universe on each dimension — a country can only be flagged for ranking *meaningfully higher* on material outcomes than on governance practice, not for having a poor absolute score on either axis alone.

### 2.3 Threshold

`FACADE_THRESHOLD = 0.20` is a provisional, pre-registered calibration choice — not fit to the data after seeing results. It was carried over unchanged from an earlier rejected variant of this same pilot (Section 2.5) for continuity, and has not been re-tuned to produce a particular list size or composition.

### 2.4 Pre-registered test

Before the full 175-country run, four countries were named as predictions: Bulgaria, Hungary, and Russia were expected to be FACADE (strong material optics, weak observed governance); Germany was expected not to be. All four predictions held. This is a single pass/fail check on a small, deliberately chosen sample — it demonstrates the mechanism behaves as intended in known cases, not that the full list is correct.

### 2.5 Rejected variants — kept for honesty

Two earlier formulations of this same question were tried and dropped before arriving at the method above. Both are preserved in the pilot script's docstring rather than deleted, so the reasoning is auditable rather than presented after the fact as the only path considered.

1. **WGI (World Governance Indicators) vs. V-Dem.** Rejected because WGI is itself a perception-survey aggregate that already "sees" overt autocracy — Russia scored *low* divergence under this formulation despite being an unambiguous case, because WGI already rates it poorly. The two sides were not independent enough to isolate a facade-specific signal.
2. **V-Dem de-jure vs. V-Dem de-facto** (`v2clacfree`/`v2mecenefm`, hypothesized law-on-paper, against the same `freexp`/`corr`/`rule` practice variables). Rejected because the direction was not predictable — Germany, the control, showed the *largest* divergence of the four pilot countries under this formulation. V-Dem codes most of its variables from observed expert judgment either way; there is no clean law-vs-practice split available inside V-Dem alone.

### 2.6 Known dilution — flagged, not hidden

The quantitative composite's `flourishing` component already includes one V-Dem-derived indicator (`v2x_freexp_altinf`, folded into `CULTURE_MEDIA_REVIEW` in the production wellbeing pipeline) — 1 of roughly 16 axes inside 1 of 3 composite dimensions. This is a minor same-construct overlap between the two sides of the divergence formula, not the dominant circularity that broke variant 1 above, but it is real and should be corrected before this becomes a production metric rather than a pilot.

---

## 3. Findings

### 3.1 Distribution

| | Count | % of universe |
|---|---|---|
| Total World Bank wellbeing countries | 217 | — |
| Excluded (no V-Dem coverage) | 42 | — |
| Universe (both sources present) | 175 | 100% |
| **FACADE** (divergence ≥ 0.20) | **33** | **18.9%** |
| Not flagged | 142 | 81.1% |

### 3.2 Full FACADE list (33 countries, sorted by divergence, descending)

| ISO | Country | Quant. pct. | Qual. pct. | Divergence |
|---|---|---|---|---|
| CN | China | 0.782 | 0.247 | 0.534 |
| RS | Serbia | 0.678 | 0.266 | 0.412 |
| RU | Russian Federation | 0.534 | 0.138 | 0.397 |
| TR | Turkiye | 0.546 | 0.163 | 0.383 |
| BA | Bosnia and Herzegovina | 0.759 | 0.387 | 0.372 |
| VE | Venezuela, RB | 0.397 | 0.038 | 0.358 |
| BY | Belarus | 0.592 | 0.239 | 0.352 |
| SV | El Salvador | 0.557 | 0.211 | 0.347 |
| TJ | Tajikistan | 0.385 | 0.038 | 0.347 |
| AZ | Azerbaijan | 0.391 | 0.057 | 0.333 |
| MK | North Macedonia | 0.684 | 0.351 | 0.333 |
| UZ | Uzbekistan | 0.477 | 0.159 | 0.318 |
| AE | United Arab Emirates | 0.793 | 0.483 | 0.310 |
| HK | Hong Kong SAR, China | 0.874 | 0.565 | 0.308 |
| TM | Turkmenistan | 0.339 | 0.038 | 0.301 |
| HU | Hungary | 0.747 | 0.448 | 0.299 |
| NI | Nicaragua | 0.305 | 0.006 | 0.299 |
| QA | Qatar | 0.701 | 0.402 | 0.299 |
| BG | Bulgaria | 0.770 | 0.475 | 0.295 |
| KZ | Kazakhstan | 0.529 | 0.236 | 0.293 |
| PY | Paraguay | 0.661 | 0.377 | 0.284 |
| AL | Albania | 0.741 | 0.460 | 0.282 |
| KH | Cambodia | 0.345 | 0.069 | 0.276 |
| VN | Viet Nam | 0.575 | 0.310 | 0.264 |
| CU | Cuba | 0.454 | 0.192 | 0.262 |
| BH | Bahrain | 0.563 | 0.303 | 0.261 |
| SA | Saudi Arabia | 0.638 | 0.377 | 0.261 |
| KG | Kyrgyz Republic | 0.517 | 0.270 | 0.247 |
| TH | Thailand | 0.644 | 0.398 | 0.245 |
| UA | Ukraine | 0.580 | 0.337 | 0.243 |
| IR | Iran, Islamic Rep. | 0.414 | 0.197 | 0.216 |
| ID | Indonesia | 0.540 | 0.333 | 0.207 |
| MM | Myanmar | 0.259 | 0.056 | 0.203 |

Reading this list: high-divergence entries split into two recognizable groups — (a) resource-rich or strategically positioned authoritarian states able to fund visible material outcomes without electoral or press constraints (China, the Gulf states, Central Asian republics), and (b) states with formally democratic institutions but well-documented state capture or media pressure (Serbia, Hungary, Bulgaria, North Macedonia, Bosnia and Herzegovina). Ukraine and Myanmar sit at the low end of the list, both plausibly reflecting the method's known blind spots (active conflict distorting either side of the composite) rather than a "facade" in the intended sense — flagged here rather than quietly dropped.

### 3.3 The opposite tail — most internally consistent countries

| ISO | Country | Quant. pct. | Qual. pct. | Divergence |
|---|---|---|---|---|
| GM | Gambia, The | 0.224 | 0.703 | −0.479 |
| VU | Vanuatu | 0.241 | 0.716 | −0.475 |
| NE | Niger | 0.046 | 0.515 | −0.469 |
| TL | Timor-Leste | 0.236 | 0.701 | −0.466 |
| BJ | Benin | 0.178 | 0.634 | −0.456 |
| NA | Namibia | 0.316 | 0.747 | −0.431 |
| ZM | Zambia | 0.161 | 0.582 | −0.421 |
| LS | Lesotho | 0.144 | 0.563 | −0.420 |
| SL | Sierra Leone | 0.138 | 0.542 | −0.404 |
| TT | Trinidad and Tobago | 0.425 | 0.818 | −0.393 |

These countries rank *worse* materially than they do on governance practice: poor, but functioning democratically, with a freer press and stronger rule of law than their poverty level alone would suggest. No entry in this tail is an implausible outlier — it is a recognizable list of low-income but institutionally functional states, which is the result the mechanism should produce if it is measuring divergence rather than noise.

### 3.4 Independent corroboration — live web signal

A separate pilot (`live_divergence_pilot.py`) tested whether the top of the FACADE list holds up against a source independent of both World Bank and V-Dem data: live web search results, classified by an LLM as confirming, contradicting, or neutral toward the country's V-Dem-implied rating, restricted to the `media_freedom` construct. Seven countries were tested: the top four FACADE cases, the fifth-ranked FACADE case, and two countries expected to be clean controls.

| ISO | Country | Expected | V-Dem freexp pct. | Informative sources | Agreement with expected direction | Confidence |
|---|---|---|---|---|---|---|
| CN | China | FACADE | 0.051 | 17 of 20 | 89.7% | HIGH |
| RS | Serbia | FACADE | 0.258 | 20 of 20 | 94.8% | HIGH |
| RU | Russian Federation | FACADE | 0.073 | 18 of 19 | 75.9% | HIGH |
| TR | Turkiye | FACADE | 0.157 | 12 of 20 | 88.0% | MEDIUM |
| BA | Bosnia and Herzegovina | FACADE | 0.444 | 1 of 19 | — | LOW (insufficient) |
| EE | Estonia | control (clean) | 0.989 | 0 of 20 | — | LOW (insufficient) |
| DK | Denmark | control (clean) | 1.000 | 1 of 16 | — | LOW (insufficient) |

**Four of five FACADE cases (China, Serbia, Russia, Turkiye) are strongly and independently corroborated.** The fifth (Bosnia and Herzegovina) and both controls (Estonia, Denmark) returned too few informative sources to confirm or refute anything — this is a data-collection failure in the pilot, not a finding about those three countries. Root cause: a parsing defect where the classification step discards some LLM responses that already begin as valid JSON (e.g. a raw response beginning `{"direction":"CONFIRMS",...` was logged as unparseable), compounding with rate-limit exhaustion by the time later countries in a run are processed. This defect was still present in a rerun intended to fix it and is an open item, not resolved by this report. **No claim is made here about whether Bosnia and Herzegovina, Estonia, or Denmark would confirm or contradict the FACADE mechanism** — the honest result is "untested," not "clean" or "confirmed."

---

## 4. Limits — stated plainly

### 4.1 The 33-country list is a lower bound, not a map

A single threshold on two composite percentiles catches large, economically visible divergence. It will miss: countries where governance capture is real but the material composite is *also* mediocre (no divergence to detect even though the underlying problem exists); countries where V-Dem's own expert coding lags a recent political shift; and any form of facade that operates through a channel not captured by `freexp`/`corr`/`rule` (e.g., judicial capture that doesn't show up in the specific rule-of-law variable used here). 33/175 should be read as "at least this many," not "exactly this many."

### 4.2 The live-signal layer has a known western-corpus bias, undocumented in magnitude

Search queries in the pilot were issued primarily in English (with a secondary pass in the country's national language for non-English cases), and the underlying search and LLM classification stack is trained predominantly on English-language, Western-outlet content. Combined with the parsing defect in 3.4, this means the live-signal layer has *only* been shown to work for cases with large, internationally reported divergence (China, Russia) — it has not been validated for subtler cases, and it has not been validated at all for clean controls, where the expected signal is an *absence* of contradicting coverage rather than a presence of confirming coverage. Closing this gap requires local-language source collection, which is scoped but not yet built (see the Phase 3 media-intelligence inventory, `media_intel_worker.py`, currently English-search-only).

### 4.3 0 of 217 countries reach HIGH confidence in the underlying wellbeing profile

This is a separate, more fundamental confidence rating attached to each country's quantitative wellbeing composite (distinct from the per-source confidence rating in Section 3.4's live-signal table). It is 0/217 by structural design, not because this specific divergence result is weak: one required input series (World Bank CO2/fossil-fuel indicators, feeding the CLIMATE axis) has been discontinued at the source and is archived data for all countries, which caps every country's composite at MEDIUM confidence at best. 124 countries reach MEDIUM, 93 remain LOW. This ceiling applies uniformly across the whole wellbeing profile system, including both sides of the divergence calculation in this report — it is a statement about data completeness, not a defect specific to the countries flagged FACADE.

### 4.4 Two variants of this method were tried and rejected (Section 2.5)

Repeated here because it belongs in a limits section as much as a methods section: the choice of WB-vs-V-Dem was not the first idea, and the two rejected alternatives failed for substantive reasons (insufficient independence between sides; unpredictable direction) that could recur in a future refinement of this method if not kept in view.

### 4.5 Next layers

Two further verification layers are scoped for a future revision of this mechanism: a learning loop that revises the divergence threshold and variable weighting against confirmed outcomes over time, and a monetary/resource-integrity check — cross-referencing claimed public investment and resource flows against independent satellite-based verification (nighttime lights, infrastructure build-out, extraction activity) — as a third, non-textual signal alongside the quantitative and qualitative sides used here.

---

## 5. Verifiability

Every number in this report is generated from code and data present in this repository, not transcribed from memory or from an intermediate summary.

**Code:**
- `_divergence_pilot.py` — computes the 175-country divergence universe, the FACADE list, and the pre-registered test. Re-executed on 2026-07-03 to produce `output/divergence_latest.json`; results are identical to the original 2026-07-02 run (33/175 FACADE, same top and bottom 10).
- `live_divergence_pilot.py` — the 7-country live web-signal pilot behind Section 3.4. Outputs one JSON file per country in `output/phase3_pilot/`.

**Data:**
- `output/wellbeing_all_countries.json` — World Bank-derived quantitative composite, 217 countries, generated 2026-06-28.
- `data/V-Dem-CY-Core-v16.csv` — V-Dem Core v16, manually downloaded from v-dem.net (registration required at source; not redistributable in raw form beyond this repository's existing copy).
- `output/divergence_latest.json` — full 175-country result set (all percentiles, all divergence values, facade list, top/bottom 10), generated from the two sources above.
- `output/phase3_pilot/{ISO}_media_freedom.json` — per-country live-signal detail, including every source URL, outlet, classification, and rationale collected during the pilot (raw enough to audit any single classification by hand).

**To reproduce the divergence table from a clean checkout:**
```
python _divergence_pilot.py
```
requires only the two data files listed above; no network access or API keys.

**To reproduce the live-signal pilot:**
```
python live_divergence_pilot.py
```
requires live web search and at least one working LLM backend (Groq/Cerebras/OpenRouter/Gemini/Ollama, tried in that order with cooldown fallback); subject to the parsing defect noted in Section 3.4 until fixed.

This report makes no claim beyond what these two scripts and their outputs directly support. Where a finding is provisional, inconclusive, or contradicted by a defect in the pipeline, that is stated in Section 4 rather than omitted.
