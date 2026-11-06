from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError

CAT = "Bilder & GIF"


class ExtractFramesModule(BaseModule):
    name = "Video in Einzelbilder zerlegen"
    category = CAT
    description = "Speichert Bilder aus dem Video als Bildsequenz."
    output_suffix = "_%04d"
    options_schema = [
        OptionSpec("fps", "Bilder pro Sekunde", "float", 1, min_value=0.01, max_value=240),
        OptionSpec("format", "Bildformat", "choice", "jpg", choices={"JPG": "jpg", "PNG": "png", "WebP": "webp"}),
    ]

    def suggested_ext(self, o):
        return "." + o["format"]

    def build_command(self, inp, out, o, ctx):
        return ["-y", "-i", inp, "-vf", f"fps={o['fps']}", "-q:v", "2", out]


class GenerateGifModule(BaseModule):
    name = "GIF in hoher Qualität erstellen"
    category = CAT
    description = "Erzeugt ein GIF mit optimierter Farbpalette."
    output_ext = ".gif"
    options_schema = [
        OptionSpec("fps", "Bilder pro Sekunde", "int", 15, min_value=1, max_value=60),
        OptionSpec("width", "Breite in Pixeln", "int", 480, min_value=16, max_value=3840),
        OptionSpec("start", "Startzeit (hh:mm:ss)", "text", "00:00:00"),
        OptionSpec("duration", "Dauer in Sekunden (0 = bis Ende)", "float", 5, min_value=0),
    ]

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"]) or ctx.duration_or_none(inp)

    def build_command(self, inp, out, o, ctx):
        vf = (f"fps={o['fps']},scale={o['width']}:-1:flags=lanczos,split[s0][s1];"
              f"[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5")
        cmd = ["-y", "-ss", o["start"], "-i", inp]
        if float(o["duration"]) > 0:
            cmd += ["-t", str(o["duration"])]
        return cmd + ["-vf", vf, "-loop", "0", out]


class ThumbnailModule(BaseModule):
    name = "Thumbnail / Vorschaubild erzeugen"
    category = CAT
    description = "Speichert ein einzelnes Bild aus dem Video."
    output_ext = ".jpg"
    output_suffix = "_thumbnail"
    options_schema = [
        OptionSpec("time", "Zeitpunkt (hh:mm:ss)", "text", "00:00:03"),
        OptionSpec("format", "Bildformat", "choice", "jpg", choices={"JPG": "jpg", "PNG": "png", "WebP": "webp"}),
    ]

    def suggested_ext(self, o):
        return "." + o["format"]

    def build_command(self, inp, out, o, ctx):
        return ["-y", "-ss", o["time"], "-i", inp, "-frames:v", "1", "-q:v", "2", "-update", "1", out]


class ImageAudioVideoModule(BaseModule):
    name = "Video aus Bild + Audio (z. B. Musik für YouTube)"
    category = CAT
    description = "Erstellt ein Video aus einem Standbild und einer Audiodatei."
    input_kind = "image"
    output_ext = ".mp4"
    output_suffix = "_video"
    options_schema = [
        OptionSpec("audio", "Audiodatei", "file", "", filetypes="audio"),
        OptionSpec("resolution", "Videogröße", "choice", "1920:1080", choices={
            "1920 × 1080 (YouTube)": "1920:1080", "1080 × 1080 (Quadrat)": "1080:1080",
            "1080 × 1920 (Hochformat)": "1080:1920", "Bildgröße beibehalten": "",
        }),
        OptionSpec("background", "Hintergrundfarbe (Rand)", "color", "#000000"),
    ]

    def expected_duration(self, inp, o, ctx):
        return ctx.duration_or_none(o["audio"])

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(o["audio"])
        if o["resolution"]:
            w, h = o["resolution"].split(":")
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={fu.fcolor(o['background'])},setsar=1,format=yuv420p")
        else:
            vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p"
        return ["-y", "-loop", "1", "-framerate", "25", "-i", inp, "-i", o["audio"], "-map", "0:v", "-map", "1:a",
                "-vf", vf, "-c:v", "libx264", "-tune", "stillimage", "-crf", "20", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", "-movflags", "+faststart", out]


class ContactSheetModule(BaseModule):
    name = "Vorschau-Kachel / Contact Sheet"
    category = CAT
    description = "Viele gleichmäßig verteilte Vorschaubilder in einem einzigen Bild."
    output_ext = ".jpg"
    output_suffix = "_uebersicht"
    options_schema = [
        OptionSpec("cols", "Spalten", "int", 4, min_value=1, max_value=20),
        OptionSpec("rows", "Zeilen", "int", 5, min_value=1, max_value=30),
        OptionSpec("tile_w", "Breite eines Bildes (Pixel)", "int", 400, min_value=64, max_value=1920),
        OptionSpec("timestamps", "Zeitstempel einblenden", "bool", True),
        OptionSpec("format", "Bildformat", "choice", "jpg", choices={"JPG": "jpg", "PNG": "png"}),
    ]

    def suggested_ext(self, o):
        return "." + o["format"]

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        n = int(o["cols"]) * int(o["rows"])
        vf = f"fps={n}/{dur:.3f},scale={o['tile_w']}:-2"
        if o["timestamps"]:
            size = max(12, int(o["tile_w"]) // 16)
            vf += (f",drawtext=fontfile={fu.fpath(fu.font_file('Consolas'))}:text='%{{pts\\:hms}}'"
                   f":fontsize={size}:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=4:x=w-text_w-6:y=h-text_h-6")
        vf += f",tile={o['cols']}x{o['rows']}:padding=4:margin=4:color=0x202020"
        return ["-y", "-i", inp, "-vf", vf, "-frames:v", "1", "-q:v", "2", "-update", "1", out]


class AnimatedImageModule(BaseModule):
    name = "Animiertes WebP / APNG"
    category = CAT
    description = "Moderne GIF-Alternativen: kleiner (WebP) oder verlustfrei mit Transparenz (APNG)."
    output_suffix = "_animiert"
    options_schema = [
        OptionSpec("format", "Format", "choice", "webp", choices={"Animiertes WebP": "webp", "APNG": "apng"}),
        OptionSpec("fps", "Bilder pro Sekunde", "int", 15, min_value=1, max_value=60),
        OptionSpec("width", "Breite in Pixeln", "int", 480, min_value=16, max_value=3840),
        OptionSpec("start", "Startzeit (hh:mm:ss)", "text", "00:00:00"),
        OptionSpec("duration", "Dauer in Sekunden (0 = bis Ende)", "float", 5, min_value=0),
        OptionSpec("quality", "Qualität (nur WebP, 0–100)", "int", 75, min_value=0, max_value=100),
        OptionSpec("loop", "Endlos wiederholen", "bool", True),
    ]

    def suggested_ext(self, o):
        return ".webp" if o["format"] == "webp" else ".png"

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"]) or ctx.duration_or_none(inp)

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-ss", o["start"], "-i", inp]
        if float(o["duration"]) > 0:
            cmd += ["-t", str(o["duration"])]
        vf = f"fps={o['fps']},scale={o['width']}:-1:flags=lanczos"
        if o["format"] == "webp":
            return cmd + ["-vf", vf, "-c:v", "libwebp_anim", "-quality", str(o["quality"]),
                          "-loop", "0" if o["loop"] else "1", "-an", out]
        return cmd + ["-vf", vf, "-c:v", "apng", "-plays", "0" if o["loop"] else "1", "-f", "apng", "-an", out]


class ImageConvertModule(BaseModule):
    name = "Bildformat umwandeln (PNG / JPG / WebP / …)"
    category = CAT
    description = "Wandelt Bilder um, optional mit neuer Breite. Tipp: Mit „Stapel“ ganze Ordner umwandeln."
    input_kind = "image"
    output_suffix = ""
    options_schema = [
        OptionSpec("format", "Zielformat", "choice", "jpg", choices={
            "JPG": "jpg", "PNG": "png", "WebP": "webp", "BMP": "bmp", "TIFF": "tiff",
        }),
        OptionSpec("quality", "Qualität (JPG/WebP, 1–100)", "int", 90, min_value=1, max_value=100),
        OptionSpec("width", "Neue Breite in Pixeln (0 = unverändert)", "int", 0, min_value=0, max_value=20000),
    ]

    def suggested_ext(self, o):
        return "." + o["format"]

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-i", inp]
        if int(o["width"]) > 0:
            cmd += ["-vf", f"scale={o['width']}:-1:flags=lanczos"]
        q = int(o["quality"])
        f = o["format"]
        if f == "jpg":
            cmd += ["-q:v", str(round(31 - q / 100 * 29))]
        elif f == "webp":
            cmd += ["-c:v", "libwebp", "-quality", str(q)]
        elif f == "png":
            cmd += ["-compression_level", "6"]
        return cmd + ["-frames:v", "1", "-update", "1", out]


MODULES: List[BaseModule] = [ExtractFramesModule(), GenerateGifModule(), ThumbnailModule(), ImageAudioVideoModule(),
                             ContactSheetModule(), AnimatedImageModule(), ImageConvertModule()]
