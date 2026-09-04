#!/usr/bin/env bash
# Samples the shape of a death: trainer RSS, system available RAM, GPU MiB, every 30s.
# Added 4 Sep 2026 after a long training run was killed silently with no OOM and no
# traceback, in the same minute three CORTEX tasks woke. A clean stop tells you
# nothing; a curve tells you whether memory was climbing into a ceiling.
OUT="claude/reports/K1B_SAMPLER_4SEP.tsv"
PID="$1"
if [ ! -s "$OUT" ]; then
  printf "ts\ttrainer_pid\ttrainer_rss_mb\tsys_avail_mb\tsys_total_mb\tgpu_used_mib\tn_python\n" > "$OUT"
fi
while true; do
  TS=$(date +%Y-%m-%dT%H:%M:%S)
  RSS=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\" | Select-Object -ExpandProperty WorkingSetSize) / 1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  AVAIL=$(powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  TOTAL=$(powershell -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB" 2>/dev/null | tr -d '\r' | cut -d. -f1)
  GPU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)
  NPY=$(powershell -NoProfile -Command "(Get-Process python -ErrorAction SilentlyContinue).Count" 2>/dev/null | tr -d '\r')
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$TS" "$PID" "${RSS:-GONE}" "${AVAIL:-?}" "${TOTAL:-?}" "${GPU:-?}" "${NPY:-?}" >> "$OUT"
  [ -z "$RSS" ] && printf "%s\tTRAINER_GONE\n" "$TS" >> "$OUT" && break
  sleep 30
done
