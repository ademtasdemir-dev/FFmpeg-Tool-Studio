from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, crf_option

CAT = "Bildgröße & Geometrie"


class ScaleModule(BaseModule):
    name = "Auflösung ändern (Skalieren)"
    category = CAT
    description = "Ändert die Auflösung, das Seitenverhältnis bleibt erhalten."
    output_suffix = "_skaliert"
    options_schema = [
        OptionSpec("resolution", "Zielauflösung", "choice", "1280:-2", choices={
            "2160p (3840 breit)": "3840:-2", "1440p (2560 breit)": "2560:-2", "1080p (1920 breit)": "1920:-2",
            "720p (1280 breit)": "1280:-2", "480p (854 breit)": "854:-2", "360p (640 breit)": "640:-2",
            "Halbe Größe": "trunc(iw/4)*2:-2", "Hochformat 1080 breit": "1080:-2", "Hochformat 720 breit": "720:-2",
        }),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        return ["-y", "-i", inp, "-vf", f"scale={o['resolution']}:flags=lanczos"] + fu.x264(o["crf"]) + \
               ["-c:a", "copy", out]


class CropModule(BaseModule):
    name = "Bildausschnitt zuschneiden (Crop)"
    category = CAT
    description = "Schneidet einen Bildausschnitt aus (Mitte) oder entfernt schwarze Balken."
    output_suffix = "_crop"
    options_schema = [
        OptionSpec("preset", "Ausschnitt", "choice", "square", choices={
            "Quadrat 1:1 (Mitte)": "square", "Hochformat 9:16 (Mitte)": "portrait",
            "Instagram 4:5 (Mitte)": "insta", "Querformat 16:9 (Mitte)": "wide",
            "Eigener crop-Filter": "custom",
        }),
        OptionSpec("custom", "Eigener Filter (nur bei „Eigener crop-Filter“)", "text", "crop=iw/2:ih/2"),
        crf_option(19),
    ]

    PRESETS = {
        "square": "crop=min(iw\\,ih):min(iw\\,ih):(iw-ow)/2:(ih-oh)/2",
        "portrait": "crop=trunc(ih*9/16/2)*2:ih:(iw-ow)/2:0",
        "insta": "crop=trunc(ih*4/5/2)*2:ih:(iw-ow)/2:0",
        "wide": "crop=iw:trunc(iw*9/16/2)*2:0:(ih-oh)/2",
    }

    def build_command(self, inp, out, o, ctx):
        vf = o["custom"] if o["preset"] == "custom" else self.PRESETS[o["preset"]]
        return ["-y", "-i", inp, "-vf", vf] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


class RotateFlipModule(BaseModule):
    name = "Video rotieren & spiegeln"
    category = CAT
    description = "Dreht oder spiegelt das Bild (mit Neukodierung). Ohne Neukodierung: Kategorie Metadaten."
    output_suffix = "_gedreht"
    options_schema = [
        OptionSpec("vf", "Transformation", "choice", "transpose=1", choices={
            "90° im Uhrzeigersinn": "transpose=1", "90° gegen den Uhrzeigersinn": "transpose=2",
            "180°": "transpose=1,transpose=1", "Horizontal spiegeln": "hflip", "Vertikal spiegeln": "vflip",
        }),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        return ["-y", "-i", inp, "-vf", o["vf"]] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


class SocialAutoBlurModule(BaseModule):
    name = "16:9 zu 9:16 mit Blur-Rand"
    category = CAT
    description = "Querformat-Video als Hochformat mit unscharfem Hintergrund (Reels, TikTok, Shorts)."
    output_suffix = "_9x16"
    options_schema = [
        OptionSpec("height", "Zielgröße", "choice", 1920, choices={
            "1080 × 1920 (Full HD)": 1920, "720 × 1280 (HD)": 1280,
        }),
        OptionSpec("blur", "Stärke des Hintergrund-Blurs", "int", 35, min_value=1, max_value=100),
        crf_option(21),
    ]

    def build_command(self, inp, out, o, ctx):
        h = int(o["height"])
        w = h * 9 // 16
        fc = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},boxblur={o['blur']}:5[bg];"
              f"[b]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
        return ["-y", "-i", inp, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?"] + fu.x264(o["crf"]) + \
               ["-c:a", "copy", out]


MODULES: List[BaseModule] = [ScaleModule(), CropModule(), RotateFlipModule(), SocialAutoBlurModule()]
