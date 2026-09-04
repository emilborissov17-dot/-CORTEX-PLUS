"""
K1b trainer: QLoRA over the machine's own verified experience.

Constraints this file is built around, not around defaults:
    GTX 1650 · Turing · CC 7.5 · 4096 MiB · driver 526.56 · torch cu118
    - no bf16 units on CC 7.5 -> fp16 compute, and the assertion is printed,
      not assumed
    - 4 GB total, shared with the Windows desktop -> batch 1 + gradient
      accumulation, gradient checkpointing on, short sequences

Every adapter written by this file carries adapter_provenance.json with the
sha256 of the corpus it was trained on. An adapter that cannot name its
corpus is not evidence of anything, and eval_adapter.py says so out loud.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, get_cosine_schedule_with_warmup

MIN_TRAIN = 32


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


class PairDataset(Dataset):
    def __init__(self, rows: list[dict], tok, max_len: int):
        self.rows, self.tok, self.max_len = rows, tok, max_len

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        r = self.rows[i]
        p_ids = self.tok(r["prompt"], add_special_tokens=True)["input_ids"]
        t_ids = self.tok(r["target"], add_special_tokens=False)["input_ids"]
        ids = (p_ids + t_ids)[: self.max_len]
        labels = list(ids)
        for j in range(min(len(p_ids), len(labels))):
            labels[j] = -100
        if all(l == -100 for l in labels):
            # the target was truncated away entirely - refuse rather than train on nothing
            raise ValueError(f"example {i}: target truncated to zero at max_len={self.max_len}")
        return {"input_ids": ids, "labels": labels}


def collate(batch, pad_id: int):
    n = max(len(b["input_ids"]) for b in batch)
    ids, labels, mask = [], [], []
    for b in batch:
        pad = n - len(b["input_ids"])
        ids.append(b["input_ids"] + [pad_id] * pad)
        labels.append(b["labels"] + [-100] * pad)
        mask.append([1] * len(b["input_ids"]) + [0] * pad)
    return (
        torch.tensor(ids),
        torch.tensor(labels),
        torch.tensor(mask),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/Qwen2.5-3B-Instruct")
    ap.add_argument("--train", default="cortex_memory/training/train.jsonl")
    ap.add_argument("--out", default="models/adapters/k1b_latest")
    ap.add_argument("--report", default="claude/reports/K1B_TRAIN.md")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--targets", default="q_proj,k_proj,v_proj,o_proj")
    args = ap.parse_args()

    train_path = Path(args.train)
    if not train_path.exists():
        print(f"REFUSED: no corpus at {train_path}. Build it first.")
        return 2

    rows = [json.loads(l) for l in train_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("prompt") and str(r.get("target", "")).strip()]
    if len(rows) < MIN_TRAIN:
        print(f"REFUSED: {len(rows)} usable examples, minimum is {MIN_TRAIN}.")
        print("Training on this would produce an adapter that memorises noise and calls it learning.")
        return 2

    if not torch.cuda.is_available():
        print("REFUSED: no CUDA device. This trainer is sized for one specific 4 GB GPU.")
        return 2

    # torch.cuda.is_bf16_supported() returns True on CC 7.5 because recent torch
    # counts emulation as support. Measured on this machine, 4 Sep 2026. Gate on the
    # hardware, not on the flag, or the run silently picks emulated bf16 and is slower
    # and less stable for no visible reason.
    cap = torch.cuda.get_device_capability(0)
    bf16_flag = torch.cuda.is_bf16_supported()
    bf16 = bf16_flag and cap >= (8, 0)
    print(
        f"device: {torch.cuda.get_device_name(0)}  ·  compute capability: {cap[0]}.{cap[1]}\n"
        f"is_bf16_supported() reports: {bf16_flag}  ·  real bf16 hardware: {bf16}"
    )
    compute_dtype = torch.bfloat16 if bf16 else torch.float16

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    import bitsandbytes as bnb

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant, device_map={"": 0})
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.gradient_checkpointing_enable()
    model.config.use_cache = False

    lcfg = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[t.strip() for t in args.targets.split(",") if t.strip()],
    )
    model = get_peft_model(model, lcfg)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"trainable: {trainable:,} / {total:,} ({100 * trainable / total:.3f}%)")

    ds = PairDataset(rows, tok, args.max_len)
    dl = DataLoader(ds, batch_size=1, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id))

    opt = bnb.optim.AdamW8bit([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    steps = max(1, (len(dl) * args.epochs) // args.accum)
    sched = get_cosine_schedule_with_warmup(opt, int(0.03 * steps) + 1, steps)
    scaler = torch.cuda.amp.GradScaler(enabled=not bf16)

    torch.cuda.reset_peak_memory_stats()
    t0, losses, step = time.time(), [], 0
    model.train()
    for epoch in range(args.epochs):
        for i, (ids, labels, mask) in enumerate(dl):
            ids, labels, mask = ids.cuda(), labels.cuda(), mask.cuda()
            with torch.autocast("cuda", dtype=compute_dtype):
                loss = model(input_ids=ids, labels=labels, attention_mask=mask).loss / args.accum
            scaler.scale(loss).backward()
            losses.append(float(loss) * args.accum)
            if (i + 1) % args.accum == 0:
                scaler.step(opt)
                scaler.update()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0:
                    recent = sum(losses[-args.accum * 10 :]) / len(losses[-args.accum * 10 :])
                    print(f"epoch {epoch} step {step}/{steps} loss {recent:.4f}")

    wall = time.time() - t0
    peak = torch.cuda.max_memory_allocated() / 2**20
    reserved = torch.cuda.max_memory_reserved() / 2**20

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out))
    tok.save_pretrained(str(out))

    prov = {
        "corpus_path": str(train_path),
        "corpus_sha256": sha256_file(train_path),
        "n_train": len(rows),
        "git_commit": git_commit(),
        "hyperparams": {
            "epochs": args.epochs,
            "max_len": args.max_len,
            "accum": args.accum,
            "lr": args.lr,
            "rank": args.rank,
            "alpha": args.alpha,
            "targets": args.targets,
            "compute_dtype": str(compute_dtype),
            "compute_capability": f"{cap[0]}.{cap[1]}",
            "bf16_flag_reported": bf16_flag,
            "bf16_hardware_real": bf16,
        },
        "peak_alloc_mib": round(peak, 1),
        "peak_reserved_mib": round(reserved, 1),
        "wall_seconds": round(wall, 1),
        "first_loss": round(losses[0], 4) if losses else None,
        "last_loss": round(sum(losses[-20:]) / len(losses[-20:]), 4) if losses else None,
    }
    (out / "adapter_provenance.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")

    report = [
        "# K1b training run",
        "",
        f"- examples: {len(rows)}  ·  optimiser steps: {step}  ·  wall: {wall:.1f}s",
        f"- peak allocated: {peak:.1f} MiB  ·  peak reserved: {reserved:.1f} MiB  (of 4096 MiB)",
        f"- bf16 supported: {bf16}  ·  compute dtype: {compute_dtype}",
        f"- loss: {prov['first_loss']} -> {prov['last_loss']}",
        f"- corpus sha256: `{prov['corpus_sha256']}`",
        "",
        "Falling loss means the adapter fit this corpus. It does NOT mean the machine",
        "learned anything about the world. That question belongs to eval_adapter.py,",
        "on a held-out split it never saw, and the answer there may still be NO EFFECT.",
    ]
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
