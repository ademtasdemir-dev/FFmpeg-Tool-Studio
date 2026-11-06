import os
import re
import subprocess
from typing import Dict, List

from core import ffutil as fu
from core.executor import NO_WINDOW, find_ffmpeg
from .base import BaseModule, OptionSpec, ModuleError

CAT = "Aufnahme & Streaming"

_device_cache: Dict[str, Dict[str, str]] = {}


def list_dshow_devices(kind: str) -> Dict[str, str]:
    """DirectShow-Geräte (kind = 'video' oder 'audio') -> {Anzeigename: Gerätename}."""
    if "all" not in _device_cache:
        devices = {"video": {}, "audio": {}}
        try:
            res = subprocess.run([find_ffmpeg(), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=NO_WINDOW, timeout=15, encoding="utf-8", errors="replace")
            for line in res.stderr.splitlines():
                m = re.search(r'"([^"]+)"\s+\((video|audio)\)', line)
                if m:
                    devices[m.group(2)][m.group(1)] = m.group(1)
        except Exception:
            pass
        _device_cache["all"] = devices  # type: ignore[assignment]
    return dict(_device_cache["all"][kind])  # type: ignore[index]


def mic_choices() -> Dict[str, str]:
    return {"Kein Ton": "", **list_dshow_devices("audio")}


def cam_choices() -> Dict[str, str]:
    cams = list_dshow_devices("video")
    return cams or {"(keine Kamera gefunden)": ""}


def _duration_args(o) -> List[str]:
    return ["-t", str(o["duration"])] if float(o["duration"]) > 0 else []


class ScreenRecordModule(BaseModule):
    name = "Bildschirm aufnehmen"
    category = CAT
    description = "Nimmt den Bildschirm (optional mit Mikrofon) auf. „Stoppen“ beendet die Aufnahme sauber."
    input_kind = "none"
    interactive = True
    output_ext = ".mp4"
    output_suffix = "Bildschirmaufnahme"
    options_schema = [
        OptionSpec("fps", "Bildrate", "int", 30, min_value=5, max_value=120),
        OptionSpec("area", "Bereich", "choice", "desktop", choices={
            "Gesamter Bildschirm (alle Monitore)": "desktop", "Rechteck (x, y, Breite, Höhe)": "region",
        }),
        OptionSpec("region", "Rechteck (nur bei „Rechteck“)", "text", "0,0,1920,1080"),
        OptionSpec("mic", "Mikrofon / Tonquelle", "choice", "", choices_fn=mic_choices),
        OptionSpec("mouse", "Mauszeiger aufnehmen", "bool", True),
        OptionSpec("duration", "Automatisch stoppen nach Sekunden (0 = manuell)", "float", 0, min_value=0),
        OptionSpec("crf", "Qualität (CRF, kleiner = besser)", "int", 23, min_value=0, max_value=51),
    ]

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"]) or None

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-f", "gdigrab", "-framerate", str(o["fps"]), "-draw_mouse", "1" if o["mouse"] else "0"]
        if o["area"] == "region":
            try:
                x, y, w, h = [int(v) for v in o["region"].replace(" ", "").split(",")]
            except ValueError:
                raise ModuleError("Rechteck bitte als x,y,Breite,Höhe angeben, z. B. 0,0,1280,720")
            cmd += ["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{fu.even(w)}x{fu.even(h)}"]
        cmd += ["-i", "desktop"]
        if o["mic"]:
            cmd += ["-f", "dshow", "-i", f"audio={o['mic']}"]
        cmd += _duration_args(o) + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"] + fu.x264(o["crf"], "ultrafast")
        if o["mic"]:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        return cmd + ["-movflags", "+faststart", out]


class WebcamRecordModule(BaseModule):
    name = "Webcam aufnehmen"
    category = CAT
    description = "Nimmt Kamera (und Mikrofon) auf. „Stoppen“ beendet die Aufnahme sauber."
    input_kind = "none"
    interactive = True
    output_ext = ".mp4"
    output_suffix = "Webcam"
    options_schema = [
        OptionSpec("camera", "Kamera", "choice", "", choices_fn=cam_choices),
        OptionSpec("mic", "Mikrofon", "choice", "", choices_fn=mic_choices),
        OptionSpec("size", "Auflösung", "choice", "", choices={
            "Kamera-Standard": "", "640 × 480": "640x480", "1280 × 720": "1280x720", "1920 × 1080": "1920x1080",
        }),
        OptionSpec("fps", "Bildrate", "choice", "", choices={"Kamera-Standard": "", "30": "30", "60": "60"}),
        OptionSpec("duration", "Automatisch stoppen nach Sekunden (0 = manuell)", "float", 0, min_value=0),
    ]

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"]) or None

    def build_command(self, inp, out, o, ctx):
        if not o["camera"]:
            raise ModuleError("Keine Kamera gefunden bzw. ausgewählt.")
        cmd = ["-y", "-f", "dshow", "-rtbufsize", "256M"]
        if o["size"]:
            cmd += ["-video_size", o["size"]]
        if o["fps"]:
            cmd += ["-framerate", o["fps"]]
        device = f"video={o['camera']}" + (f":audio={o['mic']}" if o["mic"] else "")
        cmd += ["-i", device] + _duration_args(o) + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"] + \
            fu.x264(21, "veryfast")
        if o["mic"]:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        return cmd + ["-movflags", "+faststart", out]


class StreamSaveModule(BaseModule):
    name = "Stream speichern (HLS / m3u8 → MP4)"
    category = CAT
    description = "Lädt einen Stream (z. B. .m3u8-Link) herunter und speichert ihn als MP4. Live-Streams: „Stoppen“."
    input_kind = "url"
    interactive = True
    output_ext = ".mp4"
    output_suffix = "Stream"
    options_schema = [
        OptionSpec("reencode", "Neu kodieren (nur falls Kopieren fehlschlägt)", "bool", False),
        OptionSpec("duration", "Nur die ersten X Sekunden (0 = alles)", "float", 0, min_value=0),
    ]

    def expected_duration(self, inp, o, ctx):
        return float(o["duration"]) or ctx.duration_or_none(inp)

    def build_command(self, inp, out, o, ctx):
        if not re.match(r"^(https?|rtmp|rtsp|srt|udp)://", inp.strip(), re.I):
            raise ModuleError("Bitte eine gültige Stream-URL eingeben (http://, https://, rtmp://, rtsp:// …).")
        cmd = ["-y", "-i", inp.strip()] + _duration_args(o)
        cmd += fu.x264(21, "veryfast") + ["-c:a", "aac", "-b:a", "160k"] if o["reencode"] else ["-c", "copy"]
        return cmd + ["-movflags", "+faststart", out]


class RtmpStreamModule(BaseModule):
    name = "Zu YouTube / Twitch streamen (RTMP)"
    category = CAT
    description = "Sendet ein Video live an YouTube, Twitch oder einen eigenen RTMP-Server. „Stoppen“ beendet."
    needs_output = False
    interactive = True
    options_schema = [
        OptionSpec("service", "Dienst", "choice", "rtmp://a.rtmp.youtube.com/live2", choices={
            "YouTube": "rtmp://a.rtmp.youtube.com/live2", "Twitch": "rtmp://live.twitch.tv/app",
            "Eigener Server (URL unten)": "custom",
        }),
        OptionSpec("custom_url", "Eigene RTMP-URL", "text", "rtmp://", optional=True),
        OptionSpec("key", "Stream-Schlüssel", "password", ""),
        OptionSpec("bitrate", "Video-Bitrate", "choice", 4500, choices={
            "2500 kbit/s (720p)": 2500, "4500 kbit/s (1080p30)": 4500, "6000 kbit/s (1080p60)": 6000,
        }),
        OptionSpec("loop", "Video endlos wiederholen", "bool", False),
    ]

    def expected_duration(self, inp, o, ctx):
        return None if o["loop"] else ctx.duration_or_none(inp)

    def execute(self, inp, out, o, ctx):
        base = o["custom_url"].strip() if o["service"] == "custom" else o["service"]
        if not base.startswith("rtmp"):
            raise ModuleError("Bitte eine gültige RTMP-URL angeben.")
        if not o["key"].strip():
            raise ModuleError("Bitte den Stream-Schlüssel eingeben.")
        target = base.rstrip("/") + "/" + o["key"].strip()
        b = int(o["bitrate"])
        cmd = ["-re"] + (["-stream_loop", "-1"] if o["loop"] else []) + ["-i", inp,
               "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{b}k", "-maxrate", f"{b}k",
               "-bufsize", f"{b * 2}k", "-g", "60", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-f", "flv", target]
        ctx.run(cmd, duration=self.expected_duration(inp, o, ctx), interactive=True, mask=[o["key"].strip()])
        return "Stream beendet."


class HlsDashModule(BaseModule):
    name = "HLS / DASH für Web-Player erzeugen"
    category = CAT
    description = "Zerlegt das Video in Segmente + Playlist für Web-Streaming (optional mit mehreren Qualitätsstufen)."
    output_is_dir = True
    output_suffix = "_stream"
    options_schema = [
        OptionSpec("format", "Format", "choice", "hls", choices={"HLS (.m3u8)": "hls", "DASH (.mpd)": "dash"}),
        OptionSpec("mode", "Qualitätsstufen", "choice", "single", choices={
            "Eine Stufe (Originalgröße)": "single", "Adaptiv: 1080p / 720p / 480p": "abr",
        }),
        OptionSpec("seg", "Segmentlänge (Sekunden)", "int", 6, min_value=1, max_value=30),
    ]

    def build_command(self, inp, out, o, ctx):
        os.makedirs(out, exist_ok=True)
        audio = ctx.has_audio(inp)
        seg = str(o["seg"])
        gop = ["-g", "48", "-keyint_min", "48", "-sc_threshold", "0"]
        if o["mode"] == "single":
            cmd = ["-y", "-i", inp, "-map", "0:v:0"] + (["-map", "0:a:0"] if audio else []) + \
                fu.x264(21, "veryfast") + gop + (["-c:a", "aac", "-b:a", "128k"] if audio else [])
            if o["format"] == "hls":
                return cmd + ["-f", "hls", "-hls_time", seg, "-hls_playlist_type", "vod",
                              "-hls_segment_filename", os.path.join(out, "seg_%04d.ts"),
                              os.path.join(out, "index.m3u8")]
            return cmd + ["-f", "dash", "-seg_duration", seg, "-use_template", "1", "-use_timeline", "1",
                          os.path.join(out, "manifest.mpd")]

        _, src_h = ctx.video_size(inp)
        ladder = [(h, b) for h, b in ((1080, 5000), (720, 2800), (480, 1400)) if h <= max(src_h, 480)]
        n = len(ladder)
        fc = f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)) + ";" + \
             ";".join(f"[s{i}]scale=-2:{h}[v{i}]" for i, (h, _) in enumerate(ladder))
        cmd = ["-y", "-i", inp, "-filter_complex", fc]
        for i in range(n):
            cmd += ["-map", f"[v{i}]"]
        if audio:
            cmd += ["-map", "0:a:0"] * (n if o["format"] == "hls" else 1)
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"] + gop
        for i, (_, b) in enumerate(ladder):
            cmd += [f"-b:v:{i}", f"{b}k", f"-maxrate:v:{i}", f"{int(b * 1.07)}k", f"-bufsize:v:{i}", f"{b * 2}k"]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
        if o["format"] == "hls":
            vmap = " ".join(f"v:{i},a:{i}" if audio else f"v:{i}" for i in range(n))
            return cmd + ["-f", "hls", "-hls_time", seg, "-hls_playlist_type", "vod", "-var_stream_map", vmap,
                          "-master_pl_name", "master.m3u8",
                          "-hls_segment_filename", os.path.join(out, "v%v", "seg_%04d.ts"),
                          os.path.join(out, "v%v", "index.m3u8")]
        sets = "id=0,streams=v" + (" id=1,streams=a" if audio else "")
        return cmd + ["-f", "dash", "-seg_duration", seg, "-use_template", "1", "-use_timeline", "1",
                      "-adaptation_sets", sets, os.path.join(out, "manifest.mpd")]


MODULES: List[BaseModule] = [ScreenRecordModule(), WebcamRecordModule(), StreamSaveModule(), RtmpStreamModule(),
                             HlsDashModule()]
