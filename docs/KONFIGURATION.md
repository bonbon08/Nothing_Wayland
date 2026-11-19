# Konfiguration

Alle Einstellungen liegen in **`~/.config/nothing-de/config.json`**. Die Einstellungs-App schreibt diese
Datei. Du kannst sie auch von Hand bearbeiten: Die Shell bemerkt Änderungen und übernimmt sie sofort.
Fehlende Schlüssel ergänzt sie mit den Standardwerten (`shell/nothing_de/config.py`, `DEFAULTS`).

## Schlüssel

| Schlüssel | Typ | Standard | Bedeutung |
|---|---|---|---|
| `theme` | `"dark"` \| `"light"` | `"dark"` | Dunkles oder helles Design |
| `accent` | `"#RRGGBB"` | `"#D71921"` | Kontrastfarbe |
| `wallpaper` | Pfad | `…/wallpapers/dots-dark.svg` | Hintergrundbild; leer bedeutet nur Farbe. Ein Video (`.mp4`, `.webm`, `.mkv`, `.mov`) läuft stumm in Schleife; `live:<szene>` zeigt einen Live-Hintergrund: `live:snow-forest` (Schneewald), `live:blue-hour` (Blaue Stunde), `live:black-hole` (Ereignishorizont), `live:ember` (Glut) |
| `wallpaper_fps` | 10, 20, 30 | `20` | Bilder pro Sekunde eines Live-Hintergrunds |
| `accent_auto` | bool | `false` | Kontrastfarbe aus dem Hintergrund: die auffälligste Farbe des Bilds, bei Live-Hintergründen deren eigene. Eine von Hand gewählte Farbe schaltet das ab |
| `wallpaper_fit` | `"cover"` \| `"contain"` \| `"fill"` | `"cover"` | Füllen / Einpassen / Strecken |
| `background_color` | `"#RRGGBB"` | `"#000000"` | Farbe hinter oder statt dem Bild |
| `workspaces` | 1–10 | `4` | Anzahl der Arbeitsflächen |
| `terminal` | Befehl | `""` | Terminal für Super + Eingabe; leer bedeutet automatisch (kgx, gnome-terminal, foot, …) |
| `files` | Befehl | `""` | Dateimanager für Super + E; leer bedeutet Standard-App für Ordner |
| `keyboard.layout` / `.variant` / `.options` | XKB | `"us"`, `""`, `""` | Tastaturbelegung |
| `display.scale` | Zahl, 0.5–4 | `1.0` | Skalierung aller Bildschirme ohne eigenen Wert |
| `form` | `auto`, `phone`, `desktop` | `auto` | Oberfläche: `auto` nimmt die Telefon-Ansicht, wenn der erste Bildschirm hochkant steht. `phone` geht auch am Rechner: Im Querformat stehen Uhr und Suche links neben dem App-Raster, App-Suche und Kontrollzentrum behalten ihre Desktop-Breite, und mit angeschlossener Tastatur gibt es keine Bildschirmtastatur |
| `phone.scale` | Zahl, 0.5–4 | `2.0` | Skalierung in der Telefon-Ansicht, sofern kein `outputs.<NAME>.scale` gesetzt ist. Bildschirme ab 13" Diagonale (Monitore, Laptops) behalten `display.scale` |
| `phone.screen_timeout` | Sekunden | `60` | Telefon: so lange ohne Berührung, dann geht der Bildschirm aus und das Telefon sperrt (`0` = nie) |
| `phone.auto_rotate` | `true` \| `false` | `true` | Telefon: Bildschirm mit dem Lagesensor drehen (gesperrt immer hochkant) |
| `phone.wallpaper` | Pfad | `""` | Telefon: Hintergrundbild hinter dem App-Raster, leicht abgedunkelt; leer = schwarz |
| `outputs.<NAME>.scale` | Zahl, 0.5–4 | `display.scale` | Skalierung dieses Bildschirms, `NAME` ist der Anschluss wie `DP-1` |
| `outputs.<NAME>.enabled` | bool | `true` | Bildschirm verwenden; der letzte aktive lässt sich nicht abschalten |
| `bar.clock_24h` | bool | `true` | 24-Stunden-Uhr |
| `bar.show_seconds` | bool | `false` | Sekunden in der Leiste |
| `bar.show_date` | bool | `true` | Datum in der Leiste |
| `bar.show_workspaces` | bool | `true` | Punkte für die Arbeitsflächen |
| `icons` | `"nothing"` \| `"original"` | `"nothing"` | App-Symbole in Dock und App-Suche: einfarbig auf rundem Grund oder Original |
| `dock.launcher` | `"left"` \| `"right"` | `"left"` | Position des Knopfs für die App-Suche im Dock |
| `dock.all_monitors` | bool | `false` | Dock auf jedem Bildschirm statt nur auf dem ersten |
| `dock.icon_size` | px | `48` | Symbolgröße im Dock (Höchstwert; bei vielen Apps automatisch kleiner, mindestens 24) |
| `dock.pinned` | Liste von `.desktop`-IDs | Dateien, Firefox, Konsole, Texteditor, Einstellungen | Angeheftete Apps in Dock-Reihenfolge (wird auch durch Ziehen im Dock geändert) |
| `weather.city` / `.lat` / `.lon` | Text / Zahl | Berlin | Ort des Wetter-Widgets |
| `widgets` | Liste | Uhr, Wetter, Akku, Kalender | Widgets auf dem Schreibtisch, siehe unten |
| `notes` | Text | `""` | Inhalt des Notizen-Widgets |
| `photo` | Pfad | `""` | Bild für das Foto-Widget |
| `dnd` | bool | `false` | *Nicht stören*: blendet normale Benachrichtigungen aus |
| `desktop.visualizer` | `off`, `wave`, `bars`, `dots` | `off` | Audio-Visualizer am unteren Bildschirmrand (Welle, Balken, Punktmatrix) |
| `desktop.visualizer_height` | px, 40–600 | `140` | Höhe des Visualizer-Bands |
| `desktop.visualizer_color` | `"#RRGGBB"` | `""` | Farbe des Bands; leer = Kontrastfarbe |
| `desktop.visualizer_opacity` | 0–1 | `0.9` | Deckkraft des Bands |
| `lock.wallpaper` | bool | `true` | Sperrbildschirm zeigt das Hintergrundbild (abgedunkelt) |
| `lock.avatar` | bool | `true` | Sperrbildschirm zeigt das Benutzerbild bzw. den Anfangsbuchstaben |
| `eq.enabled` | bool | `false` | Systemweiter Equalizer: legt über PipeWire (filter-chain) die Ausgabe „Nothing Equalizer“ an und macht sie zur Standardausgabe; aus = vorherige Ausgabe zurück |
| `eq.gains` | 10 Zahlen, dB (−12…12) | alle `0` | Verstärkung für 31, 63, 125, 250, 500 Hz, 1, 2, 4, 8, 16 kHz; Änderungen wirken sofort ohne Aussetzer |
| `island.enabled` | bool | `true` | Island: schwarze Pille unter der Leiste mit dem laufenden Titel; unter dem Mauszeiger und beim Titelwechsel klappt sie zur Karte mit Fortschritt und Tasten auf |
| `dotvis.mode` | `face`, `pulse`, `ripple`, `torus`, `clock`, `ticker` | `face` | Modus des Dot-Visualizers (Klick oder Scrollen auf das Widget wechselt ihn) |

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
| `clock-stacked` | klein | Punktmatrix-Uhr, Stunden über Minuten |
| `clock-ring` | klein | Runde Uhr, der Ring füllt sich mit den Sekunden |
| `analog` | klein | Analoguhr |
| `weather` | klein | Wetter (open-meteo.com) |
| `battery` | klein | Akkustand bzw. „AC“ |
| `system` | klein | CPU- und RAM-Auslastung |
| `calendar` | breit | Monatskalender |
| `notes` | groß | Notizen (Text wird gespeichert) |
| `media` | breit | Steuerung des laufenden Players (MPRIS) |
| `media-round` | klein | Runde Medien-Taste: Klick = Wiedergabe/Pause, Scrollen = Titel wechseln, Ring = Fortschritt |
| `visualizer` | breit | Audio-Visualizer als Punktmatrix (braucht GStreamer oder `cava`) |
| `equalizer` | hoch | Laufender Titel mit Cover, Fortschritt und Tasten über einem 10-Band-Equalizer mit Voreinstellungen (Flat, Bass, Treble, Vocal, Pop, Rock, Jazz, Classic). Regler ziehen (auch quer über mehrere), scrollen oder doppelklicken (= 0 dB) |
| `dot-visualizer` | groß, rund | Punktmatrix mit sechs Modi: Gesicht (schaut zum Mauszeiger, singt mit), Puls, Wellen im Takt, Torus, Uhr, Laufschrift mit Spektrum |
| `cassette` | Deck | Kassette: Spulen drehen sich, das Band wickelt sich mit dem Fortschritt um; daneben Oszilloskop und LOW/MID/HIGH. Klick = Wiedergabe/Pause, Scrollen = Titel wechseln |
| `photo` | groß | Ein Foto (`photo`) |

Klein = 172×172, breit = 360×172, groß = 360×360, hoch = 360×470, Deck = 440×210 Pixel.

## Umgebungsvariablen

| Variable | Wirkung |
|---|---|
| `NOTHING_WM_SCALE` | Startwert für die Skalierung aller Ausgänge, z. B. `1.5`; `display.scale` und `outputs.<NAME>.scale` überschreiben ihn, sobald die Shell läuft |
| `XKB_DEFAULT_LAYOUT` / `_VARIANT` / `_OPTIONS` | Tastaturbelegung beim Start des Compositors |
| `XCURSOR_THEME` / `XCURSOR_SIZE` | Mauszeiger |
| `NOTHING_WM_DEBUG=1` | Ausführliche Logs des Compositors |
| `NOTHING_DE_DATA` | Anderes Datenverzeichnis (Hintergründe) |
| `NOTHING_NO_GSETTINGS=1` | Shell schreibt nicht in GNOMEs `color-scheme`/`accent-color` |
| `NOTHING_NO_AUTOSTART=1` | XDG-Autostart-Einträge nicht starten |
| `NOTHING_NO_AUDIO=1` | Audio-Visualizer greift keinen Ton ab (bleibt flach) |
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
und weder `Hidden=true` noch `X-GNOME-Autostart-enabled=false` gesetzt ist. Damit gelten auch die
Autostart-Apps aus GNOME, die dort liegen; `X-GNOME-Autostart-Delay` wird beachtet.
