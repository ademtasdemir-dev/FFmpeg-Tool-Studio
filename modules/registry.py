"""Zentrale Liste aller Module, gruppiert nach Kategorie (Reihenfolge = Anzeige in der GUI)."""
from collections import OrderedDict
from typing import Dict, List

from . import analysis, audio, capture, color, edit, expert, export, geometry, images, meta, overlay, timing
from .base import BaseModule

_GROUPS = [edit, geometry, color, timing, overlay, export, audio, images, analysis, meta, capture, expert]

CATEGORIES: "OrderedDict[str, List[BaseModule]]" = OrderedDict()
for _mod in _GROUPS:
    for _m in _mod.MODULES:
        CATEGORIES.setdefault(_m.category, []).append(_m)

ALL: Dict[str, BaseModule] = {m.name: m for mods in CATEGORIES.values() for m in mods}
