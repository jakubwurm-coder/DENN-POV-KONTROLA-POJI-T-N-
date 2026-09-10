@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo  DENNI POV - INSTALACE WINDOWS AGENTA
echo ==============================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_WINDOWS_SERVICE.ps1"
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo ==============================================
    echo  INSTALACE SKONCILA CHYBOU - kod %EXITCODE%
    echo ==============================================
    echo.
    echo Okno se nezavre. Posli mi text chyby vyse nebo fotografii obrazovky.
) else (
    echo Instalator skoncil bez hlasene chyby.
)

echo.
pause
endlocal & exit /b %EXITCODE%
