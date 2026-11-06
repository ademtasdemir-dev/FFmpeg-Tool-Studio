import os
from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError, crf_option

CAT = "Überlagerungen & Text"

POSITIONS = {k: k for k in fu.OVERLAY_POS}
TEXT_POSITIONS = {k: k for k in fu.TEXT_POS}
FONT_CHOICES = {k: k for k in fu.FONTS}


def _enable(start: float, end: float) -> str:
    """Zeitbereich für Filter (end = 0 bedeutet bis zum Ende)."""
    if end and end > start:
        return f":enable='between(t,{start:g},{end:g})'"
    if start > 0:
        return f":enable='gte(t,{start:g})'"
    return ""


class WatermarkModule(BaseModule):
    name = "Wasserzeichen / Logo einblenden"
    category = CAT
    description = "Blendet ein Bild (PNG mit Transparenz empfohlen) über dem Video ein."
    output_suffix = "_logo"
    options_schema = [
        OptionSpec("logo", "Logo / Bild", "file", "", filetypes="image"),
        OptionSpec("position", "Position", "choice", "Unten rechts", choices=POSITIONS),
        OptionSpec("size", "Größe (% der Videobreite)", "int", 15, min_value=1, max_value=100),
        OptionSpec("opacity", "Deckkraft (0 = unsichtbar, 1 = voll)", "float", 0.8, min_value=0.0, max_value=1.0),
        OptionSpec("margin", "Randabstand (Pixel)", "int", 24, min_value=0, max_value=2000),
        OptionSpec("start", "Einblenden ab Sekunde", "float", 0, min_value=0),
        OptionSpec("end", "Ausblenden bei Sekunde (0 = bis Ende)", "float", 0, min_value=0),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        w, _ = ctx.video_size(inp)
        lw = fu.even(w * int(o["size"]) / 100)
        x, y = fu.pos(fu.OVERLAY_POS, o["position"], int(o["margin"]))
        fc = (f"[1:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa={float(o['opacity']):g}[wm];"
              f"[0:v][wm]overlay={x}:{y}:format=auto{_enable(float(o['start']), float(o['end']))},"
              f"format=yuv420p[v]")
        return ["-y", "-i", inp, "-i", o["logo"], "-filter_complex", fc, "-map", "[v]", "-map", "0:a?"] + \
               fu.x264(o["crf"]) + ["-c:a", "copy", out]


class TextOverlayModule(BaseModule):
    name = "Text einblenden"
    category = CAT
    description = "Schreibt einen Text ins Video – Schrift, Farbe, Position und Zeitraum frei wählbar."
    output_suffix = "_text"
    options_schema = [
        OptionSpec("text", "Text (mehrzeilig möglich)", "multiline", "Mein Text"),
        OptionSpec("font", "Schriftart", "choice", "Arial Fett", choices=FONT_CHOICES),
        OptionSpec("size", "Schriftgröße", "int", 56, min_value=6, max_value=500),
        OptionSpec("color", "Schriftfarbe", "color", "#FFFFFF"),
        OptionSpec("position", "Position", "choice", "Unten Mitte", choices=TEXT_POSITIONS),
        OptionSpec("margin", "Randabstand (Pixel)", "int", 60, min_value=0, max_value=2000),
        OptionSpec("border", "Umrandung (Pixel, 0 = keine)", "int", 2, min_value=0, max_value=20),
        OptionSpec("box", "Hintergrund-Kasten", "bool", True),
        OptionSpec("box_color", "Kastenfarbe", "color", "#000000"),
        OptionSpec("box_opacity", "Kasten-Deckkraft (0–1)", "float", 0.5, min_value=0, max_value=1),
        OptionSpec("start", "Einblenden ab Sekunde", "float", 0, min_value=0),
        OptionSpec("end", "Ausblenden bei Sekunde (0 = bis Ende)", "float", 0, min_value=0),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        textfile = ctx.write_temp("text.txt", o["text"])
        x, y = fu.pos(fu.TEXT_POS, o["position"], int(o["margin"]))
        dt = (f"drawtext=fontfile={fu.fpath(fu.font_file(o['font']))}:textfile={fu.fpath(textfile)}"
              f":expansion=none:fontsize={o['size']}:fontcolor={fu.fcolor(o['color'])}:x={x}:y={y}"
              f":line_spacing=8")
        if int(o["border"]) > 0:
            dt += f":borderw={o['border']}:bordercolor=black@0.8"
        if o["box"]:
            dt += f":box=1:boxcolor={fu.fcolor(o['box_color'], float(o['box_opacity']))}:boxborderw=14"
        dt += _enable(float(o["start"]), float(o["end"]))
        return ["-y", "-i", inp, "-vf", dt] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


class TimecodeModule(BaseModule):
    name = "Zeitstempel / Timecode einbrennen"
    category = CAT
    description = "Blendet die laufende Zeit, einen SMPTE-Timecode oder die Bildnummer ein."
    output_suffix = "_timecode"
    options_schema = [
        OptionSpec("mode", "Anzeige", "choice", "pts", choices={
            "Laufzeit (hh:mm:ss.mmm)": "pts",
            "SMPTE-Timecode (hh:mm:ss:ff)": "smpte",
            "Bildnummer": "frame",
        }),
        OptionSpec("start_tc", "Start-Timecode (nur SMPTE)", "text", "00:00:00:00"),
        OptionSpec("size", "Schriftgröße", "int", 40, min_value=6, max_value=300),
        OptionSpec("color", "Schriftfarbe", "color", "#FFFFFF"),
        OptionSpec("position", "Position", "choice", "Oben links", choices=TEXT_POSITIONS),
        OptionSpec("box", "Hintergrund-Kasten", "bool", True),
        crf_option(20),
    ]

    def build_command(self, inp, out, o, ctx):
        x, y = fu.pos(fu.TEXT_POS, o["position"], 30)
        font = fu.fpath(fu.font_file("Consolas"))
        if o["mode"] == "smpte":
            fps, _ = ctx.frame_rate(inp)
            tc = o["start_tc"].strip().replace(":", "\\:")
            source = f"timecode='{tc}':rate={fps}"
        elif o["mode"] == "frame":
            source = "text='Bild %{n}'"
        else:
            source = "text='%{pts\\:hms}'"
        dt = (f"drawtext=fontfile={font}:{source}:fontsize={o['size']}:fontcolor={fu.fcolor(o['color'])}"
              f":x={x}:y={y}:borderw=2:bordercolor=black@0.7")
        if o["box"]:
            dt += ":box=1:boxcolor=black@0.5:boxborderw=10"
        return ["-y", "-i", inp, "-vf", dt] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


class BurnSubtitlesModule(BaseModule):
    name = "Untertitel einbrennen (SRT / ASS / VTT)"
    category = CAT
    description = "Brennt eine Untertiteldatei fest ins Bild (sichtbar in jedem Player)."
    output_suffix = "_untertitel"
    options_schema = [
        OptionSpec("subs", "Untertiteldatei", "file", "", filetypes="subtitle"),
        OptionSpec("fontsize", "Schriftgröße (0 = aus Datei / Standard)", "int", 0, min_value=0, max_value=200),
        OptionSpec("font", "Schriftart (nur SRT/VTT)", "choice", "Arial", choices=FONT_CHOICES),
        OptionSpec("color", "Schriftfarbe (nur SRT/VTT)", "color", "#FFFFFF"),
        OptionSpec("outline", "Umrandung (0–5)", "int", 2, min_value=0, max_value=5),
        crf_option(19),
    ]

    def build_command(self, inp, out, o, ctx):
        ext = os.path.splitext(o["subs"])[1].lower()
        if ext not in (".srt", ".ass", ".ssa", ".vtt"):
            raise ModuleError("Bitte eine .srt-, .ass- oder .vtt-Datei wählen.")
        # In einen einfachen Pfad kopieren – vermeidet Escaping-Probleme mit Sonderzeichen im Dateinamen.
        subs = ctx.copy_temp(o["subs"], "untertitel" + ext)
        vf = f"subtitles=filename={fu.fpath(subs)}"
        if ext in (".srt", ".vtt"):
            c = fu.fcolor(o["color"])[2:]
            style = [f"FontName={o['font'].replace(' Fett', '')}", f"PrimaryColour=&H00{c[4:6]}{c[2:4]}{c[0:2]}",
                     f"Outline={o['outline']}", "BorderStyle=1"]
            if "Fett" in o["font"]:
                style.append("Bold=1")
            if int(o["fontsize"]) > 0:
                style.append(f"Fontsize={o['fontsize']}")
            vf += f":force_style='{','.join(style)}'"
        elif int(o["fontsize"]) > 0:
            vf += f":force_style='Fontsize={o['fontsize']}'"
        return ["-y", "-i", inp, "-vf", vf] + fu.x264(o["crf"]) + ["-c:a", "copy", out]


MODULES: List[BaseModule] = [WatermarkModule(), TextOverlayModule(), TimecodeModule(), BurnSubtitlesModule()]
