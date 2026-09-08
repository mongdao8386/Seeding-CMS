@echo off
rem Worker ARQ trong vong lap: chet la 5 giay sau tu bat lai. Ctrl+C hai lan de thoat han.
rem 08/09/2026: cua so worker con mo ma python da chet tu luc nao, lich nuoi dung im ca buoi.
cd /d "%~dp0.."
:loop
".venv\Scripts\python.exe" -m arq seeding.worker.settings.WorkerSettings
echo.
echo Worker da dung (ma thoat %ERRORLEVEL%). 5 giay nua bat lai - Ctrl+C de thoat.
timeout /t 5 /nobreak >nul
goto loop
