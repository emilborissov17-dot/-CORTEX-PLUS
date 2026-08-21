#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/interval_head.py — ПЪРВАТА ОБУЧАЕМА ГЛАВА: ИНТЕРВАЛ, НЕ ЧИСЛО.

ЗАЩО ИНТЕРВАЛ
--------------
Всяко предсказание, което тази система е правила досега, е ТОЧКА: „осата ще
бъде 44.0". Точка не може да сгреши малко — тя или уцелва, или не, и затова
всяка присъда по нея е спор. Интервалът носи собствената си несигурност: „между
612 и 980 секунди". Той може да бъде тесен и да сгреши, или широк и да е
безполезен, и точно това го прави измерим с ЕДНО число (Winkler score), вместо
с разказ.

АРХИТЕКТУРА
------------
    замразено вграждане (2048) -> Linear 256 -> ReLU -> Linear 256 -> ReLU
                               -> Linear 2 -> (център, log-полуширина)

    lo = център - exp(log-полуширина)
    hi = център + exp(log-полуширина)

ОБЪРНАТ ИНТЕРВАЛ Е НЕВЪЗМОЖЕН ПО ПОСТРОЕНИЕ. Мрежата не предсказва lo и hi
поотделно — тя предсказва център и ЛОГАРИТЪМ на полуширината. exp() е винаги
положителен, значи hi > lo винаги, при всяко тегло, включително преди обучение
и при разминала се оптимизация. Проверка след факта („ако lo > hi, размени")
би скрила счупен модел вместо да го спре.

ЗАМРАЗЕНО значи замразено: вгражданията идват от локалния qwen2.5:3b през
Ollama, кешират се на диска по sha256 на текста, и НЕ УЧАСТВАТ в градиента.
Обучава се само главата. Ако Ollama мълчи, се пада на детерминирано хеширано
вграждане и ТОВА СЕ ОБЯВЯВА в записа на пускането — обучение върху резервно
представяне, представено като обучение върху истинското, е точно видът тихо
влошаване, срещу който е целият този репозиторий.

ЗАГУБАТА (Winkler / interval score, α = 0.2, тоест 80% интервал)

    W = (hi - lo)
        + (2/α)(lo - y)  ако y < lo
        + (2/α)(y - hi)  ако y > hi

Тя наказва ширината винаги и пропуска — скъпо. Модел, който отговаря
„между 0 и безкрайност", губи по ширина; модел, който отговаря „точно 3.0",
губи по пропуск. Няма как да се спечели с увереност без покритие.

В ЛОГАРИТМИЧНО ПРОСТРАНСТВО. Стъпките траят от 0.01 s до 2710 s. Загуба в
секунди би била изцяло за сметка на web_intelligence и би обявила модел, който
не различава нищо под минута, за добър. Обучава се върху ln(секунди); отчита се
и покритието, и ширината в СЕКУНДИ, за да не се крие зад мащаба.

РАЗДЕЛЯНЕТО Е ПО СТЪПКА, НЕ ПО РЕД. Ако `daily_analysis` има 12 реда, случайно
разделяне слага част от тях в обучението и част в проверката — и мрежата, която
вижда ЕДНО вграждане на име, просто ги е запомнила. Затова държим настрана цели
СТЪПКИ: проверката пита може ли моделът да предскаже времето на стъпка, която
никога не е засичал. Това е по-трудният въпрос и единственият интересен.

САМО ЗАЗЕМЕНИ ЦЕЛИ. Данните идват от core/training_log.py, който връща само
MEASURED. Ред, чийто произход е модел, никога не влиза — и това се проверява
тук отново, а не се приема на доверие.

ДВА ЧЕСТНИ ОТРИЦАТЕЛНИ РЕЗУЛТАТА (21 август 2026)
--------------------------------------------------
ПЪРВИЯТ. Главата виждаше ЕДНО вграждане на ИМЕ на стъпка, тоест всички редове на
`daily_analysis` имаха вход, който не се различава по нищо. При разделяне по цели
стъпки въпросът беше „можеш ли да предскажеш времетраенето на име, което не си
чел" — и отговорът беше не. Правилен отговор: имената не носят нищо за това
колко ще тече една стъпка.

ВТОРИЯТ, с истински признаци. Добавени са пореден номер на стъпката в цикъла,
час от денонощието като sin/cos, времетраенето на СЪЩАТА стъпка в последните три
цикъла, брой цикли от началото на дневника и свободна RAM в началото на стъпката.
Същият протокол — същото разделяне по цели стъпки, същата плоска базова линия,
същият хеширан контрол, същите епохи и семе. Измерено (`--compare`):

    рамо                                    heldout Winkler   покритие   ширина
    A  само имена, истинско вграждане            16.7224        11%       16 s
    B  само имена, хеширан контрол               17.1295         9%        9 s
    C  имена + признаци, истинско вграждане      13.3303        24%       12 s
    D  имена + признаци, хеширан контрол         15.6935         4%        3 s
    ПЛОСКА БАЗОВА ЛИНИЯ                            8.4337

Признаците помагат много — 16.72 -> 13.33, с покритие от 11% на 24% — И ВСЕ ПАК
ГУБЯТ от една константа. Това се казва на глас и не се пипа. Втори честен
отрицателен резултат е напредък; настройване, докато числото стане по-хубаво от
базовата линия, е Goodhart върху собствения ти измервателен уред.

ТРЕТО НЕЩО, КОЕТО ЛИЧИ ОТ ТАБЛИЦАТА и не беше търсено: C бие D (13.33 срещу
15.69), докато A и B са неразличими (16.72 срещу 17.13). Тоест семантичното
вграждане НЕ носи нищо само по себе си, но носи нещо, когато има с какво да се
съчетае. Това е хипотеза от една таблица, не заключение.

И ЧЕТВЪРТО: покритие 24% при номинални 80% значи, че главата не е неинформирана
— тя е СВРЪХУВЕРЕНА. Интервали от 12 s за стъпки от 0.01 s до 2710 s. Диагнозата
е различна от „не знае" и вероятно е следващата работа, но не днес.

    venv\\Scripts\\python.exe core/interval_head.py --selftest
    venv\\Scripts\\python.exe core/interval_head.py --compare
    venv\\Scripts\\python.exe -m core.interval_head --train
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CACHE = BASE / "memory" / "embeddings_cache.json"
RUNS = BASE / "memory" / "interval_head_runs.jsonl"
CURVE = BASE / "memory" / "interval_head_curve.json"

EMBED_MODEL = "qwen2.5:3b"
EMBED_URL = "http://localhost:11434/api/embed"
FALLBACK_DIM = 256

ALPHA = 0.2               # 80% central interval
HIDDEN = 256
LAYERS = 2
SEED = 20260821
EPOCHS = 400
LR = 3e-3
WEIGHT_DECAY = 1e-4
HOLDOUT_FRACTION = 0.25   # of the distinct STEPS, not of the rows


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# The frozen embedding
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def _hashed(text: str, dim: int = FALLBACK_DIM) -> list:
    """Deterministic fallback. Character n-grams into a fixed number of buckets.

    Not a good representation — it has no notion that `planet_snapshots` and
    `human_snapshots` are similar. That is the point: when it is used, the run
    record says so, and the numbers are read as the floor rather than the result.
    """
    vec = [0.0] * dim
    t = f"  {text}  "
    for n in (3, 4, 5):
        for i in range(len(t) - n + 1):
            g = t[i:i + n]
            h = int(hashlib.sha256(g.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts, model: str = EMBED_MODEL) -> tuple:
    """(matrix, source). Cached on disk by sha256(model|text). Never trained."""
    cache = _load_cache()
    out, source, fresh = [], "ollama:" + model, 0
    try:
        import requests
    except Exception:
        requests = None

    for text in texts:
        key = hashlib.sha256(f"{model}|{text}".encode("utf-8")).hexdigest()
        if key in cache:
            out.append(cache[key])
            continue
        vec = None
        if requests is not None:
            try:
                r = requests.post(EMBED_URL, timeout=120,
                                  json={"model": model, "input": text})
                r.raise_for_status()
                vec = r.json()["embeddings"][0]
                fresh += 1
            except Exception:
                vec = None
        if vec is None:
            source = "hashed_fallback"
            vec = _hashed(text)
        cache[key] = vec
        out.append(vec)

    if fresh:
        _save_cache(cache)
    # A run that fell back for even one text is a fallback run: mixing two
    # representations of different dimension cannot be trained at all, and
    # mixing two of the same dimension would be worse — silently incoherent.
    if source == "hashed_fallback":
        out = [_hashed(t) for t in texts]
    return np.asarray(out, dtype=np.float64), source


# ---------------------------------------------------------------------------
# The head
# ---------------------------------------------------------------------------

class IntervalHead:
    """MLP(2 x 256) -> (centre, log-halfwidth). Numpy, explicit gradients.

    No torch on this machine and none is wanted: the project runs free and
    local, and a two-layer head with an analytic gradient is 60 lines. Every
    derivative below is written out so it can be checked against the loss, and
    _selftest checks them numerically.
    """

    def __init__(self, dim: int, hidden: int = HIDDEN, seed: int = SEED):
        rng = np.random.default_rng(seed)
        def he(a, b):
            return rng.normal(0.0, math.sqrt(2.0 / a), size=(a, b))
        self.W1, self.b1 = he(dim, hidden), np.zeros(hidden)
        self.W2, self.b2 = he(hidden, hidden), np.zeros(hidden)
        self.W3, self.b3 = he(hidden, 2) * 0.01, np.zeros(2)
        # start wide rather than narrow: an interval that begins confident
        # spends its first epochs paying miss penalties instead of learning.
        self.b3[1] = 0.5
        self._adam = {}
        self.t = 0

    # -- forward ----------------------------------------------------------

    def forward(self, X):
        z1 = X @ self.W1 + self.b1
        a1 = np.maximum(z1, 0.0)
        z2 = a1 @ self.W2 + self.b2
        a2 = np.maximum(z2, 0.0)
        z3 = a2 @ self.W3 + self.b3
        return {"z1": z1, "a1": a1, "z2": z2, "a2": a2, "z3": z3}

    def predict(self, X):
        """(lo, hi). hi > lo ALWAYS — exp() cannot be negative."""
        z3 = self.forward(X)["z3"]
        c, s = z3[:, 0], z3[:, 1]
        h = np.exp(np.clip(s, -20.0, 20.0))
        return c - h, c + h

    # -- loss -------------------------------------------------------------

    @staticmethod
    def winkler(lo, hi, y, alpha: float = ALPHA):
        """The interval score. Lower is better; width always costs."""
        pen = 2.0 / alpha
        return ((hi - lo)
                + pen * np.maximum(0.0, lo - y)
                + pen * np.maximum(0.0, y - hi))

    def loss(self, X, y, alpha: float = ALPHA) -> float:
        lo, hi = self.predict(X)
        return float(np.mean(self.winkler(lo, hi, y, alpha)))

    # -- backward ---------------------------------------------------------

    def grads(self, X, y, alpha: float = ALPHA):
        n = X.shape[0]
        f = self.forward(X)
        c, s = f["z3"][:, 0], f["z3"][:, 1]
        h = np.exp(np.clip(s, -20.0, 20.0))
        lo, hi = c - h, c + h
        pen = 2.0 / alpha
        below = (y < lo).astype(np.float64)
        above = (y > hi).astype(np.float64)

        # dW/dc =  pen*1[below] - pen*1[above]
        # dW/ds =  2h - pen*h*(1[below] + 1[above])
        dz3 = np.empty_like(f["z3"])
        dz3[:, 0] = pen * (below - above) / n
        dz3[:, 1] = (2.0 * h - pen * h * (below + above)) / n

        gW3 = f["a2"].T @ dz3
        gb3 = dz3.sum(axis=0)
        da2 = dz3 @ self.W3.T
        dz2 = da2 * (f["z2"] > 0)
        gW2 = f["a1"].T @ dz2
        gb2 = dz2.sum(axis=0)
        da1 = dz2 @ self.W2.T
        dz1 = da1 * (f["z1"] > 0)
        gW1 = X.T @ dz1
        gb1 = dz1.sum(axis=0)
        return {"W1": gW1, "b1": gb1, "W2": gW2, "b2": gb2,
                "W3": gW3, "b3": gb3}

    # -- Adam -------------------------------------------------------------

    def step(self, g, lr: float = LR, wd: float = WEIGHT_DECAY):
        self.t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        for name, grad in g.items():
            p = getattr(self, name)
            if name.startswith("W"):
                grad = grad + wd * p
            m, v = self._adam.get(name, (np.zeros_like(p), np.zeros_like(p)))
            m = b1 * m + (1 - b1) * grad
            v = b2 * v + (1 - b2) * (grad ** 2)
            self._adam[name] = (m, v)
            mh = m / (1 - b1 ** self.t)
            vh = v / (1 - b2 ** self.t)
            setattr(self, name, p - lr * mh / (np.sqrt(vh) + eps))


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------

def dataset(target: str = "step_seconds") -> dict:
    """Grounded rows only. The provenance is re-checked here, not trusted."""
    from core import training_log as tl

    every = tl.rows(target=target, include_asserted=True)
    grounded = [r for r in every if tl.is_trainable(r)]
    excluded = len(every) - len(grounded)

    keys = [str(r["key"]) for r in grounded]
    y = np.log(np.asarray([max(float(r["value"]), 1e-3) for r in grounded]))
    # Two counts, because they answer two questions. The per-target one says
    # what THIS training set refused; the whole-log one says how much of the
    # record is model opinion at all — 0 and 386 are very different facts and
    # reporting only the first would flatter the log.
    return {"keys": keys, "y": y, "rows": grounded,
            "excluded_asserted": excluded,
            "excluded_asserted_whole_log": tl.stats()["excluded"],
            "target": target}


# ---------------------------------------------------------------------------
# PER-ROW FEATURES (21 August 2026)
# ---------------------------------------------------------------------------
#
# THE HONEST NEGATIVE THAT CAME BEFORE THIS. The head has so far seen ONE
# embedding per step NAME, so every row of `daily_analysis` had an identical
# input. Held out by whole step, it was being asked to predict the duration of a
# name it had never read, from the name alone. It lost to the flat baseline, and
# that result was correct: names carry nothing about how long a step will run.
#
# These are features that plausibly DO. Every one of them is available at
# prediction time — that is the test of whether a feature is real or is the
# answer in disguise:
#
#   step_ordinal        where in the cycle this step ran (1st, 17th, 52nd)
#   hour sin/cos        time of day on a circle, so 23:00 and 01:00 are near
#   prev1/2/3           this step's duration in the last three cycles
#   prev_count          how many of those three actually existed (0-3)
#   cycles_since_boot   how many cycles this log has seen before this one
#   ram_free_at_start   from the body sensorium — see the flag below
#
# ABSENT IS ZERO AND A FLAG, NEVER ZERO ALONE. A step running for the first
# time has no previous duration; writing 0 there without saying so would tell
# the head "this step took no time last cycle", which is a measurement, and a
# false one. So every may-be-missing feature ships with its own presence flag
# and the head can learn to ignore the value when the flag is 0.
#
# WHAT prev1/2/3 DOES TO THE HOLDOUT, SAID OUT LOUD. The split holds out whole
# STEPS, and its question was "can you predict a step you have never seen". With
# prev1/2/3 that question changes: for a held-out step the model still never
# trains on that step's targets, but it can read that step's own earlier
# durations as inputs. That is legitimate — it is exactly what production has,
# and the targets of held-out rows are never used in training — but it is a
# DIFFERENT question: "given a step's own recent history, can you bound its next
# run". Both are worth answering, so train() reports both arms and never quietly
# substitutes one for the other.
#
# ONLY STRICTLY EARLIER ROWS. prev1/2/3 are taken from rows whose timestamp is
# strictly before this one. A same-cycle or future row would be the target
# wearing a hat.

# Consecutive rows more than this far apart belong to different cycles.
# MEASURED, not chosen: on 628 grounded rows the sorted gap list steps from
# 4,343 s to 10,293 s with nothing in between, so any threshold in that gap
# gives the same 9 cycles over the six days of log. 2 h sits inside it and is
# comfortably above the longest single step ever recorded (2,710 s).
CYCLE_GAP_SEC = 7200

ROW_FEATURE_NAMES = (
    "step_ordinal",
    "hour_sin",
    "hour_cos",
    "prev1_log",
    "prev2_log",
    "prev3_log",
    "prev_count",
    "cycles_since_boot",
    "ram_free_gb_at_start",
    "has_prev",
    "has_ram",
)


def _cycle_of(rows) -> list:
    """Which cycle each row belongs to, by time gap. Rows must be ts-sorted."""
    out, cyc = [], 0
    prev_ts = None
    for r in rows:
        try:
            t = datetime.fromisoformat(r["ts"]).timestamp()
        except Exception:
            t = prev_ts if prev_ts is not None else 0.0
        if prev_ts is not None and (t - prev_ts) > CYCLE_GAP_SEC:
            cyc += 1
        out.append(cyc)
        prev_ts = t
    return out


def _ram_free_gb_at(ts_iso: str) -> float | None:
    """RAM free at the moment the step started, from the body sensorium.

    Returns None when there is no reading within an hour of the row — which, for
    every row currently in the training log, is the case: core/body_sensorium.py
    began recording on 21 Aug 2026 and the log starts on 16 Aug. The feature is
    wired and flagged absent rather than left out, so that it starts carrying
    information as soon as there is history behind it, without another edit.
    """
    try:
        from core.body_sensorium import _rows_since
        from datetime import timedelta
        t = datetime.fromisoformat(ts_iso)
        rows = _rows_since(t - timedelta(hours=1))
    except Exception:
        return None
    best, best_d = None, None
    for r in rows or []:
        try:
            d = abs((datetime.fromisoformat(r["ts"]) - t).total_seconds())
        except Exception:
            continue
        if r.get("ram_available_mb") is None:
            continue
        if best_d is None or d < best_d:
            best, best_d = r["ram_available_mb"] / 1024.0, d
    return best if (best_d is not None and best_d <= 3600) else None


def row_features(rows) -> tuple:
    """(F, names, coverage). One row of numbers per training row.

    `coverage` reports, per may-be-missing feature, on what fraction of rows it
    was actually present — because a feature that is absent everywhere is not a
    feature, and a table that does not say so implies it was.
    """
    ordered = sorted(range(len(rows)), key=lambda i: str(rows[i].get("ts") or ""))
    cycles = _cycle_of([rows[i] for i in ordered])
    cycle_of = {}
    ordinal = {}
    seen_in_cycle: dict = {}
    for pos, i in enumerate(ordered):
        c = cycles[pos]
        cycle_of[i] = c
        seen_in_cycle[c] = seen_in_cycle.get(c, 0) + 1
        ordinal[i] = seen_in_cycle[c]

    # Strictly-earlier durations of the SAME step.
    history: dict = {}
    prevs: dict = {}
    for i in ordered:
        key = str(rows[i]["key"])
        past = history.get(key, [])
        prevs[i] = list(past[-3:])[::-1]      # newest first
        history.setdefault(key, []).append(max(float(rows[i]["value"]), 1e-3))

    F, present_prev, present_ram = [], 0, 0
    for i in range(len(rows)):
        r = rows[i]
        try:
            t = datetime.fromisoformat(r["ts"])
            hour = t.hour + t.minute / 60.0
        except Exception:
            hour = 0.0
        p = prevs.get(i, [])
        p_log = [math.log(v) for v in p]
        while len(p_log) < 3:
            p_log.append(0.0)
        if p:
            present_prev += 1
        ram = _ram_free_gb_at(str(r.get("ts") or ""))
        if ram is not None:
            present_ram += 1
        F.append([
            float(ordinal.get(i, 0)),
            math.sin(2 * math.pi * hour / 24.0),
            math.cos(2 * math.pi * hour / 24.0),
            p_log[0], p_log[1], p_log[2],
            float(len(p)),
            float(cycle_of.get(i, 0)),
            float(ram if ram is not None else 0.0),
            1.0 if p else 0.0,
            1.0 if ram is not None else 0.0,
        ])
    n = max(len(rows), 1)
    coverage = {
        "prev_durations_present": round(present_prev / n, 3),
        "ram_free_present": round(present_ram / n, 3),
        "cycles_detected": (max(cycles) + 1) if cycles else 0,
    }
    return np.asarray(F, dtype=np.float64), list(ROW_FEATURE_NAMES), coverage


def split_by_step(keys, y, fraction: float = HOLDOUT_FRACTION, seed: int = SEED):
    """Hold out whole STEPS. A random row split would test memorisation."""
    steps = sorted(set(keys))
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(steps))
    n_hold = max(1, int(round(fraction * len(steps))))
    held = {steps[i] for i in order[:n_hold]}
    idx = np.arange(len(keys))
    train = np.asarray([i for i in idx if keys[i] not in held])
    val = np.asarray([i for i in idx if keys[i] in held])
    return train, val, sorted(held)


def coverage_and_width(lo, hi, y):
    """In SECONDS, so the numbers cannot hide behind the log scale."""
    inside = float(np.mean((y >= lo) & (y <= hi)))
    width = float(np.mean(np.exp(hi) - np.exp(lo)))
    return inside, width


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(epochs: int = EPOCHS, lr: float = LR, alpha: float = ALPHA,
          write: bool = True, verbose: bool = True,
          force_fallback: bool = False, row_feats: bool = False) -> dict:
    """One training run. `force_fallback` is the CONTROL: the same head on the
    same split with the semantic embedding replaced by a meaningless hash. If
    the real embedding is carrying information, it must beat this; if the two
    are indistinguishable, the frozen embedding is decoration.

    `row_feats` appends the per-row features (see ROW_FEATURE_NAMES) to the
    step embedding. Everything else — the split, the loss, the baseline, the
    epochs, the seed — is unchanged, because a new arm compared under a new
    protocol is not a comparison."""
    data = dataset()
    keys, y = data["keys"], data["y"]
    if len(keys) < 20:
        return {"error": f"only {len(keys)} grounded rows — not enough to train"}

    steps = sorted(set(keys))
    texts = [f"CORTEX cycle step: {s}" for s in steps]
    if force_fallback:
        E = np.asarray([_hashed(t) for t in texts], dtype=np.float64)
        source = "hashed_control"
    else:
        E, source = embed(texts)
    by_step = {s: E[i] for i, s in enumerate(steps)}
    X = np.asarray([by_step[k] for k in keys])

    row_cov, row_names = None, []
    if row_feats:
        F, row_names, row_cov = row_features(data["rows"])
        X = np.hstack([X, F])

    tr, va, held = split_by_step(keys, y)
    mu = X[tr].mean(axis=0)
    sd = X[tr].std(axis=0)
    sd[sd < 1e-8] = 1.0
    Xn = (X - mu) / sd

    head = IntervalHead(dim=Xn.shape[1])
    curve = []
    for epoch in range(1, epochs + 1):
        head.step(head.grads(Xn[tr], y[tr], alpha), lr=lr)
        if epoch == 1 or epoch % 20 == 0 or epoch == epochs:
            l_tr = head.loss(Xn[tr], y[tr], alpha)
            l_va = head.loss(Xn[va], y[va], alpha)
            lo_v, hi_v = head.predict(Xn[va])
            cov, wid = coverage_and_width(lo_v, hi_v, y[va])
            curve.append({"epoch": epoch, "train": round(l_tr, 4),
                          "heldout": round(l_va, 4),
                          "heldout_coverage": round(cov, 3),
                          "heldout_mean_width_sec": round(wid, 1)})
            if verbose:
                print(f"  epoch {epoch:>4}  train {l_tr:8.4f}  "
                      f"held-out {l_va:8.4f}  coverage {cov:5.1%}  "
                      f"mean width {wid:9.1f}s")

    lo_t, hi_t = head.predict(Xn[tr])
    lo_v, hi_v = head.predict(Xn[va])
    assert bool(np.all(hi_t > lo_t)) and bool(np.all(hi_v > lo_v))

    # The comparison that makes the curve mean something: one flat interval,
    # the best constant band the training set can offer.
    q_lo, q_hi = np.quantile(y[tr], [alpha / 2, 1 - alpha / 2])
    base_tr = float(np.mean(IntervalHead.winkler(q_lo, q_hi, y[tr], alpha)))
    base_va = float(np.mean(IntervalHead.winkler(q_lo, q_hi, y[va], alpha)))

    result = {
        "ts": _now(),
        "target": data["target"],
        "embedding": source,
        "embedding_dim": int(Xn.shape[1]),
        "architecture": f"frozen embedding -> {LAYERS} x {HIDDEN} ReLU -> "
                        f"(centre, log-halfwidth)",
        "alpha": alpha,
        "rows_total": len(keys),
        "rows_excluded_asserted": data["excluded_asserted"],
        "rows_excluded_asserted_whole_log": data["excluded_asserted_whole_log"],
        "row_features": row_names,
        "row_feature_coverage": row_cov,
        "steps_total": len(steps),
        "steps_heldout": held,
        "rows_train": int(len(tr)),
        "rows_heldout": int(len(va)),
        "epochs": epochs,
        "curve": curve,
        "final": {
            "train": round(head.loss(Xn[tr], y[tr], alpha), 4),
            "heldout": round(head.loss(Xn[va], y[va], alpha), 4),
            "train_coverage": round(coverage_and_width(lo_t, hi_t, y[tr])[0], 3),
            "heldout_coverage": round(coverage_and_width(lo_v, hi_v, y[va])[0], 3),
            "train_mean_width_sec": round(coverage_and_width(lo_t, hi_t, y[tr])[1], 1),
            "heldout_mean_width_sec": round(coverage_and_width(lo_v, hi_v, y[va])[1], 1),
        },
        "flat_baseline": {
            "what": f"the single best constant {1 - alpha:.0%} band over the "
                    f"training rows",
            "train": round(base_tr, 4),
            "heldout": round(base_va, 4),
        },
    }
    result["beats_flat_baseline_heldout"] = \
        result["final"]["heldout"] < result["flat_baseline"]["heldout"]

    if write:
        RUNS.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        CURVE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return result


def summary(result: dict) -> str:
    if result.get("error"):
        return f"interval head: {result['error']}"
    f, b = result["final"], result["flat_baseline"]
    first, last = result["curve"][0], result["curve"][-1]
    return (
        f"interval head [{result['embedding']}, dim {result['embedding_dim']}]: "
        f"{result['rows_train']} train / {result['rows_heldout']} held-out rows, "
        f"{len(result['steps_heldout'])} of {result['steps_total']} steps held out\n"
        f"  train Winkler   {first['train']:.4f} -> {last['train']:.4f}\n"
        f"  held-out        {first['heldout']:.4f} -> {last['heldout']:.4f}"
        f"   (flat baseline {b['heldout']:.4f} -> "
        f"{'BEATEN' if result['beats_flat_baseline_heldout'] else 'NOT beaten'})\n"
        f"  held-out coverage {f['heldout_coverage']:.0%} at "
        f"{1 - result['alpha']:.0%} nominal, mean width "
        f"{f['heldout_mean_width_sec']:.0f}s\n"
        f"  excluded as asserted: {result['rows_excluded_asserted']} rows for "
        f"this target, {result.get('rows_excluded_asserted_whole_log')} across "
        f"the whole training log")


# ---------------------------------------------------------------------------
# The four arms, under one protocol
# ---------------------------------------------------------------------------

ARMS = (
    ("A  names only, real embedding", dict(force_fallback=False, row_feats=False)),
    ("B  names only, hashed control", dict(force_fallback=True, row_feats=False)),
    ("C  names + row features, real", dict(force_fallback=False, row_feats=True)),
    ("D  names + row features, hash", dict(force_fallback=True, row_feats=True)),
)


def compare(write: bool = False) -> dict:
    """All four arms on the SAME split, loss, baseline, epochs and seed.

    One table, produced by one command, so that "the features helped" and "the
    features won" cannot be confused with each other by anybody reading a
    number out of context — including whoever wrote it.
    """
    rows, flat = [], None
    for label, kw in ARMS:
        r = train(write=write, verbose=False, **kw)
        if r.get("error"):
            rows.append({"arm": label, "error": r["error"]})
            continue
        flat = r["flat_baseline"]["heldout"]
        rows.append({
            "arm": label,
            "heldout": r["final"]["heldout"],
            "coverage": r["final"]["heldout_coverage"],
            "width_sec": r["final"]["heldout_mean_width_sec"],
            "beats_flat": r["beats_flat_baseline_heldout"],
            "embedding": r["embedding"],
            "row_feature_coverage": r.get("row_feature_coverage"),
        })
    return {"ts": _now(), "arms": rows, "flat_baseline_heldout": flat,
            "any_arm_beats_flat": any(x.get("beats_flat") for x in rows)}


def compare_table(result: dict) -> str:
    out = [f"{'arm':<34}{'heldout':>10}{'coverage':>10}{'width':>9}  verdict"]
    for r in result["arms"]:
        if r.get("error"):
            out.append(f"{r['arm']:<34}  ERROR {r['error']}")
            continue
        out.append(f"{r['arm']:<34}{r['heldout']:>10.4f}"
                   f"{r['coverage']:>9.0%}{r['width_sec']:>8.0f}s  "
                   f"{'BEATS flat' if r['beats_flat'] else 'LOSES to flat'}")
    out.append(f"{'FLAT BASELINE':<34}{result['flat_baseline_heldout']:>10.4f}")
    cov = next((r.get("row_feature_coverage") for r in result["arms"]
                if r.get("row_feature_coverage")), None)
    if cov:
        out.append("")
        out.append(f"row-feature coverage: prev durations present on "
                   f"{cov['prev_durations_present']:.0%} of rows, RAM-at-start on "
                   f"{cov['ram_free_present']:.0%}, "
                   f"{cov['cycles_detected']} cycles detected")
        if cov["ram_free_present"] == 0:
            out.append("  RAM-at-start is ABSENT on every row: the body "
                       "sensorium began recording on 21 Aug 2026 and this log "
                       "starts on 16 Aug. Wired and flagged, not dropped.")
    if not result["any_arm_beats_flat"]:
        out.append("")
        out.append("NO ARM BEATS THE FLAT BASELINE. Said plainly, and not tuned "
                   "until it does — that would be Goodhart on our own instrument.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/interval_head.py --selftest")
    ok = True
    checks = []
    rng = np.random.default_rng(1)

    # (1) An inverted interval is impossible, at any weights.
    #
    # The parameterisation gives lo = c - h and hi = c + h with h = exp(s) > 0,
    # so lo <= hi holds for EVERY weight vector, before training and after a
    # diverged one. Strict inequality can still be lost to floating point at
    # absurd scales — when |c| is ~1e15 times h, c-h and c+h round to the same
    # double. That is a property of doubles, not of the design, and it is
    # asserted here as what it is rather than papered over.
    head = IntervalHead(dim=16, seed=3)
    for name in ("W1", "W2", "W3", "b1", "b2", "b3"):
        p = getattr(head, name)
        setattr(head, name, rng.normal(0, 50, size=p.shape))
    lo, hi = head.predict(rng.normal(0, 3, size=(200, 16)))
    checks.append((f"never inverted, even at absurd weights "
                   f"({int(np.sum(hi < lo))} inversions)", bool(np.all(hi >= lo))))

    head2 = IntervalHead(dim=16, seed=3)
    lo2, hi2 = head2.predict(rng.normal(0, 1, size=(200, 16)))
    checks.append((f"strictly hi > lo at realistic weights "
                   f"({int(np.sum(hi2 <= lo2))} ties)", bool(np.all(hi2 > lo2))))

    # (2) The Winkler loss behaves the way the docstring claims.
    y = np.asarray([1.0])
    tight_hit = IntervalHead.winkler(np.array([0.9]), np.array([1.1]), y)[0]
    moderate_hit = IntervalHead.winkler(np.array([0.5]), np.array([1.5]), y)[0]
    huge_hit = IntervalHead.winkler(np.array([-5.0]), np.array([7.0]), y)[0]
    tight_miss = IntervalHead.winkler(np.array([2.0]), np.array([2.2]), y)[0]
    checks += [
        (f"a tight hit beats a looser hit ({tight_hit:.2f} < {moderate_hit:.2f})",
         tight_hit < moderate_hit),
        (f"a tight miss loses to a moderate hit "
         f"({tight_miss:.2f} > {moderate_hit:.2f})", tight_miss > moderate_hit),
        # This is the loss doing its job, not a bug: an interval 12 wide is
        # worth LESS than a 0.2-wide interval that misses by 1.0. Width is not a
        # free way to be right.
        (f"a huge hit is worse than a near miss "
         f"({huge_hit:.2f} > {tight_miss:.2f})", huge_hit > tight_miss),
        ("width always costs something",
         IntervalHead.winkler(np.array([0.99]), np.array([1.01]), y)[0] > 0),
    ]

    # (3) The gradients are the gradients — checked numerically, not asserted.
    #
    # The loss is PIECEWISE linear: it has kinks at y == lo, y == hi and at every
    # ReLU. A central difference that steps across a kink compares two different
    # linear pieces and disagrees with both. So a coordinate is only checked when
    # the ACTIVE SET is identical at both probe points; otherwise the derivative
    # genuinely does not exist there and checking it would be theatre.
    head = IntervalHead(dim=8, hidden=6, seed=7)
    X = rng.normal(0, 1, size=(24, 8))
    yv = rng.normal(0, 1, size=24)
    g = head.grads(X, yv)

    def _active(h):
        f = h.forward(X)
        c, s = f["z3"][:, 0], f["z3"][:, 1]
        hw = np.exp(np.clip(s, -20, 20))
        return (np.sign(f["z1"]).tobytes(), np.sign(f["z2"]).tobytes(),
                (yv < c - hw).tobytes(), (yv > c + hw).tobytes())

    worst, checked, skipped = 0.0, 0, 0
    for name in ("W1", "b1", "W2", "b2", "W3", "b3"):
        p = getattr(head, name)
        flat = p.ravel()
        gflat = g[name].ravel()
        for i in (0, len(flat) // 2, len(flat) - 1):
            eps = 1e-6
            old = flat[i]
            flat[i] = old + eps
            a_hi, l_hi = _active(head), head.loss(X, yv)
            flat[i] = old - eps
            a_lo, l_lo = _active(head), head.loss(X, yv)
            flat[i] = old
            if a_hi != a_lo:
                skipped += 1        # the kink is between the probes
                continue
            checked += 1
            worst = max(worst, abs((l_hi - l_lo) / (2 * eps) - gflat[i]))
    checks.append((f"analytic gradient matches numeric on {checked} coordinates "
                   f"({skipped} skipped at kinks, max diff {worst:.2e})",
                   checked >= 12 and worst < 1e-6))

    # (4) It actually learns something on a signal with a KNOWN answer.
    d = 12
    Xs = rng.normal(0, 1, size=(400, d))
    w = rng.normal(0, 1, size=d)
    ys = Xs @ w + rng.normal(0, 0.3, size=400)
    h2 = IntervalHead(dim=d, hidden=32, seed=5)
    before = h2.loss(Xs, ys)
    for _ in range(600):
        h2.step(h2.grads(Xs, ys), lr=5e-3)
    after = h2.loss(Xs, ys)
    lo2, hi2 = h2.predict(Xs)
    cov = float(np.mean((ys >= lo2) & (ys <= hi2)))
    checks += [
        (f"loss falls on a learnable signal ({before:.3f} -> {after:.3f})",
         after < before * 0.5),
        (f"and it covers roughly the nominal 80% ({cov:.0%})", 0.6 <= cov <= 0.95),
    ]

    # (5) NEGATIVE CONTROL: pure noise must NOT be learnable OUT OF SAMPLE.
    #
    # In-sample it certainly can be — this head memorises 400 noise points down
    # to a Winkler of 0.39 against a flat band of 3.58. That is precisely why the
    # real run holds out whole steps: an in-sample number here would prove
    # nothing except that the head has enough parameters, which we already know.
    Xn2 = rng.normal(0, 1, size=(500, d))
    yn = rng.normal(0, 1, size=500)
    h3 = IntervalHead(dim=d, hidden=32, seed=5)
    for _ in range(600):
        h3.step(h3.grads(Xn2[:400], yn[:400]), lr=5e-3)
    q_lo, q_hi = np.quantile(yn[:400], [ALPHA / 2, 1 - ALPHA / 2])
    flat_in = float(np.mean(IntervalHead.winkler(q_lo, q_hi, yn[:400])))
    flat_out = float(np.mean(IntervalHead.winkler(q_lo, q_hi, yn[400:])))
    got_in = h3.loss(Xn2[:400], yn[:400])
    got_out = h3.loss(Xn2[400:], yn[400:])
    checks += [
        (f"noise IS memorised in-sample ({got_in:.3f} vs flat {flat_in:.3f}) "
         f"— which is why the real split holds out whole steps",
         got_in < flat_in),
        (f"but on held-out noise it does NOT beat the flat band "
         f"({got_out:.3f} vs flat {flat_out:.3f})", got_out > flat_out),
    ]

    # (6) The split holds out whole steps, never half a step.
    keys = ["a"] * 10 + ["b"] * 10 + ["c"] * 10 + ["d"] * 10
    tr, va, held = split_by_step(keys, np.zeros(40))
    tr_steps = {keys[i] for i in tr}
    va_steps = {keys[i] for i in va}
    checks += [
        (f"held-out steps {held} appear in no training row",
         not (tr_steps & va_steps)),
        ("the held-out set is not empty", len(va) > 0),
    ]

    # (7) Asserted rows can never reach the dataset.
    from core import training_log as tl
    data = dataset()
    leaked = [r for r in data["rows"] if not tl.is_trainable(r)]
    checks.append((f"no asserted row is in the dataset ({len(leaked)} leaked)",
                   not leaked))
    print(f"\n  live dataset: {len(data['keys'])} grounded rows, "
          f"{len(set(data['keys']))} distinct steps, "
          f"{data['excluded_asserted']} excluded as asserted")

    print("  интеграции:")
    try:
        import requests
        r = requests.post(EMBED_URL, timeout=20,
                          json={"model": EMBED_MODEL, "input": "ping"})
        emb_live = r.ok
    except Exception:
        emb_live = False
    for name, alive in (("numpy", True),
                        (f"ollama embeddings ({EMBED_MODEL})", emb_live),
                        ("core.training_log", True),
                        ("memory/training_log.jsonl",
                         (BASE / "memory" / "training_log.jsonl").exists())):
        print(f"    {'LIVE  ' if alive else 'INERT '} {name}")

    print()
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--compare" in sys.argv:
        # All four arms, one protocol, one table. write=False by default: a
        # comparison is not a training run and must not append four rows to
        # memory/interval_head_runs.jsonl as though it were.
        print(compare_table(compare(write="--write" in sys.argv)))
        sys.exit(0)
    res = train()
    print()
    print(summary(res))
    if "--control" in sys.argv:
        print()
        print("  CONTROL — the same split, embedding replaced by a hash:")
        ctl = train(verbose=True, force_fallback=True)
        print()
        print(summary(ctl))
        real, hashed = res["final"]["heldout"], ctl["final"]["heldout"]
        print()
        print(f"  semantic {real:.4f} vs hashed {hashed:.4f} on held-out: "
              + ("the embedding carries signal" if real < hashed * 0.95
                 else "the embedding carries NO usable signal here"))
