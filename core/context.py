import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core import probe as pr
from core.executor import FFmpegExecutor, FFmpegExecutionError
from core.hardware import apply_gpu

TIME_RE = re.compile(r"time=\s*(-?\d+):(\d+):(\d+(?:\.\d+)?)")


class Cancelled(Exception):
    pass


class ModuleError(Exception):
    """Verständliche Fehlermeldung für den Nutzer (z. B. 'Video hat keine Tonspur')."""


class RunContext:
    """Wird jedem Modul beim Ausführen übergeben: FFmpeg starten, Dateien analysieren,
    Fortschritt melden, temporäre Dateien verwalten."""

    def __init__(
        self,
        executor: FFmpegExecutor,
        prober: pr.Prober,
        hw: Dict,
        use_gpu: bool,
        log: Callable[[str], None],
        progress: Callable[[Optional[float]], None],
        stats: Callable[[str], None],
    ):
        self.executor = executor
        self.prober = prober
        self.hw = hw
        self.use_gpu = use_gpu and hw.get("gpu", False)
        self.log = log
        self._progress = progress
        self._stats = stats
        self.cancelled = False
        self.tmp_dir = tempfile.mkdtemp(prefix="ffts_")

    # ------------------------------------------------------------ Steuerung
    def cancel(self):
        self.cancelled = True
        self.executor.kill()

    def stop(self):
        """Aufnahme/Stream sauber beenden (zählt als Erfolg)."""
        self.executor.stop()

    def cleanup(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def check_cancel(self):
        if self.cancelled:
            raise Cancelled()

    # ------------------------------------------------------------ FFmpeg
    def run(
        self,
        args: List[str],
        duration: Optional[float] = None,
        step: int = 0,
        steps: int = 1,
        interactive: bool = False,
        cwd: Optional[str] = None,
        mask: Iterable[str] = (),
        allow_gpu: bool = True,
    ) -> List[str]:
        self.check_cancel()
        if self.use_gpu and allow_gpu:
            args = apply_gpu(args, self.hw)
        full = ["-hide_banner"] + ([] if interactive else ["-nostdin"]) + ["-stats_period", "0.5"] + list(args)

        shown = subprocess.list2cmdline(full)
        for secret in mask:
            if secret:
                shown = shown.replace(secret, "****")
        self.log(f"> ffmpeg {shown}")
        if duration is None:
            self._progress(None if steps == 1 else step / steps)

        def on_line(line: str):
            m = TIME_RE.search(line)
            if line.startswith(("frame=", "size=")) or (m and "speed=" in line):
                self._stats(line)
                if m and duration:
                    t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    self._progress((step + max(0.0, min(1.0, t / duration))) / steps)
            else:
                self.log(line)

        try:
            lines = self.executor.run(full, on_line, interactive=interactive, cwd=cwd)
        except FFmpegExecutionError:
            if self.cancelled:
                raise Cancelled()
            raise
        self.check_cancel()
        return lines

    # ------------------------------------------------------------ Datei-Infos
    def info(self, path: str) -> dict:
        try:
            return self.prober.probe(path)
        except pr.ProbeError as err:
            raise ModuleError(str(err))

    def duration(self, path: str) -> float:
        d = pr.duration(self.info(path))
        if not d:
            raise ModuleError(f"Die Dauer von „{os.path.basename(path)}“ konnte nicht ermittelt werden.")
        return d

    def duration_or_none(self, path: str) -> Optional[float]:
        try:
            return pr.duration(self.prober.probe(path))
        except Exception:
            return None

    def has_audio(self, path: str) -> bool:
        return bool(pr.streams(self.info(path), "audio"))

    def has_video(self, path: str) -> bool:
        return bool(pr.streams(self.info(path), "video"))

    def video_size(self, path: str) -> Tuple[int, int]:
        size = pr.video_size(self.info(path))
        if not size:
            raise ModuleError(f"„{os.path.basename(path)}“ enthält keine Videospur.")
        return size

    def frame_rate(self, path: str) -> Tuple[str, float]:
        return pr.frame_rate(self.info(path))

    def sample_rate(self, path: str) -> int:
        a = pr.streams(self.info(path), "audio")
        return int(a[0].get("sample_rate", 48000)) if a else 48000

    def require_audio(self, path: str):
        if not self.has_audio(path):
            raise ModuleError(f"„{os.path.basename(path)}“ hat keine Tonspur.")

    # ------------------------------------------------------------ Temporäre Dateien
    def temp_path(self, name: str) -> str:
        return os.path.join(self.tmp_dir, name)

    def write_temp(self, name: str, text: str) -> str:
        path = self.temp_path(name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def copy_temp(self, src: str, name: str) -> str:
        path = self.temp_path(name)
        shutil.copyfile(src, path)
        return path
