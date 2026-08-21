#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/body_sensorium.py — STAGE 0: THE BODY'S RAW FEED. NUMBERS ONLY.

WHAT THIS IS
-------------
One JSON row per supervisor tick, appended to a daily file, describing the
machine this system runs on: CPU load, RAM, disk free, network throughput,
battery and AC state, GPU VRAM, process count, and per-core temperatures where
the platform exposes them.

WHY IT IS CONTINUOUS AND NOT ON DEMAND
---------------------------------------
agents/body/body_scanner.py already answers "how is the machine RIGHT NOW",
once per cycle, at the moment it is asked. That is a glance, not a sense. It
cannot say whether RAM has been at 96% for an hour or arrived there in the last
ninety seconds, and those are different facts with different actions attached.
Hunger is not a query you run; it is a signal that is already there when you
think to check. The supervisor already ticks every five minutes, so this rides
that tick and costs one file append.

STAGE 0 IS NUMBERS ONLY — AND THAT IS A BOUNDARY, NOT A BACKLOG
-----------------------------------------------------------------
No audio. No images. No screen capture. No microphone, no camera, no EM. Not
"not yet implemented" — deliberately absent, and they stay absent until the
physical-switch design is agreed with Emil. A sensor that can be enabled by
editing a config is a sensor that can be enabled by a patch. Everything in this
file is a scalar reading of the host's own resource state, of the kind any task
manager displays.

WHAT IS ABSENT IS NAMED
------------------------
psutil.sensors_temperatures() does not exist on Windows — it is a Linux-only
API. A reading that cannot be taken is recorded in `unavailable` WITH ITS
REASON, rather than as a missing key or, worse, as a zero. "no per-core
temperature" and "per-core temperature is 0 C" are opposite claims and only one
of them is true here.

RATE ACROSS PROCESSES
----------------------
A supervisor tick is a short-lived process: it starts, decides, exits. So a
network RATE cannot be computed from two samples in memory — there is no second
sample. The previous counters and their timestamp are kept in _last.json beside
the daily files, and the first tick after a boot honestly reports no rate rather
than dividing by an interval it does not know.

    venv\\Scripts\\python.exe core/body_sensorium.py --selftest
    venv\\Scripts\\python.exe core/body_sensorium.py --tick
    venv\\Scripts\\python.exe core/body_sensorium.py --show
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

# NOT memory/sensorium/ — that directory is already occupied by
# experiments/sensorium/sensorium.py, which keeps a Merkle-committed chain of
# sensory drops there (_merkle_leaves.jsonl, _merkle_root.json). Dropping daily
# telemetry files into a tamper-evident chain's directory would confuse the
# audit and the reader both. Different sense, different name.
SENSE_DIR = BASE / "memory" / "body_sensorium"
STATE = SENSE_DIR / "_last.json"

RETENTION_DAYS = 14

# ── REQUIRES ────────────────────────────────────────────────────────────────
# What this module reads to do its job, declared rather than left to be inferred
# from the imports.
#
# NOT in config/step_inputs.json, and that is deliberate: that file is in
# safety/protected_paths.py — the ONE place a step can be handed provenance it
# did not earn from a scan, and therefore the one file a machine must never
# write. This declaration belongs to the module, so adding it does not require
# touching a human-owned file. If body_sensorium ever becomes a step of its own
# whose inputs the notary must grade, Emil adds the entry there by hand.
REQUIRES = {
    "psutil": "cpu, ram, disk, net counters, battery, process count "
              "(REQUIRED — without it the sample is empty and says so)",
    "nvidia-smi": "GPU VRAM used/total. OPTIONAL: absent on a machine with no "
                  "NVIDIA GPU, and its absence is recorded, not guessed",
    "memory/body_sensorium/_last.json": "the previous tick's network counters "
                                        "and timestamp, for the byte rate",
}

# ── FOOTPRINT ───────────────────────────────────────────────────────────────
# What tick() writes. core/step_contract.py measures a step by the files it
# touched under WATCHED, and "memory" is watched, so these land in the footprint
# without any registration.
#
# Note WHO writes them: the SUPERVISOR's tick, not a cycle step. body_scan only
# READS this sense (agents/body/body_scanner.scan attaches latest() and
# trend()), so body_scan's own footprint is unchanged by this wiring — it did
# not start writing anything new, it started knowing something it did not know.
PRODUCES = (
    "memory/body_sensorium/<YYYY-MM-DD>.jsonl",
    "memory/body_sensorium/_last.json",
)

GPU_TIMEOUT_SEC = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_file(when: datetime | None = None,
              base: pathlib.Path | None = None) -> pathlib.Path:
    d = (base or SENSE_DIR)
    return d / f"{(when or _now()):%Y-%m-%d}.jsonl"


# ---------------------------------------------------------------------------
# The readings
# ---------------------------------------------------------------------------

def _gpu() -> tuple:
    """(vram_used_mb, vram_total_mb) or (None, reason)."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=GPU_TIMEOUT_SEC)
    except FileNotFoundError:
        return None, "nvidia-smi is not on PATH (no NVIDIA GPU, or no driver)"
    except subprocess.TimeoutExpired:
        return None, f"nvidia-smi did not answer in {GPU_TIMEOUT_SEC}s"
    except Exception as exc:                          # noqa: BLE001
        return None, f"nvidia-smi failed: {type(exc).__name__}"
    line = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0 or not line:
        return None, f"nvidia-smi exited {proc.returncode} with no reading"
    try:
        used, total = (int(x.strip()) for x in line[0].split(",")[:2])
        return (used, total), None
    except (ValueError, IndexError):
        return None, f"nvidia-smi answered unparseably: {line[0][:60]!r}"


def _temps() -> tuple:
    """Per-core temperatures, or (None, why not)."""
    try:
        import psutil
    except Exception:
        return None, "psutil is not installed"
    fn = getattr(psutil, "sensors_temperatures", None)
    if fn is None:
        return None, ("psutil.sensors_temperatures() does not exist on this "
                      "platform — it is Linux-only; Windows exposes no per-core "
                      "temperature through psutil")
    try:
        raw = fn()
    except Exception as exc:                          # noqa: BLE001
        return None, f"sensors_temperatures() raised {type(exc).__name__}"
    if not raw:
        return None, "the platform exposes no thermal zones"
    out = {}
    for chip, entries in raw.items():
        vals = [round(float(e.current), 1) for e in entries
                if getattr(e, "current", None) is not None]
        if vals:
            out[str(chip)] = vals
    return (out or None), (None if out else "thermal zones present but empty")


def sample(state_path: pathlib.Path | None = None) -> dict:
    """One row. Numbers only. Never raises.

    Every reading that could not be taken lands in `unavailable` with the reason
    — a missing key and a zero are both lies, and the second is the worse one.
    """
    row: dict = {"ts": _now().isoformat()}
    missing: dict = {}

    try:
        import psutil
    except Exception as exc:                          # noqa: BLE001
        row["unavailable"] = {"psutil": f"not importable: {type(exc).__name__}"}
        return row

    # CPU. interval=None is the non-blocking form: it reports load since the
    # PREVIOUS call in this process. A short-lived tick has no previous call, so
    # a small blocking interval is used — 0.3 s of a five-minute tick.
    try:
        row["cpu_pct"] = round(psutil.cpu_percent(interval=0.3), 1)
        row["cpu_count"] = psutil.cpu_count()
    except Exception as exc:                          # noqa: BLE001
        missing["cpu"] = type(exc).__name__

    try:
        vm = psutil.virtual_memory()
        row["ram_pct"] = round(vm.percent, 1)
        row["ram_available_mb"] = round(vm.available / 2**20, 1)
        row["ram_total_mb"] = round(vm.total / 2**20, 1)
    except Exception as exc:                          # noqa: BLE001
        missing["ram"] = type(exc).__name__

    try:
        du = psutil.disk_usage(str(BASE))
        row["disk_free_mb"] = round(du.free / 2**20, 1)
        row["disk_pct"] = round(du.percent, 1)
    except Exception as exc:                          # noqa: BLE001
        missing["disk"] = type(exc).__name__

    try:
        row["process_count"] = len(psutil.pids())
    except Exception as exc:                          # noqa: BLE001
        missing["process_count"] = type(exc).__name__

    try:
        bat = psutil.sensors_battery()
        if bat is None:
            missing["battery"] = "no battery on this machine (desktop or VM)"
        else:
            row["battery_pct"] = round(float(bat.percent), 1)
            row["on_ac"] = 1 if bat.power_plugged else 0
            secs = getattr(bat, "secsleft", None)
            # psutil signals "unlimited" and "unknown" with negative sentinels.
            # Writing -2 into a seconds field would read as a measurement.
            if isinstance(secs, int) and secs >= 0:
                row["battery_secs_left"] = secs
    except Exception as exc:                          # noqa: BLE001
        missing["battery"] = type(exc).__name__

    # Network, as a RATE, across process boundaries. See the module docstring.
    try:
        net = psutil.net_io_counters()
        row["net_sent_total"] = int(net.bytes_sent)
        row["net_recv_total"] = int(net.bytes_recv)
        prev = _read_state(state_path)
        now_ts = _now().timestamp()
        if prev:
            dt = now_ts - float(prev.get("ts_epoch", 0))
            # A counter that went DOWN means the interface was reset or the
            # machine rebooted. A negative rate is not a slow network.
            if (dt > 0.5
                    and net.bytes_sent >= prev.get("net_sent_total", 0)
                    and net.bytes_recv >= prev.get("net_recv_total", 0)):
                row["net_sent_bps"] = round(
                    (net.bytes_sent - prev["net_sent_total"]) / dt, 1)
                row["net_recv_bps"] = round(
                    (net.bytes_recv - prev["net_recv_total"]) / dt, 1)
                row["net_interval_sec"] = round(dt, 1)
            else:
                missing["net_rate"] = ("counters reset or the interval was too "
                                       "short — no rate, rather than a wrong one")
        else:
            missing["net_rate"] = "first tick since boot — no previous counters"
        _write_state({"ts_epoch": now_ts,
                      "net_sent_total": int(net.bytes_sent),
                      "net_recv_total": int(net.bytes_recv)}, state_path)
    except Exception as exc:                          # noqa: BLE001
        missing["net"] = type(exc).__name__

    gpu, why = _gpu()
    if gpu:
        row["gpu_vram_used_mb"], row["gpu_vram_total_mb"] = gpu
        if row["gpu_vram_total_mb"]:
            row["gpu_vram_pct"] = round(
                100.0 * row["gpu_vram_used_mb"] / row["gpu_vram_total_mb"], 1)
    else:
        missing["gpu"] = why

    temps, why = _temps()
    if temps:
        row["core_temps_c"] = temps
        flat = [v for vals in temps.values() for v in vals]
        if flat:
            row["temp_max_c"] = max(flat)
    else:
        missing["core_temps"] = why

    if missing:
        row["unavailable"] = missing
    return row


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _read_state(path: pathlib.Path | None = None) -> dict:
    try:
        return json.loads((path or STATE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(d: dict, path: pathlib.Path | None = None) -> None:
    p = path or STATE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def tick(base: pathlib.Path | None = None) -> dict:
    """Take one sample, append it, prune. Returns the row. Never raises.

    Called from the supervisor's tick, which runs whatever else happens: a
    telemetry write that could raise would be a sense that can kill its own
    body.
    """
    d = base or SENSE_DIR
    state = (d / "_last.json") if base else STATE
    try:
        row = sample(state)
    except Exception as exc:                          # noqa: BLE001
        return {"ts": _now().isoformat(),
                "unavailable": {"sample": f"{type(exc).__name__}: {exc}"}}
    try:
        d.mkdir(parents=True, exist_ok=True)
        with _day_file(base=d).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:                          # noqa: BLE001
        row.setdefault("unavailable", {})["write"] = type(exc).__name__
        return row
    try:
        prune(base=d)
    except Exception:
        pass
    return row


def prune(days: int = RETENTION_DAYS, base: pathlib.Path | None = None) -> list:
    """Delete daily files older than `days`. Returns what was deleted."""
    d = base or SENSE_DIR
    if not d.exists():
        return []
    cutoff = (_now() - timedelta(days=days)).date()
    gone = []
    for f in d.glob("*.jsonl"):
        try:
            day = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue                      # not a daily file; leave it alone
        if day < cutoff:
            try:
                f.unlink()
                gone.append(f.name)
            except OSError:
                pass
    return gone


def _rows_since(since: datetime, base: pathlib.Path | None = None) -> list:
    d = base or SENSE_DIR
    out = []
    if not d.exists():
        return out
    # Two days of files covers any window up to 24h without reading the archive.
    for when in (since, since + timedelta(days=1), _now()):
        f = _day_file(when, d)
        if not f.exists() or any(f == x for x in (r[0] for r in out[:0])):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            if ts >= since:
                out.append((f, r))
    seen, rows = set(), []
    for _f, r in out:
        if r.get("ts") in seen:
            continue
        seen.add(r.get("ts"))
        rows.append(r)
    return sorted(rows, key=lambda r: r.get("ts", ""))


def latest(base: pathlib.Path | None = None):
    """The most recent row, or None."""
    d = base or SENSE_DIR
    for when in (_now(), _now() - timedelta(days=1)):
        f = _day_file(when, d)
        if not f.exists():
            continue
        try:
            lines = [ln for ln in f.read_text(encoding="utf-8",
                                              errors="ignore").splitlines()
                     if ln.strip()]
        except OSError:
            continue
        for ln in reversed(lines):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return None


def trend(hours: float = 1.0, base: pathlib.Path | None = None) -> dict:
    """min/mean/max over the last `hours`, plus how many rows that is.

    `samples` is reported because two rows and forty rows support very different
    statements, and a mean with no n behind it invites the wrong one.
    """
    rows = _rows_since(_now() - timedelta(hours=hours), base)
    out: dict = {"window_hours": hours, "samples": len(rows)}
    if not rows:
        out["why"] = ("no rows in the window — the supervisor has not ticked "
                      "since then, or this sense has only just been wired")
        return out
    for key in ("cpu_pct", "ram_pct", "ram_available_mb", "disk_free_mb",
                "gpu_vram_pct", "temp_max_c", "net_recv_bps"):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        if not vals:
            continue
        out[f"{key}_min"] = round(min(vals), 1)
        out[f"{key}_max"] = round(max(vals), 1)
        out[f"{key}_mean"] = round(sum(vals) / len(vals), 1)
    out["oldest_ts"] = rows[0].get("ts")
    out["newest_ts"] = rows[-1].get("ts")
    on_ac = [r["on_ac"] for r in rows if "on_ac" in r]
    if on_ac:
        out["on_ac_share"] = round(sum(on_ac) / len(on_ac), 2)
    return out


def for_evidence(base: pathlib.Path | None = None) -> dict:
    """The flat facts a phase's evidence menu can cite. Numbers only, prefixed
    so they cannot be confused with a reading taken by anything else."""
    ev: dict = {}
    row = latest(base)
    if row:
        for k, v in row.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ev[f"body_{k}"] = v
        try:
            age = (_now() - datetime.fromisoformat(row["ts"])).total_seconds()
            ev["body_reading_age_sec"] = round(age, 1)
        except Exception:
            pass
        if row.get("unavailable"):
            ev["body_unavailable_count"] = len(row["unavailable"])
    t = trend(1.0, base)
    for k, v in t.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ev[f"body_1h_{k}"] = v
    return ev


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    print("core/body_sensorium.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {name}")

    for name, mod in (("psutil", "psutil"),):
        try:
            __import__(mod)
            print(f"  LIVE    {name}")
        except Exception:
            print(f"  INERT   {name} — every reading will be empty and say so")
    g, why = _gpu()
    print(f"  {'LIVE    nvidia-smi' if g else f'INERT   nvidia-smi ({why})'}")
    t, why_t = _temps()
    print(f"  {'LIVE    core temps' if t else f'INERT   core temps ({why_t})'}")

    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        r1 = tick(base=d)
        check("a tick writes a row", _day_file(base=d).exists())
        check("...with a cpu reading", isinstance(r1.get("cpu_pct"), (int, float)))
        check("...and a ram reading", isinstance(r1.get("ram_pct"), (int, float)))
        check("the first tick reports NO net rate rather than a wrong one",
              "net_sent_bps" not in r1
              and "first tick" in str((r1.get("unavailable") or {}).get("net_rate")))
        # Two ticks back to back are ~0.35 s apart (cpu_percent blocks for
        # 0.3 s), which is under the 0.5 s floor the rate guard imposes. Real
        # ticks are five MINUTES apart. Sleeping past the floor tests the
        # production path instead of lowering the guard to fit the test.
        import time as _t
        _t.sleep(0.6)
        r2 = tick(base=d)
        check("the second tick has a rate, computed across processes",
              isinstance(r2.get("net_recv_bps"), (int, float)))
        r3 = tick(base=d)          # immediately after r2, inside the floor
        check("...and a sub-floor interval yields NO rate, not a huge one",
              "net_sent_bps" not in r3)

        check("NUMBERS ONLY — no capture keys anywhere in the row",
              not any(k in json.dumps(r2).lower()
                      for k in ("audio", "image", "screenshot", "camera",
                                "microphone", "frame", "capture")))

        check("what could not be read is NAMED, not zeroed",
              all(v not in (0, "0") for v in (r2.get("unavailable") or {}).values()))

        check("latest() returns the newest row", latest(d)["ts"] == r3["ts"])
        tr = trend(1.0, d)
        check("the 1h trend sees every sample", tr["samples"] == 3)
        check("...and reports n alongside the mean",
              "cpu_pct_mean" in tr and "samples" in tr)

        ev = for_evidence(d)
        check("the evidence menu is flat numbers, all body_-prefixed",
              ev and all(k.startswith("body_") for k in ev)
              and all(isinstance(v, (int, float)) for v in ev.values()))

        old = d / "2020-01-01.jsonl"
        old.write_text('{"ts":"2020-01-01T00:00:00+00:00"}\n', encoding="utf-8")
        gone = prune(base=d)
        check("retention deletes past 14 days", "2020-01-01.jsonl" in gone)
        check("...and leaves today alone", _day_file(base=d).exists())

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--tick" in sys.argv:
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
    elif "--show" in sys.argv:
        print(json.dumps({"latest": latest(), "trend_1h": trend(1.0)},
                         ensure_ascii=False, indent=2))
    else:
        sys.exit(_selftest())
