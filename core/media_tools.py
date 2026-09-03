#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/media_tools.py — WHERE ffmpeg AND deno ACTUALLY ARE (3 Sep 2026).

WHY THIS EXISTS. Three nights of cycle logs (1-3 Sep 2026) carry, per video:
    WARNING: ffmpeg not found. The downloaded format may not be the best available.
    WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is
             enabled by default; to use another runtime add --js-runtimes RUNTIME[:PATH]
Neither binary is installed on the machine, and the consequences are not cosmetic:
  - attempt 4 (Groq Whisper) downloads audio with `yt-dlp -x --audio-format mp3`.
    `-x` IS an ffmpeg post-processor. Without ffmpeg the download exits non-zero,
    internet_agent._get_transcript_whisper returned None in silence, and the Whisper leg
    - the only one immune to the subtitle-endpoint 429 - has never produced a transcript.
  - yt-dlp >= 2025.x solves YouTube's player signature in a JS runtime. Without one, a
    growing share of videos cannot be resolved at all, whatever the subtitle endpoint says.

WHAT IT DOES. Finds the two binaries the way the SCHEDULED cycle will see them - which
is NOT the interactive PATH: `schtasks` launches venv\\Scripts\\python.exe with the
user's registry PATH as it was at logon, so a fresh winget install is invisible to the
03:00 run until the next logon. That is why every location is probed EXPLICITLY, and
why the flags carry the resolved path rather than trusting PATH:
    --ffmpeg-location <dir>      (yt-dlp accepts a directory or the exe)
    --js-runtimes deno:<exe>     (yt-dlp's documented RUNTIME[:PATH] form)

Search order, first hit wins:
    1. environment   FFMPEG_PATH / DENO_PATH  (absolute path to the exe, or its dir)
    2. shutil.which  - honours whatever PATH the process really has
    3. winget Links  %LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\<name>.exe
    4. winget pkgs   %LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg*\\**\\bin\\ffmpeg.exe
                     %LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\DenoLand.Deno*\\deno.exe
    5. deno's own    %USERPROFILE%\\.deno\\bin\\deno.exe
    6. repo-local    <repo>\\bin\\ffmpeg\\ffmpeg.exe, <repo>\\bin\\deno\\deno.exe
                     (bin/ is gitignored; a hand-dropped binary is the last resort)

INSTALL: tools/install_media_deps.ps1 (winget). Run it ONCE as the user that owns the
scheduled task; then `venv\\Scripts\\python.exe -m core.media_tools --selftest` prints
what the cycle will see.

  venv\\Scripts\\python.exe -m core.media_tools --selftest
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
_IS_WIN = os.name == "nt"
_EXE = ".exe" if _IS_WIN else ""


def _first_file(paths) -> Optional[str]:
    for p in paths:
        if not p:
            continue
        try:
            if Path(p).is_file():
                return str(Path(p))
        except OSError:
            continue
    return None


def _env_candidate(var: str, name: str) -> list:
    v = os.environ.get(var, "").strip().strip('"')
    if not v:
        return []
    p = Path(v)
    return [str(p), str(p / f"{name}{_EXE}")]


def _winget_roots() -> list:
    lad = os.environ.get("LOCALAPPDATA", "")
    if not lad:
        return []
    return [Path(lad) / "Microsoft" / "WinGet"]


def find_ffmpeg() -> Optional[str]:
    """Absolute path to the ffmpeg executable, or None. Never raises."""
    cands = _env_candidate("FFMPEG_PATH", "ffmpeg")
    w = shutil.which("ffmpeg")
    if w:
        cands.append(w)
    for root in _winget_roots():
        cands.append(str(root / "Links" / f"ffmpeg{_EXE}"))
        cands += sorted(glob.glob(str(root / "Packages" / "Gyan.FFmpeg*" / "**" / "bin"
                                      / f"ffmpeg{_EXE}"), recursive=True), reverse=True)
        cands += sorted(glob.glob(str(root / "Packages" / "*FFmpeg*" / "**"
                                      / f"ffmpeg{_EXE}"), recursive=True), reverse=True)
    cands.append(str(REPO / "bin" / "ffmpeg" / f"ffmpeg{_EXE}"))
    cands.append(str(REPO / "bin" / "ffmpeg" / "bin" / f"ffmpeg{_EXE}"))
    return _first_file(cands)


def find_deno() -> Optional[str]:
    """Absolute path to the deno executable, or None. Never raises."""
    cands = _env_candidate("DENO_PATH", "deno")
    w = shutil.which("deno")
    if w:
        cands.append(w)
    for root in _winget_roots():
        cands.append(str(root / "Links" / f"deno{_EXE}"))
        cands += sorted(glob.glob(str(root / "Packages" / "DenoLand.Deno*" / "**"
                                      / f"deno{_EXE}"), recursive=True), reverse=True)
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    if home:
        cands.append(str(Path(home) / ".deno" / "bin" / f"deno{_EXE}"))
    cands.append(str(REPO / "bin" / "deno" / f"deno{_EXE}"))
    return _first_file(cands)


def yt_dlp_extra_args() -> list:
    """The argv fragment every yt-dlp call site appends. Empty when nothing is found -
    the call still runs and yt-dlp still prints its own WARNING, so absence stays
    visible in the cycle log rather than being papered over here."""
    args = []
    ff = find_ffmpeg()
    if ff and _runs(ff):
        args += ["--ffmpeg-location", str(Path(ff).parent)]
    dn = find_deno()
    if dn and _runs(dn):
        args += ["--js-runtimes", f"deno:{dn}"]
    return args


# ── Binary sanity (Kimi, brief 2026-09-03_ytdlp_429_parking, Q4): a found path that
# does not RUN is worse than no flag - yt-dlp then commits to a dead runtime instead of
# looking for another. So each binary is executed once per process (`--version`) and the
# flag is passed only if it answered. Cached; never raises.
_RUNS: dict = {}


def _version_flag(path: str) -> str:
    # ffmpeg takes `-version` (one dash; `--version` is "Unrecognized option", rc=8).
    # deno takes `--version`. Found the hard way in the cloud selftest, 3 Sep 2026.
    return "-version" if Path(path).stem.lower().startswith("ffmpeg") else "--version"


def _runs(path: Optional[str]) -> bool:
    if not path:
        return False
    if path in _RUNS:
        return _RUNS[path][0]
    try:
        import subprocess
        r = subprocess.run([path, _version_flag(path)], capture_output=True, text=True,
                           timeout=15)
        ok = (r.returncode == 0)
        first = ((r.stdout or r.stderr or "").strip().splitlines() or [""])[0][:80]
    except Exception:
        ok, first = False, ""
    _RUNS[path] = (ok, first)
    return ok


def binary_version(path: Optional[str]) -> str:
    """First line of the binary's version output, or '' - for --selftest and DEP_CHECK."""
    if not _runs(path):
        return ""
    return _RUNS.get(path, (False, ""))[1]


# ── YouTube's 429, measured (cycle logs 1-3 Sep 2026) ────────────────────────────
# [TRANSCRIPT-YTDLP] lines per cycle: 129 / 277 / 281, almost all
#   "Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests".
# Fresh yt-dlp subtitle successes over the same nights: 18 / 1 / 0.
#
# THE RULE, as ruled by Kimi (3 Sep 2026, brief 2026-09-03_ytdlp_429_parking):
#   Q3: "Не е отделен endpoint ... YouTube rate limit-ва на ниво IP, не на ниво URL
#        path. Нужен е глобален circuit breaker за всички YouTube outbound канали."
#   Q2: "По време (sliding window), не по обем ... Правилният модел е exponential
#        backoff с таван (напр. 5, 10, 20 мин), не cycle-scoped state."
# So: ONE breaker for EVERY yt-dlp call against YouTube (subtitles AND the Whisper audio
# download), tripped by YT_429_TRIP_AFTER consecutive 429s, parked on the WALL CLOCK with
# exponential backoff 5 -> 10 -> 20 min (cap), persisted in memory/yt_backoff.json so a
# fresh process (the nightly cycle IS a fresh process) honours a park set minutes ago.
# Playwright (youtube-transcript.ai) is a different host and is not gated.
# YT_429_TRIP_AFTER = 5 is a first estimate; Kimi's Q1 asks for a histogram of 429
# intervals before it is called a measurement - the breaker records total_429 per process
# and the log line carries the count, which is that histogram's raw material.
YT_429_TRIP_AFTER = 5
YT_BACKOFF_MIN = (5, 10, 20)          # minutes, escalating per consecutive trip
YT_BACKOFF_FILE = REPO / "memory" / "yt_backoff.json"


class YouTubeBreaker:
    """Process-wide state for every yt-dlp call against YouTube, wall-clock parked."""

    def __init__(self, trip_after: int = YT_429_TRIP_AFTER, state_file: Path = None):
        self.trip_after = int(trip_after)
        self.state_file = Path(state_file) if state_file else YT_BACKOFF_FILE
        self.streak = 0
        self.total_429 = 0
        self.announced = False
        self.parked_until = 0.0     # epoch seconds
        self.level = 0              # index into YT_BACKOFF_MIN
        self._load()

    # persistence: a park must survive the process, the cycle is a fresh process each night
    def _load(self) -> None:
        try:
            import json
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.parked_until = float(d.get("parked_until", 0) or 0)
            self.level = int(d.get("level", 0) or 0)
        except Exception:
            pass

    def _save(self) -> None:
        try:
            import json, time
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(
                {"parked_until": self.parked_until, "level": self.level,
                 "trip_after": self.trip_after, "total_429_this_process": self.total_429,
                 "written": time.time()}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def reset(self) -> None:
        """Per-process counters only. The wall-clock park is NOT a per-cycle thing
        (Kimi Q2) and is left alone; clear_park() exists for tests and for a human."""
        self.streak = 0
        self.total_429 = 0
        self.announced = False

    def clear_park(self) -> None:
        self.parked_until = 0.0
        self.level = 0
        self._save()

    @property
    def parked(self) -> bool:
        import time
        return time.time() < self.parked_until

    def seconds_left(self) -> int:
        import time
        return max(0, int(self.parked_until - time.time()))

    @staticmethod
    def is_429(text: str) -> bool:
        t = (text or "")
        return "429" in t and ("Too Many Requests" in t or "HTTP Error 429" in t)

    def record(self, stderr_text: str, success: bool = False) -> bool:
        """Feed one attempt's outcome. Returns True if the breaker is (now) parked."""
        import time
        if success:
            self.streak = 0
            if self.level and not self.parked:
                self.level = 0          # a clean success after the window closes the ladder
                self._save()
            return self.parked
        if self.is_429(stderr_text):
            self.streak += 1
            self.total_429 += 1
            if self.streak >= self.trip_after and not self.parked:
                minutes = YT_BACKOFF_MIN[min(self.level, len(YT_BACKOFF_MIN) - 1)]
                self.parked_until = time.time() + minutes * 60
                self.level = min(self.level + 1, len(YT_BACKOFF_MIN))
                self.announced = False
                self._save()
        else:
            self.streak = 0        # a non-429 failure is not evidence of rate limiting
        return self.parked

    def park_line(self) -> str:
        """The one line printed when the breaker trips; empty once already printed."""
        if not self.parked or self.announced:
            return ""
        self.announced = True
        return (f"    [YT-BREAKER] YouTube answered HTTP 429 {self.streak} times in a row "
                f"({self.total_429} this process) - EVERY yt-dlp call (subtitles and "
                f"Whisper audio) parked for {self.seconds_left() // 60} min on the wall "
                f"clock (level {self.level}/{len(YT_BACKOFF_MIN)}); Playwright continues")


# Kept under the old name so the two call sites and the tests need no rename.
SubtitleRateLimit = YouTubeBreaker
YT_SUBS_429_PARK_AFTER = YT_429_TRIP_AFTER
SUBS_LIMIT = YouTubeBreaker()


def status() -> dict:
    """For [DEP_CHECK] and --selftest: what the running process can see."""
    ff, dn = find_ffmpeg(), find_deno()
    return {"ffmpeg": ff, "deno": dn,
            "ffmpeg_ok": bool(ff) and _runs(ff), "deno_ok": bool(dn) and _runs(dn),
            "ffmpeg_version": binary_version(ff), "deno_version": binary_version(dn),
            "yt_breaker_parked_s": SUBS_LIMIT.seconds_left(),
            "yt_dlp_extra_args": yt_dlp_extra_args(),
            "python": sys.executable,
            "path_has_venv_scripts": str(Path(sys.executable).parent).lower()
                                     in os.environ.get("PATH", "").lower()}


def dep_check_lines() -> list:
    """Two lines in the runner's own [DEP_CHECK] vocabulary. MISSING is a proposal to
    the human (tools/install_media_deps.ps1), never a self-install - the cycle does not
    modify the machine it runs on."""
    s = status()
    out = []
    for name, ok, path, why in (
        ("ffmpeg", s["ffmpeg_ok"], s["ffmpeg"],
         "yt-dlp -x (Whisper leg) needs it; without it that leg has never produced text"),
        ("deno", s["deno_ok"], s["deno"],
         "yt-dlp JS runtime for YouTube signatures; without it videos fail to resolve"),
    ):
        if ok:
            out.append(f"[DEP_CHECK] OK      {name} ({path}; {s.get(name + '_version') or '?'})")
        elif path:
            out.append(f"[DEP_CHECK] FAIL    {name} found at {path} but `--version` did not run "
                       f"- NOT passed to yt-dlp (a dead runtime is worse than none)")
        else:
            out.append(f"[DEP_CHECK] MISSING {name} (optional) -> {why}; "
                       f"run tools\\install_media_deps.ps1, NOT self-installed")
    return out


def _selftest() -> int:
    s = status()
    print("core/media_tools --selftest")
    print(f"  python                 : {s['python']}")
    print(f"  PATH has venv\\Scripts  : {s['path_has_venv_scripts']}")
    print(f"  ffmpeg                 : {'LIVE ' + s['ffmpeg'] if s['ffmpeg_ok'] else 'INERT (not found)'}")
    print(f"  deno                   : {'LIVE ' + s['deno'] if s['deno_ok'] else 'INERT (not found)'}")
    print(f"  yt-dlp extra args      : {s['yt_dlp_extra_args'] or '[] (nothing found)'}")
    # integrations that consume this module, checked for existence in THIS repo
    for rel, needle in (("youtube_intel.py", "yt_dlp_extra_args"),
                        ("agents/internet/internet_agent.py", "yt_dlp_extra_args"),
                        ("fast_cycle_runner.py", "dep_check_lines")):
        p = REPO / rel
        wired = p.is_file() and needle in p.read_text(encoding="utf-8", errors="ignore")
        print(f"  consumer {rel:36s}: {'LIVE' if wired else 'INERT'}")
    for line in dep_check_lines():
        print("  " + line)
    return 0 if (s["ffmpeg_ok"] and s["deno_ok"]) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    import json
    print(json.dumps(status(), ensure_ascii=False, indent=2))
