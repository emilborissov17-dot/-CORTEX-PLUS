#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/fill_pantry.py — the fetching, moved out of the night.

WHY THIS FILE EXISTS. agents/internet/internet_agent.run() used to be step 4 of
the cycle: RSS, GitHub, arXiv, the YouTube API, yt-dlp, Whisper and Playwright,
1691.8s and a browser with dozens of child processes, at three in the morning, on
a machine that died of memory three times on 13 Sep 2026. The cycle now READS the
pantry instead (internet_agent.read_pantry). run() itself was never touched — it
simply had nothing left to call it.

That left a hole worth more than the 28 minutes it saved: the cycle was the ONLY
thing writing news/<day>/. Checked, not assumed — scripts/intel_daemon.py writes
to SQLite and says so in its own docstring, and nothing else touches that
directory. Without a filler the system is blind to news from the next morning on,
which is a worse failure than a slow night.

So: the same work, at a time the machine can afford it. Twice a day, far from the
03:00-05:00 window.

IT ASKS THE SAME GATE THE CYCLE ASKS. This is a heavy job — it is the heavy job —
and running it at 96% memory would repeat the mistake in a new place. It calls
core/homeostasis.assess() and refuses when that refuses. The threshold is not
copied here; it lives in one protected file and this does not know its value.

    venv\\Scripts\\python.exe tools\\fill_pantry.py
    venv\\Scripts\\python.exe tools\\fill_pantry.py --force   # ignore the gate
    venv\\Scripts\\python.exe tools\\fill_pantry.py --axes CLIMATE_GLOBAL_RISK_REVIEW
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LOG = REPO / "memory" / "pantry_fill.jsonl"


def _mem():
    try:
        import psutil
        v = psutil.virtual_memory()
        return round(v.available / 1048576.0, 1), v.percent
    except Exception:
        return None, None


def _count(day: str) -> dict:
    news = REPO / "news" / day
    cache = REPO / "memory" / "transcript_cache"
    fresh = 0
    if cache.is_dir():
        for f in cache.glob("*.json"):
            try:
                if dt.datetime.fromtimestamp(f.stat().st_mtime).date().isoformat() == day:
                    fresh += 1
            except OSError:
                pass
    # THE FILE COUNT IS A LIE AND IT TOLD ONE. The first run reported
    # "news 24 -> 24 (+0)" while every one of the 24 files had in fact been
    # rewritten: the names never change, only the contents. A field whose name
    # misleads is the exact thing this whole day is against, so what is recorded
    # now is the newest mtime — freshness, not a headcount.
    newest = 0.0
    for f in (news.glob("*.json") if news.is_dir() else []):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            pass
    return {"news_files": len(list(news.glob("*.json"))) if news.is_dir() else 0,
            "news_newest_mtime": newest,
            "transcripts_today": fresh,
            "transcripts_total": len(list(cache.glob("*.json"))) if cache.is_dir() else 0}


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="run even if the survival gate refuses")
    ap.add_argument("--axes", nargs="*", default=None)
    ap.add_argument("--ignore-fresh", action="store_true",
                    dest="ignore_fresh",
                    help="refetch even what is still fresh (a human may; the schedule may not)")
    a = ap.parse_args(argv)

    day = dt.date.today().isoformat()
    before = _count(day)
    avail0, pct0 = _mem()

    if not a.force:
        try:
            from core.homeostasis import assess
            verdict = assess(verbose=False) or {}
            if not verdict.get("can_start"):
                print(f"[PANTRY] REFUSED by the same gate the cycle asks: "
                      f"{verdict.get('abort_reason')}")
                print(f"[PANTRY] nothing fetched; the pantry keeps whatever it had "
                      f"({before['news_files']} news file(s) for {day})")
                return 0
        except Exception as e:                       # noqa: BLE001
            # Fail-open, for the same reason the supervisor's check does: an
            # unreadable sensor must not become a system that never fetches.
            print(f"[PANTRY] gate unavailable ({type(e).__name__}: {e}) — proceeding")

    # Peak memory is sampled from a thread, because the number that matters is the
    # worst moment, not the moment it happened to finish.
    peak = {"used_pct": pct0 or 0.0, "min_avail_mb": avail0 or 0.0}
    stop = threading.Event()

    def _watch():
        while not stop.wait(2.0):
            av, pc = _mem()
            if av is None:
                continue
            peak["min_avail_mb"] = min(peak["min_avail_mb"], av)
            peak["used_pct"] = max(peak["used_pct"], pc)

    w = threading.Thread(target=_watch, daemon=True)
    w.start()

    print(f"[PANTRY] filling for {day}; before: {before}")
    t0 = time.perf_counter()
    t_start_wall = time.time()
    err = None
    try:
        from agents.internet.internet_agent import run
        run(axes=a.axes, ignore_fresh=a.ignore_fresh)
    except Exception as e:                           # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        print(f"[PANTRY] run() FAILED: {err}")
    took = time.perf_counter() - t0
    stop.set()
    w.join(timeout=3)

    after = _count(day)
    # How many files this run actually rewrote — the honest version of the number
    # the first run got wrong.
    news_dir = REPO / "news" / day
    refreshed = 0
    for f in (news_dir.glob("*.json") if news_dir.is_dir() else []):
        try:
            if f.stat().st_mtime >= t_start_wall:
                refreshed += 1
        except OSError:
            pass
    avail1, pct1 = _mem()
    rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "day": day,
           "seconds": round(took, 1), "error": err,
           "before": before, "after": after,
           "news_files_added": after["news_files"] - before["news_files"],
           "news_refreshed": refreshed,
           "transcripts_added": after["transcripts_today"] - before["transcripts_today"],
           "avail_mb_start": avail0, "avail_mb_end": avail1,
           "avail_mb_low": peak["min_avail_mb"], "used_pct_peak": peak["used_pct"]}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass

    print(f"[PANTRY] {took:.1f}s | {refreshed} of {after['news_files']} news file(s) "
          f"REWRITTEN (+{rec['news_files_added']} new name(s)) | transcripts today "
          f"{before['transcripts_today']} -> {after['transcripts_today']} "
          f"(+{rec['transcripts_added']})")
    print(f"[PANTRY] memory: start {avail0} MB free, low {peak['min_avail_mb']} MB, "
          f"end {avail1} MB, peak {peak['used_pct']}% used")
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
