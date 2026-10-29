# IPC

`nothing-wm` lauscht auf einem Unix-Socket. Den Pfad findest du in `$NOTHING_WM_SOCK`
(`$XDG_RUNTIME_DIR/nothing-wm.<WAYLAND_DISPLAY>.sock`). Das Protokoll ist zeilenbasiert:
**Befehle sind Text, Antworten und Ereignisse sind JSON**, jeweils eine Zeile.

Am einfachsten geht es mit dem mitgelieferten Werkzeug:

```sh
nothing-msg state                  # aktuellen Zustand als JSON ausgeben
nothing-msg ws 2                   # zu Arbeitsfläche 2 wechseln
nothing-msg action launcher        # App-Suche öffnen (wie Super + Leertaste)
nothing-msg geometry 5 100 80 1200 800
```

Ohne `nothing-msg` geht es zum Beispiel mit `socat`:

```sh
echo state | socat - UNIX-CONNECT:"$NOTHING_WM_SOCK"
```

## Befehle

Fenster-IDs (`ID`) stammen aus `state`. Arbeitsflächen werden ab 1 gezählt.

| Befehl | Wirkung |
|---|---|
| `subscribe` | Diese Verbindung erhält ab jetzt alle Ereignisse (sofort einmal `state`) |
| `state` | Einmalig den Zustand senden |
| `focus ID` | Fenster fokussieren (wechselt die Arbeitsfläche, stellt Minimierte wieder her) |
| `toggle ID` | Wie ein Klick im Dock: aktives Fenster minimieren, sonst fokussieren |
| `close ID` | Fenster höflich schließen |
| `minimize ID` | Minimieren |
| `maximize ID` | Maximieren umschalten |
| `fullscreen ID` | Vollbild umschalten |
| `geometry ID X Y B H` | Fenster an Position X/Y mit Breite B und Höhe H setzen (Layout-Koordinaten) |
| `ws N` | Zu Arbeitsfläche N wechseln |
| `move ID N` | Fenster auf Arbeitsfläche N verschieben |
| `show_desktop` | Alle Fenster der aktuellen Arbeitsfläche minimieren |
| `action NAME` | Aktion an alle Abonnenten senden (siehe unten) |
| `config KEY WERT` | Laufzeit-Einstellung setzen (siehe unten) |
| `exit` | Compositor beenden, also abmelden |

### `config`-Schlüssel

| Schlüssel | Wert |
|---|---|
| `workspaces` | Anzahl 1–10 |
| `accent` | `#RRGGBB`, wirkt auf die X11-Titelleisten |
| `dark` | `1` oder `0` |
| `kb_layout`, `kb_variant`, `kb_options` | XKB-Werte, z. B. `de`, `nodeadkeys`, `caps:escape` |
| `cursor_theme` | Name des Cursor-Themes (setzt `XCURSOR_THEME` für danach gestartete Programme) |

Die Shell sendet diese Werte beim Verbinden und bei jeder Änderung von `config.json`.

## Ereignisse

**`state`** kommt bei jeder Änderung, zusammengefasst pro Durchlauf der Ereignisschleife:

```json
{"event":"state","workspace":1,"workspaces":4,"focused":3,"locked":false,
 "windows":[{"id":3,"app_id":"org.gnome.Console","title":"~","ws":1,
             "minimized":false,"maximized":false,"fullscreen":false,"x11":false,"pid":1234}]}
```

Fenster sind nach ID sortiert. X11-Fenster mit `skip_taskbar` fehlen.

**`action`** kommt bei Tastenkürzeln, die die Shell erledigt, oder nach `action NAME`:

```json
{"event":"action","name":"launcher"}
```

Bekannte Namen: `launcher`, `control`, `terminal`, `files`, `settings`, `lock`, `screenshot`.

## Beispiel: eigene Zeile für eine Statusleiste

```sh
nothing-msg state | python3 -c '
import json, sys
s = json.load(sys.stdin)
print(f"Arbeitsfläche {s[\"workspace\"]}/{s[\"workspaces\"]} · {len(s[\"windows\"])} Fenster")'
```
