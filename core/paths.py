import os
import sys
import shutil


def app_dir() -> str:
    """Ordner der EXE (bzw. von main.py beim Start als Skript)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def resource_dir() -> str:
    """Ordner mit eingebetteten Dateien (PyInstaller entpackt nach sys._MEIPASS)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_tool(name: str) -> str:
    """Sucht ffmpeg/ffprobe: 1) in der EXE eingebettet, 2) neben der EXE, 3) im System-PATH."""
    for base in (getattr(sys, "_MEIPASS", None), app_dir()):
        if not base:
            continue
        for candidate in (name + ".exe", name):
            path = os.path.join(base, candidate)
            if os.path.isfile(path):
                return path
    return shutil.which(name) or name


def user_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "FFmpegToolStudio")
    os.makedirs(path, exist_ok=True)
    return path


def videos_dir() -> str:
    path = os.path.join(os.path.expanduser("~"), "Videos")
    return path if os.path.isdir(path) else os.path.expanduser("~")
