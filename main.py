import os
import queue
import re
import threading
import time
import traceback
from dataclasses import dataclass
from tkinter import filedialog, messagebox
from typing import Any, Dict, List, Optional

import customtkinter as ctk

try:  # Drag & Drop ist optional – ohne tkinterdnd2 läuft das Tool trotzdem
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # pragma: no cover
    HAS_DND = False

from core import ffutil as fu
from core.context import Cancelled, ModuleError, RunContext
from core.executor import FFmpegExecutionError, FFmpegExecutor
from core.hardware import CPU_INFO, HardwareAccelerator
from core.paths import resource_dir
from core.presets import JsonStore, PresetStore
from core.probe import Prober
from modules.base import BaseModule
from modules.registry import ALL, CATEGORIES
from ui.option_fields import OptionField

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "FFmpeg Tool Studio"
POLL_MS = 80
MAX_LOG_LINES = 5000
INPUT_LABELS = {
    "video": "Eingabevideo:", "audio": "Audiodatei:", "media": "Eingabedatei:", "image": "Bild:",
    "url": "Stream-URL:", "any": "Datei (optional):",
}
STATUS_COLORS = {"Wartet": "gray70", "Läuft": "#4aa3ff", "Fertig": "#4cc27a", "Fehler": "#e05555",
                 "Abgebrochen": "#d0a040"}
DEFAULT_PRESET = "(Standardwerte)"

_Base = (ctk.CTk, TkinterDnD.DnDWrapper) if HAS_DND else (ctk.CTk,)


@dataclass
class Job:
    id: int
    module: str
    inp: str
    out: str
    options: Dict[str, Any]
    status: str = "Wartet"
    message: str = ""


def _fmt_secs(s: float) -> str:
    s = int(max(0, s))
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


class FFmpegStudioApp(*_Base):
    def __init__(self):
        super().__init__()
        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass
        self.title(APP_TITLE)
        self.geometry("1060x940")
        self.minsize(900, 760)

        self.executor = FFmpegExecutor()
        self.prober = Prober()
        self.hw: Dict = dict(CPU_INFO)
        self.presets = PresetStore()
        self.settings = JsonStore("settings.json")

        self.jobs: List[Job] = []
        self._next_job_id = 1
        self._ui_queue: "queue.Queue[tuple]" = queue.Queue()
        self._running = False
        self._cancel_all = False
        self._queued_ids: set = set()
        self._batch_results: List[Job] = []
        self._ctx: Optional[RunContext] = None
        self._current_job: Optional[Job] = None
        self._job_started = 0.0
        self._last_auto_output = ""
        self.fields: Dict[str, OptionField] = {}

        self.input_var = ctk.StringVar()
        self.output_var = ctk.StringVar()
        self.gpu_var = ctk.BooleanVar(value=bool(self.settings.data.get("gpu", True)))

        self._build_ui()
        first_cat = self.settings.data.get("category") if self.settings.data.get("category") in CATEGORIES \
            else next(iter(CATEGORIES))
        self.cat_var.set(first_cat)
        self._on_category(first_cat, preferred=self.settings.data.get("module"))
        self.input_var.trace_add("write", lambda *_: self._suggest_output())

        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        threading.Thread(target=self._detect_hw, daemon=True).start()
        self.after(POLL_MS, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================================== UI-Aufbau
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(7, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 2))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text=APP_TITLE, font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w")
        self.hw_label = ctk.CTkLabel(head, text="Grafikkarte wird geprüft …", text_color="gray60")
        self.hw_label.grid(row=0, column=1, sticky="w", padx=14)
        self.gpu_switch = ctk.CTkSwitch(head, text="GPU-Encoding", variable=self.gpu_var, state="disabled")
        self.gpu_switch.grid(row=0, column=2, sticky="e")

        sel = ctk.CTkFrame(self)
        sel.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        sel.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(sel, text="Kategorie:").grid(row=0, column=0, padx=(12, 6), pady=(10, 4), sticky="w")
        self.cat_var = ctk.StringVar()
        ctk.CTkOptionMenu(sel, variable=self.cat_var, values=list(CATEGORIES), width=240,
                          command=lambda c: self._on_category(c)).grid(row=0, column=1, pady=(10, 4), sticky="w")
        ctk.CTkLabel(sel, text="Funktion:").grid(row=0, column=2, padx=(16, 6), pady=(10, 4), sticky="w")
        self.mod_var = ctk.StringVar()
        self.mod_menu = ctk.CTkOptionMenu(sel, variable=self.mod_var, values=["-"], dynamic_resizing=False,
                                          command=lambda m: self._on_module())
        self.mod_menu.grid(row=0, column=3, padx=(0, 12), pady=(10, 4), sticky="ew")
        self.desc_label = ctk.CTkLabel(sel, text="", text_color="gray70", anchor="w", justify="left",
                                       wraplength=980)
        self.desc_label.grid(row=1, column=0, columnspan=4, padx=12, pady=(0, 10), sticky="w")

        io = ctk.CTkFrame(self)
        io.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        io.grid_columnconfigure(1, weight=1)
        self.in_label = ctk.CTkLabel(io, text="Eingabevideo:", width=130, anchor="w")
        self.in_entry = ctk.CTkEntry(io, textvariable=self.input_var,
                                     placeholder_text="Datei wählen oder ins Fenster ziehen")
        self.in_browse = ctk.CTkButton(io, text="Durchsuchen", width=110, command=self._pick_input)
        self.in_info = ctk.CTkButton(io, text="Info", width=60, fg_color="gray30", command=self._show_info)
        self.out_label = ctk.CTkLabel(io, text="Ausgabeziel:", width=130, anchor="w")
        self.out_entry = ctk.CTkEntry(io, textvariable=self.output_var)
        self.out_browse = ctk.CTkButton(io, text="Speichern unter", width=110, command=self._pick_output)
        self.in_widgets = [self.in_label, self.in_entry, self.in_browse, self.in_info]
        self.out_widgets = [self.out_label, self.out_entry, self.out_browse]
        self.in_label.grid(row=0, column=0, padx=(12, 4), pady=(10, 4), sticky="w")
        self.in_entry.grid(row=0, column=1, padx=4, pady=(10, 4), sticky="ew")
        self.in_browse.grid(row=0, column=2, padx=4, pady=(10, 4))
        self.in_info.grid(row=0, column=3, padx=(4, 12), pady=(10, 4))
        self.out_label.grid(row=1, column=0, padx=(12, 4), pady=(4, 10), sticky="w")
        self.out_entry.grid(row=1, column=1, padx=4, pady=(4, 10), sticky="ew")
        self.out_browse.grid(row=1, column=2, padx=4, pady=(4, 10))

        pre = ctk.CTkFrame(self, fg_color="transparent")
        pre.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 0))
        ctk.CTkLabel(pre, text="Optionen", font=("Segoe UI", 14, "bold")).pack(side="left", padx=(2, 16))
        ctk.CTkLabel(pre, text="Preset:").pack(side="left")
        self.preset_var = ctk.StringVar(value=DEFAULT_PRESET)
        self.preset_menu = ctk.CTkOptionMenu(pre, variable=self.preset_var, values=[DEFAULT_PRESET], width=200,
                                             command=self._apply_preset)
        self.preset_menu.pack(side="left", padx=6)
        ctk.CTkButton(pre, text="Speichern …", width=100, command=self._save_preset).pack(side="left", padx=4)
        ctk.CTkButton(pre, text="Löschen", width=80, fg_color="gray30", command=self._delete_preset).pack(side="left")

        self.options_frame = ctk.CTkScrollableFrame(self, height=250)
        self.options_frame.grid(row=4, column=0, sticky="ew", padx=16, pady=6)
        self.options_frame.grid_columnconfigure(2, weight=1)

        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 2))
        act.grid_columnconfigure(0, weight=1)
        self.run_btn = ctk.CTkButton(act, text="▶  Start", height=40, font=("Segoe UI", 14, "bold"),
                                     command=self._start_now)
        self.run_btn.grid(row=0, column=0, sticky="ew")
        self.queue_btn = ctk.CTkButton(act, text="+ Warteschlange", height=40, width=140, fg_color="gray30",
                                       command=self._add_current_to_queue)
        self.queue_btn.grid(row=0, column=1, padx=(8, 0))
        self.batch_files_btn = ctk.CTkButton(act, text="Stapel: Dateien …", height=40, width=140, fg_color="gray30",
                                             command=self._batch_files)
        self.batch_files_btn.grid(row=0, column=2, padx=(8, 0))
        self.batch_dir_btn = ctk.CTkButton(act, text="Stapel: Ordner …", height=40, width=140, fg_color="gray30",
                                           command=self._batch_folder)
        self.batch_dir_btn.grid(row=0, column=3, padx=(8, 0))
        self.cancel_btn = ctk.CTkButton(act, text="Abbrechen", height=40, width=120, state="disabled",
                                        fg_color="#8a2b2b", hover_color="#a33535", command=self._cancel)
        self.cancel_btn.grid(row=0, column=4, padx=(8, 0))

        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.grid(row=6, column=0, sticky="ew", padx=16, pady=(6, 0))
        prog.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(prog, height=12)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress_label = ctk.CTkLabel(prog, text="Bereit.", anchor="w", text_color="gray70")
        self.progress_label.grid(row=1, column=0, sticky="ew")

        self.tabs = ctk.CTkTabview(self, height=220)
        self.tabs.grid(row=7, column=0, sticky="nsew", padx=16, pady=(0, 12))
        log_tab = self.tabs.add("Log")
        q_tab = self.tabs.add("Warteschlange")
        log_tab.grid_columnconfigure(0, weight=1)
        log_tab.grid_rowconfigure(0, weight=1)
        self.log_view = ctk.CTkTextbox(log_tab, font=("Consolas", 11), wrap="none")
        self.log_view.grid(row=0, column=0, sticky="nsew")

        q_tab.grid_columnconfigure(0, weight=1)
        q_tab.grid_rowconfigure(1, weight=1)
        qbar = ctk.CTkFrame(q_tab, fg_color="transparent")
        qbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkButton(qbar, text="▶  Warteschlange starten", width=190, command=self._start_queue).pack(side="left")
        ctk.CTkButton(qbar, text="Erledigte entfernen", width=150, fg_color="gray30",
                      command=self._remove_done).pack(side="left", padx=8)
        ctk.CTkButton(qbar, text="Alles leeren", width=110, fg_color="gray30", command=self._clear_queue).pack(side="left")
        self.queue_info = ctk.CTkLabel(qbar, text="", text_color="gray70")
        self.queue_info.pack(side="left", padx=12)
        self.queue_list = ctk.CTkScrollableFrame(q_tab)
        self.queue_list.grid(row=1, column=0, sticky="nsew")
        self.queue_list.grid_columnconfigure(2, weight=1)
        self._render_queue()

    # ================================================================== Modulwahl
    @property
    def module(self) -> BaseModule:
        return ALL[self.mod_var.get()]

    def _on_category(self, cat: str, preferred: Optional[str] = None):
        names = [m.name for m in CATEGORIES[cat]]
        self.mod_menu.configure(values=names)
        self.mod_var.set(preferred if preferred in names else names[0])
        self._on_module()

    def _on_module(self):
        m = self.module
        self.desc_label.configure(text=m.description)

        # Eingabezeile je nach Modul
        if m.input_kind == "none":
            for w in self.in_widgets:
                w.grid_remove()
        else:
            for w in self.in_widgets:
                w.grid()
            self.in_label.configure(text=INPUT_LABELS.get(m.input_kind, "Eingabedatei:"))
            if m.input_kind == "url":
                self.in_browse.grid_remove()
                self.in_info.grid_remove()
        # Ausgabezeile
        if m.needs_output:
            for w in self.out_widgets:
                w.grid()
            self.out_label.configure(text="Zielordner:" if m.output_is_dir else "Ausgabeziel:")
        else:
            for w in self.out_widgets:
                w.grid_remove()
        batch_ok = m.input_kind not in ("none", "url")
        for b in (self.batch_files_btn, self.batch_dir_btn):
            b.configure(state="normal" if batch_ok else "disabled")

        # Optionsfelder neu aufbauen
        for child in self.options_frame.winfo_children():
            child.destroy()
        self.fields.clear()
        if not m.options_schema:
            ctk.CTkLabel(self.options_frame, text="Diese Funktion hat keine Einstellungen.",
                         text_color="gray60").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        for row, spec in enumerate(m.options_schema):
            self.fields[spec.key] = OptionField(self.options_frame, row, spec, self._suggest_output)
        try:
            self.options_frame._parent_canvas.yview_moveto(0)
        except Exception:
            pass

        self._refresh_presets()
        self.output_var.set("")
        self._last_auto_output = ""
        self._suggest_output()

    # ================================================================== Optionen
    def _collect_options(self, m: BaseModule) -> Dict[str, Any]:
        return {key: field.value() for key, field in self.fields.items()}

    def _choice_options(self) -> Dict[str, Any]:
        """Optionen ohne Prüfung – reicht für Endungs-Vorschläge."""
        o = self.module.default_options()
        for key, f in self.fields.items():
            if f.spec.kind == "choice":
                o[key] = f.get()
        return o

    def _output_for(self, m: BaseModule, inp: str, o: Dict[str, Any]) -> str:
        base, in_ext = os.path.splitext(inp)
        if m.output_is_dir:
            return base + m.output_suffix
        ext = m.suggested_ext(o) or in_ext or ".mp4"
        out = f"{base}{m.output_suffix}{ext}"
        if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(inp)):
            out = f"{base}_converted{ext}"
        return out

    def _suggest_output(self):
        m = self.module
        if not m.needs_output:
            return
        current = self.output_var.get()
        if current and current != self._last_auto_output:
            return  # vom Nutzer geändert -> nicht überschreiben
        o = self._choice_options()
        inp = self.input_var.get().strip()
        if m.input_kind in ("none", "url"):
            suggestion = m.default_output(o)
        elif inp and m.input_kind != "url":
            suggestion = self._output_for(m, inp, o)
        else:
            return
        self._last_auto_output = suggestion
        self.output_var.set(suggestion)

    # ================================================================== Presets
    def _refresh_presets(self):
        names = [DEFAULT_PRESET] + self.presets.names(self.module.name)
        self.preset_menu.configure(values=names)
        self.preset_var.set(DEFAULT_PRESET)

    def _apply_preset(self, name: str):
        m = self.module
        values = m.default_options() if name == DEFAULT_PRESET else {**m.default_options(),
                                                                     **self.presets.get(m.name, name)}
        for key, f in self.fields.items():
            if f.spec.kind != "password" and key in values:
                f.set(values[key])
        self._suggest_output()

    def _save_preset(self):
        m = self.module
        if not m.options_schema:
            messagebox.showinfo("Preset", "Diese Funktion hat keine Einstellungen.")
            return
        try:
            opts = self._collect_options(m)
        except ValueError as err:
            messagebox.showerror("Ungültige Option", str(err))
            return
        name = ctk.CTkInputDialog(title="Preset speichern", text="Name für das Preset:").get_input()
        if not name or not name.strip() or name.strip() == DEFAULT_PRESET:
            return
        opts = {k: v for k, v in opts.items() if self.fields[k].spec.kind != "password"}
        self.presets.put(m.name, name.strip(), opts)
        self._refresh_presets()
        self.preset_var.set(name.strip())

    def _delete_preset(self):
        name = self.preset_var.get()
        if name == DEFAULT_PRESET:
            return
        if messagebox.askyesno("Preset löschen", f"Preset „{name}“ löschen?"):
            self.presets.delete(self.module.name, name)
            self._refresh_presets()

    # ================================================================== Dateien
    def _pick_input(self):
        m = self.module
        path = filedialog.askopenfilename(title="Eingabedatei wählen",
                                          filetypes=fu.FILETYPES.get(m.input_kind, fu.FILETYPES["any"]))
        if path:
            self._set_input(path)

    def _set_input(self, path: str):
        self.output_var.set("")
        self._last_auto_output = ""
        self.input_var.set(path)

    def _pick_output(self):
        m = self.module
        current = self.output_var.get()
        if m.output_is_dir:
            path = filedialog.askdirectory(title="Zielordner wählen",
                                           initialdir=os.path.dirname(current) if current else None)
        else:
            ext = os.path.splitext(current)[1] if current else ""
            path = filedialog.asksaveasfilename(
                title="Ausgabedatei wählen",
                initialdir=os.path.dirname(current) if current else None,
                initialfile=os.path.basename(current) if current else "",
                defaultextension=ext,
                filetypes=[(f"{ext} Datei", f"*{ext}"), ("Alle Dateien", "*.*")] if ext else [("Alle Dateien", "*.*")],
            )
        if path:
            self.output_var.set(os.path.normpath(path))

    def _on_drop(self, event):
        paths = [p for p in self.tk.splitlist(event.data)]
        if not paths:
            return
        m = self.module
        if len(paths) == 1 and os.path.isfile(paths[0]):
            if m.input_kind in ("none", "url"):
                messagebox.showinfo("Drag & Drop", "Diese Funktion braucht keine Eingabedatei.")
                return
            self._set_input(paths[0])
            return
        files = []
        for p in paths:
            files += self._files_in_folder(p, m) if os.path.isdir(p) else [p]
        if files and messagebox.askyesno("Stapelverarbeitung",
                                         f"{len(files)} Dateien als Stapel mit „{m.name}“ verarbeiten?"):
            self._add_batch(files)

    # ================================================================== Aufträge
    def _build_job(self, inp: Optional[str] = None, quiet: bool = False) -> Optional[Job]:
        """Liest das Formular, prüft alles und erzeugt einen Auftrag (oder zeigt einen Fehler)."""
        m = self.module
        try:
            opts = self._collect_options(m)
        except ValueError as err:
            messagebox.showerror("Ungültige Option", str(err))
            return None

        inp = (self.input_var.get() if inp is None else inp).strip()
        if m.input_kind in ("video", "audio", "media", "image") and not os.path.isfile(inp):
            messagebox.showerror("Fehler", "Bitte eine gültige Eingabedatei wählen!")
            return None
        if m.input_kind == "url" and not inp:
            messagebox.showerror("Fehler", "Bitte eine Stream-URL eingeben!")
            return None
        if m.input_kind == "any" and inp and not os.path.isfile(inp):
            messagebox.showerror("Fehler", f"Datei nicht gefunden:\n{inp}")
            return None
        if m.input_kind == "none":
            inp = ""

        out = ""
        if m.needs_output:
            if self.output_var.get() == self._last_auto_output and m.input_kind in ("none", "url"):
                self._suggest_output()  # neuer Zeitstempel für Aufnahmen
            out = self.output_var.get().strip()
            if not out:
                messagebox.showerror("Fehler", "Bitte ein Ausgabeziel angeben!")
                return None
            out = os.path.abspath(out)
            parent = os.path.dirname(out)
            if not os.path.isdir(parent):
                messagebox.showerror("Fehler", f"Der Zielordner existiert nicht:\n{parent}")
                return None
            if inp and os.path.normcase(out) == os.path.normcase(os.path.abspath(inp)):
                messagebox.showerror("Fehler", "Ausgabe darf nicht die Eingabedatei sein.")
                return None
            if not quiet and not m.output_is_dir and "%" not in out and os.path.exists(out):
                if not messagebox.askyesno("Überschreiben?", f"Die Datei existiert bereits:\n{out}\n\nÜberschreiben?"):
                    return None
        job = Job(self._next_job_id, m.name, inp, out, opts)
        self._next_job_id += 1
        return job

    def _start_now(self):
        if self._running:
            messagebox.showinfo("Läuft bereits", "Es läuft bereits ein Auftrag. Neue Aufträge bitte über "
                                                 "„+ Warteschlange“ einreihen.")
            return
        job = self._build_job()
        if job:
            self.jobs.append(job)
            self._render_queue()
            self._run_jobs([job.id])

    def _add_current_to_queue(self):
        job = self._build_job()
        if job:
            self.jobs.append(job)
            self._render_queue()
            self.tabs.set("Warteschlange")

    def _files_in_folder(self, folder: str, m: BaseModule) -> List[str]:
        exts = fu.KIND_EXTS.get(m.input_kind)
        result = []
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and (exts is None or os.path.splitext(name)[1].lower() in exts):
                result.append(path)
        return result

    def _batch_files(self):
        m = self.module
        files = filedialog.askopenfilenames(title="Dateien für Stapelverarbeitung",
                                            filetypes=fu.FILETYPES.get(m.input_kind, fu.FILETYPES["any"]))
        if files:
            self._add_batch(list(files))

    def _batch_folder(self):
        folder = filedialog.askdirectory(title="Ordner für Stapelverarbeitung")
        if not folder:
            return
        files = self._files_in_folder(folder, self.module)
        if not files:
            messagebox.showinfo("Stapel", "In diesem Ordner wurden keine passenden Dateien gefunden.")
            return
        self._add_batch(files)

    def _add_batch(self, files: List[str]):
        m = self.module
        try:
            opts = self._collect_options(m)
        except ValueError as err:
            messagebox.showerror("Ungültige Option", str(err))
            return
        new_jobs, existing = [], 0
        for f in files:
            out = self._output_for(m, f, opts) if m.needs_output else ""
            if out and os.path.exists(out) and "%" not in out:
                existing += 1
            new_jobs.append(Job(self._next_job_id, m.name, f, out, dict(opts)))
            self._next_job_id += 1
        if existing and not messagebox.askyesno("Überschreiben?", f"{existing} Ausgabedatei(en) existieren bereits "
                                                                  f"und würden überschrieben. Fortfahren?"):
            return
        self.jobs += new_jobs
        self._render_queue()
        self.tabs.set("Warteschlange")
        if not self._running and messagebox.askyesno("Stapel", f"{len(new_jobs)} Aufträge hinzugefügt.\n\nJetzt starten?"):
            self._run_jobs([j.id for j in new_jobs])

    def _show_info(self):
        inp = self.input_var.get().strip()
        if not os.path.isfile(inp):
            messagebox.showerror("Info", "Bitte zuerst eine Datei wählen.")
            return
        if self._running:
            messagebox.showinfo("Info", "Bitte warten, bis der laufende Auftrag fertig ist.")
            return
        job = Job(self._next_job_id, "Medieninfo anzeigen", inp, "", {})
        self._next_job_id += 1
        self.jobs.append(job)
        self._render_queue()
        self._run_jobs([job.id])

    # ================================================================== Warteschlange (Anzeige)
    def _render_queue(self):
        for child in self.queue_list.winfo_children():
            child.destroy()
        if not self.jobs:
            ctk.CTkLabel(self.queue_list, text="Keine Aufträge. Über „+ Warteschlange“ oder „Stapel“ hinzufügen.",
                         text_color="gray60").grid(row=0, column=0, columnspan=3, padx=8, pady=8, sticky="w")
        for row, job in enumerate(self.jobs):
            ctk.CTkLabel(self.queue_list, text=job.status, width=90, anchor="w",
                         text_color=STATUS_COLORS.get(job.status, "gray70")).grid(row=row, column=0, padx=6, sticky="w")
            ctk.CTkLabel(self.queue_list, text=job.module, anchor="w", width=300).grid(row=row, column=1, padx=6,
                                                                                       sticky="w")
            name = os.path.basename(job.inp) if job.inp else os.path.basename(job.out) or "–"
            text = name + (f"   →   {job.message.splitlines()[0]}" if job.message else "")
            ctk.CTkLabel(self.queue_list, text=text, anchor="w").grid(row=row, column=2, padx=6, sticky="w")
            if job.status in ("Wartet", "Fehler", "Abgebrochen", "Fertig") and not (self._running and job is self._current_job):
                ctk.CTkButton(self.queue_list, text="✕", width=28, height=24, fg_color="gray30",
                              command=lambda j=job: self._remove_job(j)).grid(row=row, column=3, padx=6, pady=1)
        pending = sum(1 for j in self.jobs if j.status == "Wartet")
        self.queue_info.configure(text=f"{len(self.jobs)} Aufträge, {pending} wartend")

    def _remove_job(self, job: Job):
        if self._running and job.status == "Wartet" and job.id in self._queued_ids:
            self._queued_ids.discard(job.id)
        if job in self.jobs:
            self.jobs.remove(job)
        self._render_queue()

    def _remove_done(self):
        self.jobs = [j for j in self.jobs if j.status in ("Wartet", "Läuft")]
        self._render_queue()

    def _clear_queue(self):
        if self._running:
            messagebox.showinfo("Warteschlange", "Bitte zuerst den laufenden Auftrag abbrechen.")
            return
        self.jobs.clear()
        self._render_queue()

    def _start_queue(self):
        if self._running:
            messagebox.showinfo("Läuft bereits", "Die Warteschlange läuft bereits.")
            return
        ids = [j.id for j in self.jobs if j.status == "Wartet"]
        if not ids:
            messagebox.showinfo("Warteschlange", "Keine wartenden Aufträge.")
            return
        self._run_jobs(ids)

    # ================================================================== Ausführung
    def _run_jobs(self, ids: List[int]):
        self._running = True
        self._cancel_all = False
        self._queued_ids = set(ids)
        self._batch_results: List[Job] = []
        self._set_running(True)
        self.log_view.delete("1.0", "end")
        self.tabs.set("Log")
        jobs = {j.id: j for j in self.jobs}
        ordered = [jobs[i] for i in ids if i in jobs]
        threading.Thread(target=self._worker, args=(ordered, self.gpu_var.get() and self.hw.get("gpu", False)),
                         daemon=True).start()

    def _worker(self, jobs: List[Job], use_gpu: bool):
        """Hintergrund-Thread: fasst die GUI NIE direkt an, sondern nur über die Queue."""
        post = self._ui_queue.put
        for job in jobs:
            if self._cancel_all:
                break
            if job.id not in self._queued_ids:
                continue  # inzwischen aus der Warteschlange entfernt
            module = ALL[job.module]
            post(("job_start", job.id))
            ctx = RunContext(self.executor, self.prober, self.hw, use_gpu,
                             log=lambda s: post(("log", s)),
                             progress=lambda p: post(("progress", p)),
                             stats=lambda s: post(("stats", s)))
            self._ctx = ctx
            status, msg = "Fertig", ""
            try:
                msg = module.execute(job.inp, job.out, module.resolve(job.options), ctx) or ""
            except Cancelled:
                status, msg = "Abgebrochen", "Vom Benutzer abgebrochen."
            except ModuleError as err:
                status, msg = "Fehler", str(err)
            except FFmpegExecutionError as err:
                tail = "\n".join(err.stderr_log.splitlines()[-10:])
                status, msg = "Fehler", f"{err}\n\n{tail}"
            except Exception as err:
                status, msg = "Fehler", f"Unerwarteter Fehler: {err}"
                post(("log", traceback.format_exc()))
            finally:
                self._ctx = None
                ctx.cleanup()
            post(("job_end", job.id, status, msg))
        post(("finished",))

    def _poll_queue(self):
        log_lines: List[str] = []
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    log_lines.append(msg[1])
                    continue
                if log_lines:
                    self._append_log(log_lines)
                    log_lines = []
                self._handle_message(msg)
        except queue.Empty:
            pass
        if log_lines:
            self._append_log(log_lines)
        self.after(POLL_MS, self._poll_queue)

    def _handle_message(self, msg: tuple):
        kind = msg[0]
        if kind == "hw":
            self._apply_hw(msg[1])
        elif kind == "job_start":
            job = self._job(msg[1])
            if job:
                job.status = "Läuft"
                self._current_job = job
                self._job_started = time.time()
                interactive = ALL[job.module].interactive
                self.cancel_btn.configure(text="■  Stoppen" if interactive else "Abbrechen")
                self._set_progress(0)
                self.progress_label.configure(text=f"Läuft: {job.module} – {os.path.basename(job.inp or job.out)}")
                self._append_log([f"=== {job.module}: {job.inp or job.out} ==="])
                self._render_queue()
        elif kind == "progress":
            self._set_progress(msg[1])
        elif kind == "stats":
            self._update_stats(msg[1])
        elif kind == "job_end":
            job = self._job(msg[1])
            if job:
                job.status, job.message = msg[2], msg[3]
                self._batch_results.append(job)
                symbol = {"Fertig": "✔", "Fehler": "✖", "Abgebrochen": "■"}.get(job.status, "")
                self._append_log([f"{symbol} {job.status}" + (f": {job.message}" if job.message else ""), ""])
                self._render_queue()
        elif kind == "finished":
            self._finish_run()

    def _finish_run(self):
        self._running = False
        self._current_job = None
        self._set_running(False)
        results = self._batch_results
        self._render_queue()
        if not results:
            self.progress_label.configure(text="Bereit.")
            return
        if len(results) == 1:
            job = results[0]
            self.progress_label.configure(text=f"{job.status}: {job.module}")
            if job.status == "Fertig":
                self._set_progress(1)
                text = job.message or "Verarbeitung abgeschlossen!"
                if job.out and ALL[job.module].needs_output:
                    text += f"\n\nGespeichert unter:\n{job.out}"
                messagebox.showinfo("Fertig", text)
            elif job.status == "Fehler":
                messagebox.showerror("Fehler", job.message)
            return
        done = sum(1 for j in results if j.status == "Fertig")
        errors = sum(1 for j in results if j.status == "Fehler")
        cancelled = sum(1 for j in results if j.status == "Abgebrochen")
        summary = f"{done} fertig, {errors} mit Fehler, {cancelled} abgebrochen"
        self.progress_label.configure(text=f"Warteschlange beendet: {summary}")
        (messagebox.showwarning if errors else messagebox.showinfo)("Warteschlange beendet", summary)

    def _job(self, job_id: int) -> Optional[Job]:
        return next((j for j in self.jobs if j.id == job_id), None)

    # ================================================================== Fortschritt
    def _set_progress(self, p: Optional[float]):
        if p is None:
            if self.progress.cget("mode") != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start()
            return
        if self.progress.cget("mode") != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress.set(max(0.0, min(1.0, p)))
        self._last_progress = p

    def _update_stats(self, line: str):
        if not self._current_job:
            return
        elapsed = time.time() - self._job_started
        parts = [f"Läuft: {self._current_job.module}", f"verstrichen {_fmt_secs(elapsed)}"]
        if self.progress.cget("mode") == "determinate":
            p = self.progress.get()
            if 0.01 < p < 1:
                parts.insert(1, f"{p * 100:.0f} %")
                parts.append(f"Rest ca. {_fmt_secs(elapsed * (1 - p) / p)}")
        speed = re.search(r"speed=\s*([\d.]+x)", line)
        if speed:
            parts.append(f"Tempo {speed.group(1)}")
        size = re.search(r"size=\s*(\d+)(KiB|kB|MiB|MB)", line)
        if size and size.group(1) != "0":
            n = int(size.group(1))
            parts.append(f"{n / 1024:.1f} MB" if size.group(2) in ("KiB", "kB") else f"{n} MB")
        self.progress_label.configure(text="  ·  ".join(parts))

    def _append_log(self, lines: List[str]):
        self.log_view.insert("end", "\n".join(lines) + "\n")
        count = int(self.log_view.index("end-1c").split(".")[0])
        if count > MAX_LOG_LINES:
            self.log_view.delete("1.0", f"{count - MAX_LOG_LINES}.0")
        self.log_view.see("end")

    def _set_running(self, running: bool):
        self.run_btn.configure(state="disabled" if running else "normal", text="Läuft …" if running else "▶  Start")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        if not running:
            self.cancel_btn.configure(text="Abbrechen")
            if self.progress.cget("mode") == "indeterminate":
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self.progress.set(0)

    def _cancel(self):
        ctx, job = self._ctx, self._current_job
        if not ctx or not job:
            return
        if ALL[job.module].interactive:
            ctx.stop()  # Aufnahme/Stream sauber beenden -> zählt als fertig
            self.progress_label.configure(text="Wird gestoppt …")
            return
        pending = sum(1 for j in self.jobs if j.status == "Wartet" and j.id in self._queued_ids)
        if pending and not messagebox.askyesno("Abbrechen", f"Auch die {pending} wartenden Aufträge abbrechen?\n\n"
                                                            "Ja = alles stoppen, Nein = nur den aktuellen"):
            ctx.cancel()
            return
        self._cancel_all = True
        ctx.cancel()

    # ================================================================== Hardware
    def _detect_hw(self):
        self._ui_queue.put(("hw", HardwareAccelerator.detect(self.executor.ffmpeg_bin)))

    def _apply_hw(self, hw: Dict):
        self.hw = hw
        if hw.get("gpu"):
            self.hw_label.configure(text=f"Grafikkarte: {hw['label']} verfügbar", text_color="#4cc27a")
            self.gpu_switch.configure(state="normal", text=f"GPU-Encoding ({hw['label']})")
        else:
            self.hw_label.configure(text="Keine nutzbare GPU gefunden – Encoding über CPU", text_color="gray60")
            self.gpu_var.set(False)

    # ================================================================== Beenden
    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("Beenden?", "Es läuft noch ein Auftrag. Abbrechen und beenden?"):
                return
            self._cancel_all = True
            if self._ctx:
                job = self._current_job
                (self._ctx.stop if job and ALL[job.module].interactive else self._ctx.cancel)()
        try:
            self.settings.data.update({"gpu": bool(self.gpu_var.get()) if self.hw.get("gpu") else
                                       self.settings.data.get("gpu", True),
                                       "category": self.cat_var.get(), "module": self.mod_var.get()})
            self.settings.save()
        except OSError:
            pass
        self.destroy()


def main():
    try:
        app = FFmpegStudioApp()
    except FileNotFoundError as err:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("FFmpeg nicht gefunden",
                             f"{err}\n\nAlternativ: ffmpeg.exe in denselben Ordner wie diese EXE legen.")
        raise SystemExit(1)
    try:
        app.iconbitmap(os.path.join(resource_dir(), "app.ico"))
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
