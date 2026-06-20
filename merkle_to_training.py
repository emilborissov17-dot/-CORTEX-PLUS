#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merkle_to_training.py
=====================
Converts Merkle archive cycles into JSONL fine-tuning data.

For each cortex_memory/archive/cycle_XXXXXX/:
  input  = mission + cycle metadata + compressed signals + essence excerpt
  output = decisions taken + measurable result (goal_score / improvement)

Output: cortex_memory/training/training_data.jsonl  (one JSON per line)

Idempotent — already-processed cycle dirs are tracked inside the JSONL
itself (via the "cycle_dir" metadata field).  Re-running is safe.

CLI:
  python merkle_to_training.py              # batch: all unprocessed cycles
  python merkle_to_training.py --latest     # only the newest cycle (runner mode)
  python merkle_to_training.py --stats      # file stats
"""

from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ARCHIVE_DIR  = Path("cortex_memory/archive")
TRAINING_DIR = Path("cortex_memory/training")
OUTPUT_FILE  = TRAINING_DIR / "training_data.jsonl"
ESSENCE_FILE = Path("cortex_memory/abstractions/essence.md")

MISSION = (
    "Мисия: Устойчива цивилизация. Човешко достойнство над печалба и власт. "
    "Разпръскване отвъд Земята. Прозрачен AGI в служба на човечеството."
)

# ≥ this many readings of the same metric → collapse to min/max/avg
_COLLAPSE_AT = 3


# ── file helpers ──────────────────────────────────────────────────────────────

def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── signal compression ────────────────────────────────────────────────────────

def _compress_signals(signals: list[dict]) -> str:
    """
    Group by category → metric, collapse repeated numeric readings,
    sample up to 2 text values with overflow count.
    """
    by_cat: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    cat_source: dict[str, dict[str, str]] = defaultdict(dict)

    for s in signals:
        cat    = s.get("category", "UNKNOWN")
        metric = s.get("metric", "unknown")
        value  = s.get("value")
        source = s.get("source", "")
        if value is not None:
            by_cat[cat][metric].append(value)
        if metric not in cat_source[cat] and source:
            cat_source[cat][metric] = source

    lines: list[str] = []
    for cat in sorted(by_cat):
        metrics   = by_cat[cat]
        n_signals = sum(len(v) for v in metrics.values())
        lines.append(f"\n{cat} ({n_signals} сигн.):")

        for metric in sorted(metrics):
            vals   = metrics[metric]
            source = cat_source[cat].get(metric, "")
            src    = f" [{source}]" if source else ""

            # Try numeric coercion
            nums: list[float] = []
            texts: list[str]  = []
            for v in vals:
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    texts.append(str(v))

            if nums and not texts:
                if len(nums) >= _COLLAPSE_AT:
                    mn, mx = min(nums), max(nums)
                    avg    = sum(nums) / len(nums)
                    lines.append(
                        f"  {metric}: {len(nums)} евент. ({mn:g}–{mx:g}, avg={avg:.3g}){src}"
                    )
                elif len(nums) == 1:
                    lines.append(f"  {metric}={nums[0]:g}{src}")
                else:
                    lines.append(
                        f"  {metric}: {' | '.join(f'{v:g}' for v in nums)}{src}"
                    )
            elif texts and not nums:
                sample = texts[:2]
                extra  = f" (+{len(texts)-2} още)" if len(texts) > 2 else ""
                quoted = " | ".join(f'"{t[:70]}"' for t in sample)
                lines.append(f"  {metric}: {quoted}{extra}{src}")
            elif nums and texts:
                # Mixed (rare): show both
                lines.append(
                    f"  {metric}: [{', '.join(f'{v:g}' for v in nums[:3])}] "
                    f"+ [{', '.join(texts[:2])}]{src}"
                )

    return "\n".join(lines) if lines else "  (няма сигнали)"


# ── essence excerpt ───────────────────────────────────────────────────────────

def _essence_excerpt() -> str:
    """
    Extract ТРЕНД ВЕКТОРИ + СЕБЕПРОФИЛ blocks from essence.md (≤12 lines).
    These are the system's own compressed self-knowledge.
    """
    if not ESSENCE_FILE.exists():
        return ""
    text     = ESSENCE_FILE.read_text(encoding="utf-8", errors="replace")
    lines    = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("## ТРЕНД ВЕКТОРИ") or line.startswith("## СЕБЕПРОФИЛ"):
            in_block = True
        elif line.startswith("## ВИЗИЯ") or line.startswith("## ЦЕЛИ") or line.startswith("## СИСТЕМА"):
            in_block = False
        if in_block and line.strip():
            lines.append(line)
        if len(lines) >= 12:
            break
    return "\n".join(lines)


# ── pair builder ──────────────────────────────────────────────────────────────

def build_pair(cycle_dir: Path) -> Optional[dict]:
    """
    Build one training pair from a cycle directory.
    Returns None if any of the three required files is missing or unreadable.
    """
    sig_data = _load(cycle_dir / "signals.json")
    dec_data = _load(cycle_dir / "decisions.json")
    res_data = _load(cycle_dir / "results.json")

    if not sig_data or not dec_data or not res_data:
        return None

    cycle_id  = sig_data.get("cycle_id", cycle_dir.name)
    timestamp = sig_data.get("timestamp", "")
    n_signals = sig_data.get("count", 0)
    signals   = sig_data.get("signals", [])

    # ── INPUT ─────────────────────────────────────────────────────────────────
    date_str = timestamp[:10] if timestamp else "?"
    header   = f"КОНТЕКСТ: цикъл {cycle_id} | {date_str} | {n_signals} сигнала"

    sig_block = _compress_signals(signals)
    ess_block = _essence_excerpt()

    input_parts = [MISSION, "", header, sig_block]
    if ess_block:
        input_parts += ["", "ЕСЕНЦИЯ:", ess_block]
    input_text = "\n".join(input_parts).strip()

    # ── OUTPUT ────────────────────────────────────────────────────────────────
    decisions = dec_data.get("decisions", [])
    if decisions:
        parts = []
        for d in decisions:
            if isinstance(d, dict):
                action   = d.get("action", "")
                priority = d.get("priority", "")
                label    = f"{action} (priority={priority})" if priority else action
                parts.append(label or str(d))
            else:
                parts.append(str(d))
        decisions_str = " | ".join(parts)
    else:
        decisions_str = "—"

    goal_score = res_data.get("goal_score")
    results    = res_data.get("results", [])

    imp_scores: list[float] = []
    for r in results:
        if isinstance(r, dict):
            for k in ("improvement_score", "score"):
                if k in r and r[k] is not None:
                    try:
                        imp_scores.append(float(r[k]))
                    except (ValueError, TypeError):
                        pass

    goal_str = f"goal_score={goal_score:.4f}" if goal_score is not None else "goal_score=?"
    if imp_scores:
        avg_imp  = sum(imp_scores) / len(imp_scores)
        goal_str += f" | improvement={avg_imp:.4f}"

    output_text = f"РЕШЕНИЕ: {decisions_str}\nРЕЗУЛТАТ: {goal_str}"

    return {
        "cycle_dir": cycle_dir.name,   # used for idempotency tracking
        "cycle_id":  cycle_id,
        "input":     input_text,
        "output":    output_text,
    }


# ── idempotency ───────────────────────────────────────────────────────────────

def _already_processed() -> set[str]:
    if not OUTPUT_FILE.exists():
        return set()
    done: set[str] = set()
    for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            cd = json.loads(line).get("cycle_dir", "")
            if cd:
                done.add(cd)
        except Exception:
            pass
    return done


def _write_pair(pair: dict) -> None:
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(pair, ensure_ascii=False) + "\n")


# ── public API ────────────────────────────────────────────────────────────────

def run_batch() -> dict:
    """
    Process all unprocessed cycle dirs in the archive.
    Safe to run repeatedly — already-processed cycles are skipped.

    Returns {"added": int, "skipped": int, "total_lines": int}
    """
    cycle_dirs = sorted(ARCHIVE_DIR.glob("cycle_??????"))
    done       = _already_processed()
    added = skipped = 0

    for cycle_dir in cycle_dirs:
        if cycle_dir.name in done:
            skipped += 1
            continue
        pair = build_pair(cycle_dir)
        if pair is None:
            skipped += 1
            continue
        _write_pair(pair)
        done.add(cycle_dir.name)
        added += 1
        print(f"  [TRAINING] +{cycle_dir.name}  ({pair['cycle_id']})")

    total = 0
    if OUTPUT_FILE.exists():
        total = sum(1 for l in OUTPUT_FILE.open(encoding="utf-8") if l.strip())

    return {"added": added, "skipped": skipped, "total_lines": total}


def append_latest_cycle() -> bool:
    """
    Process only the most recently created archive cycle.
    Called from fast_cycle_runner.py as Step 25 (after MerkleMemory commit).
    Returns True if a new pair was appended, False otherwise.
    """
    cycle_dirs = sorted(ARCHIVE_DIR.glob("cycle_??????"))
    if not cycle_dirs:
        return False

    latest = cycle_dirs[-1]
    if latest.name in _already_processed():
        return False

    pair = build_pair(latest)
    if pair is None:
        return False

    _write_pair(pair)
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_stats() -> None:
    if not OUTPUT_FILE.exists():
        print(f"  {OUTPUT_FILE} does not exist yet — run without flags to create it.")
        return
    text  = OUTPUT_FILE.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    size  = OUTPUT_FILE.stat().st_size / 1024
    print(f"  File  : {OUTPUT_FILE}")
    print(f"  Pairs : {len(lines)} training examples")
    print(f"  Size  : {size:.1f} KB")
    if lines:
        first = json.loads(lines[0])
        last  = json.loads(lines[-1])
        print(f"  First : {first.get('cycle_dir')} ({first.get('cycle_id')})")
        print(f"  Last  : {last.get('cycle_dir')} ({last.get('cycle_id')})")
        # Input / output preview for last pair
        print(f"\n  --- last input (first 300 chars) ---")
        print(f"  {last['input'][:300].replace(chr(10), chr(10)+'  ')}")
        print(f"\n  --- last output ---")
        print(f"  {last['output']}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Build JSONL training data from CORTEX++ Merkle archive"
    )
    parser.add_argument("--latest", action="store_true",
                        help="Append only the most recent cycle (fast_cycle_runner mode)")
    parser.add_argument("--stats",  action="store_true",
                        help="Show output file statistics and last pair preview")
    args = parser.parse_args()

    if args.stats:
        _print_stats()
        return

    if args.latest:
        ok = append_latest_cycle()
        status = f"appended to {OUTPUT_FILE}" if ok else "nothing new (already processed or archive empty)"
        print(f"[TRAINING] {status}")
        return

    # Default: batch all
    print(f"[TRAINING] Batch scan of {ARCHIVE_DIR} ...")
    summary = run_batch()
    print(
        f"[TRAINING] Done — added={summary['added']} | "
        f"skipped={summary['skipped']} | "
        f"total={summary['total_lines']} pairs in {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
