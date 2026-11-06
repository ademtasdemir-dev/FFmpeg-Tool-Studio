import shlex
from typing import List

from .base import BaseModule, OptionSpec, ModuleError

CAT = "Experten-Modus"


def split_args(text: str) -> List[str]:
    """Zerlegt die Eingabe wie eine Kommandozeile; Windows-Pfade mit Backslash bleiben intakt."""
    lexer = shlex.shlex(text.replace("\n", " "), posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = []
    for tok in lexer:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        tokens.append(tok)
    return tokens


class CustomCommandModule(BaseModule):
    name = "Eigener FFmpeg-Befehl"
    category = CAT
    description = "Beliebige FFmpeg-Parameter. Platzhalter {input} und {output} werden durch die Dateien ersetzt."
    input_kind = "any"
    output_suffix = "_custom"
    options_schema = [
        OptionSpec("args", "FFmpeg-Parameter (ohne „ffmpeg“ am Anfang)", "multiline",
                   "-i {input} -c:v libx264 -crf 23 -c:a aac {output}"),
    ]

    def build_command(self, inp, out, o, ctx):
        try:
            tokens = split_args(o["args"])
        except ValueError as err:
            raise ModuleError(f"Befehl konnte nicht gelesen werden: {err}")
        if tokens and tokens[0].lower() in ("ffmpeg", "ffmpeg.exe"):
            tokens = tokens[1:]
        if any("{input}" in t for t in tokens) and not inp:
            raise ModuleError("Der Befehl nutzt {input}, aber es ist keine Eingabedatei gewählt.")
        if any("{output}" in t for t in tokens) and not out:
            raise ModuleError("Der Befehl nutzt {output}, aber es ist kein Ausgabeziel gesetzt.")
        tokens = [t.replace("{input}", inp).replace("{output}", out) for t in tokens]
        if not tokens:
            raise ModuleError("Bitte Parameter eingeben.")
        return (["-y"] if "-y" not in tokens and "-n" not in tokens else []) + tokens


MODULES: List[BaseModule] = [CustomCommandModule()]
