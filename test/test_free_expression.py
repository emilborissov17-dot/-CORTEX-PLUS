"""training/free_expression.py — the floor: mechanics-only prompt, raw state, measured divergence.

Each test names the ceremony it blocks:
  * the prompt must not name a trigger, a feeling, or a desired content (Kimi R33);
  * silence must be offered as a first-class option;
  * the raw state must be numbers only — no interpretive label;
  * divergence must be computed from tokens, and identical outputs must read as 0.
"""
from __future__ import annotations

import re
from pathlib import Path

from training import free_expression as fe

REPO = Path(__file__).resolve().parents[1]


def test_prompt_is_mechanics_only():
    p = fe.FLOOR_PROMPT
    for forbidden in ("surprise", "surprised", "refus", "reward", "should", "important",
                      "feel", "learned", "please", "good", "insight"):
        assert forbidden not in p.lower(), f"prompt smuggles guidance: {forbidden!r}"
    assert fe.SILENT in p
    assert "Nobody will reply" in p and "Nothing is required" in p


def test_state_is_numbers_only():
    norms = {"model.layers.0.self_attn.q_proj": 0.5, "model.layers.1.self_attn.v_proj": 0.25,
             "model.layers.1.self_attn.o_proj": 0.1}
    s = fe.compact_state(norms, {"loss_start": 2.26, "loss_end": 1.99, "examples": 1077,
                                 "steps": 134, "corpus_sha256": "ab" * 32})
    assert "delta_by_layer: [0.5, 0.35]" in s
    assert "delta_total: 0.85" in s
    # every line is key: value with a number, a list of numbers, or a hex hash
    for line in s.splitlines():
        k, v = line.split(": ", 1)
        assert re.fullmatch(r"[a-z_0-9]+", k)
        assert re.fullmatch(r"-?[0-9.]+|\[[-0-9., ]*\]|[0-9a-f]{64}", v), line


def test_parse_train_report(tmp_path):
    p = tmp_path / "K1B_TRAIN_A.md"
    p.write_text("- examples: 1077  ·  optimiser steps: 134  ·  wall: 6932.5s\n"
                 "- loss: 2.2571 -> 1.993\n- corpus sha256: `" + "0" * 64 + "`\n", encoding="utf-8")
    r = fe.parse_train_report(p)
    assert r == {"loss_start": 2.2571, "loss_end": 1.993, "examples": 1077, "steps": 134,
                 "corpus_sha256": "0" * 64}
    assert fe.parse_train_report(tmp_path / "missing.md") is None


def test_divergence_counts_tokens_not_stories():
    assert fe.divergence([1, 2, 3], [1, 2, 3]) == {"first_divergent_token": None, "differing_fraction": 0.0,
                                                   "len_adapter": 3, "len_base": 3}
    d = fe.divergence([1, 2, 3, 4], [1, 9, 3])
    assert d["first_divergent_token"] == 1 and d["differing_fraction"] == 0.5
    d = fe.divergence([1, 2], [1, 2, 3])
    assert d["first_divergent_token"] == 2 and d["differing_fraction"] == round(1 / 3, 4)


def test_silence_and_freedom_are_recorded_as_numbers():
    # The record must carry P(silent) at the first token and sampled variants with entropy —
    # greedy alone is the mode of the distribution, its least free reading.
    src = (REPO / "training" / "free_expression.py").read_text(encoding="utf-8")
    for key in ('"choice_adapter"', '"choice_base"', '"samples_adapter"', '"samples_base"',
                '"silent_rate_samples"', "p_silent_first_token", "first_token_entropy_nats",
                "token_entropy_nats"):
        assert key in src, f"the floor no longer records {key}"
    assert "temperature=1.0" in src and "top_p=1.0" in src, "sampling must be from the full distribution"


def test_encode_accepts_both_tokenizer_return_shapes():
    """5 Sep 19:55: the floor crashed because apply_chat_template returned a BatchEncoding and
    model.generate got a dict. The earlier five tests never touched encoding, so 'tests green'
    said nothing about whether the floor could open. This one exercises the exact seam."""
    class _T:
        def __init__(self, v): self.v = v
        def to(self, device): return self
        @property
        def shape(self): return (1, len(self.v))

    class BatchLike(dict):
        pass

    class TokDict:  # transformers >= 4.4x: returns a mapping
        def apply_chat_template(self, msgs, add_generation_prompt, return_tensors):
            return BatchLike(input_ids=_T([1, 2, 3]), attention_mask=_T([1, 1, 1]))

    class TokTensor:  # older: returns the tensor itself
        def apply_chat_template(self, msgs, add_generation_prompt, return_tensors):
            return _T([4, 5])

    class TokBroken:  # no chat template at all -> fallback path, also a mapping
        def apply_chat_template(self, *a, **k):
            raise ValueError("no chat template")
        def __call__(self, prompt, return_tensors):
            return {"input_ids": _T([9])}

    assert fe._encode(TokDict(), "x", "cpu").shape == (1, 3)
    assert fe._encode(TokTensor(), "x", "cpu").shape == (1, 2)
    assert fe._encode(TokBroken(), "x", "cpu").shape == (1, 1)
    import pytest as _pt
    with _pt.raises(TypeError):
        fe._as_ids("not a tensor")
