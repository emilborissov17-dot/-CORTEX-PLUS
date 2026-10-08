#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/narration.py - THE BATON SAYS WHAT IT DOES, WHILE IT DOES IT (Emil R60).

  "ДА КАЗВА НА ВСЯКА СТЪПКА КАКВО ПРАВИ" / "ДА СЕ ВИЖДА И НА ЖИВО" / "И ПИСМЕНА СЛЕДА"

ONE mechanism for the two turns of the baton (scripts/turn_brain.py,
scripts/turn_agents.py) and for every call to the local model made inside a
turn (core/brain.think). One row per event, appended and fsynced per line:

  OPEN   the turn: role, turn id, pid, and the switches that change what a turn
         can do (CORTEX_NO_REAL_MODEL, CONTROL_NO_TELEGRAM) with their values
  START  a step: its name, WHY (the caller's sentence), what it is declared to
         read, each file with its age in hours, or MISSING
  MODEL  one call to the local model inside the open step: model, seconds, what
         was asked (the instance, not the template), what came back - or
         REFUSED / ERROR with the exception. Nothing is swallowed here: a call
         that core/brain.think turns into "no reply" is named on this row.
  NOTE   one fact inside the open step (a need served, a verdict)
  END    the step: OK, or FAILED with the exception; seconds; RESULT (the
         caller's sentence); the files it wrote and read AS SEEN by an audit
         hook in this process (child processes are not seen, and the row says so)
  CLOSE  the turn: exit code and summary

Two readers, one text:
  memory/narration/<turn id>.jsonl   machine; the cockpit's LIVE tab polls it
  stdout                             the same human line, which the witness
                                     (tools/cycle_witness.ps1) keeps in
                                     logs/turns/<turn id>.log

Every row carries "line", the human sentence, so the page and the log cannot
say two different things.

Outside an open turn every call here is a no-op: the legacy cycle and the tests
that call core.brain.think write nothing.

NEVER COSTS A STEP. Every public function catches everything, except step(),
which re-raises the step's own exception after writing its END row. A narrator
that cannot write prints "[NARRATION] DOWN: <reason>" once per turn; the turn
goes on.

    venv\\Scripts\\python.exe -m core.narration latest     # print the newest turn's lines
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
NARR_DIR = BASE / "memory" / "narration"
SWITCHES = ("CORTEX_NO_REAL_MODEL", "CONTROL_NO_TELEGRAM")
HEAD = 300              # characters of a question or a reply kept on a MODEL row
LIST_CAP = 12           # files named in the human line; the .jsonl keeps up to TRACK_CAP
TRACK_CAP = 2000
_SKIP_EXT = (".py", ".pyc", ".pyd", ".pyi", ".dll", ".so")
_SKIP_PARTS = (os.sep + "venv" + os.sep, os.sep + "venv312_metta" + os.sep,
               os.sep + "__pycache__" + os.sep, os.sep + ".git" + os.sep)

_S: dict = {"turn": None, "role": None, "dir": None, "n": 0, "step": None, "open": None,
            "reads": set(), "writes": set(), "track": False, "hook": False, "down": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_id(turn_id) -> str:
    out = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(turn_id))
    return out[:120] or "unnamed"


def path_for(turn_id, narr_dir=None) -> pathlib.Path:
    return pathlib.Path(narr_dir or NARR_DIR) / f"{safe_id(turn_id)}.jsonl"


def is_open() -> bool:
    return _S["turn"] is not None


# -- the hook: in memory only, never raises ----------------------------------

def _audit(name, args) -> None:
    try:
        if not _S["track"] or name != "open" or not args:
            return
        p = args[0]
        if not isinstance(p, (str, bytes, os.PathLike)):
            return
        p = os.path.abspath(os.fsdecode(p))
        if not p.startswith(str(BASE)) or any(s in p for s in _SKIP_PARTS):
            return
        if p.startswith(str(pathlib.Path(_S["dir"] or NARR_DIR))):
            return
        mode = str(args[1]) if len(args) > 1 and args[1] is not None else "r"
        rel = os.path.relpath(p, str(BASE)).replace("\\", "/")
        if any(c in mode for c in "wax+"):
            if len(_S["writes"]) < TRACK_CAP:
                _S["writes"].add(rel)
        elif not rel.endswith(_SKIP_EXT) and len(_S["reads"]) < TRACK_CAP:
            _S["reads"].add(rel)
    except Exception:
        pass


def _install_hook() -> None:
    if not _S["hook"]:
        sys.addaudithook(_audit)          # cannot be removed; it does nothing while _S["track"] is False
        _S["hook"] = True


# -- writing ---------------------------------------------------------------

def _down(reason: str) -> None:
    if _S["down"] is not None:
        return
    _S["down"] = reason
    try:
        print(f"[NARRATION] DOWN: {reason} - the turn continues without a narrator", flush=True)
    except Exception:
        pass


def _emit(row: dict) -> None:
    if _S["turn"] is None:
        return
    _S["n"] += 1
    row = {"n": _S["n"], "t": _now(), "turn": _S["turn"], **row}
    try:
        print(f"[NARRATION] {row['t'][11:19]} {row.get('line', '')}", flush=True)
    except Exception:
        pass
    track, _S["track"] = _S["track"], False        # the narrator's own writes are not the step's
    try:
        p = path_for(_S["turn"], _S["dir"])
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as e:
        _down(f"{type(e).__name__}: {e}")
    finally:
        _S["track"] = track


def age_h(path) -> float | None:
    """Hours since the file (for a directory: its newest top-level entry) was
    modified; None when it does not exist."""
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = BASE / p
    try:
        if p.is_dir():
            ms = [e.stat().st_mtime for e in os.scandir(p)]
            m = max(ms) if ms else p.stat().st_mtime
        else:
            m = p.stat().st_mtime
    except (OSError, ValueError):
        return None
    return round((time.time() - m) / 3600.0, 2)


def _rel(path) -> str:
    p = pathlib.Path(path)
    try:
        return p.resolve().relative_to(BASE).as_posix()
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def _fmt(files: list, key: str) -> str:
    if not files:
        return "none seen"
    out = []
    for f in files[:LIST_CAP]:
        v = f.get(key)
        if key == "bytes":
            out.append(f"{f['path']} ({v} B)" if v is not None else f"{f['path']} (gone)")
        elif f.get("rewritten"):
            out.append(f"{f['path']} (rewritten by this step)")
        else:
            out.append(f"{f['path']} ({'MISSING' if v is None else f'{v} h'})")
    more = len(files) - LIST_CAP
    return ", ".join(out) + (f", ... +{more} more" if more > 0 else "")


# -- the turn ----------------------------------------------------------------

def open_turn(role: str, turn_id=None, narr_dir=None) -> str | None:
    """Opens the narration of one turn. The id is CORTEX_TURN_ID (set by
    scripts/turns_loop.py for the witnessed turn, the same id as the witness's
    cycle_id) or, when none was given, "turn-<role>-noid-<utc>". Returns the
    file it writes, or None if it cannot."""
    try:
        given = turn_id or os.environ.get("CORTEX_TURN_ID")
        tid = given or f"turn-{role.lower()}-noid-{time.strftime('%Y-%m-%dT%H%M%SZ', time.gmtime())}"
        _S.update({"turn": safe_id(tid), "role": role, "dir": narr_dir, "n": 0, "step": None, "open": None,
                   "reads": set(), "writes": set(), "track": False, "down": None})
        _install_hook()
        sw = {k: os.environ.get(k) for k in SWITCHES}
        set_ = [f"{k}={v}" for k, v in sw.items() if v is not None]
        warn = (" | WARNING: " + ", ".join(set_) + " is set - " +
                ("no request reaches the local model in this turn" if sw.get("CORTEX_NO_REAL_MODEL") == "1"
                 else "a test switch is set in a live turn")) if set_ else ""
        _emit({"kind": "OPEN", "role": role, "pid": os.getpid(), "switches": sw,
               "id_from": "the loop (CORTEX_TURN_ID)" if given else "none given: started outside the loop, or by a loop "
                                                                    "older than C-NARRATE-2",
               "line": f"OPEN turn {_S['turn']} ({role}), pid {os.getpid()}"
                       + ("" if given else " (no id from the loop)") + "; switches: "
                       + (", ".join(set_) if set_ else "none set") + warn})
        return str(path_for(_S["turn"], narr_dir))
    except Exception as e:
        _down(f"open_turn: {type(e).__name__}: {e}")
        return None


def close_turn(exit_code, summary: str = "") -> None:
    try:
        if _S["turn"] is None:
            return
        if _S.get("open"):
            _end("FAILED", "the turn ended with this step still open", None)
        _emit({"kind": "CLOSE", "exit": exit_code, "summary": summary,
               "line": f"CLOSE exit {exit_code}: {summary}"})
    except Exception as e:
        _down(f"close_turn: {type(e).__name__}: {e}")
    finally:
        _S.update({"turn": None, "role": None, "step": None, "open": None, "track": False})


class _Step:
    def __init__(self, name: str):
        self.name = name
        self.result = None
        self.wrote: list = []

    def said(self, result: str) -> None:
        """The step's result, in one sentence, for its END row."""
        self.result = str(result)

    def wrote_file(self, path) -> None:
        """A file the step wrote through a child process the hook cannot see."""
        self.wrote.append(_rel(path))


def _start(name: str, why: str, reads) -> None:
    decl = [{"path": _rel(r), "age_h": age_h(r)} for r in reads]
    _S["step"], _S["reads"], _S["writes"] = name, set(), set()
    _S["open"] = {"name": name, "t0": time.time()}
    rtxt = _fmt(decl, "age_h") if decl else "nothing declared"
    _emit({"kind": "START", "step": name, "why": why, "reads": decl,
           "line": f"START {name} - why: {why} | reads: {rtxt}"})
    _S["track"] = True


def _end(status: str, err, result, extra_wrote=()) -> None:
    op = _S.get("open")
    if not op:
        return
    _S["track"], _S["open"] = False, None
    wrote = sorted(set(_S["writes"]) | set(extra_wrote))
    w = []
    for rel in wrote:
        try:
            b = (BASE / rel).stat().st_size
        except OSError:
            b = None
        w.append({"path": rel, "bytes": b})
    r = [({"path": rel, "rewritten": True} if rel in wrote else {"path": rel, "age_h": age_h(rel)})
         for rel in sorted(_S["reads"])]
    secs = round(time.time() - op["t0"], 1)
    res = result if result is not None else ("no result stated" if status == "OK" else "")
    name = op["name"]
    _emit({"kind": "END", "step": name, "status": status, "error": err, "seconds": secs,
           "result": res, "wrote": w, "read": r, "seen_by": "audit hook, this process only",
           "line": f"END {name} {status} {secs} s" + (f" | error: {err}" if err else "")
                   + (f" | result: {res}" if res else "")
                   + f" | wrote: {_fmt(w, 'bytes')} | read: {_fmt(r, 'age_h')}"})
    _S["step"], _S["reads"], _S["writes"] = None, set(), set()


@contextmanager
def step(name: str, why: str, reads=()):
    """START now; END when the block leaves: OK, FAILED with the exception, or
    INTERRUPTED. The step's own exception is re-raised after its END row;
    nothing else here raises."""
    s = _Step(name)
    if _S["turn"] is None:
        yield s
        return
    try:
        if _S.get("open"):
            _end("FAILED", "a new step started while this one was open", None)
        _start(name, why, reads)
    except Exception as e:
        _down(f"step({name}) START: {type(e).__name__}: {e}")
    # INTERRUPTED stays when neither line below runs: a KeyboardInterrupt or a
    # SystemExit left the block. Not caught here (test_no_bare_except), only named.
    status, err = "INTERRUPTED", None
    try:
        yield s
        status = "OK"
    except Exception as e:
        status, err = "FAILED", f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        try:
            if status == "INTERRUPTED":
                err = "the block was left by a signal or sys.exit, not by an exception"
            _end(status, err, s.result, s.wrote)
        except Exception as e:
            _down(f"step({name}) END: {type(e).__name__}: {e}")


def begin(name: str, why: str, reads=()) -> None:
    """START for a phase that is not a with-block; end() closes it. A turn that
    ends with it still open closes it as FAILED (close_turn)."""
    try:
        if _S["turn"] is None:
            return
        if _S.get("open"):
            _end("FAILED", "a new step started while this one was open", None)
        _start(name, why, reads)
    except Exception as e:
        _down(f"begin({name}): {type(e).__name__}: {e}")


def end(result=None, status: str = "OK", error=None) -> None:
    try:
        if _S["turn"] is None:
            return
        _end(status, error, result)
    except Exception as e:
        _down(f"end: {type(e).__name__}: {e}")


def note(text: str, **facts) -> None:
    try:
        if _S["turn"] is None:
            return
        _emit({"kind": "NOTE", "step": _S["step"], **facts, "line": f"  - {text}"})
    except Exception as e:
        _down(f"note: {type(e).__name__}: {e}")


def asked_part(prompt: str) -> str:
    """The instance of a written instruction text: its last paragraph (the
    examples come first, the question last)."""
    s = str(prompt or "").strip()
    parts = [p for p in s.split("\n\n") if p.strip()]
    return parts[-1] if parts else s


def model(role: str, model_name, asked: str, reply, seconds, error=None) -> None:
    """One call to the local model inside the open step."""
    try:
        if _S["turn"] is None:
            return
        if error:
            word = "REFUSED" if "REFUSED" in str(error).upper() else "ERROR"
        else:
            word = "REPLIED" if reply else "EMPTY"
        a = " ".join(str(asked or "").split())
        if len(a) > HEAD:              # both ends: the question opens TEXT C, the sentence closes TEXT B
            a = a[:HEAD // 2] + " ... " + a[-HEAD // 2:]
        rp = " ".join(str(reply or "").split())[:HEAD]
        _emit({"kind": "MODEL", "step": _S["step"], "role": role, "model": model_name, "outcome": word,
               "seconds": seconds, "asked": a, "reply": rp, "error": (str(error)[:500] if error else None),
               "line": f"  MODEL {model_name} {word} {seconds} s ({role}) | asked: {a}"
                       + (f" | error: {str(error)[:300]}" if error else f" | said: {rp or '(nothing)'}")})
    except Exception as e:
        _down(f"model: {type(e).__name__}: {e}")


# -- reading back (the cockpit, a human) --------------------------------------

def turns(narr_dir=None, n: int = 12) -> list:
    d = pathlib.Path(narr_dir or NARR_DIR)
    try:
        fs = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return [{"turn": f.stem, "age_s": round(time.time() - f.stat().st_mtime, 1)} for f in fs[:n]]


def read(turn_id, since: int = 0, narr_dir=None) -> dict:
    """The complete rows of one turn from `since` on. A last line with no
    newline is being written and is not served yet."""
    p = path_for(turn_id, narr_dir)
    raw = p.read_bytes()
    lines = raw.decode("utf-8", "replace").split("\n")
    complete = lines[:-1]                     # the piece after the last "\n" is unfinished (or empty)
    rows = []
    for ln in complete[since:]:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            rows.append({"kind": "UNREADABLE", "line": f"unreadable row: {ln[:200]}"})
    return {"turn": p.stem, "rows": rows, "next": len(complete),
            "age_s": round(time.time() - p.stat().st_mtime, 1)}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    t = turns()
    if not t:
        print("no turn has narrated yet (memory/narration/ is empty)")
        return 0
    tid = t[0]["turn"] if not argv or argv[0] == "latest" else argv[0]
    for r in read(tid)["rows"]:
        print(f"{str(r.get('t', ''))[11:19]} {r.get('line', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
