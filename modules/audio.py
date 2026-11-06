import os
from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError

CAT = "Audio"


def _video_copy(ctx, inp) -> List[str]:
    return ["-c:v", "copy"] if ctx.has_video(inp) else []


class ExtractAudioModule(BaseModule):
    name = "Tonspur extrahieren (MP3 / AAC / WAV / FLAC)"
    category = CAT
    description = "Speichert den Ton eines Videos als Audiodatei."
    output_suffix = "_audio"
    options_schema = [
        OptionSpec("format", "Audioformat", "choice", "mp3", choices={
            "MP3": "mp3", "AAC (M4A)": "m4a", "WAV (verlustfrei)": "wav", "FLAC (verlustfrei)": "flac",
            "Opus": "opus",
        }),
        OptionSpec("bitrate", "Bitrate (nur MP3/AAC/Opus)", "choice", "192k", choices={
            "128 kbit/s": "128k", "192 kbit/s": "192k", "256 kbit/s": "256k", "320 kbit/s": "320k",
        }),
    ]

    def suggested_ext(self, o):
        return "." + o["format"]

    def build_command(self, inp, out, o, ctx):
        ctx.require_audio(inp)
        return ["-y", "-i", inp, "-vn"] + fu.audio_codec_for(out, o["bitrate"]) + [out]


class MuteVideoModule(BaseModule):
    name = "Video stummschalten (Ton entfernen)"
    category = CAT
    description = "Entfernt alle Tonspuren, das Bild bleibt unverändert."
    output_suffix = "_stumm"

    def build_command(self, inp, out, o, ctx):
        return ["-y", "-i", inp, "-an", "-c:v", "copy", out]


class ReplaceAudioModule(BaseModule):
    name = "Ton ersetzen (neue Musik unter das Video)"
    category = CAT
    description = "Ersetzt den Originalton komplett durch eine Audiodatei."
    output_suffix = "_neuer_ton"
    options_schema = [
        OptionSpec("music", "Audiodatei", "file", "", filetypes="audio"),
        OptionSpec("loop", "Musik wiederholen, falls kürzer als das Video", "bool", True),
        OptionSpec("music_start", "Musik ab Sekunde starten", "float", 0, min_value=0),
        OptionSpec("volume", "Lautstärke (1 = unverändert)", "float", 1.0, min_value=0, max_value=10),
        OptionSpec("fade_out", "Ausblenden am Ende (Sekunden, 0 = aus)", "float", 2.0, min_value=0, max_value=60),
    ]

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        cmd = ["-y", "-i", inp]
        if o["loop"]:
            cmd += ["-stream_loop", "-1"]
        if float(o["music_start"]) > 0:
            cmd += ["-ss", str(o["music_start"])]
        af = [f"volume={float(o['volume']):g}", "apad"]
        fo = float(o["fade_out"])
        if 0 < fo < dur:
            af.append(f"afade=t=out:st={dur - fo:.3f}:d={fo:g}")
        return cmd + ["-i", o["music"], "-map", "0:v:0", "-map", "1:a:0", "-af", ",".join(af), "-t", f"{dur:.3f}",
                      "-c:v", "copy"] + fu.audio_codec_for(out) + [out]


class MixMusicModule(BaseModule):
    name = "Hintergrundmusik mischen (mit Ducking)"
    category = CAT
    description = "Legt Musik unter den Originalton. Ducking senkt die Musik automatisch, wenn jemand spricht."
    output_suffix = "_mit_musik"
    options_schema = [
        OptionSpec("music", "Musikdatei", "file", "", filetypes="audio"),
        OptionSpec("music_vol", "Musik-Lautstärke", "float", 0.3, min_value=0, max_value=5,
                   hint="0.2–0.4 ist typisch für Hintergrundmusik"),
        OptionSpec("orig_vol", "Originalton-Lautstärke", "float", 1.0, min_value=0, max_value=5),
        OptionSpec("ducking", "Ducking (Musik leiser bei Sprache)", "bool", True),
        OptionSpec("loop", "Musik wiederholen, falls kürzer als das Video", "bool", True),
        OptionSpec("fade_out", "Musik am Ende ausblenden (Sekunden)", "float", 3.0, min_value=0, max_value=60),
    ]

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        fo = float(o["fade_out"])
        fade = f",afade=t=out:st={dur - fo:.3f}:d={fo:g}" if 0 < fo < dur else ""
        fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
        music = f"[1:a]{fmt},volume={float(o['music_vol']):g}{fade}[m]"
        if ctx.has_audio(inp):
            orig = f"[0:a]{fmt},volume={float(o['orig_vol']):g}"
            if o["ducking"]:
                fc = (f"{music};{orig},asplit[o1][o2];"
                      f"[m][o2]sidechaincompress=threshold=0.03:ratio=8:attack=40:release=500[md];"
                      f"[o1][md]amix=inputs=2:duration=first:normalize=0[a]")
            else:
                fc = f"{music};{orig}[o];[o][m]amix=inputs=2:duration=first:normalize=0[a]"
        else:
            fc = f"{music};[m]apad[a]"
        cmd = ["-y", "-i", inp] + (["-stream_loop", "-1"] if o["loop"] else []) + ["-i", o["music"]]
        return cmd + ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]", "-t", f"{dur:.3f}",
                      "-c:v", "copy"] + fu.audio_codec_for(out) + [out]


class AudioFadeModule(BaseModule):
    name = "Audio ein- und ausblenden"
    category = CAT
    description = "Weiches Ein- und Ausblenden des Tons (optional auch das Bild von/zu Schwarz)."
    input_kind = "media"
    output_suffix = "_fade"
    options_schema = [
        OptionSpec("fade_in", "Einblenden (Sekunden, 0 = aus)", "float", 2.0, min_value=0, max_value=120),
        OptionSpec("fade_out", "Ausblenden (Sekunden, 0 = aus)", "float", 3.0, min_value=0, max_value=120),
        OptionSpec("video_too", "Bild ebenfalls von/zu Schwarz blenden", "bool", False),
    ]

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        fi, fo = float(o["fade_in"]), float(o["fade_out"])
        if fi + fo > dur:
            raise ModuleError("Ein- und Ausblenden zusammen sind länger als die Datei.")
        def fades(prefix):
            f = []
            if fi > 0:
                f.append(f"{prefix}fade=t=in:st=0:d={fi:g}")
            if fo > 0:
                f.append(f"{prefix}fade=t=out:st={dur - fo:.3f}:d={fo:g}")
            return ",".join(f)
        has_audio, has_video = ctx.has_audio(inp), ctx.has_video(inp)
        if not has_audio and not (o["video_too"] and has_video):
            raise ModuleError("Die Datei hat keine Tonspur.")
        if not fades("a"):
            raise ModuleError("Bitte Einblend- oder Ausblenddauer größer 0 wählen.")
        cmd = ["-y", "-i", inp]
        if has_audio:
            cmd += ["-af", fades("a")] + fu.audio_codec_for(out)
        if has_video:
            cmd += ["-vf", fades("")] + fu.x264(19) if o["video_too"] else ["-c:v", "copy"]
        return cmd + [out]


class AudioDelayModule(BaseModule):
    name = "Audio verschieben (Lippensynchronität)"
    category = CAT
    description = "Verschiebt den Ton gegenüber dem Bild – ohne Neukodierung."
    output_suffix = "_sync"
    options_schema = [
        OptionSpec("offset", "Versatz in Sekunden (+ = Ton später, − = Ton früher)", "float", 0.2,
                   min_value=-60, max_value=60, hint="Typisch: ±0.04 bis ±0.5"),
    ]

    def build_command(self, inp, out, o, ctx):
        ctx.require_audio(inp)
        off = float(o["offset"])
        if off >= 0:
            # Eingang 1 (Ton) wird verzögert
            return ["-y", "-i", inp, "-itsoffset", f"{off:g}", "-i", inp,
                    "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", out]
        # Ton früher = Bild verzögern
        return ["-y", "-itsoffset", f"{-off:g}", "-i", inp, "-i", inp,
                "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", out]


class AudioEffectsModule(BaseModule):
    name = "Tonhöhe, Echo, Equalizer & Lautstärke"
    category = CAT
    description = "Tonhöhe ändern (ohne Tempo), Hall/Echo, Bass/Höhen, Lautstärke oder Lautheit normalisieren."
    input_kind = "media"
    output_suffix = "_klang"
    options_schema = [
        OptionSpec("pitch", "Tonhöhe in Halbtönen (0 = unverändert)", "float", 0, min_value=-24, max_value=24),
        OptionSpec("echo", "Hall / Echo", "choice", "", choices={
            "Kein": "", "Leichter Raumhall": "aecho=0.8:0.7:40:0.25",
            "Halle": "aecho=0.8:0.88:60|120:0.4|0.3", "Kathedrale": "aecho=0.8:0.9:200|400|800:0.4|0.3|0.2",
            "Echo (Berg)": "aecho=0.8:0.9:500|1000:0.3|0.2", "Telefon": "highpass=f=300,lowpass=f=3400",
            "Radio (alt)": "highpass=f=500,lowpass=f=4000,acrusher=bits=10:mode=log",
        }),
        OptionSpec("bass", "Bass (dB)", "float", 0, min_value=-20, max_value=20),
        OptionSpec("treble", "Höhen (dB)", "float", 0, min_value=-20, max_value=20),
        OptionSpec("volume", "Lautstärke (1 = unverändert)", "float", 1.0, min_value=0, max_value=20),
        OptionSpec("loudnorm", "Lautheit normalisieren (EBU R128, −14 LUFS)", "bool", False,
                   hint="Gleichmäßig laut wie auf YouTube/Spotify"),
    ]

    def build_command(self, inp, out, o, ctx):
        ctx.require_audio(inp)
        af = []
        if float(o["pitch"]) != 0:
            af.append(f"rubberband=pitch={2 ** (float(o['pitch']) / 12):.6f}")
        if o["echo"]:
            af.append(o["echo"])
        if float(o["bass"]) != 0:
            af.append(f"bass=g={float(o['bass']):g}")
        if float(o["treble"]) != 0:
            af.append(f"treble=g={float(o['treble']):g}")
        if float(o["volume"]) != 1:
            af.append(f"volume={float(o['volume']):g}")
        if o["loudnorm"]:
            af.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        if not af:
            raise ModuleError("Keine Änderung gewählt.")
        return ["-y", "-i", inp] + _video_copy(ctx, inp) + ["-af", ",".join(af)] + fu.audio_codec_for(out) + [out]


MODULES: List[BaseModule] = [ExtractAudioModule(), MuteVideoModule(), ReplaceAudioModule(), MixMusicModule(),
                             AudioFadeModule(), AudioDelayModule(), AudioEffectsModule()]
