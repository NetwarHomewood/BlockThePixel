# Richtet BlockThePixel als Aufgabe bei der Anmeldung ein und startet es sofort.
# Aufruf: powershell -ExecutionPolicy Bypass -File autostart_einrichten.ps1 [-Intervall 300]
param([int]$Intervall = 300)
$ErrorActionPreference = 'Stop'

$skript = Join-Path $PSScriptRoot 'blockthepixel.py'
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $python = & py -3 -c "import sys; print(sys.executable)" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = & python -c "import sys; print(sys.executable)" }
if (-not $python) { throw 'Python 3 nicht gefunden.' }
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe nicht gefunden neben $python" }
& $python -c "import numpy, cffi"
if ($LASTEXITCODE -ne 0) { throw 'numpy oder cffi fehlt: py -m pip install numpy cffi' }

$benutzer = "$env:USERDOMAIN\$env:USERNAME"
$aktion = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$skript`" --meldungen --intervall $Intervall" -WorkingDirectory $PSScriptRoot
$ausloeser = New-ScheduledTaskTrigger -AtLogOn -User $benutzer
$konto = New-ScheduledTaskPrincipal -UserId $benutzer -LogonType Interactive -RunLevel Limited
$einstellungen = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -Priority 4
Register-ScheduledTask -TaskName 'BlockThePixel' -Description "Haelt defekte VRAM-Bereiche fest ($PSScriptRoot)" -Action $aktion -Trigger $ausloeser -Principal $konto -Settings $einstellungen -Force | Out-Null
Start-ScheduledTask -TaskName 'BlockThePixel'
"Aufgabe 'BlockThePixel' eingerichtet und gestartet."
"Programm: $pythonw"
"Protokoll: $(Join-Path $PSScriptRoot 'blockthepixel.log')"
