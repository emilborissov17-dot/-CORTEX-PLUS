#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/qlora_smoke.py — THE GO/NO-GO. One QLoRA gradient step on a 3B model.

This is not a trainer. It answers exactly one question and then stops: can this
machine take a single forward + backward + optimizer step on a 3B model in 4-bit,
inside 4 GB of VRAM, and write and reload an adapter afterwards.

WHY IT IS SHAPED THIS WAY (measured on this machine, 4 Sep 2026)
  GTX 1650, 4096 MiB, compute capability 7.5 (Turing, TU117).
  - 4-bit NF4 needs CC >= 7.5, so this GPU is exactly at the floor.
  - bf16 needs CC >= 8.0 (Ampere). It is NOT available here, so compute dtype is
    fp16 throughout. Asking for bf16 on this card is an error, not a preference.
  - TU117 has no tensor cores, so the step will be slow. Slow is a pass; OOM is
    not.
  - driver 526.56 tops out at CUDA 12.0, which is why torch is a cu118 build.

Run:
    venv_train\\Scripts\\python.exe tools\\qlora_smoke.py --model <path>
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch


def mib(x: int) -> float:
    return round(x / 1024 / 1024, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF-format model directory")
    ap.add_argument("--out", default=None, help="where to write the adapter")
    ap.add_argument("--seq", type=int, default=128, help="sequence length")
    args = ap.parse_args()

    report: dict = {"model": args.model, "seq_len": args.seq}

    # ── the environment, stated before anything is loaded ────────────────────
    report["torch"] = torch.__version__
    report["cuda_build"] = torch.version.cuda
    report["cuda_available"] = torch.cuda.is_available()
    if not torch.cuda.is_available():
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("\nNO-GO: CUDA did not initialise.")
        return 2

    dev = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(0)
    cc = f"{props.major}.{props.minor}"
    report["device"] = props.name
    report["compute_capability"] = cc
    report["vram_total_MiB"] = mib(props.total_memory)
    free, total = torch.cuda.mem_get_info()
    report["vram_free_MiB_before"] = mib(free)
    report["bf16_supported"] = torch.cuda.is_bf16_supported()

    # fp16, never bf16: CC 7.5 has no bfloat16 units
    compute_dtype = torch.float16
    report["compute_dtype"] = str(compute_dtype)

    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)
    from peft import LoraConfig, get_peft_model, PeftModel
    import bitsandbytes as bnb

    report["transformers"] = __import__("transformers").__version__
    report["peft"] = __import__("peft").__version__
    report["bitsandbytes"] = bnb.__version__

    torch.cuda.reset_peak_memory_stats()
    t_load = time.time()

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        dtype=compute_dtype,
        device_map={"": 0},
    )
    report["load_seconds"] = round(time.time() - t_load, 1)
    report["vram_after_load_MiB"] = mib(torch.cuda.memory_allocated())

    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.config.use_cache = False

    lora = LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.0, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_p = sum(p.numel() for p in model.parameters())
    report["trainable_params"] = trainable
    report["total_params"] = total_p
    report["trainable_pct"] = round(100 * trainable / total_p, 4)

    # ── one synthetic example, batch 1 ───────────────────────────────────────
    text = ("CORTEX++ measures civilisation. On 4 September 2026 K1 was 0.6287 "
            "and k1_fresh was near zero, because ninety-five of a hundred and "
            "five measured weight had not moved in thirty cycles.")
    batch = tok(text, return_tensors="pt", truncation=True,
                max_length=args.seq, padding="max_length")
    batch = {k: v.to(dev) for k, v in batch.items()}
    batch["labels"] = batch["input_ids"].clone()

    opt = bnb.optim.AdamW8bit(
        [p for p in model.parameters() if p.requires_grad], lr=1e-4)

    model.train()
    t_step = time.time()
    out = model(**batch)
    loss = out.loss
    loss.backward()
    opt.step()
    opt.zero_grad(set_to_none=True)
    torch.cuda.synchronize()
    report["step_seconds"] = round(time.time() - t_step, 2)
    report["loss"] = round(float(loss.detach().float().cpu()), 6)
    report["peak_vram_MiB"] = mib(torch.cuda.max_memory_allocated())
    report["peak_vram_reserved_MiB"] = mib(torch.cuda.max_memory_reserved())
    free2, _ = torch.cuda.mem_get_info()
    report["vram_free_MiB_after"] = mib(free2)

    # ── save the adapter and read it back ────────────────────────────────────
    out_dir = Path(args.out or (Path(args.model).parent / "adapter_smoke"))
    model.save_pretrained(out_dir)
    files = sorted(p.name for p in out_dir.iterdir())
    report["adapter_dir"] = str(out_dir)
    report["adapter_files"] = files
    report["adapter_bytes"] = sum(p.stat().st_size for p in out_dir.iterdir())

    del model
    torch.cuda.empty_cache()

    base = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=quant, dtype=compute_dtype,
        device_map={"": 0})
    reloaded = PeftModel.from_pretrained(base, out_dir)
    report["adapter_reloaded"] = True
    report["reloaded_trainable_modules"] = sum(
        1 for n, _ in reloaded.named_modules() if "lora_A" in n)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("\nGO: one 4-bit QLoRA gradient step completed on this machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
