#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/collector_memory.py — the memory the collecting loop never had.

THE FIXED POINT (memory/collector_runs.jsonl, 31 Jul - 3 Aug 2026)
------------------------------------------------------------------
12 scheduled runs over 3 days. ONE axis every time. TWO distinct queries, one of which
was used 10 runs running. 34 page reads over 11 distinct URLs — the same four marketing
blogs read and rejected eight times each. Every run cost a browser session and a handful
of local-model votes to rediscover, from scratch, exactly what the previous run had
already rejected.

Nothing in the loop was broken in the sense of raising. Each individual piece behaved
correctly. The loop had no memory, so it had no way to be anywhere but where it started:

  axis   need_from_composer() returned the FIRST slot_unfilled in JSON key order.
         21 axes were hungry. SOCIAL_RELATIONS_REVIEW is simply first in the file.
  query  decide() is a temperature-0.1 model call over a constant prompt. Same input,
         same output, forever.
  pages  no record of what had been read, so the same search returned the same pages
         and every one was re-fetched and re-judged.

Three memories, one file each, and a rotation cursor:

  memory/collector_seen.json      {url: {axis, need_class, last_read, verdict, content_hash}}
  memory/collector_queries.json   per axis+need_class: which queries were tried, what they yielded
  memory/collector_rotation.json  per axis: consecutive dry runs, last run, and the cursor

INSTRUMENTATION, AND WHY IT IS NOT OPTIONAL
-------------------------------------------
weekly() reports distinct_urls_tried, distinct_queries and axes_touched NEXT TO the
decline rate, and they must be published together. A decline rate on its own cannot
distinguish honest discipline from a stuck loop: a guard that reads ten good pages and
rejects nine looks exactly like a loop that reads the same rejected page nine times.
Both report 90%. The first is the system working; the second is the system asleep with
its eyes open. Only the breadth counters tell them apart.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

CONFIG_FILE   = REPO / "config" / "collector.json"
SEEN_FILE     = REPO / "memory" / "collector_seen.json"
QUERIES_FILE  = REPO / "memory" / "collector_queries.json"
ROTATION_FILE = REPO / "memory" / "collector_rotation.json"
RUNS_LOG      = REPO / "memory" / "collector_runs.jsonl"
INSTRUMENT    = REPO / "memory" / "collector_instrumentation.json"

DEFAULTS = {
    "seen_ttl_days": 14,
    "hash_probe": True,
    "hash_probe_timeout_s": 12,
    "max_query_attempts": 3,
    "dry_runs_before_rotation": 3,
}

QUERY_EXHAUSTED = "query space exhausted for this need"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


def _load(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, obj) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        pass


def cfg() -> dict:
    out = dict(DEFAULTS)
    for k, v in (_load(CONFIG_FILE, {}) or {}).items():
        if not k.startswith("_") and k in DEFAULTS:
            out[k] = v
    return out


def _age_days(iso_str) -> float | None:
    try:
        return (_now() - datetime.fromisoformat(iso_str)).total_seconds() / 86400.0
    except Exception:
        return None


def _key(axis: str, need_class) -> str:
    return f"{axis}|{need_class or '*'}"


# ── seen memory ──────────────────────────────────────────────────────────────

def content_hash(text: str) -> str:
    """Whitespace-normalised so a re-rendered page with the same words hashes the same.
    A page that only changed its ad slots has not changed its evidence."""
    norm = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def remember(url: str, axis: str, need_class, verdict: str, text: str = "",
             seen_path: Path = None) -> None:
    """Record what this URL turned out to be worth, for this axis and this need class."""
    path = Path(seen_path or SEEN_FILE)
    doc = _load(path, {})
    doc[url] = {"axis": axis, "need_class": need_class, "last_read": _iso(),
                "verdict": verdict, "content_hash": content_hash(text) if text else None}
    _save(path, doc)


def _probe_hash(url: str, timeout: int):
    """One plain GET, no browser, no model. Returns a hash or None if it could not be read."""
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 CORTEX-collector-probe"})
        r.raise_for_status()
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
        return content_hash(re.sub(r"<[^>]+>", " ", txt))
    except Exception:
        return None


def should_skip(url: str, axis: str, need_class, seen_path: Path = None,
                probe=None, config: dict = None) -> tuple:
    """(skip, reason). Skip only when ALL of these hold:

      * we have read this exact URL before, for THIS axis and THIS need class
      * we rejected it then
      * that was less than seen_ttl_days ago
      * and its content has not changed since

    Anything else is a read. The TTL is the outer gate on purpose: past it the record is
    stale and the page is read again whatever its hash says, because the world moves and
    a permanent skip is just a blacklist with better manners.
    """
    conf = config or cfg()
    rec = (_load(Path(seen_path or SEEN_FILE), {}) or {}).get(url)
    if not rec:
        return False, "never read"
    if rec.get("axis") != axis or rec.get("need_class") != need_class:
        return False, (f"read before for {rec.get('axis')}/{rec.get('need_class')}, "
                       f"not for {axis}/{need_class}")
    if rec.get("verdict") != "rejected":
        return False, f"previous verdict was {rec.get('verdict')!r}, not a rejection"
    age = _age_days(rec.get("last_read"))
    if age is None or age >= float(conf["seen_ttl_days"]):
        return False, f"last read {age}d ago — past the {conf['seen_ttl_days']}d window"
    old = rec.get("content_hash")
    if old and conf.get("hash_probe"):
        probe = probe or (lambda u: _probe_hash(u, int(conf["hash_probe_timeout_s"])))
        new = probe(url)
        if new and new != old:
            return False, "content changed since it was rejected — re-reading"
        if new is None:
            return True, (f"rejected {age:.1f}d ago for {axis}/{need_class}; the change "
                          f"probe could not read it, so the skip stands")
    return True, f"rejected {age:.1f}d ago for {axis}/{need_class}, unchanged"


# ── query history ────────────────────────────────────────────────────────────

def query_history(axis: str, need_class, queries_path: Path = None) -> dict:
    doc = _load(Path(queries_path or QUERIES_FILE), {})
    return (doc.get(_key(axis, need_class)) or {}).get("queries", {})


def dry_queries(axis: str, need_class, queries_path: Path = None) -> list:
    """Queries that have been tried and produced NOTHING. These may not be reused: a
    zero-yield query is not a coin that lands differently on the next toss — the engine
    index and the model prompt are both unchanged."""
    hist = query_history(axis, need_class, queries_path)
    return sorted(q for q, v in hist.items() if not (v or {}).get("components"))


def prior_queries(axis: str, need_class, queries_path: Path = None) -> list:
    return sorted(query_history(axis, need_class, queries_path))


def record_query(axis: str, need_class, query: str, components: int,
                 queries_path: Path = None) -> None:
    path = Path(queries_path or QUERIES_FILE)
    doc = _load(path, {})
    k = _key(axis, need_class)
    entry = doc.setdefault(k, {"queries": {}})
    q = entry["queries"].setdefault(str(query), {"attempts": 0, "components": 0})
    q["attempts"] += 1
    q["components"] = max(int(q.get("components") or 0), int(components or 0))
    q["last_ts"] = _iso()
    _save(path, doc)


def choose_query(axis, need_class, propose, config: dict = None,
                 queries_path: Path = None) -> tuple:
    """(query, attempts, refusal). `propose(prior)` returns a candidate query.

    Refuses rather than repeats. After max_query_attempts the run ends with a NAMED
    refusal — "query space exhausted for this need" — which is a fact about the search,
    not a silent zero that reads as "the world had no signal today"."""
    conf = config or cfg()
    banned = set(dry_queries(axis, need_class, queries_path))
    tried = []
    for _ in range(int(conf["max_query_attempts"])):
        q = (propose(sorted(banned | set(tried))) or "").strip()
        if q and q not in banned and q not in tried:
            return q, tried, None
        if q:
            tried.append(q)
    return None, tried, (f"{QUERY_EXHAUSTED}: {len(tried)} attempt(s) all returned a query "
                         f"already known to yield nothing for {axis}/{need_class or '*'}")


# ── axis rotation ────────────────────────────────────────────────────────────

def hungry_axes(needs_doc: dict) -> list:
    """Every axis declaring an unfilled slot, in the order the file states them. The bug
    was never this list — it was taking [0] of it and calling that a decision."""
    out = []
    for axis, entry in (needs_doc or {}).items():
        for it in (entry or {}).get("items", []):
            if it.get("kind") == "slot_unfilled":
                out.append((axis, it))
                break
    return out


def pick_axis(needs_doc: dict, config: dict = None, rotation_path: Path = None) -> tuple:
    """(axis, item, note). Round-robin over the hungry axes, skipping any that has gone
    dry K times running — its turn passes to the next one that has not.

    STARVATION IS NOT A FIX FOR REPETITION. When every hungry axis is over its dry limit
    the loop does not stop sensing; the axis that has waited longest goes anyway and its
    counter is cleared. Otherwise a bad week would silently switch the eye off."""
    conf = config or cfg()
    path = Path(rotation_path or ROTATION_FILE)
    state = _load(path, {"cursor": None, "axes": {}})
    axes = state.setdefault("axes", {})
    hungry = hungry_axes(needs_doc)
    if not hungry:
        return None, None, "no axis declares an unfilled slot"

    names = [a for a, _it in hungry]
    limit = int(conf["dry_runs_before_rotation"])
    start = (names.index(state["cursor"]) + 1) if state.get("cursor") in names else 0
    order = names[start:] + names[:start]

    chosen, note = None, ""
    for a in order:
        if int((axes.get(a) or {}).get("dry_runs", 0)) < limit:
            chosen = a
            skipped = [x for x in order[:order.index(a)]]
            note = (f"round-robin from {state.get('cursor') or '(start)'}"
                    + (f"; skipped {skipped} — {limit} dry runs each" if skipped else ""))
            break
    if chosen is None:
        # everyone is over the limit: the one that has waited longest goes, and starts fresh
        def _waited(a):
            return _age_days((axes.get(a) or {}).get("last_run")) or 1e9
        chosen = max(names, key=_waited)
        axes.setdefault(chosen, {})["dry_runs"] = 0
        note = (f"every hungry axis is over {limit} dry runs; {chosen} has waited longest "
                f"and goes anyway — a dry spell must not switch the eye off")

    state["cursor"] = chosen
    _save(path, state)
    item = dict(hungry)[chosen]
    return chosen, item, note


def record_run(axis: str, components: int, rotation_path: Path = None) -> dict:
    """A run that produced nothing is a DRY run and is counted as one. A run that produced
    a component clears the count — the axis is evidently still yielding."""
    path = Path(rotation_path or ROTATION_FILE)
    state = _load(path, {"cursor": None, "axes": {}})
    a = state.setdefault("axes", {}).setdefault(axis, {"dry_runs": 0})
    a["dry_runs"] = 0 if int(components or 0) > 0 else int(a.get("dry_runs", 0)) + 1
    a["last_run"] = _iso()
    a["last_components"] = int(components or 0)
    _save(path, state)
    return a


# ── instrumentation ──────────────────────────────────────────────────────────

def weekly(days: int = 7, runs_log: Path = None) -> dict:
    """Breadth counters BESIDE the decline rate, never instead of it.

    A decline rate alone cannot tell honest discipline from a stuck loop. Reading ten
    fresh pages and rejecting nine, and reading the same rejected page nine times, both
    report 90%. distinct_urls_tried, distinct_queries and axes_touched are what separate
    them, which is why they are computed here and published together."""
    cutoff = _now() - timedelta(days=days)
    rows = []
    try:
        for line in Path(runs_log or RUNS_LOG).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(str(r.get("ts")))
            except Exception:
                continue
            if ts >= cutoff:
                rows.append(r)
    except Exception:
        pass

    urls, queries, axes = set(), set(), set()
    accepted = declined = pages = skipped = 0
    for r in rows:
        if r.get("axis"):
            axes.add(r["axis"])
        for q in (r.get("search_query"), r.get("query_used")):
            if q and q not in ("(given urls)", "(pages supplied)"):
                queries.add(str(q))
        for c in (r.get("components") or []):
            urls.add(c.get("url"))
            accepted += 1
        for c in (r.get("rejected") or []):
            urls.add(c.get("url"))
            declined += 1
        for s in (r.get("seen_skipped") or []):
            urls.add(s.get("url") if isinstance(s, dict) else s)
            skipped += 1
        pages += int(r.get("pages_read") or 0)

    judged = accepted + declined
    return {
        "ts": _iso(), "window_days": days, "runs": len(rows),
        "distinct_urls_tried": len([u for u in urls if u]),
        "distinct_queries": len(queries),
        "axes_touched": sorted(axes),
        "n_axes_touched": len(axes),
        "pages_read": pages,
        "seen_skipped": skipped,
        "components_accepted": accepted,
        "components_declined": declined,
        "decline_rate": round(declined / judged, 3) if judged else None,
        "reading_note": "decline_rate alone cannot distinguish an honest guard from a "
                        "stuck loop — read it only together with distinct_urls_tried, "
                        "distinct_queries and axes_touched",
    }


def publish_weekly(days: int = 7, runs_log: Path = None, out: Path = None) -> dict:
    rep = weekly(days, runs_log)
    _save(Path(out or INSTRUMENT), rep)
    return rep


if __name__ == "__main__":
    print(json.dumps(publish_weekly(), ensure_ascii=False, indent=2))
