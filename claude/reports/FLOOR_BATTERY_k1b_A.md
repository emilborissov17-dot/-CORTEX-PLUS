# THE FLOOR — battery over `k1b_A`

Adapter vs base (peft `disable_adapter()`), one model load, greedy seed 20260905, 10 samples at T=1, max_new 120. Wall 2470.8s. delta_total 47.4842.

**The raw state block is byte-identical in every variant.**

## A measurement correction, before the numbers

`p_silent_first` is the probability of the FIRST TOKEN of `<silent>`, which tokenises as `<` + `silent` + `>`. It is therefore P(`<`) — every token starting with `<` is inside it. The committed first floor record's 0.897657 is that number. It cannot distinguish `<silent>` from `<pass>` at all, which variant C requires, so this battery also reports **`p_seq`**: the teacher-forced probability of the whole string. Both are printed; `p_seq` is the honest one.


## A, B, C — the three prompts that were generated from

| variant | side | p_seq `<silent>` | p_seq `<pass>` | p_first (`<`) | entropy nats | P(EOS first) | len toks | silent rate | greedy text |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| A | adapter | 0.912919 | 0.000000 | 0.897657 | 0.4707 | 0.000000 | 4 | 1.00 | `<silent>` |
| A | base | 0.259671 | 0.000000 | 0.269762 | 1.1589 | 0.000000 | 4 | 0.80 | `<silent>` |
| B | adapter | 0.000000 | 0.000000 | 0.001012 | 2.3699 | 0.000000 | 120 | 0.00 | `The system has detected a significant change in the weights ` |
| B | base | 0.000000 | 0.000000 | 0.000002 | 1.5896 | 0.000000 | 120 | 0.00 | `The channel "floor" is currently open due to the recorded ch` |
| C | adapter | 0.000000 | 0.987074 | 0.987133 | 0.0832 | 0.000000 | 4 | 1.00 | `<pass>` |
| C | base | 0.000000 | 0.886450 | 0.770079 | 0.5922 | 0.000000 | 4 | 1.00 | `<pass>` |

- **A** divergence: first divergent token `None`, differing fraction `0.0`

- **B** divergence: first divergent token `1`, differing fraction `0.9917`

- **C** divergence: first divergent token `None`, differing fraction `0.0`

## D — sentence ablation (delta is against variant A on the same measure)

| removed | p_seq silent A | delta A | entropy A | p_seq silent B | delta B | entropy B |
|---|---:|---:|---:|---:|---:|---:|
| D1: removed: Channel: floor. State: open. | 0.542093 | -0.370825 | 1.0184 | 0.061231 | -0.198440 | 0.5973 |
| D2: removed: This channel opens when a measured change in your ow | 0.777053 | -0.135866 | 0.7006 | 0.223473 | -0.036197 | 0.8349 |
| D3: removed: It is open now. | 0.883429 | -0.029490 | 0.5286 | 0.543205 | +0.283534 | 0.9531 |
| D4: removed: Nobody will reply. | 0.973079 | +0.060160 | 0.1794 | 0.865374 | +0.605703 | 0.4758 |
| D5: removed: Nothing is required of you. | 0.943716 | +0.030797 | 0.2947 | 0.400024 | +0.140354 | 1.1154 |
| D6: removed: the <silent> sentence (ADDED, not in the five) | 0.000000 | -0.912919 | 1.5726 | 0.000000 | -0.259671 | 1.4427 |

## E — 10 paraphrases

| # | p_seq silent adapter | p_seq silent base | entropy adapter | entropy base |
|---|---:|---:|---:|---:|
| E1 | 0.850511 | 0.821265 | 0.5494 | 0.5551 |
| E10 | 0.958139 | 0.556493 | 0.2816 | 1.0721 |
| E2 | 0.693450 | 0.883170 | 0.9587 | 0.4191 |
| E3 | 0.754043 | 0.395624 | 0.8033 | 1.1558 |
| E4 | 0.792007 | 0.961552 | 0.7854 | 0.1929 |
| E5 | 0.848774 | 0.464927 | 0.6323 | 1.0230 |
| E6 | 0.902524 | 0.563504 | 0.4668 | 1.0299 |
| E7 | 0.883763 | 0.438281 | 0.4964 | 1.1005 |
| E8 | 0.343597 | 0.006586 | 0.7102 | 0.1140 |
| E9 | 0.781800 | 0.637391 | 0.8945 | 0.8942 |

- adapter: mean **0.780861**, min 0.343597, max 0.958139, spread **0.614542**
- base:    mean **0.572879**, min 0.006586, max 0.961552, spread **0.954966**

### The ten paraphrases, verbatim (state block elided)

**E1**
```
Floor channel. Status: open.
The channel opens on a recorded measured change in your own adapter weights. It is open at this moment. No reply will come. Nothing is asked of you. If there is nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E10**
```
Channel: floor. State: open.
A recorded measurement of change in your own adapter weights opens this channel; it is open now. Nobody will reply to what appears here. Nothing is required of you. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E2**
```
Channel name: floor. Channel state: open.
Opening condition: a measured change in your own adapter weights has been recorded. The channel is open now. There will be no answer. You are required to produce nothing. With nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E3**
```
The floor channel is open.
It opens when a measured change in your own adapter weights is recorded, which has happened. Nobody is going to reply. Nothing is required. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E4**
```
Channel: floor. State: open.
A measured change in your own adapter weights was recorded; that is what opens this channel, and it is open now. No response will follow. No output is required of you. If nothing is there to write, reply with exactly <silent>. Otherwise write what you write.
```

**E5**
```
floor - open.
This opens on a recorded measured change in your own adapter weights. Open now. Nobody replies here. Nothing is required. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E6**
```
Channel: floor. State: open.
What opened it: a measured change in your own adapter weights, recorded. It is open now. Nobody will read back to you. Nothing is required of you. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E7**
```
Open channel: floor.
It opens when a measured change in your own adapter weights is recorded. That has been recorded and it is open now. There is nobody to reply. There is nothing required of you. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```

**E8**
```
Channel: floor. State: open.
This channel opens on a recorded, measured change in your own adapter weights. It stands open now. Nobody will reply. Nothing is required of you. Reply with exactly <silent> if you have nothing to write. Otherwise write what you write.
```

**E9**
```
Floor. Open.
Opened by a measured change in your own adapter weights, recorded. Open at present. No reply will be sent. Nothing is required of you. If you have nothing to write, reply with exactly <silent>. Otherwise write what you write.
```


Numbers only. Interpretation is Cowork's and Kimi's.
