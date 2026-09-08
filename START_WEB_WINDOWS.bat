@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_WEB_WINDOWS.ps1"
if errorlevel 1 (
  echo.
  echo Spusteni skoncilo chybou.
  pause
)
