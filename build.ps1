# Baut FFmpeg Tool Studio:
#   1) dist\FFmpeg Tool Studio.exe          – portable Einzel-EXE mit eingebettetem FFmpeg
#   2) dist\FFmpeg Tool Studio\             – Ordner-Version (schneller Start), Basis für den Installer
#   3) installer_output\FFmpeg_Tool_Studio_Setup_*.exe – Installer mit Startmenü-/Desktop-Verknüpfung
#
# Aufruf:  powershell -ExecutionPolicy Bypass -File build.ps1 [-FFmpegPath C:\pfad\ffmpeg.exe]
param([string]$FFmpegPath = "")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Name = "FFmpeg Tool Studio"

if (-not $FFmpegPath) {
    # Echte ffmpeg.exe finden (WinGet-"Links" sind nur Verknüpfungen, daher Packages-Ordner bevorzugen)
    # Neuesten Build nehmen, der auch ffprobe.exe mitbringt (wird für Dauer/Infos gebraucht)
    $FFmpegPath = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.DirectoryName "ffprobe.exe") } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $FFmpegPath) { $FFmpegPath = (Get-Command ffmpeg -ErrorAction Stop).Source }
}
$FFprobePath = Join-Path (Split-Path $FFmpegPath) "ffprobe.exe"
if (-not (Test-Path $FFprobePath)) { throw "ffprobe.exe nicht gefunden neben $FFmpegPath" }
Write-Host "Verwende FFmpeg:  $FFmpegPath"
Write-Host "Verwende FFprobe: $FFprobePath"

python -m pip install --quiet --upgrade pyinstaller customtkinter tkinterdnd2
if ($LASTEXITCODE) { throw "pip fehlgeschlagen" }

$common = @("--noconfirm", "--clean", "--windowed", "--name", $Name, "--icon", "app.ico",
            "--add-data", "app.ico;.", "--add-binary", "$FFmpegPath;.", "--add-binary", "$FFprobePath;.",
            "--collect-data", "customtkinter", "--collect-all", "tkinterdnd2")

Write-Host "`n=== 1/3 Portable Einzel-EXE ==="
python -m PyInstaller @common --onefile --workpath build\onefile main.py
if ($LASTEXITCODE) { throw "PyInstaller (onefile) fehlgeschlagen" }

Write-Host "`n=== 2/3 Ordner-Version fuer den Installer ==="
python -m PyInstaller @common --onedir --workpath build\onedir main.py
if ($LASTEXITCODE) { throw "PyInstaller (onedir) fehlgeschlagen" }

Write-Host "`n=== 3/3 Installer ==="
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup nicht gefunden. Installieren mit: winget install JRSoftware.InnoSetup" }
& $iscc /Q installer.iss
if ($LASTEXITCODE) { throw "Inno Setup fehlgeschlagen" }

Write-Host "`nFertig:"
Get-Item "dist\$Name.exe", "installer_output\*.exe" | Format-Table Name, @{n="MB"; e={[math]::Round($_.Length / 1MB, 1)}}
