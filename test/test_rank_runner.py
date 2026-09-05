# -*- coding: utf-8 -*-
"""
training/rank_runner.py — the four wiring failure modes, each with its test.

Written before anything ran on the GPU. Runs on CPU with a 1-layer GPT-2 built
from config: no download, no network, no card. Like test_eval_harness.py this
file is INERT under the main suite (venv/ has numpy only) and executes under:

    venv_train\\Scripts\\python.exe -m pytest test/test_rank_runner.py -q

The batching test is the one that decides a policy: if batched and unbatched
disagree on the real model, DEFAULT_BATCH stays 1 and the run costs what it
costs. This file proves the arithmetic is right; only the real model can prove
the kernels are.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

torch = pytest.importorskip("torch", reason="training stack lives in venv_train only")
pytest.importorskip("transformers", reason="training stack lives in venv_train only")
pytest.importorskip("peft", reason="training stack lives in venv_train only")

import training.rank_metric as rm            # noqa: E402
import training.rank_runner as rr            # noqa: E402
from training.eval_adapter import example_nll  # noqa: E402


class Tok:
    """Deterministic tokenizer with a real pad id, so padding is exercised."""
    pad_token_id = 0
    eos_token_id = 0

    def __call__(self, text, add_special_tokens=True):
        # NO `or [1]` fallback. A real tokenizer returns [] for "", and a stub
        # that quietly returns a token instead HID the batcher's empty-candidate
        # guard — caught 5 Sep 2026 by this very test failing for the wrong
        # reason. A stub kinder than reality tests nothing.
        return {"input_ids": [(ord(c) % 50) + 1 for c in str(text)]}


@pytest.fixture(scope="module")
def model():
    from transformers import GPT2Config, GPT2LMHeadModel
    cfg = GPT2Config(vocab_size=64, n_positions=256, n_embd=16, n_layer=1, n_head=1)
    torch.manual_seed(20260905)
    return GPT2LMHeadModel(cfg).eval()


def wordlen(s):
    return max(1, len(str(s).split()))


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 1 — masking drift
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("prompt,target", [
    ("problem: the axis is stale", "solution: refresh the source"),
    ("p", "t"),
    ("a much longer prompt with several words in it", "short"),
])
def test_the_nll_fn_equals_example_nll_exactly(model, prompt, target):
    """The callback handed to rank_metric must score the SAME quantity as the NLL
    secondary, or the two numbers cannot appear in one report."""
    fn = rr.make_nll_fn(model, Tok(), "cpu")
    assert fn(prompt, target) == example_nll(model, Tok(), prompt, target, "cpu")


def test_the_prompt_is_masked_and_only_the_candidate_is_scored(model):
    """Changing the PROMPT must change the score; that is the whole point. But
    two different prompts of the same length must not accidentally give identical
    values, which would mean the prompt is being ignored."""
    fn = rr.make_nll_fn(model, Tok(), "cpu")
    a = fn("problem: alpha", "solution: x")
    b = fn("problem: gamma", "solution: x")
    assert a != b, "the prompt is not reaching the score at all"


def test_a_longer_prompt_does_not_change_the_token_count_being_averaged(model):
    """Per-TOKEN NLL over the target only. If prompt tokens leaked into the
    denominator, padding the prompt would move the number toward zero."""
    tok = Tok()
    short = rr.make_nll_fn(model, tok, "cpu")("p", "same target here")
    long_ = rr.make_nll_fn(model, tok, "cpu")("p" * 40, "same target here")
    # Both are means over the SAME 16 target tokens, so they must be comparable
    # magnitudes — a leaked denominator would collapse one of them.
    assert 0.2 < short / long_ < 5.0, (short, long_)


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 2 — candidate batching
# ════════════════════════════════════════════════════════════════════════════

CANDS = ["short one", "a considerably longer candidate string here",
         "mid length candidate", "x", "another one entirely",
         "candidate six", "seven", "eighth candidate text", "nine", "ten ten"]


def test_batched_equals_unbatched_per_candidate(model):
    """THE PADDING TEST. Candidates differ in length, so every one of them is
    padded differently. Each must score exactly what it scores alone."""
    tok = Tok()
    batched = rr.batch_nll(model, tok, "problem: p", CANDS, "cpu")
    alone = [example_nll(model, tok, "problem: p", c, "cpu") for c in CANDS]
    assert len(batched) == len(alone) == 10
    for c, b, a in zip(CANDS, batched, alone):
        assert abs(b - a) < 1e-4, f"{c!r}: batched {b} vs alone {a}"


def test_the_longest_candidate_is_also_correct(model):
    """The unpadded row is the one a padding bug spares, so it must be checked
    explicitly rather than assumed covered by the loop above."""
    tok = Tok()
    longest = max(CANDS, key=len)
    i = CANDS.index(longest)
    batched = rr.batch_nll(model, tok, "problem: p", CANDS, "cpu")
    assert abs(batched[i] - example_nll(model, tok, "problem: p", longest, "cpu")) < 1e-4


def test_candidate_order_does_not_change_any_score(model):
    """A padding or position bug usually shows up as order dependence."""
    tok = Tok()
    fwd = rr.batch_nll(model, tok, "problem: p", CANDS, "cpu")
    rev = rr.batch_nll(model, tok, "problem: p", list(reversed(CANDS)), "cpu")
    for i, c in enumerate(CANDS):
        assert abs(fwd[i] - rev[len(CANDS) - 1 - i]) < 1e-4, c


def test_per_sequence_nll_is_not_the_batch_mean(model):
    """HF's out.loss averages over every unmasked label in the batch. If
    _per_sequence_nll returned that, all ten numbers would be identical — which
    would rank by nothing at all."""
    tok = Tok()
    vals = rr.batch_nll(model, tok, "problem: p", CANDS, "cpu")
    assert len(set(round(v, 6) for v in vals)) > 1, vals


def test_an_empty_candidate_is_refused_by_the_batcher(model):
    with pytest.raises(ValueError):
        rr.batch_nll(model, Tok(), "p", ["fine", ""], "cpu")


def test_the_default_is_unbatched_until_the_real_model_says_otherwise():
    """DEFAULT_BATCH stays 1 until the equality test passes on the quantised 3B,
    not on this CPU stub. Correctness first."""
    assert rr.DEFAULT_BATCH == 1


def test_candidate_nlls_reports_which_method_it_used(model):
    _, how = rr.candidate_nlls(model, Tok(), "p", CANDS, "cpu", batch=1)
    assert how == "unbatched"
    _, how = rr.candidate_nlls(model, Tok(), "p", CANDS, "cpu", batch=10)
    assert how == "batched"


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 3 — base and adapter must see identical candidate sets
# ════════════════════════════════════════════════════════════════════════════

def _rows(n=60):
    return [{"prompt": f"problem {i}", "target": f"solution number {i}",
             "record_kind": "sig01_plain"} for i in range(n)]


def test_the_candidate_sets_are_built_once_and_reused_by_both_passes():
    """The wiring-level assertion. Even with a correct seed, a runner that redrew
    per pass could reorder; build_items freezes them before either pass runs."""
    rows = _rows()
    pool = rm.build_pool(rows, wordlen)
    items, _ = rr.build_items(rows, pool, wordlen)
    base_pass = [it["candidates"] for it in items]
    adapter_pass = [it["candidates"] for it in items]
    assert base_pass == adapter_pass
    assert all(a is b for a, b in zip(base_pass, adapter_pass)), "not the same object"


def test_rebuilding_from_scratch_reproduces_the_same_sets():
    """And if someone does rebuild — a resume, a second process — the sha256 seed
    must give the identical draw."""
    rows = _rows()
    pool = rm.build_pool(rows, wordlen)
    a, _ = rr.build_items(rows, pool, wordlen)
    b, _ = rr.build_items(rows, pool, wordlen)
    assert [x["candidates"] for x in a] == [x["candidates"] for x in b]


def test_the_true_target_is_candidate_zero(model):
    """Scored first, so a stateful model or a KV-cache bug cannot be primed by
    nine distractors before it sees the real answer."""
    seen = []
    rr.score_one(lambda p, t: seen.append(t) or 1.0, None, "p", "TRUE", ["d1", "d2"])
    assert seen[0] == "TRUE"


def test_score_one_marks_a_hit_only_when_the_true_target_is_strictly_lowest(model):
    lows = {"TRUE": 0.5, "d1": 1.0, "d2": 2.0}
    assert rr.score_one(lambda p, t: lows[t], None, "p", "TRUE", ["d1", "d2"])["hit"] == 1
    ties = {"TRUE": 1.0, "d1": 1.0, "d2": 2.0}
    assert rr.score_one(lambda p, t: ties[t], None, "p", "TRUE", ["d1", "d2"])["hit"] == 0


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 4 — OOM falls back to unbatched, never to a shorter sequence
# ════════════════════════════════════════════════════════════════════════════

def test_oom_falls_back_to_unbatched_and_says_so(model, monkeypatch):
    def boom(*a, **k):
        raise torch.cuda.OutOfMemoryError("simulated")
    monkeypatch.setattr(rr, "batch_nll", boom)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    nlls, how = rr.candidate_nlls(model, Tok(), "p", CANDS, "cpu", batch=10)
    assert how == "oom_fallback"
    assert len(nlls) == 10


def test_the_oom_fallback_returns_the_SAME_numbers_as_the_batched_path(model, monkeypatch):
    """A fallback that scored differently would make a run's results depend on
    whether memory happened to be free — irreproducible by construction."""
    tok = Tok()
    good = rr.batch_nll(model, tok, "problem: p", CANDS, "cpu")
    monkeypatch.setattr(rr, "batch_nll",
                        lambda *a, **k: (_ for _ in ()).throw(torch.cuda.OutOfMemoryError("x")))
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)
    fell_back, how = rr.candidate_nlls(model, tok, "problem: p", CANDS, "cpu", batch=10)
    assert how == "oom_fallback"
    for g, f in zip(good, fell_back):
        assert abs(g - f) < 1e-4


def test_nothing_in_the_module_truncates_a_sequence_to_fit():
    """Structural. Shortening to survive OOM would change what is scored and do it
    silently — the defect class this whole night has been about."""
    src = (REPO / "training" / "rank_runner.py").read_text(encoding="utf-8")
    body = src.split("def candidate_nlls", 1)[1].split("def score_one", 1)[0]
    for bad in ("[:max_len]", "truncation=True", "max_length="):
        assert bad not in body, f"the OOM path truncates: {bad}"


# ════════════════════════════════════════════════════════════════════════════
# The estimate must be computed, not typed into the report by hand
# ════════════════════════════════════════════════════════════════════════════

def test_forward_pass_count_is_computed_from_the_real_shape():
    assert rr.forward_passes(216) == 216 * 10 * 2
    assert rr.forward_passes(246) == 4920
    assert rr.forward_passes(246, passes=1) == 2460


def test_unscorable_items_are_reported_not_dropped():
    rows = _rows(40) + [{"prompt": "", "target": "x", "record_kind": "k"},
                        {"prompt": "p", "target": "   ", "record_kind": "k"}]
    pool = rm.build_pool(rows, wordlen)
    items, unscorable = rr.build_items(rows, pool, wordlen)
    assert len(items) == 40
    assert [u[1] for u in unscorable] == ["blank", "blank"]


# ════════════════════════════════════════════════════════════════════════════
# THE COST KNOBS — pre-registered, and unreachable from any result
# ════════════════════════════════════════════════════════════════════════════

def _body_of(fn) -> str:
    """Source with the docstring removed.

    The first version of these two tests scanned the WHOLE source and failed on
    the docstring, which says "it cannot see an accuracy" and "max_len is never
    shortened" — the function explaining its own guarantee tripped the test for
    that guarantee. Prose is not a code path; only the body is scanned.
    """
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    node = tree.body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)):
        node.body = node.body[1:]
    return ast.unparse(node)


def test_bit_identical_and_fitting_keeps_K9_and_batches():
    d = rr.decide_knobs({"max_abs_diff": 0.0, "fits": True, "batch": 10})
    assert (d["k"], d["chance"], d["batch"]) == (9, 0.1, 10)


@pytest.mark.parametrize("diff", [1e-9, 3e-7, 1e-4, 0.5])
def test_anything_short_of_bit_identical_drops_to_K4(diff):
    """'Not merely close.' A 1e-9 disagreement is still a disagreement, and the
    rule was fixed before anyone knew which branch it would take."""
    d = rr.decide_knobs({"max_abs_diff": diff, "fits": True, "batch": 10})
    assert (d["k"], d["chance"], d["batch"]) == (4, 0.2, 1)
    assert "not bit-identical" in d["why"]


def test_a_batch_that_does_not_fit_drops_to_K4_and_says_so():
    d = rr.decide_knobs({"max_abs_diff": 0.0, "fits": False, "batch": 10})
    assert d["k"] == 4 and d["batch"] == 1
    assert "did not fit" in d["why"]


def test_a_missing_probe_field_is_never_read_as_success():
    """Fail toward the cheaper, safer branch. An absent measurement is not a
    passed one — the same rule the notary learned on 17 August."""
    for probe in ({}, {"fits": True}, {"max_abs_diff": 0.0}, {"batch": 10}):
        assert rr.decide_knobs(probe)["k"] == 4, probe


def test_decide_knobs_CANNOT_SEE_AN_ACCURACY():
    """THE STRUCTURAL GUARANTEE the rule asked for: impossible, not discouraged.

    There is no parameter through which a result could reach this function, and
    its body never names one. If someone later threads an accuracy in to 'just
    check', this fails.
    """
    import inspect
    body = _body_of(rr.decide_knobs)
    # Whole identifiers, not substrings: 'identical' contains 'ci' and would
    # make this fire on text that is not a result at all.
    words = set(re.findall("[A-Za-z_]+", body.lower()))
    for word in ("accuracy", "acc", "hits", "hit", "verdict", "ci", "delta"):
        assert word not in words, (
            "decide_knobs BODY mentions " + repr(word)
            + " - K could be tuned on a result. Body: " + body)
    params = list(inspect.signature(rr.decide_knobs).parameters)
    assert params == ["probe"], params


def test_max_len_is_not_a_knob_anywhere_in_the_decision():
    """Rule 3 is not a branch. Shortening sequences to buy speed must not be
    expressible, so there is no code path that could choose it."""
    body = _body_of(rr.decide_knobs)
    assert "max_len" not in body and "max_length" not in body, body


def test_the_chance_level_follows_K_so_a_verdict_cannot_use_the_wrong_baseline():
    """A K=4 run graded against 0.10 would call a chance-level adapter ABOVE
    CHANCE. That is the mistake the k argument exists to prevent."""
    at_chance_k4 = [1] * 40 + [0] * 160        # 0.20 exactly
    assert rm.rank_verdict(at_chance_k4, k=4)[0] == "AT CHANCE"
    assert rm.rank_verdict(at_chance_k4, k=9)[0] == "ABOVE CHANCE"
