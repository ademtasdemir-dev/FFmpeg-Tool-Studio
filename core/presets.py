import json
import os
from typing import Any, Dict, List

from core.paths import user_data_dir


class JsonStore:
    """Kleine JSON-Datei in %APPDATA%\\FFmpegToolStudio (Presets, Einstellungen)."""

    def __init__(self, filename: str):
        self.path = os.path.join(user_data_dir(), filename)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data: Dict[str, Any] = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


class PresetStore(JsonStore):
    """Presets pro Modul: {Modulname: {Presetname: {Option: Wert}}}"""

    def __init__(self):
        super().__init__("presets.json")

    def names(self, module: str) -> List[str]:
        return sorted(self.data.get(module, {}))

    def get(self, module: str, name: str) -> Dict[str, Any]:
        return dict(self.data.get(module, {}).get(name, {}))

    def put(self, module: str, name: str, options: Dict[str, Any]):
        self.data.setdefault(module, {})[name] = options
        self.save()

    def delete(self, module: str, name: str):
        self.data.get(module, {}).pop(name, None)
        self.save()
