# L1-DAILY STEP 0 — the browser search census
### 6 September 2026. Read-only. The census cannot report what was searched, and that is the finding.

## What was asked, and what exists

The brief asks for last night's browser searches: **queries, CAPTCHA hits, seconds.**

I read all 52 `*_web_intel.json` files written on 5–6 September. Their top-level keys,
across 50 axis files:

```
timestamp  axis  domain  sources_count  rss_count  ddg_count  youtube_count
youtube_items  analysis  raw_items
```

```
queries found ............ 0
CAPTCHA records .......... 0
timing fields ............ 0
```

**None of the three is recorded anywhere.** Not the query text, not a CAPTCHA hit, not
a duration. The pipeline stores *how many* results came back and the results themselves
(`title, link, summary, published, source_type`) — and nothing about the asking.

So the census returns nothing not because last night was quiet, but because **the thing
the brief wants counted is not instrumented**. Reporting "0 CAPTCHAs" as a fact about
the world would be the mistake; the honest statement is that a CAPTCHA last night would
have left no trace.

## What the counts do say — and it is not good

```
axis files ......... 50
sources_count ...... 565
rss_count .......... 379
youtube_count ...... 150
ddg_count ........... 36        <-- across ALL 50 axes
axes with ddg_count == 0 ... 42 of 50
```

**DuckDuckGo returned 36 results in total, and 42 of 50 axes got zero.** RSS (379) and
YouTube (150) carry the night; the search path contributes 6% of sources and is silent
for 84% of axes.

That is consistent with a search path being blocked, rate-limited or CAPTCHA'd — and it
is equally consistent with it being called rarely or failing quietly. **The data cannot
distinguish those**, which is the same gap again: an unrecorded failure and an
unattempted search look identical from here.

## `memory/search_wants.jsonl` — the schema this argues for

One line per **attempt**, written whether it succeeds or fails. The file is named
*wants* because the first field is what the machine wanted to know, which is the part
that survives when the answer does not.

```json
{"ts": "2026-09-06T03:12:44Z",
 "axis": "ENERGY_REVIEW",
 "want": "renewable share of global generation 2026",
 "engine": "ddg",
 "outcome": "OK",
 "n_results": 7,
 "seconds": 2.41,
 "http_status": 200,
 "blocked_reason": null,
 "url_sample": ["https://…", "https://…"]}
```

| field | why it is there |
|---|---|
| `ts`, `axis` | when, and on whose behalf |
| `want` | **the query text.** Nothing today records it, so nothing can tell whether the query was bad or the engine was hostile |
| `engine` | `ddg`, `tavily`, `browser` — the paths must be distinguishable |
| `outcome` | `OK` / `EMPTY` / `CAPTCHA` / `RATE_LIMIT` / `HTTP_ERROR` / `TIMEOUT` / `REFUSED` |
| `n_results` | 0 with `OK` is a real answer; 0 with `CAPTCHA` is not the same event, and today they are indistinguishable |
| `seconds` | a search that takes 30 s and returns nothing is being throttled, not answered |
| `http_status`, `blocked_reason` | the evidence for the outcome, so the label can be checked |
| `url_sample` | what it actually got, for spot-checking relevance |

**`REFUSED` is in the outcome list deliberately.** Per the standing rule, if the Tavily
key is absent the discovery is refused **by name** and not attempted in a browser, and
that refusal has to appear in the same ledger as a success — otherwise "no line" means
both "never asked" and "asked and blocked".

## No CAPTCHA handling is proposed, and none will be added

The brief says not to add any, and nothing here does. `CAPTCHA` is an **outcome label**
so the event becomes countable. A CAPTCHA is a signal that a source does not want to be
read by a machine, and the correct response is to record it and use a different source —
which is exactly what the USGS and GDACS probes that follow are for.

## What step 0 hands to the rest of L1-DAILY

1. **The search path is not a daily source today.** 36 results across 50 axes cannot
   feed a daily tier, and no amount of scheduling changes that.
2. **Before it can be fixed it has to be visible.** `search_wants.jsonl` is the
   precondition, not an improvement.
3. **The daily tier should not be built on search at all.** It should be built on APIs
   that publish on a schedule and say so — which is why the next two steps probe USGS
   and GDACS, with the extract path read off a real payload rather than assumed.
