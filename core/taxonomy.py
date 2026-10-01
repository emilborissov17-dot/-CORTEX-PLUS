#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/taxonomy.py — THE ONE LOADER of config/taxonomy.json (1 Oct 2026).

The tree is domain -> category -> subcategory. A subcategory is a BUNDLE of
keys, never one number. Everything that asks "which subcategory is this?" or
"where does this atom live?" asks here; nothing else parses the file.

REFUSAL IS THE ONLY FAILURE MODE. load() raises TaxonomyError on:
  * a file that cannot be read or parsed;
  * counts that differ from the file's own _meta.counts;
  * a duplicate id anywhere in the tree;
  * a category or subcategory id that is not prefixed by its parent's id
    (folder_for and is_system read the hierarchy from the id);
  * a category whose subgoal is not one of the five sub-goal names in
    config/target_config.json or the literal SYSTEM.
There is no partial tree and no default: a caller either gets the whole
validated tree or an exception.

DOMAIN E IS THE SYSTEM ITSELF and is never mixed into a world-facing number.
world_subcategories() and world_keys() are the world-facing listings; each one
filters with _is_world() and then re-checks its own output with _assert_world(),
which reads the domain id directly, so removing the filter makes the listing
raise rather than leak.

Usage:
  venv\\Scripts\\python.exe -m core.taxonomy --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAXONOMY = REPO / "config" / "taxonomy.json"
TARGET_CONFIG = REPO / "config" / "target_config.json"
KEY_MAP = REPO / "config" / "taxonomy_key_map.json"
ATOMS = "atoms"

SYSTEM = "SYSTEM"            # the subgoal literal for domain E's categories
SYSTEM_DOMAIN = "E"


class TaxonomyError(Exception):
    """Raised, never returned."""


def _read_json(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise TaxonomyError(f"cannot read {p}: {type(e).__name__}: {e}") from e


def subgoal_names(target_path: Path | None = None) -> set:
    """The five sub-goal names: the top-level object keys of target_config.json."""
    doc = _read_json(target_path or TARGET_CONFIG)
    names = {k for k, v in doc.items() if not k.startswith("_") and isinstance(v, dict)}
    if not names:
        raise TaxonomyError(f"{target_path or TARGET_CONFIG} names no sub-goal")
    return names


def load(path: Path | None = None, target_path: Path | None = None) -> dict:
    """The validated tree: {"meta", "domains", "by_id"}. Raises TaxonomyError."""
    doc = _read_json(path or TAXONOMY)
    meta = doc.get("_meta") or {}
    want = meta.get("counts")
    if not isinstance(want, dict):
        raise TaxonomyError("_meta.counts is missing")
    domains = doc.get("domains")
    if not isinstance(domains, list):
        raise TaxonomyError("'domains' is not a list")
    allowed = subgoal_names(target_path) | {SYSTEM}

    by_id: dict = {}

    def _claim(node_id, row):
        if not isinstance(node_id, str) or not node_id:
            raise TaxonomyError(f"a node has no id: {row!r:.120}")
        if node_id in by_id:
            raise TaxonomyError(f"duplicate id {node_id!r}")
        by_id[node_id] = row

    n_cat = n_sub = 0
    for d in domains:
        did = d.get("id")
        _claim(did, {"level": "domain", "id": did, "name_en": d.get("name_en")})
        for c in d.get("categories") or []:
            cid = c.get("id")
            _claim(cid, {"level": "category", "id": cid, "domain": did,
                         "name_en": c.get("name_en"), "subgoal": c.get("subgoal")})
            n_cat += 1
            if not str(cid).startswith(str(did)):
                raise TaxonomyError(f"category {cid!r} is not under domain {did!r}")
            if c.get("subgoal") not in allowed:
                raise TaxonomyError(f"category {cid!r}: subgoal {c.get('subgoal')!r} is not one of "
                                    f"{sorted(allowed)}")
            for s in c.get("subcategories") or []:
                sid = s.get("id")
                _claim(sid, {"level": "subcategory", "id": sid, "domain": did, "category": cid,
                             "name_en": s.get("name_en"), "subgoal": c.get("subgoal"),
                             "wanted_keys": list(s.get("wanted_keys") or [])})
                n_sub += 1
                if not str(sid).startswith(f"{cid}."):
                    raise TaxonomyError(f"subcategory {sid!r} is not under category {cid!r}")

    got = {"domains": len(domains), "categories": n_cat, "subcategories": n_sub}
    for k in ("domains", "categories", "subcategories"):
        if want.get(k) != got[k]:
            raise TaxonomyError(f"count mismatch: _meta.counts.{k}={want.get(k)!r}, tree has {got[k]}")
    return {"meta": meta, "domains": domains, "by_id": by_id, "counts": got}


def _tree(tree):
    return tree if tree is not None else load()


def subcategories(tree: dict | None = None) -> list:
    """Every subcategory row, in file order (all five domains, E included)."""
    return [r for r in _tree(tree)["by_id"].values() if r["level"] == "subcategory"]


def subcategory(sub_id: str, tree: dict | None = None) -> dict:
    r = _tree(tree)["by_id"].get(sub_id)
    if r is None or r["level"] != "subcategory":
        raise TaxonomyError(f"no subcategory {sub_id!r}")
    return r


def folder_for(sub_id: str, tree: dict | None = None) -> str:
    """atoms/<domain id>/<category id>/<subcategory id> — a path STRING only."""
    r = subcategory(sub_id, tree)
    return f"{ATOMS}/{r['domain']}/{r['category']}/{r['id']}"


def is_system(sub_id: str, tree: dict | None = None) -> bool:
    """True for a subcategory of domain E (the system itself)."""
    return subcategory(sub_id, tree)["domain"] == SYSTEM_DOMAIN


# ── the world-facing listings and their guard ────────────────────────────────
def _is_world(row: dict) -> bool:
    return row["domain"] != SYSTEM_DOMAIN


def _assert_world(rows: list) -> list:
    leaked = [r["id"] for r in rows if r.get("domain") == SYSTEM_DOMAIN]
    if leaked:
        raise TaxonomyError(f"domain {SYSTEM_DOMAIN} leaked into a world-facing listing: {leaked}")
    return rows


def world_subcategories(tree: dict | None = None) -> list:
    """Every subcategory a world-facing number may count. Domain E never."""
    return _assert_world([r for r in subcategories(tree) if _is_world(r)])


def load_key_map(path: Path | None = None, tree: dict | None = None) -> dict:
    """{key: subcategory id} from config/taxonomy_key_map.json, every target
    validated against the tree. Raises on an unreadable file or an unknown id."""
    doc = _read_json(path or KEY_MAP)
    keys = doc.get("keys")
    if not isinstance(keys, dict):
        raise TaxonomyError(f"{path or KEY_MAP}: 'keys' is not an object")
    t = _tree(tree)
    out = {}
    for k, v in keys.items():
        sid = v.get("subcategory") if isinstance(v, dict) else None
        subcategory(sid, t)                       # raises on an unknown id
        out[k] = sid
    return out


def world_keys(key_map: dict, tree: dict | None = None) -> dict:
    """{key: subcategory id} restricted to world subcategories. Domain E never."""
    t = _tree(tree)
    rows = [{"id": k, "sub": s, "domain": subcategory(s, t)["domain"]} for k, s in key_map.items()]
    kept = _assert_world([r for r in rows if _is_world(r)])
    return {r["id"]: r["sub"] for r in kept}


# ── selftest ──────────────────────────────────────────────────────────────────
def _imports_taxonomy(py: Path) -> bool:
    import ast
    try:
        t = ast.parse(py.read_text(encoding="utf-8"))
    except Exception:
        return False
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module in ("core.taxonomy", "core") and \
                any(a.name in ("taxonomy", "load", "load_key_map") for a in n.names):
            return True
        if isinstance(n, ast.Import) and any(a.name == "core.taxonomy" for a in n.names):
            return True
    return False


def selftest() -> dict:
    res: dict = {"integrations": {}, "facts": {}}
    try:
        t = load()
        res["integrations"]["config/taxonomy.json"] = (
            f"LIVE ({t['counts']['domains']}/{t['counts']['categories']}/{t['counts']['subcategories']})")
    except TaxonomyError as e:
        res["integrations"]["config/taxonomy.json"] = f"INERT ({e})"
        t = None
    try:
        res["integrations"]["config/target_config.json"] = f"LIVE ({len(subgoal_names())} sub-goals)"
    except TaxonomyError as e:
        res["integrations"]["config/target_config.json"] = f"INERT ({e})"
    if t is not None:
        try:
            km = load_key_map(tree=t)
            res["integrations"]["config/taxonomy_key_map.json"] = (
                f"LIVE ({len(km)} keys, {len(world_keys(km, t))} world-facing)")
        except TaxonomyError as e:
            res["integrations"]["config/taxonomy_key_map.json"] = f"INERT ({e})"
        res["facts"]["world subcategories"] = len(world_subcategories(t))
        res["facts"]["system (domain E) subcategories"] = sum(
            1 for r in subcategories(t) if r["domain"] == SYSTEM_DOMAIN)
    res["integrations"][f"{ATOMS}/ (folder_for target)"] = (
        "LIVE" if (REPO / ATOMS).is_dir() else "INERT (no atoms/ directory: folder_for returns a path string only)")
    users = sorted(p.relative_to(REPO).as_posix() for p in list((REPO / "tools").glob("*.py"))
                   + list((REPO / "core").glob("*.py")) + list((REPO / "scripts").glob("*.py"))
                   if p.name != "taxonomy.py" and _imports_taxonomy(p))
    res["integrations"]["callers outside test/ (tools/, core/, scripts/)"] = (
        f"LIVE ({', '.join(users)})" if users else "INERT (nothing imports core.taxonomy yet)")
    legacy = REPO / "config" / "domains_tree.json"
    res["integrations"]["config/domains_tree.json (replaced, not deleted)"] = (
        "still on disk (its readers: tools/ask.py readers config/domains_tree.json)"
        if legacy.exists() else "gone")
    res["ok"] = t is not None
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2, ensure_ascii=False))
        sys.exit(0 if r["ok"] else 1)
    print(__doc__)
