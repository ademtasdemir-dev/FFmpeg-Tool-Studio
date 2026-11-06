"""Hilfsfunktionen zum Bauen von FFmpeg-Filtern (Escaping, Zeiten, Positionen, Codecs)."""
import os
import re
from typing import List

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".mts",
             ".m2ts", ".3gp", ".ogv", ".vob", ".mxf", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ac3", ".mka"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif", ".heic"}

FILETYPES = {
    "video": [("Videos", " ".join("*" + e for e in sorted(VIDEO_EXT))), ("Alle Dateien", "*.*")],
    "audio": [("Audio", " ".join("*" + e for e in sorted(AUDIO_EXT))), ("Alle Dateien", "*.*")],
    "media": [("Video & Audio", " ".join("*" + e for e in sorted(VIDEO_EXT | AUDIO_EXT))), ("Alle Dateien", "*.*")],
    "image": [("Bilder", " ".join("*" + e for e in sorted(IMAGE_EXT))), ("Alle Dateien", "*.*")],
    "subtitle": [("Untertitel", "*.srt *.ass *.ssa *.vtt"), ("Alle Dateien", "*.*")],
    "any": [("Alle Dateien", "*.*")],
}
KIND_EXTS = {"video": VIDEO_EXT, "audio": AUDIO_EXT, "media": VIDEO_EXT | AUDIO_EXT, "image": IMAGE_EXT}

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONTS = {
    "Arial": "arial.ttf",
    "Arial Fett": "arialbd.ttf",
    "Segoe UI": "segoeui.ttf",
    "Segoe UI Fett": "segoeuib.ttf",
    "Impact": "impact.ttf",
    "Verdana": "verdana.ttf",
    "Georgia": "georgia.ttf",
    "Times New Roman": "times.ttf",
    "Consolas": "consola.ttf",
    "Comic Sans MS": "comic.ttf",
}

# Positionen für overlay (W/H = Video, w/h = Logo) – {m} = Randabstand
OVERLAY_POS = {
    "Unten rechts": ("W-w-{m}", "H-h-{m}"),
    "Unten links": ("{m}", "H-h-{m}"),
    "Oben rechts": ("W-w-{m}", "{m}"),
    "Oben links": ("{m}", "{m}"),
    "Mitte": ("(W-w)/2", "(H-h)/2"),
    "Oben Mitte": ("(W-w)/2", "{m}"),
    "Unten Mitte": ("(W-w)/2", "H-h-{m}"),
}
# Positionen für drawtext (w/h = Video, text_w/text_h = Text)
TEXT_POS = {
    "Unten Mitte": ("(w-text_w)/2", "h-text_h-{m}"),
    "Oben Mitte": ("(w-text_w)/2", "{m}"),
    "Mitte": ("(w-text_w)/2", "(h-text_h)/2"),
    "Unten links": ("{m}", "h-text_h-{m}"),
    "Unten rechts": ("w-text_w-{m}", "h-text_h-{m}"),
    "Oben links": ("{m}", "{m}"),
    "Oben rechts": ("w-text_w-{m}", "{m}"),
}


def pos(table: dict, label: str, margin: int):
    x, y = table[label]
    return x.format(m=margin), y.format(m=margin)


def fpath(path: str) -> str:
    """Pfad für Filter-Optionen (fontfile=, subtitles=, textfile=) korrekt escapen."""
    p = os.path.abspath(path).replace("\\", "/").replace(":", "\\:")
    return "'" + p.replace("'", "'\\\\\\''") + "'"


def font_file(label: str) -> str:
    path = os.path.join(FONT_DIR, FONTS.get(label, "arial.ttf"))
    if not os.path.isfile(path):
        path = os.path.join(FONT_DIR, "arial.ttf")
    return path


def fcolor(hex_color: str, alpha: float = None) -> str:
    c = hex_color.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFFFFF"
    return f"0x{c}" + (f"@{alpha:g}" if alpha is not None else "")


def parse_time(text) -> float:
    """'90', '1:30', '00:01:30.5' -> Sekunden."""
    s = str(text).strip().replace(",", ".")
    if not s:
        raise ValueError("leere Zeitangabe")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"ungültige Zeit: {text}")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError(f"negative Zeit: {text}")
    return total


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def atempo_chain(speed: float) -> str:
    """atempo akzeptiert pro Filter nur 0.5–2.0 zuverlässig, daher bei Bedarf verketten."""
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    parts.append(f"atempo={speed:.5f}")
    return ",".join(parts)


def audio_codec_for(path: str, bitrate: str = "192k") -> List[str]:
    """Passender Audio-Codec je nach Endung der Ausgabedatei."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mp3":
        return ["-c:a", "libmp3lame", "-b:a", bitrate]
    if ext in (".wav", ".aiff", ".aif"):
        return ["-c:a", "pcm_s16le"]
    if ext == ".flac":
        return ["-c:a", "flac"]
    if ext in (".ogg", ".oga"):
        return ["-c:a", "libvorbis", "-q:a", "6"]
    if ext in (".opus", ".webm"):
        return ["-c:a", "libopus", "-b:a", bitrate]
    return ["-c:a", "aac", "-b:a", bitrate]


def x264(crf, preset: str = "medium") -> List[str]:
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p"]
