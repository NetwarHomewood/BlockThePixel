# BlockThePixel

[English](README.md) | **Deutsch**

Hält defekte Bereiche im Grafikspeicher (VRAM) einer NVIDIA-Grafikkarte fest, damit Spiele sie nicht mehr bekommen. Für Windows.

## Das Problem

GeForce-Karten haben weder Fehlerkorrektur (ECC) noch eine Möglichkeit, defekte Speicherbereiche auszusortieren. Ist eine Stelle im Grafikspeicher kaputt, landen dort früher oder später Modelle oder Texturen eines Spiels. Typische Folgen sind schwarze Zacken-Polygone, die aus Objekten herausschießen („Vertex-Explosionen“), Pixelblöcke und bunte Leuchtpunkte, unabhängig vom Spiel und von der Grafikschnittstelle (DirectX, OpenGL, Vulkan). Bei einem festen Defekt hilft Untertakten nicht.

## Die Idee

BlockThePixel belegt beim Start fast den gesamten freien Grafikspeicher in Stücken von 8 MiB, schreibt Prüfmuster hinein und liest sie zurück. Fehlerfreie Stücke gibt es sofort wieder frei, die defekten hält es mit höchster Speicherpriorität fest. Solange das Programm läuft, vergibt der Treiber diese Stellen an kein anderes Programm. Ein Wächter prüft die festgehaltenen Stücke regelmäßig nach: Zeigen sie keine Fehler mehr, hat der Treiber den Speicher vermutlich verschoben, und BlockThePixel warnt.

Jeder Suchlauf und jede Wächter-Prüfung landet in einer SQLite-Datenbank. Aus den früheren Läufen bildet BlockThePixel einen Normalwert und meldet, wenn ein neuer Lauf davon abweicht. Ein Symbol in der Systemleiste zeigt den Zustand jederzeit an.

Die Grafikkarte wird über Vulkan angesprochen (die `vulkan-1.dll` bringt der NVIDIA-Treiber mit). Geprüft wird nur mit Kopierbefehlen, ohne Shader.

## Ergebnis auf dem Testsystem

Hardware und Software siehe [Testsystem](#testsystem). Defekt gefunden mit [memtest_vulkan](https://github.com/GpuZelenograd/memtest_vulkan) v0.5.0.

| Test | Fehlermeldungen |
| --- | --- |
| memtest_vulkan, normaler Takt (7 min) | 11.930 |
| memtest_vulkan, Speicher −500 MHz / Kern −100 MHz (7 min) | 11.050 |
| memtest_vulkan, BlockThePixel aktiv (5 min) | 0 |

BlockThePixel fand bei jedem Start 16.384 Fehler pro Durchgang in 5 Stücken (40 MiB) und hielt sie fest. Die Suche dauerte 20 bis 30 Sekunden. In Spielen traten mit aktivem BlockThePixel bei mittleren und hohen Grafikeinstellungen keine Grafikfehler mehr auf.

## Testsystem

| Komponente | Details |
| --- | --- |
| Betriebssystem | Windows 11 Pro 26H2, Build 26300.9711 |
| Grafikkarte | NVIDIA GeForce RTX 2070 SUPER, 8 GB, Boardpartner MSI (PCI-Subsystem 1462:3860), VBIOS 90.04.95.00.58 |
| Grafiktreiber | NVIDIA 616.92, Vulkan-Loader 1.4.341.0 |
| Anbindung | PCIe 3.0 x16 |
| Prozessor | Intel Core i5-12400F |
| Mainboard | ASRock B660M-HDV |
| Arbeitsspeicher | 16 GB, 3200 MT/s |
| Python | 3.11.9, numpy 2.3.5, cffi 2.0.0, pywin32 311, Pillow 12.0.0 |

Gemessener Verbrauch auf diesem System:

| Phase | Grafikspeicher | Arbeitsspeicher |
| --- | --- | --- |
| Suche (20–30 s) | 6.960 MiB kurzzeitig belegt | Reservierung steigt kurz auf rund 7,6 GB |
| Danach (Wächter) | 42 MiB, davon 40 MiB festgehaltene Stücke | 23 MB im Speicher, rund 760 MB reserviert |

Rechenzeit fällt nur bei der Suche und bei den Wächter-Prüfungen an (alle 5 Minuten werden 40 MiB kopiert und verglichen).

## Voraussetzungen

- Windows (getestet: Windows 11)
- NVIDIA-Grafikkarte mit aktuellem Treiber
- Python 3 (getestet: 3.11) mit numpy, cffi, pywin32 und Pillow: `py -m pip install -r requirements.txt`

Ohne pywin32 und Pillow läuft BlockThePixel ohne Symbol in der Systemleiste.

## Benutzung

Nur prüfen, nichts festhalten:

```powershell
py blockthepixel.py --nur-suchen
```

Festhalten mit Symbol in der Systemleiste:

```powershell
py blockthepixel.py
```

Festhalten ohne Symbol, nur Konsole (Beenden mit Strg+C):

```powershell
py blockthepixel.py --ohne-symbol
```

Autostart bei jeder Anmeldung einrichten (startet sofort, ohne Konsolenfenster, Warnungen als Fenster):

```powershell
powershell -ExecutionPolicy Bypass -File autostart_einrichten.ps1
```

Autostart entfernen:

```powershell
powershell -ExecutionPolicy Bypass -File autostart_entfernen.ps1
```

BlockThePixel sollte vor Spielen, Browser und Steam laufen. Was ein anderes Programm bereits belegt hat, kann es nicht mehr festhalten. Läuft BlockThePixel schon, beendet sich eine zweite Instanz sofort.

## Optionen

Jede Option hat einen deutschen und einen englischen Namen, beide funktionieren.

| Option | Englischer Name | Standard | Bedeutung |
| --- | --- | --- | --- |
| `--chunk-mib` | | 8 | Stückgröße in MiB |
| `--durchgaenge` | `--passes` | 4 | Prüfdurchgänge bei der Suche |
| `--reserve-mib` | | 256 | Grafikspeicher, der bei der Suche frei bleibt |
| `--abbruch-prozent` | `--abort-percent` | 10 | Abbruch, wenn mehr als so viel Prozent des Grafikspeichers defekt sind |
| `--intervall` | `--interval` | 300 | Sekunden zwischen zwei Wächter-Prüfungen |
| `--warn-nach` | `--warn-after` | 2 | Warnung nach so vielen fehlerfreien Wächter-Prüfungen in Folge |
| `--verlauf` | `--history` | 10 | so viele frühere Suchläufe bilden den Normalwert |
| `--empfindlichkeit streng\|normal\|tolerant` | `--sensitivity strict\|normal\|tolerant` | gespeicherte Wahl, sonst normal | Schwellen der Meldungen, siehe [Empfindlichkeit](#empfindlichkeit) |
| `--nur-suchen` | `--search-only` | – | nur suchen und berichten (ohne Symbol) |
| `--meldungen` | `--dialogs` | – | Warnungen zusätzlich als Fenster anzeigen |
| `--ohne-symbol` | `--no-icon` | – | kein Symbol in der Systemleiste |
| `--sprache de\|en` | `--language` | gespeicherte Wahl, sonst Windows-Sprache | Sprache der Oberfläche |

## Sprache

Beim ersten Start wählt BlockThePixel Deutsch, wenn Windows auf Deutsch läuft, sonst Englisch. Der Menüpunkt „Sprache / Language“ am Symbol schaltet sofort um, ohne Neustart, und die Wahl wird gespeichert. In der Befehlszeile überschreibt `--sprache de` oder `--sprache en` sie für diesen Lauf.

## Symbol in der Systemleiste

| Farbe | Bedeutung |
| --- | --- |
| grün | Defekt gesperrt, Werte im Normalbereich |
| gelb | Suche läuft, oder eine Abweichung vom Normalwert ist aufgefallen |
| rot | nicht gesperrt (kein Defekt gefunden, Speicher verschoben, Fehler) |
| grau | startet |

Beim Darüberfahren zeigt das Symbol die gesperrte Menge und die letzte Prüfung. Ein Doppelklick öffnet den Status mit Normalwert, Veränderung seit der ersten Messung und Verlauf. Das Rechtsklick-Menü bietet „Jetzt prüfen“, „Neu suchen“, „Protokoll öffnen“, „Sprache / Language“, „Empfindlichkeit / Sensitivity“ und „Beenden“.

Windows 11 blendet neue Symbole zunächst aus. BlockThePixel schaltet sein Symbol beim ersten Start einmalig sichtbar. Wer es danach selbst ausblendet, behält diese Einstellung.

## Meldungen

Abweichungen erscheinen als Hinweisblase am Symbol. Grundlage ist der Normalwert, der Median der letzten zehn erfolgreichen Suchläufe. Ein Hinweis erscheint, wenn

- die Suche mehr Fehler findet, als der Normalwert zulässt, oder mehr als ein zusätzliches defektes Stück,
- die Suche deutlich weniger Fehler findet als üblich (ein Teil der defekten Stelle ist vermutlich von einem anderen Programm belegt),
- drei Starts in Folge jeweils mehr Fehler zeigen als der vorige (stetiges Wachstum),
- der gesperrte Speicher einen Anteil des Grafikspeichers der Karte übersteigt,
- der Wächter mehr Fehler findet als die Suche.

## Empfindlichkeit

Die Schwellen für diese Hinweise hängen von der gewählten Empfindlichkeit ab. Sie lässt sich im Menü „Empfindlichkeit / Sensitivity“ am Symbol umstellen; die Änderung wirkt sofort, die aktuellen Werte werden neu bewertet.

| Empfindlichkeit | mehr Fehler als Normalwert | weniger Fehler als Normalwert | stetiges Wachstum je Start | Warnung, wenn gesperrter Speicher übersteigt |
| --- | --- | --- | --- | --- |
| Streng | +2 % | unter 95 % | +1 % | 1 % des Grafikspeichers |
| Normal (Standard) | +5 % | unter 90 % | +2 % | 3 % des Grafikspeichers |
| Tolerant | +10 % | unter 80 % | +5 % | 6 % des Grafikspeichers |

Die Abweichungsschwellen beziehen sich auf den Normalwert der eigenen Karte, die Warnschwelle auf ihre Speichergröße. Dieselben Einstellungen passen daher für jede Karte. Auf dem Testsystem schwankte die Fehlerzahl nur zwischen 16.383 und 16.384 pro Durchgang; „Normal“ lässt also reichlich Spielraum. Bei Karten, deren Defekt temperaturabhängig ist, kann die Zahl stärker schwanken; dort vermeidet „Tolerant“ Fehlalarme.

Unabhängig von der Empfindlichkeit bricht BlockThePixel ab und sperrt nichts, wenn mehr als 10 % des Grafikspeichers defekt sind (`--abbruch-prozent`). Das schützt vor Fehlmessungen.

Ist der Defekt nicht gesperrt, wird das Symbol rot. Mit `--meldungen` (im Autostart gesetzt) erscheint dann zusätzlich ein Fenster, das man wegklicken muss. Das passiert, wenn die Suche keinen Defekt findet, der Wächter in den festgehaltenen Stücken keine Fehler mehr findet, nicht genug Grafikspeicher für die Suche frei ist oder die Grafikkarte nicht ansprechbar ist.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `blockthepixel.py` | das Programm |
| `requirements.txt` | benötigte Python-Pakete |
| `blockthepixel.log` | Protokoll (rotiert bei 1 MB, 3 ältere Dateien) |
| `blockthepixel.db` | Verlauf (SQLite): Tabellen `suchlauf`, `stueck`, `waechter` mit Zeit, Fehlern, Stücken, Temperatur und Treiberversion |
| `autostart_einrichten.ps1` / `autostart_entfernen.ps1` | Aufgabe „BlockThePixel“ in der Windows-Aufgabenplanung einrichten / entfernen |

In der Registry schreibt BlockThePixel nur unter `HKCU\Software\BlockThePixel` (Sprache, Empfindlichkeit und ein Vermerk, dass das Symbol einmal sichtbar geschaltet wurde) sowie einmalig den Wert `IsPromoted` seines eigenen Symbol-Eintrags unter `HKCU\Control Panel\NotifyIconSettings`.

## Exit-Codes

| Code | Bedeutung |
| --- | --- |
| 0 | beendet (Strg+C, Menü „Beenden“ oder `--nur-suchen`) |
| 1 | unerwarteter Fehler |
| 2 | Vulkan-Fehler |
| 3 | zu wenig freier Grafikspeicher für die Suche |
| 4 | kein Defekt gefunden, nichts festgehalten |
| 5 | zu viele defekte Stücke (mehr als `--abbruch-prozent` des Grafikspeichers) |
| 6 | läuft bereits |

## Grenzen

- Keine Reparatur. Die Karte bleibt defekt, BlockThePixel umgeht den Defekt nur.
- Windows kann Grafikspeicher verschieben oder auslagern. Der Wächter erkennt das und warnt, verhindern kann er es nicht. In den Tests (memtest_vulkan unter Volllast, Spiele auf hohen Einstellungen) ist es nicht vorgekommen.
- Geprüft wird über Kopierbefehle. Das findet feste Defekte, ersetzt aber keinen Belastungstest wie memtest_vulkan bei takt- oder temperaturabhängigen Fehlern.
- Getestet auf genau einer Karte.

## Verwandtes Projekt

Der Ansatz, defekten Grafikspeicher durch Festhalten zu sperren, entstand bei der Fehlersuche an der Testkarte. Bei der anschließenden Recherche fand sich [gpu-vram-quarantine](https://github.com/JoshBolding/gpu-vram-quarantine), das dasselbe Prinzip unter Linux mit CUDA umsetzt. Von dort übernommen wurden einzelne Entwurfsentscheidungen: Stücke von 8 MiB, Bestätigung über mehrere Durchgänge, ein Wächter für die festgehaltenen Stücke, „kein Fehler gefunden“ ausdrücklich nicht als Entwarnung zu werten, und das Schema der Exit-Codes 2 bis 5. Code wurde nicht übernommen. BlockThePixel ist eine eigenständige Umsetzung für Windows mit Vulkan.

## Entstehung

BlockThePixel wurde mit KI-Unterstützung entwickelt, mit [Claude Code](https://claude.com/claude-code) von Anthropic (Modell Claude Opus 5.5). Fehlerdiagnose, Programmcode, Messungen und diese Dokumentation entstanden im Dialog mit der KI. Fragestellung, Richtungsentscheidungen und Spieltests kamen vom Menschen.

## Lizenz

[MIT](LICENSE) © 2026 The BlockThePixel authors
