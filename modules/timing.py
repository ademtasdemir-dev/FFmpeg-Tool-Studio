from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError, crf_option

CAT = "Zeit & Bildrate"


class PlaybackSpeedModule(BaseModule):
    name = "Geschwindigkeit ändern (Zeitraffer / Zeitlupe)"
    category = CAT
    description = "Schneller oder langsamer abspielen, Tonhöhe bleibt erhalten."
    output_suffix = "_tempo"
    options_schema = [
        OptionSpec("speed", "Faktor (2 = doppelt so schnell, 0.5 = halb)", "float", 2.0, min_value=0.1, max_value=16),
        OptionSpec("keep_audio", "Ton beibehalten", "bool", True),
        crf_option(20),
    ]

    def expected_duration(self, inp, o, ctx):
        d = ctx.duration_or_none(inp)
        return d / float(o["speed"]) if d else None

    def build_command(self, inp, out, o, ctx):
        speed = float(o["speed"])
        pts = 1.0 / speed
        if o["keep_audio"] and ctx.has_audio(inp):
            return ["-y", "-i", inp, "-filter_complex",
                    f"[0:v]setpts={pts:.5f}*PTS[v];[0:a]{fu.atempo_chain(speed)}[a]",
                    "-map", "[v]", "-map", "[a]"] + fu.x264(o["crf"]) + ["-c:a", "aac", "-b:a", "192k", out]
        return ["-y", "-i", inp, "-vf", f"setpts={pts:.5f}*PTS", "-an"] + fu.x264(o["crf"]) + [out]


class MotionInterpolationModule(BaseModule):
    name = "Flüssige Zeitlupe / Bildrate erhöhen (Zwischenbilder)"
    category = CAT
    description = "Berechnet Zwischenbilder per Bewegungsschätzung (minterpolate). Sehr rechenintensiv!"
    output_suffix = "_interpoliert"
    options_schema = [
        OptionSpec("fps", "Ziel-Bildrate (fps)", "int", 60, min_value=10, max_value=240),
        OptionSpec("slow", "Zeitlupen-Faktor (1 = nur Bildrate erhöhen, 2 = halb so schnell)", "float", 1.0,
                   min_value=1.0, max_value=8.0),
        OptionSpec("mode", "Verfahren", "choice", "mci", choices={
            "Bewegungskompensiert (beste Qualität, langsam)": "mci",
            "Überblenden (schnell, weicher)": "blend",
        }),
        crf_option(18),
    ]

    def expected_duration(self, inp, o, ctx):
        d = ctx.duration_or_none(inp)
        return d * float(o["slow"]) if d else None

    def build_command(self, inp, out, o, ctx):
        slow = float(o["slow"])
        vf = (f"setpts={slow:g}*PTS," if slow != 1 else "") + f"minterpolate=fps={o['fps']}:mi_mode={o['mode']}"
        if o["mode"] == "mci":
            vf += ":mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        cmd = ["-y", "-i", inp, "-vf", vf] + fu.x264(o["crf"])
        if not ctx.has_audio(inp):
            cmd += ["-an"]
        elif slow == 1:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-af", fu.atempo_chain(1 / slow), "-c:a", "aac", "-b:a", "192k"]
        return cmd + [out]


class FreezeFrameModule(BaseModule):
    name = "Standbild einfrieren / Bild verlängern"
    category = CAT
    description = "Hält ein Bild für einige Sekunden an (am Anfang, am Ende oder an einem Zeitpunkt)."
    output_suffix = "_standbild"
    options_schema = [
        OptionSpec("mode", "Modus", "choice", "at", choices={
            "An Zeitpunkt einfrieren": "at",
            "Erstes Bild verlängern (Anfang)": "start",
            "Letztes Bild verlängern (Ende)": "end",
        }),
        OptionSpec("time", "Zeitpunkt (nur bei „An Zeitpunkt“)", "text", "00:00:03"),
        OptionSpec("hold", "Standbild-Dauer (Sekunden)", "float", 2.0, min_value=0.1, max_value=600),
        crf_option(19),
    ]

    def expected_duration(self, inp, o, ctx):
        d = ctx.duration_or_none(inp)
        return d + float(o["hold"]) if d else None

    def build_command(self, inp, out, o, ctx):
        hold = float(o["hold"])
        ms = int(hold * 1000)
        audio = ctx.has_audio(inp)
        mode = o["mode"]
        if mode == "start":
            fc = f"[0:v]tpad=start_mode=clone:start_duration={hold}[v]"
            if audio:
                fc += f";[0:a]adelay={ms}:all=1[a]"
        elif mode == "end":
            fc = f"[0:v]tpad=stop_mode=clone:stop_duration={hold}[v]"
            if audio:
                fc += f";[0:a]apad=pad_dur={hold}[a]"
        else:
            try:
                t = fu.parse_time(o["time"])
            except ValueError:
                raise ModuleError(f"Ungültiger Zeitpunkt: {o['time']}")
            if t >= ctx.duration(inp):
                raise ModuleError("Der Zeitpunkt liegt hinter dem Videoende.")
            fc = (f"[0:v]split[v0][v1];[v0]trim=end={t},setpts=PTS-STARTPTS[va];"
                  f"[v1]trim=start={t},setpts=PTS-STARTPTS,tpad=start_mode=clone:start_duration={hold}[vb];"
                  f"[va][vb]concat=n=2:v=1:a=0[v]")
            if audio:
                fc += (f";[0:a]asplit[a0][a1];[a0]atrim=end={t},asetpts=PTS-STARTPTS[aa];"
                       f"[a1]atrim=start={t},asetpts=PTS-STARTPTS,adelay={ms}:all=1[ab];"
                       f"[aa][ab]concat=n=2:v=0:a=1[a]")
        cmd = ["-y", "-i", inp, "-filter_complex", fc, "-map", "[v]"]
        if audio:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        return cmd + fu.x264(o["crf"]) + [out]


MODULES: List[BaseModule] = [PlaybackSpeedModule(), MotionInterpolationModule(), FreezeFrameModule()]
