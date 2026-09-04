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

THE MEMORISATION TRAP (added 4 Sep 2026, before any run)
    The corpus has an exact-duplicate target rate of 43.76% - the archive
    proposes the same solutions over and over. With a chronological split,
    the holdout therefore contains targets that appear VERBATIM in train.
    An adapter that memorised those strings will show lower NLL on them, the
    table would read IMPROVED, and the machine would have learned a repeated
    string rather than anything about the world.
    So every holdout example is labelled SEEN or UNSEEN against the exact set
    of training targets, and the two are never averaged together.
    THE HEADLINE VERDICT IS THE UNSEEN ROW. The SEEN row is reported as a
    memorisation check: large gains there with none on UNSEEN is the signature
    of memorisation, and it is a finding, not a success.

PRE-REGISTERED DECISION RULE (do not edit after seeing a result)
    - Fewer than MIN_HOLDOUT examples in a bucket -> UNRESOLVABLE for that
      bucket. Not "no improvement". Refusing to grade is a valid outcome.
    - Improvement is claimed only if the paired bootstrap 95% CI of
      (base_nll - adapter_nll) lies entirely above zero, on UNSEEN targets.
    - Strata are reported SEPARATELY. Failing to beat persistence on a slow
      index is nearly expected; failing to predict your own failure is worse
      and must not be hidden inside an average.

NO SILENT DEFAULTS
    The stratum key is required, not defaulted. A missing key raises. This
    file previously used .get(key, "unspecified") - the same defect class as
    merkle_to_training.py:183, found in review on 4 Sep before it ever ran.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MIN_HOLDOUT = 30
BOOTSTRAP_N = 10000
SEED = 20260904
STRATUM_KEY = "record_kind"


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


def norm(text: str) -> str:
    """Whitespace-normalised target, for exact-duplicate detection."""
    return " ".join(str(text).split())


def resolve_stratum(row: dict, path: Path, i: int) -> str:
    """No default. A record that cannot name its stratum stops the run."""
    if STRATUM_KEY not in row:
        raise SystemExit(
            f"{path}: record {i} has no '{STRATUM_KEY}'. Observed keys: {sorted(row)}.\n"
            f"Refusing to grade under a made-up stratum name. Fix the corpus contract "
            f"in training/corpus_from_merkle.py so every emitted record declares one."
        )
    value = row[STRATUM_KEY]
    if not str(value).strip():
        raise SystemExit(f"{path}: record {i} has an empty '{STRATUM_KEY}'.")
    return str(value)


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
    return float(out.loss)


def paired_bootstrap(deltas: np.ndarray, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(deltas), size=(n, len(deltas)))
    means = deltas[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def verdict_for(deltas: np.ndarray) -> tuple[str, str]:
    n = len(deltas)
    if n < MIN_HOLDOUT:
        return f"UNRESOLVABLE (n<{MIN_HOLDOUT})", "-"
    lo, hi = paired_bootstrap(deltas, BOOTSTRAP_N, SEED)
    ci = f"[{lo:+.4f}, {hi:+.4f}]"
    if lo > 0:
        return "IMPROVED", ci
    if hi < 0:
        return "WORSE", ci
    return "NO EFFECT", ci


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/Qwen2.5-3B-Instruct")
    ap.add_argument("--adapter", default="models/adapters/k1b_latest")
    ap.add_argument("--holdout", default="cortex_memory/training/holdout.jsonl")
    ap.add_argument("--train", default="cortex_memory/training/train.jsonl",
                    help="read only to detect targets the adapter has already seen")
    ap.add_argument("--report", default="claude/reports/K1B_EVAL.md")
    ap.add_argument("--max-tokens", type=int, default=512)
    args = ap.parse_args()

    holdout_path, train_path = Path(args.holdout), Path(args.train)
    if not holdout_path.exists():
        print(f"REFUSED: no holdout at {holdout_path}. Build the corpus first.")
        return 2
    if not train_path.exists():
        print(f"REFUSED: no train split at {train_path}. Without it, SEEN vs UNSEEN "
              f"cannot be determined and the verdict would be uninterpretable.")
        return 2

    rows = load_jsonl(holdout_path)
    if not rows:
        print("REFUSED: holdout is empty.")
        return 2

    train_targets = {norm(r["target"]) for r in load_jsonl(train_path) if r.get("target")}
    print(f"train targets: {len(train_targets)} distinct strings")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        print("WARNING: no CUDA. Slower, but the numbers are still valid.")

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,  # CC 7.5 has no bf16 units; see train_lora.py
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

    prov_path = adapter_dir / "adapter_provenance.json"
    prov = json.loads(prov_path.read_text(encoding="utf-8")) if prov_path.exists() else {}

    buckets: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    skipped = 0
    for i, r in enumerate(rows, 1):
        prompt, target = r.get("prompt"), r.get("target")
        if not prompt or not str(target).strip():
            skipped += 1
            continue
        if len(tok(prompt + target)["input_ids"]) > args.max_tokens:
            skipped += 1
            continue
        kind = resolve_stratum(r, holdout_path, i)
        novelty = "SEEN" if norm(target) in train_targets else "UNSEEN"
        with model.disable_adapter():
            base = example_nll(model, tok, prompt, target, device)
        adapted = example_nll(model, tok, prompt, target, device)
        buckets[(kind, novelty)].append((base, adapted))

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

    n_seen = sum(len(v) for (k, nv), v in buckets.items() if nv == "SEEN")
    n_unseen = sum(len(v) for (k, nv), v in buckets.items() if nv == "UNSEEN")
    lines += [
        f"Held-out read: {len(rows)}  ·  skipped (empty or too long): {skipped}",
        f"Targets already present verbatim in train: {n_seen}  ·  novel: {n_unseen}",
        "",
        "## UNSEEN targets - this is the verdict",
        "",
        "| stratum | n | base NLL | adapter NLL | delta | 95% CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    def emit(novelty: str) -> list[str]:
        out = []
        for (kind, nv), pairs in sorted(buckets.items()):
            if nv != novelty:
                continue
            arr = np.array(pairs, dtype=float)
            deltas = arr[:, 0] - arr[:, 1]  # positive = adapter better
            v, ci = verdict_for(deltas)
            out.append(
                f"| {kind} | {len(arr)} | {arr[:,0].mean():.4f} | {arr[:,1].mean():.4f} "
                f"| {deltas.mean():+.4f} | {ci} | {v} |"
            )
        return out or ["| - | 0 | - | - | - | - | NO DATA |"]

    unseen_rows = emit("UNSEEN")
    lines += unseen_rows
    lines += [
        "",
        "## SEEN targets - memorisation check, NOT a result",
        "",
        "| stratum | n | base NLL | adapter NLL | delta | 95% CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += emit("SEEN")

    lines += [
        "",
        "## How to read this",
        "- Lower NLL means the model assigns more probability to what actually happened.",
        "- Gains on SEEN with none on UNSEEN = memorisation of a repeated string.",
        "  That is a finding about the corpus (43.76% duplicate targets), not a success.",
        "- `NO EFFECT` on UNSEEN with changed weights means we changed weights and",
        "  learned nothing. That is a real result and it closes the day honestly.",
        "- `UNRESOLVABLE` is the corpus being too small to grade that bucket. Fix it by",
        "  waiting for cycles, not by lowering the bar.",
    ]

    report = "\n".join(lines)
    out_path = Path(args.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report)

    return 0 if any("IMPROVED" in r for r in unseen_rows) else 1


if __name__ == "__main__":
    sys.exit(main())
