# -*- coding: utf-8 -*-
"""core/turn_live.py — the live checks of the baton (C-FIX-1, 2 Oct 2026).

Decided: core.turn keeps the baton only; its live checks live here
(test/test_turn_is_pure.py holds the rule).

    venv\\Scripts\\python.exe -m core.turn_live --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def witness(cycle_id: str):
    import supervisor
    return supervisor.witness_exit_for(cycle_id)


def alarm(subject: str, detail: str, dedup_key: str) -> str:
    import supervisor
    return supervisor.alarm_human(subject, detail, dedup_key=dedup_key, cls="TURN_STUCK",
                                  level=supervisor.ALARM)


def cycle() -> Optional[str]:
    from core import model_window as mw
    if mw.in_cycle():
        return "this process is inside the nightly cycle"
    try:
        from scripts.micro_cycle import big_cycle_running
        running, why = big_cycle_running()
        return why if running else None
    except Exception as exc:                                         # noqa: BLE001
        return f"cycle liveness could not be checked ({type(exc).__name__}) — waiting"


def body() -> Optional[str]:
    from core import homeostasis
    a = homeostasis.assess(verbose=False)
    return None if a.get("can_start", True) else f"body: {a.get('abort_reason')}"


def selftest() -> dict:
    loop = REPO / "scripts" / "turns_loop.py"
    src = loop.read_text(encoding="utf-8") if loop.exists() else ""
    return {"integrations": {"scripts/turns_loop.py passes these to core.turn":
                             "LIVE" if "turn_live" in src else "INERT"}, "ok": True}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
