# -*- coding: utf-8 -*-
"""test/test_engine_probe_realistic.py — the realistic obs/8 probe and the arity-8 ceiling
(Perplexity round 81B В6 and round 81C В4, 8 Oct 2026, under Emil R73).

Decided: for every form within an arity, a separate probe with the form's real content; the
ceiling of the arity is the MINIMUM over its forms of the largest wholly clean size. For obs/8
the real content repeats constant columns (subcategory, key, period, unit, source), the shape
that panicked at 341 atoms and was clean at 340 on 3 Oct (claude/reports/GUARD_2026-10-03.md),
while the all-distinct ladder of 4 Oct was clean at 390. The engine is injected here; the live
run is the probe itself on the machine (test_live_* below, marker live_state).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
import engine_probe as EP  # noqa: E402
from core import space as sp  # noqa: E402


def _runner(fail_at=(), wrong_at=()):
    calls = []

    def run(total, rep):
        calls.append(total)
        if total in fail_at:
            return "PANIC", 3.0
        if total in wrong_at:
            return "WRONG", 0.2
        return "CLEAN", 0.2
    run.calls = calls
    return run


# ── the family: the real obs/8 content ──────────────────────────────────────
def test_the_realistic_family_has_the_requested_total_and_the_obs_8_shape():
    atoms, query, want = EP.realistic_family(341)
    assert len(atoms) == 341, "size is the TOTAL number of obs/8 atoms in the space, extra included"
    assert all(sp.shape_counts(a) == {"obs/8": 1} for a in atoms)
    assert len(want) == 2 and want == sorted(['(hit "P7" "v7")', '(hit "P107" "v507")'])
    assert query.startswith('!(match &self (obs "k7" ')


def test_the_realistic_family_repeats_the_constant_columns_of_the_real_obs_8():
    atoms, _, _ = EP.realistic_family(50)
    cols = list(zip(*[sp.parse(a) for a in atoms]))
    # (obs id subcategory key place period value unit source): columns 2, 3, 5, 7, 8 are constant
    for idx, const in ((2, "C0"), (3, "key"), (5, "2023"), (7, "u"), (8, "src")):
        assert set(cols[idx]) == {const}, f"column {idx} must repeat the constant {const!r}"
    # and columns 1, 4, 6 vary (the id, the place, the value)
    for idx in (1, 4, 6):
        assert len(set(cols[idx])) > 1, f"column {idx} must vary"
    assert EP.REALISTIC_CONSTANTS == ("C0", "key", "2023", "u", "src")


def test_the_realistic_family_differs_from_the_all_distinct_ladder_family():
    real, _, _ = EP.realistic_family(10)
    ladder, _, _ = EP.family(8, "obs", 9)
    real_cols = list(zip(*[sp.parse(a) for a in real]))
    ladder_cols = list(zip(*[sp.parse(a) for a in ladder]))
    assert len(set(real_cols[2])) == 1 and len(set(ladder_cols[2])) == len(ladder), \
        "the ladder of 4 Oct varies every column; the realistic form repeats them"


# ── the probe: largest wholly clean size among the probed totals ────────────
def test_a_panic_at_341_and_390_gives_340():
    r = EP.probe_realistic(runner=_runner(fail_at={341, 390}))
    assert r["budget"] == 340 and r["sizes_tried"] == [300, 340, 341, 390]
    assert len(r["runs"]) == 12 and r["form"].startswith("obs/8 realistic")


def test_all_clean_gives_390():
    assert EP.probe_realistic(runner=_runner())["budget"] == 390


def test_a_panic_at_340_gives_300():
    assert EP.probe_realistic(runner=_runner(fail_at={340, 341, 390}))["budget"] == 300


def test_a_panic_everywhere_forbids():
    assert EP.probe_realistic(runner=_runner(fail_at={300, 340, 341, 390}))["budget"] == "forbidden"


def test_a_wrong_answer_fails_the_size_like_a_panic():
    assert EP.probe_realistic(runner=_runner(wrong_at={341, 390}))["budget"] == 340


def test_one_bad_repetition_fails_the_size():
    seq = iter(["CLEAN"] * 3 + ["CLEAN", "PANIC", "CLEAN"] + ["PANIC"] * 6)
    r = EP.probe_realistic(runner=lambda total, rep: (next(seq), 0.1))
    assert r["budget"] == 300, "340 had one panic in three: not wholly clean"


def test_every_size_is_probed_even_after_a_failure():
    run = _runner(fail_at={340})
    EP.probe_realistic(runner=run)
    assert sorted(set(run.calls)) == [300, 340, 341, 390], "no early stop: 341 and 390 are measured too"


# ── the ceiling: minimum over the forms of the arity ────────────────────────
def test_the_ladder_budget_is_read_from_clean_sizes_or_budget():
    assert EP.ladder_budget({"clean_sizes": [100, 250, 390]}) == 390
    assert EP.ladder_budget({"budget": 300, "clean_sizes": [100, 250]}) == 300
    assert EP.ladder_budget({}) == "forbidden"


def test_the_ceiling_of_arity_8_is_the_minimum_over_its_forms():
    assert EP.ceiling_for_arity8(390, 340) == 340
    assert EP.ceiling_for_arity8(390, 390) == 390
    assert EP.ceiling_for_arity8(250, 340) == 250
    assert EP.ceiling_for_arity8(390, "forbidden") == 0
    assert EP.ceiling_for_arity8("forbidden", 340) == 0


def test_write_realistic_sets_the_budget_of_arity_8_and_keeps_the_ladder_record(tmp_path):
    cfg = tmp_path / "engine_guard.json"
    cfg.write_text(sp.GUARD_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    before = json.loads(cfg.read_text(encoding="utf-8"))
    rec = EP.probe_realistic(runner=_runner(fail_at={341, 390}))
    EP.write_realistic(rec, path=cfg)
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["budgets"]["8"] == 340
    kept = {k: v for k, v in after["probed"]["8"].items() if k != "realistic"}
    ladder_before = {k: v for k, v in before["probed"]["8"].items() if k != "realistic"}
    assert kept == ladder_before, "the 4 Oct ladder record stays as it was"
    assert EP.ladder_budget(before["probed"]["8"]) == 390, "the ladder of 4 Oct: clean_sizes up to 390"
    assert after["probed"]["8"]["realistic"]["budget"] == 340
    assert after["probed"]["8"]["realistic"]["reason"].startswith("Perplexity round 81B")
    assert "341" in after["_budgets_why"]["8"] and "340" in after["_budgets_why"]["8"]
    for a in map(str, range(1, 8)):
        assert after["budgets"][a] == before["budgets"][a], f"arity {a} untouched"
    loaded = sp.guard_config(cfg)
    assert loaded["budgets"][8] == 340
    assert sp.preflight({"obs/8": 77}, loaded) == []
    assert [r["cause"] for r in sp.preflight({"obs/8": 340}, loaded)] == ["ENGINE_BUDGET"]


def test_write_realistic_with_a_forbidden_form_sets_budget_zero(tmp_path):
    cfg = tmp_path / "engine_guard.json"
    cfg.write_text(sp.GUARD_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    EP.write_realistic(EP.probe_realistic(runner=_runner(fail_at={300, 340, 341, 390})), path=cfg)
    assert json.loads(cfg.read_text(encoding="utf-8"))["budgets"]["8"] == 0


def test_a_missing_sidecar_raises_instead_of_counting_as_a_panic(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "SIDECAR_PY", tmp_path / "absent.exe")
    with pytest.raises(sp.SpaceEngineFailed):
        EP.run_realistic_case(10, 1)
    assert EP.main(["--realistic"]) == 2, "the CLI stops without the engine and writes nothing"


# ── the live measurement on the machine (deselected from the gating suite) ──
@pytest.mark.live_state
def test_live_340_realistic_obs_8_atoms_are_clean_and_341_panic():
    assert sp.SIDECAR_PY.exists(), "venv312_metta is the engine; no sidecar, no measurement"
    assert EP.run_realistic_case(340, 1)[0] == "CLEAN"
    assert EP.run_realistic_case(341, 1)[0] == "PANIC"


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_probe_that_took_the_maximum_would_give_390_for_arity_8():
    assert EP.ceiling_for_arity8(390, 340) != max(390, 340)


def test_mutation_counting_one_clean_rep_as_a_clean_size_would_give_340_here():
    seq = iter(["CLEAN"] * 3 + ["CLEAN", "PANIC", "CLEAN"] + ["PANIC"] * 6)
    r = EP.probe_realistic(runner=lambda total, rep: (next(seq), 0.1))
    assert r["budget"] != 340
