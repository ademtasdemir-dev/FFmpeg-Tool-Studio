import json
import subprocess
from typing import Dict, List, Optional, Tuple

from core.executor import NO_WINDOW
from core.paths import find_tool


class ProbeError(Exception):
    pass


def parse_fraction(text: Optional[str]) -> float:
    if not text or text in ("0/0", "N/A"):
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


class Prober:
    """Liest Datei-Informationen über ffprobe (mit Cache)."""

    def __init__(self):
        self.bin = find_tool("ffprobe")
        self._cache: Dict[str, dict] = {}

    def probe(self, path: str) -> dict:
        if path in self._cache:
            return self._cache[path]
        try:
            res = subprocess.run(
                [self.bin, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", "-show_chapters", path],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=NO_WINDOW, timeout=60, encoding="utf-8", errors="replace",
            )
        except FileNotFoundError:
            raise ProbeError("ffprobe wurde nicht gefunden.")
        except subprocess.TimeoutExpired:
            raise ProbeError(f"ffprobe hat zu lange gebraucht: {path}")
        if res.returncode != 0:
            raise ProbeError(f"Datei konnte nicht gelesen werden:\n{path}\n{res.stderr.strip()[:500]}")
        info = json.loads(res.stdout or "{}")
        self._cache[path] = info
        return info


# ---------------------------------------------------------------- Auswertung
def streams(info: dict, kind: str) -> List[dict]:
    result = []
    for s in info.get("streams", []):
        if s.get("codec_type") != kind:
            continue
        if kind == "video" and s.get("disposition", {}).get("attached_pic"):
            continue  # Cover-Bilder sind keine echte Videospur
        result.append(s)
    return result


def duration(info: dict) -> Optional[float]:
    d = parse_fraction(info.get("format", {}).get("duration"))
    if d > 0:
        return d
    durations = [parse_fraction(s.get("duration")) for s in info.get("streams", [])]
    durations = [x for x in durations if x > 0]
    return max(durations) if durations else None


def rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                return int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    try:
        return int(stream.get("tags", {}).get("rotate", 0))
    except ValueError:
        return 0


def video_size(info: dict) -> Optional[Tuple[int, int]]:
    """Breite/Höhe wie angezeigt (Handy-Videos mit Drehungs-Flag werden berücksichtigt)."""
    vs = streams(info, "video")
    if not vs:
        return None
    w, h = int(vs[0].get("width", 0)), int(vs[0].get("height", 0))
    if abs(rotation(vs[0])) % 180 == 90:
        w, h = h, w
    return w, h


def frame_rate(info: dict) -> Tuple[str, float]:
    vs = streams(info, "video")
    if not vs:
        return "30", 30.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = vs[0].get(key)
        f = parse_fraction(val)
        if 0 < f < 1000:
            return val, f
    return "30", 30.0
