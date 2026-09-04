# -*- coding: utf-8 -*-
"""
training/eval_adapter.py — the harness, verified before any number it produces is
read as a verdict.

WHY (5 September 2026, 02:30)
-----------------------------
eval_adapter.py was written before train_lora.py, so the criterion could not be
chosen after seeing the result. That is the right order. But the harness itself
was never tested, and an untested harness does not produce evidence — it
produces a number with a confident format.

The load-bearing claim is one line:

    with model.disable_adapter():
        base = example_nll(...)
    adapted = example_nll(...)

**If `disable_adapter()` leaks, `base` and `adapted` are the same model and every
delta in every table is noise around zero.** A leak would look exactly like the
honest "NO EFFECT" the design hopes to be able to report — the most dangerous
failure available, because it is indistinguishable from success at reporting
failure. Test 1 exists for that one line.

WHERE THIS RUNS — and where it does NOT
---------------------------------------
`training/eval_adapter.py` imports torch and transformers at module level. The
main suite runs under `venv/`, which has numpy but **no torch, peft or
transformers** — the training stack was deliberately installed in `venv_train/`
only. So this whole file SKIPS under the suite and is INERT there.

    venv_train\\Scripts\\python.exe -m pytest test/test_eval_harness.py -v

is the only invocation that executes it. Said out loud here rather than left to
be discovered, because a test that silently does not run is worse than one that
does not exist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

torch = pytest.importorskip("torch", reason="training stack lives in venv_train only")
pytest.importorskip("transformers", reason="training stack lives in venv_train only")
pytest.importorskip("peft", reason="training stack lives in venv_train only")

import training.eval_adapter as ea            # noqa: E402


# ── a tokenizer that needs no files, no network and no vocabulary ────────────

class Tok:
    """Deterministic byte-ish tokenizer. example_nll only needs input_ids."""

    def __call__(self, text, add_special_tokens=True):
        return {"input_ids": [(ord(c) % 50) + 1 for c in str(text)] or [1]}


# ════════════════════════════════════════════════════════════════════════════
# 1. disable_adapter() REALLY DISABLES
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def tiny():
    """A 1-layer GPT-2 built from config — no download — plus a LoRA whose B
    matrices are deliberately NON-ZERO.

    peft initialises lora_B to zeros, which makes a fresh adapter a mathematical
    identity. A test using the default weights would pass whether or not
    disable_adapter() works, and would prove nothing at all.
    """
    from transformers import GPT2Config, GPT2LMHeadModel
    from peft import LoraConfig, get_peft_model

    cfg = GPT2Config(vocab_size=64, n_positions=32, n_embd=16, n_layer=1, n_head=1)
    torch.manual_seed(20260905)
    base = GPT2LMHeadModel(cfg).eval()
    pristine = {k: v.clone() for k, v in base.state_dict().items()}   # BEFORE wrapping

    peft_model = get_peft_model(
        base, LoraConfig(r=2, lora_alpha=4, lora_dropout=0.0,
                         target_modules=["c_attn"], task_type="CAUSAL_LM"))
    touched = 0
    for name, p in peft_model.named_parameters():
        if "lora_B" in name:
            torch.nn.init.normal_(p, mean=0.0, std=0.5)
            touched += 1
    assert touched > 0, "no lora_B found — the adapter would be an identity"
    peft_model.eval()

    fresh = GPT2LMHeadModel(cfg).eval()
    fresh.load_state_dict(pristine)
    return peft_model, fresh, Tok()


def test_the_adapter_changes_the_number_at_all(tiny):
    """Precondition for everything else. If the adapter is inert, tests 1b/1c are
    vacuous and so is the whole eval."""
    model, _fresh, tok = tiny
    adapted = ea.example_nll(model, tok, "problem: x", "solution: y", "cpu")
    with model.disable_adapter():
        base = ea.example_nll(model, tok, "problem: x", "solution: y", "cpu")
    assert abs(base - adapted) > 1e-6, (
        f"base={base} adapted={adapted} — disable_adapter() made no difference "
        f"with a deliberately non-zero adapter. THE ADAPTER IS LEAKING and every "
        f"delta in every eval table is noise around zero.")


def test_disabled_equals_a_model_with_no_adapter_at_all(tiny):
    """Not merely 'different' — the disabled path must equal the TRUE base. A
    partial disable (some layers restored, some not) would pass the test above
    and still corrupt every base NLL."""
    model, fresh, tok = tiny
    with model.disable_adapter():
        disabled = ea.example_nll(model, tok, "problem: x", "solution: y", "cpu")
    pure = ea.example_nll(fresh, tok, "problem: x", "solution: y", "cpu")
    assert abs(disabled - pure) < 1e-5, (
        f"disabled={disabled} vs never-adapted={pure} — disable_adapter() does "
        f"not restore the base model. Every 'base NLL' column is wrong.")


def test_the_adapter_comes_back_after_the_context_exits(tiny):
    """The context manager must be symmetric. If it did not restore, every
    example after the first would be measured base-vs-base."""
    model, _fresh, tok = tiny
    before = ea.example_nll(model, tok, "problem: x", "solution: y", "cpu")
    with model.disable_adapter():
        pass
    after = ea.example_nll(model, tok, "problem: x", "solution: y", "cpu")
    assert abs(before - after) < 1e-6, (
        "the adapter did not come back after disable_adapter() exited")


# ════════════════════════════════════════════════════════════════════════════
# 2. SEEN / UNSEEN classification
# ════════════════════════════════════════════════════════════════════════════

def test_trailing_whitespace_still_counts_as_SEEN():
    """norm() collapses whitespace, so a target that differs only by spacing is
    correctly recognised as one the adapter has already seen."""
    train = {ea.norm("proposal: raise the sampling rate")}
    assert ea.norm("proposal: raise the sampling rate   ") in train
    assert ea.norm("proposal:  raise   the sampling rate\n") in train


def test_a_single_full_stop_makes_a_SEEN_target_read_as_UNSEEN():
    """THE WEAKNESS, ASSERTED AS IT IS, not as it should be.

    norm() is `" ".join(text.split())` — whitespace only. It does not touch
    punctuation or case. So a memorised training target with a full stop appended
    is classified UNSEEN and is graded in the bucket that IS the verdict.

    This test documents the actual behaviour so it cannot change unnoticed. It is
    a finding about the harness, not a passing feature: memorisation can leak into
    the UNSEEN row through punctuation alone.
    """
    train = {ea.norm("proposal: raise the sampling rate")}
    leaked = "proposal: raise the sampling rate."
    assert ea.norm(leaked) not in train, (
        "norm() now handles punctuation — good, but the eval reports and this "
        "test must be updated together")


def test_case_also_leaks_for_the_same_reason():
    train = {ea.norm("proposal: raise the sampling rate")}
    assert ea.norm("Proposal: raise the sampling rate") not in train


# ════════════════════════════════════════════════════════════════════════════
# 3. paired_bootstrap / verdict_for — the boundary, exactly
# ════════════════════════════════════════════════════════════════════════════

def test_constant_positive_deltas_are_IMPROVED():
    v, ci = ea.verdict_for(np.full(40, 0.25))
    assert v == "IMPROVED", (v, ci)


def test_constant_negative_deltas_are_WORSE():
    v, ci = ea.verdict_for(np.full(40, -0.25))
    assert v == "WORSE", (v, ci)


def test_symmetric_noise_is_NO_EFFECT():
    """Mean exactly zero, so the 95% CI must straddle it."""
    deltas = np.array([0.5, -0.5] * 20)
    v, ci = ea.verdict_for(deltas)
    assert v == "NO EFFECT", (v, ci)


def test_n_29_is_UNRESOLVABLE_and_n_30_is_graded():
    """The pre-registered boundary, checked on both sides with the SAME data, so
    only n differs."""
    assert ea.MIN_HOLDOUT == 30
    v29, ci29 = ea.verdict_for(np.full(29, 0.25))
    v30, _ = ea.verdict_for(np.full(30, 0.25))
    assert v29 == "UNRESOLVABLE (n<30)", v29
    assert ci29 == "-", "an UNRESOLVABLE bucket must not report a CI"
    assert v30 == "IMPROVED", v30


def test_the_bootstrap_is_deterministic():
    """Same deltas, same seed, same CI — otherwise a verdict near the boundary
    changes between runs and nothing is reproducible."""
    d = np.random.default_rng(7).normal(0.05, 1.0, 200)
    assert ea.paired_bootstrap(d, 2000, ea.SEED) == ea.paired_bootstrap(d, 2000, ea.SEED)


# ════════════════════════════════════════════════════════════════════════════
# 4. Stratum refusal names the file and the index
# ════════════════════════════════════════════════════════════════════════════

def test_a_record_with_no_record_kind_raises_naming_file_and_index():
    p = Path("cortex_memory/training/holdout.jsonl")
    with pytest.raises(SystemExit) as exc:
        ea.resolve_stratum({"prompt": "p", "target": "t"}, p, 17)
    msg = str(exc.value)
    assert "holdout.jsonl" in msg and "17" in msg, msg
    assert "record_kind" in msg, msg
    assert "prompt" in msg and "target" in msg, "the observed keys must be shown"


def test_an_empty_record_kind_is_refused_too():
    with pytest.raises(SystemExit) as exc:
        ea.resolve_stratum({"record_kind": "   "}, Path("h.jsonl"), 3)
    assert "empty" in str(exc.value)


def test_a_present_record_kind_is_returned_unchanged():
    assert ea.resolve_stratum({"record_kind": "sig3_x"}, Path("h.jsonl"), 1) == "sig3_x"


# ════════════════════════════════════════════════════════════════════════════
# 5. An empty target never reaches the model
# ════════════════════════════════════════════════════════════════════════════

def test_example_nll_refuses_an_empty_target(tiny):
    model, _fresh, tok = tiny

    class NoTokens(Tok):
        def __call__(self, text, add_special_tokens=True):
            return {"input_ids": [] if not str(text).strip() else [1, 2, 3]}

    with pytest.raises(ValueError) as exc:
        ea.example_nll(model, NoTokens(), "problem: x", "", "cpu")
    assert "empty target" in str(exc.value)


@pytest.mark.parametrize("target", ["", "   ", "\n", "\t "])
def test_main_skips_blank_targets_before_the_model_is_touched(target, monkeypatch, tmp_path):
    """The second layer. main() filters on `not str(target).strip()`, so a blank
    target is counted as skipped and never becomes a bucket entry."""
    calls = []
    monkeypatch.setattr(ea, "example_nll",
                        lambda *a, **k: calls.append(a) or 1.0)
    rec = _run_main(monkeypatch, tmp_path,
                    holdout=[{"prompt": "p", "target": target, "record_kind": "k"}],
                    train=[{"target": "other"}])
    assert calls == [], f"a blank target reached example_nll: {calls}"
    assert "skipped (empty or too long): 1" in rec["report"]


# ════════════════════════════════════════════════════════════════════════════
# 6. Exit codes
# ════════════════════════════════════════════════════════════════════════════

def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    import json
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                    encoding="utf-8")
    return path


class _StubModel:
    """Stands in for the 4-bit PeftModel. Records whether the adapter is on, so a
    stubbed example_nll can return a different number for base and adapted."""

    def __init__(self):
        self.adapter_on = True

    def eval(self):
        return self

    def disable_adapter(self):
        model = self

        class _Ctx:
            def __enter__(self_inner):
                model.adapter_on = False

            def __exit__(self_inner, *a):
                model.adapter_on = True
                return False
        return _Ctx()


def _run_main(monkeypatch, tmp_path, holdout, train, adapter_exists=True,
              delta=0.0, argv_extra=()):
    """Runs main() with every GPU-touching part stubbed. Returns the exit code
    and the written report."""
    import json

    h = _write_jsonl(tmp_path / "holdout.jsonl", holdout)
    t = _write_jsonl(tmp_path / "train.jsonl", train)
    adir = tmp_path / "adapter"
    if adapter_exists:
        adir.mkdir()
        (adir / "adapter_provenance.json").write_text(
            json.dumps({"corpus_sha256": "abc", "n_train": len(train)}), encoding="utf-8")
    report = tmp_path / "report.md"

    stub = _StubModel()
    monkeypatch.setattr(ea.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(ea.AutoTokenizer, "from_pretrained",
                        staticmethod(lambda *a, **k: Tok()))
    monkeypatch.setattr(ea.AutoModelForCausalLM, "from_pretrained",
                        staticmethod(lambda *a, **k: stub))
    import peft
    monkeypatch.setattr(peft.PeftModel, "from_pretrained",
                        staticmethod(lambda m, *a, **k: stub))
    if not hasattr(ea.example_nll, "_patched_by_caller"):
        monkeypatch.setattr(
            ea, "example_nll",
            lambda model, tok, p, tgt, dev: 1.0 if not model.adapter_on else 1.0 - delta)

    monkeypatch.setattr(sys, "argv", [
        "eval_adapter.py", "--holdout", str(h), "--train", str(t),
        "--adapter", str(adir), "--report", str(report), *argv_extra])
    code = ea.main()
    return {"code": code,
            "report": report.read_text(encoding="utf-8") if report.exists() else ""}


def _corpus(n, kind="sig3_x", novel=True):
    return [{"prompt": f"problem {i}", "target": f"solution {i}" if novel else "shared",
             "record_kind": kind} for i in range(n)]


def test_exit_2_when_the_holdout_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", [
        "eval_adapter.py", "--holdout", str(tmp_path / "nope.jsonl"),
        "--train", str(tmp_path / "also_nope.jsonl")])
    assert ea.main() == 2
    assert "REFUSED" in capsys.readouterr().out


def test_exit_2_when_the_train_split_is_missing(monkeypatch, tmp_path, capsys):
    h = _write_jsonl(tmp_path / "holdout.jsonl", _corpus(3))
    monkeypatch.setattr(sys, "argv", [
        "eval_adapter.py", "--holdout", str(h), "--train", str(tmp_path / "nope.jsonl")])
    assert ea.main() == 2
    assert "SEEN vs UNSEEN cannot be determined" in capsys.readouterr().out


def test_exit_2_when_the_holdout_is_empty(monkeypatch, tmp_path, capsys):
    h = _write_jsonl(tmp_path / "holdout.jsonl", [])
    t = _write_jsonl(tmp_path / "train.jsonl", [{"target": "x"}])
    monkeypatch.setattr(sys, "argv",
                        ["eval_adapter.py", "--holdout", str(h), "--train", str(t)])
    assert ea.main() == 2
    assert "holdout is empty" in capsys.readouterr().out


def test_exit_2_when_the_adapter_is_missing(monkeypatch, tmp_path, capsys):
    rec = _run_main(monkeypatch, tmp_path, holdout=_corpus(3),
                    train=[{"target": "z"}], adapter_exists=False)
    assert rec["code"] == 2
    assert "no adapter at" in capsys.readouterr().out


def test_exit_0_only_when_an_UNSEEN_stratum_IMPROVED(monkeypatch, tmp_path):
    rec = _run_main(monkeypatch, tmp_path, holdout=_corpus(40),
                    train=[{"target": "unrelated"}], delta=0.30)
    assert "IMPROVED" in rec["report"]
    assert rec["code"] == 0


def test_exit_1_when_the_adapter_did_nothing(monkeypatch, tmp_path):
    rec = _run_main(monkeypatch, tmp_path, holdout=_corpus(40),
                    train=[{"target": "unrelated"}], delta=0.0)
    assert "NO EFFECT" in rec["report"]
    assert rec["code"] == 1


def test_exit_1_when_the_adapter_made_it_WORSE(monkeypatch, tmp_path):
    rec = _run_main(monkeypatch, tmp_path, holdout=_corpus(40),
                    train=[{"target": "unrelated"}], delta=-0.30)
    assert "WORSE" in rec["report"]
    assert rec["code"] == 1


def test_exit_1_when_the_UNSEEN_bucket_is_too_small_to_grade(monkeypatch, tmp_path):
    """UNRESOLVABLE must NOT be reported as success, however large the delta."""
    rec = _run_main(monkeypatch, tmp_path, holdout=_corpus(29),
                    train=[{"target": "unrelated"}], delta=0.90)
    assert "UNRESOLVABLE" in rec["report"]
    assert rec["code"] == 1


def test_improvement_on_SEEN_alone_does_not_earn_exit_0(monkeypatch, tmp_path):
    """THE MEMORISATION TRAP, as an exit code. Every target is already in train,
    so the gain lands entirely in the SEEN table and the UNSEEN table is empty.
    A pure memoriser must not be able to return 0."""
    rows = _corpus(40, novel=False)
    rec = _run_main(monkeypatch, tmp_path, holdout=rows,
                    train=[{"target": "shared"}], delta=0.30)
    assert "IMPROVED" in rec["report"], "the SEEN table should show the memorisation"
    unseen = rec["report"].split("## SEEN")[0]
    assert "NO DATA" in unseen, "the UNSEEN table should be empty here"
    assert rec["code"] == 1, "memorisation alone returned success"
