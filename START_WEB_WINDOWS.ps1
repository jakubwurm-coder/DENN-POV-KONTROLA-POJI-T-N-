$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=============================================="
Write-Host " DENNI POV - WEB / WINDOWS"
Write-Host "=============================================="
Write-Host ""

if (Test-Path ".git") {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Write-Host "Kontroluji nejnovější verzi z GitHubu..."
        try {
            git pull --ff-only origin main
        } catch {
            Write-Host "Aktualizace z GitHubu se nepodařila, pokračuji místní verzí."
        }
        Write-Host ""
    }
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @("py", "-3") }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @("python") }

    $candidates = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($candidates) { return @($candidates[0].FullName) }

    return $null
}

$pythonCmd = Find-Python

if (-not $pythonCmd) {
    Write-Host "Python 3 není nainstalovaný. Zkusím ho nainstalovat přes winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host ""
        Write-Host "CHYBA: Python 3 není nainstalovaný a winget není dostupný."
        Write-Host "Nainstaluj Python 3 z python.org a potom spusť znovu START_WEB_WINDOWS.bat."
        Read-Host "Stiskni Enter pro zavření"
        exit 1
    }

    winget install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
    $pythonCmd = Find-Python

    if (-not $pythonCmd) {
        Write-Host ""
        Write-Host "Python se nainstaloval, ale tento proces ho ještě nevidí."
        Write-Host "Zavři toto okno a spusť START_WEB_WINDOWS.bat ještě jednou."
        Read-Host "Stiskni Enter pro zavření"
        exit 1
    }
}

function Run-Python([string[]]$arguments) {
    if ($pythonCmd.Count -eq 2) {
        & $pythonCmd[0] $pythonCmd[1] @arguments
    } else {
        & $pythonCmd[0] @arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python skončil s chybou $LASTEXITCODE"
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "První spuštění: vytvářím Python prostředí..."
    Run-Python @("-m", "venv", ".venv")
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Kontroluji potřebné balíčky..."
& $venvPython -m pip install --upgrade pip | Out-Null
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Instalace Python balíčků selhala."
}

Write-Host ""
Write-Host "Přihlašovací údaje se použijí jen pro toto spuštění a neuloží se do GitHubu."
Write-Host ""

if (-not $env:TIRBAZAR_PASSWORD) {
    $secureSql = Read-Host "Heslo SQL účtu TB pro TIRBazar" -AsSecureString
    $ptrSql = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSql)
    try {
        $env:TIRBAZAR_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptrSql)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptrSql)
    }
}

if (-not $env:UNIQA_USER) {
    $env:UNIQA_USER = Read-Host "UNIQA uživatelské jméno"
}

if (-not $env:UNIQA_PASSWORD) {
    $secureUniqa = Read-Host "UNIQA heslo" -AsSecureString
    $ptrUniqa = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUniqa)
    try {
        $env:UNIQA_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptrUniqa)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptrUniqa)
    }
}

$env:PORT = "5001"

$oldPid = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($oldPid) {
    Write-Host "Ukončuji předchozí instanci na portu 5001..."
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:5001/"
} | Out-Null

Write-Host ""
Write-Host "Web se spouští na: http://127.0.0.1:5001/"
Write-Host "Toto okno nech otevřené po dobu běhu aplikace."
Write-Host ""

try {
    & $venvPython windows_bootstrap.py
} finally {
    Remove-Item Env:TIRBAZAR_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:UNIQA_PASSWORD -ErrorAction SilentlyContinue
}
