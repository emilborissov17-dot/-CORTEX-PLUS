"""
core/measurement_honesty.py — разликата между ИЗМЕРЕНО и ТВЪРДЯНО.

ЗАЩО СЪЩЕСТВУВА (измерено на 20 август 2026)
--------------------------------------------
Последният запис в memory/goal_score_history.json:

    10 оси  ->  10 x "llm_level",  0 x "measured"

Цялата история: 69 llm_level | 28 measured | 12 llm_level(risk-inverted).
Осем оси стоят на ТОЧНО 60.0, защото модел ги е поставил там.

А goal_score_calculator.py няма нито едно срещане на "llm_level" или
"score_source". Тоест твърдение на модел тежи в композита точно колкото
четене от NOAA.

Това е директно срещу визията. Уред, който не различава измерено от твърдяно,
не може да покаже разликата между твърдение и реалност — той сам е източникът
на твърдения. Не е дефект в апарата; дефект е в самата цел.

КАКВО ПРАВИ ТОЗИ МОДУЛ
----------------------
Класифицира всяка ос по ПРОИЗХОДА на числото ѝ и връща не едно число, а
картина: честен композит само върху измереното, срещу днешния композит, плюс
дела на твърдяното — разбито по петте подцели.

ДВЕ ПРАВИЛА, ВГРАДЕНИ В ТИПА, НЕ В ДИСЦИПЛИНАТА
-----------------------------------------------
1. FAIL-CLOSED. Непознат източник се брои за ТВЪРДЯН, не за измерен.
   Липсата на доказателство не е доказателство.

2. КОМПОЗИТЪТ НЕ СЕ ЧЕТЕ САМ. Reading.__float__ хвърля. Числото пътува
   заедно с покритието си или не пътува. Това прави E5 дефекта
   (заглушен сензор вдига композита) невъзможен за нов код, вместо да
   разчита някой да го помни.

Този модул НЕ пише в живото състояние на системата освен в собствения си
изходен файл, и НЕ мени никакъв скор. Той само казва какво е какво.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
HISTORY = BASE / "memory" / "goal_score_history.json"
TARGETS = BASE / "config" / "target_config.json"
OUT = BASE / "memory" / "measurement_honesty_latest.json"

# --------------------------------------------------------------------------- #
# класификация на произхода
# --------------------------------------------------------------------------- #

MEASURED = "MEASURED"   # число, проследимо до външен източник
CARRIED = "CARRIED"     # пренесено от по-ранно реално четене
ASSERTED = "ASSERTED"   # мнение на модела, не измерване
ABSENT = "ABSENT"       # няма число

# Само тези низове се броят за измерване. Списъкът е БЯЛ нарочно:
# нов източник трябва да бъде добавен съзнателно, а не да се промъкне,
# защото името му случайно не съдържа "llm".
_MEASURED_SOURCES = frozenset({
    "measured",
    "composed",
    "scorer",
    "real",
})

_CARRIED_SOURCES = frozenset({
    "carried",
    "carry_forward",
    "_carried",
})


def classify(source) -> str:
    """
    Произходът на едно число. FAIL-CLOSED по дизайн.

    Всичко, което не е в белия списък — включително None, празен низ и всеки
    непознат низ — се класифицира като ТВЪРДЯНО. Ако утре някой добави
    източник 'satellite_v2' и забрави да го впише тук, системата ще
    подцени себе си. Това е правилната посока на грешката.
    """
    if source is None:
        return ABSENT
    s = str(source).strip().lower()
    if not s:
        return ABSENT
    base = s.split("(", 1)[0].strip()
    if base in _MEASURED_SOURCES:
        return MEASURED
    if base in _CARRIED_SOURCES:
        return CARRIED
    return ASSERTED


# --------------------------------------------------------------------------- #
# число, което не може да бъде прочетено само
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Reading:
    """
    Композит, който отказва да бъде използван като гол float.

    0.680 при 60% покритие не е същото като 0.680 при 95%. Досега кодът
    нямаше как да различи двете, защото и двете бяха просто float.
    """
    value: float | None
    coverage: float          # дял от ОБЩОТО тегло, зад което стои измерване
    asserted_share: float    # дял от общото тегло, зад което стои твърдение
    basis_weight: float      # теглото, върху което value е сметнато
    total_weight: float

    def __float__(self):
        raise TypeError(
            "Композитът не се чете сам. 0.680 при 60% покритие не е същото "
            "като 0.680 при 95%. Ползвай .value и .coverage заедно, или "
            ".as_text() за доклад."
        )

    def as_text(self) -> str:
        if self.value is None:
            return f"НЯМА ЧЕСТНО ЧИСЛО (покритие {self.coverage:.0%})"
        return (f"{self.value:.4f} при покритие {self.coverage:.0%} "
                f"(твърдяно {self.asserted_share:.0%})")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "coverage": round(self.coverage, 4),
            "asserted_share": round(self.asserted_share, 4),
            "basis_weight": round(self.basis_weight, 1),
            "total_weight": round(self.total_weight, 1),
        }


@dataclass
class Assessment:
    ts: str
    by_axis: dict = field(default_factory=dict)
    by_branch: dict = field(default_factory=dict)
    honest: Reading | None = None
    todays_number: Reading | None = None
    asserted_axes: list = field(default_factory=list)
    absent_axes: list = field(default_factory=list)
    verdict: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "verdict": self.verdict,
            "honest_composite": self.honest.to_dict() if self.honest else None,
            "todays_number": self.todays_number.to_dict() if self.todays_number else None,
            "asserted_axes": self.asserted_axes,
            "absent_axes": self.absent_axes,
            "by_branch": self.by_branch,
            "by_axis": self.by_axis,
        }


# --------------------------------------------------------------------------- #
# оценката
# --------------------------------------------------------------------------- #

def _branches(targets: dict) -> dict:
    return {k: v for k, v in targets.items() if not str(k).startswith("_")}


def assess(scores: dict, sources: dict, targets: dict, ts: str | None = None) -> Assessment:
    """
    scores  : ос -> число (както го пише цикълът)
    sources : ос -> низ за произход (score_sources)
    targets : config/target_config.json
    """
    a = Assessment(ts=ts or datetime.now(timezone.utc).isoformat(timespec="seconds"))

    total_w = 0.0
    honest_num = honest_w = 0.0
    todays_num = todays_w = 0.0
    asserted_w = 0.0

    for branch, axes in _branches(targets).items():
        b = {"weight": 0.0, "measured_weight": 0.0, "asserted_weight": 0.0,
             "absent_weight": 0.0, "axes": {}}

        for axis, cfg in axes.items():
            w = float(cfg.get("weight", 1))
            total_w += w
            b["weight"] += w

            raw = scores.get(axis)
            kind = ABSENT if raw is None else classify(sources.get(axis))
            if raw is None:
                kind = ABSENT

            a.by_axis[axis] = {"branch": branch, "weight": w, "kind": kind,
                               "score": raw, "source": sources.get(axis)}
            b["axes"][axis] = kind

            if kind in (MEASURED, CARRIED):
                b["measured_weight"] += w
                honest_num += float(raw) * w
                honest_w += w
                todays_num += float(raw) * w
                todays_w += w
            elif kind == ASSERTED:
                b["asserted_weight"] += w
                asserted_w += w
                a.asserted_axes.append({"axis": axis, "weight": w,
                                        "score": raw, "source": sources.get(axis)})
                # днешното число ги брои — точно това е дефектът
                todays_num += float(raw) * w
                todays_w += w
            else:
                b["absent_weight"] += w
                a.absent_axes.append({"axis": axis, "weight": w})

        b["measured_share_of_branch"] = (round(b["measured_weight"] / b["weight"], 4)
                                         if b["weight"] else 0.0)
        a.by_branch[branch] = b

    coverage = honest_w / total_w if total_w else 0.0
    asserted_share = asserted_w / total_w if total_w else 0.0

    a.honest = Reading(
        value=(honest_num / honest_w) if honest_w else None,
        coverage=coverage, asserted_share=asserted_share,
        basis_weight=honest_w, total_weight=total_w,
    )
    a.todays_number = Reading(
        value=(todays_num / todays_w) if todays_w else None,
        coverage=(todays_w / total_w if total_w else 0.0),
        asserted_share=asserted_share,
        basis_weight=todays_w, total_weight=total_w,
    )

    if honest_w == 0:
        a.verdict = (
            "НЯМА ИЗМЕРВАНЕ. Нито една ос не носи число от външен източник. "
            "Днешният композит е изцяло съставен от твърдения на модела и не "
            "казва нищо за света."
        )
    elif asserted_share >= 0.5:
        a.verdict = (
            f"ПОВЕЧЕТО Е ТВЪРДЕНИЕ. {asserted_share:.0%} от теглото на целта стои "
            f"зад мнение на модела, не зад измерване. Честният композит покрива "
            f"{coverage:.0%}."
        )
    elif asserted_share > 0:
        a.verdict = (
            f"ЧАСТИЧНО ИЗМЕРЕНО. Покритие {coverage:.0%}; твърдяно "
            f"{asserted_share:.0%}. Осите по-долу са мнение, не данни."
        )
    else:
        a.verdict = f"ИЗМЕРЕНО. Покритие {coverage:.0%}, нула твърдяни оси."

    return a


# --------------------------------------------------------------------------- #
# доклад и пуск
# --------------------------------------------------------------------------- #

def report(a: Assessment) -> str:
    lines = [
        "=" * 68,
        "ЧЕСТНОСТ НА ИЗМЕРВАНЕТО",
        "=" * 68,
        a.verdict,
        "",
        f"  честен композит (само измерено) : {a.honest.as_text()}",
        f"  днешното число (с твърденията)  : {a.todays_number.as_text()}",
        "",
        f"{'клон':<28} {'тегло':>6} {'измерено':>9} {'твърдяно':>9} {'липсва':>8}",
    ]
    for name, b in a.by_branch.items():
        lines.append(f"{name:<28} {b['weight']:>6.0f} {b['measured_weight']:>9.0f} "
                     f"{b['asserted_weight']:>9.0f} {b['absent_weight']:>8.0f}")

    if a.asserted_axes:
        lines += ["", "ОСИ, КОИТО СА МНЕНИЕ, НЕ ИЗМЕРВАНЕ:"]
        for x in sorted(a.asserted_axes, key=lambda r: -r["weight"]):
            lines.append(f"  {x['axis']:<40} w={x['weight']:>2.0f}  "
                         f"{x['score']}  <- {x['source']}")
    return "\n".join(lines)


def _latest_record(history) -> dict:
    items = history if isinstance(history, list) else list(history.values())
    return items[-1] if items else {}


def run(write: bool = True) -> dict:
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    rec = _latest_record(history)

    a = assess(rec.get("scores", {}) or {},
               rec.get("score_sources", {}) or {},
               targets,
               ts=rec.get("timestamp"))
    print(report(a))
    if write:
        OUT.write_text(json.dumps(a.to_dict(), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"\n-> {OUT}")
    return a.to_dict()


if __name__ == "__main__":
    run()
