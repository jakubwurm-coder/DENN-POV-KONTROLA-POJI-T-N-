$ErrorActionPreference = "Stop"

$repoUrl = "https://github.com/jakubwurm-coder/DENN-POV-KONTROLA-POJI-T-N-.git"
$taskName = "DENNI POV Online Agent"
$serviceRoot = Join-Path $env:LOCALAPPDATA "DENNI_POV_SERVICE"
$appDir = Join-Path $serviceRoot "app"
$pythonDir = Join-Path $serviceRoot "python-portable"
$pythonExe = Join-Path $pythonDir "python.exe"
$credentialDir = Join-Path $env:LOCALAPPDATA "DENNI_POV_KONTROLA"
$sqlCredPath = Join-Path $credentialDir "tirbazar.credential.xml"
$uniqaCredPath = Join-Path $credentialDir "uniqa.credential.xml"
$pythonVersion = "3.11.9"

New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
New-Item -ItemType Directory -Path $credentialDir -Force | Out-Null

function Load-SecureCredential([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try { return Import-Clixml -Path $path } catch { return $null }
}

function Save-SecureCredential([string]$path, [System.Management.Automation.PSCredential]$cred) {
    $cred | Export-Clixml -Path $path
}

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($candidate in @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Ensure-Credentials {
    if (-not (Load-SecureCredential $sqlCredPath)) {
        Write-Host "SQL prihlaseni neni ulozene. Zadas ho pouze jednou."
        $sqlUser = Read-Host "TIRBazar SQL uzivatel (vychozi TB)"
        if ([string]::IsNullOrWhiteSpace($sqlUser)) { $sqlUser = "TB" }
        $sqlSecure = Read-Host "TIRBazar SQL heslo" -AsSecureString
        Save-SecureCredential $sqlCredPath (New-Object System.Management.Automation.PSCredential($sqlUser, $sqlSecure))
    }

    if (-not (Load-SecureCredential $uniqaCredPath)) {
        Write-Host "UNIQA prihlaseni neni ulozene. Zadas ho pouze jednou."
        $uniqaUser = Read-Host "UNIQA uzivatelske jmeno"
        $uniqaSecure = Read-Host "UNIQA heslo" -AsSecureString
        Save-SecureCredential $uniqaCredPath (New-Object System.Management.Automation.PSCredential($uniqaUser, $uniqaSecure))
    }
}

function Update-ServiceCopy([string]$gitExe) {
    if (Test-Path (Join-Path $appDir ".git")) {
        Write-Host "Aktualizuji servisni kopii z GitHubu..."
        & $gitExe -C $appDir fetch origin main
        if ($LASTEXITCODE -ne 0) { throw "Git fetch selhal." }
        & $gitExe -C $appDir reset --hard origin/main
        if ($LASTEXITCODE -ne 0) { throw "Aktualizace servisni kopie selhala." }
    } else {
        if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
        Write-Host "Vytvarim cistou servisni kopii z GitHubu..."
        & $gitExe clone --branch main --single-branch $repoUrl $appDir
        if ($LASTEXITCODE -ne 0) { throw "Git clone selhal." }
    }
}

function Ensure-PortablePython {
    if (Test-Path $pythonExe) {
        try {
            & $pythonExe -c "import sys; print(sys.version)" *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Portable Python uz je pripraven."
                return
            }
        } catch {}
    }

    Write-Host "Pripravuji portable Python $pythonVersion - bez instalace do Windows..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zipPath = Join-Path $env:TEMP ("python-$pythonVersion-embed-amd64.zip")
    $zipUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip"
    if (-not (Test-Path $zipPath)) {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    }

    if (Test-Path $pythonDir) { Remove-Item $pythonDir -Recurse -Force }
    New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $pythonDir -Force

    $pth = Join-Path $pythonDir "python311._pth"
    @(
        "python311.zip",
        ".",
        "Lib",
        "Lib\site-packages",
        "import site"
    ) | Set-Content -LiteralPath $pth -Encoding ASCII

    New-Item -ItemType Directory -Path (Join-Path $pythonDir "Lib\site-packages") -Force | Out-Null

    if (-not (Test-Path $pythonExe)) { throw "Portable python.exe nebyl po rozbaleni nalezen." }

    $getPip = Join-Path $pythonDir "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
    & $pythonExe $getPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "Inicializace pip pro portable Python selhala." }

    $versionText = (& $pythonExe --version 2>&1 | Out-String).Trim()
    Write-Host ("Portable Python pripraven: " + $versionText)
}

function Install-Requirements {
    Write-Host "Instaluji/aktualizuji potrebne Python balicky..."
    & $pythonExe -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $appDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Instalace Python balicku selhala." }
}

function Register-AgentTask {
    $runner = Join-Path $appDir "WINDOWS_ONLINE_AGENT.ps1"
    $quotedRunner = '"' + $runner + '"'
    $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $quotedRunner"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User ("$env:USERDOMAIN\$env:USERNAME")
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 10 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
    $principal = New-ScheduledTaskPrincipal `
        -UserId ("$env:USERDOMAIN\$env:USERNAME") `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "DENNI POV - automaticky online agent pro TIRBazar, UNIQA a Render" `
        -Force | Out-Null

    try { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } catch {}
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "=============================================="
Write-Host " DENNI POV - PORTABLE WINDOWS AGENT"
Write-Host "=============================================="
Write-Host ""

Ensure-Credentials
$gitExe = Find-Git
if (-not $gitExe) { throw "Git nebyl nalezen." }
Update-ServiceCopy $gitExe
Ensure-PortablePython
Install-Requirements
Register-AgentTask

$task = Get-ScheduledTask -TaskName $taskName
Write-Host ""
Write-Host "=============================================="
Write-Host " HOTOVO"
Write-Host "=============================================="
Write-Host ("Sluzba: " + $taskName)
Write-Host ("Stav: " + $task.State)
Write-Host "Python: portable, bez instalace do Windows"
Write-Host "Automaticka kontrola: kazdych 15 minut"
Write-Host "Online tlacitko: kontrola pozadavku kazdych 15 sekund"
Write-Host "Online web: https://denni-pov-kontrola.onrender.com"
Write-Host ("Log: " + (Join-Path $credentialDir "online-agent.log"))
Write-Host ""
Start-Process "https://denni-pov-kontrola.onrender.com"
