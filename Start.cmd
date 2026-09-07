@echo off
REM Bam doi vao file nay de bat toan bo he thong.
REM -ExecutionPolicy Bypass chi ap dung cho lan chay nay, khong doi cai dat cua may.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
