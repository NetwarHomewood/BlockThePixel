# Beendet BlockThePixel und entfernt die Aufgabe aus der Aufgabenplanung.
# Aufruf: powershell -ExecutionPolicy Bypass -File autostart_entfernen.ps1
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName 'BlockThePixel' -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName 'BlockThePixel'
    Unregister-ScheduledTask -TaskName 'BlockThePixel' -Confirm:$false
    "Aufgabe 'BlockThePixel' beendet und entfernt."
} else {
    "Keine Aufgabe 'BlockThePixel' vorhanden."
}
