#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GDELT_DAILY — a genuine daily event count, and the wiring to make the gate resolve it.

NOT ACTIVATED. This module computes the value and states the exact registration entry;
it does NOT write it. `cortex_memory/abstractions/trends.json` and `metric_details` stay unchanged
until after the 03:04 cycle, so tonight's gate report stays comparable with this
morning's.

WHY NOT THE ENDPOINT THE CYCLE ALREADY PULLS
    `core/global_indicators.py:603 fetch_gdelt()` calls the DOC 2.0 API with
    `mode=timelinetone`. Two things are wrong with it as a source for a daily COUNT:
    it returns tone, not a count; and measured 2026-09-07 it returns NOTHING —

        mode=timelinetone   http 200, 121 bytes, "data": [ ]
        mode=timelinevolraw http 200,  80 bytes, "timeline": [ ]
        every request after that: http 429, for 45+ minutes

    So the media slot is already dead on arrival and a count cannot be built from it.
    The static file server is a different host and answers: one file per day,
    published ~07:00 UTC the following day.

THE RESOLUTION CHAIN, traced 2026-09-07
    proposal_intake.judge
      -> proposal_intake._default_resolver
      -> hypothesis_intake._resolves
      -> evaluator.ground_truth(axis, metric)
      -> cortex_memory/abstractions/trends.json[axis]  ... takes values[-1]

    So the registration is ONE key in trends.json holding a LIST, and the gate
    reads the last element. `registration_entry()` returns exactly that and nothing
    writes it.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

INDICATOR = "GDELT_DAILY"
EVENTS_URL = "https://data.gdeltproject.org/events/{day}.export.CSV.zip"
# THE REAL PATHS, read off evaluator.py rather than assumed. I first wrote
# memory/trends_latest.json here and it is WRONG: evaluator.py:17 resolves
# cortex_memory/abstractions/trends.json, and metric_details lives inside
# snapshots/master/goal_score_latest.json (evaluator.py:22). A registration
# written to the wrong file would resolve nothing while looking done.
TRENDS_PATH = REPO / "cortex_memory" / "abstractions" / "trends.json"
GOAL_SNAP_PATH = REPO / "snapshots" / "master" / "goal_score_latest.json"

# THE EXTRACT PATH, read off the real payload on 2026-09-07:
#   GET https://data.gdeltproject.org/events/<YYYYMMDD>.export.CSV.zip
#   -> zip containing exactly one member, "<YYYYMMDD>.export.CSV"
#   -> TAB-separated, 58 columns, NO header row
#   -> column 0  GLOBALEVENTID
#      column 1  SQLDATE  (YYYYMMDD)
#   -> the daily event count is the NUMBER OF ROWS
EXTRACT_PATH = ("zip://<YYYYMMDD>.export.CSV.zip!/<YYYYMMDD>.export.CSV "
                "-> row count (58 TSV columns, no header); col 1 = SQLDATE")
UNITS = "events per day (count of GDELT event records)"


def count_from_zip(raw: bytes, day: str, sqldate_filter: bool = True) -> int:
    """Rows in the daily export. With `sqldate_filter`, only rows whose SQLDATE is
    the file's own day.

    THE FILTER IS NOT COSMETIC. A daily export contains events RECORDED that day,
    and roughly 2% of them carry an older SQLDATE — an article published today about
    something that happened last year. Measured on the three real files:

        20260903  117,020 rows   114,504 with SQLDATE == 20260903  (97.8%)
        20260904  107,037 rows   104,882 with SQLDATE == 20260904  (98.0%)
        20260905   66,878 rows    65,683 with SQLDATE == 20260905  (98.2%)

    Both are defensible numbers and they are DIFFERENT numbers. Which one is meant
    has to be decided once and then never silently switched, which is why it is a
    named argument and not a magic default buried in a loop.
    """
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    if not names:
        raise ValueError("the daily export zip is empty")
    data = z.read(names[0])
    n = 0
    want = day.encode("ascii")
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        if sqldate_filter:
            parts = line.split(b"\t")
            if len(parts) < 2 or parts[1].strip() != want:
                continue
        n += 1
    return n


def fetch_day(day: str, timeout: int = 180) -> bytes:
    """One day's export. Network; never called by the tests."""
    import requests
    r = requests.get(EVENTS_URL.format(day=day), timeout=timeout,
                     headers={"User-Agent": "CORTEX++/1.0 (research)"})
    r.raise_for_status()
    return r.content


def recent_days(n: int = 3, today: date | None = None) -> list:
    """The n most recent days whose file should exist.

    Yesterday is the newest available: a day's file is published around 07:00 UTC the
    FOLLOWING day (Last-Modified on the three real files: 04 Sep 07:00:10,
    05 Sep 07:00:12, 06 Sep 07:00:06). Asking for today returns 404.
    """
    today = today or date.today()
    return [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(n, 0, -1)]


def series(days: list, fetcher=None, sqldate_filter: bool = True) -> list:
    """[(day, count)] — `fetcher` is injectable so the tests never touch the network."""
    get = fetcher or fetch_day
    return [(d, count_from_zip(get(d), d, sqldate_filter)) for d in days]


def registration_entry(counts: list) -> dict:
    """THE ONE LINE FOR TOMORROW, and this module does not write it.

    evaluator.ground_truth reads trends.json[axis] and takes values[-1], so the entry
    is a LIST and the newest value goes last. Merge this into
    cortex_memory/abstractions/trends.json after the 03:04 cycle has finished.
    """
    return {INDICATOR: [int(c) for c in counts]}


def is_registered(trends_path: Path | None = None) -> bool:
    """Is GDELT_DAILY live in trends.json yet? Expected False until tomorrow."""
    import json
    p = Path(trends_path or TRENDS_PATH)
    try:
        return INDICATOR in json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False


def _selftest() -> int:
    print("core/gdelt_daily.py --selftest")
    print(f"  INDICATOR      : {INDICATOR}")
    print(f"  EXTRACT_PATH   : {EXTRACT_PATH}")
    print(f"  UNITS          : {UNITS}")
    print(f"  registered live: {is_registered()}   (expected False before tomorrow)")
    print(f"  recent_days(3) : {recent_days(3)}")
    print("  LIVE fetch is NOT performed by --selftest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
