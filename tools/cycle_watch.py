#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/cycle_watch.py — say where the night is WHILE it is there.

WHY (19 September 2026). A cycle runs 1h45m across 75 mapped steps and says
nothing a human can follow until it is over. When it dies — and it died twice on
19 September, once at 12:30:35 under memory pressure — the question "which step
was it in?" is answered by reading a 270 KB JSONL by hand.

WHAT IT READS, AND WHY TWO SOURCES

  memory/blackbox.jsonl      core/blackbox.py writes one fsync'd line per step,
                             phase=begin then phase=end. It does NOT catch the
                             death: a begin with no end IS the finding, and it is
                             the only thing that survives a hard kill. This is
                             the spine — ordering, timing, and the last line.

  memory/steps/<cid>_steps.jsonl
                             core/step_contract.py writes one row per step as it
                             exits: verdict (OK / NO_EFFECT / SLOW / MISSING /
                             RAISED / UNKNOWN), seconds, and `touched`. NO_EFFECT
                             is the silent refusal — a step that swallowed its
                             error and wrote nothing looks, in the trace alone,
                             exactly like a step that did its job. Without this
                             the status column could only ever say OK.

Neither is written by this tool. cycle_watch is READ-ONLY on memory/ and writes
only its own report under claude/reports/.

THE LINE, one per step end:

  [n/75] step | seconds | OK|DEGRADED|SKIPPED | files written | contract yes/no

A step that has begun and not ended is written IMMEDIATELY as IN PROGRESS. That
is the whole point: if the process dies, that line is the last line of the file
and it names the step the night stopped in. The completed line is appended after
it rather than replacing it, because this file is append-only and fsync'd per
line — a report that rewrites itself can lose the very record the crash created.

[n/75] IS HONEST ABOUT A GAP. core/cycle_map.py maps 75 steps; only 44 of them
reach the flight recorder, because the rest bypass _run(). The 31 that never
appear are not silently dropped: --summary lists them as NOT INSTRUMENTED, which
is a different statement from SKIPPED and must not be collapsed into it. The
recorder's own names differ from the map's (body_scanner vs body_scan), so every
name is put through cycle_map.resolve() before it is numbered.

USAGE
  venv/Scripts/python.exe tools/cycle_watch.py                  # follow live
  venv/Scripts/python.exe tools/cycle_watch.py --replay --pid N # re-render a past run
  venv/Scripts/python.exe tools/cycle_watch.py --summary        # close the file off
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BLACKBOX = REPO / "memory" / "blackbox.jsonl"
STEPS_DIR = REPO / "memory" / "steps"

# Contract verdicts that mean the step ran but did not do its job. NO_EFFECT is
# the one that matters: it returned without raising and touched nothing it
# usually touches.
DEGRADED_VERDICTS = ("NO_EFFECT", "SLOW", "MISSING", "RAISED", "DEGRADED")


def _load_map():
    """(ordered canonical names, resolve(name) -> canonical, produces(name))."""
    try:
        from core.cycle_map import STEPS as _S
        from core import cycle_map as _cm
        names = [s[0] for s in _S]

        def resolve(n):
            try:
                canon, _kind = _cm.resolve(n)
                return canon or n
            except Exception:
                return n

        def produces(n):
            try:
                return list(_cm.produces(n) or [])
            except Exception:
                return []

        return names, resolve, produces
    except Exception as e:                                   # noqa: BLE001
        print("[cycle_watch] cycle_map unavailable (%s) — numbering degrades to "
              "a running count, which is still ordered and still honest"
              % type(e).__name__, file=sys.stderr)
        return [], (lambda n: n), (lambda n: [])


def _iter_json(path: Path, offset: int):
    """Records appended since `offset`, and the new offset.

    CONSUME ONLY UP TO THE LAST NEWLINE. The first version walked
    data.split(b"\n") and counted the empty element after a trailing newline as
    one consumed byte. Every poll of a file ending in a newline therefore
    advanced the offset ONE BYTE TOO FAR, the next read began mid-line, that line
    failed json.loads, and the except swallowed it. The record was gone.

    Measured 19 Sep 2026: steps 23, 24 and 25 produced no line at all, and
    self_awareness reported 2535.8s -- its `begin` row had been eaten, so the
    duration fell through to the absolute elapsed_s of the process instead of the
    span. A drift of one byte per poll, losing whichever row it landed in.

    A partially written last line is left for the next poll rather than parsed
    into nonsense, which is the only reason this function tracks bytes at all.
    """
    if not path.exists():
        return [], offset
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    if not data:
        return [], offset
    cut = data.rfind(bytes([10]))
    if cut < 0:
        return [], offset          # nothing complete yet
    complete = data[:cut + 1]
    out = []
    for line in complete.split(bytes([10])):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line.decode("utf-8")))
        except Exception:                                    # noqa: BLE001
            pass
    return out, offset + len(complete)


class Report:
    """Append-only, fsync per line. Never rewrites what it has written."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fresh = not self.path.exists()

    def line(self, text: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip("\n") + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        print(text, flush=True)

    def header(self, note: str) -> None:
        if not self._fresh:
            return
        self.line("# CYCLE LIVE — %s" % datetime.now().astimezone().date().isoformat())
        self.line("")
        self.line("One line per step as it happens, from memory/blackbox.jsonl "
                  "(fsync'd begin/end) enriched with core/step_contract verdicts.")
        self.line("Append-only: an IN PROGRESS line is never rewritten, so if the "
                  "cycle dies the last line names the step it died in.")
        if note:
            self.line("")
            self.line(note)
        self.line("")
        self.line("```")
        self._fresh = False


def _contract_rows(cycle_file: Path | None) -> dict:
    """step -> latest contract row, by name. Read fresh on every poll."""
    if not cycle_file or not cycle_file.exists():
        return {}
    out = {}
    try:
        with open(cycle_file, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    r = json.loads(raw)
                except Exception:                            # noqa: BLE001
                    continue
                k = r.get("step") or r.get("label")
                if k:
                    out[k] = r
    except Exception:                                        # noqa: BLE001
        pass
    return out


LATEST = REPO / "memory" / "step_contract_latest.json"


def _live_contracts() -> dict:
    """This run's contract rows, from memory/step_contract_latest.json.

    NOT memory/steps/<cid>_steps.jsonl. That per-cycle file is written with the
    PREVIOUS cycle's contents at the start of a run, so during a cycle the
    newest-by-mtime file belongs to the night before. Reading it made the first
    live lines of 19 Sep report the 03:04 run's numbers: daily_tier came out as
    1.07s when this run took 0.1s. Stale numbers under a live heading are worse
    than no numbers, so the source is the file that carries a cycle_id and is
    rewritten as the run goes.
    """
    try:
        d = json.loads(LATEST.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}
    out = {}
    for r in d.get("steps") or []:
        k = r.get("step") or r.get("label")
        if k:
            out[k] = r
    return out


def _newest_steps_file() -> Path | None:
    files = sorted(glob.glob(str(STEPS_DIR / "*_steps.jsonl")), key=os.path.getmtime)
    return Path(files[-1]) if files else None


def _files_written(produced: list, t_begin: float, t_end: float) -> list:
    """Declared produces paths whose mtime falls inside the step's span.

    Declared, not scanned. A repo-wide scan was tried in this codebase before and
    misclassified whole families of files; cycle_map already states what each step
    promises, so the honest question is whether it kept THAT promise.
    """
    hits = []
    for rel in produced:
        p = REPO / rel
        try:
            if p.exists() and t_begin - 1.0 <= p.stat().st_mtime <= t_end + 1.0:
                hits.append(rel)
        except OSError:
            pass
    return hits


STILL_ACTIVE = 259


def _alive(pid: int) -> bool:
    """Is this process RUNNING -- not merely nameable.

    OpenProcess succeeding is not aliveness. Measured 19 Sep 2026 at 15:23: the
    cycle worker 16996 had exited at 15:11:38, Get-Process reported it gone, and
    OpenProcess still returned handle 312 because another process was holding a
    handle to the corpse. The first version of this function called that True, so
    --idle-stop kept resetting its timer and the watcher would have followed a
    finished cycle until its wall-clock deadline.

    GetExitCodeProcess is the actual question: a live process reports
    STILL_ACTIVE (259); anything else is its exit code.
    """
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x0400, False, int(pid))   # PROCESS_QUERY_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    except Exception:                                        # noqa: BLE001
        return os.path.exists("/proc/%d" % int(pid))


def _offset_of_current_cycle() -> int:
    """Byte offset of the last `cycle/start` row.

    NOT end-of-file. A watcher restarted mid-cycle -- which is exactly what
    happened at 13:39 on 19 Sep 2026, when this tool's own --idle-stop fired
    during the cycle's 15-minute uninstrumented prefix -- must pick up the steps
    the run has already recorded, not only the ones after the restart. Starting
    at the current cycle's own start row replays this run and nothing older.
    """
    try:
        data = BLACKBOX.read_bytes()
    except OSError:
        return 0
    # SPLIT EXACTLY AS _iter_json DOES. bytes.splitlines() also breaks on a bare
    # carriage return, and one blackbox row (earning_verifier's revocation message) carries
    # one. Counting offsets with splitlines() while reading them with
    # split on newline only, desynchronised the two by a row and sent the follower back to
    # a cycle that ended hours earlier. Measured 19 Sep 2026.
    pos, found = 0, 0
    for line in data.split(bytes([10])):
        if b'"step": "cycle"' in line and b'"phase": "start"' in line:
            found = pos
        pos += len(line) + 1
    return found


def _ts(rec) -> float:
    try:
        return datetime.strptime(rec["utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:                                        # noqa: BLE001
        return time.time()


def run(out_path: Path, replay_pid=None, poll=3.0, idle_stop=None, note="",
        watch_pid=None):
    names, resolve, produces = _load_map()
    total = len(names) or 75
    index = {n: i + 1 for i, n in enumerate(names)}

    rep = Report(out_path)
    rep.header(note)

    # LIVE STARTS AT THE END OF THE FILE. memory/blackbox.jsonl is 270 KB of
    # previous nights; following from byte 0 would replay every one of them as if
    # it were happening now. Replay is the mode that wants history, and it says so.
    offset = 0
    if replay_pid is None:
        offset = _offset_of_current_cycle()
    open_steps = {}
    _open_elapsed = {}          # canonical -> (begin_ts, raw_name)
    done = []                # canonical names, in completion order
    announced = set()        # canonical names already written as IN PROGRESS
    seen_any = False
    last_change = time.time()

    while True:
        recs, offset = _iter_json(BLACKBOX, offset)
        if recs:
            last_change = time.time()
        contracts = _live_contracts()

        for r in recs:
            if replay_pid is not None and r.get("pid") != replay_pid:
                continue
            phase = r.get("phase")
            step = r.get("step")
            if not step or step == "cycle":
                if step == "cycle" and phase in ("start", "exit"):
                    seen_any = True
                continue

            canon = resolve(step)

            if phase == "begin":
                open_steps[canon] = (_ts(r), step)
                _open_elapsed[canon] = r.get("elapsed_s") or 0
                if canon not in announced:
                    announced.add(canon)
                    n = index.get(canon, len(done) + 1)
                    rep.line("[%2d/%d] %-28s | IN PROGRESS%s"
                             % (n, total, canon,
                                "" if canon == step else "  (recorded as %s)" % step))

            elif phase == "end":
                t0, raw_name = open_steps.pop(canon, (None, step))
                t1 = _ts(r)
                secs = r.get("elapsed_s")
                row = contracts.get(raw_name) or contracts.get(canon) or {}
                # THE SPAN THIS RUN RECORDED WINS. elapsed_s is the runner's own
                # clock for this process; a contract row can belong to another
                # cycle, and if it does its seconds are a different night's.
                b0, b1 = r.get("elapsed_s"), None
                if t0 is not None and isinstance(b0, (int, float)):
                    b1 = round(b0 - _open_elapsed.get(canon, b0), 1)
                if b1 is not None:
                    secs = b1
                elif row.get("seconds") is not None:
                    secs = row["seconds"]
                elif t0 is not None:
                    secs = round(t1 - t0, 1)

                verdict = row.get("verdict")
                if verdict in DEGRADED_VERDICTS or row.get("degraded"):
                    status = "DEGRADED"
                elif verdict in (None, ""):
                    status = "OK"
                elif verdict == "UNKNOWN":
                    status = "OK"
                else:
                    status = "OK"

                touched = row.get("touched")
                if isinstance(touched, list) and touched:
                    written = [str(x) for x in touched][:6]
                else:
                    written = _files_written(produces(canon),
                                             t0 if t0 is not None else t1, t1)
                files = ", ".join(written) if written else "-"

                has_contract = "yes" if row else "no"
                why = row.get("why") or ""
                n = index.get(canon, len(done) + 1)
                done.append(canon)
                rep.line("[%2d/%d] %-28s | %7ss | %-8s | %s | contract %s%s"
                         % (n, total, canon,
                            secs if secs is not None else "?",
                            status, files, has_contract,
                            ("  <- " + str(why)[:90]) if status == "DEGRADED" and why else ""))

            elif phase in ("error", "lift_revoked"):
                rep.line("       %-28s | %s | %s"
                         % (resolve(step), phase.upper(),
                            str(r.get("why") or r.get("reason") or "")[:100]))

        if replay_pid is not None and not recs:
            break
        # AN IDLE BLACKBOX IS NOT A FINISHED CYCLE. 31 of the 75 steps emit no
        # begin/end, and the run of 19 Sep spent its first 15 minutes entirely
        # inside them -- long enough for a 900s idle-stop to fire and close the
        # report while the cycle was still in web_intelligence. Silence means
        # "in an uninstrumented step" at least as often as it means "over", so
        # liveness is asked of the PROCESS, never inferred from the file.
        if idle_stop and watch_pid and _alive(watch_pid):
            last_change = time.time()
        if idle_stop and time.time() - last_change > idle_stop:
            rep.line("")
            rep.line("[cycle_watch] no new blackbox rows for %ds — stopping the "
                     "follow. Steps still open: %s"
                     % (idle_stop, ", ".join(sorted(open_steps)) or "none"))
            break
        if replay_pid is None:
            time.sleep(poll)

    return done, open_steps, names, seen_any


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--replay", action="store_true",
                    help="render an already-finished run instead of following")
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--poll", type=float, default=3.0)
    ap.add_argument("--idle-stop", type=int, default=None,
                    help="stop after N seconds with no new blackbox rows")
    ap.add_argument("--note", default="")
    ap.add_argument("--summary", action="store_true",
                    help="write only the close-out for the recorded run and "
                         "exit; used when a follower has already been stopped")
    ap.add_argument("--watch-pid", type=int, default=None,
                    help="the cycle process; while it is alive, --idle-stop is "
                         "held off, because silence means an uninstrumented step")
    a = ap.parse_args()

    out = Path(a.out) if a.out else (
        REPO / "claude" / "reports"
        / ("CYCLE_LIVE_%s.md" % datetime.now().astimezone().date().isoformat()))

    if a.summary:
        # Close out from the recorded run without following anything. The
        # sequence is already on disk in memory/blackbox.jsonl; this reads it
        # once and writes the verdict block.
        names, resolve, _p = _load_map()
        recs, _ = _iter_json(BLACKBOX, _offset_of_current_cycle())
        done, open_steps = [], {}
        for r in recs:
            st = r.get("step")
            if not st or st == "cycle":
                continue
            canon = resolve(st)
            if r.get("phase") == "begin":
                open_steps[canon] = True
            elif r.get("phase") == "end":
                open_steps.pop(canon, None)
                if canon not in done:
                    done.append(canon)
    else:
        done, open_steps, names, _ = run(
            out, replay_pid=(a.pid if a.replay else None),
            poll=a.poll, idle_stop=a.idle_stop, note=a.note,
            watch_pid=a.watch_pid)

    rep = Report(out)
    rep.line("```")
    rep.line("")
    rep.line("## Close-out")
    rep.line("")
    rep.line("- steps that ENDED: **%d**" % len(done))
    if open_steps:
        rep.line("- **began and never ended: %s** — this is where it stopped."
                 % ", ".join(sorted(open_steps)))
    else:
        rep.line("- began and never ended: none")

    # NOT INSTRUMENTED is not SKIPPED. Saying so is the whole point of the line.
    if names:
        never = [n for n in names if n not in set(done) and n not in open_steps]
        rep.line("- mapped in core/cycle_map.py but NOT INSTRUMENTED (they bypass "
                 "_run(), so the flight recorder never sees them — this is a "
                 "blind spot, NOT a claim that they were skipped): **%d**"
                 % len(never))
        for n in never:
            rep.line("    - %s" % n)


if __name__ == "__main__":
    main()
