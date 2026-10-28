# Nothing Desktop

Eine Wayland-Desktopumgebung im Stil von Nothing OS, aufgebaut wie macOS mit einer
Leiste oben und einem Dock unten. X11-Programme laufen über XWayland.

```
┌──────────────────────────────────────────────────────────────┐
│ ⠿  Firefox  Titel …          ▬ • • •        📶 🔊 Mi 28. 22:24 │  ← Leiste (layer-shell, oben)
│                                                              │
│  ┌───────────┐ ┌─────┐                                       │
│  │ 22:24     │ │ 8°  │   Widgets auf dem Schreibtisch         │  ← Hintergrund-Layer
│  └───────────┘ └─────┘                                       │
│                    ┌─────────────────────┐                   │
│                    │ ⠿ │ 📁 🦊 >_ 📝 │ ⚙ │                   │  ← Dock
└──────────────────────────────────────────────────────────────┘
```

## Komponenten

| Teil | Sprache | Aufgabe |
|---|---|---|
| `compositor/nothing-wm.c` | C, wlroots 0.20 | Wayland-Compositor: xdg-shell, **XWayland**, layer-shell, **virtuelle Arbeitsflächen**, Session-Lock, Screencopy, Zwischenablage, IPC-Socket |
| `shell/nothing_de/` | Python, GTK4, gtk4-layer-shell | Leiste, Dock, Schreibtisch mit Widgets, App-Suche, Kontrollzentrum, Benachrichtigungen, Sperrbildschirm |
| `shell/nothing_de/settings.py` | Python, libadwaita | Einstellungs-App |
| `bin/` | sh | Sitzungsstart, Shell-Launcher, `nothing-msg` (IPC-Werkzeug) |

Shell und Compositor sprechen über einen Unix-Socket (`$NOTHING_WM_SOCK`, zeilenbasiert, Antworten als JSON).
Die Konfiguration liegt in `~/.config/nothing-de/config.json`. Die Einstellungs-App schreibt sie, und die Shell
übernimmt Änderungen sofort, ohne Neustart.

## Funktionen

- **Design im Nothing-Stil:** Schwarz/Weiß, Punktmatrix-Ziffern (selbst gezeichnet, keine Schriftart nötig), runde Karten,
  Beschriftungen in Monospace-Großbuchstaben. Helles und dunkles Design.
- **Wählbare Kontrastfarbe:** Neun Vorgaben oder eine eigene Farbe. Sie gilt für die Shell, die Fensterknöpfe von
  X11-Fenstern und libadwaita-Apps (über GNOMEs `accent-color`).
- **Hintergrundbild:** Mitgelieferte Nothing-Motive, Systemhintergründe oder ein eigenes Bild. Wählbar sind
  Füllen, Einpassen oder Strecken, dazu eine Hintergrundfarbe.
- **Widgets:** Uhr (Punktmatrix), Analoguhr, Wetter (open-meteo, ohne Konto), Akku, System (CPU/RAM),
  Kalender, Notizen, Medien (MPRIS) und Foto. Hinzufügen und verschieben geht per Rechtsklick auf den
  Schreibtisch → *Widgets bearbeiten*.
- **Leiste:** Systemmenü (Sperren, Bereitschaft, Neustart, Ausschalten, Abmelden), Name der aktiven App mit Fenstermenü,
  Punkte für die Arbeitsflächen, Netzwerk, Lautstärke, Akku, Uhr mit Kalender.
- **Dock:** Angeheftete Apps und laufende Fenster, nach App gruppiert. Ein Punkt markiert laufende Apps, ein Punkt in
  Kontrastfarbe die aktive. Linksklick fokussiert, minimiert oder wechselt zwischen den Fenstern einer App. Rechtsklick
  öffnet ein Menü mit Fensterliste, *Im Dock behalten* und *Beenden*.
- **Mehrere Arbeitsflächen** (1–10).
- **Kontrollzentrum:** WLAN, Bluetooth, Dunkelmodus, *Nicht stören*, Lautstärke, Helligkeit (über logind, ohne root),
  Kontrastfarbe, Ein/Aus.
- **Einstellungs-App:** Darstellung, Widgets und Wetterort, Dock und Leiste, Arbeitsflächen, Standard-Apps
  (Browser, Mail, Musik, Video …), Tastaturbelegung, **Benutzer** (AccountsService: Name, Bild, Passwort,
  Benutzer anlegen und löschen) sowie **Online-Konten** (GNOME Online Accounts: Google, Microsoft 365, Nextcloud,
  IMAP …; einzelne Dienste ein- und ausschalten).
- **Sperrbildschirm** über ext-session-lock. Das Passwort prüft `unix_chkpwd`.
- **Benachrichtigungsdienst** (`org.freedesktop.Notifications`).

## Installation (Arch Linux)

```sh
./install.sh --deps      # Abhängigkeiten per pacman (wlroots0.20, gtk4-layer-shell, …)
./install.sh             # bauen und nach /usr/local installieren
# oder als Paket:
makepkg -si
```

Danach abmelden und im Anmeldebildschirm (GDM/SDDM) die Sitzung **Nothing** wählen.

### Ausprobieren ohne Abmelden

Innerhalb von GNOME startet der Compositor als Fenster:

```sh
WLR_BACKENDS=wayland nothing-wm -s nothing-shell
```

## Tastenkürzel

| Kürzel | Aktion |
|---|---|
| Super + Leertaste | Apps und Suche (mit Rechner: `12*7`) |
| Super + A | Kontrollzentrum |
| Super + Eingabe / E / , | Terminal / Dateien / Einstellungen |
| Super + 1 … 0 | Arbeitsfläche wechseln |
| Super + Umschalt + 1 … 0 | Fenster auf Arbeitsfläche verschieben |
| Super + Strg + ← / → | Vorherige / nächste Arbeitsfläche |
| Super + Q / F / M | Schließen / Vollbild / Minimieren |
| Super + ↑ / ↓ | Maximieren / Wiederherstellen |
| Super + Ziehen links / rechts | Fenster verschieben / Größe ändern |
| Super + D | Schreibtisch anzeigen |
| Super + L | Sperren |
| Alt + Tab | Fenster wechseln |
| Druck | Bildschirmfoto (`grim`) |
| Super + Umschalt + Esc | Abmelden |
| Strg + Alt + F1 … F12 | Zu einer anderen virtuellen Konsole (TTY) wechseln |

Eigene Kürzel lassen sich über `nothing-msg` an andere Programme binden, z. B. `nothing-msg action launcher`,
`nothing-msg ws 3` oder `nothing-msg state`.

## Umgebungsvariablen

- `NOTHING_WM_SCALE=1.5` setzt die Skalierung für HiDPI-Bildschirme.
- `XKB_DEFAULT_LAYOUT=de` setzt die Tastaturbelegung beim Start. Später übernimmt die Einstellungs-App.
- `NOTHING_WM_DEBUG=1` schaltet ausführliche Logs ein.

## Bekannte Grenzen / nächste Schritte

- Für **Google- und Microsoft-Konten** öffnet der Hinzufügen-Dialog `gnome-control-center online-accounts`, denn
  der interaktive OAuth-Dialog von GOA steckt dort. Auflisten, Dienste schalten und Entfernen geschieht direkt in
  den Nothing-Einstellungen.
- Es gibt keine Bildschirmverwaltung (Anordnung, Auflösung) in der UI. Mehrere Monitore werden automatisch
  nebeneinander gesetzt, und jeder Monitor bekommt eine eigene Leiste und ein eigenes Hintergrundbild.
- Die Titelleisten von X11-Fenstern sind minimal: drei Knöpfe ohne Titeltext. Wayland-Apps zeichnen ihre
  Dekoration selbst (CSD).
- Fenster lassen sich nicht kacheln.
