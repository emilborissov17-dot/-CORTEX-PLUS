# D1-W pre-registration — DRAFT

Status: DRAFT, 1 October 2026. Not sealed, not signed, not published. It is under review.
No fit, forecast or score exists, and none is computed by this document.
The machine-readable twin is `experiments/track_w/prereg_w.json`.

1. **Target.** The target is UCDP GED state-based violence (`type_of_violence = 1`), measured as best-estimate fatalities and summed per country-month.

2. **Frozen country list.** The list contains every country with at least 40 months, since 1989, that each have at least 1 state-based fatality in GED 26.1.
   - The list is computed by code: `experiments/track_w/build_prereg_inputs.py`.
   - Input: `data/external/ucdp/ged261-csv.zip`, sha256 `8c941d84954e555ee2e54f40fa04d9203bf1e2f962203d0a9930966c4947c667`.
   - The month is taken from `date_start`. A month counts when the summed `best` for that month is at least 1.
   - Count: **56 countries**. D0 also found 56.
   - The list and each country's month count are in `prereg_w.json` under `frozen_country_list`.
   - The list's sha256 is `59f8a77b18dd16c29b51b35d04be1736169b35367a321fa6bab55c06b254d0d6`, taken over canonical JSON (`sort_keys`, no whitespace, UTF-8).

3. **Origins.** Origins fall every 3 months from 2015-01 to 2024-12, which gives 40 origins from 2015-01 to 2024-10. Horizons run from 1 to 12 months.

4. **Arms.**
   - (a) **No-change:** the last observed month is carried forward. Its predictive interval comes from that country's own past no-change errors, observed strictly before the origin.
   - (b) **ETS.**
   - (c) **VIEWS:** only vintages whose documented release date is on or before the origin.
   - (d) **Learner L v1:** a regularised negative-binomial GLM on lagged fatalities with country intercepts. It is refit at each origin on the data available at that origin.

   No other learner is allowed. A combiner or a program search is explicitly OUT of this pre-registration.

5. **Metrics.** CRPS per horizon, and coverage of the 80% interval.

6. **PASS rule.** L v1 passes when both of these hold:
   - its CRPS is at or below the no-change CRPS at horizons 1–3 on at least 60% of the frozen countries;
   - its 80% interval coverage is within ±10 points.

   VIEWS is reported as secondary.

   **KILL rules.**
   - Without a machine-verified embargo, no W number is ever published.
   - If L v1 does not beat no-change on the frozen list, the L v1 class is recorded dead. That is one honest loss, with no retune-and-extend.

7. **Three leak guards.** Each one is enforced by code, with a test, before any number exists.
   - **(G1) Version-date join:** at origin t, only a GED version released on or before t may be read.
   - **(G2) VIEWS vintage filter:** vintages are filtered by release date.
   - **(G3) One assembler:** any row with source_date > origin aborts the run.

   For G1 and G2, `experiments/track_w/release_dates.json` holds one row per GED version and per VIEWS vintage. Each row gives a release date and the file or URL that proves it. A version without a provable date is "UNPROVEN" and is excluded. No date is guessed.
   - **GED:** all 144 versions are UNPROVEN (15 annual, 2.0 to 26.1, and 129 Candidate). The UCDP download pages state no release dates, and HTTP Last-Modified is not used.
   - **VIEWS:** 60 of 91 vintages have a release date stated in the publisher's wiki table. The wiki is snapshotted as `data/external/views/wiki_Available-datasets.md`, sha256 `7b7568695487cc32a3e503432eb0994bc674044fc85af6c51eaff32ca1cf4789`, and the stated dates run from 2022-07-18 to 2026-09-25.
   - **VIEWS UNPROVEN:** 31 vintages. They are either absent from that table or stated to the month only.

8. **Holdout.** Origins from 2024-01 on (2024-01, 2024-04, 2024-07, 2024-10) are write-once. They are scored once, after the architecture is frozen, and published whatever they say.

9. **Surrogate null.** The same pipeline is run on each country's series with months permuted within country. L v1 must beat its own null.

10. **Attached rules, frozen now.**
    - **Point 6:** L is retrained on the error ledger in three ways on hold-out origins: recency-weighted sampling, shuffled-error sampling, and no retrain. This is demonstrated only if recency-weighted reduces CRPS at horizons 3–12 and shuffled does not.
    - **Point 11:** coverage outside the band at 3 consecutive origins triggers an automatic, logged switch of model class. This is demonstrated only if all three hold: it fires on real data, coverage returns to the band, and it does not fire on shuffled-error controls.

11. **Publication.** Every result is published, win or lose.
