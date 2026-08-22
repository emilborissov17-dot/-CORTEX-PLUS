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
    "idle_seconds", "brightness_pct", "event_log_errors_24h",
)
# ^ WAS "event_log_errors", which matched no sensor key: the reading is emitted
# as event_log_errors_24h, so dim 25 silently resolved to None and the report
# called it "24 of 25 measured" as if the machine could not answer. It could —
# the Windows Event Log was read correctly every time and thrown away on a name.
# cockpit/vector.assert_fields_resolve() now fails loudly if this recurs. No
# version bump: memory/state_vectors.jsonl did not exist, so nothing was ever
# fitted from the broken vector and there is no migration to log.
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
                "source": self.source, "reflexivity": self.reflexivity,
                # Computed here so the API and the page cannot disagree about
                # what colour a number is.
                "band": band_for(self.key, self.value) if self.available else None,
                "direction": direction_of(self.key)}


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



CONFIG_PATH = BASE / "config_expression.yaml"


def toggles(config_path: Optional[pathlib.Path] = None) -> dict:
    """{mic_enabled, camera_enabled} read from config_expression.yaml.

    Read on EVERY probe rather than cached at import: a switch the operator
    turns OFF must take effect on the next refresh, and a cached value would
    mean the device stays live until somebody restarts the server. Missing file
    or unreadable yaml reads FALSE for both — the fail-closed direction.
    """
    try:
        import yaml
        blob = yaml.safe_load(
            pathlib.Path(config_path or CONFIG_PATH).read_text(encoding="utf-8"))
        blob = blob if isinstance(blob, dict) else {}
    except Exception:
        blob = {}
    return {"mic_enabled": bool(blob.get("mic_enabled")),
            "camera_enabled": bool(blob.get("camera_enabled"))}



# ---------------------------------------------------------------------------
# DIRECTION: WHICH WAY IS BAD
# ---------------------------------------------------------------------------
# battery_percent 97 rendered RED, because the bar coloured on MAGNITUDE alone:
# anything over 85 was "bad". For a battery, 97 is the best reading available.
#
# So each metric declares its direction. HIGHER_BETTER means a large value is
# healthy and the warning is at the LOW end (battery, wifi signal, free disk);
# LOWER_BETTER means the opposite (load, temperature, memory, swap). A metric
# with no direction gets no colour at all rather than a guessed one — a grey bar
# says "not judged", and a green bar says "judged, and fine". Those are different
# claims and the panel should not make the second one by accident.

HIGHER_BETTER, LOWER_BETTER, NEUTRAL = "higher_better", "lower_better", "neutral"

# (direction, amber_edge, red_edge). For HIGHER_BETTER the edges are floors that
# a value falls THROUGH; for LOWER_BETTER they are ceilings it rises through.
DIRECTIONS = {
    "battery_percent":   (HIGHER_BETTER, 40.0, 15.0),
    "wifi_signal_pct":   (HIGHER_BETTER, 50.0, 25.0),
    "brightness_pct":    (NEUTRAL, None, None),
    "cpu_percent":       (LOWER_BETTER, 65.0, 85.0),
    "gpu_util_pct":      (LOWER_BETTER, 80.0, 95.0),
    "ram_percent":       (LOWER_BETTER, 75.0, 90.0),
    "swap_percent":      (LOWER_BETTER, 50.0, 80.0),
    "gpu_temp_c":        (LOWER_BETTER, 75.0, 85.0),
    "cpu_temp_c":        (LOWER_BETTER, 75.0, 90.0),
    "gateway_ping_ms":   (LOWER_BETTER, 100.0, 500.0),
    "idle_seconds":      (NEUTRAL, None, None),
    "uptime_hours":      (NEUTRAL, None, None),
    "event_log_errors_24h": (LOWER_BETTER, 5.0, 25.0),
}


def direction_of(key: str) -> str:
    return DIRECTIONS.get(key, (NEUTRAL, None, None))[0]


def band_for(key: str, value) -> Optional[str]:
    """green / amber / red, or None when the metric declares no direction.

    None is not a failure and not "green". It means nobody has said which way is
    bad for this number, so the panel draws it uncoloured instead of implying a
    verdict it does not have.
    """
    spec = DIRECTIONS.get(key)
    if not spec or not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    direction, amber, red = spec
    if direction == NEUTRAL or amber is None:
        return None
    if direction == HIGHER_BETTER:
        return "red" if value <= red else "amber" if value <= amber else "green"
    return "red" if value >= red else "amber" if value >= amber else "green"

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


# ---------------------------------------------------------------------------
# CAPTURE — ONE SAMPLE, ONE SCALAR, NO BUFFER, NO FILE
# ---------------------------------------------------------------------------
# Both capture paths follow the same four steps and nothing else:
#
#     open the device -> take ONE sample -> close it -> reduce to a scalar
#
# The reduction happens while the raw data is still a local variable, and the
# variable goes out of scope with the function. Nothing is appended to a list,
# nothing is cached for a later comparison, and NO AUDIO OR IMAGE FILE IS EVER
# WRITTEN. What survives is a float.
#
# The camera's motion MSE compares against the PREVIOUS FRAME'S SCALAR SUMMARY,
# not against a stored frame. That is the whole reason the summary is a small
# vector of block means rather than the frame: a stored frame is a picture of
# somebody's room, and a stored 4x4 grid of averages is not.
#
# THE COOLDOWN IS A CONTRACT, NOT A PERFORMANCE TUNING. A cockpit that polls
# /api/somatic every 15 seconds must not become a device that samples the room
# every 15 seconds. Ten seconds between captures, enforced here rather than by
# asking callers to behave.

CAPTURE_COOLDOWN_SEC = 10.0

MIC_WINDOW_SEC = 0.1            # ~100 ms
MIC_SAMPLE_RATE = 16000

# An RMS spike must PERSIST to be reported as a level. A single 100 ms window
# that reads loud may be a click, a key press, or an ultrasonic artefact; the
# room being loud shows up in the next window too. The guard stores one float.
ULTRASONIC_GUARD_FACTOR = 4.0

_last_capture = {"mic": 0.0, "camera": 0.0}
_last_mic_rms = None            # one float, for the persistence guard
_last_frame_summary = None      # 16 floats, for the motion MSE


def capture_state() -> dict:
    """What the guards currently hold. Floats only — inspectable, and small."""
    return {"last_capture": dict(_last_capture),
            "last_mic_rms": _last_mic_rms,
            "frame_summary_len": (0 if _last_frame_summary is None
                                  else len(_last_frame_summary)),
            "cooldown_sec": CAPTURE_COOLDOWN_SEC}


def _cooldown_block(kind: str, now: Optional[float] = None) -> Optional[float]:
    """Seconds still to wait, or None if a capture is allowed."""
    t = time.monotonic() if now is None else now
    left = CAPTURE_COOLDOWN_SEC - (t - _last_capture.get(kind, 0.0))
    return left if left > 0 else None


def _stamp(kind: str) -> None:
    _last_capture[kind] = time.monotonic()


def mic_rms_once() -> tuple:
    """(rms, error). ONE ~100 ms window. The device is closed before returning.

    sounddevice.rec() + wait() opens a stream, fills one array and closes the
    stream on return. The array is reduced to a float on the next line and is
    never stored, written, or passed anywhere.
    """
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError as e:
        return None, "no audio capture library: {}".format(e)
    try:
        frames = int(MIC_WINDOW_SEC * MIC_SAMPLE_RATE)
        block = sd.rec(frames, samplerate=MIC_SAMPLE_RATE, channels=1,
                       dtype="float32")
        sd.wait()
        rms = float(np.sqrt(np.mean(np.square(block, dtype="float64"))))
        del block                     # explicit: the samples end here
        return rms, None
    except Exception as e:            # noqa: BLE001
        return None, "{}: {}".format(type(e).__name__, e)
    finally:
        try:
            import sounddevice as sd
            sd.stop()                 # idempotent; guarantees no stream is left open
        except Exception:
            pass


def _frame_summary(gray) -> list:
    """A 4x4 grid of block means. Sixteen floats — not a picture."""
    import numpy as np
    h, w = gray.shape[:2]
    bh, bw = max(1, h // 4), max(1, w // 4)
    return [float(np.mean(gray[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw]))
            for r in range(4) for c in range(4)]


def camera_scalars_once() -> tuple:
    """(lux, motion_mse, error). ONE frame. The device is released before returning.

    The frame never leaves this function. What is kept between calls is the 4x4
    block-mean summary, sixteen floats, which is what the motion MSE is computed
    against — a stored frame would be a picture of a room, and this is not one.
    """
    global _last_frame_summary
    cap = None
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        return None, None, "no camera library: {}".format(e)
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return None, None, "camera did not open"
        ok, frame = cap.read()
        if not ok or frame is None:
            return None, None, "camera opened but returned no frame"
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lux = float(np.mean(gray))
        summary = _frame_summary(gray)
        del frame, gray               # explicit: the image ends here
        mse = None
        if _last_frame_summary is not None:
            a = np.asarray(summary, dtype="float64")
            b = np.asarray(_last_frame_summary, dtype="float64")
            mse = float(np.mean((a - b) ** 2))
        _last_frame_summary = summary
        return lux, mse, None
    except Exception as e:            # noqa: BLE001
        return None, None, "{}: {}".format(type(e).__name__, e)
    finally:
        # RELEASED IN A finally, so an exception on any line above still closes
        # the device. A test asserts release() was called.
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def acoustic(enabled: bool = False) -> list:
    """RMS scalar only. OFF unless the toggle says otherwise."""
    global _last_mic_rms
    if not enabled:
        return [_off("ACOUSTIC", "mic_rms", "rms")]
    if cycle_is_live():
        return [_na("ACOUSTIC", "mic_rms",
                    "REFUSED: a cycle is running and no microphone is activated "
                    "while one is", "rms")]
    left = _cooldown_block("mic")
    if left is not None:
        return [_na("ACOUSTIC", "mic_rms",
                    "REFUSED: {:.1f}s left of the {:.0f}s capture cooldown — a "
                    "15-second page refresh must not become a device that "
                    "samples the room every 15 seconds".format(
                        left, CAPTURE_COOLDOWN_SEC), "rms")]
    _stamp("mic")
    rms, err = mic_rms_once()
    if err:
        return [_na("ACOUSTIC", "mic_rms", err, "rms")]

    # THE ULTRASONIC / TRANSIENT GUARD. A window far above the previous one is
    # reported as a TRANSIENT, not as a level: a click is not a room.
    kind = "level"
    if _last_mic_rms is not None and rms > ULTRASONIC_GUARD_FACTOR * max(
            _last_mic_rms, 1e-6):
        kind = "transient (not reported as a level: a spike must persist)"
    _last_mic_rms = rms
    return [Reading("ACOUSTIC", "mic_rms", round(rms, 6), "rms"),
            Reading("ACOUSTIC", "mic_reading_kind", kind, "")]


def optic(enabled: bool = False) -> list:
    """Derived scalars only — lux and motion MSE. OFF unless the toggle says so."""
    if not enabled:
        return [_off("OPTIC", "camera_lux", "lux"), _off("OPTIC", "motion_mse", "mse")]
    if cycle_is_live():
        return [_na("OPTIC", "camera_lux",
                    "REFUSED: a cycle is running and no camera is activated while "
                    "one is", "lux"),
                _na("OPTIC", "motion_mse", "REFUSED: a cycle is running", "mse")]
    left = _cooldown_block("camera")
    if left is not None:
        msg = ("REFUSED: {:.1f}s left of the {:.0f}s capture cooldown".format(
            left, CAPTURE_COOLDOWN_SEC))
        return [_na("OPTIC", "camera_lux", msg, "lux"),
                _na("OPTIC", "motion_mse", msg, "mse")]
    _stamp("camera")
    lux, mse, err = camera_scalars_once()
    if err:
        return [_na("OPTIC", "camera_lux", err, "lux"),
                _na("OPTIC", "motion_mse", err, "mse")]
    rows = [Reading("OPTIC", "camera_lux", round(lux, 3), "lux")]
    rows.append(Reading("OPTIC", "motion_mse", round(mse, 4), "mse")
                if mse is not None else
                _na("OPTIC", "motion_mse",
                    "first frame of this session; motion needs a previous "
                    "summary to compare against", "mse"))
    return rows


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

def probe(mic_enabled: Optional[bool] = None,
          camera_enabled: Optional[bool] = None,
          config_path: Optional[pathlib.Path] = None) -> dict:
    """Every group, once. Read-only; safe to run beside a live cycle.

    With no explicit argument the toggles come from config_expression.yaml, read
    fresh on every call. An explicit True/False still wins, which is what the
    tests use — they must never depend on what the operator last switched.
    """
    cfg = toggles(config_path)
    mic_enabled = cfg["mic_enabled"] if mic_enabled is None else mic_enabled
    camera_enabled = (cfg["camera_enabled"] if camera_enabled is None
                      else camera_enabled)
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
        "toggles": {"mic_enabled": bool(mic_enabled),
                    "camera_enabled": bool(camera_enabled),
                    "source": "config_expression.yaml, re-read every probe"},
        "capture": capture_state(),
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
