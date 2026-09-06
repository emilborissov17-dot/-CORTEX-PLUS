# L1-DAILY — GDACS probe
### 6 September 2026. Live payload, extract path read off it — and three traps found by reading it.

## The probe

```
GET https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?fromDate=&toDate=&alertlevel=&eventlist=
http_status=200   bytes=142,068   seconds=1.28   content-type=application/json
```

No key, no browser, no CAPTCHA. The RSS endpoint also answers (`/xml/rss.xml`, 1.4 MB,
`application/xml`) but the JSON API is the one worth using — same events, structured.

## The payload, as it actually came back

```
top-level keys : type, features, bbox      (GeoJSON FeatureCollection)
features       : 100
properties     : Class, affectedcountries, alertlevel, alertscore, country,
                 datemodified, description, episodealertlevel, episodealertscore,
                 episodeid, eventid, eventname, eventtype, fromdate, glide,
                 htmldescription, icon, iconoverall, iscurrent, iso3, istemporary,
                 name, polygonlabel, severitydata, source, sourceid
```

## The extract path — quoted from the payload

```
features[i].properties.eventtype          -> "FL"
features[i].properties.eventid            -> 1104081
features[i].properties.alertlevel         -> "Orange"
features[i].properties.fromdate           -> "2026-07-31T01:00:00"
features[i].properties.todate             -> "2026-09-07T01:00:00"
features[i].properties.country            -> "China"
features[i].properties.iscurrent          -> "true"          <- STRING, not bool
features[i].properties.severitydata       -> {"severity": 0.0,
                                              "severitytext": "Magnitude 0 ",
                                              "severityunit": ""}
```

```
eventtype   : EQ 28, FL 25, TC 19, WF 15, DR 7, VO 6
alertlevel  : Orange 80, Red 20
```

## Three traps, found by reading the payload rather than trusting the field names

**1. `severity` is present, numeric, and meaningless for a third of the feed.**
`severity` parses as a number in 100 of 100 features — which is exactly the kind of
"100% coverage" that would pass a naive check. But:

```
severity == 0.0 : 31 of 100     all floods (25) and volcanoes (6)
```

```
FL: severity=0.0        text='Magnitude 0 '     unit=''
VO: severity=0.0        text=''                 unit=''
EQ: severity=5.0        text='Magnitude 5M, Depth:10km'                 unit='M'
TC: severity=212.96     text='Tropical Storm (maximum wind speed …)'     unit='km/h'
DR: severity=1412468.0  text='Medium impact for agricultural drought …'  unit='km2'
WF: severity=18310.0    text='Orange impact for forestfire in 18310 ha'  unit='ha'
```

**The units are different per event type and two types have no severity at all.**
Averaging or summing `severity` across the feed would add square kilometres to km/h to
nothing, and produce a number with no meaning that nonetheless moves daily. That is the
facade pattern exactly, and this feed hands it to you pre-packaged.

**2. `iscurrent` is a STRING, and almost nothing is current.**

```
iscurrent == "true" : 3 of 100
```

Ninety-seven of the hundred events are historical, with `fromdate` reaching back to
**2025-05-21**. A daily indicator built on `len(features)` would be counting a mostly
static archive and reporting it as today's news. The three current events right now are
a flood in China, a volcano in Indonesia and a tropical cyclone off Japan.

Note also `"true"` is the string, not the boolean — `if props["iscurrent"]:` is true for
`"false"` as well.

**3. `alertlevel` has no Green.** The default query returns Orange and Red only. Whether
that is the endpoint's default filter or the real state of the world is not visible from
one response, so any "share of alerts that are Red" computed from this call is a ratio
of a filtered set and would look alarming for a reason that is not about the world.

## What it can honestly feed, daily

```
current events, by alert level and type -> 3 today (FL Orange, VO Orange, TC Orange)
```

Counting **current** events per type is a real daily quantity. `severity` is usable
**within one event type at a time**, never across them, and never for FL or VO.

## Status

**Probe only.** Nothing wired, no config entry, no axis claimed — same as USGS. The
finding is that GDACS is live, keyless and daily, and that it carries a field which
looks like a clean numeric indicator and is not one. The extract path above is what the
payload actually says; the three traps are what the field names would have let a
consumer assume.
