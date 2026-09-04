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
import os
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
    ap.add_argument("--save-every", type=int, default=25,
                    help="checkpoint every N optimiser steps; a kill then costs minutes, not the run")
    ap.add_argument("--resume", action="store_true",
                    help="continue from <out>/ckpt if it exists")
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

    from peft import LoraConfig, get_peft_model
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
    print(f"after load          allocated {torch.cuda.memory_allocated() / 2**20:8.1f} MiB")

    # prepare_model_for_kbit_training() is deliberately NOT used.
    # It upcasts every non-quantised parameter to fp32. On Qwen2.5-3B the input
    # embedding is 311M parameters TIED to the output head, so that call costs
    # +595 MiB before a single activation exists - measured on this machine,
    # 4 Sep 2026, and the reason max-len 256, 192 and 128 all died at the same
    # 3.3 GiB. Sequence length was never the binding constraint.
    # Only the LoRA adapters train, so the frozen embedding has no reason to be
    # fp32. Below is what that helper does that we actually need, and nothing else.
    for p in model.parameters():
        p.requires_grad = False

    # Qwen2.5 ships bf16, and the non-quantised tensors keep the checkpoint dtype.
    # On CC 7.5 there are no bf16 units, so every touch of that 311M-parameter
    # embedding goes through emulation. Same 2 bytes, so this is not a memory fix -
    # it is a speed fix, and at ~4.8 s per example (measured 4 Sep) speed is the
    # binding constraint. Done BEFORE the norm upcast so norms still end at fp32.
    n_cast = 0
    if compute_dtype == torch.float16:
        for module in model.modules():
            if isinstance(module, torch.nn.Embedding) and module.weight.dtype == torch.bfloat16:
                module.to(torch.float16)
                n_cast += 1
    print(f"embeddings cast bf16 -> fp16: {n_cast}")

    # fp32 only for the normalisation layers: numerically worth it, and they are
    # thousands of parameters rather than hundreds of millions.
    n_norm = 0
    for name, module in model.named_modules():
        if "norm" in name.lower():
            module.to(torch.float32)
            n_norm += 1
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    # required once the embedding stays frozen, or checkpointing yields no grads
    model.enable_input_require_grads()
    emb_dtype = model.get_input_embeddings().weight.dtype
    print(
        f"after prepare       allocated {torch.cuda.memory_allocated() / 2**20:8.1f} MiB"
        f"   embedding dtype {emb_dtype}   norms upcast: {n_norm}"
    )
    if emb_dtype == torch.float32:
        print("REFUSED: the embedding is fp32. That is the 595 MiB regression this file exists to avoid.")
        return 2
    if emb_dtype == torch.bfloat16 and not bf16:
        print("WARNING: embedding is bf16 on hardware without bf16 units - emulated, and slower.")

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
    print(f"after LoRA attach   allocated {torch.cuda.memory_allocated() / 2**20:8.1f} MiB")
    print(f"trainable: {trainable:,} / {total:,} ({100 * trainable / total:.3f}%)")
    if trainable == 0:
        print("REFUSED: nothing is trainable. Freezing ran after LoRA attachment.")
        return 2

    ds = PairDataset(rows, tok, args.max_len)
    dl = DataLoader(ds, batch_size=1, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id))

    opt = bnb.optim.AdamW8bit([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    steps = max(1, (len(dl) * args.epochs) // args.accum)
    sched = get_cosine_schedule_with_warmup(opt, int(0.03 * steps) + 1, steps)
    scaler = torch.cuda.amp.GradScaler(enabled=not bf16)

    # --- survivability -------------------------------------------------------
    # A long run on this machine has been killed twice with no OOM and no traceback
    # (the 30 Aug cycle at the survival gate, and the 4 Sep control at ~27 min).
    # The killer is not named yet. This does not prevent a kill - it makes one cost
    # minutes instead of the whole run, and leaves a dated trace of the death.
    ck = Path(args.out) / "ckpt"
    hb = Path(args.out) / "heartbeat.json"
    ck.mkdir(parents=True, exist_ok=True)
    start_step = 0
    if args.resume and (ck / "state.pt").exists():
        st = torch.load(ck / "state.pt", map_location="cuda")
        from peft import set_peft_model_state_dict
        set_peft_model_state_dict(model, st["adapter"])
        opt.load_state_dict(st["optimizer"])
        sched.load_state_dict(st["scheduler"])
        start_step = st["step"]
        print(f"RESUMED from optimiser step {start_step}")

    def save_ckpt(step_i: int, loss_v: float) -> None:
        from peft import get_peft_model_state_dict
        torch.save(
            {
                "adapter": get_peft_model_state_dict(model),
                "optimizer": opt.state_dict(),
                "scheduler": sched.state_dict(),
                "step": step_i,
            },
            ck / "state.pt.tmp",
        )
        os.replace(ck / "state.pt.tmp", ck / "state.pt")  # atomic: a kill mid-write cannot corrupt it
        hb.write_text(
            json.dumps(
                {
                    "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "step": step_i,
                    "of_steps": steps,
                    "loss": round(loss_v, 4),
                    "gpu_alloc_mib": round(torch.cuda.memory_allocated() / 2**20, 1),
                }
            ),
            encoding="utf-8",
        )

    torch.cuda.reset_peak_memory_stats()
    t0, losses, step = time.time(), [], start_step
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
                recent = sum(losses[-args.accum * 10 :]) / len(losses[-args.accum * 10 :])
                if step % 10 == 0:
                    print(f"epoch {epoch} step {step}/{steps} loss {recent:.4f}", flush=True)
                if step % args.save_every == 0:
                    save_ckpt(step, recent)

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
