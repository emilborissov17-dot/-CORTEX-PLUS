# QLORA SMOKE TEST — GO/NO-GO — 4 September 2026

One gradient step on a 3B model, 4-bit NF4, on this machine. Nothing more.

## VERDICT

**GO.** A single 4-bit QLoRA forward + backward + optimizer step completed on a
GTX 1650 with 4 GB of VRAM. It did **not** OOM.

## THE NUMBERS

| | |
|---|---|
| OOM | **no** |
| peak VRAM allocated | **2270.3 MiB** |
| peak VRAM reserved | **2344.0 MiB** |
| VRAM total / free before | 4095.8 / 3311.2 MiB |
| VRAM free after the step | 223.2 MiB |
| step wall time | **8.35 s** |
| loss | **9.435968** |
| model load time | 13.5 s |
| VRAM after load | 1969.3 MiB |
| trainable params | 3,686,400 (0.2165%) |
| adapter written | 14,790,008 bytes, README.md, adapter_config.json, adapter_model.safetensors |
| adapter reloaded | True — 288 LoRA modules |

## bf16 — THE FLAG LIES, AND WE DID NOT TRUST IT

`torch.cuda.is_bf16_supported()` returned **True** on this card.
That is misleading: compute capability is **7.5** (Turing, TU117) and bf16 needs
**CC >= 8.0** (Ampere). Recent torch reports emulation as support. The run used
`torch.float16` throughout, as specified. The flag is recorded here so the
discrepancy is on the record rather than silently trusted.

## ENVIRONMENT

| | |
|---|---|
| device | NVIDIA GeForce GTX 1650 |
| compute capability | 7.5 |
| driver | 526.56 (CUDA 12.0 ceiling) |
| torch | 2.7.1+cu118 (CUDA build 11.8) |
| transformers / peft / bitsandbytes | 5.16.1 / 0.20.0 / 0.50.2 |
| venv | `venv_train`, Python 3.12.10 (isolated from the 3.14 cycle venv) |
| model | `models/Qwen2.5-3B-Instruct` — Qwen2.5-3B-Instruct, HF safetensors, 5.8 GB |
| config | NF4 + double quant, fp16 compute, LoRA r=8 alpha=16 on q/k/v/o, |
| | gradient checkpointing on, batch 1, seq 128, AdamW8bit |

**Why cu118 and not cu12x:** driver 526.56 tops out at CUDA 12.0, and Windows
requires >= 527.41 for CUDA 12.1. No cu12x wheel would have initialised. cu118
needs only >= 452.39. **No driver update was required.**

## HONEST CAVEATS

- **The loss (9.435968) is not a quality signal.** One step, untrained adapter,
  and the labels include padding tokens, which inflates it. It is reported because
  it proves a real backward pass ran, not because the value means anything.
- **Headroom is thin.** 223.2 MiB free after the step at seq
  128, batch 1. Longer sequences or batch > 1 will need measuring, not
  assuming.
- **`total_params` reads 1,702,359,040** because 4-bit packing changes the
  count; it is not a 1.7B model.
- **7B and 8B remain out of reach.** NF4 weights alone would be ~4-4.5 GB, above
  the 4 GB card. The two larger local Ollama models cannot be trained here.
- GGUF weights (the 12 GB Ollama store) are inference-only and cannot be
  LoRA-trained. This test used freshly downloaded HF-format safetensors.

## RAW REPORT (verbatim)

```json
{
  "model": "models/Qwen2.5-3B-Instruct",
  "seq_len": 128,
  "torch": "2.7.1+cu118",
  "cuda_build": "11.8",
  "cuda_available": true,
  "device": "NVIDIA GeForce GTX 1650",
  "compute_capability": "7.5",
  "vram_total_MiB": 4095.8,
  "vram_free_MiB_before": 3311.2,
  "bf16_supported": true,
  "compute_dtype": "torch.float16",
  "transformers": "5.16.1",
  "peft": "0.20.0",
  "bitsandbytes": "0.50.2",
  "load_seconds": 13.5,
  "vram_after_load_MiB": 1969.3,
  "trainable_params": 3686400,
  "total_params": 1702359040,
  "trainable_pct": 0.2165,
  "step_seconds": 8.35,
  "loss": 9.435968,
  "peak_vram_MiB": 2270.3,
  "peak_vram_reserved_MiB": 2344.0,
  "vram_free_MiB_after": 223.2,
  "adapter_dir": "models\\adapter_smoke",
  "adapter_files": [
    "README.md",
    "adapter_config.json",
    "adapter_model.safetensors"
  ],
  "adapter_bytes": 14790008,
  "adapter_reloaded": true,
  "reloaded_trainable_modules": 288
}
```