@echo off
set "T=%LOCALAPPDATA%\Programs\DailyPrison\uninstall.ps1"
if not exist "%T%" goto missing
powershell -NoProfile -ExecutionPolicy Bypass -File "%T%"
goto end
:missing
echo DailyPrison is not installed in %LOCALAPPDATA%\Programs\DailyPrison
:end
echo.
pause
