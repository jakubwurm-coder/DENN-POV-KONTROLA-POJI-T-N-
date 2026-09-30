$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:LOCALAPPDATA "DenniPOV"
$scriptPath = Join-Path $installDir "denni-pov-tray.ps1"
$url = "https://denni-pov-kontrola.onrender.com/static/denni-pov-tray.ps1"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Invoke-WebRequest -Uri $url -OutFile $scriptPath -UseBasicParsing

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "DENNI POV.lnk"
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"'
$shortcut.WorkingDirectory = $installDir
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
$shortcut.Save()

Start-Process -FilePath $shortcut.TargetPath -ArgumentList $shortcut.Arguments -WindowStyle Hidden
Write-Host ""
Write-Host "DENNI POV byl nainstalovan." -ForegroundColor Green
Write-Host "Ikona se zobrazi v systemove liste vedle hodin."
Write-Host "Spousti se automaticky po prihlaseni do Windows."