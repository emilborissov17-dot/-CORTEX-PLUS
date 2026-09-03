@echo off
rem Double-click wrapper for tools\install_media_deps.ps1 (ffmpeg + deno via winget).
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\install_media_deps.ps1"
echo.
pause
