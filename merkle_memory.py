"""
merkle_memory.py — Merkle Tree архитектура за памет на CORTEX++

Три режима на достъп:
  FAST  — state.json + essence.md (~1000 токена) → зарежда се при всяка сесия
  MEDIUM — + trends + self_profile + последна седмица (~5000 токена)
  DEEP  — + конкретен цикъл от архива → верификация

Структура:
  cortex_memory/
  ├── state.json              ← root hash + STATE компресия
  ├── abstractions/
  │   ├── essence.md          ← компресия на компресиите
  │   ├── trends.json         ← тренд-вектори
  │   ├── self_profile.json   ← себеусещане
  │   └── hashes.json         ← Merkle хашове
  ├── middle/
  │   ├── week_001.json       ← компресия на ~100 цикъла
  │   └── hashes.json
  └── archive/
      ├── cycle_000001/
      │   ├── signals.json
      │   ├── decisions.json
      │   ├── results.json
      │   └── hash.txt
      └── merkle_root.txt

Интеграция в fast_cycle_runner.py:
    from merkle_memory import MerkleMemory
    self.merkle = MerkleMemory()
    # в края на run_cycle():
    await self.merkle.commit(
        cycle_id=cycle_id,
        signals=observations,
        decisions=proposals,
        results=patch_results + world_results,
        goal_score=goal_score,
    )
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.llm_text import refuse_llm_text   # task #29

log = logging.getLogger("MerkleMemory")

# ── пътища ───────────────────────────────────────────────────────────────────
BASE          = Path("cortex_memory")
ABSTRACTIONS  = BASE / "abstractions"
MIDDLE        = BASE / "middle"
ARCHIVE       = BASE / "archive"
STATE_FILE    = BASE / "state.json"
ESSENCE_FILE  = ABSTRACTIONS / "essence.md"
TRENDS_FILE   = ABSTRACTIONS / "trends.json"
PROFILE_FILE  = ABSTRACTIONS / "self_profile.json"
ABS_HASHES    = ABSTRACTIONS / "hashes.json"
MID_HASHES    = MIDDLE / "hashes.json"
MERKLE_ROOT   = ARCHIVE / "merkle_root.txt"
# Every root ever computed, one row per commit, each naming the root before it
# (25 Sep 2026). Appended, never rewritten: verify_root_chain() fails on a gap.
ROOTS_LOG     = Path("memory") / "merkle_roots.jsonl"

# SEAL v2 (25 Sep 2026). Until then hash.txt was sha256 of {cycle_id, ts,
# signals_count, goal_score} - four fields - so an archive whose signals,
# decisions or results were edited still verified. A v2 seal hashes the exact
# bytes of the three content files, the Merkle root before this cycle, and the
# writer (process + commit sha), and keeps the last two in seal.json so the
# hash can be recomputed. A cycle without seal.json is a v1 (legacy) seal.
SEAL_FILE     = "seal.json"
CONTENT_FILES = ("signals.json", "decisions.json", "results.json")

VISION_FILE   = Path("civilization_vision.txt")
GOAL_FILE     = Path("civilization_goal.txt")

CYCLES_PER_WEEK   = 100   # колко цикъла = 1 middle запис
MAX_MIDDLE_WEEKS  = 52    # пази 1 година middle history
ESSENCE_MAX_TOKENS = 900  # target размер на essence


_COMMIT_SHA: dict = {}


def writer_identity() -> dict:
    """Which process wrote the seal, and from which commit of this repo."""
    if "v" not in _COMMIT_SHA:
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                               timeout=10, cwd=str(Path(__file__).resolve().parent))
            _COMMIT_SHA["v"] = (r.stdout.strip() or None, None if r.returncode == 0
                                else (r.stderr.strip()[:200] or f"exit {r.returncode}"))
        except Exception as e:  # noqa: BLE001
            _COMMIT_SHA["v"] = (None, f"{type(e).__name__}: {e}")
    sha, err = _COMMIT_SHA["v"]
    w = {"pid": os.getpid(), "process": Path(sys.argv[0] or "?").name, "commit": sha}
    if err:
        w["commit_error"] = err
    return w


def seal_hash(cycle_dir: Path, prev_root, writer) -> str:
    """sha256 over the exact bytes of the content files, the previous root and the
    writer. Raises FileNotFoundError when a content file is gone."""
    h = hashlib.sha256()
    for name in CONTENT_FILES:
        b = (Path(cycle_dir) / name).read_bytes()
        h.update(name.encode("utf-8") + b"\0" + len(b).to_bytes(8, "big") + b)
    h.update(b"prev_root\0" + str(prev_root or "").encode("utf-8"))
    h.update(b"writer\0" + json.dumps(writer, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def verify_root_chain(path: Path | None = None) -> dict:
    """Every row's prev_root must be the previous row's root. A deleted, reordered
    or rewritten row breaks the chain; so does a row that does not parse."""
    p = Path(path or ROOTS_LOG)
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:
        return {"ok": False, "rows": 0, "broken_at": None, "why": f"{p} does not exist"}
    prev = None
    for i, line in enumerate(lines):
        try:
            row = json.loads(line)
        except Exception:
            return {"ok": False, "rows": len(lines), "broken_at": i, "why": "row does not parse"}
        if not row.get("root"):
            return {"ok": False, "rows": len(lines), "broken_at": i, "why": "row has no root"}
        if i > 0 and row.get("prev_root") != prev:
            return {"ok": False, "rows": len(lines), "broken_at": i,
                    "why": f"prev_root {str(row.get('prev_root'))[:12]} != previous root {str(prev)[:12]}"}
        prev = row["root"]
    return {"ok": True, "rows": len(lines), "broken_at": None, "why": ""}


class MerkleMemory:
    """
    Пълна Merkle-базирана памет за CORTEX++.
    Архивира всичко. Абстрахира нагоре. Верифицира надолу.
    """

    def __init__(self):
        for d in [BASE, ABSTRACTIONS, MIDDLE, ARCHIVE]:
            d.mkdir(parents=True, exist_ok=True)

        self._trends: dict = self._load_json(TRENDS_FILE, default={
            "co2_ppm": [], "kp_index": [], "earthquake_max": [],
            "refugees": [], "gbif_30d": [], "goal_score": [],
            "cycle_count": 0,
            "_trend_dates": {},
        })
        # Backfill _trend_dates if loading an older trends.json that lacks it
        if "_trend_dates" not in self._trends:
            self._trends["_trend_dates"] = {}
        self._profile: dict = self._load_json(PROFILE_FILE, default={
            "total_cycles": 0,
            "avg_goal_score": 0.0,
            "best_goal_score": 0.0,
            "sensor_reliability": {},
            "weak_domains": [],
            "strong_domains": [],
            "last_escalation": None,
            "known_gaps": [],
        })
        self._state: dict = self._load_json(STATE_FILE, default={
            "merkle_root": None,
            "last_cycle": None,
            "last_updated": None,
            "total_cycles": 0,
            "essence_summary": "",
        })

    # ── кой е следващият цикъл ────────────────────────────────────────────────

    @staticmethod
    def _archived_cycle_nums(archive: Path | None = None) -> list:
        """Номерата на цикъл-директориите, които НАИСТИНА са на диска."""
        root = archive or ARCHIVE
        out = []
        if not root.is_dir():
            return out
        for d in root.iterdir():
            if not d.is_dir() or not d.name.startswith("cycle_"):
                continue
            try:
                out.append(int(d.name[len("cycle_"):]))
            except ValueError:
                continue          # чуждо име в archive/ не е номер
        return sorted(out)

    def _next_cycle_num(self, archive: Path | None = None) -> int:
        """СЛЕДВАЩИЯТ номер идва от АРХИВА, не от брояч.

        ЗАЩО (3 сеп 2026). Беше `self._state["total_cycles"] + 1`. state.json е
        мутируем файл и беше нулиран на 28 авг: броячът се върна на 16, докато 56-те
        директории оцеляха. Резултатът не беше „грешен номер" — беше ЗАГУБА НА ДАННИ.
        Нощите на 1, 2 и 3 септ. презаписаха cycle_000017, 000018 и 000019, които
        съдържаха юлски цикли, и следващата нощ щеше да изяде cycle_000020 (29 юли).
        Архивът не може да бъде презаписан от число, което някой е нулирал: истината
        за това докъде сме стигнали е самият архив.

        max(existing) + 1, и НИКОГА по-малко от total_cycles + 1 — дупка в номерата
        (изтрита директория) не бива да върне брояча назад върху жива история.
        """
        nums = self._archived_cycle_nums(archive)
        from_disk = (max(nums) + 1) if nums else 1
        from_state = int(self._state.get("total_cycles", 0) or 0) + 1
        return max(from_disk, from_state)

    # ── main entry ────────────────────────────────────────────────────────────

    async def commit(
        self,
        cycle_id: str,
        signals: list,
        decisions: list,
        results: list,
        goal_score: float | None = 0.0,
    ):
        """Главна точка — извиква се в края на всеки цикъл.

        goal_score=None означава ЗАДЪРЖАН композит (19 септ 2026): покритието е
        под прага и goal_score_calculator отказва да публикува число. Тогава
        цикълът СЕ ЗАПЕЧАТВА — веригата е одит и мълчанието в нея е по-лошо от
        празен ред — но числото НЕ влиза нито в тренда, нито в средното, нито в
        рекорда. Нула на негово място би била измислена ниска оценка в
        собствената история на системата, тоест точно измаменото число, заради
        което композитът започна да отказва.
        """
        for _name, _v in (("cycle_id", cycle_id), ("signals", signals),
                          ("decisions", decisions), ("results", results),
                          ("goal_score", goal_score)):
            refuse_llm_text(_v, f"merkle_memory.commit {_name}")
        ts = datetime.now(timezone.utc).isoformat()
        prev_root = self._state.get("merkle_root")

        # 1. Архивирай цикъла
        cycle_num = self._next_cycle_num()
        cycle_hash = await self._archive_cycle(cycle_num, cycle_id, signals, decisions, results, goal_score, ts)

        # 2. Обнови тренд-вектори
        self._update_trends(signals, goal_score)

        # 3. Обнови себепрофила
        self._update_profile(signals, goal_score, cycle_num)

        # 4. Обнови middle layer ако е нужно
        if cycle_num % CYCLES_PER_WEEK == 0:
            await self._compress_to_middle(cycle_num)

        # 5. Изчисли нов Merkle root и го впиши в историята на корените
        new_root = self._compute_merkle_root()
        self._append_root(new_root, ts, cycle_id, cycle_num, prev_root)

        # 6. Обнови abstractions
        self._save_json(TRENDS_FILE, self._trends)
        self._save_json(PROFILE_FILE, self._profile)

        # 7. Генерирай essence — ПРЕДИ хашовете (3 сеп 2026).
        # Беше обратното: _update_abs_hashes() вземаше хаша на essence.md на ред 144,
        # а ред 148 презаписваше файла. Затова hashes.json["essence.md"] беше
        # СТРУКТУРНО невъзможно да съвпадне — той винаги беше хашът на вчерашния
        # essence. trends.json и self_profile.json съвпадаха, защото се пишат преди
        # хеширането; само essence.md се пишеше след него. Един ред разлика, но той
        # прави третината от abstractions непроверима.
        essence = self._generate_essence(cycle_id, goal_score, ts)
        ESSENCE_FILE.write_text(essence, encoding="utf-8")

        # 8. Хеширай ТРИТЕ файла, всеки в окончателния си вид
        self._update_abs_hashes()

        # 9. Запиши state (root на всичко)
        self._state.update({
            "merkle_root": new_root,
            "last_cycle": cycle_id,
            "last_updated": ts,
            "total_cycles": cycle_num,
            "essence_summary": essence[:500],
        })
        self._save_json(STATE_FILE, self._state)
        MERKLE_ROOT.write_text(new_root, encoding="utf-8")

        _g = f"{goal_score:.3f}" if goal_score is not None else "WITHHELD"
        log.info(f"MerkleMemory: cycle={cycle_num} | root={new_root[:12]}... | goal={_g}")

    # ── archive ───────────────────────────────────────────────────────────────

    async def _archive_cycle(
        self, cycle_num: int, cycle_id: str,
        signals: list, decisions: list, results: list,
        goal_score: float, ts: str,
    ) -> str:
        """Записва пълния цикъл в archive/cycle_XXXXXX/"""
        cycle_dir = ARCHIVE / f"cycle_{cycle_num:06d}"
        cycle_dir.mkdir(exist_ok=True)

        # Сериализирай сигналите
        signals_data = []
        for s in signals:
            if hasattr(s, "__dict__"):
                signals_data.append(s.__dict__)
            elif hasattr(s, "_asdict"):
                signals_data.append(s._asdict())
            else:
                signals_data.append(dict(s) if isinstance(s, dict) else str(s))

        self._save_json(cycle_dir / "signals.json", {
            "cycle_id": cycle_id,
            "timestamp": ts,
            "count": len(signals_data),
            "signals": signals_data,
        })
        self._save_json(cycle_dir / "decisions.json", {
            "cycle_id": cycle_id,
            "count": len(decisions),
            "decisions": decisions if isinstance(decisions, list) else [],
        })
        self._save_json(cycle_dir / "results.json", {
            "cycle_id": cycle_id,
            # null here MEANS withheld, and the flag beside it says so in a word
            # a reader cannot mistake for a missing key or a failed write.
            "goal_score": goal_score,
            "goal_withheld": goal_score is None,
            "count": len(results),
            "results": results if isinstance(results, list) else [],
        })

        # Хаш на СЪДЪРЖАНИЕТО на цикъла (seal v2, 25 Sep 2026): байтовете на
        # трите файла + предишния корен + кой го е записал.
        prev_root = self._state.get("merkle_root")
        writer = writer_identity()
        cycle_hash = seal_hash(cycle_dir, prev_root, writer)
        self._save_json(cycle_dir / SEAL_FILE, {
            "version": 2, "hash": cycle_hash, "prev_root": prev_root,
            "writer": writer, "files": list(CONTENT_FILES),
        })
        (cycle_dir / "hash.txt").write_text(cycle_hash, encoding="utf-8")

        return cycle_hash

    # ── middle compression ────────────────────────────────────────────────────

    async def _compress_to_middle(self, cycle_num: int):
        """Компресира последните CYCLES_PER_WEEK цикъла в един middle запис."""
        week_num = cycle_num // CYCLES_PER_WEEK
        start = cycle_num - CYCLES_PER_WEEK + 1

        summary = {
            "week": week_num,
            "cycles": f"{start}-{cycle_num}",
            "co2_avg": self._avg_last(self._trends["co2_ppm"], CYCLES_PER_WEEK),
            "goal_avg": self._avg_last(self._trends["goal_score"], CYCLES_PER_WEEK),
            "earthquake_max": max(self._trends["earthquake_max"][-CYCLES_PER_WEEK:], default=0),
            "refugees_last": self._trends["refugees"][-1] if self._trends["refugees"] else None,
            "gbif_last": self._trends["gbif_30d"][-1] if self._trends["gbif_30d"] else None,
            "profile_snapshot": {
                "avg_goal_score": self._profile.get("avg_goal_score", 0.0),
                "weak_domains": self._profile.get("weak_domains", []),
                "known_gaps": self._profile.get("known_gaps", []),
            },
        }

        week_file = MIDDLE / f"week_{week_num:03d}.json"
        self._save_json(week_file, summary)

        # Обнови middle hashes
        mid_hashes = self._load_json(MID_HASHES, default={})
        mid_hashes[f"week_{week_num:03d}"] = self._sha256(json.dumps(summary, sort_keys=True))
        self._save_json(MID_HASHES, mid_hashes)

        # Почисти стари middle файлове
        weeks = sorted(MIDDLE.glob("week_*.json"))
        if len(weeks) > MAX_MIDDLE_WEEKS:
            for old in weeks[:-MAX_MIDDLE_WEEKS]:
                old.unlink()

        log.info(f"MerkleMemory: middle week_{week_num:03d} записан")

    # ── trends ────────────────────────────────────────────────────────────────

    def _update_trends(self, signals: list, goal_score: float):
        from datetime import date as _date
        today = _date.today().isoformat()
        dates = self._trends["_trend_dates"]

        self._trends["cycle_count"] += 1

        # goal_score — date-keyed: overwrite same-day, append new day.
        # A WITHHELD COMPOSITE LEAVES NO ROW. There is no goal score for this
        # cycle, so the series must not gain a point; a 0.0 here would read
        # forever after as "the world scored zero that day" and would drag every
        # average and every forecast baseline computed from this series.
        if goal_score is None:
            log.info("MerkleMemory: goal composite WITHHELD — no trend row written")
        elif dates.get("goal_score") == today and self._trends["goal_score"]:
            self._trends["goal_score"][-1] = round(goal_score, 4)
        else:
            self._trends["goal_score"].append(round(goal_score, 4))
            dates["goal_score"] = today

        by_metric = defaultdict(list)
        for s in signals:
            metric = s.metric if hasattr(s, "metric") else s.get("metric", "")
            value  = s.value  if hasattr(s, "value")  else s.get("value")
            if isinstance(value, (int, float)):
                by_metric[metric].append(value)

        def _append_dated(key, metric):
            """Append metric average to trend list, but overwrite if same day."""
            vals = by_metric.get(metric, [])
            if not vals:
                return
            new_val = round(sum(vals) / len(vals), 4)
            if dates.get(key) == today and self._trends[key]:
                self._trends[key][-1] = new_val
            else:
                self._trends[key].append(new_val)
                dates[key] = today
            if len(self._trends[key]) > 5000:
                self._trends[key] = self._trends[key][-5000:]

        _append_dated("co2_ppm", "co2_ppm")
        _append_dated("kp_index", "kp_index")
        _append_dated("refugees", "total_refugees")
        _append_dated("gbif_30d", "species_observations_30d")

        mags = by_metric.get("earthquake_magnitude", [])
        if mags:
            new_max = round(max(mags), 4)
            if dates.get("earthquake_max") == today and self._trends["earthquake_max"]:
                self._trends["earthquake_max"][-1] = new_max
            else:
                self._trends["earthquake_max"].append(new_max)
                dates["earthquake_max"] = today
            if len(self._trends["earthquake_max"]) > 5000:
                self._trends["earthquake_max"] = self._trends["earthquake_max"][-5000:]

    # ── self profile ──────────────────────────────────────────────────────────

    def _update_profile(self, signals: list, goal_score: float, cycle_num: int):
        p = self._profile
        p["total_cycles"] = cycle_num

        # Rolling avg goal score. Withheld means the cycle contributes NOTHING
        # to it — not zero. The count of cycles that did contribute is kept
        # separately, because a rolling average whose denominator silently
        # includes cycles that had no number is not an average of anything.
        n = cycle_num
        if goal_score is None:
            p["goal_withheld_cycles"] = int(p.get("goal_withheld_cycles", 0)) + 1
        else:
            k = int(p.get("goal_scored_cycles", max(0, n - 1))) + 1
            p["avg_goal_score"] = round(
                (p.get("avg_goal_score", 0.0) * (k - 1) + goal_score) / k, 4
            )
            p["goal_scored_cycles"] = k
            if goal_score > p.get("best_goal_score", 0.0):
                p["best_goal_score"] = round(goal_score, 4)

        # Sensor reliability — брой сигнали по source
        source_counts: dict = p.get("sensor_reliability", {})
        for s in signals:
            src = s.source if hasattr(s, "source") else s.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        p["sensor_reliability"] = source_counts

        # Слаби домейни — домейни с малко сигнали
        domain_counts: dict[str, int] = defaultdict(int)
        for s in signals:
            dom = s.domain if hasattr(s, "domain") else s.get("domain", "unknown")
            domain_counts[dom] += 1

        avg_signals = len(signals) / max(len(domain_counts), 1)
        p["weak_domains"]   = [d for d, c in domain_counts.items() if c < avg_signals * 0.5]
        p["strong_domains"] = [d for d, c in domain_counts.items() if c >= avg_signals * 1.5]

        self._profile = p

    # ── Merkle root ───────────────────────────────────────────────────────────

    @staticmethod
    def _leaf_hashes() -> list:
        hashes = []
        for cycle_dir in sorted(ARCHIVE.glob("cycle_*")):
            hash_file = cycle_dir / "hash.txt"
            if hash_file.exists():
                hashes.append(hash_file.read_text().strip())
        return hashes

    def _append_root(self, root: str, ts: str, cycle_id: str, cycle_num: int,
                     prev_root) -> dict:
        """One row in ROOTS_LOG. prev_root is the last row's root when the log has
        one - the chain is the log's own - else the state's root before this
        commit (the first row of a new log)."""
        last = None
        try:
            lines = [l for l in ROOTS_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
            last = json.loads(lines[-1]).get("root") if lines else None
        except FileNotFoundError:
            pass
        row = {"root": root, "ts": ts, "cycle_id": cycle_id, "cycle_num": cycle_num,
               "leaf_count": len(self._leaf_hashes()),
               "prev_root": last if last is not None else prev_root}
        ROOTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ROOTS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return row

    def _compute_merkle_root(self) -> str:
        """Изчислява Merkle root от всички archive хашове."""
        hashes = self._leaf_hashes()

        if not hashes:
            return self._sha256("empty")

        # Bottom-up Merkle
        while len(hashes) > 1:
            next_level = []
            for i in range(0, len(hashes), 2):
                left = hashes[i]
                right = hashes[i + 1] if i + 1 < len(hashes) else left
                next_level.append(self._sha256(left + right))
            hashes = next_level

        return hashes[0]

    def _update_abs_hashes(self):
        hashes = {}
        for f in [TRENDS_FILE, PROFILE_FILE, ESSENCE_FILE]:
            if f.exists():
                hashes[f.name] = self._sha256(f.read_text(encoding="utf-8"))
        self._save_json(ABS_HASHES, hashes)

    # ── essence generator ─────────────────────────────────────────────────────

    def _generate_essence(self, cycle_id: str, goal_score: float, ts: str) -> str:
        """Генерира essence.md — компресия на всичко (~900 токена)."""
        p = self._profile
        t = self._trends
        ts_short = ts[:16].replace("T", " ")

        def _trend_line(series: list, name: str, unit: str = "") -> str:
            if len(series) < 2:
                return f"- {name}: {series[-1] if series else 'N/A'}{unit}"
            delta = series[-1] - series[-2]
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            return f"- {name}: {series[-1]}{unit} {arrow} (Δ{delta:+.3f})"

        lines = [
            "# CORTEX STATE ESSENCE",
            f"> {ts_short} | цикъл: {cycle_id} | goal: "
            + (f"{goal_score:.3f}" if goal_score is not None
               else "ЗАДЪРЖАН (покритието под прага)"),
            "",
            "## СИСТЕМА",
            f"- Цикли: {p['total_cycles']} | avg goal: {p['avg_goal_score']:.3f} | best: {p['best_goal_score']:.3f}",
            f"- Merkle root: `{self._state.get('merkle_root', 'N/A')}`",
            "",
            "## ТРЕНД ВЕКТОРИ",
        ]

        if t["co2_ppm"]:       lines.append(_trend_line(t["co2_ppm"], "CO₂", " ppm"))
        if t["earthquake_max"]:lines.append(_trend_line(t["earthquake_max"], "Earthquake max M"))
        if t["kp_index"]:      lines.append(_trend_line(t["kp_index"], "Kp index"))
        if t["refugees"]:      lines.append(_trend_line(t["refugees"], "Бежанци"))
        if t["gbif_30d"]:      lines.append(_trend_line(t["gbif_30d"], "GBIF obs/30d"))
        if t["goal_score"]:    lines.append(_trend_line(t["goal_score"], "Goal score"))

        lines += [
            "",
            "## СЕБЕПРОФИЛ",
            f"- Силни домейни: {', '.join(p['strong_domains']) or 'N/A'}",
            f"- Слаби домейни: {', '.join(p['weak_domains']) or 'none'}",
            f"- Известни дупки: {', '.join(p.get('known_gaps', [])) or 'none'}",
            "",
            "## ВИЗИЯ (константа)",
            "Устойчива общочовешка цивилизация. Човешко достойнство над печалба и власт.",
            "Ресурсно базиран модел. Разпръскване отвъд Земята. Прозрачен AGI.",
            "",
            "## ЦЕЛИ",
            "1. Устойчиви ресурси  2. Здрави среди  3. Устойчива цивилизация",
            "4. Знание и разбиране  5. Безопасност (предпочитай обратими стратегии)",
        ]

        return "\n".join(lines)

    # ── verification ──────────────────────────────────────────────────────────

    def verify_cycle(self, cycle_num: int) -> dict:
        """Верифицира integrity на конкретен цикъл."""
        cycle_dir = ARCHIVE / f"cycle_{cycle_num:06d}"
        if not cycle_dir.exists():
            return {"ok": False, "error": "цикълът не съществува"}

        hash_file = cycle_dir / "hash.txt"
        if not hash_file.exists():
            return {"ok": False, "error": "липсва hash.txt"}

        stored_hash = hash_file.read_text().strip()
        seal_file = cycle_dir / SEAL_FILE
        if seal_file.exists():
            seal = self._load_json(seal_file, default={})
            try:
                recomputed = seal_hash(cycle_dir, seal.get("prev_root"), seal.get("writer"))
            except FileNotFoundError as e:
                return {"ok": False, "cycle": cycle_num, "version": 2,
                        "error": f"content file missing: {Path(str(e.filename)).name}"}
            ok = stored_hash == recomputed == seal.get("hash")
            return {
                "ok": ok, "cycle": cycle_num, "version": 2,
                "stored_hash": stored_hash[:16] + "...",
                "recomputed": recomputed[:16] + "...",
                "signals": self._load_json(cycle_dir / "signals.json", {}).get("count", 0),
            }
        signals_file = cycle_dir / "signals.json"
        if not signals_file.exists():
            return {"ok": False, "error": "липсва signals.json"}

        data = self._load_json(signals_file, default={})
        recomputed = self._sha256(json.dumps({
            "cycle_id": data.get("cycle_id"),
            "ts": data.get("timestamp"),
            "signals_count": data.get("count"),
            "goal_score": self._load_json(cycle_dir / "results.json", {}).get("goal_score"),
        }, sort_keys=True))

        ok = stored_hash == recomputed
        return {
            "ok": ok,
            "cycle": cycle_num,
            "version": 1,
            "covers": "cycle_id, ts, signals count, goal_score only (legacy seal)",
            "stored_hash": stored_hash[:16] + "...",
            "recomputed": recomputed[:16] + "...",
            "signals": data.get("count", 0),
        }

    def load_fast(self) -> str:
        """FAST режим — връща essence за context window."""
        if ESSENCE_FILE.exists():
            return ESSENCE_FILE.read_text(encoding="utf-8")
        return "# CORTEX STATE\n> Няма данни още.\n"

    def load_medium(self) -> dict:
        """MEDIUM режим — essence + trends + profile + последна седмица."""
        result = {
            "essence": self.load_fast(),
            "trends": self._load_json(TRENDS_FILE, {}),
            "profile": self._load_json(PROFILE_FILE, {}),
            "last_week": None,
        }
        weeks = sorted(MIDDLE.glob("week_*.json"))
        if weeks:
            result["last_week"] = self._load_json(weeks[-1], {})
        return result

    # ── utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _avg_last(series: list, n: int) -> float | None:
        chunk = series[-n:] if series else []
        return round(sum(chunk) / len(chunk), 4) if chunk else None

    @staticmethod
    def _load_json(path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default if default is not None else {}

    @staticmethod
    def _save_json(path: Path, data: Any):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    from dataclasses import dataclass
    from typing import Any as _Any

    @dataclass
    class FakeSig:
        source: str; category: str; domain: str
        metric: str; value: _Any; delta: float | None
        timestamp: str; raw: dict

    fake_signals = [
        FakeSig("NOAA", "EARTH_HEALTH", "atmosphere", "co2_ppm", 432.44, None, "2026-05-09", {}),
        FakeSig("USGS", "THREATS", "geological", "earthquake_magnitude", 5.8, None, "2026-05-09", {}),
        FakeSig("USGS", "THREATS", "geological", "earthquake_magnitude", 4.2, None, "2026-05-09", {}),
        FakeSig("UNHCR", "HUMAN_HEALTH", "displacement", "total_refugees", 43_400_000, None, "2026-05-09", {}),
        FakeSig("arXiv", "PROGRESS", "ai", "arxiv_paper", "UniPool MoE", None, "2026-05-09", {}),
        FakeSig("GBIF", "EARTH_HEALTH", "biodiversity", "species_observations_30d", 4_933_538, None, "2026-05-09", {}),
        FakeSig("NOAA SWPC", "EARTH_HEALTH", "solar", "kp_index", 2.67, None, "2026-05-09", {}),
    ]

    async def test():
        mm = MerkleMemory()

        # Симулирай 3 цикъла
        for i in range(1, 4):
            await mm.commit(
                cycle_id=f"cycle_test_{i}",
                signals=fake_signals,
                decisions=[{"action": "monitor", "priority": "HIGH"}],
                results=[{"improvement_score": 0.7 + i * 0.05}],
                goal_score=0.7 + i * 0.05,
            )
            print(f"\n--- Цикъл {i} ---")

        print("\n" + "="*60)
        print("ESSENCE (FAST режим):")
        print("="*60)
        print(mm.load_fast())

        print("\n" + "="*60)
        print("ВЕРИФИКАЦИЯ цикъл 2:")
        print("="*60)
        print(mm.verify_cycle(2))

        print(f"\nMerkle root: {(ARCHIVE / 'merkle_root.txt').read_text()[:32]}...")

    asyncio.run(test())