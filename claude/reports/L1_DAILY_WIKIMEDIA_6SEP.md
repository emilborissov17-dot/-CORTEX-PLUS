# L1-DAILY — Wikimedia pageviews probe → CULTURE_MEDIA
### 6 September 2026. Live payloads, extract path read off them, cadence and the bot share measured rather than assumed.

## The probe

Four live GETs, `en.wikipedia`, `all-access`, `all-agents`, daily, 2026-08-20 → 2026-09-06:

```
Ukraine          http_status=200   bytes=2,563   seconds=0.45
Sudan            http_status=200   bytes=2,527   seconds=0.33
Bulgaria         http_status=200   bytes=2,578   seconds=0.34
Climate_change   http_status=200   bytes=2,680   seconds=0.34
```

**Key required: no.** Anonymous GET. A descriptive `User-Agent` is required by
Wikimedia's policy and was sent; a generic one is rate-limited or blocked.

## The payload

```
top keys : items
item keys: project, article, granularity, timestamp, access, agent, views

{'project': 'en.wikipedia', 'article': 'Ukraine', 'granularity': 'daily',
 'timestamp': '2026082000', 'access': 'all-access', 'agent': 'all-agents',
 'views': 8471}
```

## The extract path

```
items[i]["timestamp"] -> "2026082000"    YYYYMMDDHH — the HH is ALWAYS "00" at daily
                                          granularity and is NOT an hour
items[i]["views"]     -> 8471            UNITS: page requests, integer count
items[i]["article"]   -> "Ukraine"       echoed back — use it to confirm no redirect
items[i]["agent"]     -> "all-agents"    echoed back — see the trap below
```

## Real update cadence — from the timestamps

```
                rows   first        last         step        lag
Ukraine          17    2026-08-20   2026-09-05   1 day x16   1 day
Sudan            17    2026-08-20   2026-09-05   1 day x16   1 day
Bulgaria         17    2026-08-20   2026-09-05   1 day x16   1 day
Climate_change   17    2026-08-20   2026-09-05   1 day x16   1 day
```

**Genuinely daily, no gaps, one-day lag.** I asked for 18 days and got 17: **today is
not there.** The API silently returns a shorter list rather than erroring, so a caller
that assumes `len(items) == days_requested` is wrong on every call.

Current values (2026-09-05): Ukraine 6,981 · Sudan 3,399 · Bulgaria 4,739 ·
Climate_change 2,996.

## What would be wrong to do with it

**1. Using `all-agents`. A quarter of it is not people.** Measured on Ukraine,
2026-09-01…05:

```
user        27,964     74.1%
automated    6,593
spider       3,198
all-agents  37,755     bots + automated = 25.9%
```

`all-agents` is the API's default-looking value and the one in every example. **For
anything about human attention, the correct agent is `user`.** The bot share is not
constant across articles or over time, so it is not even a stable offset — it is noise
with a trend of its own.

**2. Comparing raw counts across articles.** Ukraine 6,981 against Bulgaria 4,739 says
almost nothing: article popularity is dominated by baseline notability, inbound links,
and whether the title is a common word. Only the *change against that article's own
baseline* carries information.

**3. Treating a spike as public concern.** Pageviews respond to news cycles, a link from
a large site, a TV mention, or a redirect change. A spike on `Sudan` is a media event
whose sign is unknown — it can mean attention to a crisis or a football result.
Attaching it to a `CULTURE_MEDIA` axis and reading it as "engagement" would be a real
number that moves daily attached to a concept it does not measure.

**4. Assuming the article title is stable.** The API resolves redirects silently and
echoes the *requested* title in `article`. If a page is renamed, the series continues
under a title that no longer exists, or quietly becomes a different page's counts.
`Climate_change` is exactly the kind of title that gets reorganised.

**5. Reading `timestamp` as a datetime.** `"2026082000"` is `YYYYMMDDHH` with `HH`
fixed at `00` for daily granularity. It is not an hour, and `fromisoformat` does not
parse it.

## Status

**Probe only.** Nothing wired, no config entry, no axis claimed. The finding: keyless,
sub-half-second, genuinely daily with a one-day lag — and the value nearly everyone
reads (`all-agents`) is **25.9% non-human** on the one article where I measured it.
