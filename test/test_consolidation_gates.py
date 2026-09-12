# -*- coding: utf-8 -*-
"""test/test_consolidation_gates.py — двете врати пред тихата фаза. (12 Sep 2026)

D. LOCAL RUN, NOT DRIFT — съгласен ли е целият запис с посоката на прозореца.
E. IMPOSSIBLE AT THE HORIZON — излиза ли твърдението от домейна на своята серия.

Поводът е една истинска хипотеза от първата нощ, в която дневният слой беше
прочетен: "quakes.quake_m45_count надолу до -20.84, интервал [-35.67, -6.01]".
Брой земетресения. Всеки ред покрит, всеки клон взет, аритметиката точна.

Всеки тест строи ЗАПЕЧАТАН свят в tmp_path. Нищо не чете и не пише живото
състояние — точно дефектът, който conftest пазачът хвана два пъти днес.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import consolidation as c  # noqa: E402

TODAY = date(2026, 9, 12)


def _tier(p: Path, rows: list) -> Path:
    """rows: (indicator, days_ago, value)"""
    p.write_text("\n".join(json.dumps(
        {"date": (TODAY - timedelta(days=d)).isoformat(), "indicator": ind, "value": v})
        for ind, d, v in rows), encoding="utf-8")
    return p


# ИСТИНСКИТЕ стойности на quakes.quake_m45_count за 2026-08-13..2026-09-11,
# прочетени от memory/daily_tier.jsonl. Измисленият месец беше ГЛАДЪК и падаше
# на по-ранната врата ("достатъчно бързо за нощна стъпка"), защото при права
# линия наклонът е равен на средната нощна крачка. Истинската серия е шумна —
# крачката е ~7, наклонът ~0.9 — и точно затова стига до вратата D. Фикстура,
# по-подредена от света, проверява друг код, не този.
REAL_QUAKE_MONTH = [14, 36, 56, 33, 41, 32, 31, 31, 29, 22, 17, 22, 17, 25, 22,
                    17, 15, 18, 10, 18, 18, 24, 12, 15, 15, 7, 16, 12, 9, 6]


def _falling_month_flat_record(ind: str, n_long: int = 731) -> list:
    """Формата на quakes: две години шум около средна 21 без наклон, и последният
    месец — истинският — който пада. Стойностите са цели и неотрицателни: брой."""
    rows = [(ind, d, 21 + (d % 7) - 3) for d in range(n_long, 30, -1)]
    rows += [(ind, 30 - i, v) for i, v in enumerate(REAL_QUAKE_MONTH)]
    return rows


# ── D ────────────────────────────────────────────────────────────────────────

def test_a_month_that_falls_against_a_flat_record_is_a_run_not_a_drift(tmp_path):
    tier = _tier(tmp_path / "t.jsonl", _falling_month_flat_record("quakes.q"))
    rec = c.run(write=False, today=TODAY, archive=tmp_path / "no_archive", daily=tier)
    assert rec["rejected"]["local_run_not_drift"] >= 1
    assert rec["emitted"] == 0, "твърдение, което записът опровергава, не се издава"
    assert rec["long_record"]["judged_against_the_record"] >= 1


def test_a_window_the_record_agrees_with_survives_the_gate(tmp_path):
    """Същата дължина на записа, но наклонът сочи в същата посока."""
    rows = [("x.rising", d, 1000.0 - 0.5 * d) for d in range(400, 0, -1)]
    tier = _tier(tmp_path / "t.jsonl", rows)
    long = c.build_series(c.read_daily_tier(3650, tier, TODAY))
    win = c.build_series(c.read_daily_tier(30, tier, TODAY))
    k = ("DAILY", "x.rising")
    verdict = c.local_run_not_drift(c._fit(win[k]), long[k], len(win[k]))
    assert verdict is False, "записът е съгласен с посоката — това не е локален пробег"


def test_a_short_record_gives_no_basis_and_is_never_counted_as_agreement(tmp_path):
    """Годишният слой има две точки на серия и ВИНАГИ ще отговаря None.
    None не е съгласие — ако беше, всяка годишна серия щеше да мине за потвърдена."""
    rows = [("y.short", d, 10.0 + d) for d in range(25, 0, -1)]
    tier = _tier(tmp_path / "t.jsonl", rows)
    win = c.build_series(c.read_daily_tier(30, tier, TODAY))
    long = c.build_series(c.read_daily_tier(3650, tier, TODAY))
    k = ("DAILY", "y.short")
    assert c.local_run_not_drift(c._fit(win[k]), long[k], len(win[k])) is None


def test_the_gate_needs_three_windows_of_record_and_the_threshold_is_pinned():
    assert c.LONG_RECORD_FACTOR == 3, "разхлабването на този праг е решение, не дреболия"


# ── E ────────────────────────────────────────────────────────────────────────

def test_a_count_predicted_below_zero_is_refused_with_its_reason():
    h = {"lo": -35.67, "hi": -6.01, "predicted": -20.84}
    long_pts = [(TODAY - timedelta(days=d), float(21 + (d % 7) - 3)) for d in range(200, 0, -1)]
    why = c.impossible_at_the_horizon(h, long_pts)
    assert why and "cannot fall below zero" in why
    assert "observed min" in why, "отказът трябва да носи стойността, не само присъдата"


def test_a_series_with_negative_observations_gets_no_floor():
    """Аномалията на температурата е отрицателна по право. Домейнът се чете от
    данните, не от името — иначе всяка метрика с 'count' в името би получила под,
    а всяка без него не би."""
    h = {"lo": -1.2, "hi": -0.4, "predicted": -0.8}
    long_pts = [(TODAY - timedelta(days=d), -0.5 + (d % 5) * 0.1) for d in range(200, 0, -1)]
    assert c.impossible_at_the_horizon(h, long_pts) is None


def test_a_fractional_series_is_not_a_count():
    h = {"lo": -3.0, "hi": 1.0, "predicted": -1.0}
    long_pts = [(TODAY - timedelta(days=d), 4.5 + (d % 3) * 0.25) for d in range(200, 0, -1)]
    assert c.impossible_at_the_horizon(h, long_pts) is None, \
        "дробни стойности не са брой, дори да са положителни"


def test_a_short_record_cannot_establish_a_domain():
    h = {"lo": -5.0, "hi": -1.0, "predicted": -3.0}
    long_pts = [(TODAY - timedelta(days=d), float(d)) for d in range(5, 0, -1)]
    assert c.impossible_at_the_horizon(h, long_pts) is None


def test_the_refused_claim_is_kept_whole_and_never_clamped_to_zero(tmp_path):
    """Подрязан интервал превръща „моделът греши" в „моделът казва нула".
    Отказът трябва да пази числото такова, каквото е било."""
    rows = _falling_month_flat_record("z.count", n_long=200)
    tier = _tier(tmp_path / "t.jsonl", rows)
    # вратата D би спряла тази серия първа; проверяваме E пряко върху нейния запис
    long = c.build_series(c.read_daily_tier(3650, tier, TODAY))[("DAILY", "z.count")]
    h = {"lo": -35.67, "hi": -6.01, "predicted": -20.84}
    why = c.impossible_at_the_horizon(h, long)
    assert why is not None
    assert h["predicted"] == -20.84 and h["lo"] == -35.67, \
        "проверката съди, не поправя — числото остава такова, каквото моделът го е дал"


# ── счетоводството, което свързва двете с договора ───────────────────────────

def test_the_taxonomy_still_adds_up_with_the_two_new_categories(tmp_path):
    """Отхвърлени + издадени + отрязани == разгледани. Серия, изпаднала между два
    филтъра, е начинът, по който един ден изчезва половината вход."""
    tier = _tier(tmp_path / "t.jsonl",
                 _falling_month_flat_record("a.count")
                 + [("b.rising", d, 100.0 - 0.2 * d) for d in range(400, 0, -1)]
                 + [("c.short", d, 5.0) for d in range(3, 0, -1)])
    rec = c.run(write=False, today=TODAY, archive=tmp_path / "none", daily=tier)
    total = sum(rec["rejected"].values()) + rec["emitted"] + rec["truncated"]
    assert total == rec["series_considered"], (
        f"{total} != {rec['series_considered']}: {json.dumps(rec['rejected'])}")


def test_every_series_reaching_the_gate_is_counted_as_judged_or_unjudged(tmp_path):
    tier = _tier(tmp_path / "t.jsonl", _falling_month_flat_record("a.count", n_long=400))
    rec = c.run(write=False, today=TODAY, archive=tmp_path / "none", daily=tier)
    seen = rec["long_record"]["judged_against_the_record"] + rec["long_record"]["no_long_record"]
    assert seen >= 1
    assert seen <= rec["series_considered"]


def test_the_run_still_uses_no_model_and_no_network():
    assert c.imported_forbidden() == set()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
