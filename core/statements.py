#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/statements.py — EVERY SENTENCE IS KEPT. (STEP 2.1, 17 September 2026.)

THE PRINCIPLE, from Emil, 30 Jul and restated 17 Sep: NOTHING IS DROPPED.
Criteria decide how a statement is CHECKED, never whether it is KEPT.

That is a reversal of the design this file replaces, and the reversal is the whole
point. The earlier plan matched sentences against declared criteria and called the
matches "candidates"; everything else fell on the floor. A criterion that filters
is a criterion whose misses are invisible — there is no record of what was thrown
away, so the miss rate cannot be measured, only felt. Keeping everything makes the
question answerable: the type of a sentence becomes a LABEL it carries, not a
permit to exist.

WHAT THIS MODULE DOES, AND ONLY THIS
  * normalises a cached text (NFKC, dashes, quotes, whitespace)
  * segments it into NUMBERED sentences
  * proves nothing was lost, mechanically, on every single call
  * embeds each sentence and builds the index
  * logs counts per text

It assigns NO types, routes nothing, and asserts nothing about the world. Typing is
STEP 2.2 and lives elsewhere; a record here says only that a source contains this
sentence at this index.

THE NO-LOSS PROOF, which is the mechanical net behind the instruction
---------------------------------------------------------------------
A segmenter is written by tuning regexes, and a regex that silently eats an
abbreviation, a bullet, or a line of dialogue is the easiest bug in this file to
ship and the hardest to notice: the output still looks like sentences. So
`segment()` does not merely try not to drop text — it CHECKS. Every call compares
the concatenation of its output against the normalised input with whitespace
removed. If a single character is missing, it raises SegmentationLostText naming
the count and the neighbourhood.

Splitting differently from a human is allowed: two sentences merged, or one split
at an abbreviation, is a segmentation the audit can see and argue with. Losing a
character is not, and cannot be argued with afterwards because the evidence is
gone. So the guard is on CONSERVATION, not on correctness.

INDEXING REUSES THE INDEX THAT EXISTS
  vectors  core/interval_head.embed()  — sha256(model|text) cache on disk
  index    core/embed_index.build()    — one implementation, numpy, mmap'd
memory/embed_index was written on 22 Aug and its own --selftest reported
"NOT BUILT" and "NOT WIRED — nothing searches this index". This fills it. No second
index implementation is written here.

A FALLBACK RUN IS NAMED. interval_head.embed() returns ("hashed_fallback", ...)
when Ollama is unreachable, and in that case EVERY text is re-hashed so the space
stays coherent. That source string is stored on every record of the run: a hashed
vector is a placeholder for meaning, not meaning, and a later reader must be able
to tell the two apart without guessing.

  venv\\Scripts\\python.exe core/statements.py --selftest
  venv\\Scripts\\python.exe core/statements.py --ingest data/media_transcripts
  venv\\Scripts\\python.exe core/statements.py --ingest <dir> --dry
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import unicodedata
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
# Run as `python core/statements.py` the interpreter puts core/ on sys.path, not the
# repo root, and `from core.interval_head import ...` then fails. Measured, not
# guessed: the first real ingest died on exactly that after segmenting 971 sentences.
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

STORE = BASE / "memory" / "statements.jsonl"
INGEST_LOG = BASE / "memory" / "statements_ingest.jsonl"

METHOD_VERSION = "statements/1"
NL = chr(10)   # written without an escape: the shell mangles backslash-n here

# Characters that are the same mark in different clothes. Normalising them is what
# lets a quote be matched verbatim later: a curly apostrophe and a straight one look
# identical on a page and are different bytes to `in`.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_SQUOTE = dict.fromkeys(map(ord, "‘’‚‛′´`"), "'")
_DQUOTE = dict.fromkeys(map(ord, "“”„‟″«»"), '"')
_SPACES = dict.fromkeys(
    map(ord, "          "
             "     　"), " ")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)

# An end-of-sentence mark followed by space and something that starts a sentence.
# Deliberately simple: this splits, and the conservation check catches what it
# mangles. A cleverer rule here would buy tidier output and cost the guarantee.
# ONLY WHITESPACE IS CONSUMED. The first version put [\"')\]]* inside the match,
# which made re.split EAT the closing quote of a quoted sentence. The conservation
# check found it on the real corpus, 17 Sep 2026: 18 of 712 files lost 1-3
# characters each, every one of them a closing quote after a full stop
#   ...dangerous."That's why...   ->   the " was deleted
# The closer now belongs to the sentence on its left, via two fixed-width
# lookbehinds (re does not allow a variable-width one).
_SPLIT = re.compile(
    r"(?:(?<=[.!?…])|(?<=[.!?…][\"')\]]))"
    r"\s+(?=[\"'(\[]*[A-Z0-9А-Я])")

# Abbreviations after which a period does NOT end a sentence. Extending this list
# changes segmentation, never retention.
_ABBREV = ("mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "no.", "vs.", "etc.",
           "e.g.", "i.e.", "fig.", "al.", "approx.", "est.", "inc.", "ltd.",
           "u.s.", "u.k.", "u.n.", "p.m.", "a.m.")


class SegmentationLostText(RuntimeError):
    """The segmenter did not return every character it was given.

    Raised, never logged-and-continued. A statement store whose sentences do not
    reconstruct their source is a store nobody can audit: the missing text cannot
    be recovered later, and its absence leaves no trace to notice.
    """


class EmptyText(ValueError):
    """Nothing to segment. A named outcome, not a crash and not an empty success."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise(text: str) -> str:
    """NFKC + dashes, quotes, spaces, zero-width. Line structure is preserved.

    Newlines survive because a transcript's line breaks carry speaker turns and
    timestamps; collapsing them would merge two speakers into one sentence.
    """
    if text is None:
        raise EmptyText("normalise() got None")
    s = unicodedata.normalize("NFKC", str(text))
    s = s.translate(_ZERO_WIDTH).translate(_SPACES)
    s = s.translate(_DASHES).translate(_SQUOTE).translate(_DQUOTE)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _ends_with_abbrev(chunk: str) -> bool:
    tail = chunk.rstrip().lower()
    return any(tail.endswith(a) for a in _ABBREV)


def _bare(s: str) -> str:
    """Whitespace removed. The unit of the conservation check: segmentation may
    move whitespace between sentences, it may not lose a character of content."""
    return re.sub(r"\s+", "", s)


# An auto-transcript with no punctuation is not a failure of the source and must not
# be rescued by a model: restoring punctuation CHANGES THE TEXT, and every guard in
# this file rests on the stored sentence being what the source actually said.
# Measured on the corpus, 17 Sep 2026: This_Country_will_be_Gone_in_25_Years is
# 15,047 characters and segments into 13 "sentences" — roughly 190 words each,
# because the transcript carries almost no terminal punctuation.
#
# So a text that punctuates too little is cut BY WINDOW instead, and says so on
# every record it produces. A window is an arbitrary boundary and admits it; a
# model-restored full stop is an invented boundary that looks authored.
WINDOW_WORDS = 40          # words per segment when punctuation is absent
WINDOW_TRIGGER_WORDS = 120  # mean sentence length above which punctuation is absent


def _window_segments(norm: str, size: int = WINDOW_WORDS) -> list:
    """Fixed windows of `size` words, no overlap. Whitespace-only input -> []."""
    words = norm.split()
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def _mean_sentence_words(segs: list) -> float:
    if not segs:
        return 0.0
    return sum(len(s.split()) for s in segs) / len(segs)


def segment(text: str, mode: str | None = None) -> tuple:
    """Normalised text -> (sentences, mode). Raises if a character went missing.

    mode is "sentence" or "window"; pass it to force one, leave it None to choose
    by measurement. Returns ([], "sentence") for empty input, which the caller
    reports as NO_SENTENCES.
    """
    norm = normalise(text)
    if not norm:
        return [], "sentence"

    out = []
    for line in norm.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts, buf = [], ""
        for piece in _SPLIT.split(line):
            buf = (buf + " " + piece).strip() if buf else piece
            if not _ends_with_abbrev(buf):
                parts.append(buf)
                buf = ""
        if buf:
            parts.append(buf)
        out.extend(p for p in parts if p.strip())

    chosen = mode or ("window" if _mean_sentence_words(out) > WINDOW_TRIGGER_WORDS
                      else "sentence")
    if chosen == "window":
        out = _window_segments(norm)

    # THE CONSERVATION CHECK. Not a test — it runs on every call, in production.
    want, got = _bare(norm), _bare("".join(out))
    if want != got:
        i = next((n for n in range(min(len(want), len(got))) if want[n] != got[n]),
                 min(len(want), len(got)))
        raise SegmentationLostText(
            f"segmentation changed the text: {len(want)} chars in, {len(got)} out "
            f"(delta {len(got) - len(want)}); first divergence at {i}, "
            f"around {want[max(0, i - 40):i + 40]!r}")
    return out, chosen


def statement_id(source_id: str, index: int, sentence: str) -> str:
    """Stable across runs: the same sentence at the same index of the same source
    keeps its id, so re-ingesting a text updates rather than duplicates."""
    h = hashlib.sha256(f"{source_id}|{index}|{sentence}".encode("utf-8")).hexdigest()
    return h[:24]


def ingest_text(source_id: str, text: str, url: str = "", origin: str = "",
                extra: dict | None = None) -> dict:
    """Segment one text. Returns a report; writes nothing.

    origin is the PROVENANCE OF THE WORDS — "transcript", "article", "podcast".
    It travels with every record because a number heard in audio is a lead and a
    number read off a primary source is an observation, and only the origin
    distinguishes them once both are sentences in the same store.
    """
    sentences, seg_mode = segment(text)
    if not sentences:
        return {"source_id": source_id, "url": url, "origin": origin,
                "outcome": "NO_SENTENCES", "sentences": 0, "records": [],
                "chars_in": len(normalise(text or "")), "ts": _now()}

    records = []
    for i, s in enumerate(sentences):
        records.append({
            "id": statement_id(source_id, i, s),
            "source_id": source_id,
            "url": url,
            "origin": origin,
            "index": i,
            "sentence": s,
            "before": sentences[i - 1] if i else None,
            "after": sentences[i + 1] if i + 1 < len(sentences) else None,
            "chars": len(s),
            "segmentation": seg_mode,
            "method_version": METHOD_VERSION,
            "ingested_at": _now(),
            **(extra or {}),
        })
    return {"source_id": source_id, "url": url, "origin": origin,
            "outcome": "SEGMENTED", "segmentation": seg_mode,
            "sentences": len(sentences),
            "records": records, "chars_in": len(_bare(normalise(text))),
            "ts": _now()}


def embed_records(records: list, embed=None) -> tuple:
    """-> ({statement_id: vector}, source). Reuses core/interval_head.embed.

    The source string is returned and stored. "hashed_fallback" means Ollama was
    unreachable and the vectors are deterministic hashes: a placeholder for
    meaning, not meaning. Stored so nobody later reads a neighbour list built on
    hashes as if it were semantic.
    """
    if not records:
        return {}, "none"
    if embed is None:
        from core.interval_head import embed as embed
    mat, source = embed([r["sentence"] for r in records])
    vecs = {r["id"]: (row.tolist() if hasattr(row, "tolist") else list(row))
            for r, row in zip(records, mat)}
    return vecs, source


class ShardFull(RuntimeError):
    """A month shard is at its ceiling. Loud, and it does NOT grow.

    embed_index is exhaustive numpy over an mmap'd matrix. Its own selftest computes
    that 50,000 vectors is 410 MB, and this machine has already killed one cycle at
    99% RAM (15 Jul, a 0-byte log). A shard that quietly grew past the ceiling would
    turn a design choice into an out-of-memory night months later, with nothing in
    the record pointing back here. So the ceiling refuses and names itself.
    """


SHARD_CEILING = 50_000


def shard_for(when) -> str:
    """The MONTH OF THE SOURCE TEXT, as YYYY-MM.

    Sharding by source month, not ingest month: a re-ingest must land in the shard
    the text belongs to, or the same sentence appears twice in two shards and a
    neighbour search returns it twice.
    """
    if isinstance(when, str):
        return when[:7]
    return datetime.fromtimestamp(float(when), tz=timezone.utc).strftime("%Y-%m")


def index_dir(shard: str) -> pathlib.Path:
    from core import embed_index
    return embed_index.INDEX_DIR / shard


def _load_shard_vectors(out: pathlib.Path) -> dict:
    """{key: vector} already in a shard, or {} if it has none.

    Read back rather than tracked in memory: an ingest can be stopped between
    batches — this one was, by host memory pressure — and the next run must see
    what is on disk, not what this process happens to remember.
    """
    keys_file, vec_file = out / "keys.json", out / "vectors.npy"
    if not (keys_file.exists() and vec_file.exists()):
        return {}
    try:
        import numpy as np
        keys = json.loads(keys_file.read_text(encoding="utf-8"))
        mat = np.load(vec_file, mmap_mode="r")
        if len(keys) != mat.shape[0]:
            raise ValueError(f"{len(keys)} keys against {mat.shape[0]} vectors")
        return {k: mat[i].tolist() for i, k in enumerate(keys)}
    except Exception as e:                                       # noqa: BLE001
        raise ShardUnreadable(
            f"shard {out.name} exists and could not be read ({type(e).__name__}: {e}). "
            f"Refusing to rebuild it from this batch alone — that would delete every "
            f"vector already in it.") from None


class ShardUnreadable(RuntimeError):
    """An existing shard could not be read back. Refuse rather than overwrite it."""


def build_index(vectors: dict, shard: str,
                ceiling: int = SHARD_CEILING) -> dict:
    """Reuse core/embed_index.build, into ONE SHARD. No second implementation.

    memory/embed_index was written 22 Aug and never built; its own --selftest said
    "NOT BUILT" and "NOT WIRED". This fills it, keyed by statement id so a neighbour
    comes back as a statement rather than as an opaque hash. chromadb is untouched:
    it keeps its four existing readers and no statement is written there.
    """
    from core import embed_index
    out = index_dir(shard)

    # A SHARD ACCUMULATES. embed_index.build() writes keys.json and vectors.npy
    # FRESH from what it is handed, so passing only this batch silently replaced the
    # shard with the batch. Caught before this was committed: shard 2026-07 held
    # 1041 statements and 433 vectors — the last batch, and nothing before it. The
    # index has to be rebuilt from the union, because build() has no append mode.
    existing = _load_shard_vectors(out)
    total = len(set(existing) | set(vectors))
    if total > ceiling:
        raise ShardFull(
            f"shard {shard} would hold {total} vectors, ceiling {ceiling}. It does "
            f"NOT grow: embed_index is exhaustive numpy over an mmap'd matrix and "
            f"{ceiling} vectors is about {ceiling * 2048 * 4 / 2**20:.0f} MB. Split "
            f"the month or raise the ceiling deliberately, having read why it is here.")
    merged = {**existing, **vectors}    # a re-ingest overwrites its own rows, not others
    meta = embed_index.build(cache=merged, out_dir=out)
    meta["added"] = len(set(vectors) - set(existing))
    meta["kept"] = len(existing)
    # embed_index.build names it "count"; expose it under the name this layer logs.
    meta["vectors"] = meta.get("count", len(vectors))
    meta["shard"] = shard
    meta["ceiling"] = ceiling
    meta["bytes"] = sum(f.stat().st_size for f in out.glob("*") if f.is_file())
    return meta


def _rss_mb():
    """Peak RSS is not available portably; current RSS at the moment of the call is.
    Reuses the same psutil path core/blackbox.py uses, and returns None rather than
    guessing when psutil is absent."""
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 2**20, 1)
    except Exception:                                            # noqa: BLE001
        return None


def _selftest() -> int:
    print("core/statements.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    check("NFKC folds a full-width digit",
          normalise("５%") == "5%")
    check("a curly apostrophe becomes straight",
          normalise("it’s") == "it's")
    check("an em dash becomes a hyphen", normalise("a—b") == "a-b")
    check("a non-breaking space becomes a space",
          normalise("a b") == "a b")
    check("a zero-width space is removed", normalise("a​b") == "ab")
    check("newlines survive normalisation — they carry speaker turns",
          "\n" in normalise("one\ntwo"))

    s, _ = segment("The rate fell. It fell again! Did it? Yes.")
    check("four sentences are found", len(s) == 4)
    check("the question mark is kept with its sentence", s[2] == "Did it?")

    s, _ = segment("Dr. Smith reported 5%. The trend held.")
    check("an abbreviation does not split a sentence",
          len(s) == 2 and s[0].startswith("Dr. Smith"))

    s = segment("Speaker A: it rose.\nSpeaker B: it did not.")
    check("a line break separates two speakers", len(s) == 2)

    check("empty text yields no sentences and does not raise", segment("   ")[0] == [])
    check("the outcome for empty text is named, not an empty success",
          ingest_text("x", "")["outcome"] == "NO_SENTENCES")

    # conservation, the guard this file exists for
    long_text = ("Emissions rose 1.5% in 2024, the IEA said. "
                 "That is not 5% — it is far less. "
                 "Will it hold? Nobody claims to know; the projection is for 2030.")
    segs, segmode = segment(long_text)
    check("every character survives segmentation",
          _bare("".join(segs)) == _bare(normalise(long_text)))
    check("a negated number keeps its negation, because the sentence is whole",
          any("not 5%" in x for x in segs))

    rec = ingest_text("t1", long_text, origin="transcript")
    check("records are numbered from zero and carry their neighbours",
          rec["records"][1]["index"] == 1
          and rec["records"][1]["before"] == segs[0]
          and rec["records"][1]["after"] == segs[2])
    check("origin travels with every record",
          all(r["origin"] == "transcript" for r in rec["records"]))
    check("the id is stable for the same source/index/sentence",
          statement_id("t1", 0, segs[0]) == rec["records"][0]["id"])
    check("no record carries a type, a verdict or a truth value",
          not any(k in rec["records"][0]
                  for k in ("type", "verdict", "true", "confidence", "axis")))

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL " + str(19) + " checks passed")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ingest", metavar="DIR")
    ap.add_argument("--origin", default="transcript")
    ap.add_argument("--batch", type=int, default=150,
                    help="files per batch; each batch embeds and writes before the next")
    ap.add_argument("--limit", type=int, default=0, help="stop after N files (0 = all)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.ingest:
        ap.error("--ingest DIR or --selftest")

    root = pathlib.Path(a.ingest)
    if not root.exists():
        print(f"[STATEMENTS] {root} does not exist")
        return 1
    files = sorted(f for f in root.rglob("*") if f.is_file()
                   and f.suffix.lower() in (".txt", ".md", ".json"))
    if a.limit:
        files = files[:a.limit]
    print(f"[STATEMENTS] {len(files)} file(s) under {root}, batch {a.batch}")

    totals = {"files": 0, "sentences": 0, "window": 0, "sentence": 0,
              "no_sentences": 0, "unreadable": 0, "vectors": 0, "bytes": 0}
    shards_seen = set()

    for b0 in range(0, len(files), a.batch):
        batch = files[b0:b0 + a.batch]
        by_shard = {}
        reports = []
        for f in batch:
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                totals["unreadable"] += 1
                reports.append({"source_id": str(f), "outcome": "UNREADABLE",
                                "error": f"{type(e).__name__}: {e}"})
                continue
            if f.suffix.lower() == ".json":
                try:
                    blob = json.loads(raw)
                    raw = (blob.get("text") or blob.get("transcript")
                           or blob.get("content") or json.dumps(blob, ensure_ascii=False))
                except Exception:                                # noqa: BLE001
                    pass
            try:
                sid = str(f.resolve().relative_to(BASE))
            except ValueError:
                sid = str(f.resolve())
            sid = sid.replace("\\", "/")
            shard = shard_for(f.stat().st_mtime)
            try:
                rep = ingest_text(sid, raw, url="", origin=a.origin,
                                  extra={"shard": shard})
            except SegmentationLostText as e:
                totals["unreadable"] += 1
                reports.append({"source_id": sid, "outcome": "SEGMENTATION_LOST",
                                "error": str(e)})
                print(f"  SEGMENTATION_LOST {f.name[:40]}: {e}")
                continue
            totals["files"] += 1
            totals["sentences"] += rep["sentences"]
            if rep["outcome"] == "NO_SENTENCES":
                totals["no_sentences"] += 1
            else:
                totals[rep["segmentation"]] += 1
            reports.append({k: v for k, v in rep.items() if k != "records"})
            by_shard.setdefault(shard, []).extend(rep["records"])

        if a.dry:
            continue

        for shard, recs in sorted(by_shard.items()):
            if not recs:
                continue
            vecs, source = embed_records(recs)
            for r in recs:
                r["embedding_source"] = source
            try:
                meta = build_index(vecs, shard)
            except ShardFull as e:
                print(f"  SHARD FULL {shard}: {e}")
                reports.append({"shard": shard, "outcome": "SHARD_FULL",
                                "error": str(e)})
                continue
            shards_seen.add(shard)
            totals["vectors"] += meta.get("vectors", len(vecs))
            totals["bytes"] = max(totals["bytes"], meta.get("bytes", 0))
            rss = _rss_mb()
            print(f"  shard {shard}  {len(recs):5d} sentences  "
                  f"{meta.get('vectors', 0):5d} vectors  "
                  f"{meta.get('bytes', 0) / 2**20:6.2f} MB  rss {rss} MB  "
                  f"embed={source}")
            STORE.parent.mkdir(parents=True, exist_ok=True)
            with open(STORE, "a", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + NL)
            with open(INGEST_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": _now(), "shard": shard, "batch_files": len(batch),
                    "sentences": len(recs), "vectors": meta.get("vectors"),
                    "index_bytes": meta.get("bytes"), "rss_mb": rss,
                    "embedding_source": source, "ceiling": meta.get("ceiling"),
                    "method_version": METHOD_VERSION,
                }, ensure_ascii=False) + NL)
        if not a.dry:
            with open(INGEST_LOG, "a", encoding="utf-8") as fh:
                for rep in reports:
                    fh.write(json.dumps({**rep, "kind": "file"},
                                        ensure_ascii=False) + NL)

    print(f"[STATEMENTS] files={totals['files']} sentences={totals['sentences']} "
          f"(sentence-mode {totals['sentence']}, window-mode {totals['window']}, "
          f"empty {totals['no_sentences']}, unreadable {totals['unreadable']})")
    print(f"[STATEMENTS] shards={sorted(shards_seen)} vectors={totals['vectors']} "
          f"largest shard {totals['bytes'] / 2**20:.2f} MB  rss {_rss_mb()} MB")
    if a.dry:
        print("[STATEMENTS] --dry: nothing written, nothing embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
