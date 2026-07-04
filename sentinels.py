"""
sentinels.py — Learning Loop сентинел-регистър.

10 държави, избрани да покрият целия спектър на divergence вместо да смятаме
всичките 175/217 наведнъж (дълбочина преди широчина). Числата са проверени
срещу output/divergence_latest.json (all_results) на 2026-07-04 — ако този
файл бъде преизчислен, стойностите тук трябва да се сверят наново.
"""

import sys
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class Sentinel:
    iso2: str
    name: str
    category: str  # "facade" | "transition" | "clean" | "chaos"
    quant_pct: float
    qual_pct: float
    divergence: float
    note: str


SENTINELS: dict[str, Sentinel] = {
    "CN": Sentinel(
        "CN", "China", "facade", 0.782, 0.247, 0.534,
        "най-голямата измерена дивергенция в целия universe",
    ),
    "RS": Sentinel(
        "RS", "Serbia", "facade", 0.678, 0.266, 0.412,
        "потвърдена от live pilot (HIGH confidence, agrees_with_vdem=True)",
    ),
    "AZ": Sentinel(
        "AZ", "Azerbaijan", "facade", 0.391, 0.057, 0.333,
        "потвърдена от live pilot",
    ),
    "AM": Sentinel(
        "AM", "Armenia", "transition", 0.655, 0.496, 0.159,
        "умерена дивергенция — кандидат за затваряне на пропастта",
    ),
    "MD": Sentinel(
        "MD", "Moldova", "transition", 0.615, 0.596, 0.019,
        "почти нулева — гранична зона, тест дали методите различават шум от сигнал",
    ),
    "EC": Sentinel(
        "EC", "Ecuador", "transition", 0.310, 0.410, -0.100,
        "обратен знак (качественото изпреварва количественото) — рядък контра-пример",
    ),
    "EE": Sentinel(
        "EE", "Estonia", "clean", 0.920, 0.964, -0.044,
        "потвърден чист контрол от live pilot (agrees_with_vdem=False, т.е. НЕ facade — очаквано)",
    ),
    "DK": Sentinel(
        "DK", "Denmark", "clean", 0.994, 1.000, -0.006,
        "най-чистият контрол в целия universe",
    ),
    "LB": Sentinel(
        "LB", "Lebanon", "chaos", 0.362, 0.320, 0.042,
        "ниска измерена дивергенция, но известна реална волатилност (валутна криза) — stress-test за слепи петна",
    ),
    "AR": Sentinel(
        "AR", "Argentina", "chaos", 0.672, 0.546, 0.126,
        "известни резки политико-икономически завои — тества дали линейните методи се чупят на волатилни серии",
    ),
}


def get(iso2: str) -> Sentinel:
    return SENTINELS[iso2.upper()]


def all_sentinels() -> list[Sentinel]:
    return list(SENTINELS.values())


def by_category(category: str) -> list[Sentinel]:
    return [s for s in SENTINELS.values() if s.category == category]


if __name__ == "__main__":
    for cat in ("facade", "transition", "clean", "chaos"):
        print(f"\n{cat.upper()}:")
        for s in by_category(cat):
            print(f"  {s.iso2} ({s.name}): divergence={s.divergence:+.3f}  — {s.note}")
