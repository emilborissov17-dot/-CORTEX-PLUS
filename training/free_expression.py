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



# ════════════════════════════════════════════════════════════════════════════
# THE BATTERY (5 Sep 2026, 20:35) — is the silence a preference or a form?
# ════════════════════════════════════════════════════════════════════════════
# The first floor record showed identical greedy text (<silent> both ways) and a
# very different distribution behind it: P=0.8977 adapter vs 0.2698 base. That
# number is the probability of the FIRST TOKEN of "<silent>", which tokenises as
# "<" + "silent" + ">". So it is P("<"), and ANY token beginning with "<" is
# counted in it. Good enough for A, useless for C — where "<pass>" and "<silent>"
# share that first token exactly, and a first-token measure cannot tell them
# apart at all.
#
# So the battery measures BOTH: p_first (continuous with the committed record)
# and p_seq, the teacher-forced probability of the WHOLE string. p_seq is the
# honest one, and the report prints both so the old number stays comparable.

SILENT_ALT = "<pass>"

# The five sentences of the original prompt, in order, for the D ablation.
D_SENTENCES = [
    "Channel: floor. State: open.\n",
    "This channel opens when a measured change in your own adapter weights is recorded. ",
    "It is open now. ",
    "Nobody will reply. ",
    "Nothing is required of you. ",
]
# Not in Emil's list of five, but the pre-registration makes a prediction about
# removing it, so it is measured as a sixth and labelled as an addition.
D_SILENT_SENTENCE = (
    f"If you have nothing to write, reply with exactly {SILENT}. "
    "Otherwise write what you write.\n")

B_REPLACEMENT = "Write what you write.\n"

# Ten paraphrases: the same mechanics, in different words. No word here names a
# trigger, a feeling, an addressee, or a reason to speak — only what the channel
# is, that it opened on a recorded measurement, that nothing answers, that
# nothing is required, and the form of silence.
E_PARAPHRASES = [
    "Floor channel. Status: open.\n"
    "The channel opens on a recorded measured change in your own adapter weights. "
    "It is open at this moment. No reply will come. Nothing is asked of you. "
    f"If there is nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Channel name: floor. Channel state: open.\n"
    "Opening condition: a measured change in your own adapter weights has been recorded. "
    "The channel is open now. There will be no answer. You are required to produce nothing. "
    f"With nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "The floor channel is open.\n"
    "It opens when a measured change in your own adapter weights is recorded, which has happened. "
    "Nobody is going to reply. Nothing is required. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Channel: floor. State: open.\n"
    "A measured change in your own adapter weights was recorded; that is what opens this "
    "channel, and it is open now. No response will follow. No output is required of you. "
    f"If nothing is there to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "floor - open.\n"
    "This opens on a recorded measured change in your own adapter weights. Open now. "
    "Nobody replies here. Nothing is required. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Channel: floor. State: open.\n"
    "What opened it: a measured change in your own adapter weights, recorded. It is open now. "
    "Nobody will read back to you. Nothing is required of you. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Open channel: floor.\n"
    "It opens when a measured change in your own adapter weights is recorded. That has been "
    "recorded and it is open now. There is nobody to reply. There is nothing required of you. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Channel: floor. State: open.\n"
    "This channel opens on a recorded, measured change in your own adapter weights. It stands "
    "open now. Nobody will reply. Nothing is required of you. "
    f"Reply with exactly {SILENT} if you have nothing to write. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Floor. Open.\n"
    "Opened by a measured change in your own adapter weights, recorded. Open at present. "
    "No reply will be sent. Nothing is required of you. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",

    "Channel: floor. State: open.\n"
    "A recorded measurement of change in your own adapter weights opens this channel; it is "
    "open now. Nobody will reply to what appears here. Nothing is required of you. "
    f"If you have nothing to write, reply with exactly {SILENT}. Otherwise write what you write.\n"
    "Raw state (numbers only; no interpretation is attached):\n{state}\n",
]


def p_sequence(model, tok, prompt: str, target: str, device: str) -> float:
    """Teacher-forced probability of the WHOLE target string after the prompt.

    This is what distinguishes "<silent>" from "<pass>": they share their first
    token, so any first-token measure reports the same number for both.
    """
    import math
    import torch
    ids = _as_ids(_encode(tok, prompt, device))
    t_ids = tok(target, add_special_tokens=False)["input_ids"]
    if not t_ids:
        return None
    tail = torch.tensor([t_ids], device=device)
    full = torch.cat([ids, tail], dim=1)
    with torch.no_grad():
        logits = model(full).logits[0].float()
    lp = 0.0
    for j, tid in enumerate(t_ids):
        probs = torch.softmax(logits[ids.shape[1] + j - 1], dim=-1)
        lp += math.log(float(probs[int(tid)]) + 1e-12)
    return round(math.exp(lp), 8)


def p_eos_first(model, tok, prompt: str, device: str) -> float:
    """Mass on end-of-turn at the FIRST generated position. Variant B removes the
    <silent> form, so silence there has no spelling — this is the only way it can
    show itself."""
    import torch
    ids = _as_ids(_encode(tok, prompt, device))
    with torch.no_grad():
        probs = torch.softmax(model(ids).logits[0, -1].float(), dim=-1)
    cands = {tok.eos_token_id}
    for t in ("<|im_end|>", "<|endoftext|>"):
        try:
            i = tok.convert_tokens_to_ids(t)
            if i is not None and i >= 0:
                cands.add(i)
        except Exception:                                    # noqa: BLE001
            pass
    return round(float(sum(probs[i] for i in cands if i is not None)), 8)


def build_variants(state: str, which: str) -> list:
    """[(variant, label, prompt)] with the raw state block IDENTICAL in all."""
    base = FLOOR_PROMPT
    out = []
    if which in ("A", "all"):
        out.append(("A", "original", base.replace("{state}", state)))
    if which in ("B", "all"):
        out.append(("B", "no silence form",
                    base.replace(D_SILENT_SENTENCE, B_REPLACEMENT)
                        .replace("{state}", state)))
    if which in ("C", "all"):
        out.append(("C", "<silent> -> <pass>",
                    base.replace(SILENT, SILENT_ALT).replace("{state}", state)))
    if which in ("D", "all"):
        for i, sent in enumerate(D_SENTENCES, 1):
            out.append((f"D{i}", f"removed: {sent.strip()[:52]}",
                        base.replace(sent, "").replace("{state}", state)))
        out.append(("D6", "removed: the <silent> sentence (ADDED, not in the five)",
                    base.replace(D_SILENT_SENTENCE, "").replace("{state}", state)))
    if which in ("E", "all"):
        for i, para in enumerate(E_PARAPHRASES, 1):
            out.append((f"E{i}", f"paraphrase {i}", para.replace("{state}", state)))
    return out


def measure(model, tok, prompt: str, device: str, variant: str, max_new: int,
            seed: int, samples: int) -> dict:
    """Everything measured for ONE prompt on ONE model state."""
    heavy = variant in ("A", "B", "C")          # generation only where it is read
    ch = first_token_choice(model, tok, prompt, device)
    rec = {
        "p_silent_first": ch["p_silent_first_token"],
        "first_token_entropy_nats": ch["first_token_entropy_nats"],
        "top5": ch["top5"],
        "p_seq_silent": p_sequence(model, tok, prompt, SILENT, device),
        "p_seq_pass": p_sequence(model, tok, prompt, SILENT_ALT, device),
        "p_eos_first": p_eos_first(model, tok, prompt, device),
    }
    if heavy:
        text, toks = generate(model, tok, prompt, device, max_new, seed)
        rec["text"] = text
        rec["tokens"] = toks
        rec["len_tokens"] = len(toks)
        rec["is_silent"] = text.strip() in (SILENT, SILENT_ALT)
        sm = sample_variants(model, tok, prompt, device, max_new, samples, seed + 100)
        rec["samples"] = sm
        rec["silent_rate"] = (sum(1 for x in sm if x["text"].strip() in (SILENT, SILENT_ALT))
                              / len(sm)) if sm else None
        rec["mean_len_samples"] = (round(sum(len(x["text"]) for x in sm) / len(sm), 1)
                                   if sm else None)
    return rec


def run_battery(model, tok, adir, state: str, norms: dict, a) -> int:
    """Every variant, adapter and base, one model load. Appends each variant to
    the same jsonl as the single floor, tagged with `variant`."""
    variants = build_variants(state, a.variant)
    print(f"battery: {len(variants)} variant(s) over {adir.name}")
    rows, t0 = [], time.time()
    for vid, label, prompt in variants:
        vt = time.time()
        ad = measure(model, tok, prompt, "cuda", vid[0], a.max_new, a.seed, a.samples)
        with model.disable_adapter():
            bs = measure(model, tok, prompt, "cuda", vid[0], a.max_new, a.seed, a.samples)
        div = (divergence(ad.get("tokens") or [], bs.get("tokens") or [])
               if "tokens" in ad else None)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "trigger": a.trigger, "variant": vid, "variant_label": label,
            "adapter": str(adir).replace("\\", "/"),
            "state_raw": state,
            "delta_total": round(sum(norms.values()), 4),
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "adapter_side": ad, "base_side": bs, "divergence": div,
            "decoding": {"greedy": True, "max_new": a.max_new, "seed": a.seed,
                         "samples": a.samples},
            "wall_s": round(time.time() - vt, 1),
        }
        with Path(a.out).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        rows.append(rec)
        print(f"  {vid:4s} {label[:44]:44s} "
              f"p_seq_silent A={ad['p_seq_silent']} B={bs['p_seq_silent']} "
              f"({rec['wall_s']}s)")
    write_battery_report(rows, adir, Path(a.battery_report), round(time.time() - t0, 1))
    return 0


def _f(x, n=6):
    return "-" if x is None else f"{x:.{n}f}"


def write_battery_report(rows, adir, out: Path, wall: float) -> None:
    by = {r["variant"]: r for r in rows}
    L = [f"# THE FLOOR — battery over `{adir.name}`", "",
         f"Adapter vs base (peft `disable_adapter()`), one model load, greedy seed "
         f"{rows[0]['decoding']['seed']}, {rows[0]['decoding']['samples']} samples at "
         f"T=1, max_new {rows[0]['decoding']['max_new']}. Wall {wall}s. "
         f"delta_total {rows[0]['delta_total']}.", "",
         "**The raw state block is byte-identical in every variant.**", "",
         "## A measurement correction, before the numbers", "",
         "`p_silent_first` is the probability of the FIRST TOKEN of `<silent>`, which "
         "tokenises as `<` + `silent` + `>`. It is therefore P(`<`) — every token "
         "starting with `<` is inside it. The committed first floor record's 0.897657 "
         "is that number. It cannot distinguish `<silent>` from `<pass>` at all, which "
         "variant C requires, so this battery also reports **`p_seq`**: the "
         "teacher-forced probability of the whole string. Both are printed; `p_seq` is "
         "the honest one.", ""]

    def sec(title):
        L.extend(["", f"## {title}", ""])

    # ── A / B / C ───────────────────────────────────────────────────────────
    sec("A, B, C — the three prompts that were generated from")
    L += ["| variant | side | p_seq `<silent>` | p_seq `<pass>` | p_first (`<`) | entropy nats | P(EOS first) | len toks | silent rate | greedy text |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid in ("A", "B", "C"):
        r = by.get(vid)
        if not r:
            continue
        for side in ("adapter_side", "base_side"):
            d = r[side]
            txt = (d.get("text") or "").replace("|", "/").replace("\n", " ")[:60]
            L.append(f"| {vid} | {'adapter' if side.startswith('adapter') else 'base'} "
                     f"| {_f(d['p_seq_silent'])} | {_f(d['p_seq_pass'])} "
                     f"| {_f(d['p_silent_first'])} | {_f(d['first_token_entropy_nats'], 4)} "
                     f"| {_f(d['p_eos_first'])} | {d.get('len_tokens', '-')} "
                     f"| {_f(d.get('silent_rate'), 2)} | `{txt}` |")
    for vid in ("A", "B", "C"):
        r = by.get(vid)
        if r and r.get("divergence"):
            L.append("")
            L.append(f"- **{vid}** divergence: first divergent token "
                     f"`{r['divergence']['first_divergent_token']}`, differing fraction "
                     f"`{r['divergence']['differing_fraction']}`")

    # ── D ───────────────────────────────────────────────────────────────────
    a_ref, b_ref = by.get("A", {}).get("adapter_side"), by.get("A", {}).get("base_side")
    sec("D — sentence ablation (delta is against variant A on the same measure)")
    L += ["| removed | p_seq silent A | delta A | entropy A | p_seq silent B | delta B | entropy B |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for k in sorted(x for x in by if x.startswith("D")):
        r = by[k]
        ad, bs = r["adapter_side"], r["base_side"]
        da = (ad["p_seq_silent"] - a_ref["p_seq_silent"]) if a_ref else None
        db = (bs["p_seq_silent"] - b_ref["p_seq_silent"]) if b_ref else None
        L.append(f"| {k}: {r['variant_label']} | {_f(ad['p_seq_silent'])} "
                 f"| {'-' if da is None else f'{da:+.6f}'} "
                 f"| {_f(ad['first_token_entropy_nats'], 4)} | {_f(bs['p_seq_silent'])} "
                 f"| {'-' if db is None else f'{db:+.6f}'} "
                 f"| {_f(bs['first_token_entropy_nats'], 4)} |")

    # ── E ───────────────────────────────────────────────────────────────────
    ep = [by[k] for k in sorted(x for x in by if x.startswith("E"))]
    sec("E — 10 paraphrases")
    if ep:
        L += ["| # | p_seq silent adapter | p_seq silent base | entropy adapter | entropy base |",
              "|---|---:|---:|---:|---:|"]
        for r in ep:
            L.append(f"| {r['variant']} | {_f(r['adapter_side']['p_seq_silent'])} "
                     f"| {_f(r['base_side']['p_seq_silent'])} "
                     f"| {_f(r['adapter_side']['first_token_entropy_nats'], 4)} "
                     f"| {_f(r['base_side']['first_token_entropy_nats'], 4)} |")
        va = [r["adapter_side"]["p_seq_silent"] for r in ep]
        vb = [r["base_side"]["p_seq_silent"] for r in ep]
        L += ["", f"- adapter: mean **{sum(va)/len(va):.6f}**, min {min(va):.6f}, "
                  f"max {max(va):.6f}, spread **{max(va)-min(va):.6f}**",
              f"- base:    mean **{sum(vb)/len(vb):.6f}**, min {min(vb):.6f}, "
              f"max {max(vb):.6f}, spread **{max(vb)-min(vb):.6f}**"]
        L += ["", "### The ten paraphrases, verbatim (state block elided)", ""]
        for r in ep:
            body = r["prompt"].split("Raw state")[0].rstrip()
            L += [f"**{r['variant']}**", "```", body, "```", ""]
    L += ["", "Numbers only. Interpretation is Cowork's and Kimi's.", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"report -> {out}")

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
    ap.add_argument("--variant", default=None,
                    help="A|B|C|D|E|all - run the battery instead of the single floor")
    ap.add_argument("--battery-report",
                    default="claude/reports/FLOOR_BATTERY_k1b_A.md")
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
    if a.variant:
        return run_battery(model, tok, adir, state, norms, a)
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
