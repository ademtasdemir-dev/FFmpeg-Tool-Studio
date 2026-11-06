import subprocess
import shutil
import threading
from typing import List, Callable, Optional

from core.paths import find_tool

# Unter Windows kein Konsolenfenster für FFmpeg-Subprozesse öffnen (wichtig für die EXE).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_ffmpeg() -> str:
    return find_tool("ffmpeg")


class FFmpegExecutionError(Exception):
    """Spezifischer Fehler für fehlgeschlagene FFmpeg-Aufrufe inklusive Log-Ausgabe."""
    def __init__(self, message: str, returncode: int, stderr_log: str):
        super().__init__(f"{message} (Exit-Code: {returncode})")
        self.returncode = returncode
        self.stderr_log = stderr_log


class FFmpegExecutor:
    """Führt FFmpeg aus. Laufende Prozesse können hart abgebrochen (kill) oder
    – bei Aufnahmen/Streams – sauber gestoppt werden (Taste 'q' an FFmpeg)."""

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        self.ffmpeg_bin = ffmpeg_bin or find_ffmpeg()
        if not shutil.which(self.ffmpeg_bin):
            raise FileNotFoundError(
                f"FFmpeg wurde unter '{self.ffmpeg_bin}' nicht gefunden! "
                "Bitte installiere FFmpeg und füge es dem System-PATH hinzu."
            )
        self._process: Optional[subprocess.Popen] = None
        self._interactive = False
        self._lock = threading.Lock()
        self.stop_requested = False

    def kill(self):
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.kill()

    def stop(self):
        """Sauberes Beenden: bei Aufnahmen 'q' senden (Datei bleibt abspielbar), sonst kill."""
        with self._lock:
            proc, interactive = self._process, self._interactive
            self.stop_requested = True
        if not proc or proc.poll() is not None:
            return
        if interactive and proc.stdin:
            try:
                proc.stdin.write("q\n")
                proc.stdin.flush()
            except OSError:
                pass
            # Falls FFmpeg nicht reagiert: nach 8 Sekunden hart beenden.
            threading.Timer(8.0, self.kill).start()
        else:
            self.kill()

    def run(
        self,
        args: List[str],
        line_callback: Optional[Callable[[str], None]] = None,
        interactive: bool = False,
        cwd: Optional[str] = None,
    ) -> List[str]:
        command = [self.ffmpeg_bin] + args
        lines: List[str] = []
        self.stop_requested = False

        try:
            with self._lock:
                self._interactive = interactive
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=NO_WINDOW,
                    universal_newlines=True,  # behandelt auch FFmpegs \r-Fortschrittszeilen als Zeilen
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,
                )
            process = self._process

            for line in process.stderr:
                clean = line.strip()
                if not clean:
                    continue
                lines.append(clean)
                if line_callback:
                    line_callback(clean)
            process.wait()

            if process.returncode != 0 and not (interactive and self.stop_requested):
                raise FFmpegExecutionError(
                    message="FFmpeg-Prozess mit Fehler beendet.",
                    returncode=process.returncode,
                    stderr_log="\n".join(lines[-200:]),
                )
            return lines

        except (subprocess.SubprocessError, OSError) as exc:
            raise FFmpegExecutionError(
                message=f"Systemfehler beim Starten von FFmpeg: {exc}",
                returncode=-1,
                stderr_log="",
            )
        finally:
            with self._lock:
                self._process = None
