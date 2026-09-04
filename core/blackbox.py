"""
core/blackbox.py — the cycle's flight recorder.

WHY THIS EXISTS
    On 30 Aug 2026 the nightly cycle died at the survival gate and left nothing
    readable. Six nights later its cause is still genuinely unknown, because there
    is no record of where it was when it stopped. Open item (3) says 31 of 66 cycle
    steps do not go through _run() and leave no trace at all.

DESIGN RULES, in order of importance
    1. IT CAN NEVER BREAK THE CYCLE. Every public function swallows every exception.
       If the recorder fails, the cycle continues as if it were not installed.
       A diagnostic that can kill the thing it observes is worse than no diagnostic.
    2. IT DOES NOT RELY ON CATCHING THE DEATH. Signal handlers and atexit miss a
       hard TerminateProcess, an OOM kill, and a power loss. So every line is
       written, flushed and fsync'd immediately. Whatever happens, the last line
       already survived. The exit hooks are a bonus, not the mechanism.
    3. IT IS CHEAP. One short line per step, and the GPU is polled at most once
       every GPU_MIN_INTERVAL seconds, because nvidia-smi costs ~100 ms.

READING IT AFTER A DEATH
    The last line names the step the cycle was inside. If the final line is a
    "begin" with no matching "end", that step is where it died. If an "exit" line
    exists, the death was orderly and its reason is recorded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

LOG_PATH = os.path.join("memory", "blackbox.jsonl")
GPU_MIN_INTERVAL = 20.0

_t0 = time.time()
_last_gpu_t = 0.0
_last_gpu_v = None
_installed = False


def _rss_and_avail() -> tuple[float | None, float | None]:
    try:
        import psutil

        p = psutil.Process()
        return (
            round(p.memory_info().rss / 2**20, 1),
            round(psutil.virtual_memory().available / 2**20, 1),
        )
    except Exception:
        return None, None


def _gpu_mib() -> int | None:
    """Polled sparingly: nvidia-smi costs ~100 ms and the cycle has 66 steps."""
    global _last_gpu_t, _last_gpu_v
    now = time.time()
    if now - _last_gpu_t < GPU_MIN_INTERVAL:
        return _last_gpu_v
    _last_gpu_t = now
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _last_gpu_v = int(out.stdout.strip().splitlines()[0]) if out.returncode == 0 else None
    except Exception:
        _last_gpu_v = None
    return _last_gpu_v


def record(step: str, phase: str = "mark", **extra) -> None:
    """Append one durable line. Never raises, whatever goes wrong inside."""
    try:
        rss, avail = _rss_and_avail()
        row = {
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_s": round(time.time() - _t0, 1),
            "pid": os.getpid(),
            "step": step,
            "phase": phase,
            "rss_mb": rss,
            "avail_mb": avail,
            "gpu_mib": _gpu_mib(),
        }
        if extra:
            row.update(extra)
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        # Durability is the whole point: a line that is only in a buffer does not
        # exist once the process is killed. flush + fsync on every line, always.
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        pass  # rule 1


class step:
    """Context manager: records begin and end, and records the exception if one escapes.

    A 'begin' with no matching 'end' in the log IS the finding - that is the step
    the process was inside when it stopped.
    """

    def __init__(self, name: str, **extra):
        self.name, self.extra = name, extra

    def __enter__(self):
        record(self.name, "begin", **self.extra)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            record(self.name, "end")
        else:
            record(self.name, "error", error_type=exc_type.__name__, error=str(exc)[:300])
        return False  # never swallow the cycle's own exceptions


def install_exit_hooks(label: str = "cycle") -> None:
    """Best-effort exit reasons. A hard kill catches none of these - that is expected,
    and is why every line is fsync'd rather than buffered until exit."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        import atexit
        import signal

        record(label, "start", argv=" ".join(sys.argv[:6]))
        atexit.register(lambda: record(label, "exit", reason="atexit"))

        def _sig(signum, frame):
            record(label, "exit", reason=f"signal_{signum}")
            sys.exit(128 + signum)

        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            s = getattr(signal, name, None)
            if s is not None:
                try:
                    signal.signal(s, _sig)
                except Exception:
                    pass

        prev = sys.excepthook

        def _hook(et, ev, tb):
            record(label, "exit", reason="uncaught", error_type=et.__name__, error=str(ev)[:300])
            prev(et, ev, tb)

        sys.excepthook = _hook
    except Exception:
        pass  # rule 1
