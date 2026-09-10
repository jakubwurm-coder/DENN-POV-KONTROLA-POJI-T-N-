@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo ==============================================
    echo  DENNI POV - VYZADUJI OPRAVNENI SPRAVCE
    echo ==============================================
    echo.
    echo Oteviram instalator jako administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c ""%~f0""' -Verb RunAs"
    endlocal
    exit /b 0
)

echo ==============================================
echo  DENNI POV - PORTABLE WINDOWS AGENT
echo ==============================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_WINDOWS_SERVICE_PORTABLE.ps1"
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo ==============================================
    echo  INSTALACE SKONCILA CHYBOU - kod %EXITCODE%
    echo ==============================================
    echo.
    echo Okno se nezavre. Posli mi text chyby vyse nebo fotografii obrazovky.
) else (
    echo Instalace probehla bez hlasene chyby.
)

echo.
pause
endlocal & exit /b %EXITCODE%
