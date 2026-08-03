#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/provider_catalog.py — traverse a provider's catalog and turn a series into a
candidate, through the SAME intake pipeline as everything else.

MODE 2: CATALOG TRAVERSAL. No search engine, no browser, no model. A provider publishes a
machine-readable list of what it holds; we read that list and address a series in it. This
is the opposite failure mode to the collector's: where the browsing loop had too much
freedom and spent three days on four marketing blogs, this has none — it can only ever
return something the provider actually publishes, by its own code.

REGISTER PROVIDERS, NOT SERIES. 713 registered UN series would be 713 things that can rot.
One registered provider is one catalog and one address shape, and adding a national
institute that speaks SDMX becomes an entry in config/providers.json rather than an adapter
in this codebase.

NO NEW SEARCH PATH, AND NO NEW TRUST. A series that comes out of a catalog gets exactly the
treatment a browsed candidate gets: fetch it, read the real payload, derive or declare the
address, smoke-test it through composer.fetch, classify its independence, and offer it to
Emil with the value, the address and the class visible. Nothing here promotes anything.

ON THE AXIS MAP. --for-axis orders a catalog using config/sdg_axis_map.json, which is a
human-owned ROUTING HINT and never a filter. Every call reports how many series it set
aside, and --all prints them. core/source_registration.py refuses in writing to add an
axis-fit filter to intake because cross-domain evidence is the point of this system; that
refusal applies with equal force here, where it would be even easier to hide.

  venv\\Scripts\\python.exe -m core.provider_catalog --providers
  venv\\Scripts\\python.exe -m core.provider_catalog --catalog un_sdg --grep water
  venv\\Scripts\\python.exe -m core.provider_catalog --catalog un_sdg --for-axis WATER_REVIEW
  venv\\Scripts\\python.exe -m core.provider_catalog --ingest un_sdg SH_H2O_SAFE \\
      --axis WATER_REVIEW --slot anchor_annual --where dimensions.Location=ALLAREA
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PROVIDERS_FILE = BASE / "config" / "providers.json"
SDG_MAP_FILE = BASE / "config" / "sdg_axis_map.json"
CACHE_DIR = BASE / "memory" / "provider_catalogs"


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def registry() -> dict:
    return (_load(PROVIDERS_FILE, {}) or {}).get("providers", {})


def provider(pid: str) -> dict:
    p = registry().get(pid)
    if not p:
        raise KeyError(f"no provider {pid!r} in config/providers.json "
                       f"(have: {sorted(registry())})")
    return p


def live_providers() -> list:
    return sorted(k for k, v in registry().items() if v.get("status") == "live")


def skipped_providers() -> list:
    """Providers we cannot READ yet. A gap in us, recorded so it can be closed."""
    return [{"id": k, "why": v.get("skip_reason"), "unblocks_if": v.get("unblocks_if")}
            for k, v in sorted(registry().items()) if v.get("status") == "skipped"]


# ── catalog traversal ────────────────────────────────────────────────────────

def _fetch(url: str, accept: str = None, timeout: int = 180) -> str:
    import requests
    headers = {"User-Agent": "CORTEX-provider-catalog/1.0"}
    if accept:
        headers["Accept"] = accept
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.text


def _parse_json_list(text: str, cat: dict) -> list:
    rows = json.loads(text)
    out = []
    for r in rows if isinstance(rows, list) else []:
        topic = r.get(cat.get("topic") or "")
        out.append({"code": str(r.get(cat.get("code") or "code") or ""),
                    "title": str(r.get(cat.get("title") or "title") or ""),
                    "topic": [str(t) for t in topic] if isinstance(topic, list)
                    else ([str(topic)] if topic else [])})
    return [o for o in out if o["code"]]


def _parse_tsv(text: str, cat: dict) -> list:
    """Eurostat's TOC: a quoted TSV whose header names the columns."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    head = [c.strip().strip('"') for c in lines[0].split("\t")]

    def col(name, default=None):
        return head.index(name) if name in head else default

    ci, ti, yi = col("code"), col("title"), col("type")
    out = []
    for l in lines[1:]:
        cells = [c.strip().strip('"') for c in l.split("\t")]
        if ci is None or ci >= len(cells):
            continue
        kind = cells[yi] if yi is not None and yi < len(cells) else ""
        if kind and kind not in ("dataset", "table"):
            continue                      # folders are not series
        out.append({"code": cells[ci],
                    "title": cells[ti] if ti is not None and ti < len(cells) else "",
                    "topic": [kind] if kind else []})
    return [o for o in out if o["code"]]


def _parse_sdmx_dataflows(text: str, cat: dict) -> list:
    data = json.loads(text)
    dfs = ((data.get("data") or data).get("dataflows")) or []
    out = []
    for d in dfs:
        agency, ver = d.get("agencyID"), d.get("version")
        code = d.get("id")
        if agency and ver:
            code = f"{agency},{d.get('id')},{ver}"
        name = d.get("name")
        if isinstance(name, dict):
            name = name.get("en") or next(iter(name.values()), "")
        out.append({"code": str(code), "title": str(name or ""),
                    "topic": [str(agency or "")]})
    return [o for o in out if o["code"]]


PARSERS = {"json_list": _parse_json_list, "tsv": _parse_tsv,
           "sdmx_dataflows": _parse_sdmx_dataflows}


def catalog(pid: str, refresh: bool = False) -> list:
    """[{code, title, topic}] for a provider. Cached on disk — a catalog is a big,
    slow-moving document and re-fetching it per query is rude to the provider."""
    p = provider(pid)
    cat = p.get("catalog") or {}
    if not cat.get("url"):
        raise KeyError(f"provider {pid!r} declares no catalog url")
    cache = CACHE_DIR / f"{pid}.json"
    if not refresh and cache.exists():
        cached = _load(cache, None)
        if cached:
            return cached
    text = _fetch(cat["url"], accept=cat.get("accept"))
    parser = PARSERS.get(cat.get("format") or "json_list")
    if not parser:
        raise KeyError(f"no parser for catalog format {cat.get('format')!r}")
    entries = parser(text, cat)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return entries


def search(entries: list, needle: str) -> list:
    rx = re.compile(re.escape(needle), re.IGNORECASE)
    return [e for e in entries if rx.search(e["title"]) or rx.search(e["code"])]


def for_axis(entries: list, axis: str) -> tuple:
    """(associated, set_aside_count). A HINT, not a filter — see the module docstring and
    config/sdg_axis_map.json. The count of what was set aside is returned so no caller can
    present this as the whole catalog without saying otherwise."""
    goal_to_axes = (_load(SDG_MAP_FILE, {}) or {}).get("goal_to_axes", {})
    goals = {g for g, axes in goal_to_axes.items() if axis in axes}
    if not goals:
        return [], len(entries)
    hit = [e for e in entries if goals & set(e.get("topic") or [])]
    return hit, len(entries) - len(hit)


# ── resolving a breakdown, without flipping a coin ───────────────────────────
#
# Most UN SDG series carry a BREAKDOWN on the same entity and the same year: Location
# RURAL/URBAN/ALLAREA, Sex FEMALE/MALE/BOTHSEX, Age bands. readers.read_json_rows refuses
# to pick one, correctly — several different values sharing the latest period is not a
# series, and returning whichever the provider serialised last is the wrong-cell failure
# in the one disguise a row key cannot catch.
#
# But the aggregate row is usually THERE and identifiable: every dimension set to its
# own total. This proposes that filter and requires it to be UNIQUE. It never picks
# between two plausible combinations, and what it proposes is written into the source
# EXPLICITLY, so the stored record says `where: {"dimensions.Location": "ALLAREA"}` and
# not a magic flag that re-decides itself on every fetch.
TOTAL_CODES = {
    "ALLAREA", "ALLAGE", "BOTHSEX", "TOTAL", "_T", "ALL", "ANY",
    "G",           # Reporting Type: Global
    "ISIC4_TOTAL", "NAT",
}


def propose_total_filter(rows: list, dim_field: str = "dimensions") -> tuple:
    """(where_filter, reason). None when no UNIQUE all-totals breakdown exists.

    `rows` are the payload's records, as fetched — this reads what is actually there
    rather than assuming a vocabulary the provider may not use.
    """
    combos = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        dims = r.get(dim_field) or {}
        if not isinstance(dims, dict):
            continue
        combos.setdefault(tuple(sorted(dims.items())), 0)
        combos[tuple(sorted(dims.items()))] += 1
    if not combos:
        return None, "the payload carries no breakdown at all"
    if len(combos) == 1:
        return {}, "only one breakdown present — nothing to disambiguate"
    totals = [c for c in combos
              if all(str(v).upper() in TOTAL_CODES for _k, v in c)]
    if len(totals) == 1:
        return ({f"{dim_field}.{k}": v for k, v in totals[0]},
                f"the one breakdown whose every dimension is its own total: "
                f"{dict(totals[0])}")
    if not totals:
        return None, (f"none of the {len(combos)} breakdown(s) is an all-totals row — "
                      f"a human must say which is meant: "
                      f"{[dict(c) for c in list(combos)[:4]]}")
    return None, (f"{len(totals)} competing all-totals breakdowns — refusing to choose: "
                  f"{[dict(c) for c in totals[:4]]}")


# ── a catalog entry -> a source the shared pipeline can test ─────────────────

def build_source(pid: str, code: str, params: dict = None, address: dict = None) -> dict:
    """The url and the reader address for one series. Templated from the provider record,
    so a new provider is a config entry rather than code."""
    p = provider(pid)
    if p.get("status") != "live":
        raise KeyError(f"provider {pid!r} is {p.get('status')}: {p.get('skip_reason')}")
    vals = dict(p.get("params") or {})
    vals.update(params or {})
    vals["code"] = code
    url = p["series_url"].format(**vals)

    def fill(obj):
        if isinstance(obj, str):
            return obj.format(**vals) if "{" in obj else obj
        if isinstance(obj, dict):
            return {k: fill(v) for k, v in obj.items()}
        return obj

    src = {"kind": p["kind"], "url": url, "org": p["name"], "deterministic": True}
    src.update(fill(p.get("address") or {}))
    for k, v in (address or {}).items():
        if v is not None:
            src[k] = v
    return src


def ingest(pid: str, code: str, axis: str = None, slot: str = None, params: dict = None,
           address: dict = None, metric: str = None, promote: bool = False) -> dict:
    """Hand the built source to the SAME intake pipeline a browsed candidate goes through.

    Nothing about coming from a catalog earns it a shortcut: same schema wall, same smoke
    fetch through composer.fetch, same registration as a candidate, same requirement that
    a human promotes it."""
    import sys
    sys.path.insert(0, str(BASE / "scripts"))
    sys.path.insert(0, str(BASE / "experiments" / "composers"))
    import cortex_ingest as CI

    src = build_source(pid, code, params=params, address=address)
    p = provider(pid)
    overrides = {k: v for k, v in src.items()
                 if k not in ("kind", "url", "org", "deterministic")}
    trail = CI.ingest(src["url"], axis=axis, slot=slot,
                      fmt="json", kind=src["kind"], org=p["name"],
                      metric=metric or f"{pid}:{code}",
                      deterministic=True, overrides=overrides,
                      register=True, promote=promote)
    trail["provider"] = pid
    trail["series_code"] = code
    trail["provider_default_independence"] = p.get("reporter_independence")
    return trail


# ── CLI ──────────────────────────────────────────────────────────────────────

def _kv(pairs):
    out = {}
    for p in pairs or []:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="provider_catalog")
    ap.add_argument("--providers", action="store_true", help="the registry")
    ap.add_argument("--catalog", metavar="PROVIDER")
    ap.add_argument("--refresh", action="store_true", help="re-fetch the catalog")
    ap.add_argument("--grep", metavar="TEXT")
    ap.add_argument("--for-axis", dest="for_axis", metavar="AXIS")
    ap.add_argument("--all", action="store_true", help="print every entry, unordered")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--ingest", nargs=2, metavar=("PROVIDER", "CODE"))
    ap.add_argument("--axis"); ap.add_argument("--slot")
    ap.add_argument("--param", action="append", help="series-url param, k=v")
    ap.add_argument("--where", action="append", help="row filter, dotted.field=value")
    ap.add_argument("--cell", action="append", help="jsonstat cell, dim=code")
    ap.add_argument("--series-key", dest="series_key", action="append", help="sdmx, DIM=code")
    ap.add_argument("--promote", action="store_true")
    a = ap.parse_args()

    if a.providers:
        for pid in sorted(registry()):
            p = registry()[pid]
            print(f"  {pid:<10} {p.get('status'):<8} {p.get('kind') or '-':<16} "
                  f"{p.get('reporter_independence') or '-':<14} {p.get('name')}")
            if p.get("status") == "skipped":
                print(f"             skipped because: {p.get('skip_reason')}")
                print(f"             NOT a blacklist: {p.get('skip_is_not_a_blacklist')}")
    elif a.catalog:
        entries = catalog(a.catalog, refresh=a.refresh)
        print(f"{a.catalog}: {len(entries)} series in the catalog")
        shown, note = entries, "every entry"
        if a.grep:
            shown = search(entries, a.grep)
            note = f"{len(shown)} matching {a.grep!r} (a text match, not a ranking)"
        elif a.for_axis and not a.all:
            shown, aside = for_axis(entries, a.for_axis)
            note = (f"{len(shown)} associated with {a.for_axis} by the human-owned SDG map; "
                    f"{aside} SET ASIDE — a HINT, not a filter. --all prints them, and any "
                    f"of them can still be ingested for this axis")
        print(f"showing: {note}\n")
        for e in shown[:a.limit]:
            print(f"  {e['code']:<28} {str(e.get('topic') or ''):<12} {e['title'][:88]}")
        if len(shown) > a.limit:
            print(f"  ... {len(shown) - a.limit} more (--limit)")
    elif a.ingest:
        pid, code = a.ingest
        addr = {}
        if a.where:
            addr["where"] = _kv(a.where)
        if a.cell:
            addr["cell"] = _kv(a.cell)
        if a.series_key:
            addr["series_key"] = _kv(a.series_key)
        print(json.dumps(ingest(pid, code, axis=a.axis, slot=a.slot,
                                params=_kv(a.param), address=addr,
                                promote=a.promote), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
