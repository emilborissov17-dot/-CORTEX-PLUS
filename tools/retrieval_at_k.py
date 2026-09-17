#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/retrieval_at_k.py — CAN THE EMBEDDER FIND A RELEVANT EPISODE AT ALL?

BEFORE THE T1 MEMORY ARM IS TRUSTED. T1's memory-on arm retrieves nearest episodes
with core/embed_index.search. If the embedder cannot put a relevant episode in the
top k, memory-on is memory-of-noise, and a null result would say nothing about
whether retrieved experience helps — only that nothing relevant was retrieved. That
is a different finding, and reporting one as the other would be the worst outcome
this test can produce.

RELEVANCE IS KNOWN BY CONSTRUCTION, not judged. A test task and an episode are
relevant iff they SHARE A LATENT PRIMITIVE (tools/transfer_tasks.py). The labels
never enter the text; they exist only here, as the answer key for scoring retrieval.
Nothing about the series says "linear_trend" — an embedder that scores well has found
the structure in the numbers.

WHAT IS MEASURED
  recall@1   share of test tasks whose TOP hit shares a primitive
  recall@5   share whose top 5 contain at least one that shares a primitive
  chance@k   the same, for a random episode ordering — the number that makes
             recall@k mean something. A recall@5 of 0.9 is impressive against a
             chance of 0.3 and meaningless against a chance of 0.88.
  holdout    the same three, over compositional hold-outs alone, which is the
             stratum the whole design turns on

THE EMBEDDER IS NAMED IN THE OUTPUT. Today it is generative qwen2.5:3b (dim 2048),
which is not an embedding model; that is recorded as debt in core/statements.py and
is the reason this file exists. The same command run after a dedicated embedding
model is installed produces the comparable number.

  venv\\Scripts\\python.exe tools/retrieval_at_k.py --selftest
  venv\\Scripts\\python.exe tools/retrieval_at_k.py --run
  venv\\Scripts\\python.exe tools/retrieval_at_k.py --run --model nomic-embed-text
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import transfer_tasks as TT    # noqa: E402

METHOD_VERSION = "retrieval_at_k/1"
OUT = BASE / "memory" / "retrieval_at_k.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relevant(test: dict, episode: dict) -> bool:
    """Known by construction: a shared latent primitive."""
    return bool(set(test["latent"]) & set(episode["latent"]))


def measure(tests: list, episodes: list, embed, index_dir: pathlib.Path,
            ks=(1, 5), seed: int = 20260917) -> dict:
    """Build the episode index, query with each test, score against the answer key."""
    from core import embed_index

    ep_texts = [TT.features(e) for e in episodes]
    mat, source = embed(ep_texts)
    vecs = {e["task_id"]: (row.tolist() if hasattr(row, "tolist") else list(row))
            for e, row in zip(episodes, mat)}
    embed_index.build(cache=vecs, out_dir=index_dir)
    by_id = {e["task_id"]: e for e in episodes}

    q_mat, q_source = embed([TT.features(t) for t in tests])
    if q_source != source:
        # Mixing a real embedding space with hashed fallbacks would make every number
        # below meaningless, and silently so.
        raise RuntimeError(f"episodes embedded as {source!r}, queries as {q_source!r} "
                           f"— refusing to score across two different spaces")

    rng = random.Random(seed)
    rows, hits = [], {k: 0 for k in ks}
    chance = {k: 0 for k in ks}
    ho_rows = []

    for t, q in zip(tests, q_mat):
        res = embed_index.search(q, k=max(ks), out_dir=index_dir)
        got = [by_id[r["key"]] for r in res if r["key"] in by_id]
        rel_flags = [relevant(t, e) for e in got]

        # chance: a random ordering of the SAME episode pool
        shuffled = episodes[:]
        rng.shuffle(shuffled)
        chance_flags = [relevant(t, e) for e in shuffled[:max(ks)]]

        row = {"task_id": t["task_id"], "stratum": t["stratum"],
               "latent": t["latent"],
               "top1_latent": got[0]["latent"] if got else None,
               "top1_relevant": bool(rel_flags[:1] and rel_flags[0]),
               "any_relevant_in_5": any(rel_flags[:5]),
               "top1_score": round(float(res[0]["score"]), 4) if res else None,
               "latent_sim_top1": round(TT.latent_similarity(t, got[0]), 3) if got else None,
               "surface_sim_top1": round(TT.surface_similarity(t, got[0]), 3) if got else None}
        rows.append(row)
        if t["stratum"] == "holdout_composition":
            ho_rows.append(row)
        for k in ks:
            if any(rel_flags[:k]):
                hits[k] += 1
            if any(chance_flags[:k]):
                chance[k] += 1

    n = len(tests)
    nh = len(ho_rows) or 1
    return {
        "ts": _now(), "method_version": METHOD_VERSION,
        "embedding_source": source, "n_tests": n, "n_episodes": len(episodes),
        "recall_at": {str(k): round(hits[k] / n, 4) for k in ks},
        "chance_at": {str(k): round(chance[k] / n, 4) for k in ks},
        "holdout_recall_at": {
            "1": round(sum(r["top1_relevant"] for r in ho_rows) / nh, 4),
            "5": round(sum(r["any_relevant_in_5"] for r in ho_rows) / nh, 4)},
        "n_holdout": len(ho_rows),
        "mean_latent_sim_top1": round(
            sum(r["latent_sim_top1"] or 0 for r in rows) / n, 4),
        "mean_surface_sim_top1": round(
            sum(r["surface_sim_top1"] or 0 for r in rows) / n, 4),
        "task_ledger_sha256": TT.ledger()["sha256"],
        "rows": rows,
    }


def _selftest() -> int:
    print("tools/retrieval_at_k.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    eps, tests = TT.memory_set(), TT.test_set()
    check("relevance is a shared primitive, both ways",
          relevant({"latent": ["a", "b"]}, {"latent": ["b"]})
          and not relevant({"latent": ["a"]}, {"latent": ["b"]}))
    check("a task is relevant to itself", relevant(tests[0], tests[0]))

    # A PERFECT embedder: identity on a one-hot of the latent set. If measure()
    # cannot score this at 1.0, the harness is broken, not the embedder.
    prims = list(TT.PRIMITIVES)
    seen = {}

    def oracle(texts):
        import numpy as np
        out = []
        for txt in texts:
            v = np.zeros(len(prims), dtype=float)
            for p in seen.get(txt, []):
                v[prims.index(p)] = 1.0
            out.append(v)
        return np.asarray(out), "oracle"

    for x in eps + tests:
        seen[TT.features(x)] = x["latent"]

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        got = measure(tests, eps, oracle, pathlib.Path(d))
    check(f"an oracle embedder scores recall@1 = 1.0 ({got['recall_at']['1']}) — "
          f"the harness can detect a perfect retriever",
          got["recall_at"]["1"] == 1.0)
    check("chance is computed and is below the oracle",
          got["chance_at"]["1"] < 1.0)
    check("hold-outs are scored separately", got["n_holdout"] >= 16)
    check("the task ledger sha is carried into the result",
          len(got["task_ledger_sha256"]) == 64)

    # A USELESS embedder: constant vector. Must NOT score above chance.
    def blind(texts):
        import numpy as np
        return np.ones((len(texts), 4), dtype=float), "blind"

    with tempfile.TemporaryDirectory() as d:
        bad = measure(tests, eps, blind, pathlib.Path(d))
    check(f"a constant-vector embedder does not beat chance at 5 "
          f"({bad['recall_at']['5']} vs chance {bad['chance_at']['5']})",
          bad["recall_at"]["5"] <= bad["chance_at"]["5"] + 0.15)

    # mixing two embedding spaces must be refused, not averaged
    calls = {"n": 0}

    def flaky(texts):
        import numpy as np
        calls["n"] += 1
        return (np.ones((len(texts), 4)),
                "real" if calls["n"] == 1 else "hashed_fallback")

    with tempfile.TemporaryDirectory() as d:
        try:
            measure(tests, eps, flaky, pathlib.Path(d))
            ok = False
        except RuntimeError as e:
            ok = "two different spaces" in str(e)
    check("scoring across two embedding spaces is REFUSED by name", ok)

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL 8 checks passed")
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--model", default=None,
                    help="ollama model for embedding; default = interval_head's")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.run:
        ap.error("--run or --selftest")

    from core import interval_head as IH
    model = a.model or IH.EMBED_MODEL

    def embed(texts):
        return IH.embed(texts, model=model)

    eps, tests = TT.memory_set(), TT.test_set()
    out_dir = BASE / "memory" / "embed_index_t1" / model.replace(":", "_")
    got = measure(tests, eps, embed, out_dir)
    got["model"] = model

    print(f"embedder            {model}  ({got['embedding_source']})")
    print(f"episodes / tests    {got['n_episodes']} / {got['n_tests']}")
    print(f"recall@1            {got['recall_at']['1']}   (chance {got['chance_at']['1']})")
    print(f"recall@5            {got['recall_at']['5']}   (chance {got['chance_at']['5']})")
    print(f"hold-out recall@1   {got['holdout_recall_at']['1']}  "
          f"@5 {got['holdout_recall_at']['5']}   (n={got['n_holdout']})")
    print(f"mean latent sim@1   {got['mean_latent_sim_top1']}")
    print(f"mean surface sim@1  {got['mean_surface_sim_top1']}")
    print(f"task ledger sha256  {got['task_ledger_sha256']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in got.items() if k != "rows"},
                            ensure_ascii=False) + "\n")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
