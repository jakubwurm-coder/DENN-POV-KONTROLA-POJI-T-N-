param([switch]$Install)
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "DENNI_POV_SERVICE"
$app = Join-Path $root "app"
$log = Join-Path $root "auto-update.log"
$taskName = "DENNI POV Auto Update"
$agentTask = "DENNI POV Online Agent"

if ($env:COMPUTERNAME.ToUpperInvariant() -ne "VCSERVER") {
    throw "Updater je urcen jen pro VCSERVER."
}
if (-not (Test-Path (Join-Path $app ".git"))) {
    throw "Nenalezen Git repozitar: $app"
}
New-Item -ItemType Directory -Path $root -Force | Out-Null
function Log([string]$message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $line
}

if ($Install) {
    # Zadani hesla pouze pri instalaci: Windows Task Scheduler je ulozi
    # bezpecne pro batch logon, skript samotny heslo nikam nezapisuje.
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $secure = Read-Host "Zadej heslo uctu $identity pro beh bez prihlaseni" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrEmpty($password)) { throw "Heslo nebylo zadano; uloha nezmenena." }
    try {
        $scriptPath = Join-Path $app "AUTO_UPDATE_WINDOWS_AGENT.ps1"
        $quoted = '"' + $scriptPath + '"'
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File $quoted"
        $startup = New-ScheduledTaskTrigger -AtStartup
        $periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15)
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startup, $periodic) -Settings $settings -User $identity -Password $password -RunLevel Limited -Force | Out-Null
        Log "Naplanovano: pri startu Windows a kazdych 15 minut bez prihlaseni ($identity)."
    } finally {
        $password = $null
        $secure.Dispose()
    }
    exit 0
}

$mutex = New-Object System.Threading.Mutex($false, "Global\DenniPovAutoUpdate")
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
    Push-Location $app
    try {
        $changes = & git status --porcelain --untracked-files=no
        if ($LASTEXITCODE -ne 0 -or $changes) {
            Log "Preskoceno: v repozitari existuji mistni upravy nebo chyba gitu."
            exit 1
        }
        $old = (& git rev-parse HEAD).Trim()
        & git fetch --quiet origin main
        if ($LASTEXITCODE -ne 0) { Log "Chyba git fetch, stara verze zachovana."; exit 1 }
        $new = (& git rev-parse FETCH_HEAD).Trim()
        if ($old -eq $new) { exit 0 }
        & git merge-base --is-ancestor $old $new
        if ($LASTEXITCODE -ne 0) { Log "Nepovolena nefast-forward aktualizace."; exit 1 }
        $py = Join-Path $app ".venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { $py = Join-Path $root "python-portable\python.exe" }
        if (-not (Test-Path $py)) { Log "Chybi virtualni i portable Python; aktualizace zastavena."; exit 1 }
        & git merge --ff-only $new
        if ($LASTEXITCODE -ne 0) { Log "Git merge selhal."; exit 1 }
        & $py -m compileall -q $app
        if ($LASTEXITCODE -ne 0) {
            & git reset --hard $old | Out-Null
            Log "Kontrola syntaxe selhala, obnovena predchozi verze $old."
            exit 1
        }
        $agent = Get-ScheduledTask -TaskName $agentTask -ErrorAction SilentlyContinue
        if ($null -eq $agent) {
            Log "Kod aktualizovan na $new, ale uloha agenta nebyla nalezena. Restart neproveden."
            exit 0
        }
        Stop-ScheduledTask -TaskName $agentTask -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $agentTask
        Log "Agent aktualizovan z $old na $new a restartovan."
    } finally { Pop-Location }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
