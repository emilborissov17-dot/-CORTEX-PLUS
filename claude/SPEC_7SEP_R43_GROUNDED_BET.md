# SPEC — R43 GROUNDED BET
### 7 September 2026. A SIGNAL must be a quote from a document that exists.

## 0. Why

`FIRST_BET_MARKETS_2026-09-07` sealed three bets whose every cited fact was invented.
The model was shown prices only, has no news access, and produced perfectly-shaped
fabrications: a Jackson Hole transcript dated thirteen days *after* the session it
claimed to explain, corporate earnings offered as the driver for **gold** and the
**dollar index**, and Q1 GDP "released 7 Sep" when BEA publishes Q1 in spring. Twenty-two
of twenty-four passed the gate.

That was predictable and was predicted: the check required "a date or a named source",
and a test asserted that *a fabricated but well-shaped signal still passes*. **A shape
check cannot do the job the rationale was added for.** A rationale exists so a wrong bet
can be diagnosed against a named event; an invented event is not diagnosable, only
decorated.

**R43 removes the possibility rather than the temptation.** The model no longer supplies
facts. It is handed retrieved snippets, and its SIGNAL must be an **exact substring of
one of them**. A bet it cannot ground is refused, and the asset gets no bet at all.

---

## 1. Read-only diagnosis — done 2026-09-07, before any code

| question | answer |
|---|---|
| Is there already a Tavily helper? | **No.** Zero `.py` files in the repo mention `tavily`. |
| Where is the key? | **`.env`, `TAVILY_API_KEY=`**, populated, 58 chars, `tvly…` prefix. |
| Does `.env` reach `os.environ`? | **No.** Nothing calls `load_dotenv`. `TAVILY_API_KEY in os.environ` is `False`. |
| How do other modules read gated keys? | `core.source_status.credential_for(key)` → looks up `config/dead_sources.json` for an `env_key`, checks `os.environ`, then falls back to reading `.env` line by line. |
| Is Tavily registered there? | **No.** `get_status("tavily")` is `None`, so `credential_for` cannot reach the key today. |
| Existing source taxonomy | `config/reporter_independence.json` declares exactly four classes — `self_reported`, `independent`, `adversarial`, `unknown`. **Do not invent a fifth** (CLAUDE.md). |

**Consequence for the build:** Tavily must be registered as a `NEEDS_AUTH` source in
`config/dead_sources.json` with `env_key: TAVILY_API_KEY`, so the existing credential
path works and an absent key produces the existing named skip rather than a new one.

---

## 2. `core/market_news.py`

**Whitelist.** Only these hosts may supply a SIGNAL. Each is mapped to a
`reporter_independence` class from the four that already exist — no fifth class.

```
reuters.com  apnews.com  bloomberg.com  wsj.com  ft.com  cnbc.com
bls.gov  bea.gov  federalreserve.gov  treasury.gov  eia.gov  sec.gov
```

A result from any other host is **discarded before the model sees it**, and the
discarded host is logged. A whitelist that silently drops is a whitelist nobody can
audit.

**Freshness.** A snippet older than **48 hours** at fetch time is discarded. Published
date comes from the API; **a result with no date is discarded, never treated as fresh** —
unknown age is not recent age.

**Refuse loud, in every failure mode, and never fall back:**

| condition | behaviour |
|---|---|
| `TAVILY_API_KEY` absent | `NewsUnavailable("tavily: no TAVILY_API_KEY — discovery REFUSED by name, not attempted in a browser")` |
| HTTP error / timeout | `NewsUnavailable` naming status and host. **No retry into a browser.** |
| zero results after whitelist+freshness | `NewsUnavailable` naming how many were dropped and why |

**Never**: a cached snippet, a synthesised headline, a widened window, a relaxed
whitelist. Every one of those turns "no evidence" into "some evidence", which is the
failure this spec exists to stop.

**Output.** `fetch_news(asset) -> list[Snippet]`, each
`{title, url, host, published_utc, snippet, retrieved_utc}`.

---

## 3. The grounded bet flow

1. **Fetch first.** For each of SPY / GLD / UUP, retrieve snippets. **An asset with zero
   usable snippets gets NO BET** — recorded as `REFUSED_NO_EVIDENCE`, with the reason.
   There is no fallback to a price-only rationale.
2. **The prompt carries the snippets, numbered**, and says the SIGNAL must be copied
   verbatim from one of them.
3. **The gate adds one rule to the existing four:**
   **`SIGNAL` must be an exact substring of at least one retrieved snippet** (after
   whitespace normalisation and case-folding). Not "similar to". Not "supported by".
   A substring, or `REFUSED`.
4. Everything already in `tools/market_bet.py` still applies: direction must be UP/DOWN,
   rationale non-empty, DRIVER in `MACRO|GEOPOL|FLOW|SECTOR`, deadline equal to the
   graded session.
5. **A signal dated after the graded session is REFUSED** — the Jackson Hole case,
   mechanically checkable and previously admitted.
6. **If all N completions agree, record `NO_DISAGREEMENT`** rather than dressing a
   constant as a majority. All 24 said UP last time.
7. The matched snippet's **url and published date are sealed with the bet**, so grading
   can open the document.

---

## 4. Tests

**`core/market_news.py`**
1. an off-whitelist host is dropped, and the drop is logged with the host named;
2. a snippet older than 48 h is dropped;
3. a snippet with **no** published date is dropped, not treated as fresh;
4. a missing `TAVILY_API_KEY` raises `NewsUnavailable` naming the key — no browser,
   no silent empty list;
5. an HTTP error raises `NewsUnavailable` naming the status;
6. zero results after filtering raises `NewsUnavailable` and says how many were dropped
   and why;
7. **no fallback exists**: the module source contains no cache read, no synthesised
   headline, no second window.

**grounded gate**
8. a SIGNAL that is an exact substring of a snippet is ADMITTED;
9. a SIGNAL that is a *paraphrase* of a snippet is REFUSED;
10. a SIGNAL that is plausible, well-formed and appears in **no** snippet is REFUSED —
    the exact failure of 2026-09-07, re-run against the new gate;
11. a SIGNAL dated after the graded session is REFUSED;
12. an asset with zero snippets yields `REFUSED_NO_EVIDENCE` and **no sealed bet**;
13. when all N agree, the record says `NO_DISAGREEMENT`;
14. the sealed bet carries the matched snippet's url and published date;
15. **the whole 2026-09-07 candidate set, replayed through the grounded gate, is
    refused** — all 22 previously-admitted fabrications.

**Prediction-only**
16. neither module contains an order, position, broker or api-key path (§VI).

---

## 5. Commit plan — one piece each

1. this spec;
2. Tavily registered in `config/dead_sources.json` as `NEEDS_AUTH` + the whitelist config;
3. `core/market_news.py` + tests 1–7;
4. the grounded gate in `tools/market_bet.py` + tests 8–16;
5. the run, only after a dry run is pasted.

**Nothing runs live until every piece above is committed and green.**

## 6. Pre-registered, before the grounded run

The R43 gate will **refuse most or all** of what a 3B produces. It has no incentive to
copy a snippet exactly when it has been rewarded all its life for paraphrasing, and the
whitelist plus 48 h window may return nothing at all on a US market holiday.

**P(at least one asset gets a grounded, sealed bet on the first attempt) = 0.45.**
**P(all three) = 0.15.** A run that refuses all three is a *success* for the gate and a
finding about the model — and it must be reported as such, not tuned away.
