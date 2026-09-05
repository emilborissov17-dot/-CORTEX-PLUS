# K1b training run

- examples: 1077  ·  optimiser steps: 134  ·  wall: 6932.5s
- peak allocated: 2433.6 MiB  ·  peak reserved: 2720.0 MiB  (of 4096 MiB)
- bf16 supported: False  ·  compute dtype: torch.float16
- loss: 2.2571 -> 1.993
- corpus sha256: `079a9d1472511aa790e94320067f3ae3890c5c53a3170596c00eb16b2ec6259e`

Falling loss means the adapter fit this corpus. It does NOT mean the machine
learned anything about the world. That question belongs to eval_adapter.py,
on a held-out split it never saw, and the answer there may still be NO EFFECT.