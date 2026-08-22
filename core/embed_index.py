#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/embed_index.py — TOP-K OVER THE EMBEDDINGS, WITHOUT A DATABASE.

WHAT IT REPLACES
-----------------
Similarity search here has meant chromadb: a server-shaped dependency, a second
copy of every vector, and a process that has to be alive. At this scale that is
all cost and no benefit. The whole corpus is 69 vectors of 2048 floats — 0.5 MB
as float32 — and the exhaustive answer is a single matrix multiply.

    vectors are L2-NORMALISED AT BUILD TIME, so cosine similarity IS the dot
    product, and top-k is one np.dot plus an argpartition.

CHROMADB IS NOT IMPORTED AT RUNTIME. It is installed in this venv, so the rule
has to be enforced rather than assumed; test/test_embed_index.py asserts that
importing this module and running a search loads no chromadb.

MMAP, AND WHY IT MATTERS AT A SIZE THIS SMALL
-----------------------------------------------
np.load(mmap_mode="r") means the file is not read into the process at import.
It costs nothing today at 0.5 MB. It matters because the cycle already runs at
the edge of memory — the 15 Jul death was a cycle at 99% RAM leaving a 0-byte
log — and an index that grows to 50k vectors would be 400 MB read eagerly into a
process that cannot afford it. The access pattern is chosen now, while it is
free, rather than after the first out-of-memory night.

BACKENDS
---------
hnswlib is used when it imports, plain numpy otherwise, and `backend()` says
which. It is NOT installed here: `pip install --dry-run hnswlib` resolves
hnswlib-0.8.0, but it builds from source and this is the venv the 03:00 cycle
runs in. Adding a compiled extension the night before a controlled test would be
the second variable the test is supposed not to have. Exhaustive numpy is exact,
which an approximate index is not, and at 69 vectors against a 50k ceiling it is
also faster than building a graph.

NOT WIRED. Nothing searches this index.

    venv\\Scripts\\python.exe core/embed_index.py --selftest
    venv\\Scripts\\python.exe core/embed_index.py --build
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CACHE = BASE / "memory" / "embeddings_cache.json"
INDEX_DIR = BASE / "memory" / "embed_index"
VECTORS = "vectors.npy"
KEYS = "keys.json"
META = "meta.json"

# Above this, an exhaustive dot product stops being the obvious right answer and
# an approximate index earns its build cost. Stated as a number so the decision
# is inspectable rather than a feeling.
EXHAUSTIVE_CEILING = 50_000

DTYPE = np.float32


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def backend() -> str:
    """Which search backend is actually available in THIS interpreter."""
    try:
        import hnswlib  # noqa: F401
        return "hnswlib"
    except ImportError:
        return "numpy"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def normalise(mat: np.ndarray) -> np.ndarray:
    """L2-normalise rows. A zero row stays zero rather than becoming NaN.

    A zero vector has no direction, so it has no cosine similarity to anything.
    Dividing by its zero norm would put NaN into the matrix, and NaN propagates
    through argpartition to give a silently wrong top-k rather than an error.
    """
    mat = np.asarray(mat, dtype=DTYPE)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(DTYPE)


def load_cache(path: Optional[pathlib.Path] = None) -> dict:
    p = pathlib.Path(path) if path else CACHE
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return blob if isinstance(blob, dict) else {}


def build(cache: Optional[dict] = None,
          cache_path: Optional[pathlib.Path] = None,
          out_dir: Optional[pathlib.Path] = None) -> dict:
    """Write vectors.npy + keys.json + meta.json from the embeddings cache.

    Rows of the wrong length are DROPPED and counted, never padded. A vector of a
    different dimension came from a different model, and padding it would place a
    foreign thing in the same space and let it be returned as a neighbour.
    """
    data = cache if cache is not None else load_cache(cache_path)
    out = pathlib.Path(out_dir) if out_dir else INDEX_DIR
    out.mkdir(parents=True, exist_ok=True)

    keys, rows, dropped = [], [], []
    dim = None
    for key, vec in data.items():
        if not isinstance(vec, (list, tuple)) or not vec:
            dropped.append({"key": str(key)[:32], "why": "not a non-empty list"})
            continue
        if dim is None:
            dim = len(vec)
        if len(vec) != dim:
            dropped.append({"key": str(key)[:32],
                            "why": "dimension {} != {}".format(len(vec), dim)})
            continue
        try:
            rows.append(np.asarray(vec, dtype=DTYPE))
        except (TypeError, ValueError):
            dropped.append({"key": str(key)[:32], "why": "not numeric"})
            continue
        keys.append(str(key))

    if rows:
        mat = normalise(np.vstack(rows))
    else:
        mat = np.zeros((0, dim or 0), dtype=DTYPE)

    np.save(out / VECTORS, mat)
    (out / KEYS).write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")
    meta = {
        "built_at": _now(), "count": len(keys), "dim": int(dim or 0),
        "dtype": str(DTYPE.__name__), "normalised": True,
        "backend_available": backend(), "dropped": dropped[:50],
        "dropped_count": len(dropped),
        "exhaustive_ceiling": EXHAUSTIVE_CEILING,
        "source": str((pathlib.Path(cache_path) if cache_path else CACHE).name),
    }
    (out / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class Index:
    """An mmap'd view of the built index. Cheap to construct, cheap to drop."""

    def __init__(self, out_dir: Optional[pathlib.Path] = None):
        self.dir = pathlib.Path(out_dir) if out_dir else INDEX_DIR
        self.meta = {}
        self.keys: list = []
        self.vectors: Optional[np.ndarray] = None
        self._hnsw = None
        self._load()

    def _load(self) -> None:
        try:
            self.meta = json.loads((self.dir / META).read_text(encoding="utf-8"))
            self.keys = json.loads((self.dir / KEYS).read_text(encoding="utf-8"))
            # mmap_mode='r': the file is mapped, not read. See the docstring.
            self.vectors = np.load(self.dir / VECTORS, mmap_mode="r")
        except Exception:
            self.meta, self.keys, self.vectors = {}, [], None

    @property
    def ready(self) -> bool:
        return self.vectors is not None and len(self.keys) > 0

    @property
    def count(self) -> int:
        return len(self.keys)

    @property
    def dim(self) -> int:
        return int(self.meta.get("dim") or 0)

    def _hnsw_index(self):
        if self._hnsw is not None:
            return self._hnsw
        try:
            import hnswlib
        except ImportError:
            return None
        idx = hnswlib.Index(space="cosine", dim=self.dim)
        idx.init_index(max_elements=max(1, self.count), ef_construction=200, M=16)
        idx.add_items(np.asarray(self.vectors), np.arange(self.count))
        idx.set_ef(max(16, min(self.count, 64)))
        self._hnsw = idx
        return idx

    def search(self, query, k: int = 5, use_hnsw: Optional[bool] = None) -> list:
        """Top-k by cosine similarity. [{key, score, row}], best first.

        Returns [] rather than raising when the index is empty or the query is
        the wrong shape: a search is a question, and "nothing matches" is a valid
        answer to a question asked of an empty index.
        """
        if not self.ready or k <= 0:
            return []
        q = np.asarray(query, dtype=DTYPE).ravel()
        if q.size != self.vectors.shape[1]:
            return []
        n = np.linalg.norm(q)
        if n == 0:
            return []           # no direction, so no nearest anything
        q = q / n

        k = min(int(k), self.count)
        want_hnsw = backend() == "hnswlib" if use_hnsw is None else use_hnsw
        if want_hnsw:
            idx = self._hnsw_index()
            if idx is not None:
                labels, distances = idx.knn_query(q, k=k)
                return [{"key": self.keys[int(r)], "score": float(1.0 - d),
                         "row": int(r)}
                        for r, d in zip(labels[0], distances[0])]

        # Exhaustive and EXACT. Vectors are normalised, so dot == cosine.
        sims = np.asarray(self.vectors) @ q
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [{"key": self.keys[int(i)], "score": float(sims[int(i)]),
                 "row": int(i)} for i in top]

    def vector_for(self, key: str) -> Optional[np.ndarray]:
        try:
            return np.asarray(self.vectors[self.keys.index(key)])
        except (ValueError, TypeError, IndexError):
            return None


def search(query, k: int = 5, out_dir: Optional[pathlib.Path] = None) -> list:
    return Index(out_dir).search(query, k)


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/embed_index.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    print("  numpy                {}".format(np.__version__))
    print("  backend              {}".format(backend()))
    if backend() == "numpy":
        print("    hnswlib is not installed. `pip install --dry-run hnswlib` "
              "resolves 0.8.0, but it builds from source and this is the venv the")
        print("    03:00 cycle runs in — not a thing to add the night before a "
              "controlled test. Exhaustive numpy is EXACT, which an approximate")
        print("    index is not, and the ceiling for preferring it is {} vectors."
              .format(EXHAUSTIVE_CEILING))

    # find_spec, not import. Even the selftest declines to load it: the claim is
    # that this module never puts chromadb in the process, and a diagnostic that
    # breaks its own claim to report on it is not a diagnostic.
    import importlib.util as _ilu
    print("  chromadb             {}".format(
        "installed, and deliberately never imported here"
        if _ilu.find_spec("chromadb") else
        "not installed (fine — nothing here wants it)"))

    print("  embeddings cache     {} exists={} ({} entries)".format(
        CACHE.name, CACHE.exists(), len(load_cache())))
    if not CACHE.exists():
        ok = False

    idx = Index()
    if idx.ready:
        print("  index                LIVE ({} vectors, dim {}, built {})".format(
            idx.count, idx.dim, str(idx.meta.get("built_at"))[:19]))
    else:
        print("  index                NOT BUILT — run with --build")

    # Synthetic sanity, always, so the selftest means something on a fresh clone.
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="embed_selftest_"))
    fake = {"a": [1.0, 0.0, 0.0], "b": [0.9, 0.1, 0.0],
            "c": [0.0, 1.0, 0.0], "d": [0.0, 0.0, 1.0]}
    meta = build(cache=fake, out_dir=tmp)
    hits = Index(tmp).search([1.0, 0.0, 0.0], k=2)
    print("  synthetic top-k      {} -> {}".format(
        [h["key"] for h in hits], [round(h["score"], 3) for h in hits]))
    if [h["key"] for h in hits] != ["a", "b"]:
        print("    BAD — nearest neighbours are wrong")
        ok = False
    print("  synthetic build      {} vectors, dim {}, {} dropped".format(
        meta["count"], meta["dim"], meta["dropped_count"]))

    # And against the real cache, if it is there.
    if CACHE.exists():
        real_tmp = pathlib.Path(tempfile.mkdtemp(prefix="embed_real_"))
        m = build(out_dir=real_tmp)
        ri = Index(real_tmp)
        if ri.ready:
            probe = np.asarray(ri.vectors[0])
            hits = ri.search(probe, k=3)
            print("  real cache           {} vectors dim {}; a vector's own top hit "
                  "is itself at {:.4f}".format(
                      m["count"], m["dim"], hits[0]["score"] if hits else float("nan")))
            if not hits or abs(hits[0]["score"] - 1.0) > 1e-3:
                print("    BAD — a vector is not its own nearest neighbour")
                ok = False
            mb = ri.vectors.nbytes / 1e6
            print("  size                 {:.2f} MB mmap'd (eager read avoided; at "
                  "the {} ceiling it would be {:.0f} MB)".format(
                      mb, EXHAUSTIVE_CEILING,
                      EXHAUSTIVE_CEILING * ri.dim * 4 / 1e6))

    print("  consumers            NOT WIRED — nothing searches this index; "
          "chromadb is still what the rest of the repo reaches for")
    return 0 if ok else 1


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Embedding index: build and search.")
    p.add_argument("--build", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.build:
        print(json.dumps(build(), ensure_ascii=False, indent=2))
        return 0
    if args.stats:
        idx = Index()
        print(json.dumps({"ready": idx.ready, "count": idx.count,
                          "dim": idx.dim, "meta": idx.meta},
                         ensure_ascii=False, indent=2)[:4000])
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
