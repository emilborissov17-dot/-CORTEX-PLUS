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
import math
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

# ── F и G ────────────────────────────────────────────────────────────────────
#
# F. SLOPE SMALLER THAN ITS OWN ERROR — по-малко ли е движението от грешката,
#    с която е измерено движението.
# G. HORIZON LONGER THAN THE RECORD — не се предсказва по-далеч напред, отколкото
#    сме гледали назад.
#
# ВСИЧКИ СТОЙНОСТИ ПО-ДОЛУ СА ИСТИНСКИ, прочетени от memory/daily_tier.jsonl на
# 13 септември 2026 и записани тук като числа, за да е тестът и истински, и
# детерминиран. Четенето на живия файл вътре в теста не върши работа: conftest
# пренасочва c.DAILY_TIER към tmp_path — и е прав да го прави — а и утрешната нощ
# ще смени числата под краката на теста.

TODAY_13 = date(2026, 9, 13)

# CLIMATE_GLOBAL_RISK_REVIEW/co2_annual_increase, 28 точки, 2026-08-14..09-13.
# Наклон -0.00269/ден при стандартна грешка 0.00602 — 0.45 пъти собствената си
# грешка. Точно тази хипотеза стоеше в нощния memory/consolidation_queue.json.
REAL_CO2_ANNUAL = [(30, 2.3), (29, 2.3), (28, 2.1), (27, 2.1), (23, 2.1), (22, 1.3),
                   (21, 1.4), (20, 1.4), (19, 1.4), (18, 1.4), (17, 1.4), (16, 1.4),
                   (15, 1.8), (14, 1.8), (13, 1.8), (12, 1.8), (11, 1.8), (10, 1.8),
                   (9, 1.8), (8, 1.8), (7, 1.9), (6, 1.9), (5, 1.9), (4, 1.9),
                   (3, 1.9), (2, 1.9), (1, 1.8), (0, 1.8)]

# Съседът ѝ в същата ос: същият прозорец, същата дължина, сигма до втория знак
# същата — и минава вратата 5.3 пъти. Разликата е само в това отношение, което е
# и причината сигма и r2 поотделно да не стигат.
REAL_CO2_PPM = [(30, 428.2), (29, 428.2), (28, 427.6), (27, 427.6), (23, 427.6),
                (22, 426.9), (21, 427.0), (20, 427.0), (19, 427.0), (18, 427.0),
                (17, 427.0), (16, 427.0), (15, 426.9), (14, 426.9), (13, 426.9),
                (12, 426.9), (11, 426.9), (10, 426.9), (9, 426.9), (8, 426.9),
                (7, 427.1), (6, 427.1), (5, 427.1), (4, 427.1), (3, 427.1),
                (2, 427.1), (1, 426.3), (0, 426.3)]

# quakes.quake_m45_count, 60 дни. Наклонът ѝ е 3.9 пъти грешката си, тоест минава
# F — и точно затова стига до G, където иска хоризонт 90 върху запис от 59 дни.
REAL_QUAKES_60 = [(60, 20.0), (59, 31.0), (58, 63.0), (57, 32.0), (56, 21.0),
                  (55, 27.0), (54, 32.0), (53, 22.0), (52, 24.0), (51, 28.0),
                  (50, 9.0), (49, 14.0), (48, 35.0), (47, 33.0), (46, 33.0),
                  (45, 39.0), (44, 24.0), (43, 28.0), (42, 28.0), (41, 12.0),
                  (40, 15.0), (39, 42.0), (38, 14.0), (37, 16.0), (36, 21.0),
                  (35, 23.0), (34, 20.0), (33, 22.0), (32, 14.0), (31, 14.0),
                  (30, 36.0), (29, 56.0), (28, 33.0), (27, 41.0), (26, 32.0),
                  (25, 31.0), (24, 31.0), (23, 29.0), (22, 22.0), (21, 17.0),
                  (20, 22.0), (19, 17.0), (18, 25.0), (17, 22.0), (16, 17.0),
                  (15, 15.0), (14, 18.0), (13, 10.0), (12, 18.0), (11, 18.0),
                  (10, 24.0), (9, 12.0), (8, 15.0), (7, 15.0), (6, 7.0),
                  (5, 16.0), (4, 12.0), (3, 9.0), (2, 6.0), (1, 13.0)]


def _sealed(tmp_path, ind, pairs):
    """Запечатан свят от ИСТИНСКИ двойки (дни назад от 13 септември, стойност)."""
    p = tmp_path / "real.jsonl"
    p.write_text(chr(10).join(json.dumps(
        {"date": (TODAY_13 - timedelta(days=d)).isoformat(),
         "indicator": ind, "value": v}) for d, v in pairs), encoding="utf-8")
    return p


def _fit_of(tier, ind, window=30):
    series = c.build_series(c.read_daily_tier(window, tier, TODAY_13))
    return c._fit(series[("DAILY", ind)])


def test_the_real_co2_annual_increase_is_refused_for_being_smaller_than_its_error(tmp_path):
    """Хипотезата от нощния опис пада, и отказът носи числата, не само присъдата."""
    tier = _sealed(tmp_path, "co2.annual_increase", REAL_CO2_ANNUAL)
    rec = c.run(write=False, today=TODAY_13, archive=tmp_path / "none", daily=tier)
    assert rec["rejected"]["slope_smaller_than_its_own_error"] == 1
    assert rec["emitted"] == 0, "движение под собствената си грешка не е движение"
    r = next(x for x in rec["refused"]
             if x.get("gate") == "slope_smaller_than_its_own_error")
    assert r["ratio"] == pytest.approx(0.447, abs=0.01)
    assert r["abs_slope"] == pytest.approx(0.00269, abs=1e-4)
    assert r["se_slope"] == pytest.approx(0.00602, abs=1e-4)
    assert r["required_ratio"] == 2.0


def test_the_real_co2_ppm_beside_it_clears_the_same_gate(tmp_path):
    """Същата ос, същият прозорец, същата сигма — и минава пет пъти. Врата, която
    режеше по сигма или по r2, щеше да отреже и това."""
    tier = _sealed(tmp_path, "co2.ppm_current", REAL_CO2_PPM)
    fit = _fit_of(tier, "co2.ppm_current")
    assert c.slope_smaller_than_its_own_error(fit) is None
    assert abs(fit["slope"]) / fit["se_slope"] > 5.0
    rec = c.run(write=False, today=TODAY_13, archive=tmp_path / "none", daily=tier)
    assert rec["emitted"] == 1
    assert rec["rejected"]["slope_smaller_than_its_own_error"] == 0


def test_the_standard_error_comes_from_the_same_points_as_the_fit(tmp_path):
    """se = sigma / sqrt(Sxx), с Sxx на редовете, по които е направена нагласата.
    Пресметнат наново другаде, той можеше да не съвпадне с линията, която съди."""
    tier = _sealed(tmp_path, "co2.ppm_current", REAL_CO2_PPM)
    fit = _fit_of(tier, "co2.ppm_current")
    assert fit["se_slope"] == pytest.approx(
        fit["sigma"] / math.sqrt(fit["sxx"]), rel=1e-12)


def test_the_factor_is_two_standard_errors_and_pinned():
    assert c.MIN_SLOPE_T == 2.0, "разхлабването на този праг е решение, не дреболия"


def test_a_ninety_day_claim_on_a_fifty_nine_day_record_is_refused(tmp_path):
    """Истинските земетресения за 60 дни: наклонът минава F, хоризонтът пада на G."""
    tier = _sealed(tmp_path, "quakes.quake_m45_count", REAL_QUAKES_60)
    rec = c.run(write=False, today=TODAY_13, window_days=60,
                archive=tmp_path / "none", daily=tier)
    assert rec["rejected"]["horizon_longer_than_the_record"] == 1
    assert rec["emitted"] == 0
    r = next(x for x in rec["refused"]
             if x.get("gate") == "horizon_longer_than_the_record")
    assert r["horizon_days"] == 90 and r["span_days"] == 59


def test_the_horizon_is_refused_and_not_quietly_shortened(tmp_path):
    """Подрязването щеше да запази твърдението живо, отговаряйки на друг въпрос.
    Записаният отказ трябва да носи ИСКАНИЯ хоризонт, не удобен по-къс."""
    tier = _sealed(tmp_path, "quakes.quake_m45_count", REAL_QUAKES_60)
    rec = c.run(write=False, today=TODAY_13, window_days=60,
                archive=tmp_path / "none", daily=tier)
    r = next(x for x in rec["refused"]
             if x.get("gate") == "horizon_longer_than_the_record")
    assert r["horizon_days"] == 90, "хоризонтът е подрязан вместо отказан"
    assert not any(h["horizon_days"] < 90 for h in rec["hypotheses"])


def test_a_horizon_inside_the_record_passes_the_gate(tmp_path):
    tier = _sealed(tmp_path, "co2.ppm_current", REAL_CO2_PPM)
    fit = _fit_of(tier, "co2.ppm_current")
    h = c._hypothesis("A", "m", fit, TODAY_13)
    assert h["horizon_days"] <= fit["span_days"]
    assert c.horizon_longer_than_the_record(h, fit) is None


@pytest.mark.parametrize("ind,pairs,window", [
    ("co2.annual_increase", REAL_CO2_ANNUAL, 30),
    ("co2.ppm_current", REAL_CO2_PPM, 30),
    ("quakes.quake_m45_count", REAL_QUAKES_60, 60),
])
def test_every_series_lands_in_exactly_one_bucket(tmp_path, ind, pairs, window):
    """rejected + emitted + truncated == considered, и за трите свята.

    run() вече вдига AssertionError, ако сметката не излезе; това го проверява
    отвън, така че премахването на онази проверка да се вижда като червен тест,
    а не като по-тих изход.
    """
    tier = _sealed(tmp_path, ind, pairs)
    rec = c.run(write=False, today=TODAY_13, window_days=window,
                archive=tmp_path / "none", daily=tier)
    assert (sum(rec["rejected"].values()) + rec["emitted"] + rec["truncated"]
            == rec["series_considered"])
