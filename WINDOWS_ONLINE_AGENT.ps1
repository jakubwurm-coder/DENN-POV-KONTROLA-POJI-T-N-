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
    try {
        return Import-Clixml -Path $path
    } catch {
        return $null
    }
}

function Find-GitExe {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

Write-AgentLog "DENNI POV online agent startuje."

# Agent bezi pod stejnym Windows uzivatelem jako ulozene DPAPI udaje.
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
    Write-AgentLog "CHYBA: chybi ulozene TIRBazar prihlaseni. Spust jednou instalator sluzby nebo START_WEB_WINDOWS_AUTO."
    exit 2
}

if (-not $env:UNIQA_USER -or -not $env:UNIQA_PASSWORD) {
    Write-AgentLog "CHYBA: chybi ulozene UNIQA prihlaseni. Spust jednou instalator sluzby nebo START_WEB_WINDOWS_AUTO."
    exit 3
}

$gitExe = Find-GitExe
if ($gitExe -and (Test-Path ".git")) {
    try {
        Write-AgentLog ("Kontroluji aktualizaci z GitHubu pres " + $gitExe)
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
} elseif (-not $gitExe) {
    Write-AgentLog "VAROVANI: Git nebyl nalezen. Agent pobezi, ale nebude se sam aktualizovat z GitHubu."
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-AgentLog "CHYBA: chybi .venv Python. Spust jednou instalator Windows sluzby."
    exit 4
}

$env:DENNI_POV_CLOUD_URL = "https://denni-pov-kontrola.onrender.com"
$env:DENNI_POV_SERVICE_MODE = "1"
$env:PYTHONUNBUFFERED = "1"

# Kdyby agent spadl nebo byl po aktualizaci ukoncen, runner ho znovu nastartuje.
while ($true) {
    try {
        Write-AgentLog "Spoustim cloud_agent.py"
        & $venvPython -u (Join-Path $PSScriptRoot "cloud_agent.py") *>> $logPath
        $exitCode = $LASTEXITCODE
        Write-AgentLog ("cloud_agent.py skoncil s kodem " + $exitCode + ". Restart za 15 s.")
    } catch {
        Write-AgentLog ("CHYBA agenta: " + $_.Exception.Message + ". Restart za 15 s.")
    }
    Start-Sleep -Seconds 15
}
