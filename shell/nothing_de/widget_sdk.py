"""nothing-widget-sdk — vereinfacht das Schreiben eigener Desktop-Widgets.

Ein Widget ist eine Unterklasse von :class:`DesktopWidget`. Es muss nur
:meth:`build` und :meth:`refresh` implementieren und wird automatisch in die
Widget-Auswahl der Einstellungen und des Desktops aufgenommen.

Beispiel::

    from gi.repository import Gtk
    from nothing_widget_sdk import DesktopWidget, register_widget

    @register_widget
    class HelloWidget(DesktopWidget):
        TYPE = "hello"
        NAME = "Hallo"
        SIZE = "small"
        REFRESH = 5

        def build(self):
            self.label = Gtk.Label(label="—")
            self.append(self.label)

        def refresh(self):
            self.label.set_label("Hallo Welt")

Eigene Widgets liegen als ``*.py`` in ``~/.config/nothing-de/widgets/`` und werden
beim Start geladen, siehe :func:`load_user_widgets`.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys
import traceback
from typing import Callable, Dict, Type

from gi.repository import GLib, Gtk

from .config import CONFIG_DIR
from .theme import hex_to_rgb

SIZES = {"small": (172, 172), "wide": (360, 172), "large": (360, 360)}

#: Globale Registrierung aller bekannten Widget-Typen (key -> Klasse).
WIDGET_TYPES: Dict[str, Type["DesktopWidget"]] = {}


def register_widget(cls: Type["DesktopWidget"]) -> Type["DesktopWidget"]:
    """Decorator/Klassen-Dekorator: registriert ein Widget-Typ global."""
    if not cls.TYPE:
        raise TypeError(f"Widget {cls.__name__} hat kein TYPE")
    WIDGET_TYPES[cls.TYPE] = cls
    return cls


def load_user_widgets(folder=None):
    """Load the widgets in the user's folder. A broken file is only reported,
    it must not take the whole shell with it."""
    # eigene Widgets schreiben: from nothing_widget_sdk import DesktopWidget
    sys.modules.setdefault("nothing_widget_sdk", sys.modules[__name__])
    folder = folder or os.path.join(CONFIG_DIR, "widgets")
    for path in sorted(glob.glob(os.path.join(folder, "*.py"))):
        name = "nothing_user_widget_" + os.path.basename(path)[:-3]
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            print("nothing-de: cannot load widget", path)
            traceback.print_exc()


def accent_rgba(cfg) -> tuple:
    r, g, b = hex_to_rgb(cfg.get("accent"))
    return (r, g, b, 1.0)


class DesktopWidget(Gtk.Box):
    """Basis-Klasse für eigene Widgets.

    Attribute (Klassen-Attribute überschreiben):
        TYPE    : str   — eindeutiger Typ-Key (z. B. "mein-widget")
        NAME    : str   — Anzeigename in der Einstellungs-Auswahl
        SIZE    : str   — "small" | "wide" | "large"
        REFRESH : int   — Sekunden bis zur automatischen Aktualisierung (0 = aus)
    """

    TYPE = ""
    NAME = ""
    SIZE = "small"
    REFRESH = 0  # seconds, 0 = none

    def __init__(self, shell, spec):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.shell = shell
        self.cfg = shell.cfg
        self.spec = spec
        self.add_css_class("n-card")
        self.add_css_class("n-root")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        w, h = SIZES.get(self.SIZE, (172, 172))
        self.set_size_request(w, h)
        self._timer = None
        self._timers = set()
        self._cfg_handler = self.cfg.connect("changed", lambda *_: self.on_config())
        self.build()
        self.refresh()
        if self.REFRESH:
            self._timer = GLib.timeout_add_seconds(self.REFRESH, self._tick)

    def _tick(self):
        self.refresh()
        return True

    def build(self):
        """Oberfläche des Widgets aufbauen (einmal beim Erstellen)."""
        pass

    def refresh(self):
        """Inhalt aktualisieren (wird zyklisch und bei Config-Änderung gerufen)."""
        pass

    def on_config(self):
        """Wird aufgerufen, wenn sich die globale Konfiguration ändert."""
        self.refresh()

    def teardown(self):
        """Aufräumen bevor das Widget entfernt wird."""
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        for source_id in self._timers:
            GLib.source_remove(source_id)
        self._timers.clear()
        if self._cfg_handler:
            self.cfg.disconnect(self._cfg_handler)
            self._cfg_handler = None

    # ------------------------------------------------------------------ helpers
    def timeout_add(self, interval_ms: int, callback: Callable) -> int:
        """GLib-Timeout, der mit dem Widget mit sauber gemacht wird."""
        return self._track(GLib.timeout_add, interval_ms, callback)

    def timeout_add_seconds(self, seconds: int, callback: Callable) -> int:
        return self._track(GLib.timeout_add_seconds, seconds, callback)

    def _track(self, add, interval, callback):
        def run():
            again = callback()
            if not again:
                self._timers.discard(source_id)
            return again
        source_id = add(interval, run)
        self._timers.add(source_id)
        return source_id

    def remove_timeout(self, source_id: int):
        self._timers.discard(source_id)
        GLib.source_remove(source_id)

    def idle_add(self, callback: Callable):
        return GLib.idle_add(callback)

    @property
    def accent(self) -> tuple:
        return accent_rgba(self.cfg)

    @property
    def accent_hex(self) -> str:
        return self.cfg.get("accent")

    def spawn(self, cmd):
        from .apps import spawn as _spawn
        _spawn(cmd)
