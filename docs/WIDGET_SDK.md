# Widget-SDK — eigene Widgets schreiben

Nothing-Desktop Widgets sind kleine GTK4-Komponenten, die auf dem Schreibtisch
frei platziert werden können. Mit dem Widget-SDK (`shell/nothing_de/widget_sdk.py`)
lässt sich ein eigenes Widget in wenigen Zeilen schreiben und automatisch in die
Einstellungen („Widgets“-Seite) und das Desktop-Kontextmenü aufnehmen.

## Grundgerüst

```python
# Beispiel: ein Widget, das die aktuelle Uhrzeit anzeigt
from gi.repository import Gtk
from nothing_widget_sdk import DesktopWidget, register_widget


@register_widget
class UhrWidget(DesktopWidget):
    TYPE = "uhr"                       # eindeutiger Typ-Key
    NAME = "Uhr"                       # Anzeigename in der Auswahl
    SIZE = "wide"                      # "small" | "wide" | "large"
    REFRESH = 1                        # Aktualisierung alle 1 Sekunde (0 = aus)

    def build(self):
        """Wird einmal beim Erstellen aufgerufen: Oberfläche aufbauen."""
        self.label = Gtk.Label(label="—")
        self.label.set_hexpand(True)
        self.append(self.label)

    def refresh(self):
        """Wird zyklisch (alle REFRESH Sekunden) und bei Config-Änderung gerufen."""
        import datetime
        self.label.set_label(datetime.datetime.now().strftime("%H:%M:%S"))
```

## Klassen-Attribute

| Attribut | Bedeutung |
|----------|-----------|
| `TYPE` | Eindeutiger Schlüssel (z. B. `"uhr"`). Wird in `config.json` gespeichert. |
| `NAME` | Anzeigename in der Widget-Auswahl der Einstellungen. |
| `SIZE` | Startgröße: `"small"` (172×172), `"wide"` (360×172), `"large"` (360×360). |
| `REFRESH` | Sekunden zwischen automatischen Aktualisierungen. `0` deaktiviert den Timer. |

## Lebenszyklus-Methoden

- **`build(self)`** — einmalig beim Erstellen: GTK-Kinder anhängen, CSS-Klassen setzen.
- **`refresh(self)`** — zyklisch + bei Config-Änderung: Inhalte neu zeichnen/setzen.
- **`on_config(self)`** — wird gerufen, wenn sich die globale Konfiguration ändert (Standard: ruft `refresh()`).
- **`teardown(self)`** — vor dem Entfernen: Timer entfernen, Signal-Handler trennen.

## Hilfsmittel der Basisklasse

| Eigenschaft / Methode | Bedeutung |
|-----------------------|-----------|
| `self.cfg` | Das Config-Objekt (`self.cfg.get("accent")`, `self.cfg.set("key", val)`). |
| `self.spec` | Das Widget-spezifische Config-Dict (Position, eigene Optionen). |
| `self.shell` | Zugriff auf die Shell (z. B. `self.shell.wm`, `self.shell.apps`). |
| `self.accent` | Aktuelle Kontrastfarbe als `(r, g, b, a)`-Tupel. |
| `self.accent_hex` | Aktuelle Kontrastfarbe als Hex-String (`"#D71921"`). |
| `self.timeout_add(ms, cb)` / `self.timeout_add_seconds(s, cb)` | Timer, der mit `teardown` automatisch entfernt wird. |
| `self.remove_timeout(id)` | Einen Timer manuell entfernen. |
| `self.idle_add(cb)` | Einen Aufruf im nächsten Main-Loop-Durchlauf planen. |
| `self.spawn(cmd)` | Einen Befehl detached ausführen. |

## Konfiguration speichern

Eigene Widget-Einstellungen landen am einfachsten in `self.spec` und werden über
`self.cfg.set("widgets", ...)` persistiert (siehe `desktop.py: _store`).
Beispiel für ein Widget, das sich einen Pfad merkt:

```python
def refresh(self):
    path = self.spec.get("pfad", "")
    self.label.set_label(path or "Kein Pfad gesetzt")
```

## Registrierung & Entdeckung

Durch den `@register_widget`-Decorator wird die Klasse automatisch in
`widget_sdk.WIDGET_TYPES` eingetragen. Die Shell liest dieses Dict aus und bietet
das Widget in:

- den Einstellungen unter „Widgets“ → „Widget hinzufügen“
- dem Desktop-Kontextmenü → „Widget hinzufügen“

an.

## Eigenes Widget hinzufügen (ohne Paket-Installation)

Legen Sie die Datei z. B. unter `~/.config/nothing-de/widgets/mein_widget.py` ab.
Alle `*.py` dort werden beim Start der Shell und der Einstellungen geladen, das Widget steht
danach in der Auswahl zur Verfügung. Nach einer Änderung die Shell neu starten:
`pkill -f '[n]othing_de.shell'`. Eine fehlerhafte Datei wird nur im Log gemeldet.

```python
from gi.repository import Gtk
from nothing_widget_sdk import DesktopWidget, register_widget

@register_widget
class MeinWidget(DesktopWidget):
    ...
```

## Beispiel: komplettes Widget mit eigener Option

```python
@register_widget
class NotizWidget(DesktopWidget):
    TYPE = "notiz"
    NAME = "Notiz"
    SIZE = "small"

    def build(self):
        self.view = Gtk.TextView()
        self.view.get_buffer().connect("changed", self._changed)
        scroll = Gtk.ScrolledWindow(child=self.view, vexpand=True, hexpand=True)
        self.append(scroll)
        self._save_id = None

    def _changed(self, buf):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(800, self._save)

    def _save(self):
        self._save_id = None
        text = self.view.get_buffer().get_text(
            self.view.get_buffer().get_start_iter(),
            self.view.get_buffer().get_end_iter(), False)
        self.spec["inhalt"] = text
        return False

    def refresh(self):
        self.view.get_buffer().set_text(self.spec.get("inhalt", ""))
```

## Bestehende Widgets als Vorlage

Die mitgelieferten Widgets in `shell/nothing_de/widgets.py` (Uhr, Wetter, Akku,
System, Kalender, Notizen, Medien, Foto) nutzen genau dieses SDK und sind gute
Kopiervorlagen für eigene Widgets.
