param(
    [string]$ApiUrl = "https://denni-pov-kontrola.onrender.com/api/windows-status",
    [string]$WebUrl = "https://denni-pov-kontrola.onrender.com"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = "SilentlyContinue"

# Windows PowerShell 5.1 muze nacitat UTF-8 .ps1 bez BOM jako ANSI.
# Vsechny ceske texty proto skladame z UTF-8 Base64, aby se v tray menu nezobrazovalo rozsypane kodovani.
function U([string]$b64) {
    return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
}
$txtApp = U "REVOTsONIFBPVg=="
$txtLoading = U "U3RhdjogbmHEjcOtdMOhbS4uLg=="
$txtCountsEmpty = U "QWt0aXZuw606IC0gfCBWIHBvxZnDoWRrdTogLSB8IEtlIGtvbnRyb2xlOiAt"
$txtOpen = U "T3RldsWZw610IERFTk7DjSBQT1Y="
$txtCheckNow = U "WmtvbnRyb2xvdmF0IG55bsOt"
$txtExit = U "VWtvbsSNaXQ="
$txtOk = U "U3RhdjogViBwb8WZw6Fka3U="
$txtRunning = U "U3RhdjogUHJvYsOtaMOhIGtvbnRyb2xh"
$txtRequires = U "U3RhdjogVnnFvmFkdWplIGtvbnRyb2x1"
$txtError = U "U3RhdjogQ2h5YmE="
$txtCountsFormat = U "QWt0aXZuw606IHswfSB8IFYgcG/FmcOhZGthOiB7MX0gfCBLZSBrb250cm9sZTogezJ9"
$txtVehicle = U "Vm96aWRsbw=="
$txtMoreFormat = U "KyBkYWzFocOtIHswfQ=="
$txtBalloonRequires = U "REVOTsONIFBPViAtIFZ5xb5hZHVqZSBrb250cm9sdQ=="
$txtBalloonError = U "REVOTsONIFBPViAtIENoeWJh"
$txtCannotLoad = U "U3RhdjogTmVsemUgbmHEjcOtc3Q="
$txtServerUnavailable = U "U2VydmVyIERFTk7DjSBQT1YgbmVuw60gZG9zdHVwbsO9"
$txtCannotLoadTitle = U "REVOTsONIFBPViAtIG5lbHplIG5hxI3DrXN0"
$stateDir = Join-Path $env:LOCALAPPDATA "DenniPOV"
$stateFile = Join-Path $stateDir "last-status.json"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Text = $txtApp
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$statusItem = $menu.Items.Add($txtLoading)
$statusItem.Enabled = $false
$countsItem = $menu.Items.Add($txtCountsEmpty)
$countsItem.Enabled = $false
$menu.Items.Add("-") | Out-Null
$openItem = $menu.Items.Add($txtOpen)
$checkItem = $menu.Items.Add($txtCheckNow)
$menu.Items.Add("-") | Out-Null
$exitItem = $menu.Items.Add($txtExit)
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
            "ok" { $notify.Icon = [System.Drawing.SystemIcons]::Information; $statusItem.Text = $txtOk }
            "running" { $notify.Icon = [System.Drawing.SystemIcons]::Information; $statusItem.Text = $txtRunning }
            "requires_check" { $notify.Icon = [System.Drawing.SystemIcons]::Warning; $statusItem.Text = $txtRequires }
            default { $notify.Icon = [System.Drawing.SystemIcons]::Error; $statusItem.Text = $txtError }
        }

        $countsItem.Text = [string]::Format($txtCountsFormat, $active, $ok, $requires)
        $notify.Text = ($txtApp + " - " + $statusItem.Text.Replace("Stav: ",""))

        $issueKeys = @()
        foreach ($issue in @($data.issues)) { $issueKeys += (($issue.vin + "|" + $issue.spz + "|" + $issue.status).ToUpper()) }
        $signature = ($status + "|" + $requires + "|" + (($issueKeys | Sort-Object) -join ";"))
        $previous = Get-PreviousSignature

        if ($previous -and $signature -ne $previous) {
            if ($status -eq "requires_check" -and $requires -gt 0) {
                $lines = @()
                foreach ($issue in @($data.issues) | Select-Object -First 3) {
                    $label = if ($issue.spz) { $issue.spz } elseif ($issue.vin) { $issue.vin } else { $txtVehicle }
                    $lines += "$label - $($issue.status)"
                }
                $extra = if ($requires -gt 3) { [Environment]::NewLine + [string]::Format($txtMoreFormat, ($requires - 3)) } else { "" }
                Show-Balloon $txtBalloonRequires (($lines -join [Environment]::NewLine) + $extra) ([System.Windows.Forms.ToolTipIcon]::Warning)
            } elseif ($status -eq "error") {
                Show-Balloon $txtBalloonError ([string]$data.error) ([System.Windows.Forms.ToolTipIcon]::Error)
            }
        }
        Save-Signature $signature
    } catch {
        $notify.Icon = [System.Drawing.SystemIcons]::Error
        $statusItem.Text = $txtCannotLoad
        $countsItem.Text = $txtServerUnavailable
        $notify.Text = $txtCannotLoadTitle
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