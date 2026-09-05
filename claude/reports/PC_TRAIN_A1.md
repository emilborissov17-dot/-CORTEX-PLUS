# K1b training run

- examples: 300  ·  optimiser steps: 37  ·  wall: 1761.2s
- peak allocated: 2190.6 MiB  ·  peak reserved: 2696.0 MiB  (of 4096 MiB)
- bf16 supported: False  ·  compute dtype: torch.float16
- loss: 7.1832 -> 2.59
- corpus sha256: `49bb0ea6c9827d76296f61823a7215b676621d93868ca5b36e3492f160329733`

Falling loss means the adapter fit this corpus. It does NOT mean the machine
learned anything about the world. That question belongs to eval_adapter.py,
on a held-out split it never saw, and the answer there may still be NO EFFECT.