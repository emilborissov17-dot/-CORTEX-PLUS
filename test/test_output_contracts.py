# -*- coding: utf-8 -*-
"""test/test_output_contracts.py — договорите хапят ли. (12 Sep 2026)

Всеки тест тук подава НАРОЧНО счупен изход и иска договорът да падне. Договор,
който не пада на счупен вход, е декорация — и по-лошо от липсващ, защото зеленият
му ред чете като „проверено".

Двата случая от 12 септември са фиксирани като тестове с истинските стойности, за
да не могат да се върнат тихо: буквата "c" като закон, и -20.84 земетресения.

Всеки тест пише САМО в tmp_path. Никой не пипа memory/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import output_contracts as oc  # noqa: E402


def _w(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _tier(p: Path, indicator: str, values: list, start: int = 1) -> Path:
    p.write_text("\n".join(json.dumps(
        {"date": f"2026-08-{start + i:02d}", "indicator": indicator, "value": v})
        for i, v in enumerate(values)), encoding="utf-8")
    return p


# ── канонът ──────────────────────────────────────────────────────────────────

def test_a_single_letter_cannot_become_law(tmp_path):
    """Точният файл, който на 11 Sep влезе в подсказката на мозъка."""
    p = _w(tmp_path / "c.json", {"invariants": [
        {"lesson": "c", "evidence": "carried forward by 3 consecutive cycle reviews (c1..c1)",
         "source": "cycle_review×3"}]})
    bad = oc.canon_invariants(p)
    whys = " ".join(b["why"] for b in bad)
    assert "too short to be law" in whys
    assert "test-fixture cycle ids" in whys, "фикстурният подпис (c1..c1) трябва да се вижда отделно"


def test_a_real_lesson_passes(tmp_path):
    p = _w(tmp_path / "c.json", {"invariants": [
        {"lesson": "resolve NOAA anchor conflicts before defining new levels",
         "evidence": "carried forward by 3 consecutive cycle reviews "
                     "(2026-09-10T03:00:00+03:00..2026-09-12T03:04:02+03:00)"}]})
    assert oc.canon_invariants(p) == []


def test_a_two_word_lesson_is_refused_and_the_boundary_is_pinned(tmp_path):
    """Прагът се фиксира и от двете страни, иначе следващият, който го пипне,
    няма да разбере че го е разхлабил."""
    assert oc.MIN_LESSON_WORDS == 3 and oc.MIN_LESSON_CHARS == 20
    short = _w(tmp_path / "s.json", {"invariants": [{"lesson": "keep anchors steady now"}]})  # 4 думи, 23 знака
    assert oc.canon_invariants(short) == []
    two = _w(tmp_path / "t.json", {"invariants": [{"lesson": "keep the anchorssssssssss"}]})  # 3 думи, но..
    assert oc.canon_invariants(two) == [], "3 думи и >=20 знака минава"
    tiny = _w(tmp_path / "u.json", {"invariants": [{"lesson": "keep it"}]})
    assert oc.canon_invariants(tiny), "2 думи трябва да падне"


def test_a_missing_canon_file_is_a_violation_not_a_pass(tmp_path):
    """„Нямам данни" никога не бива да чете като „всичко е добре"."""
    bad = oc.canon_invariants(tmp_path / "nope.json")
    assert bad and "MISSING" in bad[0]["why"]


# ── опашката на консолидацията ───────────────────────────────────────────────

def test_a_count_predicted_below_zero_is_refused(tmp_path):
    """Истинската хипотеза от 12 Sep: quakes.quake_m45_count -> -20.84."""
    tier = _tier(tmp_path / "t.jsonl", "quakes.quake_m45_count",
                 [21, 23, 20, 22, 14, 14, 36, 56, 33, 41, 32, 31, 31, 29, 22, 17, 22, 17, 25, 22])
    q = _w(tmp_path / "q.json", {"hypotheses": [
        {"metric": "quakes.quake_m45_count", "predicted": -20.84, "lo": -35.67, "hi": -6.01}]})
    bad = oc.consolidation_queue(q, tier)
    whys = " ".join(b["why"] for b in bad)
    assert "cannot go below zero" in whys


def test_a_prediction_inside_the_record_passes(tmp_path):
    tier = _tier(tmp_path / "t.jsonl", "quakes.quake_m45_count",
                 [21, 23, 20, 22, 14, 14, 36, 56, 33, 41, 32, 31, 31, 29, 22, 17, 22, 17, 25, 22])
    q = _w(tmp_path / "q.json", {"hypotheses": [
        {"metric": "quakes.quake_m45_count", "predicted": 18.0, "lo": 8.0, "hi": 28.0}]})
    assert [b for b in oc.consolidation_queue(q, tier) if b.get("severity") != "note"] == []


def test_a_prediction_outside_its_own_interval_is_refused(tmp_path):
    """Независима от домейна: числото трябва поне да е в интервала, който само обявява."""
    tier = _tier(tmp_path / "t.jsonl", "x.y", list(range(10, 40)))
    q = _w(tmp_path / "q.json", {"hypotheses": [
        {"metric": "x.y", "predicted": 99.0, "lo": 10.0, "hi": 30.0}]})
    whys = " ".join(b["why"] for b in oc.consolidation_queue(q, tier))
    assert "outside its own interval" in whys


def test_a_short_record_is_recorded_as_unjudged_not_as_a_violation(tmp_path):
    """Лъжливият сигнал, който хванах в първата версия: co2_annual_increase има
    една точка в дневния слой, значи всяко число е „извън записа". Договор, който
    вика напразно, бива изключен — затова тук се БРОИ, а не се съди."""
    tier = _tier(tmp_path / "t.jsonl", "co2_annual_increase", [1.9, 1.9])
    q = _w(tmp_path / "q.json", {"hypotheses": [
        {"metric": "co2_annual_increase", "predicted": 0.81, "lo": 0.20, "hi": 1.42}]})
    out = oc.consolidation_queue(q, tier)
    hard = [b for b in out if b.get("severity") != "note"]
    notes = [b for b in out if b.get("severity") == "note"]
    assert hard == [], "къс запис не е нарушение"
    assert notes and notes[0]["unjudged"][0]["metric"] == "co2_annual_increase", \
        "но несъдената хипотеза трябва да се вижда, иначе минава за съдена"


# ── счетоводството ───────────────────────────────────────────────────────────

def test_the_rejection_taxonomy_must_add_up(tmp_path):
    """Серия, нито издадена, нито отхвърлена, е изпаднала между два филтъра."""
    p = _w(tmp_path / "c.json", {"series_considered": 109, "emitted": 5, "truncated": 0,
                                 "rejected": {"too_few_points": 50, "constant_series": 4}})
    bad = oc.consolidation_bookkeeping(p)
    assert bad and bad[0]["lost"] == 50, "109 - (54 + 5) = 50 изгубени серии"


def test_a_balanced_ledger_passes(tmp_path):
    p = _w(tmp_path / "c.json", {"series_considered": 109, "emitted": 5, "truncated": 0,
                                 "rejected": {"too_few_points": 57, "constant_series": 46,
                                              "inside_the_noise_at_every_horizon": 1}})
    assert oc.consolidation_bookkeeping(p) == []


# ── дневният слой ────────────────────────────────────────────────────────────

def test_a_duplicate_day_is_refused(tmp_path):
    """Два реда за един ден дават на този ден двойна тежест в напасването."""
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"date": "2026-09-01", "indicator": "a.b", "value": 1.0},
        {"date": "2026-09-01", "indicator": "a.b", "value": 2.0}]), encoding="utf-8")
    whys = " ".join(b["why"] for b in oc.daily_tier(p))
    assert "duplicate" in whys


def test_a_boolean_is_not_a_number(tmp_path):
    """isinstance(True, int) е True в Python. Флаг, влязъл като 1.0, е
    безсмислица с формата на истина."""
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"date": "2026-09-01", "indicator": "a.b", "value": True}),
                 encoding="utf-8")
    assert oc.daily_tier(p), "булево не бива да мине за наблюдение"


# ── доказателството и ученикът ───────────────────────────────────────────────

def test_a_mismatched_merkle_hash_is_refused(tmp_path):
    p = _w(tmp_path / "m.json", {"ok": True, "stored_hash": "aaa", "recomputed": "bbb", "signals": 46})
    whys = " ".join(b["why"] for b in oc.merkle_verify(p))
    assert "stored_hash != recomputed" in whys


def test_a_sealed_cycle_with_zero_signals_is_refused(tmp_path):
    p = _w(tmp_path / "m.json", {"ok": True, "stored_hash": "a", "recomputed": "a", "signals": 0})
    whys = " ".join(b["why"] for b in oc.merkle_verify(p))
    assert "zero signals" in whys


def test_an_alpha_outside_zero_one_is_refused(tmp_path):
    p = _w(tmp_path / "l.json", {"A::b": {"alpha": 1.4, "fitted_on": 10}})
    whys = " ".join(b["why"] for b in oc.learner_state(p))
    assert "alpha outside" in whys


def test_a_fixture_cycle_id_in_the_live_reviews_is_refused(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps({"cycle_id": "c1", "carry_forward": "x"}), encoding="utf-8")
    whys = " ".join(b["why"] for b in oc.cycle_reviews(p))
    assert "not a timestamp" in whys


def test_a_lesson_key_carrying_a_number_is_refused(tmp_path):
    """Ключ с цикъл или стойност в себе си е уникален по построение — същият
    задънен край като дословното сравнение, само в по-къс костюм."""
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps({"cycle_id": "2026-09-12T03:04:02+03:00",
                             "lesson_key": "resolve NOAA 427.15 conflicts"}), encoding="utf-8")
    whys = " ".join(b["why"] for b in oc.cycle_reviews(p))
    assert "carries a number" in whys


# ── самият пробег ────────────────────────────────────────────────────────────

def test_a_contract_that_raises_counts_as_violated_not_as_passed(monkeypatch, tmp_path):
    """Договор, който гръмне, не бива да чете като успех.

    LATEST се пренасочва към tmp_path: check_all() пише отчета си, а пазачът в
    conftest.py хвана точно това — първата версия на този тест писа в истинския
    memory/output_contracts_latest.json. Пазачът е прав; тестът беше грешен.
    """
    def boom():
        raise RuntimeError("simulated")
    monkeypatch.setattr(oc, "CONTRACTS", (boom,))
    monkeypatch.setattr(oc, "LATEST", tmp_path / "latest.json")
    rec = oc.check_all()
    assert rec["ok"] is False and "raised RuntimeError" in rec["violations"][0]["why"]


def test_the_check_touches_no_model_and_no_network():
    """Обещанието в докстринга, направено проверимо — през AST, не през текста."""
    import ast
    tree = ast.parse((REPO / "core" / "output_contracts.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    forbidden = {"subprocess", "requests", "urllib", "http", "socket", "ollama",
                 "openai", "httpx", "aiohttp"}
    assert not (found & forbidden), f"забранен внос: {found & forbidden}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
