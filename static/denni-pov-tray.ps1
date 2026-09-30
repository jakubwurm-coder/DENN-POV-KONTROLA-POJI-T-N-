param(
    [string]$ApiUrl = "https://denni-pov-kontrola.onrender.com/api/windows-status",
    [string]$WebUrl = "https://denni-pov-kontrola.onrender.com"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = "SilentlyContinue"
$stateDir = Join-Path $env:LOCALAPPDATA "DenniPOV"
$stateFile = Join-Path $stateDir "last-status.json"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Text = "DENNÍ POV"
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$statusItem = $menu.Items.Add("Stav: načítám...")
$statusItem.Enabled = $false
$countsItem = $menu.Items.Add("Aktivní: - | V pořádku: - | Ke kontrole: -")
$countsItem.Enabled = $false
$menu.Items.Add("-") | Out-Null
$openItem = $menu.Items.Add("Otevřít DENNÍ POV")
$checkItem = $menu.Items.Add("Zkontrolovat nyní")
$menu.Items.Add("-") | Out-Null
$exitItem = $menu.Items.Add("Ukončit")
$notify.ContextMenuStrip = $menu

function Open-DenniPov { Start-Process $WebUrl }

function Get-PreviousSignature {
    if (-not (Test-Path $stateFile)) { return "" }
    try { return (Get-Content $stateFile -Raw | ConvertFrom-Json).signature } catch { return "" }
}

function Save-Signature([string]$signature) {
    @{ signature = $signature } | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
}

function Show-Balloon([string]$title, [string]$text, [System.Windows.Forms.ToolTipIcon]$icon) {
    $notify.BalloonTipTitle = $title
    $notify.BalloonTipText = $text
    $notify.BalloonTipIcon = $icon
    $notify.ShowBalloonTip(10000)
}

function Update-DenniPov {
    try {
        $data = Invoke-RestMethod -Uri $ApiUrl -Method Get -TimeoutSec 20
        $status = [string]$data.status
        $requires = [int]$data.requires_check
        $active = [int]$data.active
        $ok = [int]$data.ok

        switch ($status) {
            "ok" { $notify.Icon = [System.Drawing.SystemIcons]::Information; $statusItem.Text = "Stav: V pořádku" }
            "running" { $notify.Icon = [System.Drawing.SystemIcons]::Information; $statusItem.Text = "Stav: Probíhá kontrola" }
            "requires_check" { $notify.Icon = [System.Drawing.SystemIcons]::Warning; $statusItem.Text = "Stav: Vyžaduje kontrolu" }
            default { $notify.Icon = [System.Drawing.SystemIcons]::Error; $statusItem.Text = "Stav: Chyba" }
        }

        $countsItem.Text = "Aktivní: $active | V pořádku: $ok | Ke kontrole: $requires"
        $notify.Text = ("DENNÍ POV - " + $statusItem.Text.Replace("Stav: ",""))

        $issueKeys = @()
        foreach ($issue in @($data.issues)) { $issueKeys += (($issue.vin + "|" + $issue.spz + "|" + $issue.status).ToUpper()) }
        $signature = ($status + "|" + $requires + "|" + (($issueKeys | Sort-Object) -join ";"))
        $previous = Get-PreviousSignature

        if ($previous -and $signature -ne $previous) {
            if ($status -eq "requires_check" -and $requires -gt 0) {
                $lines = @()
                foreach ($issue in @($data.issues) | Select-Object -First 3) {
                    $label = if ($issue.spz) { $issue.spz } elseif ($issue.vin) { $issue.vin } else { "Vozidlo" }
                    $lines += "$label - $($issue.status)"
                }
                $extra = if ($requires -gt 3) { [Environment]::NewLine + "+ další $($requires - 3)" } else { "" }
                Show-Balloon "DENNÍ POV - Vyžaduje kontrolu" (($lines -join [Environment]::NewLine) + $extra) ([System.Windows.Forms.ToolTipIcon]::Warning)
            } elseif ($status -eq "error") {
                Show-Balloon "DENNÍ POV - Chyba" ([string]$data.error) ([System.Windows.Forms.ToolTipIcon]::Error)
            }
        }
        Save-Signature $signature
    } catch {
        $notify.Icon = [System.Drawing.SystemIcons]::Error
        $statusItem.Text = "Stav: Nelze načíst"
        $countsItem.Text = "Server DENNÍ POV není dostupný"
        $notify.Text = "DENNÍ POV - nelze načíst"
    }
}

$openItem.add_Click({ Open-DenniPov })
$notify.add_DoubleClick({ Open-DenniPov })
$checkItem.add_Click({ Update-DenniPov })
$exitItem.add_Click({ $notify.Visible = $false; $timer.Stop(); [System.Windows.Forms.Application]::Exit() })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 300000
$timer.add_Tick({ Update-DenniPov })
$timer.Start()
Update-DenniPov
[System.Windows.Forms.Application]::Run()