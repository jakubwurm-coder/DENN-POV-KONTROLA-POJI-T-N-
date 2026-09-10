$ErrorActionPreference = "Stop"

$repoUrl = "https://github.com/jakubwurm-coder/DENN-POV-KONTROLA-POJI-T-N-.git"
$taskName = "DENNI POV Online Agent"
$serviceRoot = Join-Path $env:LOCALAPPDATA "DENNI_POV_SERVICE"
$appDir = Join-Path $serviceRoot "app"
$credentialDir = Join-Path $env:LOCALAPPDATA "DENNI_POV_KONTROLA"
$sqlCredPath = Join-Path $credentialDir "tirbazar.credential.xml"
$uniqaCredPath = Join-Path $credentialDir "uniqa.credential.xml"

New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
New-Item -ItemType Directory -Path $credentialDir -Force | Out-Null

function Save-SecureCredential([string]$path, [string]$username, [string]$password) {
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($username, $secure)
    $cred | Export-Clixml -Path $path
}

function Load-SecureCredential([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try { return Import-Clixml -Path $path } catch { return $null }
}

function Try-Load-TirBazarFromConfig {
    $paths = @()
    try {
        Get-Process TIRBazar -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Path) { $paths += ($_.Path + ".config") }
        }
    } catch {}

    $paths += (Join-Path $PSScriptRoot "TIRBazar.exe.config")

    foreach ($path in ($paths | Select-Object -Unique)) {
        if (-not (Test-Path $path)) { continue }
        try {
            [xml]$xml = Get-Content -LiteralPath $path -Raw
            $conn = $null
            $appSetting = $xml.configuration.appSettings.add | Where-Object { $_.key -eq "DBConnectionString" } | Select-Object -First 1
            if ($appSetting) { $conn = [string]$appSetting.value }
            if (-not $conn) {
                $item = $xml.configuration.connectionStrings.add | Where-Object { $_.connectionString -match "TIRBazar" } | Select-Object -First 1
                if ($item) { $conn = [string]$item.connectionString }
            }
            if (-not $conn) { continue }

            $user = "TB"
            $password = ""
            if ($conn -match '(?i)(?:User ID|User)\s*=\s*([^;]+)') { $user = $matches[1].Trim() }
            if ($conn -match '(?i)Password\s*=\s*([^;]+)') { $password = $matches[1] }
            if ($password) {
                Save-SecureCredential $sqlCredPath $user $password
                return $true
            }
        } catch {}
    }
    return $false
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            & py -3.12 -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) { return @("py", "-3.12") }
        } catch {}
        try {
            & py -3 -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) { return @("py", "-3") }
        } catch {}
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            & python -c "import sys" *> $null
            if ($LASTEXITCODE -eq 0) { return @("python") }
        } catch {}
    }

    $localCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($candidate in $localCandidates) {
        if (Test-Path $candidate) { return @($candidate) }
    }
    return $null
}

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }

    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe"),
        (Join-Path $env:LOCALAPPDATA "GitHubDesktop\app-*\resources\app\git\cmd\git.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -like "*`**") {
            $found = Get-Item $candidate -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
            if ($found) { return $found.FullName }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Install-GitIfNeeded {
    $gitExe = Find-Git
    if ($gitExe) { return $gitExe }

    Write-Host "Git neni nainstalovany. Zkusim ho automaticky doinstalovat pres winget..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Git neni dostupny a winget na tomto serveru neni nainstalovany. Nainstaluj Git for Windows a instalator spust znovu."
    }

    & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Prvni instalace Gitu selhala. Zkusim obnovit zdroj winget a opakovat..."
        & winget source reset --force
        & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Automaticka instalace Git for Windows selhala. Posli mi text chyby z tohoto okna."
    }

    # Obnov PATH aktualniho PowerShell procesu a Git znovu dohledame.
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    Start-Sleep -Seconds 2
    $gitExe = Find-Git
    if (-not $gitExe) {
        throw "Git byl nainstalovan, ale tento proces ho zatim nevidi. Zavri okno a spust INSTALOVAT_WINDOWS_SLUZBU.bat znovu."
    }

    Write-Host ("Git pripraven: " + $gitExe)
    return $gitExe
}

Write-Host ""
Write-Host "=============================================="
Write-Host " DENNI POV - INSTALACE ONLINE SLUZBY"
Write-Host "=============================================="
Write-Host ""

# 1) Prihlaseni - pouzij uz drive ulozene udaje, nic znovu nevyzaduj pokud existuji.
if (-not (Load-SecureCredential $sqlCredPath)) {
    [void](Try-Load-TirBazarFromConfig)
}

if (-not (Load-SecureCredential $sqlCredPath)) {
    Write-Host "SQL prihlaseni zatim neni ulozene. Zadas ho pouze ted pri prvni instalaci."
    $sqlUser = Read-Host "TIRBazar SQL uzivatel (vychozi TB)"
    if ([string]::IsNullOrWhiteSpace($sqlUser)) { $sqlUser = "TB" }
    $sqlSecure = Read-Host "TIRBazar SQL heslo" -AsSecureString
    $sqlCred = New-Object System.Management.Automation.PSCredential($sqlUser, $sqlSecure)
    $sqlCred | Export-Clixml -Path $sqlCredPath
}

if (-not (Load-SecureCredential $uniqaCredPath)) {
    Write-Host "UNIQA prihlaseni zatim neni ulozene. Zadas ho pouze ted pri prvni instalaci."
    $uniqaUser = Read-Host "UNIQA uzivatelske jmeno"
    $uniqaSecure = Read-Host "UNIQA heslo" -AsSecureString
    $uniqaCred = New-Object System.Management.Automation.PSCredential($uniqaUser, $uniqaSecure)
    $uniqaCred | Export-Clixml -Path $uniqaCredPath
}

# 2) Cista servisni kopie repozitare. Nepracuje s uzivatelovou GitHub Desktop slozkou.
$gitExe = Install-GitIfNeeded

if (Test-Path (Join-Path $appDir ".git")) {
    Write-Host "Aktualizuji servisni kopii z GitHubu..."
    & $gitExe -C $appDir fetch origin main
    if ($LASTEXITCODE -ne 0) { throw "Git fetch selhal. Pokud je repozitar soukromy, prihlas tento Windows server jednou ke GitHubu." }
    & $gitExe -C $appDir reset --hard origin/main
    if ($LASTEXITCODE -ne 0) { throw "Aktualizace servisni kopie selhala." }
} else {
    if (Test-Path $appDir) { Remove-Item $appDir -Recurse -Force }
    Write-Host "Vytvarim cistou servisni kopii z GitHubu..."
    & $gitExe clone --branch main --single-branch $repoUrl $appDir
    if ($LASTEXITCODE -ne 0) {
        throw "Git clone selhal. Repozitar je soukromy - tento Windows server je potreba jednou prihlasit ke GitHubu."
    }
}

# 3) Python prostredi pro sluzbu.
$pythonSpec = Find-Python
if (-not $pythonSpec) {
    throw "Na Windows neni nalezen Python. Nejdrive spust START_WEB_WINDOWS_AUTO, ktery Python umi doinstalovat."
}

$venvPython = Join-Path $appDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Vytvarim Python prostredi sluzby..."
    if ($pythonSpec.Count -eq 2) {
        & $pythonSpec[0] $pythonSpec[1] -m venv (Join-Path $appDir ".venv")
    } else {
        & $pythonSpec[0] -m venv (Join-Path $appDir ".venv")
    }
    if ($LASTEXITCODE -ne 0) { throw "Vytvoreni Python prostredi selhalo." }
}

Write-Host "Instaluji/aktualizuji potrebne balicky..."
& $venvPython -m pip install -r (Join-Path $appDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Instalace Python balicku selhala." }

# 4) Trvaly skryty agent v Planovaci uloh pod stejnym Windows uctem.
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
Start-Sleep -Seconds 2

$task = Get-ScheduledTask -TaskName $taskName
Write-Host ""
Write-Host "HOTOVO"
Write-Host ("Sluzba: " + $taskName)
Write-Host ("Stav: " + $task.State)
Write-Host "Automaticky start: po prihlaseni do Windows"
Write-Host "Automaticka kontrola: kazdych 15 minut"
Write-Host "Online tlacitko: agent kontroluje pozadavek kazdych 15 sekund"
Write-Host "Online web: https://denni-pov-kontrola.onrender.com"
Write-Host ("Log: " + (Join-Path $credentialDir "online-agent.log"))
Write-Host ""
Start-Process "https://denni-pov-kontrola.onrender.com"
Read-Host "Stiskni Enter pro zavreni instalatoru"
