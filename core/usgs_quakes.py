#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USGS_QUAKE_M45_DAILY — daily count of M4.5+ earthquakes, and the wiring that makes the
gate resolve it.

WHY THIS AND NOT GDELT (Kimi R41). GDELT's daily event count halves at weekends —
117,020 / 107,037 / 66,878 for Thu / Fri / Sat — so beating naive persistence there is
calendar arithmetic, not insight. Earthquakes have no weekly cycle: measured
2026-09-02..06, the counts are 17 / 24 / 12 / 13 / 15 across Wed–Sun with no weekend
signature. Persistence is a true ceiling here, which is what makes the bet mean
something. The GDELT wiring (4c6751d) stays prepared for the second bet.

THE DAY BOUNDARY IS THE WHOLE DESIGN. The obvious feed — `4.5_day.geojson` — is a
ROLLING 24-hour window ending whenever you happen to ask. Measured 2026-09-07 07:17 UTC
it spanned 09-06 10:32 to 09-07 05:50. A bet sealed against a rolling window cannot be
graded, because the window has moved by the time you grade it. So this module uses the
fdsnws query API with EXPLICIT UTC calendar-day bounds, and the day is always UTC.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parents[1]

INDICATOR = "USGS_QUAKE_M45_DAILY"
MIN_MAG = 4.5
COUNT_URL = "https://earthquake.usgs.gov/fdsnws/event/1/count"
QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# read off evaluator.py rather than assumed: :17 and :22
TRENDS_PATH = REPO / "cortex_memory" / "abstractions" / "trends.json"
GOAL_SNAP_PATH = REPO / "snapshots" / "master" / "goal_score_latest.json"

EXTRACT_PATH = ("GET fdsnws/event/1/count?format=geojson"
                "&starttime=<D>T00:00:00&endtime=<D+1>T00:00:00&minmagnitude=4.5"
                " -> body.count   (UTC calendar day, M4.5+ only)")
UNITS = "earthquakes per UTC day with magnitude >= 4.5"


def day_bounds(day: date) -> tuple:
    """[start, end) in UTC. USGS starttime/endtime are UTC; there is no local day."""
    return (f"{day.isoformat()}T00:00:00",
            f"{(day + timedelta(days=1)).isoformat()}T00:00:00")


def count_url(day: date, min_mag: float = MIN_MAG) -> str:
    s, e = day_bounds(day)
    return COUNT_URL + "?" + urlencode(
        {"format": "geojson", "starttime": s, "endtime": e, "minmagnitude": min_mag})


def parse_count(body) -> int:
    """{"count": 15, "maxAllowed": 20000} -> 15.

    `maxAllowed` is the API's cap, NOT a count. A reader that grabs the first integer
    it sees gets 20000 — a number that looks like an event count and is a quota.
    """
    d = json.loads(body) if isinstance(body, (str, bytes)) else body
    if "count" not in d:
        raise ValueError(f"no 'count' in USGS response: {str(d)[:120]}")
    n = int(d["count"])
    if n >= int(d.get("maxAllowed", 20000)):
        raise ValueError(f"count {n} hit maxAllowed — the response is truncated, "
                         f"not a count")
    return n


def complete_days(n: int = 3, today: date | None = None) -> list:
    """The n most recent COMPLETE UTC days.

    Today is excluded because it is still running: a partial day always reads low, and
    a bet graded against a partial day is graded against the clock rather than the
    world.
    """
    today = today or datetime.now(timezone.utc).date()
    return [today - timedelta(days=i) for i in range(n, 0, -1)]


def fetch_count(day: date, min_mag: float = MIN_MAG, timeout: int = 60) -> int:
    """Network; never called by the tests."""
    import requests
    r = requests.get(count_url(day, min_mag), timeout=timeout,
                     headers={"User-Agent": "CORTEX++/1.0 (research)"})
    r.raise_for_status()
    return parse_count(r.text)


CHUNK_DAYS = 120            # ~2,500 M4.5+ events per chunk, far under maxAllowed 20,000


def query_url(start: date, end: date, min_mag: float = MIN_MAG) -> str:
    """[start, end) as one CSV event query — for long backfills, one call per chunk
    instead of one per day (730 days = 7 calls, not 730)."""
    return QUERY_URL + "?" + urlencode(
        {"format": "csv", "starttime": f"{start.isoformat()}T00:00:00",
         "endtime": f"{end.isoformat()}T00:00:00", "minmagnitude": min_mag, "orderby": "time-asc"})


def counts_from_csv(text: str, days: list) -> list:
    """[(day, count)] for every day in `days` (zero where no event), from a USGS CSV body.
    The first column is `time` (ISO, UTC). A day outside `days` is ignored."""
    want = {d: 0 for d in days}
    lines = text.splitlines()
    if not lines or not lines[0].lower().startswith("time"):
        raise ValueError(f"not a USGS CSV body: {text[:80]!r}")
    for line in lines[1:]:
        if not line.strip():
            continue
        try:
            d = datetime.fromisoformat(line.split(",", 1)[0].replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d in want:
            want[d] += 1
    return sorted(want.items())


def series_range(days: list, text_fetcher=None, min_mag: float = MIN_MAG) -> list:
    """Same result as series(), for many days: chunked CSV queries. `text_fetcher(url)`
    injectable so the tests never touch the network."""
    import requests
    if not days:
        return []
    get = text_fetcher or (lambda u: requests.get(u, timeout=120,
                                                  headers={"User-Agent": "CORTEX++/1.0 (research)"}).text)
    days = sorted(days)
    out = []
    i = 0
    while i < len(days):
        chunk = days[i:i + CHUNK_DAYS]
        body = get(query_url(chunk[0], chunk[-1] + timedelta(days=1), min_mag))
        rows = counts_from_csv(body, chunk)
        if sum(c for _, c in rows) >= 20000:
            raise ValueError("chunk hit maxAllowed — truncated, not a count")
        out.extend(rows)
        i += CHUNK_DAYS
    return out


def series(days: list, fetcher=None, min_mag: float = MIN_MAG) -> list:
    """[(day, count)] — `fetcher` injectable so the tests never touch the network."""
    get = fetcher or (lambda d: fetch_count(d, min_mag))
    return [(d, get(d)) for d in days]


def registration_entry(counts: list) -> dict:
    """THE REGISTRATION. evaluator.ground_truth reads trends.json[axis] and takes
    values[-1], so this is a LIST with the newest value last."""
    return {INDICATOR: [int(c) for c in counts]}


def is_registered(trends_path: Path | None = None) -> bool:
    p = Path(trends_path or TRENDS_PATH)
    try:
        return INDICATOR in json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False


def _selftest() -> int:
    print("core/usgs_quakes.py --selftest")
    print(f"  INDICATOR    : {INDICATOR}")
    print(f"  EXTRACT_PATH : {EXTRACT_PATH}")
    print(f"  UNITS        : {UNITS}")
    print(f"  registered   : {is_registered()}")
    print(f"  complete_days: {[d.isoformat() for d in complete_days(3)]}")
    print(f"  example url  : {count_url(complete_days(1)[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
