# FFmpeg Tool Studio

Desktop-Oberfläche für FFmpeg unter Windows: **52 Funktionen in 12 Kategorien**, mit GPU-Encoding (NVIDIA NVENC, Intel QuickSync, AMD AMF), Warteschlange, Stapelverarbeitung, Presets und Drag & Drop.

![Icon](app_icon_preview.png)

## Download

Fertige Versionen findest du unter **Releases**:

- `FFmpeg_Tool_Studio_Setup_x.y.z.exe`: Installer mit Startmenü- und optionaler Desktop-Verknüpfung
- `FFmpeg.Tool.Studio.exe`: portable Einzeldatei, startet ohne Installation

FFmpeg ist in beiden Varianten bereits enthalten. Es muss nichts zusätzlich installiert werden.

## Funktionen

| Kategorie | Funktionen |
|---|---|
| Schneiden & Zusammenfügen | Trimmen, Zusammenfügen (verlustfrei oder neu kodiert), Szenenwechsel erkennen & aufteilen, Übergänge (23 xfade-Effekte) |
| Bildgröße & Geometrie | Skalieren, Zuschneiden, Drehen/Spiegeln, 16:9 → 9:16 mit Blur-Rand |
| Farbe & Bildqualität | Farbfilter & Effekte, Entrauschen (hqdn3d, nlmeans, atadenoise) |
| Zeit & Bildrate | Geschwindigkeit, flüssige Zeitlupe per Zwischenbildberechnung, Standbild einfrieren |
| Überlagerungen & Text | Logo/Wasserzeichen, Text, Timecode, Untertitel einbrennen (SRT/ASS/VTT) |
| Kompression & Export | CRF H.264/H.265, Zielgröße in MB (2-Pass), ProRes/DNxHR, Plattform-Presets (YouTube, Instagram, TikTok, WhatsApp …), Remuxing |
| Audio | Tonspur extrahieren, stummschalten, Ton ersetzen, Musik mischen mit Ducking, Ein-/Ausblenden, Lippensynchronität, Tonhöhe/Hall/EQ/Lautheit |
| Bilder & GIF | Einzelbilder, GIF, Thumbnail, Video aus Bild + Audio, Contact Sheet, animiertes WebP/APNG, Bildformate umwandeln |
| Analyse & Info | Medieninfo, Wellenform/Spektrogramm, Qualitätsvergleich (PSNR/SSIM/VMAF), Schwarzbild/Stille finden, Fehlerprüfung |
| Metadaten & Spuren | Metadaten bearbeiten/entfernen (inkl. GPS), Cover einbetten, Kapitel, Spurauswahl, Drehung ohne Neukodierung |
| Aufnahme & Streaming | Bildschirm- und Webcam-Aufnahme, Stream speichern (m3u8), RTMP-Streaming (YouTube/Twitch), HLS/DASH erzeugen |
| Experten-Modus | Eigener FFmpeg-Befehl mit Platzhaltern `{input}` / `{output}` |

**Komfort:** Fortschritt mit Restzeit, Warteschlange, Stapel (mehrere Dateien oder ganzer Ordner), Drag & Drop, eigene Presets pro Funktion, Abbrechen und sauberes Stoppen von Aufnahmen.

## Aus dem Quellcode starten

Voraussetzungen: Python 3.10+, FFmpeg und ffprobe im PATH oder als `ffmpeg.exe`/`ffprobe.exe` neben `main.py`.

```powershell
pip install -r requirements.txt
python main.py
```

## EXE und Installer bauen

Zusätzlich wird [Inno Setup 6](https://jrsoftware.org/isinfo.php) benötigt (`winget install JRSoftware.InnoSetup`).

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# optional mit eigenem FFmpeg:  -FFmpegPath C:\pfad\zu\ffmpeg.exe
```

Ergebnis:

- `dist\FFmpeg Tool Studio.exe`: portable Version mit eingebettetem FFmpeg
- `installer_output\FFmpeg_Tool_Studio_Setup_*.exe`: Installer

## Projektaufbau

```
main.py              Hauptfenster (Auswahl, Warteschlange, Fortschritt, Presets, Drag & Drop)
ui/option_fields.py  Eingabefelder für alle Optionsarten
core/                FFmpeg-Ausführung, ffprobe, GPU-Erkennung, Hilfsfunktionen
modules/             Eine Datei pro Kategorie, jedes Modul beschreibt seine Optionen selbst
build.ps1            Baut EXE + Installer
installer.iss        Inno-Setup-Skript
```

Für ein **neues Modul** leitest du in der passenden Datei unter `modules/` eine Klasse von `BaseModule` ab, definierst `options_schema` und `build_command()` und trägst sie in die `MODULES`-Liste ein. Die Oberfläche erzeugt die Eingabefelder automatisch.

Presets und Einstellungen liegen unter `%APPDATA%\FFmpegToolStudio`.

## Lizenzhinweis zu FFmpeg

Die fertigen EXE-Dateien enthalten FFmpeg und ffprobe in einem GPL-Build. FFmpeg ist ein Projekt von [ffmpeg.org](https://ffmpeg.org) und steht unter der GPL. Den Quellcode gibt es unter <https://ffmpeg.org/download.html>.
