import os
import re
from typing import List

from core import ffutil as fu
from core import probe as pr
from .base import BaseModule, OptionSpec, ModuleError

CAT = "Metadaten & Spuren"

# Nur Bild-, Ton- und Untertitelspuren übernehmen (Datenspuren wie GoPro-GPS fallen weg).
STD_MAPS = ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"]


class MetadataEditModule(BaseModule):
    name = "Metadaten bearbeiten oder entfernen"
    category = CAT
    description = "Titel, Interpret, Kommentar usw. setzen – oder alle Metadaten (GPS, Kamera, Datum) löschen."
    input_kind = "media"
    output_suffix = "_meta"
    options_schema = [
        OptionSpec("mode", "Aktion", "choice", "edit", choices={
            "Ändern / ergänzen": "edit",
            "Alle Metadaten entfernen (inkl. GPS, Kamera, Datum)": "strip",
        }),
        OptionSpec("title", "Titel", "text", "", optional=True, hint="Leere Felder bleiben unverändert"),
        OptionSpec("artist", "Interpret / Autor", "text", "", optional=True),
        OptionSpec("album", "Album", "text", "", optional=True),
        OptionSpec("date", "Jahr / Datum", "text", "", optional=True),
        OptionSpec("genre", "Genre", "text", "", optional=True),
        OptionSpec("comment", "Kommentar", "text", "", optional=True),
        OptionSpec("copyright", "Copyright", "text", "", optional=True),
    ]

    def build_command(self, inp, out, o, ctx):
        cmd = ["-y", "-i", inp] + STD_MAPS + ["-c", "copy"]
        if o["mode"] == "strip":
            return cmd + ["-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1",
                          "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                          "-flags:a", "+bitexact", out]
        fields = [k for k in ("title", "artist", "album", "date", "genre", "comment", "copyright") if o[k]]
        if not fields:
            raise ModuleError("Bitte mindestens ein Feld ausfüllen.")
        for k in fields:
            cmd += ["-metadata", f"{k}={o[k]}"]
        return cmd + [out]


class CoverEmbedModule(BaseModule):
    name = "Cover-Bild einbetten (MP3 / M4A / MP4 / FLAC)"
    category = CAT
    description = "Fügt ein Coverbild hinzu, das Player und Explorer als Vorschaubild anzeigen."
    input_kind = "media"
    output_suffix = "_cover"
    options_schema = [
        OptionSpec("image", "Coverbild (JPG oder PNG)", "file", "", filetypes="image"),
    ]

    def build_command(self, inp, out, o, ctx):
        ext = os.path.splitext(out)[1].lower()
        img = o["image"]
        if ext == ".mp3":
            return ["-y", "-i", inp, "-i", img, "-map", "0:a", "-map", "1:0", "-c", "copy", "-id3v2_version", "3",
                    "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)", out]
        if ext == ".flac":
            return ["-y", "-i", inp, "-i", img, "-map", "0:a", "-map", "1:0", "-c", "copy",
                    "-disposition:v", "attached_pic", out]
        if ext in (".m4a", ".mp4", ".mov", ".m4v"):
            n_video = len(pr.streams(ctx.info(inp), "video"))
            img_codec = "png" if img.lower().endswith(".png") else "mjpeg"
            return ["-y", "-i", inp, "-i", img, "-map", "0:v?", "-map", "0:a?", "-map", "1:0", "-c", "copy",
                    f"-c:v:{n_video}", img_codec, f"-disposition:v:{n_video}", "attached_pic", out]
        raise ModuleError("Cover einbetten geht nur bei MP3, M4A, MP4, MOV und FLAC.")


class ChaptersModule(BaseModule):
    name = "Kapitel hinzufügen"
    category = CAT
    description = "Kapitelmarken, die in VLC, MPC und vielen Playern angezeigt werden (MP4/MKV)."
    output_suffix = "_kapitel"
    input_kind = "media"
    options_schema = [
        OptionSpec("chapters", "Kapitel (eine Zeile pro Kapitel: Zeit Titel)", "multiline",
                   "00:00:00 Intro\n00:01:30 Hauptteil\n00:05:00 Fazit",
                   hint="Zeit als hh:mm:ss, mm:ss oder Sekunden"),
    ]

    def build_command(self, inp, out, o, ctx):
        dur = ctx.duration(inp)
        entries = []
        for n, line in enumerate(o["chapters"].splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^([\d:.,]+)\s*[-–]?\s*(.*)$", line)
            if not m:
                raise ModuleError(f"Zeile {n} ist ungültig: „{line}“")
            try:
                t = fu.parse_time(m.group(1))
            except ValueError:
                raise ModuleError(f"Ungültige Zeit in Zeile {n}: „{m.group(1)}“")
            if t >= dur:
                raise ModuleError(f"Kapitel in Zeile {n} liegt hinter dem Dateiende.")
            entries.append((t, m.group(2).strip() or f"Kapitel {len(entries) + 1}"))
        if not entries:
            raise ModuleError("Bitte mindestens ein Kapitel angeben.")
        entries.sort()
        esc = lambda s: re.sub(r"([=;#\\\n])", r"\\\1", s)
        meta = [";FFMETADATA1"]
        for i, (t, title) in enumerate(entries):
            end = entries[i + 1][0] if i + 1 < len(entries) else dur
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(t * 1000)}", f"END={int(end * 1000)}",
                     f"title={esc(title)}"]
        path = ctx.write_temp("kapitel.txt", "\n".join(meta) + "\n")
        return ["-y", "-i", inp, "-i", path] + STD_MAPS + ["-map_metadata", "0", "-map_chapters", "1",
                                                          "-c", "copy", out]


class TrackSelectModule(BaseModule):
    name = "Spuren auswählen & neu anordnen"
    category = CAT
    description = "Behält nur bestimmte Bild-/Ton-/Untertitelspuren in gewünschter Reihenfolge (verlustfrei)."
    output_suffix = "_spuren"
    input_kind = "media"
    options_schema = [
        OptionSpec("maps", "Spuren in Reihenfolge (kommagetrennt)", "text", "0:v:0, 0:a:0",
                   hint="Spurnummern zeigt „Medieninfo“, z. B. 0:a:1 = 2. Tonspur"),
        OptionSpec("default_audio", "Erste Tonspur als Standard markieren", "bool", True),
    ]

    def build_command(self, inp, out, o, ctx):
        specs = [s.strip() for s in o["maps"].split(",") if s.strip()]
        if not specs:
            raise ModuleError("Bitte mindestens eine Spur angeben.")
        for line in ["Vorhandene Spuren:"] + [l for l in _stream_list(ctx.info(inp))]:
            ctx.log(line)
        cmd = ["-y", "-i", inp]
        for s in specs:
            if not re.fullmatch(r"0(:[vas](:\d+)?|:\d+)", s):
                raise ModuleError(f"Ungültige Spurangabe: „{s}“ (Beispiel: 0:a:1)")
            cmd += ["-map", s]
        cmd += ["-c", "copy"]
        n_audio = sum(1 for s in specs if ":a" in s)
        if o["default_audio"] and n_audio:
            cmd += ["-disposition:a:0", "default"]
            for i in range(1, n_audio):
                cmd += [f"-disposition:a:{i}", "0"]
        return cmd + [out]


def _stream_list(info) -> List[str]:
    out, counters = [], {}
    for s in info.get("streams", []):
        kind = s.get("codec_type", "?")
        idx = counters.get(kind, 0)
        counters[kind] = idx + 1
        tags = s.get("tags") or {}
        out.append(f"  0:{kind[0]}:{idx}  {s.get('codec_name', '?')}  {tags.get('language', '')} {tags.get('title', '')}")
    return out


class RotationFlagModule(BaseModule):
    name = "Drehung setzen (ohne Neukodierung)"
    category = CAT
    description = "Setzt nur die Drehungs-Markierung – sofort fertig, keine Qualitätsverluste (MP4/MOV)."
    output_suffix = "_rotiert"
    options_schema = [
        OptionSpec("angle", "Anzeige-Drehung", "choice", 270, choices={
            "90° im Uhrzeigersinn": 270, "90° gegen den Uhrzeigersinn": 90, "180°": 180,
            "Keine Drehung (Markierung entfernen)": 0,
        }),
    ]

    def build_command(self, inp, out, o, ctx):
        if not out.lower().endswith((".mp4", ".mov", ".m4v")):
            raise ModuleError("Die Drehungs-Markierung wird nur von MP4 und MOV unterstützt.")
        return ["-y", "-display_rotation:v:0", str(o["angle"]), "-i", inp, "-map", "0:v?", "-map", "0:a?",
                "-c", "copy", out]


MODULES: List[BaseModule] = [MetadataEditModule(), CoverEmbedModule(), ChaptersModule(), TrackSelectModule(),
                             RotationFlagModule()]
