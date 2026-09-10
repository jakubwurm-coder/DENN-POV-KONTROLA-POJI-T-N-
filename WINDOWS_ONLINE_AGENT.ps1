$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$storeDir = Join-Path $env:LOCALAPPDATA "DENNI_POV_KONTROLA"
New-Item -ItemType Directory -Path $storeDir -Force | Out-Null
$logPath = Join-Path $storeDir "online-agent.log"
$sqlCredPath = Join-Path $storeDir "tirbazar.credential.xml"
$uniqaCredPath = Join-Path $storeDir "uniqa.credential.xml"

function Write-AgentLog([string]$message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value ("[" + $stamp + "] " + $message) -Encoding UTF8
}

function Load-SecureCredential([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try { return Import-Clixml -Path $path } catch { return $null }
}

Write-AgentLog "DENNI POV online agent startuje."

$savedSql = Load-SecureCredential $sqlCredPath
if ($savedSql) {
    $net = $savedSql.GetNetworkCredential()
    $env:TIRBAZAR_USER = $net.UserName
    $env:TIRBAZAR_PASSWORD = $net.Password
}

$savedUniqa = Load-SecureCredential $uniqaCredPath
if ($savedUniqa) {
    $net = $savedUniqa.GetNetworkCredential()
    $env:UNIQA_USER = $net.UserName
    $env:UNIQA_PASSWORD = $net.Password
}

if (-not $env:TIRBAZAR_PASSWORD) {
    Write-AgentLog "CHYBA: chybi ulozene TIRBazar prihlaseni. Spust jednou instalator sluzby."
    exit 2
}

if (-not $env:UNIQA_USER -or -not $env:UNIQA_PASSWORD) {
    Write-AgentLog "CHYBA: chybi ulozene UNIQA prihlaseni. Spust jednou instalator sluzby."
    exit 3
}

$gitExe = $null
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd -and $gitCmd.Source) {
    $gitExe = $gitCmd.Source
} elseif (Test-Path "C:\Program Files\Git\cmd\git.exe") {
    $gitExe = "C:\Program Files\Git\cmd\git.exe"
}

if ($gitExe -and (Test-Path ".git")) {
    try {
        Write-AgentLog "Kontroluji aktualizaci z GitHubu..."
        $fetchOutput = (& $gitExe fetch origin main 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            Write-AgentLog ("VAROVANI: git fetch selhal: " + $fetchOutput)
        } else {
            $resetOutput = (& $gitExe reset --hard origin/main 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0) {
                Write-AgentLog ("GitHub aktualizace OK: " + $resetOutput)
            } else {
                Write-AgentLog ("VAROVANI: git reset selhal: " + $resetOutput)
            }
        }
    } catch {
        Write-AgentLog ("VAROVANI: aktualizace z GitHubu se nepodarila: " + $_.Exception.Message)
    }
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$serviceRoot = Split-Path $PSScriptRoot -Parent
$portablePython = Join-Path $serviceRoot "python-portable\python.exe"

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
    Write-AgentLog "Pouzivam Python z .venv."
} elseif (Test-Path $portablePython) {
    $pythonExe = $portablePython
    Write-AgentLog "Pouzivam portable Python."
} else {
    Write-AgentLog "CHYBA: chybi Python runtime. Spust jednou instalator Windows sluzby."
    exit 4
}

$env:DENNI_POV_CLOUD_URL = "https://denni-pov-kontrola.onrender.com"
$env:DENNI_POV_SERVICE_MODE = "1"
$env:PYTHONUNBUFFERED = "1"

while ($true) {
    try {
        Write-AgentLog "Spoustim cloud_agent.py"
        & $pythonExe -u (Join-Path $PSScriptRoot "cloud_agent.py") *>> $logPath
        $exitCode = $LASTEXITCODE
        Write-AgentLog ("cloud_agent.py skoncil s kodem " + $exitCode + ". Restart za 15 s.")
    } catch {
        Write-AgentLog ("CHYBA agenta: " + $_.Exception.Message + ". Restart za 15 s.")
    }
    Start-Sleep -Seconds 15
}
