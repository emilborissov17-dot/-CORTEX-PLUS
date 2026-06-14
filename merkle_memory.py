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
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

VISION_FILE   = Path("civilization_vision.txt")
GOAL_FILE     = Path("civilization_goal.txt")

CYCLES_PER_WEEK   = 100   # колко цикъла = 1 middle запис
MAX_MIDDLE_WEEKS  = 52    # пази 1 година middle history
ESSENCE_MAX_TOKENS = 900  # target размер на essence


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
        })
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

    # ── main entry ────────────────────────────────────────────────────────────

    async def commit(
        self,
        cycle_id: str,
        signals: list,
        decisions: list,
        results: list,
        goal_score: float = 0.0,
    ):
        """Главна точка — извиква се в края на всеки цикъл."""
        ts = datetime.now(timezone.utc).isoformat()

        # 1. Архивирай цикъла
        cycle_num = self._state.get("total_cycles", 0) + 1
        cycle_hash = await self._archive_cycle(cycle_num, cycle_id, signals, decisions, results, goal_score, ts)

        # 2. Обнови тренд-вектори
        self._update_trends(signals, goal_score)

        # 3. Обнови себепрофила
        self._update_profile(signals, goal_score, cycle_num)

        # 4. Обнови middle layer ако е нужно
        if cycle_num % CYCLES_PER_WEEK == 0:
            await self._compress_to_middle(cycle_num)

        # 5. Изчисли нов Merkle root
        new_root = self._compute_merkle_root()

        # 6. Обнови abstractions
        self._save_json(TRENDS_FILE, self._trends)
        self._save_json(PROFILE_FILE, self._profile)
        self._update_abs_hashes()

        # 7. Генерирай essence
        essence = self._generate_essence(cycle_id, goal_score, ts)
        ESSENCE_FILE.write_text(essence, encoding="utf-8")

        # 8. Запиши state (root на всичко)
        self._state.update({
            "merkle_root": new_root,
            "last_cycle": cycle_id,
            "last_updated": ts,
            "total_cycles": cycle_num,
            "essence_summary": essence[:500],
        })
        self._save_json(STATE_FILE, self._state)
        MERKLE_ROOT.write_text(new_root, encoding="utf-8")

        log.info(f"MerkleMemory: cycle={cycle_num} | root={new_root[:12]}... | goal={goal_score:.3f}")

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
            "goal_score": goal_score,
            "count": len(results),
            "results": results if isinstance(results, list) else [],
        })

        # Хаш на целия цикъл
        cycle_content = json.dumps({
            "cycle_id": cycle_id,
            "ts": ts,
            "signals_count": len(signals_data),
            "goal_score": goal_score,
        }, sort_keys=True)
        cycle_hash = self._sha256(cycle_content)
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
        self._trends["cycle_count"] += 1
        self._trends["goal_score"].append(round(goal_score, 4))

        by_metric = defaultdict(list)
        for s in signals:
            metric = s.metric if hasattr(s, "metric") else s.get("metric", "")
            value  = s.value  if hasattr(s, "value")  else s.get("value")
            if isinstance(value, (int, float)):
                by_metric[metric].append(value)

        def _append(key, metric):
            vals = by_metric.get(metric, [])
            if vals:
                self._trends[key].append(round(sum(vals) / len(vals), 4))
                if len(self._trends[key]) > 5000:
                    self._trends[key] = self._trends[key][-5000:]

        _append("co2_ppm", "co2_ppm")
        _append("kp_index", "kp_index")
        _append("refugees", "total_refugees")
        _append("gbif_30d", "species_observations_30d")

        mags = by_metric.get("earthquake_magnitude", [])
        if mags:
            self._trends["earthquake_max"].append(round(max(mags), 4))
            if len(self._trends["earthquake_max"]) > 5000:
                self._trends["earthquake_max"] = self._trends["earthquake_max"][-5000:]

    # ── self profile ──────────────────────────────────────────────────────────

    def _update_profile(self, signals: list, goal_score: float, cycle_num: int):
        p = self._profile
        p["total_cycles"] = cycle_num

        # Rolling avg goal score
        n = cycle_num
        p["avg_goal_score"] = round(
            (p.get("avg_goal_score", 0.0) * (n - 1) + goal_score) / n, 4
        )
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

    def _compute_merkle_root(self) -> str:
        """Изчислява Merkle root от всички archive хашове."""
        hashes = []
        for cycle_dir in sorted(ARCHIVE.glob("cycle_*")):
            hash_file = cycle_dir / "hash.txt"
            if hash_file.exists():
                hashes.append(hash_file.read_text().strip())

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
            f"> {ts_short} | цикъл: {cycle_id} | goal: {goal_score:.3f}",
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