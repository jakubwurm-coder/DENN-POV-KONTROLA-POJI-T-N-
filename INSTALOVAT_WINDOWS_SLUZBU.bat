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
echo  DENNI POV - INSTALACE WINDOWS AGENTA
echo ==============================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ENSURE_WINDOWS_PYTHON.ps1"
set "PYCODE=%ERRORLEVEL%"
if not "%PYCODE%"=="0" (
    echo.
    echo ==============================================
    echo  INSTALACE PYTHONU SKONCILA CHYBOU - kod %PYCODE%
    echo ==============================================
    echo.
    echo Okno se nezavre. Posli mi text chyby vyse nebo fotografii obrazovky.
    echo.
    pause
    endlocal & exit /b %PYCODE%
)

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
