"""
K1b gate: does the fine-tuned adapter judge better than the base model?

Written BEFORE train_lora.py on purpose. The criterion is fixed before the
result exists; a metric chosen after seeing the outcome is not evidence.

PRIMARY METRIC
    Mean per-token negative log-likelihood of the VERIFIED outcome,
    teacher-forced, on a time-ordered held-out split.
    No decoding. Decoding adds sampling noise plus a parse layer that can
    make a flat model look alive.

WHY ONE LOAD
    Base and adapter are measured on the SAME loaded 4-bit model via
    peft's disable_adapter(). Identical quantization, identical kernels,
    identical machine state. Any difference is the adapter and nothing else.

PRE-REGISTERED DECISION RULE (do not edit after seeing a result)
    - Fewer than MIN_HOLDOUT examples in a stratum -> UNRESOLVABLE for that
      stratum. Not "no improvement". Refusing to grade is a valid outcome.
    - Improvement is claimed only if the paired bootstrap 95% CI of
      (base_nll - adapter_nll) lies entirely above zero.
    - Strata are reported SEPARATELY. Failing to beat persistence on a slow
      index is nearly expected; failing to predict your own failure is worse
      and must not be hidden inside an average.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MIN_HOLDOUT = 30
BOOTSTRAP_N = 10000
SEED = 20260904


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{i}: corpus is not valid jsonl: {exc}")
    return rows


def example_nll(model, tok, prompt: str, target: str, device: str) -> float:
    """Mean NLL per target token. Prompt tokens are masked out."""
    p_ids = tok(prompt, add_special_tokens=True)["input_ids"]
    t_ids = tok(target, add_special_tokens=False)["input_ids"]
    if not t_ids:
        raise ValueError("empty target reached eval - the corpus contract failed upstream")
    ids = torch.tensor([p_ids + t_ids], device=device)
    labels = ids.clone()
    labels[0, : len(p_ids)] = -100
    with torch.no_grad():
        out = model(input_ids=ids, labels=labels)
    # HF already returns mean over non-masked tokens
    return float(out.loss)


def paired_bootstrap(deltas: np.ndarray, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(deltas), size=(n, len(deltas)))
    means = deltas[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/Qwen2.5-3B-Instruct")
    ap.add_argument("--adapter", default="models/adapters/k1b_latest")
    ap.add_argument("--holdout", default="cortex_memory/training/holdout.jsonl")
    ap.add_argument("--report", default="claude/reports/K1B_EVAL.md")
    ap.add_argument("--max-tokens", type=int, default=512)
    args = ap.parse_args()

    holdout_path = Path(args.holdout)
    if not holdout_path.exists():
        print(f"REFUSED: no holdout at {holdout_path}. Build the corpus first.")
        return 2

    rows = load_jsonl(holdout_path)
    if not rows:
        print("REFUSED: holdout is empty.")
        return 2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: no CUDA. This will be slow but the numbers are still valid.")

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,  # CC 7.5 has no bf16 units
    )
    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=quant, device_map={"": 0} if device == "cuda" else None
    )
    model.eval()

    from peft import PeftModel

    adapter_dir = Path(args.adapter)
    if not adapter_dir.exists():
        print(f"REFUSED: no adapter at {adapter_dir}. Nothing to compare against the base.")
        return 2
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()

    prov = {}
    prov_path = adapter_dir / "adapter_provenance.json"
    if prov_path.exists():
        prov = json.loads(prov_path.read_text(encoding="utf-8"))

    per_kind: dict[str, list[tuple[float, float]]] = defaultdict(list)
    skipped = 0
    for r in rows:
        prompt, target = r.get("prompt"), r.get("target")
        if not prompt or not target or not str(target).strip():
            skipped += 1
            continue
        if len(tok(prompt + target)["input_ids"]) > args.max_tokens:
            skipped += 1
            continue
        kind = r.get("record_kind", "unspecified")
        with model.disable_adapter():
            base = example_nll(model, tok, prompt, target, device)
        adapted = example_nll(model, tok, prompt, target, device)
        per_kind[kind].append((base, adapted))

    lines = ["# K1b eval - adapter vs base", ""]
    if prov:
        lines += [
            "## Adapter provenance",
            f"- corpus sha256: `{prov.get('corpus_sha256', 'MISSING')}`",
            f"- trained on: {prov.get('n_train', '?')} examples",
            f"- git commit: `{prov.get('git_commit', 'MISSING')}`",
            f"- hyperparams: `{json.dumps(prov.get('hyperparams', {}))}`",
            "",
        ]
    else:
        lines += ["## Adapter provenance", "**MISSING** - this adapter cannot be traced to a corpus.", ""]

    lines += [
        f"Held-out examples read: {len(rows)}  ·  skipped (empty or too long): {skipped}",
        "",
        "| stratum | n | base NLL | adapter NLL | delta | 95% CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    any_improved = False
    for kind, pairs in sorted(per_kind.items()):
        arr = np.array(pairs, dtype=float)
        n = len(arr)
        base_m, ad_m = arr[:, 0].mean(), arr[:, 1].mean()
        deltas = arr[:, 0] - arr[:, 1]  # positive = adapter better
        if n < MIN_HOLDOUT:
            verdict = f"UNRESOLVABLE (n<{MIN_HOLDOUT})"
            ci_s = "-"
        else:
            lo, hi = paired_bootstrap(deltas, BOOTSTRAP_N, SEED)
            ci_s = f"[{lo:+.4f}, {hi:+.4f}]"
            if lo > 0:
                verdict = "IMPROVED"
                any_improved = True
            elif hi < 0:
                verdict = "WORSE"
            else:
                verdict = "NO EFFECT"
        lines.append(
            f"| {kind} | {n} | {base_m:.4f} | {ad_m:.4f} | {deltas.mean():+.4f} | {ci_s} | {verdict} |"
        )

    lines += [
        "",
        "## What this does and does not say",
        "- Lower NLL means the model assigns more probability to what actually happened.",
        "- `NO EFFECT` with changed weights means we changed weights and learned nothing.",
        "  That is a real result and it closes the day honestly.",
        "- `UNRESOLVABLE` is not a failure of the model. It is the corpus being too small",
        "  to grade that stratum. Fix it by waiting for cycles, not by lowering the bar.",
    ]

    report = "\n".join(lines)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    return 0 if any_improved else 1


if __name__ == "__main__":
    sys.exit(main())
