"""Gemeinsame Test-Einrichtung: Importpfad, GTK-Version und isolierte Konfiguration.

Die Tests schreiben nie in die echte ~/.config/nothing-de: XDG_CONFIG_HOME zeigt
auf ein Wegwerfverzeichnis, bevor das Paket importiert wird.
"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHELL_DIR = os.path.join(ROOT, "shell")
sys.path.insert(0, SHELL_DIR)

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="nd-test-cfg-"))
os.environ["NOTHING_NO_GSETTINGS"] = "1"

import gi  # noqa: E402

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
