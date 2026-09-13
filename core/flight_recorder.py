#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/flight_recorder.py — the record of a cycle, written from OUTSIDE it.

WHY THIS EXISTS. On 13 Sep 2026 the cycle had 75 steps and 43 of them opened a
StepContract. The other 32 were invisible: they ran, they took time, and nothing
recorded that they had. Of a 129-minute night, 64 minutes were accounted for. The
missing hour was not idle — it was unobserved, which is a different and worse
thing, because an unobserved hour looks exactly like an hour that did not happen.

The fix is not to ask the remaining 32 steps to declare themselves. A record that
depends on the observed asking permission has the same hole in a new place. This
observer samples the process from a thread the steps do not know about, and hooks
the interpreter's own audit channel, which no step can decline.

WHAT IT COSTS, AND THE SHAPE OF THAT COST. One daemon thread waking each second to
read one stack, one writer thread flushing every two seconds, and an audit hook
that does a dict lookup and a queue put. Measured on this machine before it was
wired in; see the commit that added it.

STDLIB ONLY. json, hashlib, threading, queue, sys, os, time, traceback,
contextvars. No opentelemetry, no SDK, nothing that can drag a version conflict
into the first step of the night — this file exists BECAUSE cortex_reasoner died
on someone else's transitive import. psutil is the single optional import, tried
once and never required: without it the memory fields are null, which is the
honest answer, rather than absent, which reads as zero.

DURABILITY, AND WHY THE TWO CHANNELS ARE WRITTEN DIFFERENTLY.
  "open" and "span" are written SYNCHRONOUSLY and flushed at once. They are rare —
  one pair per step — so the cost is nothing, and it buys the thing that matters:
  when the process is killed, the "open" of the step it died inside is already on
  disk with no "span" after it. That asymmetry IS the finding.
  "ev" rows go through a queue and a writer thread that flushes every 2s, so a
  kill loses at most the last two seconds of samples.

ATTRIBUTION, AND THE HONEST NULL. A span is attributed through a ContextVar that
_run() sets. For the steps that never call _run(), the pulse walks the main
thread's stack and takes the deepest frame whose function name is a step name in
core/cycle_map.STEPS. When neither works, sp is null. It is never guessed: the
unattributed seconds are the answer to "where did the other hour go", and a
plausible label invented here would delete the question.

    venv\\Scripts\\python.exe core\\flight_recorder.py --selftest
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import queue
import sys
import threading
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE_DIR = os.path.join(REPO, "memory", "cycle_trace")

PULSE_SEC = 1.0
FLUSH_SEC = 2.0
# A coalesced row is emitted at least this often even while its key keeps
# being hit. Without it a step stuck in one place writes NOTHING until it
# moves: watched live on 13 Sep, the trace went quiet for three minutes
# while the cycle was alive and working. Silence that means 'busy' is
# indistinguishable from silence that means 'dead', which is the one
# distinction this recorder exists to make.
COALESCE_MAX_SEC = 30.0
FSYNC_EVERY = 200
BUFFER_CAP = 5000          # rows held before a cycle_id arrives
BUFFER_SEC = 30.0          # seconds held before giving up and using a provisional name
ERR_CHARS = 200
ARGV_HEAD = 3

# Directories the audit hook must never look at. memory/cycle_trace is first for a
# reason: without it the recorder would record its own writes, and each recorded
# write would be another write.
SKIP_PARTS = (os.sep + "venv" + os.sep, os.sep + "__pycache__" + os.sep,
              os.sep + ".git" + os.sep,
              os.sep + "memory" + os.sep + "cycle_trace" + os.sep)

_CURRENT = contextvars.ContextVar("flight_recorder_span", default=None)

# ── WHY THERE ARE TWO OF THESE, AND THE SECOND IS NOT REDUNDANT ──────────────
# A ContextVar is per-context. The pulse runs in its own thread and reads the
# default forever; a worker thread started by a step begins with a fresh context
# and reads the default too. Measured on the cycle of 13 Sep: 0 of 119 pulses
# carried a span id even while step:internet_agent was open for 1691 seconds, and
# only 2 of the cycle's 154 spawns were attributable — internet_agent does its
# fetching in threads, so every child it started fell into "unattributed".
#
# That is not a rounding error, it is the difference between "the browser step
# spawned 2 processes" and "somewhere between 2 and 154". A record that cannot say
# which is not measuring.
#
# So the ContextVar stays — it is the right thing for nesting inside one thread,
# where an inner span must not leak out of its scope — and a PLAIN module
# variable carries the step for everyone else. The plain one is deliberately only
# ever the STEP span, never a nested call span: a worker thread has no way to know
# which inner span it belongs to, and guessing one would be worse than naming the
# step it certainly belongs to.
_CURRENT_STEP = None            # the innermost open "step:*" span, process-wide
_STEP_STACK = []                # so a nested step restores its parent on exit


def _current_span():
    """The span an event belongs to: this context's, or the process-wide step."""
    return _CURRENT.get() or _CURRENT_STEP

# A thread that dies quietly takes the record with it and leaves the verdict
# green — measured, on the first run of this file's own selftest. Captured here so
# that a dead worker is a FAILURE and not a footnote in stderr.
THREAD_ERRORS = []

_state = {
    "on": False,
    "t0": 0.0,
    "trace_id": None,
    "cycle_id": None,
    "path": None,
    "fh": None,
    "lines": 0,
    "buffer": [],
    "q": None,
    "writer": None,
    "pulser": None,
    "stopping": threading.Event(),
    "lock": threading.RLock(),
    "hook_installed": False,
    "main_thread_id": None,
    "step_names": None,
    "dropped": 0,
    "last_t": 0.0,
}


# ── small helpers ─────────────────────────────────────────────────────────────

def _now() -> float:
    return round(time.time() - _state["t0"], 2)


def _sid() -> str:
    return os.urandom(8).hex()


def _safe_name(cycle_id: str) -> str:
    out = []
    for ch in str(cycle_id):
        out.append(ch if (ch.isalnum() or ch in "-_.") else "_")
    return "".join(out)[:120] or "unnamed"


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _mem() -> tuple:
    """(rss_mb, avail_mb). Nulls when psutil is absent — never a fabricated zero."""
    ps = _psutil()
    if ps is None:
        return None, None
    try:
        rss = round(ps.Process().memory_info().rss / 1048576.0, 1)
        avail = round(ps.virtual_memory().available / 1048576.0, 1)
        return rss, avail
    except Exception:
        return None, None


def _step_names() -> set:
    """Step names from core/cycle_map, loaded lazily.

    Lazily because start() runs before the repo is importable in the runner, and
    this is only needed once the pulse begins finding frames.
    """
    if _state["step_names"] is None:
        names = set()
        try:
            if REPO not in sys.path:
                sys.path.insert(0, REPO)
            from core.cycle_map import STEPS
            names = {s[0] for s in STEPS}
        except Exception:
            names = set()
        _state["step_names"] = names
    return _state["step_names"]


# ── the file ──────────────────────────────────────────────────────────────────

def _open_file(cycle_id: str) -> None:
    _state["cycle_id"] = cycle_id
    _state["trace_id"] = hashlib.sha256(str(cycle_id).encode("utf-8")).hexdigest()[:32]
    os.makedirs(TRACE_DIR, exist_ok=True)
    _state["path"] = os.path.join(TRACE_DIR, _safe_name(cycle_id) + ".jsonl")
    _state["fh"] = open(_state["path"], "a", encoding="utf-8", buffering=1)
    head = {"k": "head", "trace_id": _state["trace_id"], "cycle_id": str(cycle_id),
            "t0": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(_state["t0"])) + "Z",
            "pid": os.getpid(), "py": sys.version.split()[0],
            "channels": _state["channels"]}
    _write_now(head)
    buf, _state["buffer"] = _state["buffer"], []
    for row in buf:
        _write_now(row)


def _write_now(row: dict) -> None:
    """Write one row and flush. Holds the lock; never raises."""
    fh = _state["fh"]
    if fh is None:
        if len(_state["buffer"]) < BUFFER_CAP:
            _state["buffer"].append(row)
        else:
            _state["dropped"] += 1
        return
    try:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        _state["lines"] += 1
        if _state["lines"] % FSYNC_EVERY == 0:
            os.fsync(fh.fileno())
    except Exception:
        pass


def _emit_sync(row) -> None:
    if not isinstance(row, dict):        # a sentinel that reached the drain
        return
    with _state["lock"]:
        t = row.get("t_end") or row.get("t")
        if isinstance(t, (int, float)) and t > _state["last_t"]:
            _state["last_t"] = t
        _write_now(row)


# ── the writer thread: everything that is not open/span ───────────────────────

def _writer_loop() -> None:
    """Coalesce and flush 'ev' rows every FLUSH_SEC.

    COALESCING IS NOT COMPRESSION, it is the difference between a record and a
    firehose. A step that opens the same file four hundred times produces four
    hundred identical facts; one row carrying n=400 is the same information and
    can be read. A key is emitted once it has gone one whole flush window without
    a new hit, which is how a run of samples gets a single row with its true
    t_end — the rule the pulse needs.
    """
    pending = {}                     # key -> row being accumulated
    fresh = set()                    # keys touched since the last flush
    q = _state["q"]
    last = time.time()
    while True:
        timeout = max(0.05, FLUSH_SEC - (time.time() - last))
        try:
            item = q.get(timeout=timeout)
        except queue.Empty:
            item = None
        if item is not None:
            if item is _SENTINEL:
                break
            key, row = item
            cur = pending.get(key)
            if cur is None:
                pending[key] = row
            else:
                cur["attr"]["n"] = cur["attr"].get("n", 1) + 1
                cur["attr"]["t_end"] = row["t"]
            fresh.add(key)
        if time.time() - last >= FLUSH_SEC:
            now_t = _now()
            for key in list(pending):
                row = pending[key]
                idle = key not in fresh
                held = now_t - float(row.get("t") or 0.0)
                if idle or held >= COALESCE_MAX_SEC:
                    _emit_sync(pending.pop(key))
            fresh.clear()
            last = time.time()
    for row in pending.values():
        _emit_sync(row)


_SENTINEL = object()


def _put(key, row) -> None:
    q = _state["q"]
    if q is None:
        return
    try:
        q.put_nowait((key, row))
    except Exception:
        _state["dropped"] += 1


def event(name: str, attr: dict, sp=None) -> None:
    """Queue one 'ev'. Safe from any thread, never raises."""
    if not _state["on"]:
        return
    row = {"k": "ev", "sp": sp if sp is not None else _current_span(),
           "name": name, "t": _now(), "attr": dict(attr)}
    row["attr"].setdefault("n", 1)
    key = (row["sp"], name, attr.get("path") or attr.get("where")
           or attr.get("host") or attr.get("pid"))
    _put(key, row)


# ── CHANNEL A: the pulse ──────────────────────────────────────────────────────

def _top_repo_frame(frame):
    """The innermost frame whose file is ours. venv, tests and caches excluded."""
    best = None
    while frame is not None:
        f = frame.f_code.co_filename
        if f.startswith(REPO) and not any(p in f for p in SKIP_PARTS) \
                and (os.sep + "test" + os.sep) not in f:
            if best is None:
                best = frame
            break
        frame = frame.f_back
    return best


def _step_from_stack(frame) -> str | None:
    """The DEEPEST frame whose function name is a step name — the attribution
    path for the 32 steps that never call _run()."""
    names = _step_names()
    if not names:
        return None
    found = None
    while frame is not None:
        fn = frame.f_code.co_name
        if fn in names:
            found = fn
        frame = frame.f_back
    return found


def _pulse_loop() -> None:
    while not _state["stopping"].wait(PULSE_SEC):
        try:
            frames = sys._current_frames()
            fr = frames.get(_state["main_thread_id"])
            if fr is None:
                continue
            top = _top_repo_frame(fr)
            if top is None:
                where = None
            else:
                rel = os.path.relpath(top.f_code.co_filename, REPO).replace("\\", "/")
                where = f"{rel}:{top.f_lineno}:{top.f_code.co_name}"
            sp = _current_span()
            step = None if sp else _step_from_stack(fr)
            rss, avail = _mem()
            attr = {"where": where, "rss_mb": rss, "avail_mb": avail,
                    "gpu_mib": None, "n": 1}
            if step:
                attr["step_from_stack"] = step
            row = {"k": "ev", "sp": sp, "name": "pulse", "t": _now(), "attr": attr}
            row["attr"]["t_end"] = row["t"]
            _put((sp, "pulse", where), row)
        except Exception:
            pass


# ── CHANNEL B: the audit hook ─────────────────────────────────────────────────

def _rel_if_ours(path) -> str | None:
    try:
        p = os.path.abspath(str(path))
    except Exception:
        return None
    if not p.startswith(REPO):
        return None
    if any(part in p for part in SKIP_PARTS):
        return None
    return os.path.relpath(p, REPO).replace("\\", "/")


def _audit(name: str, args) -> None:
    """THE HOOK. It may never raise, and it may never open a file.

    An audit hook runs inside the interpreter's own event path, on every open, in
    every thread. An exception here does not fail a step — it fails the operation
    that triggered the hook, anywhere in the process, including inside the
    supervisor's own writes. So the whole body is wrapped, it does no I/O of its
    own, and its only action is queue.put_nowait. If that queue is full the sample
    is dropped and counted; a recorder that blocks the thing it records is not a
    recorder.
    """
    try:
        if not _state["on"]:
            return
        if name == "open":
            mode = args[1] if len(args) > 1 else ""
            if not mode or not any(c in str(mode) for c in "wax+"):
                return
            rel = _rel_if_ours(args[0])
            if rel is None:
                return
            event("touch", {"ev": "open-" + str(mode)[:3], "path": rel})
        elif name in ("os.rename", "os.replace"):
            rel = _rel_if_ours(args[1] if len(args) > 1 else args[0])
            if rel is None:
                return
            event("touch", {"ev": "rename", "path": rel})
        elif name == "os.remove":
            rel = _rel_if_ours(args[0])
            if rel is None:
                return
            event("touch", {"ev": "remove", "path": rel})
        elif name == "os.mkdir":
            rel = _rel_if_ours(args[0])
            if rel is None:
                return
            event("touch", {"ev": "mkdir", "path": rel})
        elif name == "subprocess.Popen":
            argv = args[1] if len(args) > 1 else args[0]
            if isinstance(argv, (list, tuple)):
                head = [str(a)[:80] for a in list(argv)[:ARGV_HEAD]]
            else:
                head = [str(argv)[:80]]
            event("spawn", {"argv": head, "pid": None})
        elif name == "socket.connect":
            addr = args[1] if len(args) > 1 else None
            if isinstance(addr, tuple) and len(addr) >= 2:
                event("connect", {"host": str(addr[0])[:80], "port": addr[1]})
        elif name == "urllib.Request":
            url = str(args[0])[:200] if args else ""
            event("connect", {"host": url.split("/")[2] if "//" in url else url,
                              "port": None})
    except Exception:
        pass


# ── CHANNEL C: per-call tracing, OFF unless asked ─────────────────────────────

def _maybe_start_calls() -> bool:
    """sys.monitoring PY_START/PY_RETURN/RAISE, only under CORTEX_TRACE_CALLS=1.

    Off by default and deliberately so: this is the one channel whose cost scales
    with how much the code does rather than with how long it runs.
    """
    if os.environ.get("CORTEX_TRACE_CALLS") != "1":
        return False
    try:
        mon = sys.monitoring
        tool = mon.PROFILER_ID
        mon.use_tool_id(tool, "cortex_flight_recorder")

        def _py_start(code, offset):
            try:
                f = code.co_filename
                if not f.startswith(REPO) or any(p in f for p in SKIP_PARTS):
                    return mon.DISABLE
                event("call", {"where": os.path.relpath(f, REPO).replace("\\", "/")
                               + ":" + str(code.co_firstlineno) + ":" + code.co_name})
            except Exception:
                return mon.DISABLE

        mon.register_callback(tool, mon.events.PY_START, _py_start)
        mon.set_events(tool, mon.events.PY_START)
        return True
    except Exception:
        return False


# ── spans ─────────────────────────────────────────────────────────────────────

def open_span(name: str, attr: dict | None = None, parent=None) -> str:
    """Write the 'open' row synchronously and return the span id."""
    if not _state["on"]:
        return ""
    sp = _sid()
    pa = parent if parent is not None else _CURRENT.get()
    _emit_sync({"k": "open", "sp": sp, "pa": pa, "name": name, "t": _now(),
                "attr": dict(attr or {})})
    return sp


def close_span(sp: str, t_open: float, name: str, parent, st: str = "OK",
               attr: dict | None = None) -> None:
    if not _state["on"] or not sp:
        return
    t_end = _now()
    _emit_sync({"k": "span", "sp": sp, "pa": parent, "name": name, "t": t_open,
                "t_end": t_end, "ms": int(round((t_end - t_open) * 1000)),
                "st": st, "attr": dict(attr or {})})


class span:
    """Context manager. An exception closes the span ERROR and re-raises.

    RE-RAISES, deliberately. The recorder observes; it does not decide whether a
    step survives. Swallowing here would turn a crashed step into a clean one in
    both the record and the run.
    """

    def __init__(self, name: str, attr: dict | None = None):
        self.name, self.attr = name, dict(attr or {})
        self.sp = ""
        self.t = 0.0
        self.token = None
        self.parent = None

    def __enter__(self):
        global _CURRENT_STEP
        if not _state["on"]:
            return self
        self.parent = _CURRENT.get() or _CURRENT_STEP
        self.t = _now()
        self.sp = open_span(self.name, self.attr, self.parent)
        self.token = _CURRENT.set(self.sp)
        # Only a step is published process-wide; see the note beside _CURRENT_STEP.
        self.is_step = self.name.startswith("step:")
        if self.is_step:
            _STEP_STACK.append(_CURRENT_STEP)
            _CURRENT_STEP = self.sp
        return self

    def __exit__(self, et, ev, tb):
        if not _state["on"] or not self.sp:
            return False
        attr = dict(self.attr)
        st = "OK"
        if et is not None:
            st = "ERROR"
            attr["error_type"] = getattr(et, "__name__", str(et))
            attr["error"] = ("".join(traceback.format_exception_only(et, ev))
                             .strip()[:ERR_CHARS])
        close_span(self.sp, self.t, self.name, self.parent, st, attr)
        if self.token is not None:
            _CURRENT.reset(self.token)
        if getattr(self, "is_step", False):
            global _CURRENT_STEP
            _CURRENT_STEP = _STEP_STACK.pop() if _STEP_STACK else None
        return False


# ── lifecycle ─────────────────────────────────────────────────────────────────

def start(cycle_id=None) -> str | None:
    """Begin recording. Safe to call twice; the second call is a no-op."""
    if _state["on"]:
        return _state["path"]
    _state["t0"] = time.time()
    _state["stopping"].clear()
    _state["q"] = queue.Queue(maxsize=20000)
    _state["main_thread_id"] = threading.main_thread().ident
    _state["lines"] = 0
    _state["buffer"] = []
    _state["dropped"] = 0
    _state["last_t"] = 0.0
    global _CURRENT_STEP
    _CURRENT_STEP = None
    _STEP_STACK.clear()
    _state["on"] = True

    THREAD_ERRORS.clear()
    _prev_hook = threading.excepthook

    def _thread_died(args):
        try:
            if str(args.thread.name).startswith("fr-"):
                THREAD_ERRORS.append(
                    f"{args.thread.name}: {args.exc_type.__name__}: {args.exc_value}")
        except Exception:
            pass
        return _prev_hook(args)

    threading.excepthook = _thread_died

    calls_on = _maybe_start_calls()
    _state["channels"] = ["pulse", "audit"] + (["calls"] if calls_on else [])

    _state["writer"] = threading.Thread(target=_writer_loop, name="fr-writer",
                                        daemon=True)
    _state["writer"].start()
    _state["pulser"] = threading.Thread(target=_pulse_loop, name="fr-pulse",
                                        daemon=True)
    _state["pulser"].start()

    if not _state["hook_installed"]:
        try:
            sys.addaudithook(_audit)
            _state["hook_installed"] = True
        except Exception:
            pass

    if cycle_id is not None:
        _open_file(cycle_id)
    else:
        threading.Timer(BUFFER_SEC, _fallback_name).start()
    return _state["path"]


def _fallback_name() -> None:
    with _state["lock"]:
        if _state["on"] and _state["fh"] is None:
            _open_file("provisional-" + time.strftime("%Y%m%dT%H%M%S",
                                                      time.gmtime(_state["t0"])))


def adopt(cycle_id) -> str | None:
    """Name the trace once the cycle knows its own id.

    start() runs before the runner has decided anything, which is the point: the
    imports it performs are part of the night. Rows written before this land in a
    small buffer and are replayed into the file the moment the name exists.
    """
    with _state["lock"]:
        if not _state["on"]:
            return None
        if _state["fh"] is None:
            _open_file(cycle_id)
        else:
            _emit_sync({"k": "ev", "sp": None, "name": "cycle_id_late",
                        "t": _now(), "attr": {"cycle_id": str(cycle_id),
                                              "file_named": _state["cycle_id"], "n": 1}})
    return _state["path"]


def stop(status: str = "OK") -> None:
    if not _state["on"]:
        return
    _state["stopping"].set()
    # ONE sentinel, and BARE. The first version also queued it as (None, _SENTINEL);
    # the loop unpacked that as an ordinary item, the sentinel ended up in `pending`,
    # and the writer thread died on the drain with AttributeError — while the
    # selftest still printed VERDICT: OK, because everything it checked had already
    # been written. A recorder whose writer is dead and whose verdict is green is
    # the exact failure this module exists to make impossible.
    try:
        _state["q"].put(_SENTINEL, timeout=1.0)
    except Exception:
        pass
    w = _state["writer"]
    if w is not None:
        w.join(timeout=5.0)
    with _state["lock"]:
        if _state["fh"] is None and _state["buffer"]:
            _open_file("provisional-" + time.strftime("%Y%m%dT%H%M%S",
                                                      time.gmtime(_state["t0"])))
        _write_now({"k": "ev", "sp": None, "name": "recorder_stop", "t": _now(),
                    "attr": {"status": status, "lines": _state["lines"],
                             "dropped": _state["dropped"], "n": 1}})
        fh = _state["fh"]
        if fh is not None:
            try:
                fh.flush()
                os.fsync(fh.fileno())
                fh.close()
            except Exception:
                pass
        _state["fh"] = None
    _state["on"] = False


def path() -> str | None:
    return _state["path"]


def is_on() -> bool:
    return bool(_state["on"])


# ── selftest ──────────────────────────────────────────────────────────────────

def _selftest() -> int:
    import tempfile
    print("core/flight_recorder --selftest")
    global TRACE_DIR
    TRACE_DIR = tempfile.mkdtemp()
    p = start("selftest-" + str(os.getpid()))
    print("  trace file           :", p)
    with span("cycle", {"source": "selftest"}):
        with span("step:demo", {"step": "demo", "index": "0", "source": "_run"}):
            f = os.path.join(REPO, "memory", "cycle_trace", "_selftest_touch.tmp")
            try:
                os.makedirs(os.path.dirname(f), exist_ok=True)
                open(f, "w", encoding="utf-8").write("x")
                os.remove(f)
            except Exception:
                pass
            time.sleep(2.5)
        try:
            with span("step:boom", {"step": "boom"}):
                raise ValueError("deliberate")
        except ValueError:
            pass
    stop()
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    kinds = {}
    for r in rows:
        kinds[r["k"]] = kinds.get(r["k"], 0) + 1
    print("  rows                 :", len(rows), kinds)
    opens = {r["sp"] for r in rows if r["k"] == "open"}
    spans = {r["sp"] for r in rows if r["k"] == "span"}
    print("  every span has an open:", spans <= opens)
    print("  unclosed spans        :", sorted(opens - spans) or "none")
    err = [r for r in rows if r["k"] == "span" and r["st"] == "ERROR"]
    print("  ERROR span recorded   :", bool(err),
          err[0]["attr"].get("error_type") if err else "")
    pulses = [r for r in rows if r.get("name") == "pulse"]
    print("  pulse rows            :", len(pulses),
          "(coalesced n:", sum(r["attr"].get("n", 1) for r in pulses), ")")
    print("  recorder threads died :", THREAD_ERRORS or "none")
    ok = bool(spans) and spans <= opens and bool(err) and not THREAD_ERRORS
    print("  VERDICT               :", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
