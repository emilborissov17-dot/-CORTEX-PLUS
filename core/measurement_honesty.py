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
# The scorer's own output. It is the only place that knows WHICH external
# reading resolved an axis; memory/goal_score_history.json knows only the word
# "measured". K1 needs the former (ITEM 7.1c).
GOAL_SNAP = BASE / "snapshots" / "master" / "goal_score_latest.json"

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


# --------------------------------------------------------------------------- #
# K1 — the first needle (ITEM 7.1, 28 August 2026)
# --------------------------------------------------------------------------- #
#
# K1 = measured_weight / total_weight, and "measured" here means ONE thing:
# the axis's primary metric resolved from an external observation in this
# cycle. Not a model assertion, not an llm_level bucket, and not a value
# carried forward from an earlier reading — carried is real but it is not a
# measurement TODAY, so it is counted and published on its own line rather than
# folded into the numerator.
#
# WHY THE PROVENANCE COMES FROM THE SCORER AND NOT FROM score_sources.
# memory/goal_score_history.json records the string "measured" per axis. That
# string is a verdict with no evidence attached: it cannot say which feed, which
# key, or which number. 7.1(c) requires an axis to NAME its external observation
# before it counts, so the numerator is built from the scorer's own
# metric_details — observation_key, source_id, current — and an axis that cannot
# name one does not count, whatever its score says.
#
# FAIL-CLOSED, AND null IS NOT ZERO. If the scorer snapshot is missing or
# unreadable, measured_weight and k1 are written as null with the reason beside
# them. Writing 0.0 there would publish "nothing is measured" — a claim — when
# the truth is "nobody looked", which is an absence.


def read_provenance(path: pathlib.Path | None = None) -> tuple[dict, str | None]:
    """
    axis -> the external reading that resolved it, from the scorer's snapshot.

    Returns (provenance, note). note is None on a clean read; it carries the
    reason when provenance is EMPTY, and a caveat when provenance was read from
    the older, lossy block. An axis appears ONLY if the snapshot named an
    observation_key for it; presence in this dict is exactly the condition for
    counting the axis in K1.
    """
    p = path or GOAL_SNAP
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"{p.as_posix()} does not exist — the scorer has not run here"
    except Exception as e:
        return {}, f"{p.as_posix()} unreadable: {type(e).__name__}: {e}"

    # axis_observations is the authoritative block and is keyed by AXIS.
    # metric_details is keyed by METRIC, and two axes share co2_ppm_mauna_loa,
    # so reading provenance out of it loses one of them and understates K1 by
    # that axis's whole weight. It stays as a fallback only for snapshots
    # written before 28 Aug 2026, and says so.
    obs = snap.get("axis_observations")
    if isinstance(obs, dict) and obs:
        prov = {axis: {
            "source_id":         d.get("source_id"),
            "observation_key":   d.get("observation_key"),
            "observation_where": d.get("observation_where"),
            "observed_value":    d.get("observed_value"),
            "metric":            d.get("metric"),
        } for axis, d in obs.items()
            if isinstance(d, dict) and d.get("observation_key")}
        if prov:
            return prov, None

    details = snap.get("metric_details")
    if not isinstance(details, dict):
        return {}, (f"{p.as_posix()} carries neither axis_observations nor "
                    f"metric_details (keys: {sorted(snap)[:8]})")

    prov = {}
    for metric, d in details.items():
        if not isinstance(d, dict):
            continue
        axis = d.get("axis")
        key = d.get("observation_key")
        if not axis or not key:
            continue
        prov[axis] = {
            "source_id":         d.get("source_id"),
            "observation_key":   key,
            "observation_where": d.get("observation_where"),
            "observed_value":    d.get("current"),
            "metric":            metric,
        }
    if not prov:
        return {}, (f"{p.as_posix()} names no external observation for any axis — "
                    f"the snapshot predates ITEM 7.1c and has to be regenerated "
                    f"by one cycle before K1 has a number")
    return prov, ("read from metric_details, not axis_observations: this snapshot "
                  "predates 28 Aug 2026 and a metric shared by two axes counts once")


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
    # K1 and its inputs. None means "not computed", never "zero".
    measured_weight: float | None = None
    carried_weight: float = 0.0
    k1: float | None = None
    k1_why: str = ""
    basis_ts: str | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "verdict": self.verdict,
            # ── K1, TOP-LEVEL AND EXPLICIT (ITEM 7.1b) ──────────────────────
            # measured_weight is the weight whose axes NAMED an external
            # observation this cycle. k1 is that over total_weight. k1_why says
            # how the numerator was arrived at, or why there is no number.
            "measured_weight": self.measured_weight,
            "k1": self.k1,
            "k1_why": self.k1_why,
            # Carried-forward weight, published separately and deliberately NOT
            # inside measured_weight: a value carried from an earlier real
            # reading is honest, and it is still not a measurement today.
            "carried_weight": round(self.carried_weight, 1),
            # ts is the moment this file was written. basis_ts is the timestamp
            # of the goal_score_history record honest_composite and
            # todays_number were computed from — the two used to be the same
            # key, which meant a file written today could be stamped with a
            # two-month-old date and nobody could tell.
            "basis_ts": self.basis_ts,
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


def assess(scores: dict, sources: dict, targets: dict, ts: str | None = None,
           provenance: dict | None = None, provenance_why: str | None = None,
           basis_ts: str | None = None) -> Assessment:
    """
    scores     : ос -> число (както го пише цикълът)
    sources    : ос -> низ за произход (score_sources)
    targets    : config/target_config.json
    provenance : ос -> външното четене, което я е разрешило (read_provenance).
                 None означава „не е гледано", не „няма" — виж k1_why.
    """
    a = Assessment(ts=ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   basis_ts=basis_ts)

    prov = provenance if isinstance(provenance, dict) else None
    k1_weight = 0.0
    carried_w = 0.0

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

            # ── THE WHY, PER AXIS (ITEM 7.1c) ────────────────────────────────
            # measured_by is the external reading this axis resolved from, or
            # None. counts_toward_k1 is exactly "measured_by is not None": an
            # axis that cannot name its observation does not count, whatever
            # its score or its score_source string says. When the scorer
            # snapshot could not be read at all, both are None and k1_why —
            # not a zero — carries the reason.
            measured_by = (prov or {}).get(axis)
            counts = bool(measured_by) if prov is not None else None
            if counts:
                k1_weight += w
            if kind == CARRIED:
                carried_w += w

            a.by_axis[axis] = {"branch": branch, "weight": w, "kind": kind,
                               "score": raw, "source": sources.get(axis),
                               "measured_by": measured_by,
                               "counts_toward_k1": counts}
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

    # ── K1 ──────────────────────────────────────────────────────────────────
    a.carried_weight = carried_w
    if prov is None:
        a.measured_weight = None
        a.k1 = None
        a.k1_why = ("NOT COMPUTED: no provenance was supplied. "
                    + (provenance_why or "read_provenance() was never called."))
    elif total_w <= 0:
        a.measured_weight = round(k1_weight, 1)
        a.k1 = None
        a.k1_why = "NOT COMPUTED: total_weight is 0 — config/target_config.json has no weighted axes."
    else:
        named = sum(1 for v in a.by_axis.values() if v.get("counts_toward_k1"))
        a.measured_weight = round(k1_weight, 1)
        a.k1 = round(k1_weight / total_w, 4)
        a.k1_why = (f"{named} of {len(a.by_axis)} axes named an external observation "
                    f"this cycle, carrying {k1_weight:.1f} of {total_w:.1f} weight. "
                    f"Source: snapshots/master/goal_score_latest.json axis_observations."
                    + (f" CAVEAT: {provenance_why}" if provenance_why else ""))

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
        ("  K1 (measured weight / total)    : "
         + ("НЯМА ЧИСЛО — " + a.k1_why if a.k1 is None
            else f"{a.k1:.4f}  ({a.measured_weight:.1f} / "
                 f"{a.honest.total_weight:.1f})")),
        f"  пренесено тегло (не в K1)       : {a.carried_weight:.1f}",
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


def run(write: bool = True, out: pathlib.Path | None = None,
        history: pathlib.Path | None = None,
        goal_snap: pathlib.Path | None = None) -> dict:
    """
    Write memory/measurement_honesty_latest.json.

    Called from fast_cycle_runner.py step 20.1, after the scorer (12.6) and
    after feedback_loop (20) has appended today's record with its
    score_sources. Before 28 Aug 2026 NOTHING called this: the only writer was
    a human typing `python core/measurement_honesty.py`, which last happened on
    20 August, and the four needles went eight days without a number.

    The paths are arguments so a fixture can run the whole thing without
    touching live state.
    """
    hist_p = history or HISTORY
    hist = json.loads(hist_p.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    rec = _latest_record(hist)
    prov, note = read_provenance(goal_snap)

    a = assess(rec.get("scores", {}) or {},
               rec.get("score_sources", {}) or {},
               targets,
               # ts is NOW. The record's own timestamp travels as basis_ts.
               ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               # An EMPTY provenance is "nobody looked" and must produce null,
               # not zero. A non-empty one with a note is usable and carries
               # the caveat into k1_why.
               provenance=(prov or None),
               provenance_why=note,
               basis_ts=rec.get("timestamp"))
    print(report(a))
    if note:
        print(f"[HONESTY] provenance note: {note}")
    if write:
        target = out or OUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(a.to_dict(), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"\n-> {target}")
    return a.to_dict()


if __name__ == "__main__":
    import sys
    run(write="--dry-run" not in sys.argv)
