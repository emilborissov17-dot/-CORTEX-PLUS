#!/usr/bin/env bash
# Samples the shape of a death: trainer RSS, system available RAM, GPU MiB, every 30s.
# Added 4 Sep 2026 after a long training run was killed silently with no OOM and no
# traceback, in the same minute three CORTEX tasks woke. A clean stop tells you
# nothing; a curve tells you whether memory was climbing into a ceiling.
#
# IT STOPPED SAMPLING A CORPSE (6 Sep 2026)
# -----------------------------------------
# The first version already had a stop condition -- `[ -z "$RSS" ] && break` -- and
# it never fired. It ran for 33.5 hours after its target died, writing a row every
# 30 seconds, because of one PowerShell coercion:
#
#     (Get-CimInstance Win32_Process -Filter "ProcessId=<dead>" |
#      Select-Object -ExpandProperty WorkingSetSize) / 1MB
#
# yields Int32 **0**, not an empty string: `$null / 1MB` is 0 in PowerShell. So RSS
# was "0", `-z` was false, and it described a process that had not existed since
# the previous day. The symptom was a column of zeros nobody read.
#
# The check is now on EXISTENCE, made before any arithmetic, and a missing process
# is written as GONE rather than 0 -- so a reader cannot mistake "no process" for
# "no memory". Same defect class as the rest of this week: a missing thing
# rendering as a plausible number.
set -u
OUT="${OUT:-claude/reports/K1B_SAMPLER_4SEP.tsv}"
PID="${1:?usage: ram_gpu_sampler.sh <pid> [interval_s]}"
INTERVAL="${2:-30}"

if [ ! -s "$OUT" ]; then
  printf "ts\ttrainer_pid\ttrainer_rss_mb\tsys_avail_mb\tsys_total_mb\tgpu_used_mib\tn_python\n" > "$OUT"
fi

# Existence first, arithmetic second. Echoes the RSS in MB, or nothing at all.
#
# The pid is baked into the command string with printf. `powershell -Command` does
# NOT accept -args -- that is -File only -- and passing it that way left the
# variable unbound so that EVERY process looked dead. That bug was invisible to the
# dead-pid test and only showed up when the positive case was run against a process
# known to be alive, which is why both directions are tested.
ps_rss() {
  local cmd
  cmd=$(printf '$p = Get-CimInstance Win32_Process -Filter "ProcessId=%s" -ErrorAction SilentlyContinue; if ($null -eq $p) { exit 3 }; [int]($p.WorkingSetSize / 1MB)' "$1")
  powershell -NoProfile -Command "$cmd" 2>/dev/null | tr -d '\r' | tr -d ' '
}

while true; do
  TS=$(date +%Y-%m-%dT%H:%M:%S)
  RSS=$(ps_rss "$PID")
  AVAIL=$(powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  TOTAL=$(powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  GPU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
  NPY=$(powershell -NoProfile -Command "(Get-Process python -ErrorAction SilentlyContinue).Count" 2>/dev/null | tr -d '\r')

  # THE STOP. An empty RSS means the process is not there -- recorded as GONE,
  # never as 0, and the loop ends instead of describing a corpse for another day
  # and a half.
  if [ -z "$RSS" ]; then
    printf "%s\t%s\tGONE\t%s\t%s\t%s\t%s\n" \
      "$TS" "$PID" "${AVAIL:-?}" "${TOTAL:-?}" "${GPU:-?}" "${NPY:-?}" >> "$OUT"
    printf "%s\tTRAINER_GONE\tpid %s no longer exists; sampler exiting\n" "$TS" "$PID" >> "$OUT"
    echo "[sampler] pid $PID is gone -- exiting after recording it"
    break
  fi

  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$TS" "$PID" "$RSS" "${AVAIL:-?}" "${TOTAL:-?}" "${GPU:-?}" "${NPY:-?}" >> "$OUT"
  sleep "$INTERVAL"
done
