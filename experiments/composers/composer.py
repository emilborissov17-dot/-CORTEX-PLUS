#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/composers/composer.py — per-axis indicator composer.

WHAT THIS IS (plain, no inflation): a small engine that stitches one axis
indicator from a PORTFOLIO of sources — a slow official anchor plus daily-moving
proxies — and reports: composed values, agreement (do proxies confirm or
contradict the anchor's direction), confidence, and NEEDS (what the portfolio
is missing). It is plumbing between raw data and analysis. It is not a mind.

DIVERSIFICATION BY RULE, NOT BY LIST
------------------------------------
config/composer_specs.json declares SLOTS by source CLASS
(anchor_annual / measurement_daily / event_daily / indirect_proxy) with minimum
counts. Sources fill slots. Self-discovered sources (data_scout) appear as
candidates; a human promotes one with --promote, which EDITS THE SPEC (a
reviewable git diff), supplying the parsing rule. An unfilled slot is never
silent: it lowers confidence and emits a NEED record the human sees.
Diversity is counted as distinct organisations across filled slots.

FALLBACK RULES (graded degradation, never silent staleness)
-----------------------------------------------------------
- reserves inside a slot: priority order; first live-and-fresh source is used
- cache TTL: a source fetched OK within TTL_H is not re-fetched (rate-limit discipline)
- backoff: a source that just failed is not hammered again within BACKOFF_H
- last-known-good with LOUD ageing: every value carries its age; past
  freshness_days it is EXCLUDED and a stale NEED is emitted
- data-date check: a source may declare where its own measurement date lives
  (data_date_extract); data older than data_max_age_days is refused even if
  the file itself was read a second ago — a reserve may not serve old data as fresh
- death: DEATH_AT consecutive failures -> source dead + NEED for a replacement
- fail-loud: an empty slot produces NO fabricated number — only lower confidence
  and a NEED record

Outputs (runtime files, not committed):
  memory/composer_state/<AXIS>.json   per-source state incl. value history
  memory/composer_needs.json          the NEED queue (what the organism lacks)
  memory/composed_indicators.json     last composed report per axis

Usage:
  python experiments/composers/composer.py --run CLIMATE_GLOBAL_RISK_REVIEW [--force]
  python experiments/composers/composer.py --needs
  python experiments/composers/composer.py --promote AXIS --url U --slot S \
      --kind http_csv --col 3 --org ORG      # human-gated: writes the spec
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import provenance as prov      # origin + reporter independence (derived, never scored)
import readers                 # deterministic parsers for json_rows / jsonstat / sdmx

REPO = HERE.parents[1]

SPEC_FILE  = REPO / "config" / "composer_specs.json"
STATE_DIR  = REPO / "memory" / "composer_state"
NEEDS_FILE = REPO / "memory" / "composer_needs.json"
OUT_FILE   = REPO / "memory" / "composed_indicators.json"
DISCOVERED = REPO / "memory" / "discovered_data_sources.json"

TTL_H       = 20   # fetched-OK within this window -> reuse, no re-fetch
BACKOFF_H   = 1    # failed within this window -> do not hammer again
DEATH_AT    = 3    # consecutive HARD failures -> dead + NEED
THROTTLE_H  = 0.25 # rate-limited within this window -> wait; NEVER counts toward death


class RateLimited(RuntimeError):
    """A 429 / provider throttle. Transient, NOT a dead source — the source is fine,
    we just asked too often. Must back off WITHOUT counting toward DEATH_AT, or a
    daily feed like GDELT (limit: 1 req / 5s) gets wrongly killed and the moving
    signal on the DYNAMIC axes disappears. (Diagnosed live 30 Jul 2026: GDELT returns
    either HTTP 429 or a 200 body 'Please limit requests to one every 5 seconds'.)"""


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).isoformat()


def _age_h(iso_str):
    try:
        return (_now() - datetime.fromisoformat(iso_str)).total_seconds() / 3600.0
    except Exception:
        return None


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _dotted(d, path):
    """Walk a dotted path. An integer part indexes a LIST ('daily.time.-1'), so the
    array-shaped APIs that most open feeds return (open-meteo, EONET, USGS) are reachable
    without a bespoke parser per provider. Dict-only paths behave exactly as before.

    An EMPTY path is the document itself. Some feeds answer with a bare top-level array
    and nothing to address it by — Celestrak's satellite catalogue is one — and without
    this, `"".split(".")` yielded [""] and int("") raised, so the whole payload was
    unreachable and the source unusable."""
    if path is None or str(path) == "":
        return d
    cur = d
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _http(url, timeout=15):
    """Fetch text. Prefers `requests` — the library the nightly cycle already uses
    SUCCESSFULLY against these same domains (NOAA/GDELT/WB). On this Windows box
    urllib hits a proxy tunnel 403 for some domains while requests gets through
    (diagnosed 30 Jul 2026 from composer_state last_error). urllib is the fallback."""
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "CORTEX-composer/1.0"})
        if r.status_code == 429:
            raise RateLimited("HTTP 429")
        r.raise_for_status()
        # some providers (GDELT) answer 200 with a plaintext throttle notice instead
        low = r.text[:200].lower()
        if "please limit requests" in low or "rate limit" in low:
            raise RateLimited("provider throttle notice")
        return r.text
    except ImportError:
        req = urllib.request.Request(url, headers={"User-Agent": "CORTEX-composer/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")


# ── CSV addressing: which row, which column ──────────────────────────────────
#
# PANEL DATA BREAKS "THE LAST ROW". An OWID grapher CSV with csvType=filtered is
# entity x year: 195 rows, one per country, latest year each. Reading the last row of that
# is reading whichever country happens to sort last — Zimbabwe's water stress reported as
# the world's. The number would be real, correctly parsed, correctly hashed, and about the
# wrong thing entirely: layer 4 (does the number measure what we think) failing while
# every other layer passes.
#
# So a source may name its row. row_key_column (default "entity") + row_key selects it, and
# column_name resolves the column by header rather than by a positional index that shifts
# the day the provider inserts a column.
#
# AND IT FAILS LOUDLY. If the key matches no row, this raises with the key named and a
# sample of what WAS there. It never falls back to the last row: a silent fallback would
# turn "the entity I asked for is gone" into "here is a number", which is the exact shape
# of the failure this whole pack exists to remove.

class CsvRowNotFound(readers.RowNotFound):
    """A named row was asked for and the payload does not contain it.

    Shares a base with the json_rows / jsonstat / sdmx failures because they are the same
    fact in four dialects: an address was declared and the payload does not hold it."""


def _csv_rows(text: str):
    return [l for l in str(text).splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


def _csv_cells(line: str):
    # TAB is a first-class delimiter: USGS NWIS serves its daily-values feed as RDB
    # (tab-separated), and without this every USGS row parses as a single cell.
    return [c.strip() for c in line.replace("\t", ",").replace(";", ",").split(",")]


def _csv_header(text: str):
    rows = _csv_rows(text)
    if not rows:
        return []
    head = _csv_cells(rows[0])
    return [] if all(_is_number(c) for c in head) else head


def _csv_col(src: dict, text: str) -> int:
    """The column index to read: by header name when one is declared, else by index."""
    name = src.get("column_name")
    if name:
        header = _csv_header(text)
        if name not in header:
            raise CsvRowNotFound(
                f"csv: column_name {name!r} is not in the header {header[:8]}"
                f"{'...' if len(header) > 8 else ''} — the provider renamed or dropped it")
        return header.index(name)
    return int(src.get("col", -1))


def _csv_select(src: dict, text: str) -> tuple:
    """(cells, data_date) for the row this source is about."""
    rows = _csv_rows(text)
    if not rows:
        raise ValueError("csv: no data rows in the payload")
    header = _csv_header(text)
    body = rows[1:] if header else rows

    key = src.get("row_key")
    if key is None:
        cells = _csv_cells(rows[-1])          # unchanged behaviour for single-series feeds
    else:
        key_col_name = src.get("row_key_column", "entity")
        if not header:
            raise CsvRowNotFound(f"csv: row_key {key!r} was asked for but the payload has "
                                 f"no header row to find {key_col_name!r} in")
        if key_col_name not in header:
            raise CsvRowNotFound(f"csv: row_key_column {key_col_name!r} is not in the "
                                 f"header {header[:8]}")
        ki = header.index(key_col_name)
        hit = None
        for line in body:
            c = _csv_cells(line)
            if ki < len(c) and c[ki] == str(key):
                hit = c                        # LAST match wins: panels are entity x year
        if hit is None:
            seen = []
            for line in body[:400]:
                c = _csv_cells(line)
                if ki < len(c) and c[ki] not in seen:
                    seen.append(c[ki])
            raise CsvRowNotFound(
                f"csv: no row where {key_col_name}=={key!r} among {len(body)} row(s). "
                f"Present keys include {seen[:6]}. Refusing to read a different row — "
                f"a fallback here would answer a question nobody asked")
        cells = hit

    if src.get("data_date_col") is not None:
        data_date = cells[int(src["data_date_col"])]
    elif src.get("data_date_column") and header and src["data_date_column"] in header:
        data_date = cells[header.index(src["data_date_column"])]
    else:
        data_date = None
    return cells, data_date


# ── fetch kinds ───────────────────────────────────────────────────────────────

def fetch(src, return_payload: bool = False) -> tuple:
    """Returns (value: float, data_date: str|None) — or (value, data_date, payload) when
    return_payload is set. Raises on any failure.

    The payload is handed back so a DETERMINISTIC source's schema can be checked against
    the exact bytes the value came from, without a second request."""
    kind = src.get("kind")
    data_date = None
    if kind == "file":
        data = json.loads((REPO / src["path"]).read_text(encoding="utf-8"))
        v = _dotted(data, src["extract"])
        if src.get("data_date_extract"):
            data_date = _dotted(data, src["data_date_extract"])
        return (float(v), data_date, data) if return_payload else (float(v), data_date)
    if kind == "http_json_path":
        data = json.loads(_http(src["url"]))
        v = float(_dotted(data, src["extract"]))
        return (v, None, data) if return_payload else (v, None)
    if kind == "http_csv":
        text = _http(src["url"])
        cells, data_date = _csv_select(src, text)
        v = float(cells[_csv_col(src, text)])
        return (v, data_date, text) if return_payload else (v, data_date)
    if kind == "http_json_count":
        # The measurement IS the number of dated events (EONET categories, USGS feeds).
        data = json.loads(_http(src["url"]))
        arr = _dotted(data, src["extract"])
        if not isinstance(arr, list):
            raise ValueError(f"json_count: '{src['extract']}' is not a list")
        v = float(len(arr))
        return (v, None, data) if return_payload else (v, None)
    if kind == "http_json_series":
        # Daily series APIs answer with parallel arrays {"daily":{"time":[...],"x":[...]}}.
        # Take the last NON-NULL value — forecast arrays carry trailing nulls for variables
        # the model does not supply, and a null tail must not read as a missing source.
        data = json.loads(_http(src["url"]))
        arr = _dotted(data, src["extract"])
        if not isinstance(arr, list):
            raise ValueError(f"json_series: '{src['extract']}' is not a list")
        idx = next((i for i in range(len(arr) - 1, -1, -1) if arr[i] is not None), None)
        if idx is None:
            raise ValueError("json_series: every value in the series is null")
        if src.get("data_date_extract"):
            dates = _dotted(data, src["data_date_extract"])
            if isinstance(dates, list) and idx < len(dates):
                data_date = dates[idx]   # the date OF the value used, not of the request
        v = float(arr[idx])
        return (v, data_date, data) if return_payload else (v, data_date)
    if kind == "http_gdelt_tone":
        data = json.loads(_http(src["url"]))
        series = (data.get("timeline") or [{}])[0].get("data") or []
        vals = [float(p["value"]) for p in series[-7:] if "value" in p]
        if not vals:
            raise ValueError("gdelt: empty tone series")
        v = round(sum(vals) / len(vals), 4)
        return (v, None, data) if return_payload else (v, None)
    # The three official-statistics families. Each is a DECLARED address into a payload —
    # a row key, a dimension cell, a series key — resolved by experiments/composers/
    # readers.py with no model anywhere in the path, and raising rather than substituting
    # when the address matches nothing.
    if kind in ("http_json_rows", "http_jsonstat", "http_sdmx"):
        data = json.loads(_http(src["url"], timeout=int(src.get("timeout", 30))))
        reader = {"http_json_rows": readers.read_json_rows,
                  "http_jsonstat": readers.read_jsonstat,
                  "http_sdmx": readers.read_sdmx}[kind]
        v, dd = reader(data, src)
        return (float(v), dd, data) if return_payload else (float(v), dd)
    raise ValueError(f"unknown source kind: {kind}")


# ── deterministic feeds: no model in the read path, and no silent adaptation ──
#
# THE CARVE-OUT AND ITS CONDITIONS, encoded rather than described.
#
# A deterministic feed skips nothing and is granted nothing. It routes through the SAME
# slot architecture, competes for the SAME slots against browsed sources, and still
# requires a human to promote it. What it gets is the right to be trusted without a model
# in the read path, and what it pays for that is a schema contract with no forgiveness:
#
#   STRUCTURED KINDS ONLY   a value must be reachable by a declared path or column. If
#                           reading it needs a model to interpret prose, it is not this.
#   SCHEMA VIOLATION KILLS  at ONE failure, not three. DEATH_AT exists for flaky networks;
#                           a feed that changed shape is not flaky, it is a different feed,
#                           and three more cycles of reading it would be three cycles of
#                           reading something else under the old name. An added field is as
#                           fatal as a dropped one: both mean the contract we validated is
#                           not the contract we are now reading.
#   NO SPECIAL PLEADING     same slots, same min counts, same freshness, same promotion.
DETERMINISTIC_KINDS = ("http_json_path", "http_csv", "http_json_series", "file",
                       # the official-statistics families: a declared address into a
                       # structured payload, resolved with no model in the path
                       "http_json_rows", "http_jsonstat", "http_sdmx")


def schema_fingerprint(kind: str, payload) -> dict:
    """The shape of a payload, in the terms its kind is read in."""
    if kind == "http_csv":
        rows = [l for l in str(payload).splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        if not rows:
            return {"type": "csv", "n_cols": 0, "header": None}
        head = rows[0].replace("\t", ",").replace(";", ",").split(",")
        last = rows[-1].replace("\t", ",").replace(";", ",").split(",")
        numeric_head = all(_is_number(c) for c in head)
        return {"type": "csv", "n_cols": len(last),
                "header": None if numeric_head else [c.strip() for c in head]}
    if isinstance(payload, dict):
        return {"type": "dict", "keys": sorted(map(str, payload.keys()))}
    if isinstance(payload, list):
        first = payload[0] if payload else None
        if isinstance(first, dict):
            return {"type": "list", "element_keys": sorted(map(str, first.keys()))}
        return {"type": "list", "element_keys": None}
    return {"type": type(payload).__name__}


def _is_number(cell) -> bool:
    try:
        float(str(cell).strip())
        return True
    except (TypeError, ValueError):
        return False


def schema_diff(expected: dict, actual: dict) -> str:
    """A named difference, or "" when the shape still matches."""
    if not expected:
        return ""
    if expected.get("type") != actual.get("type"):
        return f"payload type changed: {expected.get('type')} -> {actual.get('type')}"
    for field in ("keys", "element_keys", "header"):
        exp, act = expected.get(field), actual.get(field)
        if exp is None and act is None:
            continue
        if exp is None or act is None:
            return f"{field} appeared/disappeared: {exp!r} -> {act!r}"
        gone, new = sorted(set(exp) - set(act)), sorted(set(act) - set(exp))
        if gone or new:
            return (f"{field} changed"
                    + (f"; dropped {gone}" if gone else "")
                    + (f"; unexpected {new}" if new else ""))
    if expected.get("type") == "csv" and expected.get("n_cols") != actual.get("n_cols"):
        return f"column count changed: {expected.get('n_cols')} -> {actual.get('n_cols')}"
    return ""


def check_schema(src: dict, payload) -> str:
    """"" when the contract holds, else the named violation."""
    return schema_diff(src.get("schema") or {}, schema_fingerprint(src.get("kind"), payload))


def _data_too_old(data_date: str, max_days: float):
    """True if the source's OWN measurement date is older than max_days."""
    if not data_date:
        return False, None
    try:
        d = datetime.fromisoformat(str(data_date)[:10]).replace(tzinfo=timezone.utc)
        age_d = (_now() - d).total_seconds() / 86400.0
        return age_d > max_days, round(age_d, 1)
    except Exception:
        return False, None


# ── compose one axis ──────────────────────────────────────────────────────────

def compose(axis: str, force: bool = False) -> dict:
    spec = _load(SPEC_FILE, {}).get(axis)
    if not spec:
        return {"error": f"no composer spec for {axis}"}

    state_file = STATE_DIR / f"{axis}.json"
    state = _load(state_file, {"sources": {}})
    S = state["sources"]
    needs, slots_report = [], {}
    filled_orgs, filled_origins = set(), set()
    freshness_factors = []
    rep_cfg = prov.reporter_config()
    declared_sources = [s for sl in spec["portfolio"].values() for s in sl["sources"]]

    for slot_name, slot in spec["portfolio"].items():
        fresh_days = float(slot.get("freshness_days", 30))
        live, live_specs = [], []
        for src in slot["sources"]:
            sid = src["id"]
            st = S.setdefault(sid, {"consecutive_fails": 0, "status": "active", "history": []})
            if st.get("status") == "dead":
                continue
            ok_age = _age_h(st["last_ok_ts"]) if st.get("last_ok_ts") else None
            att_age = _age_h(st["last_attempt_ts"]) if st.get("last_attempt_ts") else None
            use_cache = (not force) and ok_age is not None and ok_age < TTL_H
            in_backoff = (not force) and att_age is not None and att_age < BACKOFF_H \
                and st["consecutive_fails"] > 0
            in_throttle = (not force) and att_age is not None and att_age < THROTTLE_H \
                and st.get("throttled")
            attempted = False
            if not use_cache and not in_backoff and not in_throttle:
                attempted = True
                st["last_attempt_ts"] = _iso()
                try:
                    if src.get("deterministic"):
                        v, data_date, payload = fetch(src, return_payload=True)
                        violation = check_schema(src, payload)
                        if violation:
                            # DEATH AT ONE. DEATH_AT=3 forgives a flaky network; a feed
                            # that changed shape is not flaky, it is a different feed, and
                            # two more cycles of reading it would be two more cycles of
                            # reading something else under the same name.
                            st["status"] = "dead"
                            st["consecutive_fails"] = DEATH_AT
                            st["last_error"] = f"schema violation: {violation}"
                            needs.append({"slot": slot_name, "kind": "schema_violation",
                                          "detail": f"{sid} DIED AT THE FIRST VIOLATION — "
                                                    f"{violation}. A deterministic feed "
                                                    f"contracts to a shape; this is no "
                                                    f"longer that shape, and adapting "
                                                    f"silently is how you end up reading a "
                                                    f"different quantity under the old name"})
                            continue
                    else:
                        v, data_date = fetch(src)
                    too_old, dd_age = _data_too_old(data_date, float(src.get("data_max_age_days", 3650)))
                    if too_old:
                        # the source ANSWERED but its own data is outdated —
                        # refuse it as fresh; do not poison last-known-good
                        st["consecutive_fails"] = 0
                        st["last_error"] = f"data_date {data_date} is {dd_age}d old — refused as current"
                        needs.append({"slot": slot_name, "kind": "stale_value",
                                      "detail": f"{sid}: own data date {data_date} ({dd_age}d old) — refused"})
                        continue
                    st["last_value"] = v
                    st["last_ok_ts"] = _iso()
                    st["consecutive_fails"] = 0
                    st.pop("throttled", None)
                    st.pop("last_error", None)
                    st["history"] = (st.get("history") or [])[-29:] + [[_iso(), v]]
                except RateLimited as e:
                    # transient throttle: wait, keep the source ALIVE, never kill it
                    st["throttled"] = True
                    st["last_error"] = f"rate-limited ({e}) — backing off {THROTTLE_H}h"
                except Exception as e:
                    st["throttled"] = False
                    st["consecutive_fails"] += 1
                    st["last_error"] = f"{type(e).__name__}: {e}"[:140]
                    if st["consecutive_fails"] >= DEATH_AT:
                        st["status"] = "dead"
                        needs.append({"slot": slot_name, "kind": "source_dead",
                                      "detail": f"{sid} dead after {DEATH_AT} consecutive failures "
                                                f"({st['last_error']}) — slot needs a replacement"})
            # usability from last-known-good, with loud ageing
            if st.get("last_ok_ts") and st.get("status") != "dead":
                age_d = (_age_h(st["last_ok_ts"]) or 0.0) / 24.0
                if age_d <= fresh_days:
                    _cls, _why = prov.reporter_class(src, rep_cfg)
                    live.append({"id": sid, "org": src.get("org", "?"),
                                 "origin": prov.origin(src),
                                 "reporter_class": _cls, "reporter_why": _why,
                                 "value": st.get("last_value"), "unit": src.get("unit"),
                                 "age_days": round(age_d, 3), "cached": not attempted})
                    live_specs.append(src)
                else:
                    needs.append({"slot": slot_name, "kind": "stale_value",
                                  "detail": f"{sid} last good value is {age_d:.1f}d old "
                                            f"(> {fresh_days}d) — excluded"})
        # WHICH LIVE SOURCE IS THE PRIMARY.
        #
        # The docstring's rule is "first LIVE-AND-FRESH source is used", and the code only
        # ever honoured the first half: `live` was in spec order, so _slot_primary took
        # whichever was declared first even when it was serving a cached value from weeks
        # ago and a sibling had fetched successfully seconds earlier.
        #
        # Measured 2026-08-03: FOOD_REVIEW's anchor kept reporting gi_undernourishment_pct
        # = 8.5 from last-known-good while its snapshot key had gone None, outranking a UN
        # SDG source that had just returned 28.0. The stale number won on declaration
        # order alone, which is not priority — it is seniority.
        #
        # Sorting by age puts a just-fetched reading first. Python's sort is stable, so
        # among sources of equal age the human's declared priority order is untouched:
        # this only ever demotes a source that is older than its sibling.
        live_order = sorted(range(len(live)), key=lambda i: live[i]["age_days"])
        live = [live[i] for i in live_order]
        live_specs = [live_specs[i] for i in live_order]

        ok = len(live) >= int(slot.get("min", 1))
        status, status_note = prov.slot_status(live_specs, slot.get("min", 1))
        if ok:
            for l in live:
                filled_orgs.add(l["org"])
                filled_origins.add(l["origin"])
            freshness_factors.append(max(0.0, 1.0 - live[0]["age_days"] / fresh_days))
        else:
            needs.append({"slot": slot_name, "kind": "slot_unfilled",
                          "detail": f"needs >= {slot.get('min', 1)} live source(s) of class "
                                    f"'{slot_name}', has {len(live)}"})
        if status == "nominally_filled":
            # the count is met and the redundancy is not real. Said out loud, because
            # "filled" was quietly promising that losing one source would not empty it.
            needs.append({"slot": slot_name, "kind": "slot_nominally_filled",
                          "detail": status_note})
        slots_report[slot_name] = {"filled": ok, "status": status,
                                   "nominally_filled": status == "nominally_filled",
                                   "status_note": status_note,
                                   "origins": sorted({l["origin"] for l in live}),
                                   "live": live}

    n_slots = len(spec["portfolio"])
    n_filled = sum(1 for s in slots_report.values() if s["filled"])
    coverage = n_filled / n_slots if n_slots else 0.0
    # DIVERSITY IS COUNTED OVER ORIGINS, NOT OVER LABELS.
    #
    # This used to be len(filled_orgs)/n_slots — distinct `org` strings, which an LLM wrote
    # at discovery time. 41 of the 43 file-kind sources in the live spec read the SAME file
    # under 15 different org labels, so the old number reported a diversified portfolio
    # standing on one file. The label count is still published below, explicitly named as
    # labels, because it is a real thing about the spec — just not the thing the word
    # "diversity" was being used to claim.
    diversity = min(1.0, len(filled_origins) / n_slots) if n_slots else 0.0
    label_diversity = min(1.0, len(filled_orgs) / n_slots) if n_slots else 0.0
    freshness = (sum(freshness_factors) / len(freshness_factors)) if freshness_factors else 0.0
    confidence = round(0.4 * coverage + 0.3 * diversity + 0.3 * freshness, 3)

    # ── who measured this, and how much of it comes from one place ────────────
    conc = prov.concentration(declared_sources)
    shares = prov.class_shares(declared_sources, rep_cfg)
    if conc["concentrated"]:
        needs.append({"slot": "*", "kind": "origin_concentrated",
                      "detail": f"{int(conc['top_share'] * 100)}% of this axis's "
                                f"{conc['n_sources']} source(s) resolve to ONE origin "
                                f"({conc['top_origin']}) — the portfolio moves when that "
                                f"one moves, whatever the other labels say"})
    if shares["self_reported_only"]:
        needs.append({"slot": "*", "kind": "self_reported_only",
                      "detail": f"every one of this axis's {shares['n_sources']} source(s) "
                                f"is SELF-REPORTED: the measured entity produces the "
                                f"statistic. Not a claim that the number is wrong — a "
                                f"statement that nothing here could notice if it were"})

    # ── composed values (no invented blended unit — anchor unit is kept) ──────
    def _slot_primary(name):
        rep = slots_report.get(name, {})
        return (rep.get("live") or [None])[0]

    anchor = _slot_primary(spec.get("anchor_slot", "anchor_annual"))
    daily = _slot_primary(spec.get("measure_slot", "measurement_daily"))
    # divergence is anchor-vs-daily on the SAME quantity. Subtracting a river's discharge
    # from a percentage, or a bond yield from GDP growth, produces a number that means
    # nothing and then flows into the hash-chained grounding ledger as if it did. So the
    # two sources must declare the same `unit` tag; anything else yields None plus a named
    # reason. FAIL-CLOSED: an undeclared unit is treated as not comparable, never assumed.
    divergence, divergence_note = None, None
    if anchor and daily and isinstance(anchor.get("value"), (int, float)) \
            and isinstance(daily.get("value"), (int, float)):
        au, du = anchor.get("unit"), daily.get("unit")
        if au and du and au == du:
            divergence = round(daily["value"] - anchor["value"], 4)
        else:
            divergence_note = (f"not comparable: anchor unit {au or 'undeclared'} vs daily unit "
                               f"{du or 'undeclared'} — subtraction would be a category error")

    # ── agreement: does each proxy's short-term direction match the anchor's? ──
    anchor_dir = None
    ac = spec.get("anchor_change")
    if ac:
        try:
            v, _ = fetch(ac)
            anchor_dir = "rising" if v > 0 else ("falling" if v < 0 else "flat")
        except Exception:
            anchor_dir = None
    agreement = {"anchor_direction": anchor_dir, "proxies": {}}
    for slot_name, rep in slots_report.items():
        if slot_name == spec.get("anchor_slot"):
            continue
        for l in rep["live"]:
            hist = (S.get(l["id"], {}).get("history") or [])
            if len(hist) >= 2:
                delta = hist[-1][1] - hist[-2][1]
                d = "rising" if delta > 1e-9 else ("falling" if delta < -1e-9 else "flat")
                agreement["proxies"][l["id"]] = {
                    "direction": d, "delta": round(delta, 4),
                    "matches_anchor": (d == anchor_dir) if anchor_dir and d != "flat" else None}
            else:
                agreement["proxies"][l["id"]] = {"direction": "unknown", "note": "needs >=2 observations"}

    # ── candidates the system found itself, awaiting human promotion ──────────
    disc = _load(DISCOVERED, {}).get(axis, {})
    spec_urls = {s.get("url") for sl in spec["portfolio"].values() for s in sl["sources"]}
    candidates = [s for s in disc.get("sources", [])
                  if s.get("status") == "active" and s.get("url") not in spec_urls]
    for c in candidates:
        needs.append({"slot": "?", "kind": "candidate_awaiting_promotion",
                      "detail": f"self-discovered: {c.get('org', '?')} | {c.get('metric', '?')[:50]} | "
                                f"promote with --promote {axis} --url {c.get('url', '')[:60]}..."})

    report = {
        "ts": _iso(), "axis": axis,
        "composed": {"anchor": anchor, "daily": daily, "divergence": divergence,
                     "divergence_note": divergence_note},
        "slots": slots_report, "agreement": agreement,
        "confidence": confidence,
        "confidence_parts": {"coverage": round(coverage, 3),
                             "diversity": round(diversity, 3),
                             "diversity_basis": "distinct ORIGINS across filled slots",
                             "freshness": round(freshness, 3)},
        "label_diversity": {"value": round(label_diversity, 3),
                            "basis": "distinct `org` LABELS, not origins",
                            "note": "published for comparison and deliberately NOT scored: "
                                    "org strings are free text written at discovery and "
                                    "41 of 43 file sources share one origin under 15 labels"},
        "origin_concentration": conc,
        "reporter_independence": shares,
        "unmapped_reporters": prov.unmapped_keys(declared_sources, rep_cfg),
        "needs": needs, "n_candidates": len(candidates),
    }

    _save(state_file, state)
    all_needs = _load(NEEDS_FILE, {})
    # The human's own demands (scripts/cortex_query.py --axis X --force) live in this
    # same file, and this assignment used to REPLACE the axis entry wholesale — so a
    # request queued by Emil was silently deleted here at beat 2.6, long before
    # data_scout read the file at beat 22.5. A queue nobody can write to durably is not
    # a queue. Human items survive the composer's rewrite of its OWN findings; they
    # leave only when the consumer marks them drained.
    kept_human = [i for i in (all_needs.get(axis) or {}).get("items", [])
                  if i.get("kind") == "human_sense_request" and not i.get("consumed")]
    all_needs[axis] = {"ts": _iso(), "items": kept_human + needs}
    _save(NEEDS_FILE, all_needs)
    all_out = _load(OUT_FILE, {})
    all_out[axis] = report
    _save(OUT_FILE, all_out)
    return report


# ── human-gated promotion: a candidate becomes a spec source (git-visible) ────

PROMOTE_FIELDS = ("extract", "col", "column_name", "row_key", "row_key_column",
                  # addresses for the official-statistics readers
                  "cell", "series_key", "where", "timeout",
                  "data_date_col", "data_date_column", "data_date_extract",
                  "data_max_age_days", "provenance", "path", "unit", "origin",
                  "reporter_class", "reporter_class_confirmed_by",
                  # `schema` must travel: without it a DECLARED contract was dropped on
                  # the floor and smoke_fetch happily captured whatever it found, so a
                  # source could be promoted against a shape nobody had validated.
                  "deterministic", "schema")

# WHERE EACH KIND ACTUALLY READS FROM.
#
# This distinction caused a false alarm on 2026-07-31 and is worth stating once, plainly:
# a "file" source is loaded from `path` (see fetch(), kind == "file"), NEVER from `url`.
# A file entry may still carry `url`, and that is not a bug — it is the identity key the
# approval path uses for the stable approve-id, for double-promote dedupe, and for
# matching a promoted source back to its candidate record. On a file entry `url` is a
# REFERENCE, not a location; reading it as a fetch source is the mistake, not its presence.
KIND_LOCATION = {
    "file":              "path",
    "http_json_path":    "url",
    "http_csv":          "url",
    "http_json_count":   "url",
    "http_json_series":  "url",
    "http_gdelt_tone":   "url",
    "http_json_rows":    "url",
    "http_jsonstat":     "url",
    "http_sdmx":         "url",
}


# The PARSING RULE each kind needs on top of its location. A source that declares where
# it lives but not how to read it fails identically on every fetch — which is a fact about
# OUR record, not about the provider, and must never be charged to the provider.
KIND_PARSE_RULE = {
    "file":              ("extract",),
    "http_json_path":    ("extract",),
    "http_json_count":   ("extract",),
    "http_json_series":  ("extract",),
    # either a positional column or a header name — a name survives the provider inserting
    # a column, which an index does not
    "http_csv":          ("col", "column_name"),
    "http_gdelt_tone":   (),          # fixed payload shape, nothing to declare
    # the address into the payload, without which each of these would return SOME row,
    # SOME cell, SOME series — which is the failure they exist to prevent
    "http_json_rows":    ("extract",),
    "http_jsonstat":     ("cell",),
    "http_sdmx":         ("series_key",),
}

# WHY A REFUSAL NEEDS A CLASS.
#
# Until 3 Aug 2026 every failed promotion looked the same to the approval path, so a
# candidate we had registered without a parsing rule was blacklisted exactly like a dead
# URL. Two working providers (OWID, the World Bank) were barred for a field WE had failed
# to compute, having never once been fetched. The class is what separates "our record is
# incomplete" from "this source does not work":
#   schema -> our fault. Discard, complete it, offer it again. NEVER blacklist.
#   fetch  -> the source's fault, and proven so by an actual request. Blacklisting is fair.
FAILURE_SCHEMA = "schema"
FAILURE_FETCH  = "fetch"


class PromotionRejected(ValueError):
    """A promotion refused BEFORE config/composer_specs.json was touched."""
    failure_class = FAILURE_SCHEMA
    reason_code = "incomplete_registration"


class SmokeFetchEmpty(PromotionRejected):
    """It answered, and what came back is not a number."""
    failure_class = FAILURE_FETCH
    reason_code = "no_usable_value"


class StaleData(PromotionRejected):
    """It answered with a real number whose own measurement date is already too old."""
    failure_class = FAILURE_FETCH
    reason_code = "stale_data_date"


_PARSE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError,
                 json.JSONDecodeError, UnicodeDecodeError)


def classify_failure(exc: BaseException) -> tuple:
    """(failure_class, reason_code) — the honest name for why a promotion failed.

    Anything that carries its own class (the PromotionRejected family) states it. Anything
    else is a real request that went wrong, and the only question is HOW: the payload was
    unreadable, or the endpoint never answered."""
    cls = getattr(exc, "failure_class", None)
    if cls:
        return cls, getattr(exc, "reason_code", "unspecified")
    if isinstance(exc, RateLimited):
        return FAILURE_FETCH, "rate_limited"
    if isinstance(exc, FileNotFoundError):
        return FAILURE_FETCH, "dead_url"
    if isinstance(exc, _PARSE_ERRORS):
        return FAILURE_FETCH, "unparseable_payload"
    return FAILURE_FETCH, "dead_url"


def validate_rule(entry: dict) -> bool:
    """Second half of the schema wall: does this entry declare HOW to read what it points
    at? Separate from validate_entry() because the two answer different questions and the
    location check is asserted independently by test/test_promotion_seam.py."""
    kind = entry.get("kind")
    if kind not in KIND_PARSE_RULE:
        raise PromotionRejected(f"unknown kind {kind!r} — promotion rejected")
    fields = KIND_PARSE_RULE[kind]
    if not fields:
        return True
    for field in fields:
        val = entry.get(field)
        if isinstance(val, int) and not isinstance(val, bool):
            return True                  # column 0 is a real column
        if str(val or "").strip():
            return True
    named = " or ".join(repr(f) for f in fields)
    raise PromotionRejected(f"kind={kind} requires {named} (the parsing rule) — "
                            f"promotion rejected")


def validate_entry(entry: dict) -> bool:
    """Schema wall: does this entry declare the location its own kind reads from?

    A source promoted without it is a ghost — it enters the portfolio, raises on every
    fetch, and dies against DEATH_AT three cycles later while the slot has looked filled
    the whole time."""
    kind = entry.get("kind")
    loc = KIND_LOCATION.get(kind)
    if loc is None:
        raise PromotionRejected(f"unknown kind {kind!r} — promotion rejected")
    if not str(entry.get(loc) or "").strip():
        raise PromotionRejected(f"kind={kind} requires {loc!r} — promotion rejected")
    return True


def validate_deterministic(entry: dict) -> bool:
    """The carve-out's structural condition, checked BEFORE anything is fetched.

    It lived inside smoke_fetch at first, which meant a network error preempted it: a
    gdelt source wrongly marked deterministic was refused for being unreachable rather
    than for being the wrong kind, and would have been ACCEPTED the moment the host came
    back. Whether a kind can be read without a model is a fact about the entry, knowable
    with no request at all, so it is settled with no request at all."""
    if not entry.get("deterministic"):
        return True
    if entry.get("kind") not in DETERMINISTIC_KINDS:
        raise PromotionRejected(
            f"deterministic sources must use a structured kind {DETERMINISTIC_KINDS}; "
            f"{entry.get('kind')!r} needs a model in the read path — promotion rejected")
    return True


def smoke_fetch(entry: dict):
    """Fetch this ONE entry with the SAME loader the composer uses, before the spec is
    written. 'Does it actually fetch?' stops being a question anyone has to ask later.

    Note 0.0 is a VALID reading (an event count of zero is a measurement); only a
    non-numeric result counts as empty.

    A source whose own measurement date is already past its declared limit is refused
    here rather than after promotion: the composer would refuse every value it served
    anyway, so promoting it only buys a slot that looks filled and never moves."""
    v, dd, payload = fetch(entry, return_payload=True)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:  # v!=v -> NaN
        raise SmokeFetchEmpty(f"smoke fetch returned no usable value ({v!r}) — "
                              f"promotion rejected")
    too_old, dd_age = _data_too_old(dd, float(entry.get("data_max_age_days", 3650)))
    if too_old:
        raise StaleData(f"smoke fetch read {v}, but its own data date {dd} is {dd_age}d old "
                        f"(limit {entry.get('data_max_age_days')}d) — promotion rejected")
    if entry.get("deterministic"):
        # For a deterministic feed the smoke test IS the schema validation: the shape read
        # here becomes the contract, so there is no window in which the source is trusted
        # without one. A pre-declared schema must MATCH what was just read, or the entry
        # is describing a feed that no longer exists.
        actual = schema_fingerprint(entry.get("kind"), payload)
        if entry.get("schema"):
            drift = schema_diff(entry["schema"], actual)
            if drift:
                raise PromotionRejected(f"declared schema does not match what was fetched: "
                                        f"{drift} — promotion rejected")
        else:
            entry["schema"] = actual
    return v, dd


def promote(axis, url, slot, kind, org, extract=None, col=None, **fields):
    """Human-gated: a candidate becomes a spec source. The PARSING RULE travels with it —
    a promoted source without its extract/col is a source that dies on first fetch and then
    counts toward DEATH_AT, so the approval path must carry these through, not just the URL."""
    specs = _load(SPEC_FILE, {})
    spec = specs.get(axis)
    if not spec or slot not in spec.get("portfolio", {}):
        return {"error": f"axis/slot not in spec: {axis}/{slot}"}
    sid = f"promoted_{abs(hash(url)) % 100000}"
    entry = {"id": sid, "kind": kind, "url": url, "org": org}
    if extract:
        entry["extract"] = extract
    if col is not None:
        entry["col"] = col
    for k in PROMOTE_FIELDS:
        if fields.get(k) is not None:
            entry[k] = fields[k]
    entry.setdefault("provenance", "self-discovered, human-promoted")

    # THREE WALLS, all BEFORE the spec is touched. A rejected promotion must leave no
    # trace: no half-written entry, no source that only fails later. Every refusal carries
    # its CLASS, so the approval path can tell an incomplete record of ours from a source
    # that genuinely does not work — only the second may ever be blacklisted.
    try:
        validate_entry(entry)                       # 1. does it declare its location?
        validate_rule(entry)                        # 2. does it declare how to read it?
        validate_deterministic(entry)               # 3. may it claim the carve-out?
        smoke_value, smoke_date = smoke_fetch(entry)  # 4. does it actually fetch, once?
    except PromotionRejected as e:
        fclass, code = classify_failure(e)
        return {"error": str(e), "rejected": True, "id": sid,
                "failure_class": fclass, "reason_code": code,
                "exception": f"{type(e).__name__}: {e}"}
    except Exception as e:
        # the RAW exception is surfaced: "it didn't work" is not a diagnosis
        fclass, code = classify_failure(e)
        return {"error": f"smoke fetch failed — promotion rejected ({type(e).__name__}: "
                         f"{str(e)[:200]})",
                "rejected": True, "id": sid,
                "failure_class": fclass, "reason_code": code,
                "exception": f"{type(e).__name__}: {e}"}

    spec["portfolio"][slot]["sources"].append(entry)
    _save(SPEC_FILE, specs)
    return {"promoted": sid, "into_slot": slot, "smoke_value": smoke_value,
            "smoke_data_date": smoke_date, "deterministic": bool(entry.get("deterministic")),
            "schema": entry.get("schema"),
            "note": "spec edited — review the git diff"}


def revive(axis: str) -> dict:
    """Human-gated resurrection: reset DEAD sources so they may be retried
    (e.g. after a fetch-path fix). Without this, death was permanent — a gap
    found on 30 Jul 2026 when a library bug killed two healthy sources."""
    state_file = STATE_DIR / f"{axis}.json"
    state = _load(state_file, {"sources": {}})
    revived = []
    for sid, st in state["sources"].items():
        if st.get("status") == "dead":
            st["status"] = "active"
            st["consecutive_fails"] = 0
            revived.append(sid)
    _save(state_file, state)
    return {"axis": axis, "revived": revived}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", metavar="AXIS")
    ap.add_argument("--force", action="store_true", help="ignore cache TTL and backoff")
    ap.add_argument("--needs", action="store_true")
    ap.add_argument("--revive", metavar="AXIS", help="reset dead sources for retry (human-gated)")
    ap.add_argument("--promote", metavar="AXIS")
    ap.add_argument("--url"); ap.add_argument("--slot"); ap.add_argument("--kind")
    ap.add_argument("--org", default="?"); ap.add_argument("--extract")
    ap.add_argument("--col", type=int)
    ap.add_argument("--column-name", dest="column_name",
                    help="http_csv: read this HEADER NAME instead of a positional column")
    ap.add_argument("--row-key", dest="row_key",
                    help="http_csv: select the row whose row-key-column equals this "
                         "(e.g. World). No match is a loud failure, never the last row")
    ap.add_argument("--row-key-column", dest="row_key_column", default=None,
                    help="http_csv: the key column (default 'entity')")
    ap.add_argument("--unit")
    ap.add_argument("--deterministic", action="store_true",
                    help="structured kinds only; the smoke fetch's shape becomes a contract "
                         "and any drift kills the source at the FIRST violation")
    ap.add_argument("--path", help="repo-relative file for --kind file (its READ location)")
    a = ap.parse_args()

    # Caught at the parser, before promote() runs: --kind file reads from --path, and a
    # --url handed in its place is the mistake this gate exists to make impossible.
    if a.promote and a.kind == "file":
        # --url first: someone typing it HAS made the specific mistake this gate exists
        # for, and deserves to be told what the right field is rather than merely that
        # something is missing.
        if a.url:
            ap.error("--kind file reads from --path, not --url; pass --path "
                     "(on a file entry 'url' is an identity reference, set by the "
                     "approval path, never a fetch location)")
        if not a.path:
            ap.error("--kind file requires --path (the file it is read from)")

    if a.run:
        print(json.dumps(compose(a.run, force=a.force), ensure_ascii=False, indent=2))
    elif a.needs:
        print(json.dumps(_load(NEEDS_FILE, {}), ensure_ascii=False, indent=2))
    elif a.revive:
        print(json.dumps(revive(a.revive), ensure_ascii=False, indent=2))
    elif a.promote:
        print(json.dumps(promote(a.promote, a.url, a.slot, a.kind, a.org, a.extract, a.col,
                                 path=a.path, unit=a.unit, column_name=a.column_name,
                                 row_key=a.row_key, row_key_column=a.row_key_column,
                                 deterministic=a.deterministic or None),
                         ensure_ascii=False, indent=2))
    else:
        ap.print_help()
