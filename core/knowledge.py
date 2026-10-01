#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/knowledge.py — WHAT THE BRAIN CAN REACH. (C-OC-3 Part 1, 1 Oct 2026.)

Emil, R27: "Inside there can be very valuable and important information that will
not pass only because you set criteria that not every source meets." So the store
has ONE criterion, and it is on us, not on the source: what we attribute to a
source must really be in that source. Nothing else decides whether text enters.

    ingest(source_id, text, url, origin)  every fetched page, WHOLE, as statements
                                          (core.statements.ingest_text: numbered
                                          sentences with its no-loss proof) appended
                                          to memory/statements.jsonl — the store the
                                          brain reads. A page with the same content
                                          hash as one already ingested is skipped
                                          and counted.
    flatten_json(payload)                 a JSON body as "path: k=v; k=v" lines, so
                                          its content is sentences too; every scalar
                                          is proven present (FlattenLostValue).
    html_text(raw)                        an HTML body reduced to its text.
    embed_pending()                       nomic-embed-text vectors for statements
                                          that have none (memory/knowledge/).
    label_all()                           LABELS, added after intake. They order;
                                          they never remove:
        kind            measurement / event / claim / definition / other
                        (rules in config/statement_kinds.json; "other" is valid)
        subcategory     top-1 cosine to each subcategory's name + wanted_keys,
                        with the score; below SUBCAT_THRESHOLD -> "unplaced"
        source_class    config/reporter_independence.json, confirmed only
        corroborated_by number of DIFFERENT hosts with a statement at cosine
                        >= CORROBORATE_THRESHOLD
    read(need, k)                         statements AND measurement atoms together,
                                          ordered by relevance to the need, then by
                                          corroboration. Every item carries its labels;
                                          none is withheld for a missing label.

Statements are stored and retrievable by text before their vectors exist; a vector
only improves the ordering.

  venv\\Scripts\\python.exe -m core.knowledge --selftest
  venv\\Scripts\\python.exe -m core.knowledge --embed-pending
  venv\\Scripts\\python.exe -m core.knowledge --label
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STORE = REPO / "memory" / "statements.jsonl"
KDIR = REPO / "memory" / "knowledge"
SEEN_CONTENT = KDIR / "seen_content.json"
VECTORS = KDIR / "vectors.npy"
VECTOR_IDS = KDIR / "vector_ids.json"
LABELS = KDIR / "labels.json"
KINDS = REPO / "config" / "statement_kinds.json"
EMBED_MODEL = "nomic-embed-text"
OLLAMA = "http://localhost:11434/api/embed"
SUBCAT_THRESHOLD = 0.55
CORROBORATE_THRESHOLD = 0.90
NL = chr(10)


class FlattenLostValue(RuntimeError):
    """A scalar of the JSON body is absent from its flattened text. Raised."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_of(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


# ── bodies to text ──────────────────────────────────────────────────────────
def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    return str(v)


def flatten_json(payload, path: str = "") -> str:
    """One line per record: "path: k=v; k=v". A dict whose values are scalars is
    one line; nested dicts inline as dotted keys; lists recurse by index. Every
    scalar is proven present in the output (FlattenLostValue)."""
    lines: list = []

    def inline(d, prefix=""):
        parts = []
        for k, v in d.items():
            if isinstance(v, dict):
                parts.extend(inline(v, f"{prefix}{k}."))
            elif isinstance(v, list):
                parts.append(f"{prefix}{k}=[{', '.join(_scalar(x) if not isinstance(x, (dict, list)) else json.dumps(x, ensure_ascii=False) for x in v)}]")
            else:
                parts.append(f"{prefix}{k}={_scalar(v)}")
        return parts

    def walk(node, p):
        if isinstance(node, dict):
            if all(not isinstance(v, list) or all(not isinstance(x, (dict, list)) for x in v) for v in node.values()):
                lines.append(f"{p or '$'}: " + "; ".join(inline(node)))
            else:
                scal = {k: v for k, v in node.items() if not isinstance(v, (dict, list))}
                if scal:
                    lines.append(f"{p or '$'}: " + "; ".join(inline(scal)))
                for k, v in node.items():
                    if isinstance(v, (dict, list)):
                        walk(v, f"{p}.{k}" if p else str(k))
        elif isinstance(node, list):
            if node and all(not isinstance(x, (dict, list)) for x in node):
                lines.append(f"{p or '$'}: [{', '.join(_scalar(x) for x in node)}]")
            else:
                for i, x in enumerate(node):
                    walk(x, f"{p}.{i}" if p else str(i))
        else:
            lines.append(f"{p or '$'}: {_scalar(node)}")

    walk(payload, path)
    text = NL.join(lines)
    assert_flatten_lossless(payload, text)
    return text


def _leaves(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _leaves(v)
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v)
    else:
        yield node


def assert_flatten_lossless(payload, text: str) -> None:
    missing = [s for s in (_scalar(x) for x in _leaves(payload)) if s not in text]
    if missing:
        raise FlattenLostValue(f"{len(missing)} scalar(s) absent from the flattened text, e.g. {missing[:3]!r}")


def html_text(raw: str) -> str:
    """Text of an HTML page; script/style removed. Block elements end lines."""
    try:
        import lxml.html
        doc = lxml.html.fromstring(raw)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.drop_tree()
        for blk in doc.xpath("//p|//div|//li|//h1|//h2|//h3|//h4|//tr|//br|//section|//article"):
            blk.tail = (blk.tail or "") + NL
        txt = doc.text_content()
    except Exception:                                             # noqa: BLE001
        txt = re.sub(r"<[^>]+>", " ", raw)
    return NL.join(re.sub(r"[ \t]+", " ", l).strip() for l in txt.splitlines() if l.strip())


def body_to_text(raw: str, payload=None, content_type: str = "") -> tuple:
    """-> (text, form). JSON is flattened, HTML reduced, everything else as is."""
    ct = (content_type or "").lower()
    if payload is not None:
        return flatten_json(payload), "json"
    s = (raw or "").lstrip()
    if "html" in ct or s[:15].lower().startswith(("<!doctype html", "<html")):
        return html_text(raw), "html"
    if "pdf" in ct or s.startswith("%PDF"):
        return "", "pdf_unreadable"           # no PDF reader installed: recorded as a need
    return raw or "", "csv" if "csv" in ct else "text"


# ── the store ───────────────────────────────────────────────────────────────
def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def ingest(source_id: str, text: str, url: str = "", origin: str = "web",
           store: Optional[Path] = None, seen_path: Optional[Path] = None, extra: Optional[dict] = None) -> dict:
    """Every sentence of `text` into the store, unless this exact content from this
    source was ingested before. Returns counts; never refuses a page for its form."""
    from core import statements as st
    store = Path(store or STORE)
    seen_path = Path(seen_path or SEEN_CONTENT)
    h = hashlib.sha256(f"{source_id}|{text}".encode("utf-8")).hexdigest()
    seen = _read_json(seen_path, {})
    if h in seen:
        return {"source_id": source_id, "outcome": "SKIPPED_SAME_CONTENT", "added": 0}
    rep = st.ingest_text(source_id, text, url=url, origin=origin,
                         extra={"host": host_of(url), "content_sha256": h, **(extra or {})})
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rep["records"]:
            fh.write(json.dumps(r, ensure_ascii=False) + NL)
    seen[h] = {"source_id": source_id, "url": url, "origin": origin, "sentences": rep["sentences"], "ts": _now()}
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return {"source_id": source_id, "outcome": rep["outcome"], "added": rep["sentences"],
            "segmentation": rep.get("segmentation")}


def statements(store: Optional[Path] = None) -> list:
    p = Path(store or STORE)
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


# ── vectors ─────────────────────────────────────────────────────────────────
def embed_texts(texts: list, batch: int = 64) -> list:
    import requests
    out = []
    for i in range(0, len(texts), batch):
        r = requests.post(OLLAMA, json={"model": EMBED_MODEL, "input": texts[i:i + batch]}, timeout=600)
        r.raise_for_status()
        out.extend(r.json()["embeddings"])
    return out


def load_vectors(vec_path: Optional[Path] = None, ids_path: Optional[Path] = None):
    import numpy as np
    vp, ip = Path(vec_path or VECTORS), Path(ids_path or VECTOR_IDS)
    if not vp.exists() or not ip.exists():
        return [], np.zeros((0, 768), dtype="float32")
    return json.loads(ip.read_text(encoding="utf-8")), np.load(vp)


def embed_pending(limit: Optional[int] = None, budget_s: Optional[float] = None, embed: Callable = None,
                  store=None, vec_path=None, ids_path=None) -> dict:
    """Vectors for statements that have none. Stops at `limit` or `budget_s`."""
    import numpy as np
    embed = embed or embed_texts
    vp, ip = Path(vec_path or VECTORS), Path(ids_path or VECTOR_IDS)
    ids, mat = load_vectors(vp, ip)
    have = set(ids)
    todo = [r for r in statements(store) if r["id"] not in have]
    if limit is not None:
        todo = todo[:limit]
    t0, done = time.time(), 0
    new_ids, new_vecs = [], []
    for i in range(0, len(todo), 256):
        chunk = todo[i:i + 256]
        vecs = embed([r["sentence"] for r in chunk])
        new_ids += [r["id"] for r in chunk]
        new_vecs += vecs
        done += len(chunk)
        if budget_s is not None and time.time() - t0 > budget_s:
            break
    if new_vecs:
        arr = np.asarray(new_vecs, dtype="float32")
        arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
        mat = arr if mat.shape[0] == 0 else np.vstack([mat, arr])
        vp.parent.mkdir(parents=True, exist_ok=True)
        np.save(vp, mat)
        ip.write_text(json.dumps(ids + new_ids), encoding="utf-8")
    remaining = len([r for r in statements(store) if r["id"] not in set(ids + new_ids)])
    return {"embedded": done, "seconds": round(time.time() - t0, 1), "remaining": remaining}


# ── labels ──────────────────────────────────────────────────────────────────
def kind_of(sentence: str, rules: Optional[dict] = None) -> str:
    rules = rules if rules is not None else _read_json(KINDS, {}).get("rules", [])
    for rule in rules:
        if re.search(rule["pattern"], sentence, re.I):
            return rule["kind"]
    return "other"


def _subcat_matrix(embed: Callable):
    import numpy as np
    from core import taxonomy as tx
    subs = tx.subcategories()
    texts = [f"{s['name_en']}: {', '.join(k.replace('_', ' ') for k in s['wanted_keys'])}" for s in subs]
    arr = np.asarray(embed(texts), dtype="float32")
    arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
    return [s["id"] for s in subs], arr


def label_all(embed: Callable = None, store=None, vec_path=None, ids_path=None, out: Optional[Path] = None) -> dict:
    """Labels for every statement, rebuilt whole. Nothing is removed by a label."""
    import numpy as np
    from experiments.composers import provenance as prov
    embed = embed or embed_texts
    recs = statements(store)
    ids, mat = load_vectors(vec_path, ids_path)
    pos = {i: n for n, i in enumerate(ids)}
    sub_ids, sub_mat = _subcat_matrix(embed)
    rules = _read_json(KINDS, {}).get("rules", [])
    cfg = prov.reporter_config()
    labels = {}
    # subcategory per vectorised statement
    sub_of = {}
    if mat.shape[0]:
        sims = mat @ sub_mat.T
        best = sims.argmax(axis=1)
        for i, rid in enumerate(ids):
            sc = float(sims[i, best[i]])
            sub_of[rid] = (sub_ids[best[i]] if sc >= SUBCAT_THRESHOLD else "unplaced", round(sc, 4))
    # corroboration: distinct OTHER hosts with a near-duplicate statement
    host_by_row = {}
    rec_by_id = {r["id"]: r for r in recs}
    for rid, n in pos.items():
        host_by_row[n] = (rec_by_id.get(rid) or {}).get("host") or host_of((rec_by_id.get(rid) or {}).get("url", ""))
    corro = {}
    if mat.shape[0]:
        hosts = [host_by_row.get(n, "") for n in range(mat.shape[0])]
        for b0 in range(0, mat.shape[0], 1024):
            block = mat[b0:b0 + 1024] @ mat.T
            for i in range(block.shape[0]):
                n = b0 + i
                hit = np.nonzero(block[i] >= CORROBORATE_THRESHOLD)[0]
                corro[ids[n]] = len({hosts[j] for j in hit if hosts[j] and hosts[j] != hosts[n]})
    for r in recs:
        cls, _why = prov.reporter_class({"org": None, "url": r.get("url")}, cfg) if r.get("url") else ("unknown", "")
        sub, score = sub_of.get(r["id"], ("pending_vector", None))
        labels[r["id"]] = {"kind": kind_of(r["sentence"], rules), "subcategory": sub, "subcategory_score": score,
                           "source_class": cls, "corroborated_by": corro.get(r["id"], 0)}
    out = Path(out or LABELS)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"computed_utc": _now(), "labels": labels}, ensure_ascii=False), encoding="utf-8")
    return {"labelled": len(labels), "with_vectors": len(sub_of),
            "placed": sum(1 for v in sub_of.values() if v[0] != "unplaced")}


def contradictions(atoms: list) -> dict:
    """card_key -> number of other observations of the same key/place/period
    with a different value."""
    groups: dict = {}
    for a in atoms:
        groups.setdefault((a.get("key"), a.get("place"), a.get("period")), []).append(a)
    out = {}
    for g in groups.values():
        for a in g:
            out[a.get("card_key")] = sum(1 for b in g if b.get("value") != a.get("value"))
    return out


# ── the brain's one reader ──────────────────────────────────────────────────
_TOK = re.compile(r"[a-z0-9]+")


def _tok(s: str) -> set:
    return set(_TOK.findall((s or "").lower()))


def read(need: str, k: int = 20, embed: Callable = None, store=None, vec_path=None, ids_path=None,
         labels_path=None, atoms_root=None, with_vectors: bool = True) -> list:
    """Statements and measurement atoms for a need, ordered by relevance then
    corroboration. `need` is a subcategory id or free text. Every item is
    returned with whatever labels it has; nothing is withheld for a missing one."""
    import numpy as np
    from core import atoms as _atoms
    from core import taxonomy as tx
    need_sub, qtext = None, need
    try:
        s = tx.subcategory(need)
        need_sub = s["id"]
        qtext = f"{s['name_en']}: {', '.join(x.replace('_', ' ') for x in s['wanted_keys'])}"
    except tx.TaxonomyError:
        pass
    labels = (_read_json(Path(labels_path or LABELS), {}) or {}).get("labels", {})
    recs = statements(store)
    ids, mat = load_vectors(vec_path, ids_path)
    pos = {i: n for n, i in enumerate(ids)}
    qv = None
    if with_vectors and mat.shape[0]:
        try:
            qv = np.asarray((embed or embed_texts)([qtext])[0], dtype="float32")
            qv /= np.linalg.norm(qv) + 1e-9
        except Exception:                                           # noqa: BLE001
            qv = None
    qt = _tok(qtext)
    items = []
    for r in recs:
        lab = labels.get(r["id"], {})
        if qv is not None and r["id"] in pos:
            rel = float(mat[pos[r["id"]]] @ qv)
        else:
            t = _tok(r["sentence"])
            rel = len(qt & t) / (len(qt | t) or 1)
        if need_sub and lab.get("subcategory") == need_sub:
            rel += 1.0
        items.append({"type": "statement", "relevance": round(rel, 4),
                      "corroborated_by": lab.get("corroborated_by", 0), "labels": lab,
                      "id": r["id"], "text": r["sentence"], "url": r.get("url"), "origin": r.get("origin"),
                      "source_id": r.get("source_id")})
    atoms = list(_atoms.read(root=atoms_root))
    contra = contradictions(atoms)
    for a in atoms:
        text = f"{a.get('key')} {a.get('value')} {a.get('unit') or ''} {a.get('place') or ''} {a.get('period') or ''}"
        t = _tok(text.replace("_", " "))
        rel = len(qt & t) / (len(qt | t) or 1)
        if need_sub and a.get("subcategory") == need_sub:
            rel += 1.0
        items.append({"type": "measurement", "relevance": round(rel, 4),
                      "corroborated_by": 0, "contradicted_by": contra.get(a.get("card_key"), 0),
                      "labels": {k: a.get(k) for k in ("subcategory", "place", "period", "period_how", "unit",
                                                       "source_class", "times_seen")},
                      "id": a.get("card_key"), "text": text.strip(), "value": a.get("value"),
                      "source_id": a.get("source_id")})
    items.sort(key=lambda x: (-x["relevance"], -x["corroborated_by"]))
    return items[:k]


# ── selftest ────────────────────────────────────────────────────────────────
def selftest() -> dict:
    res = {"integrations": {}}
    res["integrations"]["memory/statements.jsonl (the store)"] = (
        f"LIVE ({sum(1 for _ in STORE.open(encoding='utf-8'))} statements)" if STORE.exists() else "INERT (empty)")
    ids, mat = load_vectors()
    res["integrations"]["memory/knowledge vectors"] = f"LIVE ({len(ids)} vectors)" if ids else "INERT (none yet)"
    res["integrations"]["memory/knowledge/labels.json"] = "LIVE" if LABELS.exists() else "INERT (label_all never ran)"
    res["integrations"]["config/statement_kinds.json"] = "LIVE" if KINDS.exists() else "INERT (missing)"
    try:
        import requests
        r = requests.post(OLLAMA, json={"model": EMBED_MODEL, "input": ["probe"]}, timeout=60)
        res["integrations"][f"ollama {EMBED_MODEL}"] = "LIVE" if r.ok else f"INERT (HTTP {r.status_code})"
    except Exception as exc:                                         # noqa: BLE001
        res["integrations"][f"ollama {EMBED_MODEL}"] = f"INERT ({type(exc).__name__})"
    import inspect
    from scripts import openclaw_axis_worker as _w
    passes = "ingest=_kn.ingest" in inspect.getsource(_w.main)
    res["integrations"]["worker ingests every fetched page"] = (
        "LIVE" if "ingest" in inspect.signature(_w.run).parameters and passes else "INERT")
    cov = (REPO / "tools" / "taxonomy_coverage.py").read_text(encoding="utf-8")
    res["integrations"]["coverage reads through core.knowledge"] = "LIVE" if "knowledge" in cov else "INERT"
    res["ok"] = KINDS.exists()
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    if "--embed-pending" in sys.argv:
        print(json.dumps(embed_pending()))
        sys.exit(0)
    if "--label" in sys.argv:
        print(json.dumps(label_all()))
        sys.exit(0)
    print(__doc__)
