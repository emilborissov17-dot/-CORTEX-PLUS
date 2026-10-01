#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/atoms.py — an accepted card becomes ONE ATOM in its subcategory folder
(1 Oct 2026, command C-OC-1 Part 4).

    atoms/<domain>/<category>/<subcategory>/<key>.jsonl   one JSON line per atom
    atoms/<domain>/<category>/<subcategory>/<key>.metta   the same fact as MeTTa:
        (obs "<sub>" "<key>" "<place>" "<period>" <value> "<unit>" "<source_class>" "<quote_hash>")
    atoms/MANIFEST.json   RECOMPUTED from disk on every write — files, lines,
                          live_lines (retractions skipped), sha256 per file.
                          Never incremented: an increment drifts from the files
                          the first time anything else touches them.

THE FOLDER IS core.taxonomy.folder_for(subcategory). A card is an atom only if it
names a subcategory; a card without one is NOT migrated and the caller counts it.

REFUSAL (AtomRefused, raised): a subcategory that does not resolve, a domain-E
(system) subcategory on an external card, or a card missing value/unit/place/
period. There is no default for any of them.

A RETRACTION REMOVES NOTHING FROM DISK. memory/observation_retractions.jsonl
(core.card_intake.retract) is honoured by read() and by the manifest's
live_lines; the bytes of the atom files never change.

source_id IS NOT ON THE CARD (CARD_FIELDS keeps it off so a card_key never moves),
so it is resolved by (url, key) against config/openclaw_sources.json; no match
is written as null with the reason. source_class comes from
config/reporter_independence.json, CONFIRMED entries only, through the one
existing lookup (experiments/composers/provenance.reporter_class); otherwise
"unknown".

Usage:
  venv\\Scripts\\python.exe -m core.atoms --selftest
  venv\\Scripts\\python.exe -m core.atoms --manifest     # recompute and print
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ROOT = REPO / "atoms"
SOURCES = REPO / "config" / "openclaw_sources.json"
REQUIRED = ("value", "unit", "place", "period")
_SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")


class AtomRefused(ValueError):
    """Raised, never returned: a card that cannot be filed as an atom."""


def _key_file(key: str) -> str:
    """A filename from the card's key: no separators, no '..', bounded."""
    name = _SAFE.sub("_", str(key)).strip("._") or "unnamed"
    return name[:120]


def _metta_str(v) -> str:
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _metta_num(v) -> str:
    return repr(round(float(v), 6))


def _source_for(url: str, key: str) -> Optional[dict]:
    try:
        doc = json.loads(SOURCES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for s in doc.get("sources") or []:
        if s.get("url") == url and s.get("key") == key:
            return s
    return None


def _source_class(org, url) -> tuple:
    from experiments.composers import provenance as prov
    return prov.reporter_class({"org": org, "url": url})


def atom_of(row: dict) -> dict:
    """The atom for one accepted row. Raises AtomRefused; never fills a gap."""
    from core import taxonomy as tx
    rec = row.get("record") or {}
    sub = rec.get("subcategory")
    try:
        r = tx.subcategory(sub)
    except tx.TaxonomyError as exc:
        raise AtomRefused(f"subcategory {sub!r} does not resolve: {exc}") from exc
    if r["domain"] == tx.SYSTEM_DOMAIN:
        raise AtomRefused(f"{sub} is domain E (the system itself); an external card is not one")
    missing = [f for f in REQUIRED if rec.get(f) in (None, "")]
    if missing:
        raise AtomRefused(f"card {row.get('card_key')} lacks {missing}")
    try:
        value = float(rec["value"])
    except (TypeError, ValueError) as exc:
        raise AtomRefused(f"value {rec.get('value')!r} is not a number") from exc
    src = _source_for(rec.get("url"), rec.get("key"))
    cls, why = _source_class(src.get("org") if src else None, rec.get("url"))
    return {
        "subcategory": sub, "key": rec.get("key"), "value": value, "unit": rec["unit"],
        "place": rec["place"],
        "period": (_utc_day(rec["period"]) if rec.get("period_how") == "window_end_day" and _epoch_day(rec["period"])
                   else str(rec["period"])),
        "period_how": rec.get("period_how"),
        "raw_period": str(rec["period"]),
        "source_id": src.get("id") if src else None,
        "source_id_missing": None if src else "no entry in config/openclaw_sources.json has this (url, key)",
        "source_class": cls, "source_class_why": why,
        "quote_hash": hashlib.sha256(str(rec.get("quote", "")).encode("utf-8")).hexdigest(),
        "card_key": row.get("card_key"), "judged_utc": row.get("judged_utc"),
    }


def metta_line(a: dict) -> str:
    return ("(obs " + " ".join([_metta_str(a["subcategory"]), _metta_str(a["key"]), _metta_str(a["place"]),
                                _metta_str(a["period"]), _metta_num(a["value"]), _metta_str(a["unit"]),
                                _metta_str(a["source_class"]), _metta_str(a["quote_hash"])]) + ")")


# ── IDENTITY (C-OC-3 Part 0, 1 Oct 2026) ─────────────────────────────────────
# An observation seen again is ONE observation. Identity is
#     (source_id, key, place, period, value)
# and the period that enters it is never the feed's own clock. The case: USGS's
# summary feed restamps `metadata.generated` every minute while the 24 h count
# stays 13, and C-OC-2 filed that one reading twice.
PROCESSING_FIELDS = ("generated", "generated_at", "updated", "updated_at", "lastupdated", "last_updated",
                     "fetched", "fetched_at", "ts", "timestamp", "computed_at", "made_at", "cycle_ts",
                     "cached_at", "retrieved_at", "mtime")


def _epoch_day(raw) -> Optional[str]:
    s = str(raw).strip()
    if not s.isdigit():
        return None
    if len(s) == 13:
        return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).date().isoformat()
    if len(s) == 10:
        return datetime.fromtimestamp(int(s), tz=timezone.utc).date().isoformat()
    return None


def _utc_day(raw) -> Optional[str]:
    d = _epoch_day(raw)
    if d:
        return d
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def is_processing_field(field_path: str) -> bool:
    last = str(field_path or "").split(".")[-1].lower()
    return last in PROCESSING_FIELDS


def classify_period(field_path: str, raw, rolling: bool = False) -> tuple:
    """-> (period, how). A processing-time field is the feed's clock: for a
    ROLLING-WINDOW count it names the window's end DAY (how="window_end_day");
    otherwise it is kept as a label only (how="processing_time") and never
    enters identity."""
    if is_processing_field(field_path):
        if rolling:
            day = _utc_day(raw)
            if day:
                return day, "window_end_day"
        return str(raw), "processing_time"
    return str(raw), "same_record"


def identity_of(a: dict) -> tuple:
    how = a.get("period_how")
    period = a.get("period")
    if how == "processing_time":
        period = None
    elif how is None and _epoch_day(period):
        period = _epoch_day(period)          # legacy lines written before period_how existed
    return (a.get("source_id"), a.get("key"), a.get("place"), period, a.get("value"))


def _lines(p: Path) -> list:
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def _existing_keys(p: Path) -> set:
    return {x.get("card_key") for x in _lines(p)}


def write(row: dict, root: Optional[Path] = None) -> dict:
    """File one ACCEPTED row. {"written": bool, "why"/"path"/"seen_again"}.
    The SAME observation (same identity) appends a `seen` line instead of a new
    atom; files stay append-only and read() derives times_seen / last_seen_utc."""
    from core import taxonomy as tx
    root = Path(root or ROOT)
    if row.get("verdict") != "ACCEPTED":
        return {"written": False, "why": f"verdict {row.get('verdict')!r} is not ACCEPTED"}
    if not (row.get("record") or {}).get("subcategory"):
        return {"written": False, "why": "card carries no subcategory — not migrated"}
    a = atom_of(row)
    folder = root / tx.folder_for(a["subcategory"]).split("/", 1)[1]
    folder.mkdir(parents=True, exist_ok=True)
    jf = folder / f"{_key_file(a['key'])}.jsonl"
    mf = folder / f"{_key_file(a['key'])}.metta"
    existing = _lines(jf)
    if a["card_key"] in {x.get("card_key") for x in existing}:
        return {"written": False, "why": f"card {a['card_key'][:12]} already filed"}
    ident = identity_of(a)
    if any(x.get("kind", "atom") == "atom" and identity_of(x) == ident for x in existing):
        seen = {"kind": "seen", "identity": list(ident), "card_key": a["card_key"],
                "seen_utc": a.get("judged_utc") or datetime.now(timezone.utc).isoformat(),
                "raw_period": a.get("raw_period")}
        with jf.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(seen, ensure_ascii=False) + "\n")
        write_manifest(root)
        return {"written": False, "seen_again": True, "why": "same observation seen again"}
    with jf.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    with mf.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(metta_line(a) + "\n")
    write_manifest(root)
    return {"written": True, "path": jf.relative_to(root).as_posix()}


def _collapse(lines: list, gone: set) -> list:
    """Atom lines + seen lines of ONE file -> one dict per identity, with
    times_seen and last_seen_utc. Retracted card_keys are skipped."""
    by_id: dict = {}
    for x in lines:
        if x.get("card_key") in gone:
            continue
        if x.get("kind", "atom") == "seen":
            ident = tuple(x.get("identity") or [])
            if ident in by_id:
                by_id[ident]["times_seen"] += 1
                by_id[ident]["last_seen_utc"] = max(by_id[ident]["last_seen_utc"] or "", x.get("seen_utc") or "")
            continue
        ident = identity_of(x)
        if ident in by_id:
            by_id[ident]["times_seen"] += 1
            by_id[ident]["last_seen_utc"] = max(by_id[ident]["last_seen_utc"] or "", x.get("judged_utc") or "")
        else:
            by_id[ident] = {**x, "times_seen": 1, "last_seen_utc": x.get("judged_utc")}
    return list(by_id.values())


def read(root: Optional[Path] = None, subcategory: Optional[str] = None) -> Iterator[dict]:
    """Every observation on disk, ONCE, minus retracted card_keys. The one way to
    read atoms; duplicates on disk collapse by identity_of()."""
    from core import card_intake as ci
    root = Path(root or ROOT)
    gone = ci.retracted_keys()
    if not root.exists():
        return
    for f in sorted(root.rglob("*.jsonl")):
        for a in _collapse(_lines(f), gone):
            if subcategory and a.get("subcategory") != subcategory:
                continue
            yield a


def compute_manifest(root: Optional[Path] = None) -> dict:
    """From disk, every time: files, lines, live_lines (one per observation),
    sha256, and `collapsed` = atom lines that are the same observation again."""
    from core import card_intake as ci
    root = Path(root or ROOT)
    gone = ci.retracted_keys()
    files, live_subs, collapsed, atom_lines = {}, set(), 0, 0
    for f in sorted(list(root.rglob("*.jsonl")) + list(root.rglob("*.metta"))) if root.exists() else []:
        b = f.read_bytes()
        lines = [l for l in b.decode("utf-8").splitlines() if l.strip()]
        rel = f.relative_to(root).as_posix()
        entry = {"lines": len(lines), "sha256": hashlib.sha256(b).hexdigest()}
        if f.suffix == ".jsonl":
            parsed = _lines(f)
            atoms_here = [x for x in parsed if x.get("kind", "atom") == "atom"]
            live_atoms = [x for x in atoms_here if x.get("card_key") not in gone]
            obs = _collapse(parsed, gone)
            entry["atom_lines"] = len(atoms_here)
            entry["live_lines"] = len(obs)
            collapsed += len(live_atoms) - len(obs)
            atom_lines += len(atoms_here)
            live_subs |= {a.get("subcategory") for a in obs}
        files[rel] = entry
    return {"computed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rule": ("recomputed from disk on every write; retracted card_keys are on disk but not live; "
                     "atom lines with the same identity (source_id, key, place, period, value) are ONE "
                     "observation and are counted in `collapsed`"),
            "files": files,
            "atom_files": sum(1 for k in files if k.endswith(".jsonl")),
            "atoms_total": atom_lines,
            "atoms_live": sum(v.get("live_lines", 0) for v in files.values()),
            "collapsed": collapsed,
            "subcategories_with_live_atoms": sorted(s for s in live_subs if s)}


def write_manifest(root: Optional[Path] = None) -> dict:
    root = Path(root or ROOT)
    m = compute_manifest(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "MANIFEST.json").write_bytes((json.dumps(m, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return m


def selftest() -> dict:
    res = {"integrations": {}}
    for rel in ("config/taxonomy.json", "config/reporter_independence.json", "config/openclaw_sources.json"):
        res["integrations"][rel] = "LIVE" if (REPO / rel).is_file() else "INERT (missing)"
    res["integrations"]["atoms/ on disk"] = (
        f"LIVE ({sum(1 for _ in ROOT.rglob('*.jsonl'))} atom file(s))" if ROOT.is_dir() else "INERT (no atoms/ yet)")
    ci_src = (REPO / "core" / "card_intake.py").read_text(encoding="utf-8")
    res["integrations"]["core/card_intake.py calls core.atoms.write"] = (
        "LIVE" if "atoms.write(" in ci_src or "_atoms.write(" in ci_src else "INERT")
    cov = (REPO / "tools" / "taxonomy_coverage.py").read_text(encoding="utf-8")
    res["integrations"]["tools/taxonomy_coverage.py counts ATOMS"] = (
        "LIVE" if "atoms" in cov and "compute_manifest" in cov else "INERT")
    res["ok"] = all(not v.startswith("INERT (missing)") for v in res["integrations"].values())
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    if "--manifest" in sys.argv:
        print(json.dumps(write_manifest(), indent=1)[:4000])
        sys.exit(0)
    print(__doc__)
