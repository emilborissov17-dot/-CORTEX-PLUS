#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/somatic.py — A HEATMAP OF BARS. NOT A BODY.

WHY BARS AND NOT A SILHOUETTE
-------------------------------
An anthropomorphic body diagram would put a "heart" where the CPU is and invite
the reader to feel something about a number. These are machine sensors: battery
percent, GPU degrees, Wi-Fi RSSI, page faults. A terminal heatmap of grouped
bars says what they are. The moment a reading is drawn as an organ, the reader
starts reasoning about the organ instead of the reading.

EVERY ROW IS TAGGED source:hardware, reflexivity:0
-----------------------------------------------------
reflexivity is 0 for everything in this module, without exception. It rises only
when the 3b compresses a reading into a glyph — that is, when something has
INTERPRETED it. A raw sensor value has no interpretation in it, and tagging it
otherwise would make the interpretation invisible later, which is the whole
reason the tag exists.

NOT AVAILABLE IS A RESULT, NOT A GAP TO FILL WITH ZERO
--------------------------------------------------------
Every probe returns available=False with a REASON when this machine cannot
answer, and the API ships the NOT-AVAILABLE list beside the readings. A sensor
that returns 0.0 because it could not be read is indistinguishable from a sensor
that read 0.0, and this repo has spent months on exactly that class of bug.

MIC AND CAMERA ARE OFF BY DEFAULT
-----------------------------------
Each has its own toggle, each reads DISABLED when off, and the gates hold
regardless of the toggle:

  * camera frames are local-only. They never leave the machine, never enter the
    columns, and are never stored. Only derived SCALARS are kept — lux and a
    motion MSE. The frame is discarded in the same function that computed them.
  * the mic stores an RMS scalar only. Never a sample, never a spectrum, never a
    buffer. A short ultrasonic spike is guarded against by requiring the RMS to
    persist across consecutive windows before it is reported as a level, so a
    click cannot be logged as a room.

No camera and no microphone is activated while a cycle is running: probe()
refuses both when memory/cycle.lock names a live pid, and says so.

    venv/Scripts/python.exe -m cockpit.somatic --probe
    venv/Scripts/python.exe -m cockpit.somatic --selftest
"""
from __future__ import annotations

import ctypes
import json
import os
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
LOCK = BASE / "memory" / "cycle.lock"

SOURCE_TAG = "hardware"
REFLEXIVITY = 0

# The 25-dimensional state vector, VERSION TAGGED. If this list is extended the
# migration is logged by cockpit.lexicon.log_migration() rather than applied
# silently: Δ7 under v1 and Δ7 under v2 are different states that share an index.
VECTOR_VERSION = "v1"
VECTOR_FIELDS = (
    "battery_percent", "power_plugged", "uptime_hours",
    "gpu_temp_c", "gpu_power_w", "gpu_util_pct", "gpu_mem_used_mb",
    "cpu_percent", "cpu_freq_mhz", "load_1",
    "ram_percent", "ram_used_gb", "swap_percent", "page_faults",
    "disk_read_mb", "disk_write_mb", "open_handles",
    "net_sent_mb", "net_recv_mb",
    "wifi_signal_pct", "gateway_ping_ms", "connections",
    "idle_seconds", "brightness_pct", "event_log_errors",
)
assert len(VECTOR_FIELDS) == 25, "the state vector is 25-dimensional by contract"

GROUPS = ("ENERGY", "THERMAL", "COMPUTE", "MEMORY", "STORAGE", "NETWORK",
          "PERIPHERY", "ACOUSTIC", "OPTIC", "LOGS")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Reading:
    """One sensor row."""
    group: str
    key: str
    value: object = None
    unit: str = ""
    available: bool = True
    reason: str = ""
    disabled: bool = False
    source: str = SOURCE_TAG
    reflexivity: int = REFLEXIVITY

    def as_dict(self) -> dict:
        return {"group": self.group, "key": self.key, "value": self.value,
                "unit": self.unit, "available": self.available,
                "reason": self.reason, "disabled": self.disabled,
                "source": self.source, "reflexivity": self.reflexivity}


def _na(group: str, key: str, reason: str, unit: str = "") -> Reading:
    return Reading(group, key, None, unit, available=False, reason=reason)


def _off(group: str, key: str, unit: str = "") -> Reading:
    return Reading(group, key, None, unit, available=False, disabled=True,
                   reason="DISABLED — off by default; enable with the cockpit toggle")


def _run(cmd: list, timeout: float = 6.0) -> Optional[str]:
    """A short external read. Never raises, never blocks the page."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def cycle_is_live() -> bool:
    """True when memory/cycle.lock names a pid that exists."""
    try:
        pid = json.loads(LOCK.read_text(encoding="utf-8")).get("pid")
    except Exception:
        return False
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def energy() -> list:
    out = []
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            out.append(_na("ENERGY", "battery_percent", "no battery reported", "%"))
            out.append(_na("ENERGY", "power_plugged", "no battery reported", ""))
        else:
            out.append(Reading("ENERGY", "battery_percent", round(b.percent, 1), "%"))
            out.append(Reading("ENERGY", "power_plugged", bool(b.power_plugged), ""))
            secs = b.secsleft
            if isinstance(secs, int) and secs >= 0:
                out.append(Reading("ENERGY", "battery_secsleft", secs, "s"))
            else:
                out.append(_na("ENERGY", "battery_secsleft",
                               "unlimited while plugged in", "s"))
        out.append(Reading("ENERGY", "uptime_hours",
                           round((time.time() - psutil.boot_time()) / 3600.0, 2), "h"))
    except Exception as e:
        out.append(_na("ENERGY", "battery_percent",
                       "psutil failed: {}".format(type(e).__name__), "%"))
    # Discharge RATE needs two samples separated in time. A single-shot probe
    # cannot produce one, and inventing it from secsleft would be arithmetic
    # dressed as a measurement.
    out.append(_na("ENERGY", "discharge_rate",
                   "needs two samples over time; a single probe cannot measure a rate",
                   "%/h"))
    return out


def thermal() -> list:
    out = []
    raw = _run(["nvidia-smi",
                "--query-gpu=temperature.gpu,power.draw,utilization.gpu,memory.used",
                "--format=csv,noheader,nounits"])
    if raw and raw.strip():
        parts = [p.strip() for p in raw.strip().splitlines()[0].split(",")]
        names = [("gpu_temp_c", "C"), ("gpu_power_w", "W"),
                 ("gpu_util_pct", "%"), ("gpu_mem_used_mb", "MB")]
        for (key, unit), val in zip(names, parts):
            grp = "THERMAL" if key in ("gpu_temp_c", "gpu_power_w") else "COMPUTE"
            try:
                out.append(Reading(grp, key, float(val), unit))
            except ValueError:
                out.append(_na(grp, key, "nvidia-smi returned {!r}".format(val), unit))
    else:
        for key, unit in (("gpu_temp_c", "C"), ("gpu_power_w", "W"),
                          ("gpu_util_pct", "%"), ("gpu_mem_used_mb", "MB")):
            out.append(_na("THERMAL", key, "nvidia-smi unavailable or failed", unit))
    # psutil.sensors_temperatures does not exist on Windows at all — not empty,
    # ABSENT. Reported as the platform limitation it is.
    out.append(_na("THERMAL", "cpu_temp_c",
                   "psutil.sensors_temperatures() is not implemented on Windows; "
                   "CPU/chip temperature needs a vendor driver (LibreHardwareMonitor)",
                   "C"))
    out.append(_na("THERMAL", "fan_rpm",
                   "psutil.sensors_fans() is not implemented on Windows", "rpm"))
    return out


def compute() -> list:
    out = []
    try:
        import psutil
        out.append(Reading("COMPUTE", "cpu_percent",
                           psutil.cpu_percent(interval=0.15), "%"))
        out.append(Reading("COMPUTE", "cpu_cores", psutil.cpu_count(), ""))
        f = psutil.cpu_freq()
        out.append(Reading("COMPUTE", "cpu_freq_mhz", round(f.current, 0), "MHz")
                   if f else _na("COMPUTE", "cpu_freq_mhz", "cpu_freq unavailable", "MHz"))
        try:
            l1, _, _ = psutil.getloadavg()
            out.append(Reading("COMPUTE", "load_1", round(l1, 2), ""))
        except Exception:
            out.append(_na("COMPUTE", "load_1",
                           "getloadavg is emulated on Windows and needs a warm-up "
                           "window this probe does not have", ""))
    except Exception as e:
        out.append(_na("COMPUTE", "cpu_percent",
                       "psutil failed: {}".format(type(e).__name__), "%"))
    return out


def memory_group() -> list:
    out = []
    try:
        import psutil
        vm = psutil.virtual_memory()
        out.append(Reading("MEMORY", "ram_percent", vm.percent, "%"))
        out.append(Reading("MEMORY", "ram_used_gb", round(vm.used / 2**30, 2), "GB"))
        out.append(Reading("MEMORY", "ram_total_gb", round(vm.total / 2**30, 2), "GB"))
        sm = psutil.swap_memory()
        out.append(Reading("MEMORY", "swap_percent", sm.percent, "%"))
        out.append(Reading("MEMORY", "swap_used_gb", round(sm.used / 2**30, 2), "GB"))
        try:
            pf = psutil.Process(os.getpid()).memory_info()
            out.append(Reading("MEMORY", "page_faults",
                               int(getattr(pf, "num_page_faults", 0)), ""))
        except Exception:
            out.append(_na("MEMORY", "page_faults", "not exposed for this process", ""))
    except Exception as e:
        out.append(_na("MEMORY", "ram_percent",
                       "psutil failed: {}".format(type(e).__name__), "%"))
    return out


def storage() -> list:
    out = []
    try:
        import psutil
        io = psutil.disk_io_counters()
        if io:
            out.append(Reading("STORAGE", "disk_read_mb",
                               round(io.read_bytes / 2**20, 1), "MB"))
            out.append(Reading("STORAGE", "disk_write_mb",
                               round(io.write_bytes / 2**20, 1), "MB"))
        else:
            out.append(_na("STORAGE", "disk_read_mb", "disk_io_counters empty", "MB"))
        try:
            out.append(Reading("STORAGE", "open_handles",
                               psutil.Process(os.getpid()).num_handles(), ""))
        except Exception:
            out.append(_na("STORAGE", "open_handles", "num_handles unavailable", ""))
        top = []
        for p in psutil.process_iter(["name", "io_counters"]):
            try:
                c = p.info.get("io_counters")
                if c:
                    top.append((c.read_bytes + c.write_bytes, p.info["name"]))
            except Exception:
                continue
        top.sort(reverse=True)
        out.append(Reading("STORAGE", "top_io_process",
                           "{} ({} MB)".format(top[0][1], round(top[0][0] / 2**20))
                           if top else None, "")
                   if top else _na("STORAGE", "top_io_process", "no per-process io", ""))
    except Exception as e:
        out.append(_na("STORAGE", "disk_read_mb",
                       "psutil failed: {}".format(type(e).__name__), "MB"))
    out.append(_na("STORAGE", "smart_health",
                   "SMART needs elevated rights and smartctl, neither present",
                   ""))
    return out


def network() -> list:
    out = []
    raw = _run(["netsh", "wlan", "show", "interfaces"])
    ssid, signal = None, None
    if raw:
        for line in raw.splitlines():
            s = line.strip()
            if s.lower().startswith("ssid") and ":" in s and "bssid" not in s.lower():
                ssid = s.split(":", 1)[1].strip()
            elif s.lower().startswith("signal") and ":" in s:
                try:
                    signal = float(s.split(":", 1)[1].strip().rstrip("%"))
                except ValueError:
                    pass
    out.append(Reading("NETWORK", "wifi_ssid", ssid, "")
               if ssid else _na("NETWORK", "wifi_ssid", "netsh reported no SSID", ""))
    out.append(Reading("NETWORK", "wifi_signal_pct", signal, "%")
               if signal is not None
               else _na("NETWORK", "wifi_signal_pct", "netsh reported no signal", "%"))
    # RSSI in dBm is not exposed by netsh; the percentage is what Windows gives.
    out.append(_na("NETWORK", "wifi_rssi_dbm",
                   "netsh reports a percentage, not dBm; dBm needs the WLAN API", "dBm"))

    ping = _run(["ping", "-n", "1", "-w", "1500", "8.8.8.8"], timeout=5.0)
    ms = None
    if ping:
        for tok in ping.replace("=", " ").replace("<", " ").split():
            if tok.endswith("ms"):
                try:
                    ms = float(tok[:-2])
                    break
                except ValueError:
                    continue
    out.append(Reading("NETWORK", "gateway_ping_ms", ms, "ms") if ms is not None
               else _na("NETWORK", "gateway_ping_ms", "no reply within 1.5s", "ms"))

    try:
        import psutil
        n = psutil.net_io_counters()
        out.append(Reading("NETWORK", "net_sent_mb", round(n.bytes_sent / 2**20, 1), "MB"))
        out.append(Reading("NETWORK", "net_recv_mb", round(n.bytes_recv / 2**20, 1), "MB"))
        try:
            conns = psutil.net_connections()
            out.append(Reading("NETWORK", "connections", len(conns), ""))
        except Exception:
            out.append(_na("NETWORK", "connections",
                           "net_connections needs elevated rights on Windows", ""))
    except Exception as e:
        out.append(_na("NETWORK", "net_sent_mb",
                       "psutil failed: {}".format(type(e).__name__), "MB"))
    out.append(_na("NETWORK", "bluetooth_scan",
                   "no bluetooth stack binding installed (bleak/winrt absent)", ""))
    return out


_LAST_INPUT_INFO = None


def periphery() -> list:
    out = []
    # Idle time, via GetLastInputInfo. ctypes, no dependency.
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            ticks = ctypes.windll.kernel32.GetTickCount()
            out.append(Reading("PERIPHERY", "idle_seconds",
                               round((ticks - lii.dwTime) / 1000.0, 1), "s"))
        else:
            out.append(_na("PERIPHERY", "idle_seconds", "GetLastInputInfo failed", "s"))
    except Exception as e:
        out.append(_na("PERIPHERY", "idle_seconds",
                       "ctypes/user32 unavailable: {}".format(type(e).__name__), "s"))

    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        out.append(Reading("PERIPHERY", "active_window", buf.value or "(none)", ""))
    except Exception as e:
        out.append(_na("PERIPHERY", "active_window",
                       "user32 unavailable: {}".format(type(e).__name__), ""))

    raw = _run(["powershell", "-NoProfile", "-Command",
                "(Get-CimInstance -Namespace root/WMI -ClassName "
                "WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness"],
               timeout=8.0)
    try:
        out.append(Reading("PERIPHERY", "brightness_pct",
                           float(raw.strip().splitlines()[0]), "%"))
    except Exception:
        out.append(_na("PERIPHERY", "brightness_pct",
                       "WmiMonitorBrightness returned nothing (common on desktops "
                       "and external monitors)", "%"))

    out.append(_na("PERIPHERY", "ambient_light",
                   "no ambient light sensor exposed by this machine", "lux"))
    return out


def acoustic(enabled: bool = False) -> list:
    """RMS scalar only. OFF by default."""
    if not enabled:
        return [_off("ACOUSTIC", "mic_rms", "rms")]
    if cycle_is_live():
        return [_na("ACOUSTIC", "mic_rms",
                    "REFUSED: a cycle is running and no microphone is activated "
                    "while one is", "rms")]
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return [_na("ACOUSTIC", "mic_rms",
                    "no audio capture library installed (sounddevice/pyaudio "
                    "absent) — enabling the toggle cannot make one appear", "rms")]
    return [_na("ACOUSTIC", "mic_rms",
                "capture path not implemented in v1; the toggle and the gates are, "
                "so nothing is claimed that is not measured", "rms")]


def optic(enabled: bool = False) -> list:
    """Derived scalars only — lux and motion MSE. Frames never stored. OFF by default."""
    if not enabled:
        return [_off("OPTIC", "camera_lux", "lux"), _off("OPTIC", "motion_mse", "mse")]
    if cycle_is_live():
        return [_na("OPTIC", "camera_lux",
                    "REFUSED: a cycle is running and no camera is activated while "
                    "one is", "lux")]
    try:
        import cv2  # noqa: F401
    except ImportError:
        return [_na("OPTIC", "camera_lux",
                    "no camera library installed (cv2 absent) — enabling the "
                    "toggle cannot make one appear", "lux")]
    return [_na("OPTIC", "camera_lux",
                "capture path not implemented in v1; the toggle and the gates are",
                "lux")]


def logs() -> list:
    raw = _run(["powershell", "-NoProfile", "-Command",
                "(Get-WinEvent -FilterHashtable @{LogName='System';Level=2;"
                "StartTime=(Get-Date).AddHours(-24)} -ErrorAction SilentlyContinue "
                "| Measure-Object).Count"], timeout=20.0)
    try:
        return [Reading("LOGS", "event_log_errors_24h",
                        int(raw.strip().splitlines()[0]), "")]
    except Exception:
        return [_na("LOGS", "event_log_errors_24h",
                    "Get-WinEvent returned nothing or timed out", "")]


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def probe(mic_enabled: bool = False, camera_enabled: bool = False) -> dict:
    """Every group, once. Read-only; safe to run beside a live cycle."""
    rows = []
    rows += energy()
    rows += thermal()
    rows += compute()
    rows += memory_group()
    rows += storage()
    rows += network()
    rows += periphery()
    rows += acoustic(mic_enabled)
    rows += optic(camera_enabled)
    rows += logs()

    by_group = {g: [] for g in GROUPS}
    for r in rows:
        by_group.setdefault(r.group, []).append(r.as_dict())

    unavailable = [{"group": r.group, "key": r.key, "reason": r.reason}
                   for r in rows if not r.available and not r.disabled]
    disabled = [{"group": r.group, "key": r.key} for r in rows if r.disabled]

    return {
        "ts": _now(),
        "vector_version": VECTOR_VERSION,
        "groups": by_group,
        "not_available": unavailable,
        "disabled": disabled,
        "available_count": sum(1 for r in rows if r.available),
        "total_count": len(rows),
        "cycle_live": cycle_is_live(),
        "gates": {
            "camera": "local-only, never stored, never leaves the machine, "
                      "never enters the columns; only lux and motion MSE are kept",
            "mic": "RMS scalar only; never a sample or a buffer; a spike must "
                   "persist across windows before it is reported",
            "while_cycle_live": "camera and mic are refused outright",
        },
    }


def state_vector(reading: Optional[dict] = None) -> dict:
    """The 25-dim vector, version tagged. Missing sensors are None, never 0.0."""
    r = reading or probe()
    flat = {}
    for rows in r["groups"].values():
        for row in rows:
            flat[row["key"]] = row["value"] if row["available"] else None
    vec = [flat.get(f) for f in VECTOR_FIELDS]
    return {"version": VECTOR_VERSION, "fields": list(VECTOR_FIELDS),
            "vector": vec, "ts": r["ts"],
            "measured": sum(1 for v in vec if v is not None),
            "dims": len(vec)}


# ---------------------------------------------------------------------------
# The self-test harness
# ---------------------------------------------------------------------------

MANUAL_PROCEDURES = (
    ("camera_lux", "cover the camera", "lux falls to ~0"),
    ("battery_percent", "unplug the mains", "power_plugged flips False and percent falls"),
    ("gateway_ping_ms", "turn Wi-Fi off", "gateway ping times out"),
    ("mic_rms", "play a 1 kHz tone", "RMS spikes above the idle floor"),
)

ISOLATION_TEST = """ONE-HOUR ISOLATION TEST (manual)

  1. Note the time. Leave the machine alone for one hour: no keyboard, no mouse,
     no foreground window change.
  2. Sample the somatic map at the start and the end.
  3. EXPECT: idle_seconds ~3600, active_window unchanged, cpu_percent settled to
     its floor, gpu_util near zero unless a cycle ran.
  4. ANY OTHER MOVEMENT is either a scheduled task or a sensor that drifts on its
     own. Both are findings. Write down which.

The point is a baseline for what this machine does when nobody is touching it,
so that a later reading can be compared against something rather than against an
intuition."""


def selftest(mic_enabled: bool = False, camera_enabled: bool = False) -> dict:
    """PASS/FAIL per sensor, runnable from the cockpit."""
    r = probe(mic_enabled=mic_enabled, camera_enabled=camera_enabled)
    results = []
    for rows in r["groups"].values():
        for row in rows:
            if row["disabled"]:
                verdict, note = "SKIP", "toggle is off"
            elif not row["available"]:
                verdict, note = "N/A", row["reason"]
            elif row["value"] is None:
                verdict, note = "FAIL", "reported available with a null value"
            else:
                verdict, note = "PASS", ""
            results.append({"group": row["group"], "key": row["key"],
                            "verdict": verdict, "note": note,
                            "value": row["value"]})
    counts = {}
    for x in results:
        counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
    return {"ts": r["ts"], "results": results, "counts": counts,
            "manual_procedures": [{"sensor": s, "do": d, "expect": e}
                                  for s, d, e in MANUAL_PROCEDURES],
            "isolation_test": ISOLATION_TEST}


def _cli() -> int:
    if "--selftest" in sys.argv:
        out = selftest()
        print("cockpit/somatic.py --selftest")
        for x in out["results"]:
            print("  {:<6} {:<10} {:<24} {}".format(
                x["verdict"], x["group"], x["key"],
                x["note"][:60] if x["note"] else x["value"]))
        print("\n  counts: {}".format(out["counts"]))
        print("\n  MANUAL PROCEDURES")
        for m in out["manual_procedures"]:
            print("    {:<16} {:<24} -> {}".format(m["sensor"], m["do"], m["expect"]))
        return 0
    r = probe()
    print("cockpit/somatic.py --probe   ({} of {} sensors available)".format(
        r["available_count"], r["total_count"]))
    for g in GROUPS:
        for row in r["groups"].get(g, []):
            state = ("DISABLED" if row["disabled"]
                     else "n/a" if not row["available"] else str(row["value"]))
            print("  {:<10} {:<24} {:>18} {}".format(
                g, row["key"], state[:18], row["unit"]))
    print("\n  NOT AVAILABLE ON THIS MACHINE ({}):".format(len(r["not_available"])))
    for x in r["not_available"]:
        print("    {:<24} {}".format(x["key"], x["reason"][:70]))
    v = state_vector(r)
    print("\n  state vector {} — {}/{} dims measured".format(
        v["version"], v["measured"], v["dims"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
