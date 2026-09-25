# GITHUB_TOKEN replaced — 2026-09-25

- **What:** `GITHUB_TOKEN` in `.env` was replaced by Emil on 2026-09-25 with a new
  fine-grained token, `cortex-civilization-watcher-2`, Contents read/write on
  `emilborissov17-dot/cortex-civilization-watch`.
- **Why:** the old token (`cortex-civilization-watcher`) had **expired** — not a leak.
  It published at 09:27 local on 2026-09-25 and answered `401 Bad credentials` at
  ~19:03 local the same day, which stopped the F-001 publish (recorded `deferred` in
  `experiments/institution/publish_ledger.jsonl`). A search the same evening found the
  token's value in no commit pushed since 2026-09-24, no tracked file and nothing under
  `memory/`.
- **New expiry:** 2027-09-25 (GitHub's header reads `2027-09-24 21:00:00 UTC`).
- **Verified:** `GET /repos/emilborissov17-dot/cortex-civilization-watch` → 200 with the
  new token; F-001 then published (commits `01e30064`, `a7f8fc43`).
- **Before 2027-09-24:** rotate again, or every `github_publish` — nightly and
  Institution 0 — fails with 401.

The token value is not recorded anywhere in this report.
