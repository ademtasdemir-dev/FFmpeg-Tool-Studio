"""Eingabefelder für die Modul-Optionen – je OptionSpec.kind ein passendes Widget mit get()/set()."""
import os
import re
from tkinter import colorchooser, filedialog
from typing import Any, Callable, Dict, List

import customtkinter as ctk

from core import ffutil as fu
from modules.base import OptionSpec

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class OptionField:
    def __init__(self, parent, row: int, spec: OptionSpec, on_change: Callable[[], None]):
        self.spec = spec
        self._on_change = on_change
        kind = spec.kind

        ctk.CTkLabel(parent, text=spec.label + ":", anchor="w", justify="left", wraplength=330).grid(
            row=row, column=0, padx=(8, 6), pady=4, sticky="w")
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=row, column=1, padx=4, pady=4, sticky="w")

        if kind in ("int", "float", "text", "password"):
            self.var = ctk.StringVar(value="" if spec.default is None else str(spec.default))
            width = 120 if kind in ("int", "float") else 300
            ctk.CTkEntry(cell, textvariable=self.var, width=width, show="•" if kind == "password" else "").pack(side="left")
            self.get = self.var.get
            self.set = lambda v: self.var.set("" if v is None else str(v))

        elif kind == "multiline":
            box = ctk.CTkTextbox(cell, width=380, height=78, wrap="word")
            box.insert("1.0", spec.default or "")
            box.pack(side="left")
            self.get = lambda: box.get("1.0", "end-1c")

            def set_text(v):
                box.delete("1.0", "end")
                box.insert("1.0", v or "")
            self.set = set_text

        elif kind == "bool":
            self.var = ctk.BooleanVar(value=bool(spec.default))
            ctk.CTkSwitch(cell, text="", variable=self.var, command=on_change).pack(side="left")
            self.get = self.var.get
            self.set = lambda v: self.var.set(bool(v))

        elif kind == "choice":
            choices = spec.choices if spec.choices is not None else (spec.choices_fn() if spec.choices_fn else {})
            if not choices:
                choices = {"(keine Auswahl verfügbar)": ""}
            self.choices: Dict[str, Any] = choices
            labels = list(choices)
            self.var = ctk.StringVar(value=self._label_for(spec.default, labels))
            ctk.CTkOptionMenu(cell, variable=self.var, values=labels, width=300, dynamic_resizing=False,
                              command=lambda _v: on_change()).pack(side="left")
            self.get = lambda: self.choices.get(self.var.get(), "")
            self.set = lambda v: self.var.set(self._label_for(v, labels))

        elif kind == "file":
            self.var = ctk.StringVar(value=spec.default or "")
            ctk.CTkEntry(cell, textvariable=self.var, width=300).pack(side="left")
            ctk.CTkButton(cell, text="…", width=34, command=self._pick_file).pack(side="left", padx=(6, 0))
            self.get = lambda: self.var.get().strip()
            self.set = lambda v: self.var.set(v or "")

        elif kind == "files":
            self.files: List[str] = list(spec.default or [])
            ctk.CTkButton(cell, text="Hinzufügen", width=96, command=self._add_files).pack(side="left")
            ctk.CTkButton(cell, text="Leeren", width=70, fg_color="gray30",
                          command=lambda: self._set_files([])).pack(side="left", padx=6)
            self.info = ctk.CTkLabel(cell, text="", anchor="w", justify="left")
            self.info.pack(side="left", padx=4)
            self._set_files(self.files)
            self.get = lambda: list(self.files)
            self.set = lambda v: self._set_files(list(v or []))

        elif kind == "color":
            self.var = ctk.StringVar(value=spec.default or "#FFFFFF")
            ctk.CTkEntry(cell, textvariable=self.var, width=90).pack(side="left")
            self.swatch = ctk.CTkButton(cell, text="", width=34, command=self._pick_color, border_width=1,
                                        border_color="gray50")
            self.swatch.pack(side="left", padx=(6, 0))
            self.var.trace_add("write", lambda *_: self._update_swatch())
            self._update_swatch()
            self.get = lambda: self.var.get().strip()
            self.set = lambda v: self.var.set(v or "#FFFFFF")
        else:
            raise ValueError(f"Unbekannte Option: {kind}")

        if spec.hint:
            ctk.CTkLabel(parent, text=spec.hint, text_color="gray60", font=("Segoe UI", 11), anchor="w",
                         justify="left", wraplength=260).grid(row=row, column=2, padx=6, pady=4, sticky="w")

    # ------------------------------------------------------------ Hilfen
    def _label_for(self, value, labels):
        for lbl in labels:
            if self.choices[lbl] == value:
                return lbl
        return labels[0]

    def _pick_file(self):
        path = filedialog.askopenfilename(title=self.spec.label,
                                          filetypes=fu.FILETYPES.get(self.spec.filetypes, fu.FILETYPES["any"]))
        if path:
            self.var.set(path)

    def _add_files(self):
        picked = filedialog.askopenfilenames(title=self.spec.label,
                                             filetypes=fu.FILETYPES.get(self.spec.filetypes, fu.FILETYPES["any"]))
        self._set_files(self.files + list(picked))

    def _set_files(self, files):
        self.files = files
        if not files:
            text = "Keine Dateien gewählt"
        else:
            names = [os.path.basename(f) for f in files]
            text = "\n".join(names[:6]) + (f"\n… und {len(names) - 6} weitere" if len(names) > 6 else "")
        self.info.configure(text=text)

    def _pick_color(self):
        current = self.var.get() if HEX_RE.match(self.var.get()) else "#FFFFFF"
        result = colorchooser.askcolor(color=current, title=self.spec.label)
        if result and result[1]:
            self.var.set(result[1].upper())

    def _update_swatch(self):
        c = self.var.get().strip()
        if HEX_RE.match(c):
            self.swatch.configure(fg_color=c, hover_color=c)

    # ------------------------------------------------------------ Validierung
    def value(self) -> Any:
        """Gibt den geprüften Wert zurück oder wirft ValueError mit verständlicher Meldung."""
        spec, raw = self.spec, self.get()
        label = f"„{spec.label}“"
        if spec.kind in ("int", "float"):
            text = str(raw).strip().replace(",", ".")
            try:
                val = int(text) if spec.kind == "int" else float(text)
            except ValueError:
                raise ValueError(f"{label} muss eine {'ganze ' if spec.kind == 'int' else ''}Zahl sein "
                                 f"(eingegeben: „{raw}“).")
            if spec.min_value is not None and val < spec.min_value:
                raise ValueError(f"{label} muss mindestens {spec.min_value:g} sein.")
            if spec.max_value is not None and val > spec.max_value:
                raise ValueError(f"{label} darf höchstens {spec.max_value:g} sein.")
            return val
        if spec.kind in ("text", "password", "multiline"):
            val = raw.strip() if spec.kind != "multiline" else raw.strip("\n")
            if not val.strip() and not spec.optional:
                raise ValueError(f"{label} darf nicht leer sein.")
            return val
        if spec.kind == "file":
            if not raw:
                if spec.optional:
                    return ""
                raise ValueError(f"Bitte {label} auswählen.")
            if not os.path.isfile(raw):
                raise ValueError(f"{label}: Datei nicht gefunden:\n{raw}")
            return raw
        if spec.kind == "files":
            missing = [f for f in raw if not os.path.isfile(f)]
            if missing:
                raise ValueError(f"{label}: Datei nicht gefunden:\n{missing[0]}")
            return raw
        if spec.kind == "color":
            if not HEX_RE.match(raw):
                raise ValueError(f"{label} muss eine Farbe wie #FF8800 sein.")
            return raw.upper()
        return raw
