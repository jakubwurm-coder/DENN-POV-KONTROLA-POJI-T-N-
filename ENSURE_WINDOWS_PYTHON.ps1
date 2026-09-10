$ErrorActionPreference = "Stop"

function Find-PythonExe {
    $candidates = @(
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            try {
                & $candidate -c "import sys; print(sys.version)" *> $null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            } catch {}
        }
    }

    foreach ($name in @("python.exe", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) {
            try {
                & $cmd.Source -c "import sys; print(sys.version)" *> $null
                if ($LASTEXITCODE -eq 0) { return $cmd.Source }
            } catch {}
        }
    }
    return $null
}

$existing = Find-PythonExe
if ($existing) {
    $version = (& $existing --version 2>&1 | Out-String).Trim()
    Write-Host ("Python uz je pripraven: " + $version + " - " + $existing)
    exit 0
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Instalace Pythonu na tomto Windows Serveru vyzaduje opravneni spravce. Spust instalator jako administrator."
}

$pythonVersion = "3.11.9"
$installer = Join-Path $env:TEMP ("python-" + $pythonVersion + "-amd64.exe")
$installLog = Join-Path $env:TEMP "denni-pov-python-admin-install.log"
$targetDir = "C:\Program Files\Python311"
$downloadUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"

Write-Host "Windows Server blokuje instalaci Pythonu pro bezneho uzivatele."
Write-Host "Instaluji Python $pythonVersion pro cely server s opravnenim spravce..."

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not (Test-Path $installer)) {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installer -UseBasicParsing
}

$args = @(
    "/quiet",
    "InstallAllUsers=1",
    "TargetDir=$targetDir",
    "PrependPath=1",
    "Include_pip=1",
    "Include_launcher=0",
    "Include_test=0",
    "Include_doc=0",
    "Include_tcltk=0",
    "Shortcuts=0",
    "/log",
    $installLog
)

$process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
    if ($process.ExitCode -eq 1625) {
        throw "Windows Group Policy zakazala i administratorskou instalaci Pythonu (kod 1625). Log: $installLog"
    }
    throw "Instalace Pythonu skoncila kodem $($process.ExitCode). Log: $installLog"
}

Start-Sleep -Seconds 2
if (-not (Test-Path (Join-Path $targetDir "python.exe"))) {
    throw "Python instalator skoncil bez chyby, ale python.exe nebyl nalezen v $targetDir. Log: $installLog"
}

$version = (& (Join-Path $targetDir "python.exe") --version 2>&1 | Out-String).Trim()
Write-Host ("Python pripraven: " + $version + " - " + (Join-Path $targetDir "python.exe"))
exit 0
