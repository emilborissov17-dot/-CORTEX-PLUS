#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/intel_daemon.py — THE COLD SHELL. FETCHING, AND NOTHING ELSE.

WHAT IT IS FOR
---------------
`internet_intelligence` is the step the existence ledger blames most: 6 of 13
kills, and 4 deaths. It does two unrelated jobs in one place — it goes out to
twenty endpoints over a slow network, AND it reasons about what came back. The
reasoning holds the cycle's clock hostage to the network, and the network holds
it hostage to the model.

This separates them. The daemon does the FETCHING, on its own schedule, in its
own process, hours before the cycle needs the material. The cycle's job then
becomes a SELECT and a batch summarisation, which is bounded work over local
rows instead of unbounded work over the open internet.

  ZERO LLM CALLS. Not "no LLM calls today" — the process does not import the
  LLM chain at all. That is why the source table below is read out of
  agents/internet/internet_agent.py with ast.literal_eval instead of by
  importing it: importing pulls in core.groq_backend, and then "makes no model
  calls" is a claim about runtime rather than a property of the program. One
  source of truth for the endpoints, no LLM in the process. test/
  test_intel_daemon.py holds both halves.

TWO NUMBERS THAT ARE NOT CONFIGURABLE, ON PURPOSE
--------------------------------------------------
    MAX_CONTENT_BYTES   1 MB     read cap, enforced WHILE streaming
    STREAM_TIMEOUT_SEC  15 s     per-request

They are module constants with no env override and no config file, because the
failure they prevent is a daemon that is handed a bad number by something else
and then sits on a socket for an hour. A cap that can be widened by a config
file is a cap that will one day be widened by a config file. If these need to
change, they change here, in a commit, with a reason.

THE LINK IS NOT OPTIONAL
-------------------------
A row without a url is REFUSED at write time — not dropped quietly, not stored
with an empty string. This repo has spent months separating claims that can be
checked from claims that cannot, and a finding whose source cannot be opened is
the second kind. sqlite enforces it too (NOT NULL + a length check), so a future
writer that forgets cannot get past the schema.

APPEND-ONLY IS ENFORCED BY THE DATABASE
----------------------------------------
Two triggers RAISE(ABORT) on UPDATE and DELETE. Convention would have been
cheaper and would have lasted until the first person who wanted to "clean up"
the table.

    venv\\Scripts\\python.exe scripts/intel_daemon.py --selftest
    venv\\Scripts\\python.exe scripts/intel_daemon.py --run --axis CLIMATE_GLOBAL_RISK_REVIEW
    venv\\Scripts\\python.exe scripts/intel_daemon.py --schtasks     # PRINTS, does not register
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
DB_PATH = BASE / "memory" / "intel.db"
INTERNET_AGENT = BASE / "agents" / "internet" / "internet_agent.py"

# ── NOT CONFIGURABLE. See the module docstring. ─────────────────────────────
MAX_CONTENT_BYTES = 1024 * 1024          # 1 MB
STREAM_TIMEOUT_SEC = 15                  # seconds, per request
USER_AGENT = "CORTEX-IntelDaemon/1.0"

TASK_NAME = "CORTEX_Intel"
RUN_EVERY_HOURS = 6


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# The source table — one copy, read without importing the LLM chain
# ---------------------------------------------------------------------------

def _literal_assignments(path: pathlib.Path, names: tuple) -> dict:
    """{name: value} for module-level literal assignments, via AST.

    NOT an import. agents/internet/internet_agent.py imports core.groq_backend at
    module scope, so importing it to read two dicts would put the whole LLM chain
    inside a process whose entire promise is that it has no model in it.

    Fails LOUDLY rather than returning {}: a daemon that silently finds no
    sources looks exactly like a daemon whose sources all went quiet.
    """
    out: dict = {}
    try:
        # utf-8-SIG, not utf-8: internet_agent.py starts with a BOM, and ast.parse
        # rejects U+FEFF as an invalid non-printable character on line 1. Found by
        # running this, not by reading the file — the BOM is invisible in an editor.
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, SyntaxError) as e:
        raise RuntimeError(
            "cannot read the source table from {}: {}: {}".format(path, type(e).__name__, e))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    # It stopped being a literal. Say so; do not guess.
                    raise RuntimeError(
                        "{} in {} is no longer a literal, so it cannot be read "
                        "without importing the module".format(target.id, path.name))
    missing = [n for n in names if n not in out]
    if missing:
        raise RuntimeError(
            "{} does not define {} any more — the daemon's source table moved "
            "and nobody told it".format(path.name, ", ".join(missing)))
    return out


def source_table() -> dict:
    """{'RSS_FEEDS': {axis: url}, 'ARXIV_CATEGORIES': {axis: cat}}."""
    return _literal_assignments(INTERNET_AGENT, ("RSS_FEEDS", "ARXIV_CATEGORIES"))


# ---------------------------------------------------------------------------
# HTTP — capped while streaming, never after
# ---------------------------------------------------------------------------

def http_get(url: str, opener: Optional[Callable] = None) -> Optional[bytes]:
    """Up to MAX_CONTENT_BYTES of `url`, or None. Never raises.

    The cap is applied WHILE READING, in chunks. Checking Content-Length instead
    would trust a header that a hostile or broken server controls, and reading
    the whole body before measuring it is how a daemon meets its first 4GB file.
    A response that exceeds the cap is DISCARDED, not truncated: half a JSON
    document parses as nothing useful and half an article is a misquote.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(req, timeout=STREAM_TIMEOUT_SEC) as r:
            chunks, total = [], 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_CONTENT_BYTES:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Parsers — same endpoints and shapes internet_agent uses
# ---------------------------------------------------------------------------

def parse_rss(raw: bytes, max_items: int = 8) -> list:
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:2000]
        link = (item.findtext("link") or "").strip()
        items.append({"title": title, "raw_text": desc, "url": link, "source": "RSS"})
        if len(items) >= max_items:
            break
    return items


def parse_arxiv(raw: bytes, max_items: int = 8) -> list:
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", "", ns) or "").strip()[:2000]
        link = entry.find("atom:link[@rel='alternate']", ns)
        url = link.get("href", "") if link is not None else ""
        out.append({"title": title, "raw_text": summary, "url": url, "source": "arXiv"})
        if len(out) >= max_items:
            break
    return out


def parse_gdelt(raw: bytes, max_items: int = 8) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return []
    out = []
    for a in (data.get("articles") or [])[:max_items]:
        out.append({"title": (a.get("title") or "")[:300],
                    "raw_text": (a.get("title") or "")[:2000],
                    "url": a.get("url") or "",
                    "source": a.get("domain") or "GDELT"})
    return out


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS intel (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    source    TEXT NOT NULL,
    url       TEXT NOT NULL CHECK (length(trim(url)) > 0),
    title     TEXT,
    raw_text  TEXT,
    axis_hint TEXT
);
CREATE INDEX IF NOT EXISTS intel_ts   ON intel(ts);
CREATE INDEX IF NOT EXISTS intel_axis ON intel(axis_hint);
CREATE UNIQUE INDEX IF NOT EXISTS intel_url_ts ON intel(url, ts);

-- Append-only, enforced by the database rather than by good intentions.
CREATE TRIGGER IF NOT EXISTS intel_no_update
BEFORE UPDATE ON intel
BEGIN SELECT RAISE(ABORT, 'intel is append-only: UPDATE is refused'); END;

CREATE TRIGGER IF NOT EXISTS intel_no_delete
BEFORE DELETE ON intel
BEGIN SELECT RAISE(ABORT, 'intel is append-only: DELETE is refused'); END;
"""


class LinkRequired(ValueError):
    """A finding whose source cannot be opened is not a finding."""


def connect(db_path: Optional[pathlib.Path] = None) -> sqlite3.Connection:
    path = pathlib.Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def write_row(conn: sqlite3.Connection, source: str, url: str,
              title: str = "", raw_text: str = "",
              axis_hint: str = "", ts: Optional[str] = None) -> bool:
    """Append one finding. Returns False if it was a duplicate.

    Raises LinkRequired when the url is missing — deliberately an exception and
    not a silent skip. A caller that produced a linkless finding has a bug, and a
    daemon that quietly drops such rows would hide it behind a low row count.
    """
    if not url or not str(url).strip():
        raise LinkRequired(
            "refusing to store {!r} from {!r}: no url. A finding without a link "
            "cannot be checked by anyone.".format((title or "")[:60], source))
    try:
        conn.execute(
            "INSERT INTO intel (ts, source, url, title, raw_text, axis_hint) "
            "VALUES (?,?,?,?,?,?)",
            (ts or utc_now(), str(source), str(url).strip(),
             (title or "")[:500], (raw_text or "")[:20000], axis_hint or ""))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False            # same url in the same instant — already stored


def fresh_since(conn: sqlite3.Connection, ts: str,
                axis_hint: Optional[str] = None, limit: int = 500) -> list:
    """THE READER THE CYCLE WILL USE. Rows written at or after `ts`.

    Not wired to anything today. This is the seam the future
    internet_intelligence step reads instead of going to the network: the step
    becomes SELECT + summarise-in-batch, which is bounded work.
    """
    sql = "SELECT * FROM intel WHERE ts >= ?"
    args: list = [ts]
    if axis_hint:
        sql += " AND axis_hint = ?"
        args.append(axis_hint)
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def fresh_within_hours(conn: sqlite3.Connection, hours: float = 12.0,
                       axis_hint: Optional[str] = None) -> list:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return fresh_since(conn, since, axis_hint)


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) n, MIN(ts) first, MAX(ts) last FROM intel").fetchone()
    by_axis = {r["axis_hint"] or "(none)": r["n"] for r in conn.execute(
        "SELECT axis_hint, COUNT(*) n FROM intel GROUP BY axis_hint "
        "ORDER BY n DESC LIMIT 10")}
    return {"rows": row["n"], "first": row["first"], "last": row["last"],
            "by_axis": by_axis}


# ---------------------------------------------------------------------------
# One pass
# ---------------------------------------------------------------------------

def run_once(axes: Optional[list] = None,
             db_path: Optional[pathlib.Path] = None,
             getter: Optional[Callable] = None,
             table: Optional[dict] = None) -> dict:
    """Fetch every configured source for `axes` and append what came back.

    `getter` is injected so the tests can stub HTTP without a network. Nothing
    here reasons about the content: it is stored raw, and the cycle decides later
    what any of it means.
    """
    get = getter or http_get
    tbl = table or source_table()
    rss = tbl.get("RSS_FEEDS") or {}
    arx = tbl.get("ARXIV_CATEGORIES") or {}
    targets = list(axes) if axes else sorted(set(rss) | set(arx))

    conn = connect(db_path)
    report = {"started": utc_now(), "axes": targets, "written": 0,
              "duplicates": 0, "refused_no_url": 0, "fetch_failures": 0,
              "per_axis": {}}
    try:
        for axis in targets:
            wrote = 0
            for kind, url, parse in _endpoints_for(axis, rss, arx):
                raw = get(url)
                if raw is None:
                    report["fetch_failures"] += 1
                    continue
                for item in parse(raw):
                    try:
                        if write_row(conn, item.get("source") or kind,
                                     item.get("url", ""), item.get("title", ""),
                                     item.get("raw_text", ""), axis):
                            wrote += 1
                            report["written"] += 1
                        else:
                            report["duplicates"] += 1
                    except LinkRequired:
                        # Counted, never stored. An endpoint that returns
                        # linkless items is a fact about that endpoint.
                        report["refused_no_url"] += 1
            report["per_axis"][axis] = wrote
    finally:
        conn.close()
    report["finished"] = utc_now()
    return report


def _endpoints_for(axis: str, rss: dict, arx: dict) -> list:
    out = []
    feed = rss.get(axis)
    if feed:
        out.append(("RSS", feed, parse_rss))
    cat = arx.get(axis)
    if cat:
        out.append(("arXiv",
                    "https://export.arxiv.org/api/query?search_query=cat:{}"
                    "&max_results=8&sortBy=submittedDate&sortOrder=descending".format(cat),
                    parse_arxiv))
    # GDELT keyed off the axis name, which is what internet_agent does today.
    out.append(("GDELT",
                "https://api.gdeltproject.org/api/v2/doc/doc?query={}"
                "&mode=artlist&maxrecords=8&format=json".format(
                    urllib.parse.quote(axis.replace("_REVIEW", "").replace("_", " ").lower())),
                parse_gdelt))
    return out


# ---------------------------------------------------------------------------
# schtasks — PRINTED, never registered
# ---------------------------------------------------------------------------

def schtasks_lines() -> str:
    python = BASE / "venv" / "Scripts" / "python.exe"
    script = BASE / "scripts" / "intel_daemon.py"
    return "\n".join([
        "REM Register the cold shell to fetch every {}h. Run in an ADMIN shell.".format(
            RUN_EVERY_HOURS),
        "REM Nothing below has been executed — this command only prints it.",
        "",
        'schtasks /Create /TN "{}" /TR "\\"{}\\" \\"{}\\" --run" '
        "/SC HOURLY /MO {} /RL LIMITED /F".format(
            TASK_NAME, python, script, RUN_EVERY_HOURS),
        "",
        "REM check    schtasks /Query  /TN \"{}\" /V /FO LIST".format(TASK_NAME),
        "REM fire now schtasks /Run    /TN \"{}\"".format(TASK_NAME),
        "REM remove   schtasks /Delete /TN \"{}\" /F".format(TASK_NAME),
    ])


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("scripts/intel_daemon.py --selftest")
    print("  repo base            {}".format(BASE))
    print("  db                   {}  exists={}".format(DB_PATH, DB_PATH.exists()))
    print("  caps                 max_content={}B  stream_timeout={}s  "
          "(hardcoded, no override)".format(MAX_CONTENT_BYTES, STREAM_TIMEOUT_SEC))
    ok = True

    try:
        tbl = source_table()
        print("  source table         LIVE ({} RSS feeds, {} arXiv categories, "
              "read by AST from internet_agent.py)".format(
                  len(tbl["RSS_FEEDS"]), len(tbl["ARXIV_CATEGORIES"])))
    except RuntimeError as e:
        print("  source table         INERT ({})".format(e))
        ok = False

    if DB_PATH.exists():
        conn = connect()
        try:
            s = stats(conn)
            print("  rows                 {} (first={} last={})".format(
                s["rows"], s["first"], s["last"]))
            for axis, n in list(s["by_axis"].items())[:5]:
                print("    {:<38} {}".format(axis, n))
        finally:
            conn.close()
    else:
        print("  rows                 (no database yet — run with --run)")

    # The wiring question, answered honestly.
    try:
        agent = (BASE / "agents" / "internet" / "internet_agent.py").read_text(
            encoding="utf-8", errors="replace")
        runner = (BASE / "fast_cycle_runner.py").read_text(
            encoding="utf-8", errors="replace")
        wired = "intel_daemon" in agent or "intel_daemon" in runner
    except OSError:
        wired = False
    print("  internet_intelligence {}".format(
        "WIRED" if wired else
        "NOT WIRED — the step still fetches from the network itself; "
        "this daemon writes rows nobody reads yet"))

    try:
        import subprocess
        q = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                           capture_output=True, text=True, timeout=20)
        print("  scheduled task       {}".format(
            "REGISTERED" if q.returncode == 0 else
            "not registered (expected — see --schtasks)"))
    except Exception:
        print("  scheduled task       could not query schtasks")

    # Offline smoke: the whole path with a stubbed getter and a temp db.
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="intel_selftest_")) / "intel.db"
    feed = (b"<rss><channel><item><title>T</title><description>D</description>"
            b"<link>https://example.org/a</link></item></channel></rss>")
    rep = run_once(axes=["SELFTEST_AXIS"], db_path=tmp, getter=lambda u: feed,
                   table={"RSS_FEEDS": {"SELFTEST_AXIS": "https://x/rss"},
                          "ARXIV_CATEGORIES": {}})
    print("  offline smoke        wrote={} duplicates={} refused_no_url={} "
          "fetch_failures={}".format(rep["written"], rep["duplicates"],
                                     rep["refused_no_url"], rep["fetch_failures"]))
    conn = connect(tmp)
    try:
        assert len(fresh_since(conn, "1970-01-01")) == rep["written"]
        try:
            write_row(conn, "x", "", "no link")
            print("  link-required        BROKEN — a linkless row was accepted")
            ok = False
        except LinkRequired:
            print("  link-required        enforced")
        try:
            conn.execute("DELETE FROM intel")
            print("  append-only          BROKEN — DELETE succeeded")
            ok = False
        except sqlite3.DatabaseError:
            print("  append-only          enforced by the database")
    finally:
        conn.close()
    return 0 if ok else 1


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="CORTEX cold shell — fetch only.")
    p.add_argument("--run", action="store_true", help="do one fetch pass")
    p.add_argument("--axis", action="append", help="limit to this axis (repeatable)")
    p.add_argument("--since-hours", type=float, help="print rows newer than this")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--schtasks", action="store_true",
                   help="PRINT the registration commands (does not register)")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.schtasks:
        print(schtasks_lines())
        return 0
    if args.stats:
        conn = connect()
        try:
            print(json.dumps(stats(conn), ensure_ascii=False, indent=2))
        finally:
            conn.close()
        return 0
    if args.since_hours is not None:
        conn = connect()
        try:
            rows = fresh_within_hours(conn, args.since_hours)
            print(json.dumps(rows, ensure_ascii=False, indent=2)[:20000])
            print("({} rows)".format(len(rows)))
        finally:
            conn.close()
        return 0
    if args.run:
        t0 = time.monotonic()
        rep = run_once(axes=args.axis)
        rep["wall_sec"] = round(time.monotonic() - t0, 1)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
