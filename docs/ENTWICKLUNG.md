# Entwicklung & Tests

## Aufbau des Repos

```
compositor/         nothing-wm (C, wlroots 0.20) + meson.build + layer-shell-Protokoll
shell/nothing_de/   Python-Paket: Shell, Widgets, Einstellungen
bin/                Starter: nothing-session(-start), nothing-shell, nothing-settings, nothing-msg
data/               Sitzungs- und App-Einträge, Portal-Konfiguration, Hintergründe
docs/               Diese Dokumentation und Screenshots
tools/vm-test.sh    Test in einer Wegwerf-VM
install.sh          Bauen + installieren
PKGBUILD            Arch-Paket
```

## Bauen

```sh
meson setup build/compositor compositor
ninja -C build/compositor
```

Benötigt `wlroots0.20`, `wayland-protocols`, `xkbcommon` und `xcb`. Die Python-Teile brauchen keinen
Build-Schritt, aber `python-gobject`, `python-cairo` und `python-numpy` (für die Nothing-Symbole). Aus dem Repo heraus starten sie direkt:

```sh
bin/nothing-shell        # findet ../shell automatisch
bin/nothing-settings --page widgets
```

## Schnell ausprobieren

**Als Fenster in der laufenden Sitzung** (GNOME, KDE, Sway …):

```sh
WLR_BACKENDS=wayland build/compositor/nothing-wm -s bin/nothing-shell
```

**Ohne Bildschirm**, z. B. in CI oder über SSH: Das Headless-Backend von wlroots mit Software-Rendering.
Screenshots gehen dann mit `grim`, das der Compositor über screencopy unterstützt:

```sh
WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1 GSK_RENDERER=cairo \
NOTHING_NO_GSETTINGS=1 NOTHING_NO_AUTOSTART=1 \
dbus-run-session -- build/compositor/nothing-wm -s 'bin/nothing-shell & sleep 8; grim /tmp/shot.png'
```

`dbus-run-session` sorgt dafür, dass der Benachrichtigungsdienst der Shell nicht den der echten Sitzung
übernimmt. `NOTHING_NO_GSETTINGS` verhindert, dass der Test deine GNOME-Farben ändert.

## Test in einer VM (empfohlen vor Releases)

`tools/vm-test.sh` erzeugt eine Arch-Linux-VM mit QEMU/KVM, installiert den aktuellen Stand per
`install.sh` und meldet sich per Autologin direkt in der Nothing-Sitzung an. Die Sitzung läuft dort auf
einem echten DRM-Gerät (virtio-gpu), also wie nach einem richtigen Login. Tastatur, Maus und Screenshots
laufen über den QEMU-Monitor.

```sh
tools/vm-test.sh create            # Cloud-Image laden (~550 MB), Disk + cloud-init
tools/vm-test.sh start 1920x1080   # VM ohne Fenster starten
tools/vm-test.sh provision         # Pakete, dieses Repo, Autologin → Sitzung startet
tools/vm-test.sh shot desktop.png

tools/vm-test.sh key meta_l-spc            # Super + Leertaste
tools/vm-test.sh key n o t h i n g ret     # tippen (Passwort der VM: nothing)
tools/vm-test.sh click 960 1030            # Linksklick
tools/vm-test.sh click 1100 300 right      # Rechtsklick
tools/vm-test.sh drag 939 1026 1140 1020   # ziehen (z. B. Dock-Symbol umsortieren)
tools/vm-test.sh ssh 'tail /tmp/session.log'

# nach Code-Änderungen:
tools/vm-test.sh deploy && tools/vm-test.sh ssh 'sudo systemctl restart getty@tty1'
tools/vm-test.sh stop
```

Zum Steuern von Fenstern in der VM:

```sh
tools/vm-test.sh ssh 'export NOTHING_WM_SOCK=$(ls /run/user/1000/nothing-wm.*.sock);
                      nothing-msg state'
```

Die Screenshots in `docs/screenshots/` sind so entstanden (1920×1080, deutsches Locale).

### Checkliste für einen manuellen Durchlauf

- [ ] Sitzung startet, Leiste, Dock und Widgets sind sichtbar
- [ ] Super + Eingabe öffnet ein Terminal; Super + Leertaste, Tippen und Enter starten eine App
- [ ] `DISPLAY=:0 xterm` erscheint mit Nothing-Titelleiste; der rote Knopf schließt es
- [ ] Super + 2 wechselt die Arbeitsfläche; ein Klick ins Dock holt das Fenster zurück
- [ ] Esc schließt App-Suche und Kontrollzentrum
- [ ] Dock-Symbol ziehen: Eine rote Linie zeigt die Stelle; nach vorn, hinten und in die Mitte klappt es
- [ ] App aus der Suche ins Dock ziehen bzw. per Rechtsklick „Im Dock behalten“
- [ ] Einstellungen → Dock & Leiste: „App-Symbole“ und „App-Menü-Knopf“ wirken sofort
- [ ] Super + L sperrt; ein falsches Passwort wird abgelehnt, das richtige entsperrt
- [ ] Kontrastfarbe und Hell/Dunkel in den Einstellungen wirken sofort
- [ ] Shell beenden (`pkill -f '[n]othing_de.shell'`): Sie kommt genau einmal zurück

## Hinweise für Änderungen am Code

- **wlroots-Version:** Der Code zielt auf die API von wlroots 0.20. Bei einem Update zuerst kompilieren und
  die Änderungshinweise von wlroots lesen. Typische Stellen sind Ereignisnamen von xdg-shell/XWayland und
  `wlr_output_state`.
- **Kein `SIG_IGN` für `SIGCHLD`** im Compositor. Das erben Kindprozesse, und dann scheitert z. B. Xwayland
  beim Erzeugen der Tastaturbelegung. Neue Programme startet `spawn()` per Double-Fork.
- **Layer-Fenster schrumpfen nicht von selbst.** Nach einem Neuaufbau, etwa im Dock, `set_default_size(1, 1)`
  aufrufen.
- **Escape in Overlays:** Eingabefelder schlucken Escape. Der Tasten-Controller von `layer.Overlay` läuft
  deshalb in der Capture-Phase.
- **Keine Layout-Änderung beim Drag-Feedback:** Eine Lücke im Dock würde es verbreitern und neu
  zentrieren, dann verrutscht die Mausposition relativ zum Dock. Deshalb gibt es eine Markierung per
  `box-shadow`.
- **Nothing-Symbole:** `icons.py` rechnet jedes Symbol einmal pro Sitzung um, erst beim ersten Zeichnen.
  Neue Sonderfälle lassen sich am schnellsten mit einem Kontaktbogen prüfen: `glyph_for()` für eine Liste
  von Apps aufrufen und die Masken mit cairo nebeneinander in ein PNG zeichnen.
- **Fenster ↔ App:** Das Dock ordnet Fenster über `app_id` (Wayland) bzw. die X11-Klasse den `.desktop`-Dateien
  zu, unter anderem über `StartupWMClass`. Eigene Apps sollten das setzen.
- **Prozesse in Tests beenden:** `pkill -f "python3 -m nothing_de.shell"` trifft auch die eigene
  Befehlszeile, etwa eine SSH-Shell. Besser `pkill -f '[p]ython3 -m nothing_de.shell'`.
