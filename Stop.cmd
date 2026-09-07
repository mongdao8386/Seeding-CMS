@echo off
REM Dung API, worker, dashboard va cac container.
REM Du lieu khong bi xoa - container chi dung lai chu khong bi go.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Stop
