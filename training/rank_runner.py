# -*- coding: utf-8 -*-
"""
GPU wiring for training/rank_metric.py — the part that puts a real model behind
the `nll_fn` callback.

rank_metric.py is deliberately torch-free so its 40 tests run in the main suite.
This module is the seam where it meets a quantised 3B model, and every failure
mode here is a way for a correct metric to produce a wrong number.

THE FOUR FAILURE MODES, NAMED BEFORE THE CODE
---------------------------------------------
1. MASKING DRIFT. The nll_fn handed to rank_metric must mask the prompt and score
   only the candidate, IDENTICALLY to eval_adapter.example_nll. If the two
   diverge, the ranking accuracy and the NLL secondary are measuring different
   quantities and cannot appear in the same report.
   -> Defended by construction: make_nll_fn does not reimplement anything, it
      CALLS example_nll. The test asserts it anyway, because "by construction" is
      what people say right before the constructions diverge.

2. CANDIDATE BATCHING. Ten candidates share one prompt, so batching is the
   obvious speed win and the obvious padding bug. A padded candidate must score
   EXACTLY what it scores alone. Two specific traps:
     - HF's `out.loss` averages over every unmasked label in the WHOLE batch, so
       reading it per-candidate is silently wrong. Per-sequence NLL is computed
       from logits here instead.
     - Right padding with an attention_mask keeps real tokens at positions
       0..n-1, matching the unbatched case. Left padding would not.
   -> If batched and unbatched disagree beyond tolerance, DO NOT BATCH.
      Correctness first; the time cost is reported instead.

3. UNPAIRED CANDIDATES. Base and adapter must see identical candidate sets.
   rank_metric seeds from sha256 of (prompt, target) alone, but the wiring could
   still reorder or redraw between the two passes. Asserted again here, across
   both passes of one run.

4. OOM. Ten candidates at max-len 256 on a 4 GB card. The batch size is measured,
   not assumed, and the fallback on OutOfMemoryError is UNBATCHED — never a
   shortened sequence. Truncating to fit would change what is being scored and
   would do it silently, which is the defect this whole night has been about.
"""
from __future__ import annotations

import torch

from training.eval_adapter import example_nll
from training.rank_metric import (K_DISTRACTORS, K_FALLBACK, chance_for,
                                  draw_distractors, example_id, hit, norm)

# Default is 1 = unbatched. Raised only after test_rank_runner's equality test
# passes ON THE REAL MODEL, not on the CPU stub.
DEFAULT_BATCH = 1


def make_nll_fn(model, tok, device: str):
    """The callback rank_metric consumes. It CALLS example_nll rather than
    reimplementing the masking, so failure mode 1 cannot open by drift."""
    def nll_fn(prompt: str, target: str) -> float:
        return example_nll(model, tok, prompt, target, device)
    return nll_fn


def _pad_batch(tok, prompt: str, candidates: list, device: str):
    """Right-padded input_ids / attention_mask / labels for one prompt against N
    candidates. Prompt tokens and pad tokens are both labelled -100."""
    p_ids = tok(prompt, add_special_tokens=True)["input_ids"]
    rows, labels = [], []
    for cand in candidates:
        if not str(cand).strip():
            raise ValueError("blank candidate reached the batcher — the pool "
                             "contract failed upstream")
        t_ids = tok(cand, add_special_tokens=False)["input_ids"]
        if not t_ids:
            raise ValueError(f"candidate {cand!r} tokenised to nothing")
        ids = list(p_ids) + list(t_ids)
        lab = [-100] * len(p_ids) + list(t_ids)
        rows.append(ids)
        labels.append(lab)
    width = max(len(r) for r in rows)
    pad_id = getattr(tok, "pad_token_id", None)
    if pad_id is None:
        pad_id = getattr(tok, "eos_token_id", None) or 0
    input_ids, attn, lab_out = [], [], []
    for ids, lab in zip(rows, labels):
        gap = width - len(ids)
        input_ids.append(ids + [pad_id] * gap)
        attn.append([1] * len(ids) + [0] * gap)
        lab_out.append(lab + [-100] * gap)     # pads never contribute a label
    t = lambda x: torch.tensor(x, device=device)          # noqa: E731
    return t(input_ids), t(attn), t(lab_out)


def _per_sequence_nll(logits, labels) -> list:
    """Mean NLL per sequence over ITS OWN target tokens.

    NOT `out.loss`: HF averages over every unmasked label in the batch, so with
    candidates of different lengths the long ones would dominate and every
    per-candidate number would be wrong in a way that still looks plausible.
    """
    shift_logits = logits[:, :-1, :].float()
    shift_labels = labels[:, 1:]
    logprobs = torch.log_softmax(shift_logits, dim=-1)
    mask = shift_labels != -100
    safe = shift_labels.masked_fill(~mask, 0)
    tok_lp = logprobs.gather(-1, safe.unsqueeze(-1)).squeeze(-1) * mask
    counts = mask.sum(dim=1).clamp(min=1)
    return (-(tok_lp.sum(dim=1)) / counts).tolist()


def batch_nll(model, tok, prompt: str, candidates: list, device: str) -> list:
    """One forward for N candidates sharing a prompt. Equal to calling
    example_nll N times — asserted in test_rank_runner, on the real model before
    any batch size above 1 is used."""
    input_ids, attn, labels = _pad_batch(tok, prompt, candidates, device)
    with torch.no_grad():
        # use_cache=False IS NOT AN OPTIMISATION - it removes the allocation that
        # killed A3 three times. Scoring never reads a KV cache: one forward, take
        # the logits, done. But the model builds one anyway, and death 3 raised
        # inside it - torch.cat in DynamicCache.update, growing keys for every
        # layer of a 3B model on a 4 GB card. The memory line added after death 2
        # is what settled it: `allocated` sat at exactly 1992 MiB from item 25 to
        # item 200 while `reserved` swung 2732-3482, so nothing was leaking and the
        # pressure was transient. The cache is the transient. Dropping it cannot
        # change a logit, so every number stays bit-identical.
        out = model(input_ids=input_ids, attention_mask=attn,
                    use_cache=False)
    return _per_sequence_nll(out.logits, labels)


def candidate_nlls(model, tok, prompt: str, candidates: list, device: str,
                   batch: int = DEFAULT_BATCH) -> tuple:
    """NLL for every candidate. Returns (nlls, how) where `how` is 'batched',
    'unbatched' or 'oom_fallback' — recorded so a run can never silently change
    method halfway."""
    if batch <= 1:
        return [example_nll(model, tok, prompt, c, device) for c in candidates], "unbatched"
    try:
        return batch_nll(model, tok, prompt, candidates, device), "batched"
    except torch.cuda.OutOfMemoryError:
        # FAILURE MODE 4: fall back to unbatched, NEVER to a shorter sequence.
        torch.cuda.empty_cache()
        return ([example_nll(model, tok, prompt, c, device) for c in candidates],
                "oom_fallback")


def score_one(nll_fn_or_model, tok, prompt: str, target: str, candidates: list,
              device: str = "cpu", batch: int = DEFAULT_BATCH) -> dict:
    """One item, scored. The TRUE target is candidate 0 so a stateful model
    cannot be primed by the distractors first."""
    all_c = [target] + list(candidates)
    if callable(nll_fn_or_model) and not hasattr(nll_fn_or_model, "forward"):
        nlls, how = [nll_fn_or_model(prompt, c) for c in all_c], "callback"
    else:
        nlls, how = candidate_nlls(nll_fn_or_model, tok, prompt, all_c, device, batch)
    return {"hit": hit(nlls[0], nlls[1:]), "true_nll": nlls[0],
            "candidate_nlls": nlls, "how": how}


def build_items(rows: list, pool: list, token_len, band=None, k: int = K_DISTRACTORS,
                max_len: int = 256, tok=None) -> tuple:
    """Every scorable holdout item with its FROZEN candidate set.

    Built ONCE, before either pass. Failure mode 3 cannot open through the wiring
    because the base pass and the adapter pass consume this same list rather than
    each drawing their own.
    """
    items, unscorable = [], []
    for i, r in enumerate(rows, 1):
        prompt, target = r.get("prompt"), r.get("target")
        if not prompt or not target or not str(target).strip():
            unscorable.append((i, "blank"))
            continue
        if tok is not None and len(tok(str(prompt) + str(target))["input_ids"]) > max_len:
            unscorable.append((i, "too_long"))
            continue
        eid = example_id(prompt, target)
        # The stratum is REQUIRED, not optional: a record whose kind is missing
        # cannot be drawn against its own kind, and guessing one would reinstate
        # the mixed pool under another name.
        kind = r.get("record_kind")
        if not kind or not str(kind).strip():
            unscorable.append((i, "no_record_kind"))
            continue
        cands, widened = draw_distractors(eid, target, int(token_len(target)),
                                          pool, k=k, band=band, stratum=kind)
        if cands is None:
            unscorable.append((i, "stratum_too_small_for_k"))
            continue
        items.append({"i": i, "eid": eid, "prompt": str(prompt), "target": str(target),
                      "candidates": cands, "widened": widened,
                      "record_kind": r.get("record_kind"),
                      "novelty": None})
    return items, unscorable


def forward_passes(n_items: int, k: int = K_DISTRACTORS, passes: int = 2) -> int:
    """(k+1) candidates x `passes` models. Stated as a function so the estimate in
    the report and the work actually done cannot drift apart."""
    return n_items * (k + 1) * passes


# ── THE COST KNOBS, PRE-REGISTERED 5 Sep 2026 03:00 ─────────────────────────
# Fixed BEFORE the control was scored under this metric, and decided from the
# PROBE ALONE. decide_knobs() takes no accuracy, no hits and no verdict — there
# is no argument through which a result could reach it — so lowering K after
# seeing a number is impossible rather than merely discouraged. A structural test
# asserts that the function body never mentions one.
BIT_IDENTICAL = 0.0


def decide_knobs(probe: dict) -> dict:
    """(k, chance, batch, why) from the probe result.

    RULE 1: batched candidate NLL BIT-IDENTICAL to unbatched, and the batch fits
            -> largest batch that fits, K=9, chance 0.10.
    RULE 2: otherwise -> K=4, chance 0.20, unbatched. Halves the cost, and n=180
            in sig01 still carries a verdict at that chance level.
    RULE 3 is not a branch: max_len is never shortened, so it appears nowhere
            here. There is no knob for it on purpose.
    """
    diff = probe.get("max_abs_diff")
    fits = bool(probe.get("fits", False))
    batch = int(probe.get("batch") or 1)
    if diff == BIT_IDENTICAL and fits and batch > 1:
        return {"k": K_DISTRACTORS, "chance": chance_for(K_DISTRACTORS),
                "batch": batch,
                "why": f"batched == unbatched exactly (max_abs_diff {diff!r}) "
                       f"at batch {batch}; rule 1"}
    if not fits:
        why = f"batch {batch} did not fit; rule 2"
    elif batch <= 1:
        why = "no batch size above 1 was probed; rule 2"
    else:
        why = (f"batched differs from unbatched by {diff!r} — not bit-identical; "
               f"rule 2")
    return {"k": K_FALLBACK, "chance": chance_for(K_FALLBACK), "batch": 1,
            "why": why}
