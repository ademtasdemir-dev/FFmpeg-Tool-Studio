from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, crf_option

CAT = "Farbe & Bildqualität"


class VisualEffectsModule(BaseModule):
    name = "Farbfilter & Bildeffekte"
    category = CAT
    description = "Schwarz-Weiß, Sepia, Weichzeichner, Schärfen und mehr."
    output_suffix = "_effekt"
    options_schema = [
        OptionSpec("effect", "Effekt", "choice", "hue=s=0", choices={
            "Schwarz-Weiß": "hue=s=0",
            "Sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
            "Weichzeichner (Blur)": "boxblur=10:1",
            "Schärfen": "unsharp=5:5:1.0",
            "Negativ": "negate",
            "Kräftigere Farben": "eq=saturation=1.5:contrast=1.1",
            "Heller": "eq=brightness=0.08:gamma=1.1",
            "Vignette": "vignette=PI/4",
            "Filmkorn": "noise=alls=12:allf=t",
            "Eigener Filter": "custom",
        }),
        OptionSpec("custom", "Eigener -vf Filter (nur bei „Eigener Filter“)", "text", "eq=brightness=0.06"),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        vf = o["custom"] if o["effect"] == "custom" else o["effect"]
        return ["-y", "-i", inp, "-vf", vf] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


class DenoiseModule(BaseModule):
    name = "Rauschen entfernen (Entrauschen)"
    category = CAT
    description = "Reduziert Bildrauschen, z. B. bei Aufnahmen bei wenig Licht. Optional auch Tonrauschen."
    output_suffix = "_entrauscht"
    options_schema = [
        OptionSpec("method", "Verfahren", "choice", "hqdn3d=4:3:6:4.5", choices={
            "hqdn3d leicht (schnell)": "hqdn3d=2:1.5:3:2.25",
            "hqdn3d mittel (schnell)": "hqdn3d=4:3:6:4.5",
            "hqdn3d stark (schnell)": "hqdn3d=8:6:12:9",
            "nlmeans (beste Qualität, langsam)": "nlmeans=s=3:p=7:r=15",
            "nlmeans stark (sehr langsam)": "nlmeans=s=6:p=7:r=15",
            "atadenoise (zeitlich, für Videorauschen)": "atadenoise",
        }),
        OptionSpec("audio", "Auch Tonrauschen reduzieren (Rauschen/Brummen)", "bool", False),
        crf_option(18),
    ]

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-i", inp, "-vf", o["method"]] + fu.x264(o["crf"])
        if o["audio"] and ctx.has_audio(inp):
            cmd += ["-af", "afftdn=nf=-25", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]
        return cmd + [out]


MODULES: List[BaseModule] = [VisualEffectsModule(), DenoiseModule()]
