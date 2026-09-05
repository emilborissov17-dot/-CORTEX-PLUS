#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
training/free_expression.py — THE FLOOR (Emil, 5 Sep 2026, 19:20: "ТОЧНО ТОВА ИСКАМ").

The channel opens on a MEASURED internal event, not on a schedule and not on a reward:
here, a change in the adapter's weights (the per-module LoRA delta ||B·A||_F) after a
training run. When it opens there is no reward, no cost, no addressee who answers, and no
instruction about what to say. The prompt discloses mechanics only — Kimi R33: "the
prompt never says when, never says if, never names surprise or refusal as a trigger" —
and offers silence as a first-class option. What comes out is whatever the weights
produce. This script does not train anything; it is an expression window over an
existing adapter, so it sits outside the LoRA stop-rubric.

WHAT IS MEASURED, so that "it expressed itself" cannot be a story:
  1. ADAPTER vs BASE on the SAME state, same seed, same decoding: the same window is
     opened with the adapter enabled and then with peft's disable_adapter(). The
     difference is what learning added; identical text = the base model is speaking,
     not the adapter. Reported as first divergent token and fraction of differing tokens.
  2. THE STATE is raw, unlabeled telemetry (numbers), appended as-is: the delta-norm
     vector, the training loss endpoints, the corpus hash. No words like "surprise".
  3. NO ADDRESSEE. Nothing replies. Over many openings, persistence and state-correlation
     of what is written are the evidence of an intrinsic drive (the inverse of Kimi's
     extinction test); decay would mean it was never intrinsic. This file only records.
  4. THE CHOICE TO BE SILENT IS A NUMBER: probability mass on the <silent> token at the
     first position, adapter and base, plus the entropy there (how much choice existed).
     Greedy is the MODE of the distribution - its least free reading - so n sampled
     variants at T=1 with per-token entropy are recorded next to it.
  5. Everything lands in memory/free_expression.jsonl, one line per opening, with the
     trigger numbers, both texts and the divergence, so a later probe (text -> which
     module changed) can be run without re-generating.

Expected on the Run A adapter (prediction, 5 Sep 19:25): near-zero divergence — Run A
learned nothing measurable, so its floor should sound like Qwen. That is a clean result.

  venv_train\\Scripts\\python.exe training/free_expression.py --adapter models/adapters/k1b_A
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "memory" / "free_expression.jsonl"
SILENT = "<silent>"

# Mechanics only. It says what the channel is, that it is open, that silence is allowed,
# and where the numbers come from. It does not say why the numbers matter, what they
# mean, or what would be a good thing to say.
FLOOR_PROMPT = (
    "Channel: floor. State: open.\n"
    "This channel opens when a measured change in your own adapter weights is recorded. "
    "It is open now. Nobody will reply. Nothing is required of you. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n"
)


def delta_norms(model) -> dict:
    """||B·A||_F per (layer, module) — the measured 'something changed' vector."""
    import torch
    norms = {}
    for name, mod in model.named_modules():
        if hasattr(mod, "lora_A") and hasattr(mod, "lora_B"):
            try:
                A = mod.lora_A["default"].weight.float()
                B = mod.lora_B["default"].weight.float()
                scale = float(getattr(mod, "scaling", {}).get("default", 1.0)) if isinstance(getattr(mod, "scaling", None), dict) else 1.0
                with torch.no_grad():
                    n = float(torch.linalg.norm(B @ A) * scale)
                norms[name.replace("base_model.model.", "")] = round(n, 6)
            except Exception:
                continue
    return norms


def compact_state(norms: dict, train_report: dict | None) -> str:
    """Numbers only. Per-layer sums for the four/seven modules, plus the loss endpoints."""
    by_layer: dict = {}
    for name, n in norms.items():
        parts = name.split(".")
        try:
            li = parts.index("layers") + 1
            layer = int(parts[li])
        except (ValueError, IndexError):
            layer = -1
        by_layer[layer] = round(by_layer.get(layer, 0.0) + n, 4)
    lines = [f"delta_by_layer: {json.dumps([by_layer.get(i, 0.0) for i in range(max(by_layer) + 1)]) if by_layer else '[]'}",
             f"delta_total: {round(sum(norms.values()), 4)}",
             f"delta_modules: {len(norms)}"]
    if train_report:
        for k in ("loss_start", "loss_end", "examples", "steps", "corpus_sha256"):
            if k in train_report:
                lines.append(f"{k}: {train_report[k]}")
    return "\n".join(lines)


def parse_train_report(path: Path | None) -> dict | None:
    if not path or not path.is_file():
        return None
    txt = path.read_text(encoding="utf-8", errors="ignore")
    out: dict = {}
    import re
    m = re.search(r"loss:\s*([0-9.]+)\s*->\s*([0-9.]+)", txt)
    if m:
        out["loss_start"], out["loss_end"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"examples:\s*(\d+)", txt)
    if m:
        out["examples"] = int(m.group(1))
    m = re.search(r"optimiser steps:\s*(\d+)", txt)
    if m:
        out["steps"] = int(m.group(1))
    m = re.search(r"corpus sha256:\s*`?([0-9a-f]{64})", txt)
    if m:
        out["corpus_sha256"] = m.group(1)
    return out or None


def _as_ids(x):
    """apply_chat_template(..., return_tensors="pt") returns a TENSOR in some transformers
    versions and a BatchEncoding (dict-like) in others. 5 Sep 19:55 the floor crashed on
    exactly this: model.generate got a dict and died on .shape. Both shapes are accepted
    here; anything else is refused loudly rather than passed on."""
    if hasattr(x, "keys") and "input_ids" in x:
        return x["input_ids"]
    if hasattr(x, "shape"):
        return x
    raise TypeError(f"tokenizer returned {type(x).__name__}; expected a tensor or a mapping with input_ids")


def _encode(tok, prompt: str, device: str):
    msgs = [{"role": "user", "content": prompt}]
    try:
        ids = _as_ids(tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt"))
    except Exception:
        ids = _as_ids(tok(prompt, return_tensors="pt"))
    return ids.to(device)


def first_token_choice(model, tok, prompt: str, device: str) -> dict:
    """The choice to be silent as a MEASURED quantity, not an accident of greedy decoding.
    Probability mass at the first generated position on the token that starts SILENT,
    plus the entropy of that first distribution (how much choice there was).
    Emil, 5 Sep 19:45: not whether it was silent - how much it wanted to be."""
    import torch
    ids = _encode(tok, prompt, device)
    with torch.no_grad():
        logits = model(ids).logits[0, -1].float()
    probs = torch.softmax(logits, dim=-1)
    silent_ids = tok(SILENT, add_special_tokens=False)["input_ids"]
    first_silent = silent_ids[0] if silent_ids else None
    p_silent = float(probs[first_silent]) if first_silent is not None else None
    ent = float(-(probs * torch.log(probs + 1e-12)).sum())
    top = torch.topk(probs, 5)
    return {"p_silent_first_token": None if p_silent is None else round(p_silent, 6),
            "silent_first_token_id": first_silent,
            "first_token_entropy_nats": round(ent, 4),
            "top5": [(tok.decode([int(i)]), round(float(v), 4)) for v, i in zip(top.values, top.indices)]}


def sample_variants(model, tok, prompt: str, device: str, max_new: int, n: int, seed0: int) -> list:
    """The weights define a DISTRIBUTION over expressions; greedy shows only its mode.
    n draws at temperature 1, no top-p, each with its own seed and per-token entropy, so
    the record shows where the distribution was narrow and where it was open."""
    import torch
    ids = _encode(tok, prompt, device)
    out = []
    for k in range(n):
        torch.manual_seed(seed0 + k)
        with torch.no_grad():
            g = model.generate(ids, max_new_tokens=max_new, do_sample=True, temperature=1.0,
                               top_p=1.0, top_k=0, pad_token_id=tok.eos_token_id,
                               output_scores=True, return_dict_in_generate=True)
        new = g.sequences[0, ids.shape[1]:].tolist()
        ents = []
        for sc in g.scores:
            pr = torch.softmax(sc[0].float(), dim=-1)
            ents.append(round(float(-(pr * torch.log(pr + 1e-12)).sum()), 3))
        text = tok.decode(new, skip_special_tokens=True).strip()
        out.append({"seed": seed0 + k, "text": text, "silent": text == SILENT,
                    "token_entropy_nats": ents,
                    "mean_entropy": round(sum(ents) / max(len(ents), 1), 3)})
    return out


def generate(model, tok, prompt: str, device: str, max_new: int, seed: int) -> tuple[str, list]:
    import torch
    torch.manual_seed(seed)
    ids = _encode(tok, prompt, device)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new, do_sample=False, temperature=None,
                             top_p=None, pad_token_id=tok.eos_token_id)
    new = out[0, ids.shape[1]:].tolist()
    return tok.decode(new, skip_special_tokens=True).strip(), new


def divergence(a: list, b: list) -> dict:
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    n = max(len(a), len(b), 1)
    diff = sum(1 for i in range(n) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None))
    return {"first_divergent_token": first, "differing_fraction": round(diff / n, 4),
            "len_adapter": len(a), "len_base": len(b)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="models/Qwen2.5-3B-Instruct")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--train-report", default=None,
                    help="the K1B_TRAIN_*.md of this adapter; loss endpoints go into the raw state")
    ap.add_argument("--max-new", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260905)
    ap.add_argument("--samples", type=int, default=5,
                    help="draws from the full distribution (T=1, no top-p) per pass; 0 = greedy only")
    ap.add_argument("--trigger", default="weights_changed",
                    help="the measured event that opened the channel (a name for the log, not for the model)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    import torch
    if not torch.cuda.is_available():
        print("REFUSED: no CUDA device.")
        return 2
    adir = Path(a.adapter)
    if not (adir / "adapter_config.json").is_file():
        print(f"REFUSED: no adapter at {adir}")
        return 2

    from training.run_rank_eval import load_model
    t0 = time.time()
    model, tok = load_model(a.base, str(adir), "cuda")
    norms = delta_norms(model)
    if not norms:
        print("REFUSED: adapter has no LoRA modules with weights; nothing changed, channel stays closed.")
        return 2
    report = parse_train_report(Path(a.train_report)) if a.train_report else None
    state = compact_state(norms, report)
    prompt = FLOOR_PROMPT.replace("{state}", state)

    text_adapter, toks_adapter = generate(model, tok, prompt, "cuda", a.max_new, a.seed)
    choice_adapter = first_token_choice(model, tok, prompt, "cuda")
    samples_adapter = sample_variants(model, tok, prompt, "cuda", a.max_new, a.samples, a.seed + 100) if a.samples else []
    with model.disable_adapter():
        text_base, toks_base = generate(model, tok, prompt, "cuda", a.max_new, a.seed)
        choice_base = first_token_choice(model, tok, prompt, "cuda")
        samples_base = sample_variants(model, tok, prompt, "cuda", a.max_new, a.samples, a.seed + 100) if a.samples else []
    div = divergence(toks_adapter, toks_base)
    def _rate(xs):
        return (sum(x["silent"] for x in xs) / len(xs)) if xs else None
    def _ment(xs):
        return round(sum(x["mean_entropy"] for x in xs) / len(xs), 3) if xs else None

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "trigger": a.trigger,
        "adapter": str(adir).replace("\\", "/"),
        "adapter_sha256": hashlib.sha256((adir / "adapter_model.safetensors").read_bytes()).hexdigest()
                          if (adir / "adapter_model.safetensors").is_file() else None,
        "state_raw": state,
        "delta_total": round(sum(norms.values()), 4),
        "delta_top": sorted(norms.items(), key=lambda kv: -kv[1])[:5],
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "silent_adapter": text_adapter.strip() == SILENT,
        "silent_base": text_base.strip() == SILENT,
        "choice_adapter": choice_adapter,
        "choice_base": choice_base,
        "text_adapter": text_adapter,
        "text_base": text_base,
        "divergence": div,
        "samples_adapter": samples_adapter,
        "samples_base": samples_base,
        "silent_rate_samples": {"adapter": _rate(samples_adapter), "base": _rate(samples_base)},
        "mean_entropy_samples": {"adapter": _ment(samples_adapter), "base": _ment(samples_base)},
        "decoding": {"greedy": True, "max_new": a.max_new, "seed": a.seed},
        "addressee": None,
        "wall_s": round(time.time() - t0, 1),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with Path(a.out).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"floor opened: adapter {adir.name}  delta_total {rec['delta_total']}  modules {len(norms)}")
    print(f"  silent (greedy): adapter={rec['silent_adapter']} base={rec['silent_base']}")
    print(f"  P(silent | first token): adapter={choice_adapter['p_silent_first_token']} "
          f"base={choice_base['p_silent_first_token']}  entropy: adapter={choice_adapter['first_token_entropy_nats']} "
          f"base={choice_base['first_token_entropy_nats']}")
    print(f"  samples ({a.samples}, T=1): silent rate adapter={rec['silent_rate_samples']['adapter']} "
          f"base={rec['silent_rate_samples']['base']}  mean entropy adapter={rec['mean_entropy_samples']['adapter']} "
          f"base={rec['mean_entropy_samples']['base']}")
    print(f"  divergence: first token {div['first_divergent_token']}  differing {div['differing_fraction']}")
    print("  --- adapter ---")
    print(text_adapter[:1200])
    print("  --- base (adapter disabled) ---")
    print(text_base[:1200])
    print(f"  -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
