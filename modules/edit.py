import os
import re
from typing import Any, Dict, List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError, crf_option

CAT = "Schneiden & Zusammenfügen"


class TrimModule(BaseModule):
    name = "Video schneiden (Trimmen)"
    category = CAT
    description = "Einen Abschnitt aus dem Video herausschneiden."
    output_suffix = "_schnitt"
    options_schema = [
        OptionSpec("start", "Startzeit (hh:mm:ss)", "text", "00:00:00"),
        OptionSpec("duration", "Dauer in Sekunden", "float", 10, min_value=0.01),
        OptionSpec("fast_cut", "Schnellschnitt ohne Neukodierung", "bool", True,
                   hint="Schnell, aber nur an Keyframes exakt"),
    ]

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"])

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-ss", o["start"], "-i", inp, "-t", str(o["duration"])]
        cmd += ["-c", "copy"] if o["fast_cut"] else fu.x264(18) + ["-c:a", "aac", "-b:a", "192k"]
        return cmd + [out]


class ConcatModule(BaseModule):
    name = "Videos zusammenfügen"
    category = CAT
    description = "Hängt weitere Videos an das Eingabevideo an."
    output_suffix = "_zusammen"
    options_schema = [
        OptionSpec("additional_files", "Weitere Videos (in Reihenfolge)", "files", [], filetypes="video"),
        OptionSpec("reencode", "Neu kodieren (für unterschiedliche Formate/Auflösungen)", "bool", False,
                   hint="Aus = verlustfrei & schnell, nur bei identischem Format"),
        crf_option(20),
    ]

    def expected_duration(self, inp, o, ctx):
        try:
            return sum(ctx.duration(f) for f in [inp] + list(o["additional_files"]))
        except ModuleError:
            return None

    def build_command(self, inp, out, o, ctx):
        files = [inp] + list(o["additional_files"])
        if len(files) < 2:
            raise ModuleError("Bitte mindestens ein weiteres Video hinzufügen.")
        if not o["reencode"]:
            lst = "".join("file '{}'\n".format(os.path.abspath(f).replace("\\", "/").replace("'", "'\\''"))
                          for f in files)
            return ["-y", "-f", "concat", "-safe", "0", "-i", ctx.write_temp("liste.txt", lst), "-c", "copy", out]

        w, h = ctx.video_size(inp)
        w, h = fu.even(w), fu.even(h)
        fps, _ = ctx.frame_rate(inp)
        with_audio = all(ctx.has_audio(f) for f in files)
        cmd = ["-y"]
        for f in files:
            cmd += ["-i", f]
        parts, labels = [], ""
        for i in range(len(files)):
            parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
            labels += f"[v{i}]"
            if with_audio:
                parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
                labels += f"[a{i}]"
        parts.append(f"{labels}concat=n={len(files)}:v=1:a={1 if with_audio else 0}[v]" + ("[a]" if with_audio else ""))
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]"]
        if with_audio:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        return cmd + fu.x264(o["crf"]) + ["-movflags", "+faststart", out]


class SceneSplitModule(BaseModule):
    name = "Szenenwechsel erkennen & aufteilen"
    category = CAT
    description = "Findet Schnitte im Video automatisch und speichert jede Szene als eigene Datei."
    output_suffix = "_szene_%03d"
    options_schema = [
        OptionSpec("threshold", "Empfindlichkeit (0.1 = sehr empfindlich, 0.6 = nur harte Schnitte)", "float", 0.3,
                   min_value=0.02, max_value=0.95),
        OptionSpec("min_len", "Mindestlänge einer Szene (Sekunden)", "float", 1.5, min_value=0.1),
        OptionSpec("analyse_only", "Nur analysieren (Zeitpunkte im Log, nicht aufteilen)", "bool", False),
        crf_option(19),
    ]

    def execute(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        steps = 1 if o["analyse_only"] else 2
        lines = ctx.run(["-i", inp, "-an", "-vf", f"select='gt(scene,{o['threshold']})',showinfo",
                         "-f", "null", "-"], duration=dur, step=0, steps=steps, allow_gpu=False)
        raw = [float(m.group(1)) for line in lines if "Parsed_showinfo" in line
               for m in [re.search(r"pts_time:\s*([\d.]+)", line)] if m]
        cuts, last = [], 0.0
        for t in sorted(raw):
            if t - last >= o["min_len"] and dur - t >= o["min_len"]:
                cuts.append(t)
                last = t
        ctx.log(f"\n{len(cuts)} Szenenwechsel gefunden:")
        for i, t in enumerate(cuts, 1):
            ctx.log(f"  Schnitt {i:3d}: {fu.fmt_time(t)}")
        if o["analyse_only"]:
            return f"{len(cuts)} Szenenwechsel gefunden (Details im Log)."
        if not cuts:
            return "Keine Szenenwechsel gefunden – das Video wurde nicht aufgeteilt."
        ts = ",".join(f"{t:.3f}" for t in cuts)
        ctx.run(["-y", "-i", inp, "-map", "0:v:0", "-map", "0:a?"] + fu.x264(o["crf"]) +
                ["-force_key_frames", ts, "-c:a", "aac", "-b:a", "192k",
                 # segment_time_delta: Toleranz, sonst wird der Schnitt mit Tonspur knapp verpasst
                 "-f", "segment", "-segment_times", ts, "-segment_time_delta", "0.05",
                 "-reset_timestamps", "1", out],
                duration=dur, step=1, steps=2)
        return f"Video in {len(cuts) + 1} Szenen aufgeteilt."


TRANSITIONS = {
    "Überblenden": "fade", "Auflösen (Dissolve)": "dissolve", "Über Schwarz": "fadeblack",
    "Über Weiß": "fadewhite", "Wischen nach links": "wipeleft", "Wischen nach rechts": "wiperight",
    "Wischen nach oben": "wipeup", "Wischen nach unten": "wipedown", "Schieben nach links": "slideleft",
    "Schieben nach rechts": "slideright", "Schieben nach oben": "slideup", "Schieben nach unten": "slidedown",
    "Weich nach links": "smoothleft", "Weich nach rechts": "smoothright", "Kreis öffnen": "circleopen",
    "Kreis schließen": "circleclose", "Radial": "radial", "Diagonal": "diagtl", "Verpixeln": "pixelize",
    "Zoom": "zoomin", "Unschärfe": "hblur", "Horizontal öffnen": "horzopen", "Vertikal öffnen": "vertopen",
}


class TransitionModule(BaseModule):
    name = "Übergang zwischen zwei Clips (xfade)"
    category = CAT
    description = "Verbindet Eingabevideo und zweiten Clip mit einem Übergangseffekt."
    output_suffix = "_uebergang"
    output_ext = ".mp4"
    options_schema = [
        OptionSpec("second", "Zweiter Clip", "file", "", filetypes="video"),
        OptionSpec("transition", "Übergang", "choice", "fade", choices=TRANSITIONS),
        OptionSpec("tdur", "Dauer des Übergangs (Sekunden)", "float", 1.0, min_value=0.1, max_value=10),
        crf_option(20),
    ]

    def expected_duration(self, inp, o, ctx):
        try:
            return ctx.duration(inp) + ctx.duration(o["second"]) - float(o["tdur"])
        except ModuleError:
            return None

    def build_command(self, inp, out, o, ctx):
        second, d = o["second"], float(o["tdur"])
        d1, d2 = ctx.duration(inp), ctx.duration(second)
        if d >= d1 or d >= d2:
            raise ModuleError("Der Übergang ist länger als einer der Clips.")
        w, h = map(fu.even, ctx.video_size(inp))
        fps, _ = ctx.frame_rate(inp)
        norm = f"settb=AVTB,fps={fps},format=yuv420p,setsar=1"
        fc = [f"[0:v]scale={w}:{h},{norm}[v0]",
              f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,{norm}[v1]",
              f"[v0][v1]xfade=transition={o['transition']}:duration={d}:offset={d1 - d:.3f}[v]"]
        audio = ctx.has_audio(inp) and ctx.has_audio(second)
        if audio:
            fc.append("[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a0];"
                      "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];"
                      f"[a0][a1]acrossfade=d={d}[a]")
        cmd = ["-y", "-i", inp, "-i", second, "-filter_complex", ";".join(fc), "-map", "[v]"]
        if audio:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        return cmd + fu.x264(o["crf"]) + ["-movflags", "+faststart", out]


MODULES: List[BaseModule] = [TrimModule(), ConcatModule(), SceneSplitModule(), TransitionModule()]
