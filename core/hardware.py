import subprocess
from typing import Dict, List, Optional

from core.executor import NO_WINDOW

CPU_INFO = {"gpu": False, "label": "CPU (libx264 / libx265)"}

# (H.264-Encoder, HEVC-Encoder, Anzeigename, Familie)
CANDIDATES = [
    ("h264_nvenc", "hevc_nvenc", "NVIDIA NVENC", "nvenc"),
    ("h264_qsv", "hevc_qsv", "Intel QuickSync", "qsv"),
    ("h264_amf", "hevc_amf", "AMD AMF", "amf"),
]

NVENC_PRESETS = {
    "ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3",
    "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7", "veryslow": "p7",
}
QSV_PRESETS = {
    "ultrafast": "veryfast", "superfast": "veryfast", "veryfast": "veryfast", "faster": "faster",
    "fast": "fast", "medium": "medium", "slow": "slow", "slower": "slower", "veryslow": "veryslow",
}


class HardwareAccelerator:
    """Ermittelt einen GPU-Encoder, der auf diesem PC WIRKLICH funktioniert
    (FFmpeg listet NVENC & Co. auch ohne passende Grafikkarte)."""

    @staticmethod
    def detect(ffmpeg_bin: str) -> Dict:
        for h264, hevc, label, family in CANDIDATES:
            try:
                res = subprocess.run(
                    [ffmpeg_bin, "-hide_banner", "-nostdin", "-loglevel", "error",
                     "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                     "-frames:v", "1", "-c:v", h264, "-f", "null", "-"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=NO_WINDOW, timeout=15,
                )
                if res.returncode == 0:
                    return {"gpu": True, "h264": h264, "hevc": hevc, "label": label, "family": family}
            except Exception:
                continue
        return dict(CPU_INFO)


def _quality_args(family: str, q: str, hevc: bool) -> List[str]:
    if family == "nvenc":
        return ["-rc", "vbr", "-cq", q, "-b:v", "0"]
    if family == "qsv":
        return ["-global_quality", q]
    if family == "amf":
        args = ["-rc", "cqp", "-qp_i", q, "-qp_p", q]
        return args if hevc else args + ["-qp_b", q]
    return ["-crf", q]


def _preset(family: str, preset: str) -> Optional[str]:
    if family == "nvenc":
        return NVENC_PRESETS.get(preset, "p5")
    if family == "qsv":
        return QSV_PRESETS.get(preset, "medium")
    return None  # AMF: Preset-Namen passen nicht -> weglassen


def apply_gpu(args: List[str], hw: Dict) -> List[str]:
    """Ersetzt libx264/libx265 durch den GPU-Encoder und übersetzt CRF/Preset passend.
    2-Pass-Encodes bleiben auf der CPU (GPU-Encoder unterstützen das dort nicht gleichwertig)."""
    if not hw.get("gpu") or "-pass" in args or any("pass=" in str(a) for a in args):
        return args

    codec_map = {"libx264": hw["h264"], "libx265": hw["hevc"]}
    swapped: List[str] = []
    hevc = False
    changed = False
    i = 0
    while i < len(args):
        a = args[i]
        if (a.startswith("-c:v") or a == "-vcodec") and i + 1 < len(args) and args[i + 1] in codec_map:
            hevc = hevc or args[i + 1] == "libx265"
            swapped += [a, codec_map[args[i + 1]]]
            changed = True
            i += 2
            continue
        swapped.append(a)
        i += 1
    if not changed:
        return args

    family = hw["family"]
    out: List[str] = []
    i = 0
    while i < len(swapped):
        a = swapped[i]
        if a.startswith("-crf") and i + 1 < len(swapped):
            out += _quality_args(family, swapped[i + 1], hevc)
            i += 2
            continue
        if a.startswith("-preset") and i + 1 < len(swapped):
            mapped = _preset(family, swapped[i + 1])
            if mapped:
                out += [a, mapped]
            i += 2
            continue
        if (a.startswith("-tune") or a.startswith("-x265-params")) and i + 1 < len(swapped):
            i += 2
            continue
        out.append(a)
        i += 1
    return out
