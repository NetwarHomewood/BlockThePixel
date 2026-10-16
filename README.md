# BlockThePixel

**English** | [Deutsch](README.de.md)

Holds on to defective regions of an NVIDIA graphics card's video memory (VRAM) so that games can no longer get them. For Windows.

The interface, messages and log are available in English and German (see [Language](#language)).

## The problem

GeForce cards have neither error correction (ECC) nor any way to retire defective memory regions. If a spot in video memory is broken, sooner or later a game's models or textures end up there. Typical results are black jagged polygons shooting out of objects ("vertex explosions"), blocks of corrupted pixels and colourful glowing dots, regardless of the game and of the graphics API (DirectX, OpenGL, Vulkan). Underclocking does not help with a permanent defect.

## The idea

At startup BlockThePixel allocates almost all free video memory in 8 MiB chunks, writes test patterns into them and reads them back. Chunks without errors are released immediately; defective ones are kept allocated with the highest memory priority. As long as the program runs, the driver cannot hand these regions to any other program. A watchdog re-tests the held chunks regularly: if they suddenly show no errors, the driver has probably moved the memory, and BlockThePixel warns.

Every search and every watchdog check is stored in an SQLite database. From previous runs BlockThePixel derives a baseline and reports when a new run deviates from it. An icon in the notification area shows the current state at all times.

The graphics card is accessed through Vulkan (`vulkan-1.dll` ships with the NVIDIA driver). Testing uses copy commands only, no shaders.

## Results on the test system

Hardware and software: see [Test system](#test-system). Defect found with [memtest_vulkan](https://github.com/GpuZelenograd/memtest_vulkan) v0.5.0.

| Test | Error reports |
| --- | --- |
| memtest_vulkan, stock clocks (7 min) | 11,930 |
| memtest_vulkan, memory −500 MHz / core −100 MHz (7 min) | 11,050 |
| memtest_vulkan, BlockThePixel active (5 min) | 0 |

On every start BlockThePixel found 16,384 errors per pass in 5 chunks (40 MiB) and held them. The search took 20 to 30 seconds. With BlockThePixel active, games showed no more graphical errors at medium and high settings.

## Test system

| Component | Details |
| --- | --- |
| Operating system | Windows 11 Pro 26H2, build 26300.9711 |
| Graphics card | NVIDIA GeForce RTX 2070 SUPER, 8 GB, board partner MSI (PCI subsystem 1462:3860), VBIOS 90.04.95.00.58 |
| Graphics driver | NVIDIA 616.92, Vulkan loader 1.4.341.0 |
| Link | PCIe 3.0 x16 |
| CPU | Intel Core i5-12400F |
| Mainboard | ASRock B660M-HDV |
| RAM | 16 GB, 3200 MT/s |
| Python | 3.11.9, numpy 2.3.5, cffi 2.0.0, pywin32 311, Pillow 12.0.0 |

Measured resource usage on this system:

| Phase | Video memory | System memory |
| --- | --- | --- |
| Search (20–30 s) | 6,960 MiB briefly allocated | commit briefly rises to about 7.6 GB |
| Afterwards (watchdog) | 42 MiB, of which 40 MiB are held chunks | 23 MB resident, about 760 MB committed |

CPU time is only used during the search and the watchdog checks (every 5 minutes 40 MiB are copied and compared).

## Requirements

- Windows (tested: Windows 11)
- NVIDIA graphics card with a current driver
- Python 3 (tested: 3.11) with numpy, cffi, pywin32 and Pillow: `py -m pip install -r requirements.txt`

Without pywin32 and Pillow, BlockThePixel runs without the notification area icon.

## Usage

Search only, hold nothing:

```powershell
py blockthepixel.py --search-only
```

Hold with notification area icon:

```powershell
py blockthepixel.py
```

Hold without icon, console only (stop with Ctrl+C):

```powershell
py blockthepixel.py --no-icon
```

Set up autostart at every logon (starts immediately, no console window, warnings as dialog boxes):

```powershell
powershell -ExecutionPolicy Bypass -File autostart_einrichten.ps1
```

Remove autostart:

```powershell
powershell -ExecutionPolicy Bypass -File autostart_entfernen.ps1
```

BlockThePixel should start before games, browsers and Steam. It cannot hold memory that another program has already taken. If BlockThePixel is already running, a second instance exits immediately.

## Options

Every option has an English and a German name; both work.

| Option | German name | Default | Meaning |
| --- | --- | --- | --- |
| `--chunk-mib` | | 8 | chunk size in MiB |
| `--passes` | `--durchgaenge` | 4 | test passes during the search |
| `--reserve-mib` | | 256 | video memory left free during the search |
| `--abort-percent` | `--abbruch-prozent` | 10 | give up if more than this percentage of video memory is defective |
| `--interval` | `--intervall` | 300 | seconds between two watchdog checks |
| `--warn-after` | `--warn-nach` | 2 | warn after this many error-free watchdog checks in a row |
| `--history` | `--verlauf` | 10 | number of previous searches that form the baseline |
| `--sensitivity strict\|normal\|tolerant` | `--empfindlichkeit streng\|normal\|tolerant` | saved choice, otherwise normal | notification thresholds, see [Sensitivity](#sensitivity) |
| `--search-only` | `--nur-suchen` | – | search and report only (no icon) |
| `--dialogs` | `--meldungen` | – | additionally show warnings as dialog boxes |
| `--no-icon` | `--ohne-symbol` | – | no notification area icon |
| `--language de\|en` | `--sprache` | saved choice, otherwise Windows language | interface language |

## Language

On first start BlockThePixel uses German if Windows runs in German, otherwise English. The menu item "Sprache / Language" at the icon switches immediately, without a restart; the choice is saved. On the command line, `--language en` or `--language de` overrides it for that run.

## Notification area icon

| Colour | Meaning |
| --- | --- |
| green | defect held, values within the normal range |
| yellow | search running, or a deviation from the baseline was noticed |
| red | not held (no defect found, memory moved, error) |
| grey | starting |

Hovering shows the amount of held memory and the last check. A double click opens the status with baseline, change since the first measurement and history. The right-click menu offers "Check now", "Search again", "Open log", "Sprache / Language", "Empfindlichkeit / Sensitivity" and "Exit".

Windows 11 hides new icons at first. BlockThePixel makes its icon visible once on first start. If you hide it afterwards, that choice is kept.

## Notifications

Deviations appear as a balloon at the icon. The reference is the baseline, the median of the last ten successful searches. A notice appears when

- the search finds more errors than the baseline allows, or more than one additional defective chunk,
- the search finds noticeably fewer errors than usual (part of the defective region is probably held by another program),
- three starts in a row each show more errors than the one before (steady growth),
- the blocked memory exceeds a share of the card's video memory,
- the watchdog finds more errors than the search.

## Sensitivity

The thresholds for these notices depend on the selected sensitivity. It can be changed in the menu "Empfindlichkeit / Sensitivity" at the icon; the change takes effect immediately and current values are re-evaluated.

| Sensitivity | more errors than baseline | fewer errors than baseline | steady growth per start | warning when blocked memory exceeds |
| --- | --- | --- | --- | --- |
| Strict | +2 % | below 95 % | +1 % | 1 % of video memory |
| Normal (default) | +5 % | below 90 % | +2 % | 3 % of video memory |
| Tolerant | +10 % | below 80 % | +5 % | 6 % of video memory |

The deviation thresholds are relative to the card's own baseline, and the warning threshold is relative to the card's memory size, so the same settings work for any card. On the test system the error count varied only between 16,383 and 16,384 per pass; "Normal" therefore leaves plenty of headroom. Cards whose defect depends on temperature may vary more; "Tolerant" avoids false alarms there.

Independent of the sensitivity, BlockThePixel gives up and blocks nothing if more than 10 % of video memory is defective (`--abort-percent`). This protects against faulty measurements.

If the defect is not held, the icon turns red. With `--dialogs` (set by the autostart) a dialog box that has to be dismissed appears as well. This happens when the search finds no defect, the watchdog no longer finds errors in the held chunks, there is not enough free video memory for the search, or the graphics card cannot be accessed.

## Files

| File | Content |
| --- | --- |
| `blockthepixel.py` | the program |
| `requirements.txt` | required Python packages |
| `blockthepixel.log` | log (rotates at 1 MB, 3 older files kept) |
| `blockthepixel.db` | history (SQLite): tables `suchlauf` (searches), `stueck` (chunks), `waechter` (watchdog checks) with time, errors, chunks, temperature and driver version |
| `autostart_einrichten.ps1` / `autostart_entfernen.ps1` | set up / remove the task "BlockThePixel" in Windows Task Scheduler |

In the registry, BlockThePixel only writes to `HKCU\Software\BlockThePixel` (language, sensitivity and a flag that the icon was made visible once) and, once, the value `IsPromoted` of its own icon entry under `HKCU\Control Panel\NotifyIconSettings`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | finished (Ctrl+C, menu "Exit" or `--search-only`) |
| 1 | unexpected error |
| 2 | Vulkan error |
| 3 | not enough free video memory for the search |
| 4 | no defect found, nothing held |
| 5 | too many defective chunks (more than `--abort-percent` of video memory) |
| 6 | already running |

## Limitations

- Not a repair. The card stays defective; BlockThePixel only works around the defect.
- Windows can move or evict video memory. The watchdog detects this and warns, but cannot prevent it. It did not happen in the tests (memtest_vulkan at full load, games at high settings).
- Testing uses copy commands. This finds permanent defects but does not replace a stress test like memtest_vulkan for clock- or temperature-dependent errors.
- Tested on exactly one card.

## Related project

The approach of blocking defective video memory by holding it came up while troubleshooting the test card. Subsequent research turned up [gpu-vram-quarantine](https://github.com/JoshBolding/gpu-vram-quarantine), which implements the same principle on Linux with CUDA. Some design decisions were adopted from it: 8 MiB chunks, confirmation over several passes, a watchdog for the held chunks, explicitly not treating "no error found" as an all-clear, and the scheme of exit codes 2 to 5. No code was taken over. BlockThePixel is an independent implementation for Windows with Vulkan.

## How it was made

BlockThePixel was developed with AI assistance, using [Claude Code](https://claude.com/claude-code) by Anthropic (model Claude Opus 5.5). Diagnosis, program code, measurements and this documentation were created in dialogue with the AI. The questions, the direction and the game tests came from a human.

## License

[MIT](LICENSE) © 2026 [The BlockThePixel authors](https://github.com/NetwarHomewood/BlockThePixel)

Free to use, change and pass on, including commercially, as long as the copyright notice and the license text stay included.
