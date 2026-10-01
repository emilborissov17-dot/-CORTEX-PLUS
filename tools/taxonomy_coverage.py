#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/taxonomy_coverage.py — how many of the 123 subcategories the system SEES
today (1 Oct 2026).

For every subcategory of config/taxonomy.json: the live keys mapped to it by
config/taxonomy_key_map.json, and for each key
  * its value,
  * its newest OBSERVATION date, found only through the spellings registered in
    config/field_names.json (read via tools/ask.load_spellings / parse_value).
    Never a file mtime and never a processing timestamp: a key with no
    registered date says MISSING and why;
  * its source class from config/reporter_independence.json, through the one
    existing lookup (experiments/composers/provenance.reporter_class), which
    admits only human-confirmed mappings. unknown stays unknown.

SEEN, per subcategory, needs all three:
  STATE   at least one key with a finite numeric value;
  CHANGE  at least one key whose newest observation is a calendar DAY (iso_date
          or iso_datetime) at most CHANGE_MAX_AGE_DAYS old — the measurable
          footprint of a series that changes monthly or faster. A year, a year
          fraction or a missing date can never satisfy it;
  SOURCE  at least one key from a source of class independent or adversarial.
A NOT SEEN subcategory names every condition that fails.

TOTALS. World = domains A-D, 105 subcategories. Domain E (the system itself)
is counted separately and is never added to the world total. "overall" is the
plain count over all 123 and is labelled as such.

REFUSAL. An unreadable taxonomy, key map, field registry or reporter table is a
refusal (exit 2), not an empty report. An unreadable EVIDENCE file (snapshot,
composed, feeds, somatic history) is not a refusal: its keys get no evidence and
the report names the file as unusable — a missing source is a finding.

Usage:
  venv\\Scripts\\python.exe tools/taxonomy_coverage.py            # print totals
  venv\\Scripts\\python.exe tools/taxonomy_coverage.py --write    # + memory/ JSON and the dated report
  venv\\Scripts\\python.exe tools/taxonomy_coverage.py --selftest
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import taxonomy as tx  # noqa: E402
import ask  # noqa: E402

GLOBAL = REPO / "snapshots" / "master" / "global_indicators_latest.json"
GOAL_SCORE = REPO / "snapshots" / "master" / "goal_score_latest.json"
COMPOSED = REPO / "memory" / "composed_indicators.json"
COMPOSER_SPECS = REPO / "config" / "composer_specs.json"
FEEDS = REPO / "openclaw_queue" / "external_feeds.jsonl"
SOMATIC = REPO / "memory" / "somatic_history.jsonl"
REPORTER = REPO / "config" / "reporter_independence.json"
OUT_JSON = REPO / "memory" / "taxonomy_coverage_latest.json"
REPORT_DIR = REPO / "claude" / "reports"
GLOBAL_REL = "snapshots/master/global_indicators_latest.json"

CHANGE_MAX_AGE_DAYS = 45      # a monthly series plus publication lag
DAY_SHAPES = ("iso_date", "iso_datetime")
INDEPENDENT = ("independent", "adversarial")

FAIL_NO_KEY = "no live key is mapped to it"
FAIL_STATE = "STATE: no key with a value"
FAIL_CHANGE = f"CHANGE: no key with a day-resolution observation <= {CHANGE_MAX_AGE_DAYS} d old"
FAIL_SOURCE = "SOURCE: no independent or adversarial source"


class Refused(SystemExit):
    def __init__(self, why: str):
        super().__init__(2)
        self.why = why

    def __str__(self) -> str:
        return f"REFUSED: {self.why}"


# ── evidence ─────────────────────────────────────────────────────────────────
def _load_json(p: Path, unusable: dict):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        unusable[p.relative_to(REPO).as_posix()] = f"{type(e).__name__}"
        return None


def _load_jsonl(p: Path, unusable: dict) -> list:
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        unusable[p.relative_to(REPO).as_posix()] = f"{type(e).__name__}"
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def date_in_record(rec: dict, spellings: list, field: str | None = None, now=None) -> dict:
    """Newest registered observation date in ONE record's own keys.
    A year_map spelling is read at `field` only (a per-key year), never as the
    whole map. Returns {date, spelling, shape, age_days} or {missing: why}."""
    if not isinstance(rec, dict):
        return {"missing": "no record"}
    best = None
    for e in spellings:
        sp, shape = e["spelling"], e.get("shape", "iso_date")
        if sp not in rec:
            continue
        v = rec[sp]
        if shape == "year_map":
            if not (isinstance(v, dict) and field and field in v):
                continue
            dt, _how = ask.parse_value(v[field], "year")
            shape = "year"
        else:
            dt, _how = ask.parse_value(v, shape)
        if dt and (best is None or dt > best[0]):
            best = (dt, sp, shape)
    if best is None:
        return {"missing": "no registered observation-date spelling carries a value here"}
    return {"date": best[0].date().isoformat(), "spelling": best[1], "shape": best[2],
            "age_days": round(ask._age_days(best[0], now), 1)}


def _global_ev(gi, dotted: str, spellings, now) -> dict:
    if gi is None:
        return {"value": None, "obs": {"missing": f"{GLOBAL_REL} unusable"}}
    if "." not in dotted:
        return {"value": None, "obs": {"missing": f"{dotted!r} is not a section.field path"}}
    section, field = dotted.split(".", 1)
    sec = gi.get(section)
    if not isinstance(sec, dict):
        return {"value": None, "obs": {"missing": f"no section {section!r} in the snapshot"}}
    return {"value": sec.get(field), "obs": date_in_record(sec, spellings, field, now),
            "where": f"{GLOBAL_REL}#{dotted}"}


def build_evidence(key_map: dict, now=None, spellings=None, reporter_cfg=None) -> tuple:
    """({key: [evidence rows]}, {unusable path: why}). Read-only."""
    from experiments.composers import provenance as prov
    now = now or datetime.now(timezone.utc)
    spellings = spellings if spellings is not None else ask.load_spellings()
    cfg = reporter_cfg if reporter_cfg is not None else prov.reporter_config(REPORTER)
    if not (cfg or {}).get("confirmed"):
        raise Refused(f"{REPORTER.relative_to(REPO).as_posix()} has no 'confirmed' table")
    unusable: dict = {}
    gi = _load_json(GLOBAL, unusable)
    gs = _load_json(GOAL_SCORE, unusable) or {}
    md = gs.get("metric_details") or {}
    composed = _load_json(COMPOSED, unusable) or {}
    specs = _load_json(COMPOSER_SPECS, unusable) or {}
    feeds = _load_jsonl(FEEDS, unusable)
    somatic = _load_jsonl(SOMATIC, unusable)

    spec_by_id, org_by_path = {}, {}
    for ax, v in specs.items():
        if ax.startswith("_") or not isinstance(v, dict):
            continue
        for _slot, port in (v.get("portfolio") or {}).items():
            for s in port.get("sources", []):
                spec_by_id[s.get("id")] = s
                if s.get("kind") == "file" and s.get("path") == GLOBAL_REL and s.get("extract"):
                    org_by_path.setdefault(s["extract"], s.get("org"))
    comp_entry = {}
    for _ax, v in composed.items():
        if not isinstance(v, dict):
            continue
        for _slot, s in (v.get("slots") or {}).items():
            for e in (s.get("live") or []) if isinstance(s, dict) else []:
                comp_entry.setdefault(e.get("id"), e)
        for _slot, s in (v.get("composed") or {}).items():
            if isinstance(s, dict) and s.get("id"):
                comp_entry.setdefault(s["id"], s)
    feed_last = {}
    for r in feeds:
        if r.get("key"):
            feed_last[r["key"]] = r                      # file order: the last row wins
    som_last = somatic[-1] if somatic else None

    def _cls(org, url):
        c, why = prov.reporter_class({"org": org, "url": url}, cfg)
        return c, why

    out: dict = {}
    for key, entry in key_map.items():
        sources = entry.get("sources", []) if isinstance(entry, dict) else []
        rows = []
        if key in md and ("target_config" in sources or "metric_details" in sources):
            d = md[key]
            g = (_global_ev(gi, d["observation_where_field"], spellings, now)
                 if d.get("observation_where") == GLOBAL_REL and d.get("observation_where_field")
                 else {"obs": {"missing": "metric_details names no observation field in the snapshot"}})
            org = org_by_path.get(d.get("observation_where_field")) or d.get("source_id")
            c, why = _cls(org, None)
            rows.append({"via": "metric_details", "value": d.get("current"), "obs": g["obs"],
                         "org": org, "class": c, "class_why": why})
        if "daily_tier" in sources:
            g = _global_ev(gi, key, spellings, now)
            org = org_by_path.get(key)
            c, why = _cls(org, None)
            rows.append({"via": "global_indicators", "value": g["value"], "obs": g["obs"],
                         "org": org, "class": c, "class_why": why})
        if "composed" in sources:
            e = comp_entry.get(key) or {}
            spec = spec_by_id.get(key) or {}
            if spec.get("kind") == "file" and spec.get("path") == GLOBAL_REL and spec.get("extract"):
                obs = _global_ev(gi, spec["extract"], spellings, now)["obs"]
            else:
                obs = date_in_record(e, spellings, None, now)
                if "missing" in obs:
                    obs = {"missing": f"the composed record carries no registered date "
                                      f"(source kind {spec.get('kind')!r})"}
            org, url = e.get("org") or spec.get("org"), spec.get("url")
            c, why = _cls(org, url)
            rows.append({"via": "composed", "value": e.get("value"), "obs": obs,
                         "org": org, "class": c, "class_why": why})
        if "openclaw" in sources:
            r = feed_last.get(key)
            if r is None:
                rows.append({"via": "openclaw_feed", "value": None,
                             "obs": {"missing": "no trusted feed row for this key"},
                             "org": None, "class": "unknown", "class_why": "no feed row"})
            else:
                c, why = _cls(r.get("org"), r.get("url"))
                rows.append({"via": "openclaw_feed", "value": r.get("value"),
                             "obs": date_in_record(r, spellings, None, now),
                             "org": r.get("org"), "class": c, "class_why": why})
        if "somatic" in sources:
            v = (som_last or {}).get("v", {}) if som_last else {}
            rows.append({"via": "somatic_history", "value": v.get(key),
                         "obs": date_in_record(som_last or {}, spellings, None, now)
                         if som_last else {"missing": "memory/somatic_history.jsonl has no row"},
                         "org": "path:cockpit/somatic.py", "class": "unknown",
                         "class_why": "the machine measuring itself is not a reporter class"})
        out[key] = rows
    return out, unusable


# ── the rule (pure) ──────────────────────────────────────────────────────────
def is_state_key(rows: list) -> bool:
    return any(_num(r.get("value")) for r in rows)


def is_change_key(rows: list) -> bool:
    """A day-resolution observation date at most CHANGE_MAX_AGE_DAYS old.
    A row without a date can never pass: that is the guard the mutation test holds."""
    for r in rows:
        o = r.get("obs") or {}
        if o.get("date") and o.get("shape") in DAY_SHAPES and \
                o.get("age_days") is not None and o["age_days"] <= CHANGE_MAX_AGE_DAYS:
            return True
    return False


def is_independent_key(rows: list) -> bool:
    return any(r.get("class") in INDEPENDENT for r in rows)


def coverage(key_map: dict, evidence: dict, tree: dict) -> dict:
    by_sub: dict = {}
    for key, entry in key_map.items():
        by_sub.setdefault(entry["subcategory"], []).append(key)
    subs = []
    for r in tx.subcategories(tree):
        keys = sorted(by_sub.get(r["id"], []))
        if not keys:
            fails = [FAIL_NO_KEY]
        else:
            fails = []
            if not any(is_state_key(evidence.get(k, [])) for k in keys):
                fails.append(FAIL_STATE)
            if not any(is_change_key(evidence.get(k, [])) for k in keys):
                fails.append(FAIL_CHANGE)
            if not any(is_independent_key(evidence.get(k, [])) for k in keys):
                fails.append(FAIL_SOURCE)
        subs.append({"id": r["id"], "name": r["name_en"], "domain": r["domain"],
                     "category": r["category"], "seen": not fails, "fails": fails,
                     "keys": [{"key": k, "evidence": evidence.get(k, [])} for k in keys]})
    world = [s for s in subs if s["domain"] != tx.SYSTEM_DOMAIN]
    system = [s for s in subs if s["domain"] == tx.SYSTEM_DOMAIN]
    per_domain = {}
    for s in subs:
        d = per_domain.setdefault(s["domain"], {"seen": 0, "of": 0})
        d["of"] += 1
        d["seen"] += int(s["seen"])
    reasons = Counter(f for s in world for f in s["fails"])
    return {
        "totals": {
            "world": {"seen": sum(s["seen"] for s in world), "of": len(world),
                      "domains": sorted({s["domain"] for s in world})},
            "system_E": {"seen": sum(s["seen"] for s in system), "of": len(system),
                         "note": "reported separately; never added to the world total"},
            "overall": {"seen": sum(s["seen"] for s in subs), "of": len(subs),
                        "note": "plain count over all subcategories; the world total excludes E"},
            "per_domain": per_domain,
        },
        "not_seen_reasons_world": dict(reasons),
        "not_seen_reasons_E": dict(Counter(f for s in system for f in s["fails"])),
        "subcategories": subs,
    }


def atoms_totals(tree: dict, root=None) -> dict:
    """ATOMS n/105: world subcategories with at least one NON-RETRACTED atom on
    disk (core.atoms.compute_manifest, recomputed from the files). Domain E is
    counted apart, as for SEEN."""
    from core import atoms as _atoms
    live = set(_atoms.compute_manifest(root)["subcategories_with_live_atoms"])
    subs = tx.subcategories(tree)
    world = [s for s in subs if s["domain"] != tx.SYSTEM_DOMAIN]
    per = {}
    for s in subs:
        d = per.setdefault(s["domain"], {"with_atoms": 0, "of": 0})
        d["of"] += 1
        d["with_atoms"] += int(s["id"] in live)
    return {"world": {"with_atoms": sum(s["id"] in live for s in world), "of": len(world)},
            "system_E": {"with_atoms": sum(s["id"] in live for s in subs if s["domain"] == tx.SYSTEM_DOMAIN),
                         "of": sum(1 for s in subs if s["domain"] == tx.SYSTEM_DOMAIN)},
            "per_domain": per,
            "rule": "a subcategory counts when atoms/ holds at least one atom whose card_key is not retracted"}


# ── run / write ──────────────────────────────────────────────────────────────
def run(now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        tree = tx.load()
        tx.load_key_map(tree=tree)
    except tx.TaxonomyError as e:
        raise Refused(str(e))
    km_doc = json.loads(tx.KEY_MAP.read_text(encoding="utf-8"))
    key_map = km_doc["keys"]
    evidence, unusable = build_evidence(key_map, now)
    cov = coverage(key_map, evidence, tree)
    cov["totals"]["atoms"] = atoms_totals(tree)
    cov.update({
        "generated_utc": now.isoformat(timespec="seconds"),
        "rule": {"STATE": "at least one key with a finite numeric value",
                 "CHANGE": f"at least one key whose newest registered observation date is a day "
                           f"(iso_date/iso_datetime) at most {CHANGE_MAX_AGE_DAYS} days old",
                 "SOURCE": "at least one key from a source of class independent or adversarial "
                           "(config/reporter_independence.json 'confirmed' only)"},
        "unusable_evidence_files": unusable,
        "key_map_unmapped": len(km_doc.get("unmapped", [])),
    })
    return cov


def _ev_line(k: dict) -> str:
    parts = []
    for r in k["evidence"]:
        o = r["obs"]
        d = (f"{o['date']} via {o['spelling']} ({o['shape']}, {o['age_days']} d)"
             if o.get("date") else f"date MISSING ({o.get('missing')})")
        parts.append(f"{r['via']}: value {r['value']!r}; {d}; class {r['class']}")
    return f"  - `{k['key']}` — " + (" | ".join(parts) if parts else "no evidence row")


def render(cov: dict) -> str:
    t = cov["totals"]
    L = [f"# TAXONOMY COVERAGE — {cov['generated_utc'][:10]}", "",
         f"Generated {cov['generated_utc']} by `tools/taxonomy_coverage.py`. Read-only over the repo.", "",
         "## Totals", "",
         f"- **World (A-D): SEEN {t['world']['seen']}/{t['world']['of']}**",
         f"- Domain E (the system itself), separate, never in the world total: "
         f"SEEN {t['system_E']['seen']}/{t['system_E']['of']}",
         f"- Overall (plain count over all 123): SEEN {t['overall']['seen']}/{t['overall']['of']}",
         f"- **ATOMS (world): {t['atoms']['world']['with_atoms']}/{t['atoms']['world']['of']}** "
         f"subcategories with at least one non-retracted atom on disk", "",
         "| domain | SEEN | of |", "|---|---:|---:|"]
    for d, v in sorted(t["per_domain"].items()):
        L.append(f"| {d}{' (system, separate)' if d == tx.SYSTEM_DOMAIN else ''} | {v['seen']} | {v['of']} |")
    L += ["", "## The rule", ""] + [f"- **{k}**: {v}" for k, v in cov["rule"].items()]
    L += ["", "## NOT SEEN reasons, counted (world; a subcategory can fail several)", "",
          "| reason | subcategories |", "|---|---:|"]
    L += [f"| {r} | {n} |" for r, n in sorted(cov["not_seen_reasons_world"].items(), key=lambda x: -x[1])]
    L += ["", "Domain E: " + ", ".join(f"{r}: {n}" for r, n in cov["not_seen_reasons_E"].items()), ""]
    if cov["unusable_evidence_files"]:
        L += ["**Unusable evidence files:** " + ", ".join(f"`{p}` ({w})" for p, w in
                                                         cov["unusable_evidence_files"].items()), ""]
    L += ["## Subcategories with at least one live key", ""]
    for s in cov["subcategories"]:
        if not s["keys"]:
            continue
        L.append(f"### {s['id']} {s['name']} — {'SEEN' if s['seen'] else 'NOT SEEN: ' + '; '.join(s['fails'])}")
        L += [_ev_line(k) for k in s["keys"]] + [""]
    empty = [f"{s['id']} {s['name']}" for s in cov["subcategories"] if not s["keys"]]
    L += [f"## Subcategories with no live key ({len(empty)})", "", ", ".join(empty), ""]
    return "\n".join(L)


def write(cov: dict) -> tuple:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_bytes((json.dumps(cov, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    rep = REPORT_DIR / f"TAXONOMY_COVERAGE_{cov['generated_utc'][:10]}.md"
    rep.write_bytes(render(cov).encode("utf-8"))
    return OUT_JSON, rep


def selftest() -> dict:
    res = {"integrations": {}, "controls": {}}
    for p in (tx.TAXONOMY, tx.KEY_MAP, ask.FIELD_NAMES, REPORTER, GLOBAL, GOAL_SCORE,
              COMPOSED, COMPOSER_SPECS, FEEDS, SOMATIC):
        res["integrations"][p.relative_to(REPO).as_posix()] = "LIVE" if p.is_file() else "INERT (missing)"
    board = (REPO / "tools" / "daily_board.py").read_text(encoding="utf-8")
    res["integrations"]["tools/daily_board.py reads memory/taxonomy_coverage_latest.json"] = (
        "LIVE" if "taxonomy_coverage_latest.json" in board else "INERT")
    bat = (REPO / "tools" / "prophecy_morning.bat").read_text(encoding="utf-8", errors="replace")
    res["integrations"]["tools/prophecy_morning.bat runs this tool"] = (
        "LIVE" if "taxonomy_coverage.py" in bat else "INERT (nothing schedules it)")
    ok = {"value": 1.0, "obs": {"date": "2026-09-30", "shape": "iso_date", "age_days": 1.0},
          "class": "independent"}
    res["controls"]["dated fresh key passes CHANGE"] = is_change_key([ok])
    res["controls"]["undated key fails CHANGE"] = not is_change_key([{**ok, "obs": {"missing": "x"}}])
    res["controls"]["year-resolution key fails CHANGE"] = not is_change_key(
        [{**ok, "obs": {"date": "2025-12-31", "shape": "year", "age_days": 1.0}}])
    res["controls"]["old day fails CHANGE"] = not is_change_key(
        [{**ok, "obs": {**ok["obs"], "age_days": CHANGE_MAX_AGE_DAYS + 1}}])
    res["controls"]["unknown class fails SOURCE"] = not is_independent_key([{**ok, "class": "unknown"}])
    res["ok"] = all(res["controls"].values())
    return res


def main(argv) -> int:
    if "--selftest" in argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    try:
        cov = run()
    except Refused as e:
        print(str(e))
        return 2
    t = cov["totals"]
    print(f"SEEN world {t['world']['seen']}/{t['world']['of']} · E {t['system_E']['seen']}/"
          f"{t['system_E']['of']} (separate) · overall {t['overall']['seen']}/{t['overall']['of']}"
          f" · ATOMS world {t['atoms']['world']['with_atoms']}/{t['atoms']['world']['of']}")
    for r, n in sorted(cov["not_seen_reasons_world"].items(), key=lambda x: -x[1]):
        print(f"  NOT SEEN (world) {n:>3}  {r}")
    if cov["unusable_evidence_files"]:
        print("  unusable evidence:", cov["unusable_evidence_files"])
    if "--write" in argv:
        j, rep = write(cov)
        print(f"wrote {j.relative_to(REPO).as_posix()} and {rep.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
