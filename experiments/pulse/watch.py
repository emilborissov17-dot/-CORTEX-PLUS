#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/pulse/watch.py — a live window into the organism.

Reads the pulse sensory stream and the local brain's self_state AS THEY ARE
WRITTEN, and renders — live, in the moment — the organism's vital signs (body),
felt state (interoceptive valence), world sense (exteroception), and latest
thought (mind). Read-only: it opens only the experiment's own output files and
never writes anything. Ctrl+C to stop.

  python experiments/pulse/watch.py            # refresh ~1.5s
  python experiments/pulse/watch.py --once     # render a single frame and exit
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STREAM_DIR = HERE / "stream"
SELF_STATE = HERE / "self_state.jsonl"

RESET = "\033[0m"
def _c(code: str, s) -> str:
    return f"\033[{code}m{s}{RESET}"
BOLD, DIM = "1", "2"
GREEN, YELLOW, RED, CYAN, MAG, BLUE = "32", "33", "31", "36", "35", "34"


def _last_json_line(path: Path):
    try:
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    except Exception:
        return None
    return None


def _today_stream() -> Path:
    return STREAM_DIR / f"{datetime.now(timezone.utc).date().isoformat()}.jsonl"


def _age(ts) -> float | None:
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _bar(pct, width=26, warn=70.0, crit=90.0, good_high=False) -> str:
    """Horizontal bar. good_high=True colours HIGH values green (vitality);
    otherwise HIGH values go red (load, pain)."""
    try:
        v = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        return _c(DIM, "·" * width)
    fill = int(round(v / 100 * width))
    if good_high:
        col = RED if v < 100 - crit else (YELLOW if v < 100 - warn else GREEN)
    else:
        col = RED if v >= crit else (YELLOW if v >= warn else GREEN)
    return _c(col, "█" * fill) + _c(DIM, "░" * (width - fill))


def _fmt(v, suffix="", nd=1):
    if v is None:
        return _c(DIM, "—")
    if isinstance(v, float):
        return f"{v:.{nd}f}{suffix}"
    return f"{v}{suffix}"


def render() -> str:
    s = _last_json_line(_today_stream()) or {}
    mind = _last_json_line(SELF_STATE) or {}
    val = s.get("valence") or {}
    wld = s.get("world") or {}
    cyc = s.get("cycle") or {}
    net = s.get("net") or {}

    L = []
    now = datetime.now().strftime("%H:%M:%S")
    L.append(_c(BOLD, "  ╺━ CORTEX++ · ЖИВ ОРГАНИЗЪМ ━╸") + _c(DIM, f"     {now}"))

    # pulse liveness
    p_age = _age(s.get("ts"))
    if not s:
        L.append(_c(RED, "  ⚠ няма пулсов поток — pulse_daemon.py не върви?"))
    else:
        beat = _c(GREEN, "● alive") if (p_age is not None and p_age < 30) else _c(RED, f"○ stale ({_fmt(p_age,'s',0)})")
        L.append(_c(DIM, "  пулс: ") + beat + _c(DIM, f"   ({_fmt(p_age,'s',0)} ago)"))

    L.append("")
    L.append(_c(BOLD + ";" + CYAN, "  ТЯЛО") + _c(DIM, "  (субстрат)"))
    L.append(f"    cpu   {_bar(s.get('cpu_pct'))}  {_fmt(s.get('cpu_pct'),'%')}")
    L.append(f"    ram   {_bar(s.get('ram_pct'))}  {_fmt(s.get('ram_pct'),'%')}  "
             + _c(DIM, f"free {_fmt(s.get('ram_available_gb'),'GB')}"))
    where = _c(GREEN, f"cycle:{cyc.get('step')}") if cyc.get("running") else (
            _c(YELLOW, f"STALE {cyc.get('step')}") if cyc.get("stale_heartbeat") else _c(DIM, "idle"))
    L.append(f"    net   " + (_c(GREEN, "up") if net.get("reachable") else _c(RED, "DOWN"))
             + _c(DIM, f" {_fmt(net.get('latency_ms'),'ms')}") + f"   cycle {where}"
             + _c(DIM, f"   disk {_fmt(s.get('disk_free_gb'),'GB')}   churn {s.get('memory_files_changed','—')}"))

    L.append("")
    L.append(_c(BOLD + ";" + MAG, "  ДУХ/УСЕЩАНЕ") + _c(DIM, "  (интероцепция — felt state)"))
    if val.get("available"):
        pain = val.get("pain_score")
        vit = val.get("vitality")
        L.append(f"    pain     {_bar(pain, crit=100, warn=50)}  {_fmt(pain,'',0)}"
                 + _c(DIM, f"   ({val.get('pain_points','—')} points, urgency {val.get('mortality_urgency','—')})"))
        L.append(f"    vitality {_bar(vit, good_high=True)}  {_fmt(vit,'/100',0)}")
    else:
        L.append(_c(DIM, "    (felt-state файл още не е генериран — existence_latest.json)"))

    L.append("")
    L.append(_c(BOLD + ";" + BLUE, "  СВЯТ") + _c(DIM, "  (екстероцепция)"))
    if wld.get("available"):
        L.append(f"    разселени {_c(BOLD, _fmt(wld.get('displaced_millions'),'M',1))}   "
                 f"недохранени {_fmt(wld.get('undernourished_pct'),'%')}   "
                 f"живот {_fmt(wld.get('life_expectancy'),' г',1)}")
        L.append(f"    неравенство(gini) {_fmt(wld.get('inequality_gini'),'',1)}   "
                 f"върховенство на закона {_fmt(wld.get('rule_of_law'),'',2)}   "
                 f"AI статии {_c(BOLD, _fmt(wld.get('ai_papers'),'',0))}"
                 + _c(DIM, f"   {wld.get('sections_present','—')} sections"))
    else:
        L.append(_c(DIM, "    (world файл още не е генериран — global_indicators_latest.json)"))

    L.append("")
    L.append(_c(BOLD + ";" + GREEN, "  УМ") + _c(DIM, "  (последна мисъл на локалния мозък)"))
    if mind:
        m_age = _age(mind.get("ts") or mind.get("utc") or mind.get("timestamp"))
        L.append("    " + _c(BOLD, str(mind.get("state", "—"))[:100]))
        L.append(_c(DIM, "    changed: ") + str(mind.get("changed", "—"))[:100])
        anom = mind.get("anomaly")
        if anom:
            L.append(_c(RED, "    ⚠ anomaly: ") + str(anom)[:100])
        L.append(_c(DIM, f"    (мисъл преди {_fmt(m_age,'s',0)})"))
    else:
        L.append(_c(DIM, "    (мозъкът още не мисли — self_sense.py не върви, или няма модел)"))

    L.append("")
    L.append(_c(DIM, "  Ctrl+C за спиране"))
    return "\n".join(L)


def main():
    once = "--once" in sys.argv
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            sys.stdout.write(render() + "\n")
            sys.stdout.flush()
            if once:
                break
            time.sleep(1.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
