# L1-DAILY — USGS probe
### 6 September 2026. Live payload, extract path read off it rather than assumed.

## The probe

```
GET https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
http_status=200   bytes=128,026   seconds=0.416
```

No key, no browser, no CAPTCHA. One anonymous GET.

## The payload, as it actually came back

```
top-level keys : type, metadata, features, bbox
metadata       : {generated: 1788713713000, url: …, title: "USGS All Earthquakes,
                  Past Day", status: 200, api: "2.7.0", count: 178}
features       : 178
feature keys   : type, properties, geometry, id
properties     : alert, cdi, code, detail, dmin, felt, gap, ids, mag, magType, mmi,
                 net, nst, place, rms, sig, sources, status, time, title, tsunami,
                 type, types, tz, updated, url
```

## The extract path — quoted from the payload above

```
metadata.generated                 -> 1788713713000        (feed build time, ms epoch)
metadata.count                     -> 178                  (self-declared count)
features[i].properties.mag         -> 1.01                 (float, magnitude)
features[i].properties.time        -> 1788713092250        (event time, ms epoch)
features[i].properties.place       -> "7 km WNW of Cobb, CA"
```

**Checked, not assumed:** `mag` is a usable number in **178 of 178** features. `count`
in the metadata equals `len(features)` exactly, so the feed states its own size and the
statement is true — which means a truncated download is detectable without a second
request.

## What it can feed, daily

```
max magnitude in the last 24 h ....... 5.6
events with mag >= 4.5 ............... 16
```

Both are **genuinely daily**: the feed is rebuilt continuously and the window is
literally "past day", so tomorrow's value cannot be today's. That is the property the
whole daily tier needs and the property twelve of the thirteen current indicators lack.

## Two cautions before anything is wired

**1. `mag` is not an axis.** A count of earthquakes is not a measure of planetary
health, and wiring `max_mag` to `PLANET_*` because both mention the planet is exactly
the facade this repo keeps auditing. USGS is a real daily *source*; which axis, if any,
it legitimately measures is a separate decision that nobody has made yet, and this probe
does not make it.

**2. Millisecond epochs.** `generated` and `time` are milliseconds, not seconds.
`1788713713000` read as seconds is the year 58,646. Any consumer converts explicitly.

## Status

**Probe only.** Nothing is wired, no config entry is added, no axis is claimed. The
finding is that the source is live, keyless, sub-second, self-describing and truly
daily — and that its extract path is the five lines above, read off a real payload.
