#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ucdp_client.py — UCDP GED events, by FILE today and by API the day a token exists.

WHY FILES AND NOT THE API. Measured 18 Sep 2026:

    GET https://ucdpapi.pcr.uu.se/api/gedevents/26.1?pagesize=1
    401  "API token required. Add header: x-ucdp-access-token: <your-token>"

The same 401 answers the monthly candidate endpoint. `core/needs_auth.py:13` has
carried an open request for `UCDP_ACCESS_TOKEN` since 2026-07-13. The download
files, however, are open: one HEAD each, both 200, no login and no redirect. So
the file path is what runs today, the API path is written beside it, and
THE NAMES ARE IDENTICAL IN BOTH — `load_events()` returns the same rows whichever
door it came through, so the day a token arrives nothing downstream changes.

THE THREE FILES AND HOW THEY FIT, measured rather than assumed
--------------------------------------------------------------
UCDP ships the year in one file and the current year in two more, and they do
NOT simply concatenate:

    GEDEvent_v26_1.csv          1989-01-01 .. 2025-12-31   417,968 rows   the release
    GEDEvent_v26_01_26_06.csv   2026-01-01 .. 2026-06-30    10,051 rows   quarterly candidate
    GEDEvent_v26_0_7.csv        2026-03-02 .. 2026-07-31     1,828 rows   monthly candidate

The monthly file is INCREMENTAL, not cumulative: 1,796 of its 1,828 rows are
July, and the other 32 are late-arriving events for March, May and June. It
shares 12 ids with the quarterly file — those are revisions of rows the
quarterly already had. It shares ZERO ids with the release.

So the merge is: read all three, key by `id`, and let the LATER release win. A
naive concatenation double-counts 12 events and a naive "take the newest file"
loses ten thousand. Both were checked before this rule was written.

AS_OF IS THE FILE VERSION, NOT THE CLOCK. Every count this module returns
carries the version string of the newest file that fed it, because UCDP
backfills: an event that happened in July can enter the data in September, and a
number computed today is a statement about what UCDP had published today.

NO .get DEFAULTS. A row missing `type_of_violence` or `side_a` raises KeyError.
A missing column in a UCDP release is a schema change, and a schema change that
silently becomes a zero is the failure this repo keeps finding.

Names locked (a later swap to ACLED is one config line, not a rename):
    ucdp_events_osv       — count of one-sided-violence events (type_of_violence == "3")
    ucdp_deaths_civilians — sum of the deaths_civilians column over those events

Usage:
    venv\\Scripts\\python.exe core/ucdp_client.py --selftest
    venv\\Scripts\\python.exe core/ucdp_client.py --refresh
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "data" / "ucdp"

# Cloudflare answers the default Python-urllib signature with error 1010,
# "Access denied ... based on your browser's signature", AS A 403 — which reads
# exactly like an auth failure and cost an hour on 18 Sep 2026 against ACLED.
# This is an identifying UA for an authorised client, not a disguise.
USER_AGENT = ("CORTEX-PLUS/1.0 institution0 "
              "(+https://github.com/emilborissov17-dot/-CORTEX-PLUS)")

GED_VERSION = "26.1"
CANDIDATE_QUARTERLY = "26_01_26_06"
CANDIDATE_MONTHLY = "26_0_7"

SOURCES = [
    # (local filename, url, kind) — order is oldest release first, so that the
    # later file overwrites the earlier one when the same id appears twice.
    ("GEDEvent_v26_1.csv",
     "https://ucdp.uu.se/downloads/ged/ged261-csv.zip", "zip"),
    ("GEDEvent_v26_01_26_06.csv",
     "https://ucdp.uu.se/downloads/candidateged/GEDEvent_v26_01_26_06.csv", "csv"),
    ("GEDEvent_v26_0_7.csv",
     "https://ucdp.uu.se/downloads/candidateged/GEDEvent_v26_0_7.csv", "csv"),
]

API_BASE = "https://ucdpapi.pcr.uu.se/api/gedevents"
TOKEN_ENV = "UCDP_ACCESS_TOKEN"

OSV = "3"          # UCDP type_of_violence: 3 = one-sided violence against civilians
CIVILIANS = "Civilians"

REQUIRED_COLUMNS = ("id", "type_of_violence", "side_a", "side_b", "country",
                    "date_start", "deaths_civilians", "adm_1")

# UCDP's placeholder for an actor it could not identify. Counted, named, and
# NEVER charged to a party that signed something — see institution0_morning.
UNKNOWN_ACTOR_PREFIX = "XXX"


class UcdpUnavailable(RuntimeError):
    """Raised, never returned as an empty list.

    An empty list is indistinguishable from a quiet month, and a quiet month is
    exactly the finding this experiment would most like to report. So the module
    refuses rather than returning nothing.
    """


def _fetch(url: str, timeout: int = 900) -> bytes:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                raise UcdpUnavailable("%s answered HTTP %s" % (url, r.status))
            return r.read()
    except urllib.error.HTTPError as e:
        raise UcdpUnavailable("%s answered HTTP %s: %s"
                              % (url, e.code, e.read()[:200].decode("utf-8", "replace"))) from e
    except OSError as e:
        raise UcdpUnavailable("%s unreachable: %s: %s" % (url, type(e).__name__, e)) from e


def refresh(data_dir: Path = DATA_DIR) -> dict:
    """Download the three files. Returns {filename: bytes written}."""
    data_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, url, kind in SOURCES:
        body = _fetch(url)
        if kind == "zip":
            zf = zipfile.ZipFile(io.BytesIO(body))
            inner = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not inner:
                raise UcdpUnavailable("%s contains no .csv" % url)
            body = zf.read(inner[0])
        (data_dir / name).write_bytes(body)
        written[name] = len(body)
    return written


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise UcdpUnavailable("%s is not on disk — run core/ucdp_client.py --refresh" % path)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise UcdpUnavailable("%s holds no rows" % path)
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise UcdpUnavailable("%s is missing column(s) %s — UCDP changed the schema"
                              % (path, missing))
    return rows


def load_events(data_dir: Path = DATA_DIR) -> tuple[list[dict], str]:
    """(rows, as_of). Merged, deduplicated by id, later release wins.

    as_of names the newest file that contributed, e.g. "ucdp:26.0.7". It is a
    release identifier and not a timestamp on purpose: two runs on different days
    against the same release must produce the same number, and a clock in the
    field would hide that.
    """
    by_id: dict[str, dict] = {}
    seen = []
    for name, _url, _kind in SOURCES:
        path = data_dir / name
        for row in _read_csv(path):
            by_id[row["id"]] = row          # later file in SOURCES order wins
        seen.append(name)
    if not by_id:
        raise UcdpUnavailable("no rows after merging %s" % seen)
    return list(by_id.values()), "ucdp:%s" % CANDIDATE_MONTHLY.replace("_", ".")


def load_events_api(version: str = GED_VERSION, pagesize: int = 1000) -> tuple[list[dict], str]:
    """The API path. Activates only when UCDP_ACCESS_TOKEN is set.

    Written now and unused now, deliberately: the shape of the answer is the same
    list of dicts as load_events, so the day the token arrives the callers do not
    change. It refuses loudly rather than silently falling back to the files —
    a caller that asked for the API and got a file has been told a small lie
    about what it is looking at.
    """
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise UcdpUnavailable(
            "%s is not set. The API needs it (401 'API token required. Add header: "
            "x-ucdp-access-token'), requested by email 18 Sep 2026. Use load_events() "
            "for the file path." % TOKEN_ENV)
    out: list[dict] = []
    page = 0
    while True:
        url = "%s/%s?pagesize=%d&page=%d" % (API_BASE, version, pagesize, page)
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("x-ucdp-access-token", token)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raise UcdpUnavailable("API %s -> HTTP %s" % (url, e.code)) from e
        rows = payload["Result"]
        out.extend(rows)
        if page + 1 >= int(payload["TotalPages"]):
            break
        page += 1
    return out, "ucdp-api:%s" % version


# --------------------------------------------------------------------------- filters
def month_of(row: dict) -> str:
    """'YYYY-MM' of date_start. KeyError if the column is gone — by design."""
    return row["date_start"][:7]


def osv_events(rows: Iterable[dict], country: str,
               actor: Optional[str] = None) -> list[dict]:
    """ucdp_events_osv: one-sided violence, this country, optionally this actor.

    `actor` matches side_a EXACTLY. No fuzzy match, no casefold, no substring:
    the register records the string UCDP uses, and a near-match that silently
    worked would make the register's verification meaningless.
    """
    out = []
    for r in rows:
        if r["type_of_violence"] != OSV:
            continue
        if r["country"] != country:
            continue
        if actor is not None and r["side_a"] != actor:
            continue
        out.append(r)
    return out


def is_unknown_actor(name: str) -> bool:
    """UCDP codes an unidentified perpetrator as XXXnnn. Never charged to a party."""
    return name.startswith(UNKNOWN_ACTOR_PREFIX) and name[3:].isdigit()


def monthly_counts(rows: Iterable[dict]) -> dict:
    """{'YYYY-MM': count}. ucdp_events_osv aggregated by month of date_start."""
    out: dict[str, int] = {}
    for r in rows:
        out[month_of(r)] = out.get(month_of(r), 0) + 1
    return out


def monthly_deaths_civilians(rows: Iterable[dict]) -> dict:
    """{'YYYY-MM': sum}. ucdp_deaths_civilians aggregated by month."""
    out: dict[str, int] = {}
    for r in rows:
        out[month_of(r)] = out.get(month_of(r), 0) + int(r["deaths_civilians"])
    return out


def last_complete_month(rows: Iterable[dict]) -> str:
    """The newest month present in the data, as 'YYYY-MM'.

    ANCHORED ON THE DATA, NEVER ON TODAY. UCDP's monthly candidate for August is
    released in September; a window measured back from today would sit in a month
    that does not exist yet and every count would be zero, which reads as peace.
    """
    months = {month_of(r) for r in rows}
    if not months:
        raise UcdpUnavailable("no rows, so no complete month")
    return max(months)


def prior_months(anchor: str, n: int) -> list[str]:
    """The n complete months immediately before `anchor`, oldest first."""
    y, m = int(anchor[:4]), int(anchor[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append("%04d-%02d" % (y, m))
    return list(reversed(out))


def ratio_series(counts: dict, months: list[str], k: int = 3) -> list[float]:
    """The last-month / mean-of-prior-k ratio, computed at every month in `months`.

    This is the null: the place's own distribution of the statistic we are about
    to call a "rise". A month whose prior window is empty contributes nothing —
    it is not a ratio of zero, it is an absence of one.
    """
    out = []
    for month in months:
        prior = [counts.get(p, 0) for p in prior_months(month, k)]
        denom = sum(prior) / float(k)
        if denom <= 0:
            continue
        out.append(counts.get(month, 0) / denom)
    return out


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile. None for an empty series, never 0.0."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def selftest(data_dir: Path = DATA_DIR) -> dict:
    """Which integrations are LIVE in the repo this finds itself in."""
    out: dict = {"data_dir": str(data_dir), "files": {}}
    for name, url, _k in SOURCES:
        p = data_dir / name
        out["files"][name] = ("LIVE (%d bytes)" % p.stat().st_size) if p.exists() else "INERT (absent)"
        out["files"][name + " @url"] = url
    out["api"] = ("LIVE (%s is set)" % TOKEN_ENV) if os.environ.get(TOKEN_ENV) \
        else "INERT (%s unset — file path in use)" % TOKEN_ENV
    try:
        rows, as_of = load_events(data_dir)
        out["merged_rows"] = len(rows)
        out["as_of"] = as_of
        out["last_complete_month"] = last_complete_month(rows)
        out["osv_rows"] = sum(1 for r in rows if r["type_of_violence"] == OSV)
    except UcdpUnavailable as why:
        out["merged_rows"] = "REFUSED: %s" % why
    return out


def main(argv: list[str]) -> int:
    if "--refresh" in argv:
        print(json.dumps(refresh(), indent=2))
        return 0
    print(json.dumps(selftest(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
