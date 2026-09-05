# K1b training run

- examples: 1077  ·  optimiser steps: 134  ·  wall: 6895.2s
- peak allocated: 2482.3 MiB  ·  peak reserved: 2718.0 MiB  (of 4096 MiB)
- bf16 supported: False  ·  compute dtype: torch.float16
- loss: 2.6226 -> 1.9029
- corpus sha256: `2622e01a08972d62431152cfa8022b8bea779c8efaf05383e664a6e782470c6c`

Falling loss means the adapter fit this corpus. It does NOT mean the machine
learned anything about the world. That question belongs to eval_adapter.py,
on a held-out split it never saw, and the answer there may still be NO EFFECT.