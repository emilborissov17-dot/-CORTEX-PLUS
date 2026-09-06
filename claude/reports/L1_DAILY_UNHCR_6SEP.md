# L1-DAILY — UNHCR probe → SOCIAL_RELATIONS
### 6 September 2026. Live payload, extract path read off it — and the source asked for is NOT reachable.

## The probe

**The Operational Data Portal is blocked to this client.** Three ODP endpoints, all
returning the same thing:

```
GET https://data.unhcr.org/population/get/situation?...   http=404  bytes=14,083  text/html
GET https://data.unhcr.org/api/situations.json            http=404  bytes=14,083  text/html
```

**That 404 is not a 404.** It is 14 KB of obfuscated JavaScript —
`const _0x4b9492=_0x4c06;function _0x4c06(_0x4269b3,_0x4da0a8){...}` — i.e. a
bot-protection challenge page served with a 404 status. A caller checking
`status == 200` fails correctly here, but a caller checking `status != 500`, or one that
parses the body for data, gets 14 KB of minified JS and no error.

**This is exactly the case `memory/search_wants.jsonl` was specified for in step 0:**
the correct outcome label is `CAPTCHA`/`blocked`, not `HTTP_ERROR`, and today nothing
would record either. Per the standing rule, no CAPTCHA handling is proposed and none was
attempted.

**What answers instead:** the Refugee Data Finder API, `api.unhcr.org`, which is a
different service with different content — annual statistics, not the ODP's
situation-level operational figures.

```
GET https://api.unhcr.org/population/v1/population/?limit=20&yearFrom=2020&yearTo=2024&coo=UKR&columns=refugees,asylum_seekers,oip
http_status=200   bytes=1,471   seconds=0.43
```

**Key required: no.**

## The payload

```
top keys : page, short-url, maxPages, total, items
item keys: year, coo_id, coo_name, coo, coo_iso, coa_id, coa_name, coa, coa_iso,
           refugees, asylum_seekers, returned_refugees, idps, returned_idps,
           stateless, ooc, oip, hst

{"year": 2020, "coo_name": "Ukraine", "coo": "UKR", "coa_name": "-",
 "refugees": 35156, "asylum_seekers": 21426, "returned_refugees": "0",
 "idps": 734000, "returned_idps": "0", "stateless": "0", "ooc": 1620005,
 "oip": "-", "hst": "0"}
```

## The extract path

```
items[i]["year"]           -> 2020        int
items[i]["coo_name"]       -> "Ukraine"   country of ORIGIN
items[i]["coa_name"]       -> "-"         country of ASYLUM ("-" = aggregated)
items[i]["refugees"]       -> 35156       UNITS: persons
items[i]["asylum_seekers"] -> 21426       persons
items[i]["idps"]           -> 734000      persons — internally displaced
maxPages                   -> 1           paginate on this, not on len(items)
```

## Real update cadence — from the payload's own dates

```
years present: [2020, 2021, 2022, 2023, 2024]
step: 1 YEAR
latest year: 2024        lag from today: ~20 months
```

**This is an ANNUAL series, and it is the slowest thing probed today.** The latest year
is 2024 in September 2026. Under the cadence gate committed this morning it would be
`annual` and, at 20 months stale, **OVERDUE — so any deadline against it is refused by
name.** It cannot feed a daily tier. It is the same class as the twelve indicators the
gate already refuses.

**The `columns=` parameter was ignored.** I requested `refugees,asylum_seekers,oip` and
received all 18 fields. Harmless here, but it means the parameter cannot be relied on to
bound the response.

## What would be wrong to do with it

**1. Calling it daily, or calling the ODP block "no data".** The daily situation figures
are on the portal that refused the request. Substituting an annual API and reporting it
as the same source would be the substitution this repo audits for.

**2. Mixing the type strings with the numbers.** `refugees` is `35156` (int) while
`returned_refugees` is `"0"` (string) and `oip` is `"-"` in the same record. **Three
types in one row**, and `"-"` is not zero — it is "not applicable/not reported". Summing
with `int(x or 0)` turns every unknown into a zero and produces a total that is
confidently too low.

**3. Adding `refugees` to `idps` to `ooc`.** They are different populations under
different definitions, and `ooc` ("others of concern") is a residual category whose
composition changes between years. Their sum is not "people displaced".

**4. Reading a country of origin as a country's condition.** `coo=UKR` counts people
*from* Ukraine, wherever they are. It is a fact about displacement, not about Ukraine's
internal state, and `coa_name: "-"` means this row is aggregated over all asylum
countries — not that the asylum country is unknown.

## Status

**Probe only.** Nothing wired, no config entry, no axis claimed. Two findings: the
source the brief names is **behind bot protection that returns 404**, and the API that
does answer is **annual and 20 months stale** — which makes it a legitimate source for
SOCIAL_RELATIONS and a non-starter for the daily tier.
