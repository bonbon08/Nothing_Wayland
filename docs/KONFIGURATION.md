# Konfiguration

Alle Einstellungen liegen in **`~/.config/nothing-de/config.json`**. Die Einstellungs-App schreibt diese
Datei. Du kannst sie auch von Hand bearbeiten: Die Shell bemerkt Änderungen und übernimmt sie sofort.
Fehlende Schlüssel ergänzt sie mit den Standardwerten (`shell/nothing_de/config.py`, `DEFAULTS`).

## Schlüssel

| Schlüssel | Typ | Standard | Bedeutung |
|---|---|---|---|
| `theme` | `"dark"` \| `"light"` | `"dark"` | Dunkles oder helles Design |
| `accent` | `"#RRGGBB"` | `"#D71921"` | Kontrastfarbe |
| `wallpaper` | Pfad | `…/wallpapers/dots-dark.svg` | Hintergrundbild; leer bedeutet nur Farbe |
| `wallpaper_fit` | `"cover"` \| `"contain"` \| `"fill"` | `"cover"` | Füllen / Einpassen / Strecken |
| `background_color` | `"#RRGGBB"` | `"#000000"` | Farbe hinter oder statt dem Bild |
| `workspaces` | 1–10 | `4` | Anzahl der Arbeitsflächen |
| `terminal` | Befehl | `""` | Terminal für Super + Eingabe; leer bedeutet automatisch (kgx, gnome-terminal, foot, …) |
| `files` | Befehl | `""` | Dateimanager für Super + E; leer bedeutet Standard-App für Ordner |
| `keyboard.layout` / `.variant` / `.options` | XKB | `"de"`, `""`, `""` | Tastaturbelegung |
| `bar.clock_24h` | bool | `true` | 24-Stunden-Uhr |
| `bar.show_seconds` | bool | `false` | Sekunden in der Leiste |
| `bar.show_date` | bool | `true` | Datum in der Leiste |
| `bar.show_workspaces` | bool | `true` | Punkte für die Arbeitsflächen |
| `icons` | `"nothing"` \| `"original"` | `"nothing"` | App-Symbole in Dock und App-Suche: einfarbig auf rundem Grund oder Original |
| `dock.launcher` | `"left"` \| `"right"` | `"left"` | Position des Knopfs für die App-Suche im Dock |
| `dock.icon_size` | px | `48` | Symbolgröße im Dock (Höchstwert; bei vielen Apps automatisch kleiner, mindestens 24) |
| `dock.pinned` | Liste von `.desktop`-IDs | Dateien, Firefox, Konsole, Texteditor, Einstellungen | Angeheftete Apps in Dock-Reihenfolge (wird auch durch Ziehen im Dock geändert) |
| `weather.city` / `.lat` / `.lon` | Text / Zahl | Berlin | Ort des Wetter-Widgets |
| `widgets` | Liste | Uhr, Wetter, Akku, Kalender | Widgets auf dem Schreibtisch, siehe unten |
| `notes` | Text | `""` | Inhalt des Notizen-Widgets |
| `photo` | Pfad | `""` | Bild für das Foto-Widget |
| `dnd` | bool | `false` | *Nicht stören*: blendet normale Benachrichtigungen aus |

### Widgets

```json
"widgets": [
  {"type": "clock",    "x": 48,  "y": 72},
  {"type": "weather",  "x": 48,  "y": 260},
  {"type": "notes",    "x": 424, "y": 448}
]
```

`x`/`y` sind Pixel ab der linken oberen Ecke des Bildschirms. Mögliche Typen:

| Typ | Größe | Widget |
|---|---|---|
| `clock` | breit | Punktmatrix-Uhr mit Datum |
| `analog` | klein | Analoguhr |
| `weather` | klein | Wetter (open-meteo.com) |
| `battery` | klein | Akkustand bzw. „AC“ |
| `system` | klein | CPU- und RAM-Auslastung |
| `calendar` | breit | Monatskalender |
| `notes` | groß | Notizen (Text wird gespeichert) |
| `media` | breit | Steuerung des laufenden Players (MPRIS) |
| `photo` | groß | Ein Foto (`photo`) |

Klein = 172×172, breit = 360×172, groß = 360×360 Pixel.

## Umgebungsvariablen

| Variable | Wirkung |
|---|---|
| `NOTHING_WM_SCALE` | Skalierung aller Ausgänge, z. B. `1.5` für HiDPI |
| `XKB_DEFAULT_LAYOUT` / `_VARIANT` / `_OPTIONS` | Tastaturbelegung beim Start des Compositors |
| `XCURSOR_THEME` / `XCURSOR_SIZE` | Mauszeiger |
| `NOTHING_WM_DEBUG=1` | Ausführliche Logs des Compositors |
| `NOTHING_DE_DATA` | Anderes Datenverzeichnis (Hintergründe) |
| `NOTHING_NO_GSETTINGS=1` | Shell schreibt nicht in GNOMEs `color-scheme`/`accent-color` |
| `NOTHING_NO_AUTOSTART=1` | XDG-Autostart-Einträge nicht starten |
| `NOTHING_LAYER_SHELL_LIB` | Pfad zu `libgtk4-layer-shell.so`, falls nicht unter `/usr/lib` |

## Installierte Dateien

| Pfad | Inhalt |
|---|---|
| `$PREFIX/bin/nothing-*` | Compositor, Sitzungsskripte, Shell, Einstellungen, `nothing-msg` |
| `$PREFIX/share/nothing-de/shell/nothing_de/` | Python-Paket |
| `$PREFIX/share/nothing-de/data/wallpapers/` | Mitgelieferte Hintergründe |
| `$PREFIX/share/applications/nothing-settings.desktop` | Starter für die Einstellungen |
| `/usr/share/wayland-sessions/nothing.desktop` | Sitzungseintrag für den Anmeldebildschirm |
| `/usr/share/xdg-desktop-portal/nothing-portals.conf` | Portal-Zuordnung (gtk, wlr für Bildschirmfotos) |

## Autostart

Beim ersten Start der Shell in einer Sitzung startet sie Einträge aus `~/.config/autostart` und
`/etc/xdg/autostart`, sofern sie für die Desktop-Umgebung `Nothing` gelten (`OnlyShowIn`/`NotShowIn`)
und nicht `Hidden=true` gesetzt ist.
