$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=============================================="
Write-Host " DENNI POV - WEB / WINDOWS"
Write-Host "=============================================="
Write-Host ""

# Keep launcher messages ASCII-only because Windows PowerShell 5.1 may
# misread UTF-8 .ps1 files without BOM and display mojibake.

if (Test-Path ".git") {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Write-Host "Kontroluji aktualni verzi z GitHubu..."
        try {
            git pull --ff-only origin main
        } catch {
            Write-Host "Aktualizace z GitHubu se nepodarila, pokracuji mistni verzi."
        }
        Write-Host ""
    }
}

function Test-PythonCommand($spec) {
    try {
        & $spec.Exe @($spec.Prefix) -c "import sys; print(sys.executable)" *> $null
        if ($LASTEXITCODE -ne 0) { return $false }

        & $spec.Exe @($spec.Prefix) -m pip --version *> $null
        if ($LASTEXITCODE -eq 0) { return $true }

        # Some normal python.org installs have ensurepip but pip was not
        # initialized yet. Try to repair the base interpreter once.
        & $spec.Exe @($spec.Prefix) -m ensurepip --upgrade *> $null
        if ($LASTEXITCODE -ne 0) { return $false }

        & $spec.Exe @($spec.Prefix) -m pip --version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-WorkingPython {
    $choices = @()

    if (Get-Command py -ErrorAction SilentlyContinue) {
        # Prefer versions with the broadest package compatibility.
        $choices += [pscustomobject]@{ Exe = "py"; Prefix = @("-3.12"); Label = "Python 3.12" }
        $choices += [pscustomobject]@{ Exe = "py"; Prefix = @("-3.11"); Label = "Python 3.11" }
        $choices += [pscustomobject]@{ Exe = "py"; Prefix = @("-3.13"); Label = "Python 3.13" }
        $choices += [pscustomobject]@{ Exe = "py"; Prefix = @("-3"); Label = "Python 3" }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $choices += [pscustomobject]@{ Exe = "python"; Prefix = @(); Label = "python" }
    }

    $localPythons = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    foreach ($candidate in $localPythons) {
        $choices += [pscustomobject]@{ Exe = $candidate.FullName; Prefix = @(); Label = $candidate.FullName }
    }

    foreach ($choice in $choices) {
        if (Test-PythonCommand $choice) {
            return $choice
        }
    }

    return $null
}

function Invoke-BasePython($spec, [string[]]$arguments) {
    & $spec.Exe @($spec.Prefix) @arguments
}

$python = Find-WorkingPython

if (-not $python) {
    Write-Host "Nenasel jsem funkcni Python s pip. Instaluji Python 3.12 pres winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host ""
        Write-Host "CHYBA: Na PC neni funkcni Python s pip a winget neni dostupny."
        Write-Host "Nainstaluj Python 3.12 z python.org a zaskrtni volby pip a Add python.exe to PATH."
        Read-Host "Stiskni Enter pro zavreni"
        exit 1
    }

    winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements

    # The Python launcher reads installed versions from the registry, so it
    # often sees the new interpreter immediately even before a new terminal.
    $python = Find-WorkingPython

    if (-not $python) {
        Write-Host ""
        Write-Host "Python 3.12 byl nainstalovan. Zavri toto okno a spust START_WEB_WINDOWS.bat znovu."
        Read-Host "Stiskni Enter pro zavreni"
        exit 0
    }
}

Write-Host ("Pouzivam: " + $python.Label)

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$useVenv = $false

# Remove a half-created environment left behind by a failed ensurepip.
if (Test-Path ".venv") {
    $venvOk = $false
    if (Test-Path $venvPython) {
        try {
            & $venvPython -m pip --version *> $null
            $venvOk = ($LASTEXITCODE -eq 0)
        } catch {
            $venvOk = $false
        }
    }

    if (-not $venvOk) {
        Write-Host "Odstranuji nedokoncene Python prostredi z predchoziho pokusu..."
        Remove-Item ".venv" -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        $useVenv = $true
    }
}

if (-not $useVenv) {
    Write-Host "Vytvarim Python prostredi..."
    try {
        Invoke-BasePython $python @("-m", "venv", ".venv")
        if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) {
            & $venvPython -m pip --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $useVenv = $true
            }
        }
    } catch {
        $useVenv = $false
    }
}

if ($useVenv) {
    Write-Host "Python prostredi: OK"
    Write-Host "Instaluji potrebne balicky..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Aktualizace pip selhala." }
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Instalace Python balicku selhala." }
    $runtimeMode = "venv"
} else {
    # A broken ensurepip can prevent venv creation even when the base Python
    # and pip work normally. The application does not require a venv, so use
    # the user's site-packages as a safe fallback.
    Write-Host ""
    Write-Host "Vytvoreni .venv se nepodarilo. Pouziji funkcni systemovy Python."
    Write-Host "Instaluji potrebne balicky pro aktualniho uzivatele..."
    Invoke-BasePython $python @("-m", "pip", "install", "--user", "-r", "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Instalace Python balicku selhala."
    }
    $runtimeMode = "base"
}

Write-Host ""
Write-Host "Prihlasovaci udaje se pouziji jen pro toto spusteni a neulozi se do GitHubu."
Write-Host ""

if (-not $env:TIRBAZAR_PASSWORD) {
    $secureSql = Read-Host "Heslo SQL uctu TB pro TIRBazar" -AsSecureString
    $ptrSql = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSql)
    try {
        $env:TIRBAZAR_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptrSql)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptrSql)
    }
}

if (-not $env:UNIQA_USER) {
    $env:UNIQA_USER = Read-Host "UNIQA uzivatelske jmeno"
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
    Write-Host "Ukoncuji predchozi instanci na portu 5001..."
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:5001/"
} | Out-Null

Write-Host ""
Write-Host "Web se spousti na: http://127.0.0.1:5001/"
Write-Host "Toto okno nech otevrene po dobu behu aplikace."
Write-Host ""

try {
    if ($runtimeMode -eq "venv") {
        & $venvPython windows_bootstrap.py
    } else {
        Invoke-BasePython $python @("windows_bootstrap.py")
    }
} finally {
    Remove-Item Env:TIRBAZAR_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:UNIQA_PASSWORD -ErrorAction SilentlyContinue
}
