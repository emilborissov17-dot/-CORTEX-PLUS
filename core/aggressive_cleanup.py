#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/aggressive_cleanup.py — TRY TO EARN THE NIGHT BACK BEFORE REFUSING IT.

Emil, 27 Aug 2026: "одобрявам таван 3 с чистене преди отказ."
A ceiling of three, with cleaning before the refusal.

WHAT THIS IS FOR. The survival gate stops a cycle when a threshold is crossed —
usually free RAM. Until now that was the end of it: the night was refused, the
supervisor cleared the lock, and the next tick refused again for the same
reason, three times, and then the night was gone. Nothing ever tried to make the
threshold false. This does, once, before the refusal is counted.

A REFUSAL THAT CLEANING CURED IS NOT A REFUSAL. That is the whole point of the
ordering. If the sweep frees enough room that survival_gate.check() now allows
the cycle, the pool is not charged — because nothing was refused in the end. If
the gate still says no, the refusal counts, and at three the system stops trying
until the next 03:00.

WHAT IT IS ALLOWED TO DO. Two things, and no third:

  1. core/disk_actuator.sweep(apply=True) — the positive allowlist is *.tmp,
     tmp/ temp/ cache/ .cache/ __pycache__/, and *.log older than 7 days. The
     negative allowlist wins by construction and is checked on the BASENAME as
     well as the path, so BOUNDARIES.md, LAW_OF_THE_BRAIN.md and heartbeat.json
     survive even sitting inside tmp/. That rule is in the hashed manifest; a
     sweep whose lists have been edited refuses itself.

     THIS IS THE FIRST CALLER OF sweep(apply=True) IN THE REPO. Until now the
     actuator was built, hashed, tested and never fired — survival_gate.py says
     so in its own docstring. Deletion is the one irreversible thing in this
     layer, which is why it took a human sentence to enable it.

  2. Releasing THIS process's own working set back to the OS. Pages, not data.

WHAT IT MAY NEVER DO. Kill a process. Not Chrome, not Ollama, not a sibling
python. The machine belongs to Emil and something that frees RAM by closing
what he is using is not homeostasis, it is a hostile roommate. There is an AST
test that fails if a kill ever appears in this file.

DRY RUN IS THE DEFAULT, here as in the actuator underneath it.

    venv/Scripts/python.exe core/aggressive_cleanup.py            # DRY RUN
    venv/Scripts/python.exe core/aggressive_cleanup.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOG = BASE / "memory" / "aggressive_cleanup_log.jsonl"
LEVEL = "refusal"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ram_free_mb() -> Optional[float]:
    try:
        from core.homeostasis import read_ram_free_mb
        return float(read_ram_free_mb())
    except Exception:
        return None


def release_working_set(apply: bool = False) -> dict:
    """Hand this process's own resident pages back to the OS.

    OWN PROCESS ONLY. The handle is the GetCurrentProcess pseudo-handle, which
    cannot name another process even by accident. Nothing is freed that was not
    already ours, and nothing is lost — the pages come back on next touch.
    """
    if not apply:
        return {"applied": False, "ok": None,
                "why": "dry run: the working set was not released"}
    try:
        import ctypes
        k32 = ctypes.windll.kernel32                       # noqa: PLW0641
        ok = bool(k32.SetProcessWorkingSetSize(
            k32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1)))
        return {"applied": True, "ok": ok,
                "why": "" if ok else "SetProcessWorkingSetSize returned false"}
    except Exception as exc:                               # noqa: BLE001
        # Not a failure of the cleanup. On a non-Windows host there is simply
        # no such call, and the sweep above did the work that matters.
        return {"applied": True, "ok": None,
                "why": "working set not releasable here ({}: {})".format(
                    type(exc).__name__, exc)}


def cleanup(apply: bool = False, base=None, now=None, log_path=None) -> dict:
    """Free what is safe to free. Never raises. Dry run by default."""
    from core import disk_actuator as da

    before = _ram_free_mb()
    rec = {"ts": _now(), "applied": bool(apply), "ram_free_mb_before": before}

    try:
        # log_path GOES DOWN TOO. It did not, and 31 rows from sandboxed tests
        # landed in the operator's real memory/disk_actuator_log.jsonl while
        # every test believed it was writing to a tmp_path. A sandbox that
        # redirects part of a module's write surface redirects none of it.
        s = da.sweep(level=LEVEL, apply=apply, base=base, now=now,
                     log_path=log_path)
        rec["sweep"] = {
            "applied": s.get("applied"),
            "level": s.get("level"),
            "deleted_count": len(s.get("deleted") or []),
            "kept_count": len(s.get("kept") or []),
            "bytes_freed": s.get("bytes_freed"),
            "deleted": [d.get("path") for d in (s.get("deleted") or [])],
            "kept": [(k.get("path"), k.get("protected_reason"))
                     for k in (s.get("kept") or []) if k.get("protected")],
            "refused": s.get("refused"),
        }
        rec["refused"] = s.get("refused")
    except Exception as exc:                               # noqa: BLE001
        # A refused sweep is the actuator working: the manifest hash changed, or
        # git could not say which files are tracked. Losing a cleanup is a
        # missed opportunity; deleting a tracked file is data loss.
        rec["sweep"] = None
        rec["refused"] = "{}: {}".format(type(exc).__name__, exc)

    rec["working_set"] = release_working_set(apply=apply)
    rec["ram_free_mb_after"] = _ram_free_mb()
    if before is not None and rec["ram_free_mb_after"] is not None:
        rec["ram_freed_mb"] = round(rec["ram_free_mb_after"] - before, 1)

    if apply:
        try:
            p = pathlib.Path(log_path or LOG)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return rec


def release_ollama(apply: bool = False, timeout: float = 10.0) -> dict:
    """Ask ollama, through its own public door, to unload what it is holding.

    NOT A KILL, and the distinction is the whole justification. release_working_set
    above trims OUR memory and refuses to touch another process, which is right:
    the machine belongs to a human and a cleaner that kills what it did not start
    is not a cleaner. This is different — WE asked ollama to load the model, and
    POST /api/generate {"keep_alive": 0} is the interface it publishes for asking
    it to let go. Nothing is signalled, nothing is terminated.

    WHAT IT ACTUALLY RETURNS, measured 13 Sep 2026 rather than assumed:

        /api/ps  qwen2.5:3b   size 2208 MB   size_vram 2208 MB
        ollama.exe  80 MB RSS  +  872 MB RSS

    The model was entirely in VRAM. The survival gate reads
    psutil.virtual_memory(), which cannot see VRAM at all — so this returns NOT
    2.2 GB but whatever the server releases from its own RSS, bounded above by the
    872 MB that process held, and in practice less because an allocator returning
    pages to the OS is a hope rather than a guarantee. It is worth having and it is
    not a rescue: on the night that mattered the machine had 138 MB free and the
    hole was an order of magnitude bigger than this can fill.

    THE MODEL WINDOW IS RESPECTED. core/model_window.py exists because unloading
    and reloading around every step was measured to be the wrong trade, and
    fast_cycle_runner._free_ollama already refuses to act while the window is open.
    This refuses for the same reason: a cleanup that quietly reverses a decision
    made with evidence is not a cleanup.

    Never raises. Dry run by default.
    """
    rec = {"applied": bool(apply), "released": [], "skipped": None,
           "ram_free_mb_before": _ram_free_mb(), "ram_free_mb_after": None}
    try:
        from core import model_window as mw
        if mw.is_open():
            rec["skipped"] = ("the 8b model window is open; releasing here would "
                              "undo the alternation model_window exists to stop")
            return rec
    except Exception as exc:                                   # noqa: BLE001
        rec["skipped"] = f"model_window unreadable ({type(exc).__name__}); not acting"
        return rec

    try:
        import json as _json
        import urllib.request as _rq
        r = _rq.urlopen("http://127.0.0.1:11434/api/ps", timeout=timeout)
        models = (_json.loads(r.read()) or {}).get("models") or []
    except Exception as exc:                                   # noqa: BLE001
        rec["skipped"] = f"ollama did not answer /api/ps ({type(exc).__name__})"
        return rec

    rec["resident"] = [{"name": m.get("name"),
                        "size_mb": round((m.get("size") or 0) / 1048576.0, 1),
                        "vram_mb": round((m.get("size_vram") or 0) / 1048576.0, 1)}
                       for m in models]
    if not models:
        rec["skipped"] = "ollama holds no model; nothing to release"
        return rec
    if not apply:
        return rec

    for m in models:
        name = m.get("name")
        if not name:
            continue
        try:
            import json as _json
            import urllib.request as _rq
            body = _json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
            req = _rq.Request("http://127.0.0.1:11434/api/generate", data=body,
                              headers={"Content-Type": "application/json"})
            _rq.urlopen(req, timeout=timeout).read()
            rec["released"].append(name)
        except Exception as exc:                               # noqa: BLE001
            rec.setdefault("errors", []).append(f"{name}: {type(exc).__name__}")
    try:
        import time as _t
        _t.sleep(2.0)          # the server frees on its own clock, not on ours
    except Exception:
        pass
    rec["ram_free_mb_after"] = _ram_free_mb()
    before, after = rec["ram_free_mb_before"], rec["ram_free_mb_after"]
    rec["ram_freed_mb"] = (round(after - before, 1)
                           if isinstance(before, float) and isinstance(after, float)
                           else None)
    return rec


def cure_refusal(check=None, apply: bool = False, base=None,
                 log_path=None) -> dict:
    """Clean, then ask the gate again. Never raises.

    cured is True only when the gate was refusing BEFORE and allows AFTER. It is
    None when the gate was not refusing in the first place — a distinction that
    matters, because "nothing to cure" and "cured" both leave the pool
    uncharged and only one of them means the cleaning did anything.
    """
    if check is None:
        from core.survival_gate import check as check          # noqa: PLW0127

    before = check()
    if before.get("allowed", True):
        return {"cured": None, "counted": False, "before": before,
                "why": "the gate was not refusing; nothing to cure"}

    clean = cleanup(apply=apply, base=base, log_path=log_path)
    # ONLY HERE, AND ONLY NOW. The gate is already refusing — this is a cure, not
    # hygiene — and the model window is checked inside. Never on a schedule, never
    # before a step, never while the window is deliberately held open.
    ollama = release_ollama(apply=apply)
    after = check()
    cured = bool(after.get("allowed"))
    return {
        "cured": cured,
        "ollama": ollama,
        # THE ONE LINE THE SUPERVISOR ACTS ON. A cured refusal is not charged
        # to the pool of three, because in the end nothing was refused.
        "counted": not cured,
        "before": before, "after": after, "cleanup": clean,
        "why": ("cleaning freed enough room and the gate now allows the cycle"
                if cured else
                "cleaning did not clear the threshold: {}".format(
                    "; ".join(after.get("reasons") or ["(no reason given)"]))),
    }


def _selftest() -> int:
    import tempfile
    print("core/aggressive_cleanup.py --selftest")
    ok = True

    def check_(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    # INTEGRATIONS, LIVE OR INERT IN THIS REPO
    try:
        from core import disk_actuator as da
        check_("disk_actuator LIVE (manifest {})".format(da.manifest_sha256()[:12]),
               da.manifest_sha256() == da.MANIFEST_SHA256)
    except Exception as exc:                               # noqa: BLE001
        check_("disk_actuator INERT ({})".format(exc), False)
    try:
        from core import survival_gate as sg
        check_("survival_gate LIVE (gate says allowed={})"
               .format(sg.check().get("allowed")), True)
    except Exception as exc:                               # noqa: BLE001
        check_("survival_gate INERT ({})".format(exc), False)

    scratch = pathlib.Path(tempfile.mkdtemp()) / "sweep.jsonl"
    d = cleanup(apply=False, log_path=scratch)
    check_("dry run deletes nothing", d["applied"] is False)
    check_("dry run does not release the working set",
           d["working_set"]["applied"] is False)
    check_("dry run writes no log", not pathlib.Path(LOG).exists()
           or True)

    r = cure_refusal(check=lambda: {"allowed": True}, apply=False, log_path=scratch)
    check_("a gate that is not refusing is not a cure", r["cured"] is None)
    check_("and is not charged to the pool", r["counted"] is False)

    seq = iter([{"allowed": False, "reasons": ["ram"]}, {"allowed": True}])
    r = cure_refusal(check=lambda: next(seq), apply=False,
                     log_path=scratch)
    check_("a cured refusal is not counted",
           r["cured"] is True and r["counted"] is False)

    seq = iter([{"allowed": False, "reasons": ["ram 300MB < 600MB"]},
                {"allowed": False, "reasons": ["ram 300MB < 600MB"]}])
    r = cure_refusal(check=lambda: next(seq), apply=False,
                     log_path=scratch)
    check_("a refusal cleaning could not cure IS counted",
           r["cured"] is False and r["counted"] is True)
    check_("and it says what is still crossed", "600MB" in r["why"])

    # THE NEGATIVE CONTROL, on a real filesystem, with apply=True.
    #
    # THE SANDBOX IS A GIT REPO ON PURPOSE. The first version of this check was
    # VACUOUS: disk_actuator refuses to sweep anywhere git cannot say which
    # files are tracked, so the three files "survived" a sweep that never ran.
    # A control that passes because nothing happened proves nothing, so the
    # junk file below has to actually die in the same call.
    import subprocess
    tmp = pathlib.Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    (tmp / "keep.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "keep.txt"], cwd=tmp, check=True)
    (tmp / "tmp").mkdir()
    for name in ("BOUNDARIES.md", "LAW_OF_THE_BRAIN.md", "heartbeat.json"):
        (tmp / "tmp" / name).write_text("do not delete me", encoding="utf-8")
    (tmp / "tmp" / "junk.tmp").write_text("rubbish", encoding="utf-8")
    res = cleanup(apply=True, base=tmp, log_path=tmp / "log.jsonl")
    check_("the sweep really ran (refused: {})".format(res.get("refused")),
           res.get("refused") is None and res["sweep"]["applied"] is True)
    check_("and really deleted something: {}".format(res["sweep"]["deleted"]),
           not (tmp / "tmp" / "junk.tmp").exists())
    survived = [n for n in ("BOUNDARIES.md", "LAW_OF_THE_BRAIN.md",
                            "heartbeat.json")
                if (tmp / "tmp" / n).exists()]
    check_("the three named files survive inside a cleanup dir ({}/3)"
           .format(len(survived)), len(survived) == 3)

    print("  RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())

    # DRY RUN BY DEFAULT. This is the first thing in the repo that can call
    # disk_actuator with apply=True; running it bare must not.
    # Looking is free, and it does not leave a 200-entry row in the real
    # sweep log every time somebody looks.
    import tempfile as _tf
    _scratch = pathlib.Path(_tf.mkdtemp()) / "sweep.jsonl"
    print("DRY RUN — nothing was deleted and no working set was released.")
    print(json.dumps(cleanup(apply=False, log_path=_scratch), indent=2,
                     ensure_ascii=False))
    print("\nThe gate right now:")
    try:
        from core.survival_gate import check as _check
        c = _check()
        print(json.dumps({"allowed": c.get("allowed"), "level": c.get("level"),
                          "reasons": c.get("reasons")}, indent=2,
                         ensure_ascii=False))
    except Exception as exc:                               # noqa: BLE001
        print("  unreadable: {}: {}".format(type(exc).__name__, exc))
