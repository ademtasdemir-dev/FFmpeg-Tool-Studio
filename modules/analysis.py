import os
import re
from typing import List

from core import ffutil as fu
from core import probe as pr
from .base import BaseModule, OptionSpec, ModuleError

CAT = "Analyse & Info"


def _size(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def describe(path: str, info: dict) -> List[str]:
    fmt = info.get("format", {})
    lines = [f"Datei:      {os.path.basename(path)}",
             f"Container:  {fmt.get('format_long_name', fmt.get('format_name', '?'))}"]
    d = pr.duration(info)
    if d:
        lines.append(f"Dauer:      {fu.fmt_time(d)}")
    if fmt.get("size"):
        lines.append(f"Größe:      {_size(fmt['size'])}")
    if fmt.get("bit_rate"):
        lines.append(f"Bitrate:    {int(fmt['bit_rate']) / 1000:.0f} kbit/s (gesamt)")
    for key, val in (fmt.get("tags") or {}).items():
        lines.append(f"  {key}: {val}")
    counters = {}
    for s in info.get("streams", []):
        kind = s.get("codec_type", "?")
        idx = counters.get(kind, 0)
        counters[kind] = idx + 1
        label = {"video": "Video", "audio": "Audio", "subtitle": "Untertitel", "data": "Daten",
                 "attachment": "Anhang"}.get(kind, kind)
        spec = f"0:{kind[0]}:{idx}"
        desc = f"{s.get('codec_long_name', s.get('codec_name', '?'))}"
        if s.get("profile"):
            desc += f" ({s['profile']})"
        if kind == "video":
            if s.get("disposition", {}).get("attached_pic"):
                desc += " – Cover-Bild"
            fps = pr.parse_fraction(s.get("avg_frame_rate"))
            desc += f", {s.get('width')}×{s.get('height')}"
            if fps:
                desc += f", {fps:.3f} fps"
            if s.get("pix_fmt"):
                desc += f", {s['pix_fmt']}"
            rot = pr.rotation(s)
            if rot:
                desc += f", gedreht {rot}°"
        elif kind == "audio":
            desc += f", {s.get('sample_rate', '?')} Hz, {s.get('channels', '?')} Kanäle"
            if s.get("channel_layout"):
                desc += f" ({s['channel_layout']})"
        if s.get("bit_rate"):
            desc += f", {int(s['bit_rate']) / 1000:.0f} kbit/s"
        tags = s.get("tags") or {}
        if tags.get("language"):
            desc += f", Sprache: {tags['language']}"
        if tags.get("title"):
            desc += f", Titel: {tags['title']}"
        if s.get("disposition", {}).get("default"):
            desc += " [Standard]"
        lines.append(f"Spur {spec:<8} {label}: {desc}")
    chapters = info.get("chapters") or []
    if chapters:
        lines.append(f"Kapitel ({len(chapters)}):")
        for c in chapters:
            lines.append(f"  {fu.fmt_time(float(c.get('start_time', 0)))}  {(c.get('tags') or {}).get('title', '')}")
    return lines


class MediaInfoModule(BaseModule):
    name = "Medieninfo anzeigen"
    category = CAT
    description = "Codec, Auflösung, Bitrate, Dauer, Tonspuren, Untertitel, Kapitel und Metadaten."
    input_kind = "any"
    needs_output = False

    def execute(self, inp, out, o, ctx):
        if not inp:
            raise ModuleError("Bitte eine Datei wählen.")
        ctx.log("")
        for line in describe(inp, ctx.info(inp)):
            ctx.log(line)
        return "Medieninfo steht im Log."


class WaveformSpectrumModule(BaseModule):
    name = "Wellenform- / Spektrogramm-Bild"
    category = CAT
    description = "Zeichnet den Ton als Bild – Wellenform oder Frequenzspektrum."
    input_kind = "media"
    output_ext = ".png"
    output_suffix = "_wellenform"
    options_schema = [
        OptionSpec("type", "Darstellung", "choice", "wave", choices={"Wellenform": "wave", "Spektrogramm": "spec"}),
        OptionSpec("width", "Breite (Pixel)", "int", 1920, min_value=200, max_value=8000),
        OptionSpec("height", "Höhe (Pixel)", "int", 400, min_value=100, max_value=4000),
        OptionSpec("color", "Farbe (nur Wellenform)", "color", "#3FA9F5"),
    ]

    def build_command(self, inp, out, o, ctx):
        ctx.require_audio(inp)
        size = f"{o['width']}x{o['height']}"
        if o["type"] == "wave":
            fc = (f"[0:a:0]aformat=channel_layouts=mono,showwavespic=s={size}:colors={fu.fcolor(o['color'])}"
                  f"[w];color=c=0x101418:s={size}[bg];[bg][w]overlay=format=auto[v]")
        else:
            fc = f"[0:a:0]showspectrumpic=s={size}:legend=1:color=intensity[v]"
        return ["-y", "-i", inp, "-filter_complex", fc, "-map", "[v]", "-frames:v", "1", "-update", "1", out]


class QualityCompareModule(BaseModule):
    name = "Qualitätsvergleich zweier Videos (PSNR / SSIM / VMAF)"
    category = CAT
    description = "Misst, wie stark ein bearbeitetes Video (Eingabe) vom Original abweicht."
    needs_output = False
    options_schema = [
        OptionSpec("reference", "Original (Referenz)", "file", "", filetypes="video"),
        OptionSpec("metric", "Messverfahren", "choice", "ps", choices={
            "PSNR + SSIM (schnell)": "ps", "VMAF (Netflix, aussagekräftig, langsamer)": "vmaf",
        }),
    ]

    def execute(self, inp, out, o, ctx):
        ref = o["reference"]
        w, h = ctx.video_size(ref)
        dist = f"[0:v]scale={w}:{h}:flags=bicubic,setpts=PTS-STARTPTS,format=yuv420p[d];" \
               f"[1:v]setpts=PTS-STARTPTS,format=yuv420p[r];"
        if o["metric"] == "vmaf":
            fc = dist + f"[d][r]libvmaf=n_threads={os.cpu_count() or 4}"
        else:
            fc = dist + "[d]split[d1][d2];[r]split[r1][r2];[d1][r1]psnr;[d2][r2]ssim"
        lines = ctx.run(["-i", inp, "-i", ref, "-filter_complex", fc, "-an", "-f", "null", "-"],
                        duration=ctx.duration_or_none(inp), allow_gpu=False)
        text = "\n".join(lines)
        result = []
        if o["metric"] == "vmaf":
            m = re.search(r"VMAF score:\s*([\d.]+)", text)
            if m:
                v = float(m.group(1))
                rating = "praktisch identisch" if v >= 95 else "sehr gut" if v >= 90 else \
                         "gut" if v >= 80 else "sichtbare Verluste" if v >= 60 else "deutliche Verluste"
                result.append(f"VMAF: {v:.2f} von 100 – {rating}")
        else:
            m = re.search(r"PSNR .*average:([\d.inf]+)", text)
            if m:
                result.append(f"PSNR: {m.group(1)} dB (über 40 = sehr gut, unter 30 = deutliche Verluste)")
            m = re.search(r"SSIM .*All:([\d.]+)", text)
            if m:
                result.append(f"SSIM: {float(m.group(1)):.4f} (1.0 = identisch, über 0.95 = sehr gut)")
        if not result:
            raise ModuleError("Es konnte kein Messwert ermittelt werden (Details im Log).")
        ctx.log("\n" + "\n".join(result))
        return "\n".join(result)


class BlackSilenceDetectModule(BaseModule):
    name = "Schwarze oder stille Stellen finden"
    category = CAT
    description = "Listet alle Zeitbereiche mit schwarzem Bild und/oder Stille auf."
    input_kind = "media"
    needs_output = False
    options_schema = [
        OptionSpec("what", "Suchen nach", "choice", "both", choices={
            "Schwarzbild und Stille": "both", "Nur Schwarzbild": "black", "Nur Stille": "silence",
        }),
        OptionSpec("min_dur", "Mindestdauer (Sekunden)", "float", 0.5, min_value=0.05),
        OptionSpec("noise_db", "Stille-Schwelle (dB)", "int", -50, min_value=-90, max_value=-10),
        OptionSpec("pix_th", "Schwarz-Schwelle (0–1, höher = toleranter)", "float", 0.10, min_value=0.0, max_value=1.0),
    ]

    def execute(self, inp, out, o, ctx):
        args = ["-i", inp]
        want_black = o["what"] in ("both", "black") and ctx.has_video(inp)
        want_silence = o["what"] in ("both", "silence") and ctx.has_audio(inp)
        if not want_black and not want_silence:
            raise ModuleError("Die Datei hat die benötigte Bild- bzw. Tonspur nicht.")
        if want_black:
            args += ["-vf", f"blackdetect=d={o['min_dur']}:pix_th={o['pix_th']}"]
        else:
            args += ["-vn"]
        if want_silence:
            args += ["-af", f"silencedetect=n={o['noise_db']}dB:d={o['min_dur']}"]
        else:
            args += ["-an"]
        lines = ctx.run(args + ["-f", "null", "-"], duration=ctx.duration_or_none(inp), allow_gpu=False)
        text = "\n".join(lines)
        report = []
        if want_black:
            blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", text)
            report.append(f"Schwarzbild: {len(blacks)} Stelle(n)")
            report += [f"  {fu.fmt_time(float(a))} – {fu.fmt_time(float(b))}  ({float(d):.2f} s)" for a, b, d in blacks]
        if want_silence:
            starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]
            ends = re.findall(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)", text)
            report.append(f"Stille: {len(starts)} Stelle(n)")
            for i, s in enumerate(starts):
                if i < len(ends):
                    report.append(f"  {fu.fmt_time(s)} – {fu.fmt_time(float(ends[i][0]))}  ({float(ends[i][1]):.2f} s)")
                else:
                    report.append(f"  {fu.fmt_time(s)} – Dateiende")
        ctx.log("\n" + "\n".join(report))
        return "Ergebnis im Log:\n" + "\n".join(r for r in report if not r.startswith("  "))


class ErrorCheckModule(BaseModule):
    name = "Datei auf Fehler prüfen"
    category = CAT
    description = "Dekodiert die komplette Datei und meldet beschädigte Stellen."
    input_kind = "media"
    needs_output = False

    def execute(self, inp, out, o, ctx):
        # Mit "-v error" gibt FFmpeg nur Fehler aus (plus Fortschrittszeilen, die hier herausgefiltert werden).
        lines = ctx.run(["-v", "error", "-stats", "-i", inp, "-f", "null", "-"],
                        duration=ctx.duration_or_none(inp), allow_gpu=False)
        errors = [l for l in lines if not l.startswith(("frame=", "size=")) and "speed=" not in l]
        if not errors:
            ctx.log("\n✔ Keine Fehler gefunden – die Datei ist in Ordnung.")
            return "Keine Fehler gefunden – die Datei ist in Ordnung."
        ctx.log(f"\n✖ {len(errors)} Fehlermeldung(en) gefunden.")
        return f"{len(errors)} Fehlermeldung(en) gefunden – Details im Log."


MODULES: List[BaseModule] = [MediaInfoModule(), WaveformSpectrumModule(), QualityCompareModule(),
                             BlackSilenceDetectModule(), ErrorCheckModule()]
