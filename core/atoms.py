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
        "place": rec["place"], "period": str(rec["period"]),
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


def _existing_keys(p: Path) -> set:
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.add(json.loads(line).get("card_key"))
            except ValueError:
                continue
    return out


def write(row: dict, root: Optional[Path] = None) -> dict:
    """File one ACCEPTED row. {"written": bool, "why"/"path"}. A row without a
    subcategory is not migrated (written False, counted by the caller)."""
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
    if a["card_key"] in _existing_keys(jf):
        return {"written": False, "why": f"card {a['card_key'][:12]} already filed"}
    with jf.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    with mf.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(metta_line(a) + "\n")
    write_manifest(root)
    return {"written": True, "path": jf.relative_to(root).as_posix()}


def read(root: Optional[Path] = None, subcategory: Optional[str] = None) -> Iterator[dict]:
    """Every atom on disk, MINUS retracted card_keys. The one way to read atoms."""
    from core import card_intake as ci
    root = Path(root or ROOT)
    gone = ci.retracted_keys()
    if not root.exists():
        return
    for f in sorted(root.rglob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            a = json.loads(line)
            if a.get("card_key") in gone:
                continue
            if subcategory and a.get("subcategory") != subcategory:
                continue
            yield a


def compute_manifest(root: Optional[Path] = None) -> dict:
    """From disk, every time: files, lines, live_lines, sha256."""
    from core import card_intake as ci
    root = Path(root or ROOT)
    gone = ci.retracted_keys()
    files, live_subs = {}, set()
    for f in sorted(list(root.rglob("*.jsonl")) + list(root.rglob("*.metta"))) if root.exists() else []:
        b = f.read_bytes()
        lines = [l for l in b.decode("utf-8").splitlines() if l.strip()]
        rel = f.relative_to(root).as_posix()
        entry = {"lines": len(lines), "sha256": hashlib.sha256(b).hexdigest()}
        if f.suffix == ".jsonl":
            live = [json.loads(l) for l in lines]
            live = [a for a in live if a.get("card_key") not in gone]
            entry["live_lines"] = len(live)
            live_subs |= {a.get("subcategory") for a in live}
        files[rel] = entry
    return {"computed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rule": "recomputed from disk on every write; retracted card_keys are on disk but not live",
            "files": files,
            "atom_files": sum(1 for k in files if k.endswith(".jsonl")),
            "atoms_total": sum(v["lines"] for k, v in files.items() if k.endswith(".jsonl")),
            "atoms_live": sum(v.get("live_lines", 0) for v in files.values()),
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
