#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/knowledge.py — WHAT THE BRAIN CAN REACH. (C-OC-3 Part 1, 1 Oct 2026.)

Emil, R27: "Inside there can be very valuable and important information that will
not pass only because you set criteria that not every source meets." So the store
has ONE criterion, and it is on us, not on the source: what we attribute to a
source must really be in that source.

    ingest(source_id, text, url, origin)  every fetched page, WHOLE, as statements
                                          (core.statements.ingest_text: numbered
                                          sentences with its no-loss proof) appended
                                          to memory/statements.jsonl. A page with the same content
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
    """ONE LINE PER RECORD (C-TURN-1 7a): an element of an array of objects is one
    record, written with everything nested in it as dotted keys
    ("events.3: id=EONET_1; title=Flood; categories.0.id=floods; ..."); the root's
    own scalars are one line. Every scalar is proven present (FlattenLostValue)."""
    lines: list = []

    def flat(d, prefix=""):
        parts = []
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, (dict, list)):
                    parts.extend(flat(v, f"{prefix}{k}."))
                else:
                    parts.append(f"{prefix}{k}={_scalar(v)}")
        elif isinstance(d, list):
            if d and all(not isinstance(x, (dict, list)) for x in d):
                parts.append(f"{prefix.rstrip('.')}=[{', '.join(_scalar(x) for x in d)}]")
            else:
                for i, x in enumerate(d):
                    if isinstance(x, (dict, list)):
                        parts.extend(flat(x, f"{prefix}{i}."))
                    else:
                        parts.append(f"{prefix}{i}={_scalar(x)}")
        return parts

    def is_records(v):
        return isinstance(v, list) and v and any(isinstance(x, dict) for x in v)

    def walk(node, p):
        if isinstance(node, dict):
            own = {k: v for k, v in node.items() if not is_records(v)}
            if own:
                lines.append(f"{p or '$'}: " + "; ".join(flat(own)))
            for k, v in node.items():
                if is_records(v):
                    walk(v, f"{p}.{k}" if p else str(k))
        elif isinstance(node, list):
            for i, x in enumerate(node):
                q = f"{p}.{i}" if p else str(i)
                if isinstance(x, dict):
                    lines.append(f"{q}: " + "; ".join(flat(x)))
                elif isinstance(x, list):
                    walk(x, q)
                else:
                    lines.append(f"{q}: {_scalar(x)}")
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


class PdfUnreadable(ValueError):
    """The bytes are not a PDF pypdf can read, or hold no text layer."""


def pdf_text(data: bytes) -> str:
    """The text layer of a PDF, page by page (pypdf, C-TURN-1 7b). RAISES
    PdfUnreadable when there is none — a scanned PDF is not silently empty."""
    import io
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = [(pg.extract_text() or "").strip() for pg in reader.pages]
    except Exception as exc:                                         # noqa: BLE001
        raise PdfUnreadable(f"{type(exc).__name__}: {exc}") from exc
    text = "\n".join(p for p in pages if p)
    if not text.strip():
        raise PdfUnreadable(f"no text layer in {len(pages)} page(s)")
    return text


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
    seen_path = Path(seen_path or SEEN_CONTENT)
    seen = _read_json(seen_path, {})
    out = _ingest_one(source_id, text, url, origin, Path(store or STORE), seen, extra)
    if out["outcome"] != "SKIPPED_SAME_CONTENT":
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return out


def ingest_batch(items, store: Optional[Path] = None, seen_path: Optional[Path] = None) -> dict:
    """Many (source_id, text, url, origin) at once: the seen-content index is read
    once and written once, not once per item."""
    store, seen_path = Path(store or STORE), Path(seen_path or SEEN_CONTENT)
    seen = _read_json(seen_path, {})
    tot = {"items": 0, "new_content": 0, "skipped_same_content": 0, "statements_added": 0,
           "already_held": 0, "lost_text": 0}
    for it in items:
        tot["items"] += 1
        try:
            r = _ingest_one(it["source_id"], it["text"], it.get("url", ""), it.get("origin", "web"), store, seen,
                            it.get("extra"))
        except Exception as exc:                                     # noqa: BLE001
            if type(exc).__name__ != "SegmentationLostText":
                raise
            tot["lost_text"] += 1
            continue
        if r["outcome"] == "SKIPPED_SAME_CONTENT":
            tot["skipped_same_content"] += 1
            continue
        tot["new_content"] += 1
        tot["statements_added"] += r["added"]
        tot["already_held"] += r.get("already_held", 0)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    return tot


def _ingest_one(source_id: str, text: str, url: str, origin: str, store: Path, seen: dict,
                extra: Optional[dict] = None) -> dict:
    from core import statements as st
    h = hashlib.sha256(f"{source_id}|{text}".encode("utf-8")).hexdigest()
    if h in seen:
        return {"source_id": source_id, "outcome": "SKIPPED_SAME_CONTENT", "added": 0}
    rep = st.ingest_text(source_id, text, url=url, origin=origin,
                         extra={"host": host_of(url), "content_sha256": h, **(extra or {})},
                         mode="line" if (extra or {}).get("granularity") == "record" else None)
    # a CHANGED page from the same source repeats most of its sentences (a live
    # feed with one new row): those were written from the earlier page and are
    # not written again. Repeats inside ONE page are kept — that page is whole.
    before = _sentences_of(store).setdefault(source_id, set())
    new_recs = [r for r in rep["records"] if r["sentence"] not in before]
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8", newline="\n") as fh:
        for r in new_recs:
            fh.write(json.dumps(r, ensure_ascii=False) + NL)
    before.update(r["sentence"] for r in new_recs)
    seen[h] = {"source_id": source_id, "url": url, "origin": origin, "sentences": rep["sentences"],
               "added": len(new_recs), "ts": _now()}
    return {"source_id": source_id, "outcome": rep["outcome"], "added": len(new_recs),
            "already_held": rep["sentences"] - len(new_recs), "segmentation": rep.get("segmentation")}


# ── existing caches (C-OC-3 Part 2) ─────────────────────────────────────────
# Each ITEM is ingested under its own url, so one article seen in many daily
# files is one source and its sentences are held once. A model's own `analysis`
# block is NOT a source's words and is not ingested.
CACHES = {
    "web_intelligence": REPO / "memory" / "web_intelligence",
    "transcript_cache": REPO / "memory" / "transcript_cache",
    "news": REPO / "news",
    "browse_sources": REPO / "memory" / "browse_sources",
}
_ITEM_LISTS = ("raw_items", "youtube_items", "rss", "gdelt", "github_repos", "arxiv_papers")


def _item_text(it: dict) -> str:
    parts = [str(it.get(k)).strip() for k in ("title", "summary", "snippet", "description", "text")
             if it.get(k)]
    return ". ".join(p.rstrip(".") for p in parts) + ("." if parts else "")


def cache_items(origin: str, root: Optional[Path] = None):
    """Yield {source_id, text, url, origin} for one cache. Unreadable files are
    yielded as {"unreadable": path} so they are counted, not lost."""
    root = Path(root or CACHES[origin])
    files = sorted(root.rglob("*.json")) if root.exists() else []
    for f in files:
        try:
            blob = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            yield {"unreadable": str(f)}
            continue
        try:
            rel = f.resolve().relative_to(REPO).as_posix()
        except ValueError:
            rel = f.as_posix()
        if origin == "transcript_cache":
            # the source_id core/statements.py --ingest already used, so the
            # transcripts ingested before are recognised as held
            if not isinstance(blob, dict):
                continue
            text, vid = blob.get("transcript") or "", blob.get("video_id")
            if text:
                yield {"source_id": rel, "text": text, "origin": "transcript",
                       "url": f"https://www.youtube.com/watch?v={vid}" if vid else ""}
            continue
        if origin == "browse_sources":
            yield {"source_id": rel, "text": flatten_json(blob), "origin": "browse_source",
                   "url": (blob.get("source_url") or "") if isinstance(blob, dict) else ""}
            continue
        if not isinstance(blob, dict):
            continue
        for key in _ITEM_LISTS:
            for i, it in enumerate(blob.get(key) or []):
                if not isinstance(it, dict):
                    continue
                text = _item_text(it)
                if not text:
                    continue
                url = it.get("link") or it.get("url") or ""
                yield {"source_id": f"url:{url}" if url else f"{rel}#{key}{i}", "text": text,
                       "url": url, "origin": origin}
        if isinstance(blob.get("podcast"), str) and blob["podcast"].strip():
            yield {"source_id": f"{rel}#podcast", "text": blob["podcast"], "url": "", "origin": origin}


def ingest_caches(origins=None, roots: Optional[dict] = None, store=None, seen_path=None) -> dict:
    """Counts per origin."""
    out = {}
    for origin in origins or CACHES:
        unreadable = []

        def items():
            for it in cache_items(origin, (roots or {}).get(origin)):
                if "unreadable" in it:
                    unreadable.append(it["unreadable"])
                    continue
                yield it
        t0 = time.time()
        tot = ingest_batch(items(), store=store, seen_path=seen_path)
        tot["unreadable_files"] = len(unreadable)
        tot["seconds"] = round(time.time() - t0, 1)
        out[origin] = tot
    return out


_HELD: dict = {}


def _sentences_of(store: Path) -> dict:
    """source_id -> sentences already in `store`, read once per process per store."""
    key = str(Path(store).resolve())
    if key not in _HELD:
        idx: dict = {}
        for r in statements(store):
            idx.setdefault(r.get("source_id"), set()).add(r.get("sentence"))
        _HELD[key] = idx
    return _HELD[key]


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
    def flush():
        nonlocal mat, new_ids, new_vecs
        if not new_vecs:
            return
        arr = np.asarray(new_vecs, dtype="float32")
        arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
        mat = arr if mat.shape[0] == 0 else np.vstack([mat, arr])
        ids.extend(new_ids)
        vp.parent.mkdir(parents=True, exist_ok=True)
        np.save(vp, mat)
        ip.write_text(json.dumps(ids), encoding="utf-8")
        new_ids, new_vecs = [], []

    for n, i in enumerate(range(0, len(todo), 256), 1):
        chunk = todo[i:i + 256]
        vecs = embed([r["sentence"] for r in chunk])
        new_ids += [r["id"] for r in chunk]
        new_vecs += vecs
        done += len(chunk)
        if n % 20 == 0:                       # checkpoint: a killed run keeps what it embedded
            flush()
        if budget_s is not None and time.time() - t0 > budget_s:
            break
    flush()
    held = set(ids)
    remaining = len([r for r in statements(store) if r["id"] not in held])
    secs = round(time.time() - t0, 1)
    return {"embedded": done, "seconds": secs, "per_s": round(done / secs, 1) if secs else None,
            "remaining": remaining}


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


FIELD_INDEX = KDIR / "granularity_field.json"
_PATH = re.compile(r"^((?:\$|[\w\-]+)(?:\.[\w\-]+)*): ")


def record_key(sentence: str) -> Optional[str]:
    """The record a FIELD-level JSON statement belongs to: its path up to the first
    array index after the root ("events.0.geometry.0" -> "events.0"; "1.0" -> "1.0")."""
    m = _PATH.match(sentence or "")
    if not m:
        return None
    segs = m.group(1).split(".")
    for i, seg in enumerate(segs):
        if seg.isdigit() and i > 0:
            return ".".join(segs[: i + 1])
    return segs[0]


def mark_field_granularity(store=None, out: Optional[Path] = None) -> dict:
    """C-TURN-1 7a. Rows stored BEFORE a JSON record became one statement stay as
    they are; this index marks them granularity "field" with their record key, so
    the reader can collapse them by record. -> rows marked per source."""
    idx, per_source = {}, {}
    rows = statements(store)
    # a page was a flattened JSON body when its FIRST statement is the flattener's
    # root line ("$: ..." or "0: ..."); an HTML page's "Note: ..." is not a path
    json_pages = {r.get("content_sha256") for r in rows
                  if r.get("index") == 0 and re.match(r"^(\$|\d+)(\.\d+)*: ", r.get("sentence") or "")}
    for r in rows:
        if r.get("granularity") == "record" or r.get("content_sha256") not in json_pages:
            continue
        key = record_key(r.get("sentence"))
        if key is None:
            continue
        idx[r["id"]] = key
        per_source[r.get("source_id")] = per_source.get(r.get("source_id"), 0) + 1
    o = Path(out or FIELD_INDEX)
    o.parent.mkdir(parents=True, exist_ok=True)
    o.write_text(json.dumps({"computed_utc": _now(), "granularity": "field", "rows": idx}), encoding="utf-8")
    return per_source


def collapse_fields(items: list, field_index: dict) -> list:
    """Field-level statements of ONE record (same source, same record key) become
    one item, at the best relevance among them."""
    out, groups = [], {}
    for it in items:
        key = field_index.get(it.get("id")) if it.get("type") == "statement" else None
        if key is None:
            out.append(it)
            continue
        g = groups.get((it.get("source_id"), key))
        if g is None:
            g = {**it, "granularity": "field-collapsed", "record": key, "ids": [it["id"]], "texts": [it["text"]]}
            groups[(it.get("source_id"), key)] = g
            out.append(g)
        else:
            g["ids"].append(it["id"])
            g["texts"].append(it["text"])
            g["relevance"] = max(g["relevance"], it["relevance"])
    for g in groups.values():
        g["text"] = " | ".join(g.pop("texts"))
    return out


def read(need: str, k: int = 20, embed: Callable = None, store=None, vec_path=None, ids_path=None,
         labels_path=None, atoms_root=None, with_vectors: bool = True, field_index: Optional[dict] = None) -> list:
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
    if field_index is None:
        field_index = (_read_json(FIELD_INDEX, {}) or {}).get("rows", {}) if FIELD_INDEX.exists() else {}
    items = collapse_fields(items, field_index)
    items.sort(key=lambda x: (-x["relevance"], -x["corroborated_by"]))
    return items[:k]


# ── coverage, through this module only (C-OC-3 Part 4) ──────────────────────
CHANGE_MAX_AGE_DAYS = 45
INDEPENDENT = ("independent", "adversarial")


def subcategory_counts(labels_path=None, atoms_root=None) -> tuple:
    """({sub_id: {"statements": n | None, "measurements": [atoms]}}, labels_present).
    statements is None everywhere when the statement labels have not been computed:
    an absent count is MISSING, never a zero."""
    from core import atoms as _atoms
    lp = Path(labels_path or LABELS)
    labels = (_read_json(lp, {}) or {}).get("labels") if lp.exists() else None
    out: dict = {}
    if labels is not None:
        for lab in labels.values():
            s = lab.get("subcategory")
            if s and s not in ("unplaced", "pending_vector"):
                out.setdefault(s, {"statements": 0, "measurements": []})["statements"] += 1
    for a in _atoms.read(root=atoms_root):
        s = a.get("subcategory")
        if s:
            out.setdefault(s, {"statements": 0 if labels is not None else None, "measurements": []})
            out[s]["measurements"].append(a)
    return out, labels is not None


def _key_seen(rows: list, today) -> bool:
    """STATE + CHANGE + SOURCE on ONE key: a numeric value, a day-dated period at
    most CHANGE_MAX_AGE_DAYS old, and an independent or adversarial source."""
    from datetime import date
    from core import atoms as _atoms
    state = any(isinstance(a.get("value"), (int, float)) for a in rows)
    change = False
    for a in rows:
        if _atoms.period_granularity(a.get("period")) == "day":
            try:
                change |= (today - date.fromisoformat(str(a["period"])[:10])).days <= CHANGE_MAX_AGE_DAYS
            except ValueError:
                pass
    source = any(a.get("source_class") in INDEPENDENT for a in rows)
    return state and change and source


def coverage(today, labels_path=None, atoms_root=None, tree=None) -> dict:
    """KNOWN · MEASURED · CURRENT · SEEN per world subcategory and in total.
      KNOWN    at least one statement or measurement (MISSING while labels are absent)
      MEASURED at least one measurement atom
      CURRENT  at least one atom whose period is inside its granularity's bound
      SEEN     one key carries STATE + CHANGE + SOURCE (see _key_seen)"""
    from core import atoms as _atoms
    from core import taxonomy as tx
    tree = tree or tx.load()
    counts, labels_present = subcategory_counts(labels_path, atoms_root)
    per_sub, per_domain = {}, {}
    for s in tx.world_subcategories(tree):
        c = counts.get(s["id"], {"statements": 0 if labels_present else None, "measurements": []})
        atoms = c["measurements"]
        by_key: dict = {}
        for a in atoms:
            by_key.setdefault(a.get("key"), []).append(a)
        row = {"statements": c["statements"], "measurements": len(atoms),
               "measured": bool(atoms),
               "current": any(_atoms.period_is_current(a.get("period"), today) for a in atoms),
               "seen": any(_key_seen(rows, today) for rows in by_key.values())}
        row["known"] = (None if c["statements"] is None and not atoms
                        else bool(atoms) or bool(c["statements"]))
        per_sub[s["id"]] = row
        d = per_domain.setdefault(s["domain"], {"known": 0, "measured": 0, "current": 0, "seen": 0, "of": 0,
                                                "known_missing": 0})
        d["of"] += 1
        for k in ("measured", "current", "seen"):
            d[k] += int(row[k])
        if row["known"] is None:
            d["known_missing"] += 1
        else:
            d["known"] += int(row["known"])
    n = len(per_sub)

    def total(k):
        if k == "known" and not labels_present:
            return None                     # MISSING: statement labels not computed
        return sum(1 for r in per_sub.values() if r[k])
    return {"world": {k: total(k) for k in ("known", "measured", "current", "seen")} | {"of": n},
            "per_domain": per_domain, "per_subcategory": per_sub,
            "statement_labels": "present" if labels_present else "MISSING",
            "rule": {"KNOWN": "at least one statement (by its subcategory label) or measurement atom",
                     "MEASURED": "at least one non-retracted measurement atom",
                     "CURRENT": f"an atom whose period is day-dated <= {_atoms.CURRENT_DAY_DAYS} d old, month-dated "
                                f"<= {_atoms.CURRENT_MONTH_DAYS} d after the month ends, or year-dated >= this "
                                f"year - {_atoms.CURRENT_YEAR_BACK}",
                     "SEEN": f"one key with a numeric value, a day-dated period <= {CHANGE_MAX_AGE_DAYS} d old "
                             f"and an independent or adversarial source class"}}


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
    from scripts import data_feed_reader as _w
    passes = "ingest=_kn.ingest" in inspect.getsource(_w.main)
    res["integrations"]["worker ingests every fetched page"] = (
        "LIVE" if "ingest" in inspect.signature(_w.run).parameters and passes else "INERT")
    cov = (REPO / "tools" / "taxonomy_coverage.py").read_text(encoding="utf-8")
    board = (REPO / "tools" / "daily_board.py").read_text(encoding="utf-8")
    res["integrations"]["coverage reads through core.knowledge"] = (
        "LIVE" if "kn.coverage(" in cov and 't["knowledge"]["world"]' in board else "INERT")
    res["ok"] = KINDS.exists()
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    if "--embed-pending" in sys.argv:
        print(json.dumps(embed_pending()), flush=True)
        if "--label" not in sys.argv:
            sys.exit(0)
    if "--ingest-caches" in sys.argv:
        print(json.dumps(ingest_caches(), indent=1))
        sys.exit(0)
    if "--mark-field-granularity" in sys.argv:
        print(json.dumps(mark_field_granularity(), indent=1))
        sys.exit(0)
    if "--label" in sys.argv:
        print(json.dumps(label_all()))
        sys.exit(0)
    print(__doc__)
