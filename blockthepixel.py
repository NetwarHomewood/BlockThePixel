"""BlockThePixel - hält defekte Grafikspeicher-Bereiche fest, damit kein Spiel sie bekommt.

Ablauf:
  1. Belegt fast den gesamten freien Grafikspeicher in Stücken (Standard 8 MiB).
  2. Schreibt Prüfmuster hinein, liest sie zurück, mehrere Durchgänge.
  3. Gibt fehlerfreie Stücke frei, hält die defekten mit höchster Priorität fest.
  4. Wächter: prüft die festgehaltenen Stücke regelmäßig nach. Zeigen sie keine
     Fehler mehr, hat der Treiber sie vermutlich verschoben -> Warnung.
  5. Verlauf: jeder Suchlauf und jede Wächter-Prüfung landet in einer SQLite-Datenbank.
     Abweichungen vom Normalwert (Median der früheren Läufe) werden gemeldet.
  6. Symbol in der Systemleiste: grün = gesperrt, gelb = Suche/Abweichung, rot = nicht gesperrt.

Grafikkarte wird über Vulkan angesprochen (vulkan-1.dll aus dem NVIDIA-Treiber),
nur Kopierbefehle, keine Shader. Abhängigkeiten: numpy, cffi, pywin32, Pillow. Nur Windows.

Ansatz verwandt mit github.com/JoshBolding/gpu-vram-quarantine (Linux/CUDA), kein Code übernommen.
Entwickelt mit KI-Unterstützung (Claude Code, Anthropic).

Projekt: https://github.com/NetwarHomewood/BlockThePixel – MIT-Lizenz, siehe LICENSE.
"""

import argparse
import ctypes
import gc
import json
import logging
import logging.handlers
import os
import queue
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import winreg
from ctypes import wintypes
from pathlib import Path

import numpy as np
from cffi import FFI

try:
    import pywintypes
    import win32api
    import win32con
    import win32gui
except ImportError:  # ohne pywin32 läuft BlockThePixel ohne Symbol in der Systemleiste
    win32gui = None

NAME = "BlockThePixel"
VERSION = "0.2"
PROJEKT_URL = "https://github.com/NetwarHomewood/BlockThePixel"
MIB = 1024 * 1024

# Exit-Codes
EXIT_OK = 0
EXIT_UNERWARTET = 1
EXIT_VULKAN = 2
EXIT_ZU_WENIG_SPEICHER = 3
EXIT_KEIN_DEFEKT = 4
EXIT_ZU_VIELE_DEFEKTE = 5
EXIT_LAEUFT_SCHON = 6

ffi = FFI()
ffi.cdef("""
typedef uint32_t VkFlags;
typedef uint32_t VkBool32;
typedef uint64_t VkDeviceSize;
typedef int32_t VkResult;
typedef void* VkInstance;
typedef void* VkPhysicalDevice;
typedef void* VkDevice;
typedef void* VkQueue;
typedef void* VkCommandBuffer;
typedef uint64_t VkDeviceMemory;
typedef uint64_t VkBuffer;
typedef uint64_t VkCommandPool;
typedef uint64_t VkFence;
typedef uint64_t VkSemaphore;

typedef struct { int32_t sType; const void* pNext; const char* pApplicationName; uint32_t applicationVersion;
                 const char* pEngineName; uint32_t engineVersion; uint32_t apiVersion; } VkApplicationInfo;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; const VkApplicationInfo* pApplicationInfo;
                 uint32_t enabledLayerCount; const char* const* ppEnabledLayerNames;
                 uint32_t enabledExtensionCount; const char* const* ppEnabledExtensionNames; } VkInstanceCreateInfo;
typedef struct { VkFlags propertyFlags; uint32_t heapIndex; } VkMemoryType;
typedef struct { VkDeviceSize size; VkFlags flags; } VkMemoryHeap;
typedef struct { uint32_t memoryTypeCount; VkMemoryType memoryTypes[32];
                 uint32_t memoryHeapCount; VkMemoryHeap memoryHeaps[16]; } VkPhysicalDeviceMemoryProperties;
typedef struct { int32_t sType; void* pNext; VkPhysicalDeviceMemoryProperties memoryProperties; } VkPhysicalDeviceMemoryProperties2;
typedef struct { int32_t sType; void* pNext; VkDeviceSize heapBudget[16]; VkDeviceSize heapUsage[16]; } VkPhysicalDeviceMemoryBudgetPropertiesEXT;
typedef struct { VkFlags queueFlags; uint32_t queueCount; uint32_t timestampValidBits;
                 uint32_t gw; uint32_t gh; uint32_t gd; } VkQueueFamilyProperties;
typedef struct { char extensionName[256]; uint32_t specVersion; } VkExtensionProperties;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; uint32_t queueFamilyIndex; uint32_t queueCount;
                 const float* pQueuePriorities; } VkDeviceQueueCreateInfo;
typedef struct { int32_t sType; void* pNext; VkBool32 memoryPriority; } VkPhysicalDeviceMemoryPriorityFeaturesEXT;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; uint32_t queueCreateInfoCount;
                 const VkDeviceQueueCreateInfo* pQueueCreateInfos; uint32_t enabledLayerCount;
                 const char* const* ppEnabledLayerNames; uint32_t enabledExtensionCount;
                 const char* const* ppEnabledExtensionNames; const void* pEnabledFeatures; } VkDeviceCreateInfo;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; VkDeviceSize size; VkFlags usage; int32_t sharingMode;
                 uint32_t queueFamilyIndexCount; const uint32_t* pQueueFamilyIndices; } VkBufferCreateInfo;
typedef struct { VkDeviceSize size; VkDeviceSize alignment; uint32_t memoryTypeBits; } VkMemoryRequirements;
typedef struct { int32_t sType; const void* pNext; VkDeviceSize allocationSize; uint32_t memoryTypeIndex; } VkMemoryAllocateInfo;
typedef struct { int32_t sType; const void* pNext; float priority; } VkMemoryPriorityAllocateInfoEXT;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; uint32_t queueFamilyIndex; } VkCommandPoolCreateInfo;
typedef struct { int32_t sType; const void* pNext; VkCommandPool commandPool; int32_t level;
                 uint32_t commandBufferCount; } VkCommandBufferAllocateInfo;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; const void* pInheritanceInfo; } VkCommandBufferBeginInfo;
typedef struct { VkDeviceSize srcOffset; VkDeviceSize dstOffset; VkDeviceSize size; } VkBufferCopy;
typedef struct { int32_t sType; const void* pNext; VkFlags srcAccessMask; VkFlags dstAccessMask; } VkMemoryBarrier;
typedef struct { int32_t sType; const void* pNext; uint32_t waitSemaphoreCount; const VkSemaphore* pWaitSemaphores;
                 const VkFlags* pWaitDstStageMask; uint32_t commandBufferCount; const VkCommandBuffer* pCommandBuffers;
                 uint32_t signalSemaphoreCount; const VkSemaphore* pSignalSemaphores; } VkSubmitInfo;
typedef struct { int32_t sType; const void* pNext; VkFlags flags; } VkFenceCreateInfo;

VkResult vkCreateInstance(const VkInstanceCreateInfo*, const void*, VkInstance*);
void vkDestroyInstance(VkInstance, const void*);
VkResult vkEnumeratePhysicalDevices(VkInstance, uint32_t*, VkPhysicalDevice*);
void vkGetPhysicalDeviceProperties(VkPhysicalDevice, void*);
void vkGetPhysicalDeviceMemoryProperties2(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties2*);
void vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice, uint32_t*, VkQueueFamilyProperties*);
VkResult vkEnumerateDeviceExtensionProperties(VkPhysicalDevice, const char*, uint32_t*, VkExtensionProperties*);
VkResult vkCreateDevice(VkPhysicalDevice, const VkDeviceCreateInfo*, const void*, VkDevice*);
void vkDestroyDevice(VkDevice, const void*);
void vkGetDeviceQueue(VkDevice, uint32_t, uint32_t, VkQueue*);
VkResult vkCreateBuffer(VkDevice, const VkBufferCreateInfo*, const void*, VkBuffer*);
void vkDestroyBuffer(VkDevice, VkBuffer, const void*);
void vkGetBufferMemoryRequirements(VkDevice, VkBuffer, VkMemoryRequirements*);
VkResult vkAllocateMemory(VkDevice, const VkMemoryAllocateInfo*, const void*, VkDeviceMemory*);
void vkFreeMemory(VkDevice, VkDeviceMemory, const void*);
VkResult vkBindBufferMemory(VkDevice, VkBuffer, VkDeviceMemory, VkDeviceSize);
VkResult vkMapMemory(VkDevice, VkDeviceMemory, VkDeviceSize, VkDeviceSize, VkFlags, void**);
void vkUnmapMemory(VkDevice, VkDeviceMemory);
VkResult vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo*, const void*, VkCommandPool*);
void vkDestroyCommandPool(VkDevice, VkCommandPool, const void*);
VkResult vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo*, VkCommandBuffer*);
VkResult vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo*);
VkResult vkEndCommandBuffer(VkCommandBuffer);
VkResult vkResetCommandBuffer(VkCommandBuffer, VkFlags);
void vkCmdCopyBuffer(VkCommandBuffer, VkBuffer, VkBuffer, uint32_t, const VkBufferCopy*);
void vkCmdPipelineBarrier(VkCommandBuffer, VkFlags, VkFlags, VkFlags, uint32_t, const VkMemoryBarrier*,
                          uint32_t, const void*, uint32_t, const void*);
VkResult vkCreateFence(VkDevice, const VkFenceCreateInfo*, const void*, VkFence*);
void vkDestroyFence(VkDevice, VkFence, const void*);
VkResult vkResetFences(VkDevice, uint32_t, const VkFence*);
VkResult vkWaitForFences(VkDevice, uint32_t, const VkFence*, VkBool32, uint64_t);
VkResult vkQueueSubmit(VkQueue, uint32_t, const VkSubmitInfo*, VkFence);
VkResult vkDeviceWaitIdle(VkDevice);
""")

# Vulkan-Konstanten
ST_APPLICATION_INFO = 0
ST_INSTANCE_CREATE_INFO = 1
ST_DEVICE_QUEUE_CREATE_INFO = 2
ST_DEVICE_CREATE_INFO = 3
ST_SUBMIT_INFO = 4
ST_MEMORY_ALLOCATE_INFO = 5
ST_FENCE_CREATE_INFO = 8
ST_BUFFER_CREATE_INFO = 12
ST_COMMAND_POOL_CREATE_INFO = 39
ST_COMMAND_BUFFER_ALLOCATE_INFO = 40
ST_COMMAND_BUFFER_BEGIN_INFO = 42
ST_MEMORY_BARRIER = 46
ST_PHYSICAL_DEVICE_MEMORY_PROPERTIES_2 = 1000059006
ST_PHYSICAL_DEVICE_MEMORY_BUDGET_PROPERTIES_EXT = 1000237000
ST_PHYSICAL_DEVICE_MEMORY_PRIORITY_FEATURES_EXT = 1000238000
ST_MEMORY_PRIORITY_ALLOCATE_INFO_EXT = 1000238001

API_VERSION_1_1 = (1 << 22) | (1 << 12)
NVIDIA_VENDOR_ID = 0x10DE

MEM_DEVICE_LOCAL = 0x1
MEM_HOST_VISIBLE = 0x2
MEM_HOST_COHERENT = 0x4
MEM_HOST_CACHED = 0x8
HEAP_DEVICE_LOCAL = 0x1

QUEUE_GRAPHICS = 0x1
QUEUE_COMPUTE = 0x2
QUEUE_TRANSFER = 0x4

BUF_TRANSFER_SRC = 0x1
BUF_TRANSFER_DST = 0x2

STAGE_TRANSFER = 0x1000
STAGE_HOST = 0x4000
ACCESS_TRANSFER_READ = 0x800
ACCESS_TRANSFER_WRITE = 0x1000
ACCESS_HOST_READ = 0x2000

VK_SUCCESS = 0
VK_ERROR_OUT_OF_HOST_MEMORY = -1
VK_ERROR_OUT_OF_DEVICE_MEMORY = -2
VK_WHOLE_SIZE = 0xFFFFFFFFFFFFFFFF
FENCE_TIMEOUT_NS = 20_000_000_000

log = logging.getLogger(NAME)

# ---------- Sprache ----------
EINSTELLUNG = {"sprache": "de", "empfindlichkeit": "normal"}

# Schwellen der Meldungen je Empfindlichkeit: Abweichung nach oben/unten vom Normalwert, stetiges Wachstum
# je Start, Warnung ab diesem Anteil gesperrten Grafikspeichers (Prozent der Kartengröße).
EMPFINDLICHKEIT = {
    "streng": {"mehr": 0.02, "weniger": 0.95, "wachstum": 0.01, "warn_prozent": 1.0},
    "normal": {"mehr": 0.05, "weniger": 0.90, "wachstum": 0.02, "warn_prozent": 3.0},
    "tolerant": {"mehr": 0.10, "weniger": 0.80, "wachstum": 0.05, "warn_prozent": 6.0},
}

TEXTE = {
    # Befehlszeile
    "cli_beschreibung": {"de": "Sucht defekte VRAM-Bereiche und hält sie fest.",
                         "en": "Finds defective VRAM regions and holds them."},
    "cli_chunk": {"de": "Stückgröße in MiB (Standard 8)", "en": "chunk size in MiB (default 8)"},
    "cli_durchgaenge": {"de": "Prüfdurchgänge bei der Suche (Standard 4)",
                        "en": "test passes during the search (default 4)"},
    "cli_reserve": {"de": "frei zu lassender Grafikspeicher in MiB (Standard 256)",
                    "en": "video memory in MiB left free during the search (default 256)"},
    "cli_abbruch": {"de": "Abbruch, wenn mehr als so viel Prozent des Grafikspeichers defekt sind (Standard 10)",
                    "en": "give up if more than this percentage of video memory is defective (default 10)"},
    "cli_intervall": {"de": "Sekunden zwischen Wächter-Prüfungen (Standard 300)",
                      "en": "seconds between watchdog checks (default 300)"},
    "cli_warn_nach": {"de": "Warnung nach so vielen fehlerfreien Wächter-Prüfungen in Folge (Standard 2)",
                      "en": "warn after this many error-free watchdog checks in a row (default 2)"},
    "cli_verlauf": {"de": "so viele frühere Suchläufe bilden den Normalwert (Standard 10)",
                    "en": "number of previous searches that form the baseline (default 10)"},
    "cli_empfindlichkeit": {"de": "Empfindlichkeit der Meldungen: streng, normal, tolerant (Standard: gespeicherte "
                                  "Wahl, sonst normal)",
                            "en": "notification sensitivity: strict, normal, tolerant (default: saved choice, "
                                  "otherwise normal)"},
    "cli_empf_ungueltig": {"de": "unbekannte Empfindlichkeit: {s} (streng, normal, tolerant)",
                           "en": "unknown sensitivity: {s} (strict, normal, tolerant)"},
    "cli_nur_suchen": {"de": "nur suchen und berichten, nichts festhalten",
                       "en": "search and report only, hold nothing"},
    "cli_meldungen": {"de": "Warnungen zusätzlich als Fenster anzeigen",
                      "en": "additionally show warnings as dialog boxes"},
    "cli_ohne_symbol": {"de": "kein Symbol in der Systemleiste (Konsolenbetrieb)",
                        "en": "no notification area icon (console mode)"},
    "cli_sprache": {"de": "Sprache der Oberfläche (Standard: gespeicherte Wahl, sonst Windows-Sprache)",
                    "en": "interface language (default: saved choice, otherwise Windows language)"},

    # Protokoll
    "log_start": {"de": "BlockThePixel {v} startet.", "en": "BlockThePixel {v} starting."},
    "log_laeuft_schon": {"de": "BlockThePixel läuft bereits – diese Instanz beendet sich.",
                         "en": "BlockThePixel is already running – this instance exits."},
    "log_pywin32": {"de": "pywin32 fehlt – laufe ohne Symbol in der Systemleiste.",
                    "en": "pywin32 missing – running without notification area icon."},
    "log_leiste_fehlt": {"de": "Systemleiste nicht verfügbar – laufe ohne Symbol.",
                         "en": "Notification area not available – running without icon."},
    "log_ende": {"de": "BlockThePixel beendet (Exit-Code {code}).", "en": "BlockThePixel finished (exit code {code})."},
    "log_strg_c": {"de": "Beendet durch Benutzer.", "en": "Stopped by user."},
    "log_vk_versuch": {"de": "Vulkan-Start, Versuch {n}/6: {e}", "en": "Vulkan start, attempt {n}/6: {e}"},
    "log_karte": {"de": "Karte: {name} | Treiber {treiber} | Heap {heap:.0f} MiB | Budget {bud:.0f} MiB, "
                        "belegt {use:.0f} MiB, frei {frei:.0f} MiB",
                  "en": "Card: {name} | driver {treiber} | heap {heap:.0f} MiB | budget {bud:.0f} MiB, "
                        "used {use:.0f} MiB, free {frei:.0f} MiB"},
    "log_ext": {"de": "Erweiterungen: memory_budget={b}, memory_priority={p} | Warteschlangen-Familie {f}",
                "en": "Extensions: memory_budget={b}, memory_priority={p} | queue family {f}"},
    "log_belegt": {"de": "Belegt: {n} Stücke à {mib} MiB = {ges:.0f} MiB ({sek:.1f} s)",
                   "en": "Allocated: {n} chunks of {mib} MiB = {ges:.0f} MiB ({sek:.1f} s)"},
    "log_zu_wenig": {"de": "Nur {belegt:.0f} von {ziel:.0f} MiB belegbar – Suche wäre unvollständig.",
                     "en": "Only {belegt:.0f} of {ziel:.0f} MiB could be allocated – search would be incomplete."},
    "log_durchgang": {"de": "Suche Durchgang {d}/{n}: {f} Fehler in {s} Stücken ({sek:.1f} s)",
                      "en": "Search pass {d}/{n}: {f} errors in {s} chunks ({sek:.1f} s)"},
    "log_waehrend": {"de": "Während der Suche: {ram} | GPU {temp}", "en": "During search: {ram} | GPU {temp}"},
    "log_stueck": {"de": "  Stück {nr:4d}: Fehler je Durchgang {f} | erster bei +0x{off:06X} soll {soll:08X} "
                         "ist {ist:08X}{zusatz}",
                   "en": "  Chunk {nr:4d}: errors per pass {f} | first at +0x{off:06X} expected {soll:08X} "
                         "got {ist:08X}{zusatz}"},
    "log_unbestaetigt": {"de": "  (unbestätigt)", "en": "  (unconfirmed)"},
    "log_kein_defekt": {"de": "Kein Defekt gefunden. Das ist KEIN Freispruch: Der defekte Bereich ist evtl. von "
                              "einem anderen Programm belegt. Nichts festgehalten.",
                        "en": "No defect found. This is NOT an all-clear: the defective region may be held by "
                              "another program. Nothing held."},
    "log_zu_viele": {"de": "{n} defekte Stücke = {mib} MiB (mehr als {p:g} % des Grafikspeichers) – Schaden zu groß "
                           "für eine Sperre.",
                     "en": "{n} defective chunks = {mib} MiB (more than {p:g} % of video memory) – damage too large "
                           "to block."},
    "log_empf": {"de": "Empfindlichkeit: {name}", "en": "Sensitivity: {name}"},
    "log_normalwert": {"de": "Normalwert: {text}", "en": "Baseline: {text}"},
    "log_festgehalten": {"de": "Festgehalten: {n} Stücke = {mib} MiB ({b} bestätigt). Rest freigegeben.",
                         "en": "Holding: {n} chunks = {mib} MiB ({b} confirmed). Rest released."},
    "log_jetzt": {"de": "Grafikspeicher jetzt: belegt {use:.0f} MiB, frei {frei:.0f} MiB | {ram}",
                  "en": "Video memory now: used {use:.0f} MiB, free {frei:.0f} MiB | {ram}"},
    "log_nur_suchen": {"de": "--nur-suchen: beende ohne Festhalten.", "en": "--search-only: exiting without holding."},
    "log_waechter_aktiv": {"de": "Wächter aktiv: Prüfung alle {s} s.", "en": "Watchdog active: check every {s} s."},
    "log_beenden": {"de": "Beenden angefordert.", "en": "Exit requested."},
    "log_neu": {"de": "Neue Suche angefordert.", "en": "New search requested."},
    "log_wieder_im_griff": {"de": "Wächter {r}: Defekt wieder im Griff.", "en": "Watchdog {r}: defect held again."},
    "log_im_griff": {"de": "Wächter {r}: Defekt im Griff ({f} Fehler, je Stück {je}, {temp}) | {ram}",
                     "en": "Watchdog {r}: defect held ({f} errors, per chunk {je}, {temp}) | {ram}"},
    "log_leer": {"de": "Wächter {r}: keine Fehler in den festgehaltenen Stücken ({n}× in Folge)",
                 "en": "Watchdog {r}: no errors in the held chunks ({n}× in a row)"},
    "log_verschoben": {"de": "Speicher vermutlich vom Treiber verschoben – Sperre unwirksam.",
                       "en": "Memory probably moved by the driver – block ineffective."},
    "log_aufraeumen": {"de": "Aufräumen unvollständig: {e}", "en": "Cleanup incomplete: {e}"},
    "log_unerwartet": {"de": "Unerwarteter Fehler im Wächter", "en": "Unexpected error in watchdog"},
    "log_symbol_sichtbar": {"de": "Symbol in der Taskleiste einmalig sichtbar geschaltet.",
                            "en": "Taskbar icon made visible (once)."},
    "log_symbol_nicht_gefunden": {"de": "Taskleisten-Eintrag nicht gefunden – Symbol ggf. von Hand sichtbar schalten.",
                                  "en": "Taskbar entry not found – make the icon visible manually if needed."},
    "log_symbol_fehler": {"de": "Symbol nicht sichtbar schaltbar: {e}", "en": "Could not make icon visible: {e}"},
    "log_symbol_anlegen": {"de": "Symbol in der Systemleiste konnte nicht angelegt werden.",
                           "en": "Could not create the notification area icon."},
    "log_leiste_aktualisieren": {"de": "Systemleiste nicht aktualisierbar: {e}",
                                 "en": "Could not update the notification area: {e}"},
    "log_sprache": {"de": "Sprache: Deutsch", "en": "Language: English"},
    "ram": {"de": "RAM {ws:.0f} MiB im Speicher, {priv:.0f} MiB reserviert",
            "en": "RAM {ws:.0f} MiB resident, {priv:.0f} MiB committed"},

    # Vulkan
    "vk_fehlgeschlagen": {"de": "{was} fehlgeschlagen (VkResult {res})", "en": "{was} failed (VkResult {res})"},
    "vk_keine_karte": {"de": "Keine NVIDIA-Grafikkarte gefunden", "en": "No NVIDIA graphics card found"},
    "vk_kein_typ": {"de": "Kein passender Speichertyp für {art}", "en": "No suitable memory type for {art}"},
    "vk_staging": {"de": "Staging-Puffer im Arbeitsspeicher nicht anlegbar",
                   "en": "Could not allocate staging buffers in system memory"},

    # Hinweise (Abweichungen)
    "h_groesser": {"de": "Der Defekt ist größer als üblich: {f} Fehler in {s} Stücken (Normalwert {nf} in {ns:.0f}).",
                   "en": "The defect is larger than usual: {f} errors in {s} chunks (baseline {nf} in {ns:.0f})."},
    "h_weniger": {"de": "Weniger Fehler als üblich: {f} statt {nf}. Vermutlich belegt ein anderes Programm einen Teil "
                        "der defekten Stelle; dort können Grafikfehler auftreten.",
                  "en": "Fewer errors than usual: {f} instead of {nf}. Another program probably holds part of the "
                        "defective region; graphical errors may appear there."},
    "h_waechst": {"de": "Der Defekt wächst seit drei Starts stetig.",
                  "en": "The defect has grown steadily over the last three starts."},
    "h_grenze": {"de": "Mehr als {p:g} % des Grafikspeichers gesperrt ({mib} MiB von {heap:.0f} MiB). Die Karte ist "
                       "zunehmend beschädigt – Ersatz einplanen.",
                 "en": "More than {p:g} % of video memory blocked ({mib} MiB of {heap:.0f} MiB). The card is "
                       "increasingly damaged – plan a replacement."},
    "h_waechter_mehr": {"de": "Der Wächter findet mehr Fehler als die Suche: {f} statt {sf}. Der Defekt wächst "
                              "möglicherweise.",
                        "en": "The watchdog finds more errors than the search: {f} instead of {sf}. The defect may "
                              "be growing."},

    # Warnfenster (Defekt nicht gesperrt)
    "m_vk_nicht": {"de": "BlockThePixel konnte die Grafikkarte nicht ansprechen.\n\nDer defekte Speicher ist NICHT "
                         "gesperrt. Details stehen in blockthepixel.log.\n\n{hilfe}",
                   "en": "BlockThePixel could not access the graphics card.\n\nThe defective memory is NOT blocked. "
                         "Details are in blockthepixel.log.\n\n{hilfe}"},
    "m_zu_wenig": {"de": "Nicht genug freier Grafikspeicher für die Suche (läuft schon ein Spiel?).\n\nDer defekte "
                         "Speicher ist NICHT gesperrt.\n\n{hilfe}",
                   "en": "Not enough free video memory for the search (is a game already running?).\n\nThe defective "
                         "memory is NOT blocked.\n\n{hilfe}"},
    "m_kein_defekt": {"de": "Kein Defekt gefunden – nichts gesperrt.\n\nVermutlich belegt ein anderes Programm "
                            "(Browser, Steam, Spiel) die defekte Stelle bereits. Dort können Grafikfehler auftreten."
                            "\n\nDiese Programme schließen. {hilfe}",
                      "en": "No defect found – nothing blocked.\n\nAnother program (browser, Steam, game) probably "
                            "holds the defective region already. Graphical errors may appear there.\n\nClose these "
                            "programs. {hilfe}"},
    "m_zu_viele": {"de": "{n} defekte Stücke gefunden ({mib} MiB, mehr als {p:g} % des Grafikspeichers) – zu viele "
                         "für eine Sperre.\n\nDer defekte Speicher ist NICHT gesperrt. Die Karte ist großflächig "
                         "beschädigt.",
                   "en": "{n} defective chunks found ({mib} MiB, more than {p:g} % of video memory) – too many to "
                         "block.\n\nThe defective memory is NOT blocked. The card is extensively damaged."},
    "m_verschoben": {"de": "Die Sperre greift vermutlich nicht mehr: Windows hat den festgehaltenen Speicher "
                           "verschoben. Spiele können wieder Grafikfehler zeigen.\n\nSpiel beenden. {hilfe}",
                     "en": "The block is probably no longer effective: Windows has moved the held memory. Games may "
                           "show graphical errors again.\n\nClose the game. {hilfe}"},
    "m_vk_fehler": {"de": "Vulkan-Fehler: {e}\n\nDer defekte Speicher ist NICHT mehr gesperrt.\n\n{hilfe}",
                    "en": "Vulkan error: {e}\n\nThe defective memory is NO LONGER blocked.\n\n{hilfe}"},
    "m_unerwartet": {"de": "Unerwarteter Fehler: {e}\n\nDer defekte Speicher ist NICHT gesperrt. Details stehen in "
                           "blockthepixel.log.",
                     "en": "Unexpected error: {e}\n\nThe defective memory is NOT blocked. Details are in "
                           "blockthepixel.log."},
    "hilfe_symbol": {"de": "Abhilfe: Rechtsklick auf das BlockThePixel-Symbol unten rechts → „Neu suchen“.",
                     "en": "Fix: right-click the BlockThePixel icon in the notification area → \"Search again\"."},
    "hilfe_ohne": {"de": "Abhilfe: BlockThePixel neu starten (Aufgabenplanung → BlockThePixel → Beenden, dann "
                         "Ausführen).",
                   "en": "Fix: restart BlockThePixel (Task Scheduler → BlockThePixel → End, then Run)."},

    # Kurzzustand (Tooltip)
    "k_startet": {"de": "startet …", "en": "starting …"},
    "k_suche": {"de": "Suche läuft …", "en": "Searching …"},
    "k_suche_d": {"de": "Suche läuft … Durchgang {d}/{n}", "en": "Searching … pass {d}/{n}"},
    "k_gesperrt": {"de": "{mib} MiB gesperrt · {f} Fehler", "en": "{mib} MiB blocked · {f} errors"},
    "k_pruefung": {"de": "{mib} MiB gesperrt · Prüfung {uhr} ✓", "en": "{mib} MiB blocked · checked {uhr} ✓"},
    "k_vk_nicht": {"de": "Grafikkarte nicht ansprechbar – nicht gesperrt",
                   "en": "Graphics card not accessible – not blocked"},
    "k_zu_wenig": {"de": "Zu wenig freier Grafikspeicher – nicht gesperrt",
                   "en": "Not enough free video memory – not blocked"},
    "k_kein_defekt": {"de": "Kein Defekt gefunden – nichts gesperrt", "en": "No defect found – nothing blocked"},
    "k_zu_viele": {"de": "{n} defekte Stücke – zu viele, nicht gesperrt",
                   "en": "{n} defective chunks – too many, not blocked"},
    "k_verschoben": {"de": "Sperre unwirksam – bitte neu suchen", "en": "Block ineffective – please search again"},
    "k_vk_fehler": {"de": "Vulkan-Fehler – nicht gesperrt", "en": "Vulkan error – not blocked"},
    "k_fehler": {"de": "Fehler – nicht gesperrt", "en": "Error – not blocked"},

    # Statusfenster
    "s_zustand": {"de": "Zustand", "en": "State"},
    "s_gesperrt": {"de": "Gesperrt", "en": "Blocked"},
    "s_fehler": {"de": "Fehler je Durchgang", "en": "Errors per pass"},
    "s_normal": {"de": "Normalwert", "en": "Baseline"},
    "s_seit": {"de": "Seit erster Messung", "en": "Since first measurement"},
    "s_gesucht": {"de": "Letzte Suche", "en": "Last search"},
    "s_pruefung": {"de": "Letzte Wächter-Prüfung", "en": "Last watchdog check"},
    "s_verlauf": {"de": "Verlauf", "en": "History"},
    "s_treiber": {"de": "Treiber", "en": "Driver"},
    "s_hinweise": {"de": "Hinweise", "en": "Notices"},
    "s_empf": {"de": "Empfindlichkeit", "en": "Sensitivity"},
    "v_empf": {"de": "{name} (Abweichung ab {mehr:g} %, Warnung ab {warn:g} % = {mib:.0f} MiB)",
               "en": "{name} (deviation from {mehr:g} %, warning from {warn:g} % = {mib:.0f} MiB)"},
    "name_streng": {"de": "Streng", "en": "Strict"},
    "name_normal": {"de": "Normal", "en": "Normal"},
    "name_tolerant": {"de": "Tolerant", "en": "Tolerant"},
    "v_gesperrt": {"de": "{n} Stücke = {mib} MiB (Nr. {nr})", "en": "{n} chunks = {mib} MiB (no. {nr})"},
    "v_normal_1": {"de": "{f} Fehler in {s:.0f} Stücken (aus 1 früheren Lauf)",
                   "en": "{f} errors in {s:.0f} chunks (from 1 previous run)"},
    "v_normal_n": {"de": "{f} Fehler in {s:.0f} Stücken (aus {n} früheren Läufen)",
                   "en": "{f} errors in {s:.0f} chunks (from {n} previous runs)"},
    "v_normal_keiner": {"de": "noch keiner (erster Lauf)", "en": "none yet (first run)"},
    "v_seit": {"de": "{datum}: {f0} Fehler in {s0} Stücken → jetzt {f} in {s} ({aend})",
               "en": "{datum}: {f0} errors in {s0} chunks → now {f} in {s} ({aend})"},
    "v_unveraendert": {"de": "unverändert", "en": "unchanged"},
    "v_prozent": {"de": "{p:+.0f} %", "en": "{p:+.0f} %"},
    "v_seit_erste": {"de": "dies ist die erste Messung", "en": "this is the first measurement"},
    "v_gesucht": {"de": "{zeit}, {temp}", "en": "{zeit}, {temp}"},
    "v_pruefung_keine": {"de": "noch keine", "en": "none yet"},
    "v_pruefung": {"de": "{uhr} – {f} Fehler, {temp}", "en": "{uhr} – {f} errors, {temp}"},
    "v_pruefung_leer": {"de": "{uhr} – keine Fehler gefunden ({n}× in Folge)",
                        "en": "{uhr} – no errors found ({n}× in a row)"},
    "v_statistik": {"de": "{s} Suchläufe, {w} Wächter-Prüfungen", "en": "{s} searches, {w} watchdog checks"},
    "v_temp": {"de": "{c} °C", "en": "{c} °C"},
    "v_temp_unbekannt": {"de": "Temperatur unbekannt", "en": "temperature unknown"},

    # Menü
    "menu_status": {"de": "Status anzeigen", "en": "Show status"},
    "menu_pruefen": {"de": "Jetzt prüfen", "en": "Check now"},
    "menu_neu": {"de": "Neu suchen …", "en": "Search again …"},
    "menu_protokoll": {"de": "Protokoll öffnen", "en": "Open log"},
    "menu_sprache": {"de": "Sprache / Language", "en": "Sprache / Language"},
    "menu_empf": {"de": "Empfindlichkeit / Sensitivity", "en": "Empfindlichkeit / Sensitivity"},
    "menu_empf_eintrag": {"de": "{name} – Abweichung ab {mehr:g} %, Warnung ab {warn:g} % des Grafikspeichers",
                          "en": "{name} – deviation from {mehr:g} %, warning from {warn:g} % of video memory"},
    "menu_beenden": {"de": "Beenden …", "en": "Exit …"},
    "frage_neu": {"de": "Neu suchen?\n\nVorher Spiele schließen – die Suche belegt kurz fast den ganzen "
                        "Grafikspeicher.",
                  "en": "Search again?\n\nClose games first – the search briefly takes almost all video memory."},
    "frage_beenden": {"de": "BlockThePixel beenden?\n\nDanach ist der defekte Speicher nicht mehr gesperrt.",
                      "en": "Exit BlockThePixel?\n\nThe defective memory will no longer be blocked."},
}


def t(schluessel, **kw):
    """Text in der aktuellen Sprache, mit Platzhaltern gefüllt."""
    eintrag = TEXTE[schluessel]
    text = eintrag.get(EINSTELLUNG["sprache"]) or eintrag["de"]
    return text.format(**kw) if kw else text


class T:
    """Übersetzbarer Text, der erst bei der Anzeige in der dann gültigen Sprache formatiert wird."""
    __slots__ = ("schluessel", "kw")

    def __init__(self, schluessel, **kw):
        self.schluessel = schluessel
        self.kw = kw

    def __format__(self, spec):
        return format(t(self.schluessel, **self.kw), spec)

    def __str__(self):
        return format(self, "")


class Z:
    """Ganze Zahl mit dem Tausendertrennzeichen der aktuellen Sprache (16.384 / 16,384)."""
    __slots__ = ("wert",)

    def __init__(self, wert):
        self.wert = wert

    def __format__(self, spec):
        s = f"{self.wert:,.0f}"
        return s.replace(",", ".") if EINSTELLUNG["sprache"] == "de" else s

    def __str__(self):
        return format(self, "")


def systemsprache():
    """Deutsch, wenn die Windows-Oberfläche deutsch ist, sonst Englisch."""
    try:
        return "de" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x07 else "en"
    except (AttributeError, OSError):
        return "en"


def lese_einstellung(name, erlaubt):
    """Gespeicherte Wahl aus HKCU\\Software\\BlockThePixel, oder None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\BlockThePixel") as k:
            wert = winreg.QueryValueEx(k, name)[0]
        return wert if wert in erlaubt else None
    except OSError:
        return None


def speichere_einstellung(name, wert):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\BlockThePixel") as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, wert)
    except OSError:
        pass


# ---------- Windows-Hilfen ----------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi")
user32 = ctypes.WinDLL("user32")


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]

ERROR_ALREADY_EXISTS = 183
MB_WARNUNG = 0x30 | 0x10000 | 0x40000  # Warnsymbol, Vordergrund, immer oben


def ram_text():
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return t("ram", ws=pmc.WorkingSetSize / MIB, priv=pmc.PrivateUsage / MIB)


def arbeitsspeicher_zurueckgeben():
    gc.collect()
    psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())


def einzige_instanz():
    """Liefert ein Mutex-Handle oder None, wenn BlockThePixel schon läuft."""
    h = kernel32.CreateMutexW(None, False, "Local\\BlockThePixel")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return h


class Melder:
    """Zeigt Warnungen als Fenster (nur mit --meldungen), sonst nur Protokoll."""

    def __init__(self, aktiv):
        self.aktiv = aktiv

    def __call__(self, text, warten=False):
        if not self.aktiv:
            return
        th = threading.Thread(target=user32.MessageBoxW, args=(None, str(text), NAME, MB_WARNUNG), daemon=not warten)
        th.start()
        if warten:
            th.join()


# ---------- Vulkan ----------
class VulkanFehler(RuntimeError):
    pass


def ck(res, was):
    if res != VK_SUCCESS:
        raise VulkanFehler(t("vk_fehlgeschlagen", was=was, res=res))


class Chunk:
    __slots__ = ("nr", "buf", "mem", "fehler", "erste_fehler")

    def __init__(self, nr, buf, mem):
        self.nr = nr
        self.buf = buf
        self.mem = mem
        self.fehler = []          # Fehlerzahl je Durchgang
        self.erste_fehler = None  # (Byte-Offset, erwartet, gelesen)


class Gpu:
    def __init__(self, vk):
        self.vk = vk
        self._keep = []
        self.instance = None
        self.device = None
        self.pool = None
        self.fence = None

    def init(self):
        vk = self.vk
        app_name = ffi.new("char[]", NAME.encode())
        app = ffi.new("VkApplicationInfo*", {
            "sType": ST_APPLICATION_INFO, "pApplicationName": app_name,
            "pEngineName": app_name, "apiVersion": API_VERSION_1_1})
        ici = ffi.new("VkInstanceCreateInfo*", {"sType": ST_INSTANCE_CREATE_INFO, "pApplicationInfo": app})
        inst = ffi.new("VkInstance*")
        ck(vk.vkCreateInstance(ici, ffi.NULL, inst), "vkCreateInstance")
        self.instance = inst[0]

        n = ffi.new("uint32_t*")
        ck(vk.vkEnumeratePhysicalDevices(self.instance, n, ffi.NULL), "vkEnumeratePhysicalDevices")
        pds = ffi.new("VkPhysicalDevice[]", n[0])
        ck(vk.vkEnumeratePhysicalDevices(self.instance, n, pds), "vkEnumeratePhysicalDevices")

        self.pd = None
        for i in range(n[0]):
            props = ffi.new("uint8_t[2048]")
            vk.vkGetPhysicalDeviceProperties(pds[i], props)
            vendor = ffi.cast("uint32_t*", props)[2]
            if vendor == NVIDIA_VENDOR_ID:
                self.pd = pds[i]
                self.name = ffi.string(ffi.cast("char*", props + 20)).decode(errors="replace")
                max_alloc = ffi.cast("uint32_t*", props + 332)[0]  # limits.maxMemoryAllocationCount
                self.max_alloc_count = max_alloc if 64 <= max_alloc <= 1_000_000 else 4096
                break
        if self.pd is None:
            raise VulkanFehler(t("vk_keine_karte"))

        ck(vk.vkEnumerateDeviceExtensionProperties(self.pd, ffi.NULL, n, ffi.NULL), "vkEnumerateDeviceExtensionProperties")
        exts = ffi.new("VkExtensionProperties[]", n[0])
        ck(vk.vkEnumerateDeviceExtensionProperties(self.pd, ffi.NULL, n, exts), "vkEnumerateDeviceExtensionProperties")
        vorhanden = {ffi.string(exts[i].extensionName).decode() for i in range(n[0])}
        self.hat_budget = "VK_EXT_memory_budget" in vorhanden
        self.hat_prioritaet = "VK_EXT_memory_priority" in vorhanden

        self._lese_speichertypen()

        # Warteschlange: bevorzugt reine Kopier-Engine
        qn = ffi.new("uint32_t*")
        vk.vkGetPhysicalDeviceQueueFamilyProperties(self.pd, qn, ffi.NULL)
        qfp = ffi.new("VkQueueFamilyProperties[]", qn[0])
        vk.vkGetPhysicalDeviceQueueFamilyProperties(self.pd, qn, qfp)
        familie = None
        for i in range(qn[0]):
            f = qfp[i].queueFlags
            if f & QUEUE_TRANSFER and not f & (QUEUE_GRAPHICS | QUEUE_COMPUTE):
                familie = i
                break
        if familie is None:
            for i in range(qn[0]):
                if qfp[i].queueFlags & (QUEUE_TRANSFER | QUEUE_GRAPHICS | QUEUE_COMPUTE):
                    familie = i
                    break
        self.familie = familie

        prio = ffi.new("float[]", [1.0])
        qci = ffi.new("VkDeviceQueueCreateInfo*", {
            "sType": ST_DEVICE_QUEUE_CREATE_INFO, "queueFamilyIndex": familie,
            "queueCount": 1, "pQueuePriorities": prio})
        ext_namen = []
        if self.hat_budget:
            ext_namen.append(b"VK_EXT_memory_budget")
        if self.hat_prioritaet:
            ext_namen.append(b"VK_EXT_memory_priority")
        ext_c = [ffi.new("char[]", e) for e in ext_namen]
        ext_arr = ffi.new("const char*[]", ext_c) if ext_c else ffi.NULL
        feat = ffi.new("VkPhysicalDeviceMemoryPriorityFeaturesEXT*", {
            "sType": ST_PHYSICAL_DEVICE_MEMORY_PRIORITY_FEATURES_EXT, "memoryPriority": 1})
        dci = ffi.new("VkDeviceCreateInfo*", {
            "sType": ST_DEVICE_CREATE_INFO,
            "pNext": feat if self.hat_prioritaet else ffi.NULL,
            "queueCreateInfoCount": 1, "pQueueCreateInfos": qci,
            "enabledExtensionCount": len(ext_c), "ppEnabledExtensionNames": ext_arr})
        dev = ffi.new("VkDevice*")
        ck(vk.vkCreateDevice(self.pd, dci, ffi.NULL, dev), "vkCreateDevice")
        self.device = dev[0]
        q = ffi.new("VkQueue*")
        vk.vkGetDeviceQueue(self.device, familie, 0, q)
        self.queue = q[0]

        cpci = ffi.new("VkCommandPoolCreateInfo*", {
            "sType": ST_COMMAND_POOL_CREATE_INFO, "flags": 0x2, "queueFamilyIndex": familie})
        pool = ffi.new("VkCommandPool*")
        ck(vk.vkCreateCommandPool(self.device, cpci, ffi.NULL, pool), "vkCreateCommandPool")
        self.pool = pool[0]
        cbai = ffi.new("VkCommandBufferAllocateInfo*", {
            "sType": ST_COMMAND_BUFFER_ALLOCATE_INFO, "commandPool": self.pool,
            "level": 0, "commandBufferCount": 1})
        cb = ffi.new("VkCommandBuffer[1]")
        ck(vk.vkAllocateCommandBuffers(self.device, cbai, cb), "vkAllocateCommandBuffers")
        self.cb = cb[0]
        self.cb_arr = cb
        fci = ffi.new("VkFenceCreateInfo*", {"sType": ST_FENCE_CREATE_INFO})
        fence = ffi.new("VkFence[1]")
        ck(vk.vkCreateFence(self.device, fci, ffi.NULL, fence), "vkCreateFence")
        self.fence = fence[0]
        self.fence_arr = fence

        self._prio_info = ffi.new("VkMemoryPriorityAllocateInfoEXT*", {
            "sType": ST_MEMORY_PRIORITY_ALLOCATE_INFO_EXT, "priority": 1.0})
        self._keep += [app_name, app, ici, prio, qci, ext_c, ext_arr, feat, dci]

    def _lese_speichertypen(self):
        p2 = ffi.new("VkPhysicalDeviceMemoryProperties2*")
        p2.sType = ST_PHYSICAL_DEVICE_MEMORY_PROPERTIES_2
        self.vk.vkGetPhysicalDeviceMemoryProperties2(self.pd, p2)
        mp = p2.memoryProperties
        heaps = [(mp.memoryHeaps[i].size, i) for i in range(mp.memoryHeapCount)
                 if mp.memoryHeaps[i].flags & HEAP_DEVICE_LOCAL]
        self.vram_heap_groesse, self.vram_heap = max(heaps)
        self.typen = [(mp.memoryTypes[i].propertyFlags, mp.memoryTypes[i].heapIndex)
                      for i in range(mp.memoryTypeCount)]

    def budget(self):
        """(frei, budget, belegt) des Grafikspeicher-Heaps in Bytes."""
        p2 = ffi.new("VkPhysicalDeviceMemoryProperties2*")
        b = ffi.new("VkPhysicalDeviceMemoryBudgetPropertiesEXT*")
        b.sType = ST_PHYSICAL_DEVICE_MEMORY_BUDGET_PROPERTIES_EXT
        p2.sType = ST_PHYSICAL_DEVICE_MEMORY_PROPERTIES_2
        p2.pNext = b
        self.vk.vkGetPhysicalDeviceMemoryProperties2(self.pd, p2)
        bud = b.heapBudget[self.vram_heap]
        use = b.heapUsage[self.vram_heap]
        return max(0, bud - use), bud, use

    def waehle_typ(self, bits, will, nicht=0, heap=None):
        for i, (flags, h) in enumerate(self.typen):
            if not bits & (1 << i):
                continue
            if flags & will != will or flags & nicht:
                continue
            if heap is not None and h != heap:
                continue
            return i
        return None

    def puffer(self, groesse, art):
        """art: 'vram', 'upload', 'readback'. Liefert (buf, mem, ptr|None) oder None bei Speichermangel."""
        vk = self.vk
        bci = ffi.new("VkBufferCreateInfo*", {
            "sType": ST_BUFFER_CREATE_INFO, "size": groesse,
            "usage": BUF_TRANSFER_SRC | BUF_TRANSFER_DST, "sharingMode": 0})
        buf = ffi.new("VkBuffer*")
        ck(vk.vkCreateBuffer(self.device, bci, ffi.NULL, buf), "vkCreateBuffer")
        req = ffi.new("VkMemoryRequirements*")
        vk.vkGetBufferMemoryRequirements(self.device, buf[0], req)

        if art == "vram":
            typ = self.waehle_typ(req.memoryTypeBits, MEM_DEVICE_LOCAL, MEM_HOST_VISIBLE, self.vram_heap)
        elif art == "readback":
            typ = self.waehle_typ(req.memoryTypeBits, MEM_HOST_VISIBLE | MEM_HOST_COHERENT | MEM_HOST_CACHED,
                                  MEM_DEVICE_LOCAL)
            if typ is None:
                typ = self.waehle_typ(req.memoryTypeBits, MEM_HOST_VISIBLE | MEM_HOST_COHERENT, MEM_DEVICE_LOCAL)
        else:
            typ = self.waehle_typ(req.memoryTypeBits, MEM_HOST_VISIBLE | MEM_HOST_COHERENT, MEM_DEVICE_LOCAL)
        if typ is None:
            vk.vkDestroyBuffer(self.device, buf[0], ffi.NULL)
            raise VulkanFehler(t("vk_kein_typ", art=art))

        mai = ffi.new("VkMemoryAllocateInfo*", {
            "sType": ST_MEMORY_ALLOCATE_INFO, "allocationSize": req.size, "memoryTypeIndex": typ})
        if art == "vram" and self.hat_prioritaet:
            mai.pNext = self._prio_info
        mem = ffi.new("VkDeviceMemory*")
        res = vk.vkAllocateMemory(self.device, mai, ffi.NULL, mem)
        if res in (VK_ERROR_OUT_OF_DEVICE_MEMORY, VK_ERROR_OUT_OF_HOST_MEMORY):
            vk.vkDestroyBuffer(self.device, buf[0], ffi.NULL)
            return None
        ck(res, "vkAllocateMemory")
        ck(vk.vkBindBufferMemory(self.device, buf[0], mem[0], 0), "vkBindBufferMemory")
        ptr = None
        if art != "vram":
            pp = ffi.new("void**")
            ck(vk.vkMapMemory(self.device, mem[0], 0, VK_WHOLE_SIZE, 0, pp), "vkMapMemory")
            ptr = pp[0]
        return buf[0], mem[0], ptr

    def freigeben(self, buf, mem):
        self.vk.vkDestroyBuffer(self.device, buf, ffi.NULL)
        self.vk.vkFreeMemory(self.device, mem, ffi.NULL)

    def kopiere(self, kopien, host_lesen=False):
        """kopien: Liste (src_buf, dst_buf, src_off, dst_off, groesse). Wartet bis fertig."""
        vk = self.vk
        ck(vk.vkResetCommandBuffer(self.cb, 0), "vkResetCommandBuffer")
        bi = ffi.new("VkCommandBufferBeginInfo*", {"sType": ST_COMMAND_BUFFER_BEGIN_INFO, "flags": 0x1})
        ck(vk.vkBeginCommandBuffer(self.cb, bi), "vkBeginCommandBuffer")
        vor = ffi.new("VkMemoryBarrier*", {"sType": ST_MEMORY_BARRIER,
                                           "srcAccessMask": ACCESS_TRANSFER_WRITE,
                                           "dstAccessMask": ACCESS_TRANSFER_READ | ACCESS_TRANSFER_WRITE})
        vk.vkCmdPipelineBarrier(self.cb, STAGE_TRANSFER, STAGE_TRANSFER, 0, 1, vor, 0, ffi.NULL, 0, ffi.NULL)
        region = ffi.new("VkBufferCopy*")
        for src, dst, so, do, g in kopien:
            region.srcOffset, region.dstOffset, region.size = so, do, g
            vk.vkCmdCopyBuffer(self.cb, src, dst, 1, region)
        if host_lesen:
            nach = ffi.new("VkMemoryBarrier*", {"sType": ST_MEMORY_BARRIER,
                                                "srcAccessMask": ACCESS_TRANSFER_WRITE,
                                                "dstAccessMask": ACCESS_HOST_READ})
            vk.vkCmdPipelineBarrier(self.cb, STAGE_TRANSFER, STAGE_HOST, 0, 1, nach, 0, ffi.NULL, 0, ffi.NULL)
        ck(vk.vkEndCommandBuffer(self.cb), "vkEndCommandBuffer")
        si = ffi.new("VkSubmitInfo*", {"sType": ST_SUBMIT_INFO, "commandBufferCount": 1,
                                       "pCommandBuffers": self.cb_arr})
        ck(vk.vkResetFences(self.device, 1, self.fence_arr), "vkResetFences")
        ck(vk.vkQueueSubmit(self.queue, 1, si, self.fence), "vkQueueSubmit")
        ck(vk.vkWaitForFences(self.device, 1, self.fence_arr, 1, FENCE_TIMEOUT_NS), "vkWaitForFences")

    def schliessen(self):
        vk = self.vk
        if self.device:
            vk.vkDeviceWaitIdle(self.device)
            if self.fence:
                vk.vkDestroyFence(self.device, self.fence, ffi.NULL)
            if self.pool:
                vk.vkDestroyCommandPool(self.device, self.pool, ffi.NULL)
            vk.vkDestroyDevice(self.device, ffi.NULL)
            self.device = None
        if self.instance:
            vk.vkDestroyInstance(self.instance, ffi.NULL)
            self.instance = None


class Pruefer:
    """Schreib-/Lesetest über Staging-Puffer im Arbeitsspeicher: erst alles schreiben, dann alles lesen."""

    def __init__(self, gpu, chunk_bytes, stapel):
        self.gpu = gpu
        self.cb = chunk_bytes
        self.stapel = stapel
        self.wpc = chunk_bytes // 4
        groesse = chunk_bytes * stapel
        up = gpu.puffer(groesse, "upload")
        rb = gpu.puffer(groesse, "readback")
        if up is None or rb is None:
            raise VulkanFehler(t("vk_staging"))
        self.up_buf, self.up_mem, up_ptr = up
        self.rb_buf, self.rb_mem, rb_ptr = rb
        self.up = np.frombuffer(ffi.buffer(up_ptr, groesse), dtype=np.uint32)
        self.rb = np.frombuffer(ffi.buffer(rb_ptr, groesse), dtype=np.uint32)
        self.erwartet = np.empty(groesse // 4, dtype=np.uint32)
        self.ungleich = np.empty(groesse // 4, dtype=bool)

    def freigeben(self):
        self.up = self.rb = self.erwartet = self.ungleich = None
        self.gpu.freigeben(self.up_buf, self.up_mem)
        self.gpu.freigeben(self.rb_buf, self.rb_mem)

    @staticmethod
    def _konstante(durchgang, stapel_nr):
        return np.uint32((durchgang * 0x9E3779B1 + stapel_nr * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF)

    def durchgang(self, chunks, durchgang_nr, pause_s=0.0):
        """Schreibt Muster in alle chunks, liest zurück. Liefert Gesamtfehler; trägt je Chunk ein."""
        rng = np.random.default_rng(0xC0FFEE + durchgang_nr)
        basis = rng.integers(0, 2**32, size=self.wpc * self.stapel, dtype=np.uint32)
        stapelliste = [chunks[i:i + self.stapel] for i in range(0, len(chunks), self.stapel)]

        for s, gruppe in enumerate(stapelliste):
            np.bitwise_xor(basis, self._konstante(durchgang_nr, s), out=self.up)
            self.gpu.kopiere([(self.up_buf, c.buf, j * self.cb, 0, self.cb) for j, c in enumerate(gruppe)])

        if pause_s:
            time.sleep(pause_s)

        gesamt = 0
        for s, gruppe in enumerate(stapelliste):
            self.gpu.kopiere([(c.buf, self.rb_buf, 0, j * self.cb, self.cb) for j, c in enumerate(gruppe)],
                             host_lesen=True)
            n = len(gruppe) * self.wpc
            np.bitwise_xor(basis[:n], self._konstante(durchgang_nr, s), out=self.erwartet[:n])
            np.not_equal(self.rb[:n], self.erwartet[:n], out=self.ungleich[:n])
            je_chunk = self.ungleich[:n].reshape(len(gruppe), self.wpc).sum(axis=1)
            for j, c in enumerate(gruppe):
                f = int(je_chunk[j])
                c.fehler.append(f)
                gesamt += f
                if f and c.erste_fehler is None:
                    w = int(np.flatnonzero(self.ungleich[j * self.wpc:(j + 1) * self.wpc])[0])
                    idx = j * self.wpc + w
                    c.erste_fehler = (w * 4, int(self.erwartet[idx]), int(self.rb[idx]))
        return gesamt


# ---------- Hilfen ----------
def temp_text(grad):
    return T("v_temp", c=grad) if grad is not None else T("v_temp_unbekannt")


def jetzt():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Nvml:
    """Liest Temperatur und Treiberversion über nvml.dll. Fehlt sie, liefert alles None."""

    def __init__(self):
        self.lib = None
        self.handle = ctypes.c_void_p()
        for pfad in ("nvml.dll", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll"):
            try:
                lib = ctypes.CDLL(pfad)
            except OSError:
                continue
            if lib.nvmlInit_v2() == 0 and lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.handle)) == 0:
                self.lib = lib
            break

    def temperatur(self):
        if not self.lib:
            return None
        wert = ctypes.c_uint()
        return wert.value if self.lib.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(wert)) == 0 else None

    def treiber(self):
        if not self.lib:
            return None
        buf = ctypes.create_string_buffer(80)
        return buf.value.decode() if self.lib.nvmlSystemGetDriverVersion(buf, 80) == 0 else None


# ---------- Verlauf ----------
class Verlauf:
    """SQLite-Verlauf aller Suchläufe und Wächter-Prüfungen. Nur aus dem Wächter-Thread benutzen."""

    def __init__(self, pfad):
        self.db = sqlite3.connect(pfad)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS suchlauf (
                id INTEGER PRIMARY KEY, zeit TEXT NOT NULL, version TEXT, treiber TEXT, temp_c INTEGER,
                belegt_mib INTEGER, fehler_max INTEGER, fehler_min INTEGER, stuecke INTEGER,
                bestaetigt INTEGER, ergebnis TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS stueck (
                suchlauf_id INTEGER NOT NULL REFERENCES suchlauf(id), nr INTEGER, fehler TEXT, erster_offset INTEGER);
            CREATE TABLE IF NOT EXISTS waechter (
                id INTEGER PRIMARY KEY, zeit TEXT NOT NULL, suchlauf_id INTEGER REFERENCES suchlauf(id),
                fehler INTEGER, temp_c INTEGER);
        """)

    def _eins(self, sql, *p):
        row = self.db.execute(sql, p).fetchone()
        return row[0] if row else None

    def suchlauf(self, ergebnis, treiber=None, temp=None, belegt_mib=None, fehler=(), defekt=(), bestaetigt=0):
        cur = self.db.execute(
            "INSERT INTO suchlauf (zeit, version, treiber, temp_c, belegt_mib, fehler_max, fehler_min, stuecke, "
            "bestaetigt, ergebnis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (jetzt(), VERSION, treiber, temp, belegt_mib, max(fehler) if fehler else None,
             min(fehler) if fehler else None, len(defekt), bestaetigt, ergebnis))
        sid = cur.lastrowid
        self.db.executemany("INSERT INTO stueck (suchlauf_id, nr, fehler, erster_offset) VALUES (?, ?, ?, ?)",
                            [(sid, c.nr, json.dumps(c.fehler), c.erste_fehler[0] if c.erste_fehler else None)
                             for c in defekt])
        self.db.commit()
        return sid

    def waechter(self, suchlauf_id, fehler, temp):
        self.db.execute("INSERT INTO waechter (zeit, suchlauf_id, fehler, temp_c) VALUES (?, ?, ?, ?)",
                        (jetzt(), suchlauf_id, fehler, temp))
        self.db.commit()

    def fruehere_ok(self, vor_id, anzahl):
        """Die letzten erfolgreichen Suchläufe vor vor_id, älteste zuerst: [(zeit, fehler_max, stuecke)]."""
        rows = self.db.execute(
            "SELECT zeit, fehler_max, stuecke FROM suchlauf WHERE ergebnis = 'ok' AND id < ? "
            "ORDER BY id DESC LIMIT ?", (vor_id, anzahl)).fetchall()
        return rows[::-1]

    def erster_ok(self):
        return self.db.execute(
            "SELECT id, zeit, fehler_max, stuecke FROM suchlauf WHERE ergebnis = 'ok' ORDER BY id LIMIT 1").fetchone()

    def zaehler(self):
        return self._eins("SELECT COUNT(*) FROM suchlauf"), self._eins("SELECT COUNT(*) FROM waechter")


def normalwert_text(frueher):
    if not frueher:
        return T("v_normal_keiner")
    nf = statistics.median(f for _, f, _ in frueher)
    ns = statistics.median(s for _, _, s in frueher)
    return T("v_normal_1" if len(frueher) == 1 else "v_normal_n", f=Z(nf), s=ns, n=len(frueher))


def bewerte_suche(fehler, stuecke, mib, frueher, heap_mib):
    """Einfache Regeln gegen den Normalwert (Median der früheren Läufe), Schwellen nach gewählter Empfindlichkeit.
    Liefert eine Liste von Hinweisen."""
    p = EMPFINDLICHKEIT[EINSTELLUNG["empfindlichkeit"]]
    meldungen = []
    if frueher:
        nf = statistics.median(f for _, f, _ in frueher)
        ns = statistics.median(s for _, _, s in frueher)
        if fehler > nf * (1 + p["mehr"]) or stuecke > ns + 1:
            meldungen.append(T("h_groesser", f=Z(fehler), s=stuecke, nf=Z(nf), ns=ns))
        elif fehler < nf * p["weniger"]:
            meldungen.append(T("h_weniger", f=Z(fehler), nf=Z(nf)))
        letzte = [f for _, f, _ in frueher[-2:]] + [fehler]
        faktor = 1 + p["wachstum"]
        if len(letzte) == 3 and letzte[0] * faktor < letzte[1] and letzte[1] * faktor < letzte[2]:
            meldungen.append(T("h_waechst"))
    if mib > heap_mib * p["warn_prozent"] / 100:
        meldungen.append(T("h_grenze", p=p["warn_prozent"], mib=mib, heap=heap_mib))
    return meldungen


# ---------- gemeinsamer Zustand ----------
class Zustand:
    """Stand für Systemleiste und Statusfenster. Der Wächter schreibt, die Systemleiste liest.
    Texte liegen als T/Z-Objekte vor und werden erst bei der Anzeige übersetzt."""

    def __init__(self):
        self._lock = threading.Lock()
        self.farbe = "grau"
        self.kurz = T("k_startet")
        self.details = {}
        self.blasen = []
        self.bei_aenderung = None

    def setze(self, farbe=None, kurz=None, blase=None, **details):
        with self._lock:
            if farbe:
                self.farbe = farbe
            if kurz:
                self.kurz = kurz
            self.details.update(details)
            if blase:
                self.blasen.append(blase)
        if self.bei_aenderung:
            self.bei_aenderung()

    def lese(self):
        with self._lock:
            return self.farbe, self.kurz, dict(self.details)

    def hole_blasen(self):
        with self._lock:
            b, self.blasen = self.blasen, []
        return b


# ---------- Wächter-Thread (alle Vulkan-Arbeit) ----------
class Waechter(threading.Thread):
    def __init__(self, args, ordner, zustand, melde, mit_symbol):
        super().__init__(name="Waechter", daemon=True)
        self.args = args
        self.ordner = ordner
        self.zustand = zustand
        self.melde = melde
        self.mit_symbol = mit_symbol
        self.befehle = queue.Queue()
        self.exit_code = EXIT_OK
        self.bei_ende = None

    @property
    def neustart_hinweis(self):
        return T("hilfe_symbol") if self.mit_symbol else T("hilfe_ohne")

    def hinweis(self, text):
        """Abweichungen: als Blase am Symbol, ohne Symbol als Fenster (nur mit --meldungen)."""
        log.warning("%s", text)
        if self.mit_symbol:
            self.zustand.setze(blase=text)
        else:
            self.melde(text)

    def rot(self, kurz, text):
        """Defekt nicht gesperrt: Symbol rot und Fenster, das man wegklicken muss."""
        self.zustand.setze("rot", kurz)
        self.melde(text, warten=not self.mit_symbol)

    def run(self):
        try:
            self.exit_code = self._laufen()
        except Exception as e:
            log.exception(t("log_unerwartet"))
            self.rot(T("k_fehler"), T("m_unerwartet", e=e))
            self.exit_code = EXIT_UNERWARTET
        finally:
            if self.bei_ende:
                self.bei_ende()

    def _laufen(self):
        verlauf = Verlauf(self.ordner / "blockthepixel.db")
        nvml = Nvml()
        while True:
            ergebnis, code = self._zyklus(verlauf, nvml)
            if ergebnis == "beenden":
                return code
            if ergebnis == "neu":
                continue
            if not self.mit_symbol:
                return code
            befehl = self.befehle.get()
            while befehl not in ("beenden", "neu_suchen"):
                befehl = self.befehle.get()
            if befehl == "beenden":
                return code

    def _gpu_starten(self):
        vk = ffi.dlopen("vulkan-1.dll")
        for versuch in range(1, 7):
            gpu = Gpu(vk)
            try:
                gpu.init()
                return gpu
            except VulkanFehler as e:
                log.warning(t("log_vk_versuch", n=versuch, e=e))
                gpu.schliessen()
                time.sleep(10)
        return None

    def _zyklus(self, verlauf, nvml):
        """Ein Suchlauf mit anschließendem Festhalten. Liefert ("beenden"|"neu"|"fehler", exit_code)."""
        a = self.args
        z = self.zustand
        z.setze("gelb", T("k_suche"))
        treiber = nvml.treiber()
        gpu = self._gpu_starten()
        if gpu is None:
            verlauf.suchlauf("vulkan_fehler", treiber, nvml.temperatur())
            self.rot(T("k_vk_nicht"), T("m_vk_nicht", hilfe=self.neustart_hinweis))
            return "fehler", EXIT_VULKAN

        chunk_bytes = a.chunk_mib * MIB
        stapel = max(1, 64 // a.chunk_mib)
        chunks = []
        pruefer = None

        def alles_freigeben():
            """Gibt Staging-Puffer und alle Stücke frei – vor jeder Meldung, damit kein VRAM blockiert bleibt."""
            nonlocal pruefer, chunks
            try:
                if pruefer:
                    pruefer.freigeben()
                for c in chunks:
                    gpu.freigeben(c.buf, c.mem)
            except Exception as e:  # Aufräumen darf das Ergebnis nicht verdecken
                log.warning(t("log_aufraeumen", e=e))
            pruefer = None
            chunks = []

        try:
            frei, bud, use = gpu.budget() if gpu.hat_budget else (gpu.vram_heap_groesse, gpu.vram_heap_groesse, 0)
            log.info(t("log_karte", name=gpu.name, treiber=treiber, heap=gpu.vram_heap_groesse / MIB, bud=bud / MIB,
                       use=use / MIB, frei=frei / MIB))
            log.info(t("log_ext", b=gpu.hat_budget, p=gpu.hat_prioritaet, f=gpu.familie))

            # ---- belegen ----
            ziel = frei - a.reserve_mib * MIB
            max_anzahl = min(gpu.max_alloc_count - 32, ziel // chunk_bytes)
            start = time.time()
            while len(chunks) < max_anzahl:
                r = gpu.puffer(chunk_bytes, "vram")
                if r is None:
                    break
                chunks.append(Chunk(len(chunks), r[0], r[1]))
            belegt = len(chunks) * chunk_bytes
            log.info(t("log_belegt", n=len(chunks), mib=a.chunk_mib, ges=belegt / MIB, sek=time.time() - start))
            if belegt < 0.8 * max(ziel, 1):
                log.error(t("log_zu_wenig", belegt=belegt / MIB, ziel=ziel / MIB))
                alles_freigeben()
                verlauf.suchlauf("zu_wenig_speicher", treiber, nvml.temperatur(), belegt // MIB)
                self.rot(T("k_zu_wenig"), T("m_zu_wenig", hilfe=self.neustart_hinweis))
                return "fehler", EXIT_ZU_WENIG_SPEICHER

            # ---- suchen ----
            pruefer = Pruefer(gpu, chunk_bytes, stapel)
            fehler_je_durchgang = []
            for d in range(a.durchgaenge):
                z.setze(kurz=T("k_suche_d", d=d + 1, n=a.durchgaenge))
                start = time.time()
                fehler = pruefer.durchgang(chunks, d)
                fehler_je_durchgang.append(fehler)
                betroffen = sum(1 for c in chunks if c.fehler[-1])
                log.info(t("log_durchgang", d=d + 1, n=a.durchgaenge, f=fehler, s=betroffen, sek=time.time() - start))
            temp = nvml.temperatur()
            log.info(t("log_waehrend", ram=ram_text(), temp=temp_text(temp)))

            defekt = [c for c in chunks if any(c.fehler)]
            bestaetigt = [c for c in defekt if sum(1 for f in c.fehler if f) >= 2]
            for c in defekt:
                off, soll, ist = c.erste_fehler
                log.info(t("log_stueck", nr=c.nr, f=c.fehler, off=off, soll=soll, ist=ist,
                           zusatz="" if c in bestaetigt else t("log_unbestaetigt")))
            if not defekt:
                log.warning(t("log_kein_defekt"))
                alles_freigeben()
                verlauf.suchlauf("kein_defekt", treiber, temp, belegt // MIB, fehler_je_durchgang)
                self.rot(T("k_kein_defekt"), T("m_kein_defekt", hilfe=self.neustart_hinweis))
                return "fehler", EXIT_KEIN_DEFEKT
            heap_mib = gpu.vram_heap_groesse / MIB
            mib = len(defekt) * a.chunk_mib
            if mib > heap_mib * a.abbruch_prozent / 100:
                log.error(t("log_zu_viele", n=len(defekt), mib=mib, p=a.abbruch_prozent))
                alles_freigeben()
                verlauf.suchlauf("zu_viele", treiber, temp, belegt // MIB, fehler_je_durchgang, defekt,
                                 len(bestaetigt))
                self.rot(T("k_zu_viele", n=len(defekt)), T("m_zu_viele", n=len(defekt), mib=mib, p=a.abbruch_prozent))
                return "fehler", EXIT_ZU_VIELE_DEFEKTE

            # ---- mit dem Verlauf vergleichen ----
            such_fehler = max(fehler_je_durchgang)
            sid = verlauf.suchlauf("ok", treiber, temp, belegt // MIB, fehler_je_durchgang, defekt, len(bestaetigt))
            frueher = verlauf.fruehere_ok(sid, a.verlauf)
            meldungen = bewerte_suche(such_fehler, len(defekt), mib, frueher, heap_mib)
            normalwert = normalwert_text(frueher)
            log.info(t("log_normalwert", text=normalwert))
            erster = verlauf.erster_ok()
            if erster and erster[0] != sid:
                aend = (such_fehler - erster[2]) / erster[2] * 100 if erster[2] else 0
                seit = T("v_seit", datum=erster[1][:10], f0=Z(erster[2]), s0=erster[3], f=Z(such_fehler),
                         s=len(defekt), aend=T("v_unveraendert") if abs(aend) < 1 else T("v_prozent", p=aend))
            else:
                seit = T("v_seit_erste")
            for text in meldungen:
                self.hinweis(text)

            # ---- frei geben, festhalten ----
            pruefer.freigeben()
            pruefer = None
            for c in chunks:
                if not any(c.fehler):
                    gpu.freigeben(c.buf, c.mem)
            chunks = defekt
            arbeitsspeicher_zurueckgeben()
            log.info(t("log_festgehalten", n=len(chunks), mib=mib, b=len(bestaetigt)))
            if gpu.hat_budget:
                frei, bud, use = gpu.budget()
                log.info(t("log_jetzt", use=use / MIB, frei=frei / MIB, ram=ram_text()))
            suchlaeufe, pruefungen = verlauf.zaehler()
            z.setze("gelb" if meldungen else "gruen", T("k_gesperrt", mib=mib, f=Z(such_fehler)),
                    gesperrt=T("v_gesperrt", n=len(chunks), mib=mib, nr=", ".join(str(c.nr) for c in chunks)),
                    fehler=Z(such_fehler), normalwert=normalwert, seit_erstem=seit,
                    gesucht=T("v_gesucht", zeit=jetzt()[:16], temp=temp_text(temp)),
                    letzte_pruefung=T("v_pruefung_keine"), statistik=T("v_statistik", s=suchlaeufe, w=pruefungen),
                    treiber=treiber, heap_mib=heap_mib, hinweise=list(meldungen))

            if a.nur_suchen:
                log.info(t("log_nur_suchen"))
                return "beenden", EXIT_OK

            # ---- Wächter ----
            pruefer = Pruefer(gpu, chunk_bytes, 1)
            log.info(t("log_waechter_aktiv", s=a.intervall))
            ohne_fehler = 0
            gewarnt = False
            wachstum_gemeldet = False
            letzter_fehler = None
            runde = 0
            while True:
                try:
                    befehl = self.befehle.get(timeout=a.intervall)
                except queue.Empty:
                    befehl = "pruefen"
                if befehl == "beenden":
                    log.info(t("log_beenden"))
                    return "beenden", EXIT_OK
                if befehl == "neu_suchen":
                    log.info(t("log_neu"))
                    return "neu", EXIT_OK
                if befehl == "neu_bewerten":  # Empfindlichkeit wurde im Menü geändert
                    if not gewarnt:
                        meldungen = bewerte_suche(such_fehler, len(chunks), mib, frueher, heap_mib)
                        mehr = EMPFINDLICHKEIT[EINSTELLUNG["empfindlichkeit"]]["mehr"]
                        if letzter_fehler and letzter_fehler > such_fehler * (1 + mehr):
                            meldungen.append(T("h_waechter_mehr", f=Z(letzter_fehler), sf=Z(such_fehler)))
                        z.setze("gelb" if meldungen else "gruen", hinweise=list(meldungen))
                    continue

                runde += 1
                for c in chunks:
                    c.fehler.clear()
                    c.erste_fehler = None
                fehler = pruefer.durchgang(chunks, 1000 + runde, pause_s=2.0)
                temp = nvml.temperatur()
                verlauf.waechter(sid, fehler, temp)
                je = [c.fehler[-1] for c in chunks]
                uhr = time.strftime("%H:%M")
                statistik = T("v_statistik", s=suchlaeufe, w=pruefungen + runde)
                if fehler:
                    if gewarnt:
                        log.info(t("log_wieder_im_griff", r=runde))
                    ohne_fehler = 0
                    gewarnt = False
                    log.info(t("log_im_griff", r=runde, f=fehler, je=je, temp=temp_text(temp), ram=ram_text()))
                    letzter_fehler = fehler
                    mehr = EMPFINDLICHKEIT[EINSTELLUNG["empfindlichkeit"]]["mehr"]
                    if fehler > such_fehler * (1 + mehr) and not wachstum_gemeldet:
                        wachstum_gemeldet = True
                        meldungen.append(T("h_waechter_mehr", f=Z(fehler), sf=Z(such_fehler)))
                        self.hinweis(meldungen[-1])
                    z.setze("gelb" if meldungen else "gruen", T("k_pruefung", mib=mib, uhr=uhr),
                            letzte_pruefung=T("v_pruefung", uhr=uhr, f=Z(fehler), temp=temp_text(temp)),
                            statistik=statistik, hinweise=list(meldungen))
                else:
                    ohne_fehler += 1
                    log.warning(t("log_leer", r=runde, n=ohne_fehler))
                    z.setze(letzte_pruefung=T("v_pruefung_leer", uhr=uhr, n=ohne_fehler), statistik=statistik)
                    if ohne_fehler >= a.warn_nach and not gewarnt:
                        gewarnt = True
                        log.warning(t("log_verschoben"))
                        self.rot(T("k_verschoben"), T("m_verschoben", hilfe=self.neustart_hinweis))
        except VulkanFehler as e:
            log.error("%s", e)
            alles_freigeben()
            self.rot(T("k_vk_fehler"), T("m_vk_fehler", e=e, hilfe=self.neustart_hinweis))
            return "fehler", EXIT_VULKAN
        finally:
            alles_freigeben()
            try:
                gpu.schliessen()
            except Exception as e:  # Aufräumen darf das Ergebnis nicht verdecken
                log.warning(t("log_aufraeumen", e=e))


# ---------- Systemleiste ----------
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_AKTUALISIEREN = WM_APP + 2
WM_SCHLIESSEN = WM_APP + 3
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_WARNING = 0x2
CMD_STATUS, CMD_PRUEFEN, CMD_NEU, CMD_PROTOKOLL, CMD_BEENDEN, CMD_DEUTSCH, CMD_ENGLISCH = range(1001, 1008)
CMD_EMPF = {1011: "streng", 1012: "normal", 1013: "tolerant"}


def erzeuge_symbole(ordner):
    """Erzeugt die vier Zustandssymbole als .ico: farbiger Kreis mit weißem „Pixel“."""
    from PIL import Image, ImageDraw
    farben = {"gruen": (46, 160, 67), "gelb": (232, 168, 0), "rot": (214, 40, 40), "grau": (128, 128, 128)}
    ordner.mkdir(parents=True, exist_ok=True)
    pfade = {}
    for name, rgb in farben.items():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        rand = tuple(int(v * 0.6) for v in rgb) + (255,)
        d.ellipse((2, 2, 61, 61), fill=rgb + (255,), outline=rand, width=4)
        d.rectangle((22, 22, 41, 41), fill=(255, 255, 255, 255))
        pfad = ordner / f"{name}.ico"
        img.save(pfad, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64)])
        pfade[name] = pfad
    return pfade


def _symbol_eintrag_befoerdern():
    """Sucht den Taskleisten-Eintrag von BlockThePixel und schaltet ihn sichtbar. True, wenn gefunden."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\NotifyIconSettings") as basis:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(basis, i)
            except OSError:
                return False
            i += 1
            with winreg.OpenKey(basis, name, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                werte = {}
                for v in ("ExecutablePath", "InitialTooltip"):
                    try:
                        werte[v] = str(winreg.QueryValueEx(k, v)[0])
                    except OSError:
                        werte[v] = ""
                if (werte["ExecutablePath"].lower().endswith(("pythonw.exe", "python.exe"))
                        and werte["InitialTooltip"].startswith(NAME)):
                    winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1)
                    return True


def symbol_einmalig_sichtbar_schalten():
    """Windows 11 blendet neue Symbole aus. Einmalig sichtbar schalten; danach gilt die Wahl des Nutzers."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\BlockThePixel") as eigen:
            try:
                if winreg.QueryValueEx(eigen, "SymbolSichtbarGeschaltet")[0]:
                    return
            except OSError:
                pass
            for _ in range(10):
                time.sleep(3)
                if _symbol_eintrag_befoerdern():
                    winreg.SetValueEx(eigen, "SymbolSichtbarGeschaltet", 0, winreg.REG_DWORD, 1)
                    log.info(t("log_symbol_sichtbar"))
                    return
            log.info(t("log_symbol_nicht_gefunden"))
    except OSError as e:
        log.warning(t("log_symbol_fehler", e=e))


class Systemleiste:
    """Symbol unten rechts. Läuft im Haupt-Thread mit eigener Nachrichtenschleife."""

    def __init__(self, zustand, waechter, logdatei):
        self.zustand = zustand
        self.waechter = waechter
        self.logdatei = logdatei
        groesse = (win32api.GetSystemMetrics(win32con.SM_CXSMICON), win32api.GetSystemMetrics(win32con.SM_CYSMICON))
        self.symbole = {name: win32gui.LoadImage(0, str(pfad), win32con.IMAGE_ICON, *groesse,
                                                 win32con.LR_LOADFROMFILE)
                        for name, pfad in erzeuge_symbole(Path(tempfile.gettempdir()) / NAME).items()}
        self.msg_taskleiste = win32gui.RegisterWindowMessage("TaskbarCreated")
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "BlockThePixelSystemleiste"
        wc.lpfnWndProc = {WM_TRAY: self._maus, WM_AKTUALISIEREN: self._aktualisieren,
                          WM_SCHLIESSEN: self._schliessen, win32con.WM_COMMAND: self._befehl,
                          win32con.WM_DESTROY: self._zerstoert, self.msg_taskleiste: self._taskleiste_neu}
        atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(atom, NAME, win32con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        if self._anlegen():
            threading.Thread(target=symbol_einmalig_sichtbar_schalten, daemon=True).start()
        zustand.bei_aenderung = lambda: self._poste(WM_AKTUALISIEREN)
        waechter.bei_ende = lambda: self._poste(WM_SCHLIESSEN)

    def _poste(self, nachricht):
        try:
            win32api.PostMessage(self.hwnd, nachricht, 0, 0)
        except pywintypes.error:
            pass

    def _nid(self, flags, blase=None):
        farbe, kurz, _ = self.zustand.lese()
        tip = f"{NAME}: {kurz}"[:127]
        if blase:
            return (self.hwnd, 0, flags | NIF_INFO, WM_TRAY, self.symbole[farbe], tip, blase[:255], 10000,
                    NAME, NIIF_WARNING)
        return self.hwnd, 0, flags, WM_TRAY, self.symbole[farbe], tip

    def _anlegen(self):
        """Symbol anlegen; beim Windows-Start ist die Taskleiste evtl. noch nicht bereit."""
        for _ in range(60):
            try:
                win32gui.Shell_NotifyIcon(NIM_ADD, self._nid(NIF_ICON | NIF_MESSAGE | NIF_TIP))
                return True
            except pywintypes.error:
                time.sleep(2)
        log.warning(t("log_symbol_anlegen"))
        return False

    def _aktualisieren(self, hwnd, msg, wparam, lparam):
        try:
            win32gui.Shell_NotifyIcon(NIM_MODIFY, self._nid(NIF_ICON | NIF_TIP))
            blasen = self.zustand.hole_blasen()
            if blasen:
                win32gui.Shell_NotifyIcon(NIM_MODIFY, self._nid(NIF_ICON | NIF_TIP, "\n".join(map(str, blasen))))
        except pywintypes.error as e:
            log.warning(t("log_leiste_aktualisieren", e=e))
        return 0

    def _maus(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_RBUTTONUP:
            self._menue()
        elif lparam == win32con.WM_LBUTTONDBLCLK:
            self._status_zeigen()
        return 0

    def _menue(self):
        _, kurz, _ = self.zustand.lese()
        m = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(m, win32con.MF_STRING | win32con.MF_GRAYED, 0, f"{NAME}: {kurz}")
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, CMD_STATUS, t("menu_status"))
        win32gui.AppendMenu(m, win32con.MF_STRING, CMD_PRUEFEN, t("menu_pruefen"))
        win32gui.AppendMenu(m, win32con.MF_STRING, CMD_NEU, t("menu_neu"))
        win32gui.AppendMenu(m, win32con.MF_STRING, CMD_PROTOKOLL, t("menu_protokoll"))
        sprachen = win32gui.CreatePopupMenu()
        for cmd, kuerzel, name in ((CMD_DEUTSCH, "de", "Deutsch"), (CMD_ENGLISCH, "en", "English")):
            haken = win32con.MF_CHECKED if EINSTELLUNG["sprache"] == kuerzel else win32con.MF_UNCHECKED
            win32gui.AppendMenu(sprachen, win32con.MF_STRING | haken, cmd, name)
        win32gui.AppendMenu(m, win32con.MF_POPUP, sprachen, t("menu_sprache"))
        stufen = win32gui.CreatePopupMenu()
        for cmd, stufe in CMD_EMPF.items():
            p = EMPFINDLICHKEIT[stufe]
            haken = win32con.MF_CHECKED if EINSTELLUNG["empfindlichkeit"] == stufe else win32con.MF_UNCHECKED
            win32gui.AppendMenu(stufen, win32con.MF_STRING | haken, cmd,
                                t("menu_empf_eintrag", name=t("name_" + stufe), mehr=p["mehr"] * 100,
                                  warn=p["warn_prozent"]))
        win32gui.AppendMenu(m, win32con.MF_POPUP, stufen, t("menu_empf"))
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, CMD_BEENDEN, t("menu_beenden"))
        win32gui.SetMenuDefaultItem(m, CMD_STATUS, 0)
        x, y = win32gui.GetCursorPos()
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except pywintypes.error:
            pass
        win32gui.TrackPopupMenu(m, win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN, x, y, 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)

    def _status_text(self):
        _, kurz, d = self.zustand.lese()
        zeilen = [f"{NAME} {VERSION}", PROJEKT_URL, "", f"{t('s_zustand')}: {kurz}"]
        for schluessel, titel in (("gesperrt", "s_gesperrt"), ("fehler", "s_fehler"), ("normalwert", "s_normal"),
                                  ("seit_erstem", "s_seit"), ("gesucht", "s_gesucht"),
                                  ("letzte_pruefung", "s_pruefung"), ("statistik", "s_verlauf"),
                                  ("treiber", "s_treiber")):
            if d.get(schluessel) is not None:
                zeilen.append(f"{t(titel)}: {d[schluessel]}")
        stufe = EINSTELLUNG["empfindlichkeit"]
        p = EMPFINDLICHKEIT[stufe]
        if d.get("heap_mib"):
            zeilen.append(f"{t('s_empf')}: " + t("v_empf", name=t("name_" + stufe), mehr=p["mehr"] * 100,
                                                  warn=p["warn_prozent"], mib=d["heap_mib"] * p["warn_prozent"] / 100))
        if d.get("hinweise"):
            zeilen += ["", f"{t('s_hinweise')}:"] + [f"• {h}" for h in d["hinweise"]]
        return "\n".join(zeilen)

    def _status_zeigen(self):
        win32api.MessageBox(self.hwnd, self._status_text(), NAME, win32con.MB_OK | win32con.MB_ICONINFORMATION)

    def _sprache_setzen(self, sprache):
        EINSTELLUNG["sprache"] = sprache
        speichere_einstellung("Sprache", sprache)
        log.info(t("log_sprache"))
        self._aktualisieren(self.hwnd, 0, 0, 0)

    def _empfindlichkeit_setzen(self, stufe):
        EINSTELLUNG["empfindlichkeit"] = stufe
        speichere_einstellung("Empfindlichkeit", stufe)
        log.info(t("log_empf", name=t("name_" + stufe)))
        self.waechter.befehle.put("neu_bewerten")

    def _befehl(self, hwnd, msg, wparam, lparam):
        cmd = win32api.LOWORD(wparam)
        if cmd == CMD_STATUS:
            self._status_zeigen()
        elif cmd == CMD_PRUEFEN:
            self.waechter.befehle.put("pruefen")
        elif cmd == CMD_NEU:
            if win32api.MessageBox(self.hwnd, t("frage_neu"), NAME,
                                   win32con.MB_YESNO | win32con.MB_ICONQUESTION) == win32con.IDYES:
                self.waechter.befehle.put("neu_suchen")
        elif cmd == CMD_PROTOKOLL:
            os.startfile(self.logdatei)
        elif cmd == CMD_DEUTSCH:
            self._sprache_setzen("de")
        elif cmd == CMD_ENGLISCH:
            self._sprache_setzen("en")
        elif cmd in CMD_EMPF:
            self._empfindlichkeit_setzen(CMD_EMPF[cmd])
        elif cmd == CMD_BEENDEN:
            if win32api.MessageBox(self.hwnd, t("frage_beenden"), NAME,
                                   win32con.MB_YESNO | win32con.MB_ICONWARNING) == win32con.IDYES:
                self.waechter.befehle.put("beenden")
        return 0

    def _schliessen(self, hwnd, msg, wparam, lparam):
        try:
            win32gui.Shell_NotifyIcon(NIM_DELETE, (self.hwnd, 0))
        except pywintypes.error:
            pass
        win32gui.DestroyWindow(self.hwnd)
        return 0

    def _zerstoert(self, hwnd, msg, wparam, lparam):
        win32gui.PostQuitMessage(0)
        return 0

    def _taskleiste_neu(self, hwnd, msg, wparam, lparam):
        self._anlegen()  # Explorer wurde neu gestartet
        return 0

    def laufen(self):
        win32gui.PumpMessages()


# ---------- Hauptprogramm ----------
def richte_logging_ein(logdatei):
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(logdatei, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stdout is not None:  # pythonw hat keine Konsole
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def sprache_aus_befehlszeile(argv):
    """--sprache/--language vorab lesen, damit schon die Hilfe in der gewünschten Sprache erscheint."""
    for i, arg in enumerate(argv):
        for option in ("--sprache", "--language"):
            if arg == option and i + 1 < len(argv):
                return argv[i + 1] if argv[i + 1] in ("de", "en") else None
            if arg.startswith(option + "="):
                wert = arg.split("=", 1)[1]
                return wert if wert in ("de", "en") else None
    return None


def empfindlichkeit_wert(text):
    """argparse-Typ: streng|normal|tolerant, englisch auch strict."""
    stufe = {"strict": "streng"}.get(text.lower(), text.lower())
    if stufe not in EMPFINDLICHKEIT:
        raise argparse.ArgumentTypeError(t("cli_empf_ungueltig", s=text))
    return stufe


def main():
    EINSTELLUNG["sprache"] = (sprache_aus_befehlszeile(sys.argv[1:]) or lese_einstellung("Sprache", ("de", "en"))
                              or systemsprache())
    EINSTELLUNG["empfindlichkeit"] = lese_einstellung("Empfindlichkeit", tuple(EMPFINDLICHKEIT)) or "normal"

    ap = argparse.ArgumentParser(description=t("cli_beschreibung"))
    ap.add_argument("--chunk-mib", type=int, default=8, metavar="MIB", help=t("cli_chunk"))
    ap.add_argument("--durchgaenge", "--passes", type=int, default=4, metavar="N", help=t("cli_durchgaenge"))
    ap.add_argument("--reserve-mib", type=int, default=256, metavar="MIB", help=t("cli_reserve"))
    ap.add_argument("--abbruch-prozent", "--abort-percent", type=float, default=10.0, metavar="P",
                    help=t("cli_abbruch"))
    ap.add_argument("--intervall", "--interval", type=int, default=300, metavar="S", help=t("cli_intervall"))
    ap.add_argument("--warn-nach", "--warn-after", type=int, default=2, metavar="N", help=t("cli_warn_nach"))
    ap.add_argument("--verlauf", "--history", type=int, default=10, metavar="N", help=t("cli_verlauf"))
    ap.add_argument("--empfindlichkeit", "--sensitivity", type=empfindlichkeit_wert, metavar="STUFE",
                    help=t("cli_empfindlichkeit"))
    ap.add_argument("--nur-suchen", "--search-only", action="store_true", help=t("cli_nur_suchen"))
    ap.add_argument("--meldungen", "--dialogs", action="store_true", help=t("cli_meldungen"))
    ap.add_argument("--ohne-symbol", "--no-icon", action="store_true", help=t("cli_ohne_symbol"))
    ap.add_argument("--sprache", "--language", choices=("de", "en"), help=t("cli_sprache"))
    args = ap.parse_args()
    if args.sprache:
        EINSTELLUNG["sprache"] = args.sprache
    if args.empfindlichkeit:
        EINSTELLUNG["empfindlichkeit"] = args.empfindlichkeit

    ordner = Path(__file__).resolve().parent
    richte_logging_ein(ordner / "blockthepixel.log")
    melde = Melder(args.meldungen)

    mutex = einzige_instanz()
    if mutex is None:
        log.info(t("log_laeuft_schon"))
        return EXIT_LAEUFT_SCHON
    log.info(t("log_start", v=VERSION))

    mit_symbol = not (args.ohne_symbol or args.nur_suchen)
    if mit_symbol and win32gui is None:
        log.warning(t("log_pywin32"))
        mit_symbol = False
    zustand = Zustand()
    waechter = Waechter(args, ordner, zustand, melde, mit_symbol)
    leiste = None
    if mit_symbol:
        try:
            leiste = Systemleiste(zustand, waechter, ordner / "blockthepixel.log")
        except Exception:
            log.exception(t("log_leiste_fehlt"))
            waechter.mit_symbol = False
    waechter.start()
    if leiste:
        leiste.laufen()
        waechter.join(timeout=30)
    else:
        try:
            while waechter.is_alive():
                waechter.join(timeout=0.5)
        except KeyboardInterrupt:
            log.info(t("log_strg_c"))
            waechter.befehle.put("beenden")
            waechter.join(timeout=30)
    log.info(t("log_ende", code=waechter.exit_code))
    return waechter.exit_code


if __name__ == "__main__":
    sys.exit(main())
