import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from core.context import ModuleError, RunContext  # noqa: F401  (Re-Export für Module)
from core.paths import videos_dir


@dataclass
class OptionSpec:
    """Beschreibt eine einstellbare Option eines Moduls (daraus baut die GUI das Eingabefeld).

    kind:
      "int" / "float" – Zahleneingabe (optional mit min_value / max_value)
      "text"          – einzeilige Texteingabe          "multiline" – mehrzeiliger Text
      "password"      – verdeckte Eingabe (wird nie in Presets/Log gespeichert)
      "bool"          – Schalter
      "choice"        – Auswahlliste; choices = {Anzeigetext: Wert} oder choices_fn() für dynamische Listen
      "file"          – eine Zusatzdatei (filetypes = Schlüssel aus ffutil.FILETYPES)
      "files"         – mehrere Zusatzdateien
      "color"         – Farbe als #RRGGBB mit Farbwähler
    """
    key: str
    label: str
    kind: str
    default: Any = None
    choices: Optional[Dict[str, Any]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    hint: str = ""
    optional: bool = False
    filetypes: str = "any"
    choices_fn: Optional[Callable[[], Dict[str, Any]]] = None


def crf_option(default: int = 20) -> OptionSpec:
    return OptionSpec("crf", "Qualität (CRF, kleiner = besser)", "int", default, min_value=0, max_value=51,
                      hint="18 = sehr gut, 23 = Standard, 28 = klein")


class BaseModule:
    """Gemeinsame Basisklasse für alle FFmpeg-Funktionsmodule."""

    name: str = ""
    category: str = ""
    description: str = ""

    # video | audio | media (Video oder Audio) | image | url | none (keine Eingabe) | any (optional)
    input_kind: str = "video"
    needs_output: bool = True
    output_is_dir: bool = False
    output_ext: Optional[str] = None        # None = Endung der Eingabedatei übernehmen
    output_suffix: str = "_processed"
    interactive: bool = False               # Aufnahme/Stream: "Stoppen" beendet sauber
    options_schema: List[OptionSpec] = []

    # ------------------------------------------------------------ Optionen
    def default_options(self) -> Dict[str, Any]:
        return {spec.key: spec.default for spec in self.options_schema}

    def resolve(self, options: Dict[str, Any]) -> Dict[str, Any]:
        merged = self.default_options()
        merged.update({k: v for k, v in options.items() if v is not None})
        return merged

    # ------------------------------------------------------------ Ausgabe-Vorschlag
    def suggested_ext(self, options: Dict[str, Any]) -> Optional[str]:
        return self.output_ext

    def default_output(self, options: Dict[str, Any]) -> str:
        """Für Module ohne Eingabedatei (Aufnahmen): Datei im Videos-Ordner mit Zeitstempel."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = self.output_suffix.strip("_") or "ausgabe"
        return os.path.join(videos_dir(), f"{base}_{stamp}{self.suggested_ext(options) or '.mp4'}")

    # ------------------------------------------------------------ Ausführung
    def build_command(self, inp: str, out: str, o: Dict[str, Any], ctx: RunContext) -> List[str]:
        raise NotImplementedError

    def expected_duration(self, inp: str, o: Dict[str, Any], ctx: RunContext) -> Optional[float]:
        if inp and self.input_kind in ("video", "audio", "media"):
            return ctx.duration_or_none(inp)
        return None

    def execute(self, inp: str, out: str, o: Dict[str, Any], ctx: RunContext) -> Optional[str]:
        """Standard: ein FFmpeg-Aufruf. Rückgabe: optionaler Ergebnistext für die Abschlussmeldung."""
        args = self.build_command(inp, out, o, ctx)
        ctx.run(args, duration=self.expected_duration(inp, o, ctx), interactive=self.interactive)
        return None
