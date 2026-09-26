#!/usr/bin/env python3
"""
edges_runner.py — the LLM half of a cycle, run AFTER the spine (task #8 step B).

The spine (fast_cycle_runner.py) measures, scores and publishes without calling a
model. Everything that asks a model about the night happens here, afterwards, in
its own process with its own witness rows (cycle_id shared with the spine, role
"edges"). A failure here never changes the spine's exit code.

B.A (25 Sep 2026): the phase jobs. For every phase report the spine wrote under
memory/phase_reports/<cycle>/ - in phase order - the brain's debrief
(core/phase_debrief), the cockpit's one line (cockpit/phase_voice) and the phase's
Telegram message. These three used to run inside phase_tracker at each phase
boundary; there they made every spine step reach the LLM stack.

    venv\\Scripts\\python.exe edges_runner.py --cycle-id <id>
    venv\\Scripts\\python.exe edges_runner.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

PHASE_ORDER = ("A_ORIENT", "B_SENSE", "C_SNAPSHOT", "D_SCORE", "E_PROPOSE", "F_SELF", "G_LEARN")


def _must_cite(phase: str) -> set:
    """G_LEARN, and only G_LEARN, owes the mirror two numbers (moved here from
    core/phase_tracker with the debrief; core.interoception reaches the brain)."""
    if phase != "G_LEARN":
        return set()
    try:
        from core.interoception import must_cite
        return must_cite()
    except Exception:
        return set()


def _reports(cycle_id: str, base: Path = BASE) -> list:
    from core.phase_report import safe_cycle_dir
    d = base / "memory" / "phase_reports" / safe_cycle_dir(cycle_id)
    out = []
    for phase in PHASE_ORDER:
        p = d / f"{phase}.json"
        if p.exists():
            try:
                out.append((phase, json.loads(p.read_text(encoding="utf-8"))))
            except Exception as exc:  # noqa: BLE001
                print(f"[EDGES] {phase}: report unreadable ({type(exc).__name__}: {exc})")
    return out


def phase_jobs(cycle_id: str, base: Path = BASE, debrief=None, voice=None, send=None) -> list:
    """Debrief, voice and message for every phase the spine closed. Each job is
    fail-open on its own; returns one record per phase. The three callables are
    seams for tests; by default they are the real producers."""
    from core import phase_tracker as pt
    if debrief is None:
        from core.phase_debrief import debrief_phase as debrief
    if voice is None:
        from cockpit.phase_voice import on_phase_close as voice
    if send is None:
        import supervisor
        send = supervisor.send_phase_debrief
    done = []
    for phase, result in _reports(cycle_id, base):
        rec = {"phase": phase, "debrief": None, "voice": None, "sent": False}
        d = None
        try:
            d = debrief(phase, str(cycle_id), pt._evidence(phase),
                        own_numbers=pt._own_numbers(phase), must_cite=_must_cite(phase))
            rec["debrief"] = "accepted" if (d or {}).get("accepted") else "rejected"
        except Exception as exc:  # noqa: BLE001
            print(f"[EDGES] {phase}: debrief failed ({type(exc).__name__}: {exc})")
        try:
            said = voice(phase, str(cycle_id), result, d) or {}
            rec["voice"] = said.get("text") if said.get("emitted") else None
        except Exception as exc:  # noqa: BLE001
            print(f"[EDGES] {phase}: voice failed ({type(exc).__name__}: {exc})")
        try:
            if d and d.get("accepted"):
                text = d["telegram"]
            else:
                why = "; ".join((d or {}).get("rejected_because", [])) or "no debrief"
                text = (f"CORTEX++ · фаза {phase} · {result.get('verdict')}\n"
                        f"{str(result.get('reason'))[:300]}\n"
                        f"(дебрифът е отхвърлен: {why[:160]})")
            send(phase, str(cycle_id), text, trigger=pt._trigger())
            rec["sent"] = True
        except Exception as exc:  # noqa: BLE001
            print(f"[EDGES] {phase}: telegram failed ({type(exc).__name__}: {exc})")
        print(f"[EDGES] {phase}: debrief={rec['debrief']} voice={'yes' if rec['voice'] else 'no'} "
              f"sent={rec['sent']}")
        done.append(rec)
    return done


def read_the_mirror() -> str:
    """C3c (26 Sep 2026), was spine step 25.46: the brain reads the mirror's numbers
    (core/interoception). Runs before the phase jobs, so the G_LEARN debrief sees it."""
    try:
        from core.interoception import read_the_mirror as _rtm
        rec = _rtm() or {}
        print(f"[EDGES] read_the_mirror: cited {rec.get('cited_count', 0)} of "
              f"{rec.get('mirror_numbers_available', 0)} (quota {rec.get('quota')}, "
              f"met={rec.get('met_quota')})")
        return "ok"
    except Exception as exc:  # noqa: BLE001
        print(f"[EDGES] read_the_mirror failed ({type(exc).__name__}: {exc})")
        return f"failed: {type(exc).__name__}"


def brain_debrief() -> str:
    """C3c (26 Sep 2026), was spine step 25.5: the brain judges the plan it wrote at
    the start of the night (core/brain.debrief_cycle)."""
    try:
        from core.brain import debrief_cycle as _debrief
        rev = _debrief()
        if not rev:
            print("[EDGES] brain_debrief: no plan to judge / brain silent")
            return "silent"
        print(f"[EDGES] brain_debrief: success={rev.get('success')} | {str(rev.get('verdict'))[:120]}")
        return "ok"
    except Exception as exc:  # noqa: BLE001
        print(f"[EDGES] brain_debrief failed ({type(exc).__name__}: {exc})")
        return f"failed: {type(exc).__name__}"


def cortex_orchestrator() -> str:
    """B.C: the model's notes on the grounded order (core/cortex_orchestrator).
    The arithmetic (core/orchestrator_grounded) stays in the spine."""
    try:
        from core.cortex_orchestrator import run as _orchestrate
        _orchestrate()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        print(f"[EDGES] cortex_orchestrator failed ({type(exc).__name__}: {exc})")
        return f"failed: {type(exc).__name__}"


def cycle_report_words(cycle_id: str, base: Path = BASE, writer=None) -> str | None:
    """B.C: rebuild the night's report WITH the brain's words ("reporting to the
    human") and write it over the spine's deterministic one. Returns the path."""
    try:
        from core import cycle_report as cr
        if writer is None:
            from core.brain import think as writer
        rep = cr.build(cycle_id=cycle_id, brain_writer=writer)
        out = base / "output" / "reports"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"CYCLE_REPORT_{str(rep.get('ts', ''))[:10]}.md"
        path.write_text(cr.to_markdown(rep), encoding="utf-8")
        print(f"[EDGES] cycle_report with the brain's words -> {path.name}")
        return str(path)
    except Exception as exc:  # noqa: BLE001
        print(f"[EDGES] cycle_report words failed ({type(exc).__name__}: {exc})")
        return None


def main(argv: list) -> int:
    if "--selftest" in argv:
        print("edges_runner.py --selftest")
        for mod in ("core.phase_debrief", "cockpit.phase_voice", "core.phase_report",
                    "core.interoception", "core.brain"):
            try:
                __import__(mod)
                print(f"  LIVE   {mod}")
            except Exception as exc:  # noqa: BLE001
                print(f"  INERT  {mod} ({type(exc).__name__}: {exc})")
        return 0
    cid = argv[argv.index("--cycle-id") + 1] if "--cycle-id" in argv else os.environ.get("CORTEX_CYCLE_ID")
    if not cid:
        print("[EDGES] no --cycle-id and no CORTEX_CYCLE_ID - refusing to guess which night")
        return 2
    os.environ["CORTEX_EDGES"] = str(cid)
    os.environ["CORTEX_IN_CYCLE"] = str(cid)      # the core only; no loads (warm core)
    print(f"[EDGES] read_the_mirror: {read_the_mirror()}")
    print(f"[EDGES] brain_debrief: {brain_debrief()}")
    jobs = phase_jobs(cid)
    print(f"[EDGES] phase jobs: {len(jobs)} phase(s) for {cid}")
    print(f"[EDGES] cortex_orchestrator: {cortex_orchestrator()}")
    cycle_report_words(cid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
