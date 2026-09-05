#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Score an adapter under the PAIRED RANKING metric.

    # 1. the probe — measure before committing to a batch size
    venv_train\\Scripts\\python.exe training/run_rank_eval.py \\
        --adapter models/adapters/k1b_control --probe 8

    # 2. the run
    venv_train\\Scripts\\python.exe training/run_rank_eval.py \\
        --adapter models/adapters/k1b_control \\
        --report claude/reports/K1B_CONTROL_RANK.md

THE ORDER MATTERS AND IS ENFORCED HERE, NOT BY MEMORY
    Candidate sets are built ONCE by rank_runner.build_items, before either model
    pass runs, and both passes iterate that same frozen list. The base pass and
    the adapter pass therefore see identical candidates by construction rather
    than by a seed both happen to agree on.

PRE-REGISTERED (training/rank_metric.py docstring, fixed 5 Sep 2026)
    - The CONTROL must land AT CHANCE (0.10, CI containing it). Above chance means
      this metric is contaminated too and runs A and B stay unrun.
    - A or B claims learning only with a CI entirely above 0.10 AND entirely above
      the control's on the same examples.
    - NLL is reported as a SECONDARY, labelled "distributional gain, not mapping",
      because a negative control already proved that is all it measures.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.eval_adapter import load_jsonl, resolve_stratum            # noqa: E402
from training.rank_metric import (CHANCE, K_DISTRACTORS, LENGTH_BAND,     # noqa: E402
                                  MIN_BUCKET, build_pool, norm, rank_verdict)
from training.rank_runner import (build_items, candidate_nlls,  # noqa: E402
                                  decide_knobs, forward_passes)


def token_len_fn(tok):
    return lambda s: len(tok(str(s), add_special_tokens=False)["input_ids"]) or 1


def load_model(base: str, adapter: str, device: str):
    quant = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(
        base, quantization_config=quant,
        device_map={"": 0} if device == "cuda" else None)
    model.eval()
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tok


def probe(model, tok, items, device, n: int, batch: int) -> dict:
    """FAILURE MODE 2 and 4, on the real model: does batching agree, what does it
    cost, and what does it peak at. Nothing is committed until this says so."""
    out = {"batch": batch, "fits": True, "n_items": n}
    for mode, b in (("unbatched", 1), ("batched", batch)):
        if device == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        vals = []
        try:
            for it in items[:n]:
                v, how = candidate_nlls(model, tok, it["prompt"],
                                        [it["target"]] + it["candidates"], device, b)
                if how == "oom_fallback":
                    out["fits"] = False
                vals.append(v)
        except torch.cuda.OutOfMemoryError:
            # A measurement, not a crash: "it did not fit" is exactly what the
            # decision rule needs to hear.
            out["fits"] = False
            out[mode] = {"seconds": None, "per_item": None, "peak_mib": None,
                         "how": "oom", "values": []}
            continue
        out[mode] = {
            "seconds": round(time.time() - t0, 2),
            "per_item": round((time.time() - t0) / max(1, n), 3),
            "peak_mib": (round(torch.cuda.max_memory_allocated() / 2**20, 1)
                         if device == "cuda" else None),
            "how": how,
            "values": vals,
        }
    diffs = [abs(a - b) for va, vb in zip(out["unbatched"]["values"],
                                          out["batched"]["values"])
             for a, b in zip(va, vb)]
    # No tolerance here. The pre-registered rule says BIT-IDENTICAL, and a
    # tolerance is exactly how "not merely close" turns back into "close enough".
    # An empty diff list means the batched pass never ran, which is NOT agreement.
    out["max_abs_diff"] = max(diffs) if diffs else None
    out["bit_identical"] = out["max_abs_diff"] == 0.0
    if out["unbatched"].get("seconds") and out["batched"].get("seconds"):
        out["speedup"] = round(out["unbatched"]["seconds"]
                               / out["batched"]["seconds"], 2)
    for m in ("unbatched", "batched"):
        out[m].pop("values", None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/Qwen2.5-3B-Instruct")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--holdout", default="cortex_memory/training/holdout.jsonl")
    ap.add_argument("--train", default="cortex_memory/training/train.jsonl")
    ap.add_argument("--report", default="claude/reports/K1B_RANK.md")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--batch", type=int, default=1,
                    help="1 = unbatched. Raise ONLY after --probe says the two agree.")
    ap.add_argument("--no-band", action="store_true",
                    help="the unmatched variant, reported beside the banded one")
    ap.add_argument("--knobs", default="claude/reports/K1B_RANK_KNOBS.json",
                    help="written by --probe, REQUIRED by the run")
    ap.add_argument("--probe", type=int, default=0,
                    help="measure agreement, time and peak on N items, then stop")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    hp, tp, adir = Path(a.holdout), Path(a.train), Path(a.adapter)
    for p, why in ((hp, "holdout"), (tp, "train split"), (adir, "adapter")):
        if not p.exists():
            print(f"REFUSED: no {why} at {p}.")
            return 2

    rows = load_jsonl(hp)
    if not rows:
        print("REFUSED: holdout is empty.")
        return 2

    # THE KNOBS ARE NOT CHOSEN HERE. --probe decides them from a measurement and
    # writes them to disk; the run reads that file and refuses without it. There
    # is no code path in which K is picked while a result is visible.
    knobs = {"k": K_DISTRACTORS, "chance": CHANCE, "batch": 1, "why": "probe mode"}
    if not a.probe:
        kp = Path(a.knobs)
        if not kp.exists():
            print("REFUSED: no knobs at " + str(kp) + ". Run --probe first; K, the "
                  "chance level and the batch size are decided from a measurement "
                  "BEFORE any accuracy exists.")
            return 2
        knobs = json.loads(kp.read_text(encoding="utf-8"))
        print("KNOBS (pre-registered " + str(knobs.get("decided_at")) + "): K="
              + str(knobs["k"]) + " chance=" + str(knobs["chance"]) + " batch="
              + str(knobs["batch"]) + " -- " + str(knobs["why"]))
    train_targets = {norm(r["target"]) for r in load_jsonl(tp) if r.get("target")}

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, tok = load_model(a.base, str(adir), device)
    tlen = token_len_fn(tok)

    # The pool is the HOLDOUT target pool, de-duplicated under norm().
    pool = build_pool(rows, tlen)
    band = None if a.no_band else LENGTH_BAND
    items, unscorable = build_items(rows, pool, tlen, band=band, k=knobs["k"],
                                    max_len=a.max_len, tok=tok)
    for it in items:
        it["novelty"] = "SEEN" if norm(it["target"]) in train_targets else "UNSEEN"
        it["record_kind"] = resolve_stratum(
            {"record_kind": it["record_kind"]} if it["record_kind"] else {}, hp, it["i"])
    if a.limit:
        items = items[:a.limit]

    print(f"pool {len(pool)} distinct · items {len(items)} · unscorable {len(unscorable)} "
          f"· widened {sum(1 for i in items if i['widened'])}")
    print(f"forward passes: {forward_passes(len(items), k=knobs[chr(107)+chr(93)] if False else knobs['k'])} "
          f"({len(items)} x {knobs['k'] + 1} x 2)")

    if a.probe:
        rec = probe(model, tok, items, device, a.probe, max(2, a.batch))
        knobs = decide_knobs(rec)
        knobs["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        knobs["probe"] = rec
        Path(a.knobs).parent.mkdir(parents=True, exist_ok=True)
        Path(a.knobs).write_text(json.dumps(knobs, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        print(json.dumps(knobs, ensure_ascii=False, indent=2))
        print("\nKNOBS RECORDED at " + a.knobs
              + " -- K=" + str(knobs["k"]) + " chance=" + str(knobs["chance"])
              + " batch=" + str(knobs["batch"]))
        return 0

    # ── the two passes, over the SAME frozen items ──────────────────────────
    results = {"base": [], "adapter": []}
    t0 = time.time()
    for pass_name in ("base", "adapter"):
        for n, it in enumerate(items, 1):
            cands = [it["target"]] + it["candidates"]
            if pass_name == "base":
                with model.disable_adapter():
                    nlls, how = candidate_nlls(model, tok, it["prompt"], cands,
                                               device, knobs["batch"])
            else:
                nlls, how = candidate_nlls(model, tok, it["prompt"], cands,
                                           device, knobs["batch"])
            results[pass_name].append({
                "kind": it["record_kind"], "novelty": it["novelty"],
                "hit": 1 if all(nlls[0] < d for d in nlls[1:]) else 0,
                "true_nll": nlls[0], "how": how})
            if n % 25 == 0:
                print(f"  {pass_name} {n}/{len(items)}  {time.time() - t0:.0f}s")

    # ── report ──────────────────────────────────────────────────────────────
    def table(pass_name, novelty):
        buckets = defaultdict(list)
        for r in results[pass_name]:
            if r["novelty"] == novelty:
                buckets[r["kind"]].append(r["hit"])
        out = []
        for kind, hits in sorted(buckets.items()):
            v, acc, ci = rank_verdict(hits, k=knobs["k"])
            cis = f"[{ci[0]:.4f}, {ci[1]:.4f}]" if ci else "-"
            out.append(f"| {kind} | {len(hits)} | {acc:.4f} | {cis} | {v} |")
        return out or ["| - | 0 | - | - | NO DATA |"]

    def nll_table(novelty):
        b = defaultdict(list)
        for rb, ra in zip(results["base"], results["adapter"]):
            if rb["novelty"] == novelty:
                b[rb["kind"]].append((rb["true_nll"], ra["true_nll"]))
        out = []
        for kind, pairs in sorted(b.items()):
            base = sum(p[0] for p in pairs) / len(pairs)
            adap = sum(p[1] for p in pairs) / len(pairs)
            out.append(f"| {kind} | {len(pairs)} | {base:.4f} | {adap:.4f} "
                       f"| {base - adap:+.4f} |")
        return out or ["| - | 0 | - | - | - |"]

    hdr = "| stratum | n | accuracy | 95% CI | verdict |\n|---|---|---|---|---|"
    L = [f"# K1b ranking eval — {adir.name}", "",
         f"**K={knobs['k']} distractors, chance = {knobs['chance']:.2f}, "
         f"batch = {knobs['batch']}** -- pre-registered at "
         f"{knobs.get('decided_at')}: {knobs['why']}",
         f"MIN_BUCKET={MIN_BUCKET}, band={'none (unmatched)' if band is None else band}",
         f"pool {len(pool)} distinct · items {len(items)} · "
         f"unscorable {len(unscorable)} · widened "
         f"{sum(1 for i in items if i['widened'])}",
         f"wall {time.time() - t0:.0f}s · method {results['adapter'][0]['how']}", "",
         "## UNSEEN — adapter — THIS IS THE VERDICT", "", hdr]
    L += table("adapter", "UNSEEN")
    L += ["", "## UNSEEN — base (the same candidates, adapter disabled)", "", hdr]
    L += table("base", "UNSEEN")
    L += ["", "## SEEN — memorisation check, NOT a result", "", hdr]
    L += table("adapter", "SEEN")
    L += ["", "## SECONDARY: mean NLL of the true target",
          "**Distributional gain, not mapping.** A negative control trained on "
          "deranged pairs improved this by +1.2204 nats while learning no mapping "
          "at all. It is here for continuity with the old report and must not be "
          "read as evidence of learning.", "",
          "| stratum | n | base NLL | adapter NLL | delta |", "|---|---|---|---|---|"]
    L += nll_table("UNSEEN")
    L += ["", "## How to read this",
          f"- Chance is {CHANCE:.2f}. AT CHANCE means the adapter cannot tell the true "
          "target from nine real alternatives drawn from the same pool.",
          "- Every candidate comes from the SAME target distribution, so house style "
          "cannot move this number. That is the whole point of replacing NLL.",
          "- UNRESOLVABLE is the corpus being too small to grade that bucket.",
          f"- {len(unscorable)} item(s) were unscorable and are listed, not dropped: "
          f"{unscorable[:10]}"]

    out = Path(a.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
