import os
from typing import List

from core import ffutil as fu
from .base import BaseModule, OptionSpec, ModuleError, crf_option

CAT = "Kompression & Export"


class CrfCompressionModule(BaseModule):
    name = "Video komprimieren (H.264 / H.265)"
    category = CAT
    description = "Verkleinert Videos bei gleichbleibender Qualität (CRF). Mit GPU-Schalter oben deutlich schneller."
    output_ext = ".mp4"
    output_suffix = "_komprimiert"
    options_schema = [
        OptionSpec("codec", "Codec", "choice", "libx264", choices={
            "H.264 (kompatibel)": "libx264", "H.265 / HEVC (kleiner)": "libx265",
        }),
        OptionSpec("crf", "Qualität (CRF, kleiner = besser)", "int", 23, min_value=0, max_value=51),
        OptionSpec("preset", "Geschwindigkeit", "choice", "medium", choices={
            p: p for p in ("ultrafast", "veryfast", "fast", "medium", "slow", "veryslow")
        }),
        OptionSpec("audio_bitrate", "Audio-Bitrate", "choice", "128k", choices={
            "96 kbit/s": "96k", "128 kbit/s": "128k", "192 kbit/s": "192k", "256 kbit/s": "256k",
        }),
    ]

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-i", inp, "-c:v", o["codec"], "-crf", str(o["crf"]), "-preset", o["preset"],
               "-pix_fmt", "yuv420p"]
        if o["codec"] == "libx265":
            cmd += ["-tag:v", "hvc1"]
        return cmd + ["-c:a", "aac", "-b:a", o["audio_bitrate"], "-movflags", "+faststart", out]


class TargetSizeModule(BaseModule):
    name = "Zielgröße in MB treffen (2-Pass)"
    category = CAT
    description = "Berechnet die Bitrate so, dass die Datei unter die gewünschte Größe passt (Discord, WhatsApp, E-Mail)."
    output_ext = ".mp4"
    output_suffix = "_zielgroesse"
    options_schema = [
        OptionSpec("size_mb", "Zielgröße in MB", "float", 10, min_value=0.5, max_value=100000,
                   hint="Discord: 10, E-Mail: 20–25, WhatsApp: 100"),
        OptionSpec("codec", "Codec", "choice", "libx264", choices={
            "H.264 (kompatibel)": "libx264", "H.265 / HEVC (bessere Qualität bei kleiner Größe)": "libx265",
        }),
        OptionSpec("scale", "Auflösung", "choice", "", choices={
            "Original": "", "1080p": "1920:-2", "720p (empfohlen bei sehr kleiner Zielgröße)": "1280:-2",
            "480p": "854:-2",
        }),
        OptionSpec("audio_kbps", "Audio-Bitrate", "choice", 96, choices={
            "64 kbit/s": 64, "96 kbit/s": 96, "128 kbit/s": 128, "Ohne Ton": 0,
        }),
        OptionSpec("preset", "Geschwindigkeit", "choice", "medium", choices={
            p: p for p in ("veryfast", "fast", "medium", "slow")
        }),
    ]

    def execute(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        audio_k = int(o["audio_kbps"]) if ctx.has_audio(inp) else 0
        total_k = float(o["size_mb"]) * 1024 * 1024 * 8 / 1000 * 0.96  # 4 % Reserve für Container
        video_k = int(total_k / dur - audio_k)
        if video_k < 50:
            raise ModuleError(f"Die Zielgröße ist für {dur:.0f} s Video zu klein "
                              f"(nur {max(video_k, 0)} kbit/s für das Bild). Bitte größer wählen oder Video kürzen.")
        ctx.log(f"Berechnete Video-Bitrate: {video_k} kbit/s, Audio: {audio_k} kbit/s")
        vf = ["-vf", f"scale={o['scale']}:flags=lanczos"] if o["scale"] else []
        base = ["-y", "-i", inp] + vf + ["-c:v", o["codec"], "-b:v", f"{video_k}k", "-preset", o["preset"],
                                         "-pix_fmt", "yuv420p"]
        x265 = o["codec"] == "libx265"
        # Läuft im Temp-Ordner: Pass-Logdateien mit relativem Namen (x265 verträgt kein "C:" im Pfad).
        p1 = base + (["-x265-params", "pass=1:stats=pass.log"] if x265 else ["-pass", "1", "-passlogfile", "pass"])
        ctx.run(p1 + ["-an", "-f", "null", "-"], duration=dur, step=0, steps=2, cwd=ctx.tmp_dir)
        p2 = base + (["-x265-params", "pass=2:stats=pass.log", "-tag:v", "hvc1"] if x265
                     else ["-pass", "2", "-passlogfile", "pass"])
        p2 += ["-c:a", "aac", "-b:a", f"{audio_k}k"] if audio_k else ["-an"]
        ctx.run(p2 + ["-movflags", "+faststart", os.path.abspath(out)], duration=dur, step=1, steps=2,
                cwd=ctx.tmp_dir)
        size = os.path.getsize(out) / 1024 / 1024
        return f"Fertig: {size:.2f} MB (Ziel: {float(o['size_mb']):g} MB)."


class ProResDnxModule(BaseModule):
    name = "ProRes / DNxHR (für Schnittprogramme)"
    category = CAT
    description = "Schnitt-Codecs für Premiere, DaVinci Resolve und Final Cut. Große Dateien, flüssiger Schnitt."
    output_ext = ".mov"
    output_suffix = "_schnitt"
    options_schema = [
        OptionSpec("format", "Format", "choice", "prores:3", choices={
            "ProRes 422 Proxy": "prores:0", "ProRes 422 LT": "prores:1", "ProRes 422": "prores:2",
            "ProRes 422 HQ": "prores:3", "ProRes 4444 (mit Alpha)": "prores:4",
            "DNxHR LB (Proxy)": "dnxhr_lb", "DNxHR SQ": "dnxhr_sq", "DNxHR HQ": "dnxhr_hq",
            "DNxHR HQX (10 Bit)": "dnxhr_hqx", "DNxHR 444": "dnxhr_444",
        }),
    ]

    def build_command(self, inp, out, o, ctx):
        f = o["format"]
        if f.startswith("prores"):
            profile = f.split(":")[1]
            pix = "yuva444p10le" if profile == "4" else "yuv422p10le"
            v = ["-c:v", "prores_ks", "-profile:v", profile, "-vendor", "apl0", "-pix_fmt", pix]
        else:
            pix = {"dnxhr_hqx": "yuv422p10le", "dnxhr_444": "yuv444p10le"}.get(f, "yuv422p")
            v = ["-c:v", "dnxhd", "-profile:v", f, "-pix_fmt", pix]
        return ["-y", "-i", inp] + v + ["-c:a", "pcm_s16le", out]


# Plattform: (Breite, Höhe, max. fps, CRF, maxrate kbit/s, Audio-Bitrate, Ausrichtung automatisch?)
PLATFORMS = {
    "yt1080": (1920, 1080, 60, 20, 12000, "192k", True),
    "yt4k": (3840, 2160, 60, 18, 45000, "192k", True),
    "reel": (1080, 1920, 30, 21, 8000, "128k", False),
    "feed": (1080, 1350, 30, 21, 8000, "128k", False),
    "square": (1080, 1080, 30, 21, 8000, "128k", False),
    "tiktok": (1080, 1920, 30, 21, 8000, "128k", False),
    "wa": (1280, 720, 30, 27, 2000, "96k", True),
    "x": (1280, 720, 30, 23, 5000, "128k", True),
    "fb": (1920, 1080, 30, 21, 8000, "128k", True),
}


class PlatformPresetModule(BaseModule):
    name = "Plattform-Presets (YouTube, Instagram, TikTok, WhatsApp …)"
    category = CAT
    description = "Passende Auflösung, Bildrate, Bitrate und Format für die gewählte Plattform."
    output_ext = ".mp4"
    options_schema = [
        OptionSpec("platform", "Plattform", "choice", "yt1080", choices={
            "YouTube 1080p": "yt1080", "YouTube 4K": "yt4k", "Instagram Reel / Story (9:16)": "reel",
            "Instagram Feed (4:5)": "feed", "Instagram Quadrat (1:1)": "square", "TikTok (9:16)": "tiktok",
            "WhatsApp (720p, klein)": "wa", "X / Twitter (720p)": "x", "Facebook (1080p)": "fb",
        }),
        OptionSpec("fit", "Wenn das Format nicht passt", "choice", "blur", choices={
            "Blur-Hintergrund": "blur", "Schwarze Balken": "pad", "Füllen (Ränder abschneiden)": "crop",
        }),
    ]

    output_suffix = "_plattform"

    def build_command(self, inp, out, o, ctx):
        w, h, fps_max, crf, maxrate, abr, auto_orient = PLATFORMS[o["platform"]]
        sw, sh = ctx.video_size(inp)
        if auto_orient and sh > sw:
            w, h = h, w
        _, src_fps = ctx.frame_rate(inp)
        fps = f",fps={fps_max}" if src_fps > fps_max + 0.5 else ""
        if o["fit"] == "pad":
            fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1{fps},format=yuv420p[v]")
        elif o["fit"] == "crop":
            fc = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1{fps},format=yuv420p[v]"
        else:
            fc = (f"[0:v]split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"boxblur=30:4[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                  f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{fps},format=yuv420p[v]")
        return ["-y", "-i", inp, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-profile:v", "high", "-crf", str(crf), "-preset", "medium",
                "-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k",
                "-c:a", "aac", "-b:a", abr, "-ar", "48000", "-movflags", "+faststart", out]


class FormatRemuxModule(BaseModule):
    name = "Format konvertieren (Remuxing, verlustfrei)"
    category = CAT
    description = "Wechselt nur den Container (z. B. MKV → MP4), ohne neu zu kodieren. Sehr schnell."
    output_suffix = ""
    options_schema = [
        OptionSpec("container", "Zielformat", "choice", "mp4", choices={"MP4": "mp4", "MKV": "mkv", "MOV": "mov"}),
    ]

    def suggested_ext(self, o):
        return "." + o["container"]

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-i", inp, "-map", "0:v?", "-map", "0:a?", "-c", "copy"]
        if out.lower().endswith((".mp4", ".mov")):
            cmd += ["-movflags", "+faststart"]
        return cmd + [out]


MODULES: List[BaseModule] = [CrfCompressionModule(), TargetSizeModule(), ProResDnxModule(),
                             PlatformPresetModule(), FormatRemuxModule()]
