$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$storeDir = Join-Path $env:LOCALAPPDATA "DENNI_POV_KONTROLA"
New-Item -ItemType Directory -Path $storeDir -Force | Out-Null

$sqlCredPath = Join-Path $storeDir "tirbazar.credential.xml"
$uniqaCredPath = Join-Path $storeDir "uniqa.credential.xml"

function Save-SecureCredential([string]$path, [string]$username, [string]$password) {
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($username, $secure)
    $cred | Export-Clixml -Path $path
}

function Load-SecureCredential([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try {
        return Import-Clixml -Path $path
    } catch {
        return $null
    }
}

function Try-Load-TirBazarFromConfig {
    $paths = @()

    try {
        Get-Process TIRBazar -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Path) {
                $paths += ($_.Path + ".config")
            }
        }
    } catch {}

    $paths += (Join-Path $PSScriptRoot "TIRBazar.exe.config")

    foreach ($path in ($paths | Select-Object -Unique)) {
        if (-not (Test-Path $path)) { continue }

        try {
            [xml]$xml = Get-Content -LiteralPath $path -Raw
            $conn = $null

            $appSetting = $xml.configuration.appSettings.add | Where-Object { $_.key -eq "DBConnectionString" } | Select-Object -First 1
            if ($appSetting) {
                $conn = [string]$appSetting.value
            }

            if (-not $conn) {
                $item = $xml.configuration.connectionStrings.add | Where-Object { $_.connectionString -match "TIRBazar" } | Select-Object -First 1
                if ($item) {
                    $conn = [string]$item.connectionString
                }
            }

            if (-not $conn) { continue }

            $server = ""
            $database = ""
            $user = ""
            $password = ""

            if ($conn -match '(?i)(?:Data Source|Server)\s*=\s*([^;]+)') { $server = $matches[1].Trim() }
            if ($conn -match '(?i)(?:Initial Catalog|Database)\s*=\s*([^;]+)') { $database = $matches[1].Trim() }
            if ($conn -match '(?i)(?:User ID|User)\s*=\s*([^;]+)') { $user = $matches[1].Trim() }
            if ($conn -match '(?i)Password\s*=\s*([^;]+)') { $password = $matches[1] }

            if ($server) { $env:TIRBAZAR_SERVER = $server }
            if ($database) { $env:TIRBAZAR_DATABASE = $database }
            if ($user) { $env:TIRBAZAR_USER = $user }
            if ($password) { $env:TIRBAZAR_PASSWORD = $password }

            if ($user -and $password) {
                Save-SecureCredential $sqlCredPath $user $password
            }

            return [bool]$password
        } catch {}
    }

    return $false
}

# TIRBazar: load silently from the user's encrypted local store first.
if (-not $env:TIRBAZAR_PASSWORD) {
    $savedSql = Load-SecureCredential $sqlCredPath
    if ($savedSql) {
        $net = $savedSql.GetNetworkCredential()
        $env:TIRBAZAR_USER = $net.UserName
        $env:TIRBAZAR_PASSWORD = $net.Password
    } else {
        [void](Try-Load-TirBazarFromConfig)
    }
}

if (-not $env:TIRBAZAR_PASSWORD) {
    Write-Host ""
    Write-Host "Nepodarilo se automaticky nacist SQL pristup z TIRBazaru."
    Write-Host "Spust nejdriv TIRBazar a nech ho otevreny, potom spust tento soubor znovu."
    Read-Host "Stiskni Enter pro zavreni"
    exit 1
}

# UNIQA: first run only. Export-Clixml encrypts the password with Windows DPAPI,
# so it can be decrypted only by the same Windows user on this PC.
if (-not $env:UNIQA_USER -or -not $env:UNIQA_PASSWORD) {
    $savedUniqa = Load-SecureCredential $uniqaCredPath
    if ($savedUniqa) {
        $net = $savedUniqa.GetNetworkCredential()
        $env:UNIQA_USER = $net.UserName
        $env:UNIQA_PASSWORD = $net.Password
    } else {
        Write-Host ""
        Write-Host "Prvni nastaveni UNIQA - udaje ulozim sifrovane do tohoto Windows uctu."
        Write-Host "Pri dalsich spustenich se uz na nic ptat nebudu."
        $uniqaUser = Read-Host "UNIQA uzivatelske jmeno"
        $uniqaSecure = Read-Host "UNIQA heslo" -AsSecureString
        $uniqaCred = New-Object System.Management.Automation.PSCredential($uniqaUser, $uniqaSecure)
        $uniqaCred | Export-Clixml -Path $uniqaCredPath
        $net = $uniqaCred.GetNetworkCredential()
        $env:UNIQA_USER = $net.UserName
        $env:UNIQA_PASSWORD = $net.Password
    }
}

& (Join-Path $PSScriptRoot "START_WEB_WINDOWS.ps1")
exit $LASTEXITCODE
