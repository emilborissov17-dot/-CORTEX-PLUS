#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_log.py — ONE NAME FOR A CYCLE'S LOG, DERIVED FROM ITS cycle_id.

THE DEFECT
-----------
Two things wrote and read cycle logs and neither knew the other's rule.

WRITING. supervisor.spawn_cycle() opens memory/cycle_logs/cycle_<stamp>.log and
redirects the child's stdout into it. A cycle started BY HAND — the documented
recovery step, `venv\\Scripts\\python.exe fast_cycle_runner.py` — wrote to a
console that DETACHED_PROCESS has since taken away, i.e. to nothing. The run
that most needs explaining, the one a human started because the automatic one
failed, was the one that left no log.

READING. core/cycle_report._latest_log() took the newest file in the directory
by mtime and called it "this cycle". Newest-by-mtime is not "mine". On 21 Aug
2026 the directory held cycle_2026-08-21_172402.log and
cycle_2026-08-21_174401.log — a killed cycle and its replacement — and a report
for either would have been built from whichever file the OS had touched last.
A report that describes a DIFFERENT cycle is worse than no report: it is wrong
with the confidence of a fact.

THE RULE
---------
    cycle_id "2026-08-21T17:44:01.649875+03:00"
        -> memory/cycle_logs/cycle_2026-08-21_174401.log

Colons cannot appear in a Windows filename, so the id is not the name; the name
is DERIVED from it, deterministically, and by the same formula the supervisor
already used (`cycle_{now:%Y-%m-%d_%H%M%S}.log` over a cycle_id that IS
`now.isoformat()`). That equivalence is not assumed — test_cycle_log_by_id.py
asserts it against supervisor.cycle_log_path().

ABSENT IS AN ANSWER
--------------------
find_for() returns None when the named cycle has no log, and callers must say
ABSENT. Substituting another cycle's log is the bug this module exists to stop.

    venv\\Scripts\\python.exe core/cycle_log.py --selftest
"""
from __future__ import annotations

import io
import pathlib
import re
import sys
from datetime import datetime

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
LOG_DIR = BASE / "memory" / "cycle_logs"

ABSENT = "ABSENT"

_STAMP = re.compile(r"^cycle_(\d{4}-\d{2}-\d{2}_\d{6})\.log$")


def stamp_of(cycle_id: str) -> str | None:
    """The filename stamp for a cycle_id, or None if it is not a timestamp.

    Accepts the ISO form the supervisor and the runner both produce. A cycle_id
    that is not parseable gets no derived name — inventing one would let two
    unrelated runs collide on a filename.
    """
    if not cycle_id:
        return None
    try:
        dt = datetime.fromisoformat(str(cycle_id))
    except (TypeError, ValueError):
        return None
    return f"{dt:%Y-%m-%d_%H%M%S}"


def path_for(cycle_id: str, log_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    s = stamp_of(cycle_id)
    if s is None:
        return None
    return (log_dir or LOG_DIR) / f"cycle_{s}.log"


def find_for(cycle_id: str, log_dir: pathlib.Path | None = None):
    """The log OF THIS CYCLE, or None. Never the newest, never a neighbour."""
    p = path_for(cycle_id, log_dir)
    return p if (p is not None and p.exists()) else None


def describe(cycle_id: str, log_dir: pathlib.Path | None = None) -> dict:
    """What a report should print. `status` is either "FOUND" or ABSENT, and the
    reason for an ABSENT is carried so the reader is not left guessing whether
    the cycle had no log or the id could not be parsed."""
    if not cycle_id:
        return {"status": ABSENT, "cycle_id": None, "path": None,
                "why": "no cycle_id was given — nothing to match on"}
    p = path_for(cycle_id, log_dir)
    if p is None:
        return {"status": ABSENT, "cycle_id": cycle_id, "path": None,
                "why": f"cycle_id {cycle_id!r} is not a timestamp, so no log "
                       f"name can be derived from it"}
    if not p.exists():
        return {"status": ABSENT, "cycle_id": cycle_id, "path": str(p),
                "why": f"no log at {p.name} — this cycle wrote none (a cycle "
                       f"started by hand before 21 Aug 2026 wrote to a console "
                       f"that DETACHED_PROCESS had already taken away)"}
    return {"status": "FOUND", "cycle_id": cycle_id, "path": str(p),
            "bytes": p.stat().st_size}


# ---------------------------------------------------------------------------
# The tee — for a cycle started by hand
# ---------------------------------------------------------------------------

class _Tee(io.TextIOBase):
    """Write to both the original stream and the log file.

    Line-buffered by fiat (`flush()` after every write). The supervisor's own
    redirect relies on PYTHONUNBUFFERED for exactly this reason and the scar is
    recorded in supervisor.spawn_cycle(): on 15 Jul 2026 a cycle ran ~20 minutes,
    died at 99% RAM, and left a 0-byte log because its buffer died with it.
    """

    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, s):
        n = 0
        try:
            n = self._stream.write(s)
            self._stream.flush()
        except Exception:
            pass
        try:
            self._fh.write(s)
            self._fh.flush()
        except Exception:
            pass
        return n or len(s)

    def flush(self):
        for target in (self._stream, self._fh):
            try:
                target.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8") or "utf-8"


def tee_stdio(cycle_id: str, log_dir: pathlib.Path | None = None) -> dict:
    """Mirror this process's stdout and stderr into its own cycle log.

    IDEMPOTENT UNDER THE SUPERVISOR, and by evidence rather than by a flag: the
    supervisor opens the very same path with mode "w" BEFORE it spawns the
    runner, so if the file is already there the runner is the supervisor's child
    and its output is already being captured. Teeing again would write every
    line twice into one file.

    Returns a record: {"teeing": bool, "path": str|None, "why": str}. Never
    raises — losing the log must not cost the cycle, which is the same trade
    supervisor.spawn_cycle() makes when it falls back to DEVNULL.
    """
    out = {"teeing": False, "path": None, "why": ""}
    p = path_for(cycle_id, log_dir)
    if p is None:
        out["why"] = f"cycle_id {cycle_id!r} yields no log name"
        return out
    out["path"] = str(p)
    try:
        if p.exists():
            out["why"] = ("the supervisor already opened this exact file before "
                          "spawning us — teeing would double every line")
            return out
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = p.open("w", encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        out["why"] = f"could not open the log ({type(exc).__name__}: {exc})"
        return out

    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = _Tee(sys.stderr, fh)
    out["teeing"] = True
    out["why"] = "started by hand — this process owns its own log"
    return out


def _selftest() -> int:
    import tempfile
    print("core/cycle_log.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {name}")

    cid = "2026-08-21T17:44:01.649875+03:00"
    check("a cycle_id derives its own log name",
          stamp_of(cid) == "2026-08-21_174401")
    check("an unparseable cycle_id derives nothing",
          stamp_of("not-a-time") is None and path_for("not-a-time") is None)

    # The supervisor's formula and this one must agree, or a supervisor-started
    # cycle would be reported ABSENT by a report that is looking at its log.
    try:
        import supervisor
        agreed = (supervisor.cycle_log_path(datetime.fromisoformat(cid)).name
                  == path_for(cid).name)
        print(f"  LIVE    supervisor.cycle_log_path")
        check("...and it agrees with the supervisor's", agreed)
    except Exception as exc:  # noqa: BLE001
        print(f"  INERT   supervisor.cycle_log_path ({type(exc).__name__})")

    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        check("an absent log is ABSENT, not a neighbour",
              describe(cid, d)["status"] == ABSENT)
        (d / "cycle_2026-08-21_172402.log").write_text("другият цикъл",
                                                       encoding="utf-8")
        check("...even when a DIFFERENT cycle's log is sitting right there",
              describe(cid, d)["status"] == ABSENT and find_for(cid, d) is None)
        (d / "cycle_2026-08-21_174401.log").write_text("моят", encoding="utf-8")
        check("its own log is found by id", describe(cid, d)["status"] == "FOUND")

        rec = tee_stdio(cid, d)
        check("teeing is refused when the file already exists (supervisor's)",
              rec["teeing"] is False and "double" in rec["why"])

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
