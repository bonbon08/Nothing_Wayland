"""nothing-settings: system settings for the Nothing desktop."""
import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.parse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import dotmatrix  # noqa: E402
from .apps import app_icon  # noqa: E402
from .config import ACCENTS, WALLPAPER_DIR, get_config  # noqa: E402
from .theme import ThemeManager, hex_to_rgb  # noqa: E402
from .widgets import WIDGET_TYPES, fetch_json  # noqa: E402

PAGES = [
    ("appearance", "Darstellung", "applications-graphics-symbolic"),
    ("widgets", "Widgets", "view-grid-symbolic"),
    ("dock", "Dock & Leiste", "user-desktop-symbolic"),
    ("workspaces", "Arbeitsflächen", "focus-windows-symbolic"),
    ("apps", "Standard-Apps", "starred-symbolic"),
    ("keyboard", "Tastatur", "input-keyboard-symbolic"),
    ("users", "Benutzer", "system-users-symbolic"),
    ("accounts", "Online-Konten", "goa-panel-symbolic"),
    ("about", "Info", "help-about-symbolic"),
]


def css_for(widget, css):
    prov = Gtk.CssProvider()
    prov.load_from_string(css)
    widget.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)


def page(title, icon=None):
    p = Adw.PreferencesPage(title=title)
    if icon:
        p.set_icon_name(icon)
    return p


def group(title=None, description=None):
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(title)
    if description:
        g.set_description(description)
    return g


def toast(widget, text):
    w = widget.get_root()
    if hasattr(w, "toasts"):
        w.toasts.add_toast(Adw.Toast(title=text, timeout=3))


# ======================================================================
class AppearancePage:
    def __init__(self, cfg):
        self.cfg = cfg
        self.widget = page("Darstellung")

        g = group("Design")
        self.dark_row = Adw.SwitchRow(title="Dunkles Design",
                                      subtitle="Nothing-typisches Schwarz statt Hell")
        self.dark_row.set_active(cfg.get("theme") != "light")
        self.dark_row.connect("notify::active", lambda r, _p: cfg.set("theme", "dark" if r.get_active() else "light"))
        g.add(self.dark_row)
        self.widget.add(g)

        g = group("Kontrastfarbe", "Wird für Hervorhebungen, aktive Schalter und Punkte verwendet.")
        row = Adw.PreferencesRow(activatable=False)
        box = Gtk.Box(spacing=10, margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        self.swatches = []
        for name, hx in ACCENTS:
            b = Gtk.Button(tooltip_text=name)
            b.set_size_request(36, 36)
            b.add_css_class("circular")
            css_for(b, f"button {{ background: {hx}; min-width: 36px; min-height: 36px; padding: 0; "
                       f"border: 3px solid transparent; }} button.sel {{ border-color: @window_fg_color; }}")
            b.hex = hx
            b.connect("clicked", lambda _b, hx=hx: self.set_accent(hx))
            self.swatches.append(b)
            box.append(b)
        spacer = Gtk.Box(hexpand=True)
        box.append(spacer)
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(title="Eigene Farbe", with_alpha=False),
                                               tooltip_text="Eigene Farbe", valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse(cfg.get("accent"))
        self.color_btn.set_rgba(rgba)
        self.color_btn.connect("notify::rgba", self._custom_color)
        box.append(self.color_btn)
        row.set_child(box)
        g.add(row)
        self.widget.add(g)

        g = group("Anzeige", "Für sehr hochauflösende Bildschirme, auf denen alles winzig wirkt.")
        self._scales = [1.0, 1.25, 1.5, 1.75, 2.0]
        self.scale_row = Adw.ComboRow(
            title="Skalierung",
            model=Gtk.StringList.new(["100 %", "125 %", "150 %", "175 %", "200 %"]))
        self.scale_row.connect("notify::selected",
            lambda r, _p: cfg.set("display.scale", self._scales[r.get_selected()]))
        g.add(self.scale_row)
        self.widget.add(g)

        g = group("Hintergrundbild")
        self.preview = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, height_request=200,
                                   can_shrink=True)
        self.preview.add_css_class("card")
        self.preview.set_overflow(Gtk.Overflow.HIDDEN)
        g.add(self.preview)
        self.flow = Gtk.FlowBox(max_children_per_line=5, min_children_per_line=3,
                                selection_mode=Gtk.SelectionMode.NONE, row_spacing=8,
                                column_spacing=8, margin_top=12, homogeneous=True)
        g.add(self.flow)
        self.fill_wallpapers()

        choose = Adw.ActionRow(title="Eigenes Bild wählen …", activatable=True)
        choose.add_suffix(Gtk.Image(icon_name="folder-pictures-symbolic"))
        choose.connect("activated", self.choose_file)
        g.add(choose)
        fit = Adw.ComboRow(title="Anpassung", model=Gtk.StringList.new(["Füllen", "Einpassen", "Strecken"]))
        fits = ["cover", "contain", "fill"]
        fit.set_selected(fits.index(cfg.get("wallpaper_fit")) if cfg.get("wallpaper_fit") in fits else 0)
        fit.connect("notify::selected", lambda r, _p: cfg.set("wallpaper_fit", fits[r.get_selected()]))
        g.add(fit)
        bg = Adw.ActionRow(title="Hintergrundfarbe", subtitle="Sichtbar bei „Einpassen“ oder ohne Bild")
        bgbtn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        c = Gdk.RGBA()
        c.parse(cfg.get("background_color") or "#000000")
        bgbtn.set_rgba(c)
        bgbtn.connect("notify::rgba", lambda b, _p: cfg.set("background_color", rgba_hex(b.get_rgba())))
        bg.add_suffix(bgbtn)
        g.add(bg)
        none = Adw.ActionRow(title="Kein Bild (nur Farbe)", activatable=True)
        none.connect("activated", lambda *_: self.set_wallpaper(""))
        g.add(none)
        self.widget.add(g)
        cfg.connect("changed", lambda *_: self.sync())
        self.sync()

    def fill_wallpapers(self):
        paths = []
        dirs = [WALLPAPER_DIR, "/usr/share/backgrounds", "/usr/share/backgrounds/gnome",
                os.path.join(GLib.get_user_data_dir(), "backgrounds")]
        for d in dirs:
            if os.path.isdir(d):
                for n in sorted(os.listdir(d)):
                    if n.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".jxl")):
                        paths.append(os.path.join(d, n))
        for p in paths[:40]:
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
            pic.set_size_request(140, 80)
            pic.set_filename(p)
            btn = Gtk.Button(child=pic, tooltip_text=os.path.basename(p))
            btn.add_css_class("flat")
            btn.set_overflow(Gtk.Overflow.HIDDEN)
            css_for(btn, "button { padding: 0; border-radius: 12px; }")
            btn.connect("clicked", lambda _b, p=p: self.set_wallpaper(p))
            self.flow.append(btn)

    def choose_file(self, *_):
        dlg = Gtk.FileDialog(title="Hintergrundbild wählen")
        filt = Gtk.FileFilter(name="Bilder")
        filt.add_mime_type("image/*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(filt)
        dlg.set_filters(store)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                self.set_wallpaper(f.get_path())
        dlg.open(self.widget.get_root(), None, done)

    def set_wallpaper(self, path):
        self.cfg.set("wallpaper", path)

    def set_accent(self, hx):
        self.cfg.set("accent", hx)

    def _custom_color(self, btn, _p):
        hx = rgba_hex(btn.get_rgba())
        if hx.lower() != (self.cfg.get("accent") or "").lower():
            self.cfg.set("accent", hx)

    def sync(self):
        self.dark_row.set_active(self.cfg.get("theme") != "light")
        scale = self.cfg.get("display.scale") or 1.0
        self.scale_row.set_selected(min(range(len(self._scales)),
            key=lambda i: abs(self._scales[i] - scale)))
        for b in self.swatches:
            if b.hex.lower() == (self.cfg.get("accent") or "").lower():
                b.add_css_class("sel")
            else:
                b.remove_css_class("sel")
        p = self.cfg.get("wallpaper") or ""
        if p and os.path.exists(p):
            self.preview.set_filename(p)
        else:
            self.preview.set_paintable(None)


def rgba_hex(rgba):
    return "#{:02X}{:02X}{:02X}".format(int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))


# ======================================================================
class WidgetsPage:
    def __init__(self, cfg):
        self.cfg = cfg
        self.widget = page("Widgets")
        self.active = group("Auf dem Schreibtisch",
                            "Widgets lassen sich auch per Rechtsklick auf den Schreibtisch "
                            "→ „Widgets bearbeiten“ verschieben.")
        self.widget.add(self.active)
        self.rows = []

        g = group("Widget hinzufügen")
        types = list(WIDGET_TYPES.items())
        self.combo = Adw.ComboRow(title="Typ", model=Gtk.StringList.new([c.NAME for _t, c in types]))
        add = Gtk.Button(label="Hinzufügen", valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self.add(types[self.combo.get_selected()][0]))
        self.combo.add_suffix(add)
        g.add(self.combo)
        self.widget.add(g)

        g = group("Wetter", "Daten von open-meteo.com (ohne Konto).")
        self.city = Adw.EntryRow(title="Ort suchen", show_apply_button=True)
        self.city.set_text(cfg.get("weather.city") or "")
        self.city.connect("apply", self.search_city)
        g.add(self.city)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("boxed-list")
        self.results.set_visible(False)
        self.results.set_margin_top(8)
        g.add(self.results)
        self.widget.add(g)

        g = group("Foto-Widget")
        row = Adw.ActionRow(title="Foto", subtitle=os.path.basename(cfg.get("photo") or "") or "Keins gewählt",
                            activatable=True)
        row.add_suffix(Gtk.Image(icon_name="image-x-generic-symbolic"))
        row.connect("activated", self.choose_photo)
        self.photo_row = row
        g.add(row)
        self.widget.add(g)
        cfg.connect("changed", lambda *_: self.sync())
        self.sync()

    def sync(self):
        for r in self.rows:
            self.active.remove(r)
        self.rows = []
        for i, spec in enumerate(self.cfg.get("widgets") or []):
            cls = WIDGET_TYPES.get(spec.get("type"))
            if not cls:
                continue
            r = Adw.ActionRow(title=cls.NAME, subtitle=f"Position {spec.get('x', 0)} × {spec.get('y', 0)}")
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Entfernen")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, i=i: self.remove(i))
            r.add_suffix(rm)
            self.active.add(r)
            self.rows.append(r)
        self.photo_row.set_subtitle(os.path.basename(self.cfg.get("photo") or "") or "Keins gewählt")

    def add(self, wtype):
        specs = list(self.cfg.get("widgets") or [])
        y = 72 + 24 * len(specs)
        specs.append({"type": wtype, "x": 440, "y": y})
        self.cfg.set("widgets", specs)

    def remove(self, index):
        specs = list(self.cfg.get("widgets") or [])
        if 0 <= index < len(specs):
            del specs[index]
            self.cfg.set("widgets", specs)

    def search_city(self, entry):
        q = urllib.parse.urlencode({"name": entry.get_text(), "count": 6, "language": "de"})
        fetch_json("https://geocoding-api.open-meteo.com/v1/search?" + q, self._results)

    def _results(self, data):
        while (c := self.results.get_first_child()) is not None:
            self.results.remove(c)
        res = (data or {}).get("results") or []
        self.results.set_visible(True)
        if not res:
            self.results.append(Adw.ActionRow(title="Nichts gefunden"))
            return False
        for r in res:
            sub = ", ".join(x for x in (r.get("admin1"), r.get("country")) if x)
            row = Adw.ActionRow(title=r.get("name", ""), subtitle=sub, activatable=True)
            row.connect("activated", lambda _r, r=r: self._pick(r))
            self.results.append(row)
        return False

    def _pick(self, r):
        w = dict(self.cfg.get("weather") or {})
        w.update(city=r.get("name"), lat=r.get("latitude"), lon=r.get("longitude"))
        self.cfg.set("weather", w)
        self.city.set_text(r.get("name", ""))
        self.results.set_visible(False)
        toast(self.widget, f"Wetter-Ort: {r.get('name')}")

    def choose_photo(self, *_):
        dlg = Gtk.FileDialog(title="Foto wählen")

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                self.cfg.set("photo", f.get_path())
        dlg.open(self.widget.get_root(), None, done)


# ======================================================================
class DockPage:
    def __init__(self, cfg):
        self.cfg = cfg
        self.widget = page("Dock & Leiste")
        g = group("Dock")
        size = Adw.SpinRow.new_with_range(32, 80, 4)
        size.set_title("Symbolgröße")
        size.set_value(cfg.get("dock.icon_size") or 48)
        size.connect("notify::value", lambda r, _p: cfg.set("dock.icon_size", int(r.get_value())))
        g.add(size)
        self.choices = []
        for key, title, subtitle, choices in (
                ("icons", "App-Symbole", "Im Dock und in der App-Suche",
                 (("nothing", "Nothing (einfarbig)"), ("original", "Original"))),
                ("dock.launcher", "App-Menü-Knopf", "Position im Dock",
                 (("left", "Links"), ("right", "Rechts")))):
            row = Adw.ComboRow(title=title, subtitle=subtitle,
                               model=Gtk.StringList.new([label for _v, label in choices]))
            values = [v for v, _label in choices]
            row.set_selected(values.index(cfg.get(key)) if cfg.get(key) in values else 0)
            row.connect("notify::selected", lambda r, _p, key=key, values=values:
                        cfg.set(key, values[r.get_selected()]))
            g.add(row)
            self.choices.append((row, key, values))
        self.widget.add(g)

        self.pinned = group("Angeheftete Apps")
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="App hinzufügen")
        add.add_css_class("flat")
        add.connect("clicked", self.add_app)
        self.pinned.set_header_suffix(add)
        self.widget.add(self.pinned)
        self.rows = []

        g = group("Obere Leiste")
        for key, title in (("bar.clock_24h", "24-Stunden-Uhr"), ("bar.show_seconds", "Sekunden anzeigen"),
                           ("bar.show_date", "Datum anzeigen"), ("bar.show_workspaces", "Arbeitsflächen-Punkte")):
            r = Adw.SwitchRow(title=title)
            r.set_active(bool(cfg.get(key)))
            r.connect("notify::active", lambda r, _p, key=key: cfg.set(key, r.get_active()))
            g.add(r)
        self.widget.add(g)
        cfg.connect("changed", lambda *_: self.sync())
        self.sync()

    def sync(self):
        for row, key, values in self.choices:
            if self.cfg.get(key) in values:
                row.set_selected(values.index(self.cfg.get(key)))
        for r in self.rows:
            self.pinned.remove(r)
        self.rows = []
        pinned = self.cfg.get("dock.pinned") or []
        for i, did in enumerate(pinned):
            try:
                app = Gio.DesktopAppInfo.new(did)
            except TypeError:
                app = None
            r = Adw.ActionRow(title=app.get_display_name() if app else did,
                              subtitle="" if app else "Nicht installiert")
            r.add_prefix(Gtk.Image(gicon=app_icon(app), pixel_size=32))
            for icon, delta in (("go-up-symbolic", -1), ("go-down-symbolic", 1)):
                b = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER)
                b.add_css_class("flat")
                b.set_sensitive(0 <= i + delta < len(pinned))
                b.connect("clicked", lambda _b, i=i, d=delta: self.move(i, d))
                r.add_suffix(b)
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, i=i: self.remove(i))
            r.add_suffix(rm)
            self.pinned.add(r)
            self.rows.append(r)

    def move(self, i, d):
        p = list(self.cfg.get("dock.pinned") or [])
        p[i], p[i + d] = p[i + d], p[i]
        self.cfg.set("dock.pinned", p)

    def remove(self, i):
        p = list(self.cfg.get("dock.pinned") or [])
        del p[i]
        self.cfg.set("dock.pinned", p)

    def add_app(self, *_):
        dlg = AppChooser("App anheften", lambda app: self.cfg.set(
            "dock.pinned", list(self.cfg.get("dock.pinned") or []) + [app.get_id()]))
        dlg.present(self.widget.get_root())


class AppChooser(Adw.Dialog):
    def __init__(self, title, on_pick):
        super().__init__(title=title, content_width=420, content_height=560)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12,
                      margin_end=12, margin_bottom=12)
        search = Gtk.SearchEntry(placeholder_text="Suchen …")
        box.append(search)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show()),
                      key=lambda a: a.get_display_name().lower())
        for a in apps:
            r = Adw.ActionRow(title=a.get_display_name(), activatable=True)
            r.add_prefix(Gtk.Image(gicon=app_icon(a), pixel_size=32))
            r.app = a
            r.connect("activated", lambda r: (on_pick(r.app), self.close()))
            lb.append(r)
        lb.set_filter_func(lambda r: search.get_text().lower() in r.app.get_display_name().lower())
        search.connect("search-changed", lambda *_: lb.invalidate_filter())
        box.append(Gtk.ScrolledWindow(child=lb, vexpand=True))
        tv.set_content(box)
        self.set_child(tv)


# ======================================================================
class WorkspacesPage:
    def __init__(self, cfg):
        self.widget = page("Arbeitsflächen")
        g = group("Virtuelle Arbeitsflächen")
        n = Adw.SpinRow.new_with_range(1, 10, 1)
        n.set_title("Anzahl")
        n.set_value(cfg.get("workspaces") or 4)
        n.connect("notify::value", lambda r, _p: cfg.set("workspaces", int(r.get_value())))
        g.add(n)
        self.widget.add(g)
        g = group("Tastenkürzel")
        for keys, desc in (
            ("Super + 1 … 0", "Zu Arbeitsfläche wechseln"),
            ("Super + Umschalt + 1 … 0", "Fenster auf Arbeitsfläche verschieben"),
            ("Super + Strg + ← / →", "Vorherige / nächste Arbeitsfläche"),
            ("Super + Umschalt + ← / →", "Fenster mitnehmen"),
            ("Super + Leertaste", "Apps & Suche"),
            ("Super + A", "Kontrollzentrum"),
            ("Super + Eingabe", "Terminal"),
            ("Super + E", "Dateien"),
            ("Super + ,", "Einstellungen"),
            ("Super + L", "Bildschirm sperren"),
            ("Super + D", "Schreibtisch anzeigen"),
            ("Super + Q", "Fenster schließen"),
            ("Super + F / ↑ / ↓ / M", "Vollbild / Maximieren / Wiederherstellen / Minimieren"),
            ("Super + Ziehen (links / rechts)", "Fenster verschieben / Größe ändern"),
            ("Alt + Tab", "Fenster wechseln"),
            ("Druck", "Bildschirmfoto"),
            ("Super + Umschalt + Esc", "Abmelden"),
        ):
            r = Adw.ActionRow(title=desc)
            k = Gtk.Label(label=keys)
            k.add_css_class("dim-label")
            k.add_css_class("monospace")
            r.add_suffix(k)
            g.add(r)
        self.widget.add(g)


# ======================================================================
DEFAULT_TYPES = [
    ("Webbrowser", "web-browser-symbolic", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    ("E-Mail", "mail-unread-symbolic", ["x-scheme-handler/mailto"]),
    ("Kalender", "x-office-calendar-symbolic", ["text/calendar"]),
    ("Musik", "audio-x-generic-symbolic", ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav"]),
    ("Video", "video-x-generic-symbolic", ["video/mp4", "video/x-matroska", "video/webm"]),
    ("Fotos", "image-x-generic-symbolic", ["image/jpeg", "image/png", "image/gif", "image/webp"]),
    ("Texteditor", "text-x-generic-symbolic", ["text/plain"]),
    ("PDF", "x-office-document-symbolic", ["application/pdf"]),
    ("Dateien", "folder-symbolic", ["inode/directory"]),
]


class DefaultAppsPage:
    def __init__(self, cfg):
        self.cfg = cfg
        self.widget = page("Standard-Apps")
        g = group("Standardanwendungen", "Welche App öffnet welche Inhalte.")
        for title, icon, types in DEFAULT_TYPES:
            apps = []
            for t in types[:1]:
                apps = Gio.AppInfo.get_all_for_type(t)
            if not apps:
                r = Adw.ActionRow(title=title, subtitle="Keine passende App installiert")
                r.add_prefix(Gtk.Image(icon_name=icon))
                g.add(r)
                continue
            names = [a.get_display_name() for a in apps]
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new(names))
            row.add_prefix(Gtk.Image(icon_name=icon))
            cur = Gio.AppInfo.get_default_for_type(types[0], False)
            if cur:
                for i, a in enumerate(apps):
                    if a.get_id() == cur.get_id():
                        row.set_selected(i)
            row.connect("notify::selected", lambda r, _p, apps=apps, types=types: self.set_default(apps[r.get_selected()], types))
            g.add(row)
        self.widget.add(g)

        g = group("Terminal")
        terms = [a for a in Gio.AppInfo.get_all()
                 if isinstance(a, Gio.DesktopAppInfo) and "TerminalEmulator" in (a.get_categories() or "")]
        names = ["Automatisch"] + [a.get_display_name() for a in terms]
        row = Adw.ComboRow(title="Terminal", model=Gtk.StringList.new(names))
        row.add_prefix(Gtk.Image(icon_name="utilities-terminal-symbolic"))
        cur = cfg.get("terminal") or ""
        for i, a in enumerate(terms):
            if cur and a.get_executable() and os.path.basename(a.get_executable()) == cur.split()[0]:
                row.set_selected(i + 1)

        def pick(r, _p):
            i = r.get_selected()
            cfg.set("terminal", "" if i == 0 else os.path.basename(terms[i - 1].get_executable() or ""))
        row.connect("notify::selected", pick)
        g.add(row)
        self.widget.add(g)

    def set_default(self, app, types):
        for t in types:
            try:
                app.set_as_default_for_type(t)
            except GLib.Error as e:
                print("default app:", e.message)
        toast(self.widget, f"{app.get_display_name()} ist jetzt Standard")


# ======================================================================
LAYOUTS = [("de", "Deutsch"), ("de(nodeadkeys)", "Deutsch (ohne Tottasten)"), ("ch", "Schweiz"),
           ("at", "Österreich"), ("us", "Englisch (US)"), ("gb", "Englisch (UK)"),
           ("fr", "Französisch"), ("es", "Spanisch"), ("it", "Italienisch"), ("nl", "Niederländisch"),
           ("pl", "Polnisch"), ("tr", "Türkisch"), ("us(intl)", "US International")]


class KeyboardPage:
    def __init__(self, cfg):
        self.cfg = cfg
        self.widget = page("Tastatur")
        g = group("Tastaturbelegung")
        names = [n for _c, n in LAYOUTS]
        row = Adw.ComboRow(title="Belegung", model=Gtk.StringList.new(names))
        kb = cfg.get("keyboard") or {}
        cur = kb.get("layout", "de") + (f"({kb['variant']})" if kb.get("variant") else "")
        for i, (code, _n) in enumerate(LAYOUTS):
            if code == cur:
                row.set_selected(i)
        row.connect("notify::selected", lambda r, _p: self.set_layout(LAYOUTS[r.get_selected()][0]))
        g.add(row)
        opts = Adw.EntryRow(title="XKB-Optionen (z. B. caps:escape)", show_apply_button=True)
        opts.set_text(kb.get("options") or "")
        opts.connect("apply", lambda e: self.update(options=e.get_text().strip()))
        g.add(opts)
        test = Adw.EntryRow(title="Hier testen")
        g.add(test)
        self.widget.add(g)

    def set_layout(self, code):
        layout, variant = code, ""
        if "(" in code:
            layout, variant = code[:-1].split("(")
        self.update(layout=layout, variant=variant)

    def update(self, **kw):
        kb = dict(self.cfg.get("keyboard") or {})
        kb.update(kw)
        self.cfg.set("keyboard", kb)


# ======================================================================
class UsersPage:
    def __init__(self, cfg):
        self.widget = page("Benutzer")
        self.me_group = group("Ihr Konto")
        self.others = group("Weitere Benutzer")
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Benutzer hinzufügen")
        add.add_css_class("flat")
        add.connect("clicked", self.add_user)
        self.others.set_header_suffix(add)
        self.widget.add(self.me_group)
        self.widget.add(self.others)
        self.rows = []
        self.Act = None
        try:
            gi.require_version("AccountsService", "1.0")
            from gi.repository import AccountsService as Act
            self.Act = Act
            self.manager = Act.UserManager.get_default()
            if self.manager.props.is_loaded:
                self.populate()
            else:
                self.manager.connect("notify::is-loaded", lambda *_: self.populate())
            self.manager.connect("user-added", lambda *_: self.populate())
            self.manager.connect("user-removed", lambda *_: self.populate())
        except (ValueError, ImportError):
            self.me_group.add(Adw.ActionRow(title="AccountsService ist nicht verfügbar"))

    def populate(self):
        for g, r in self.rows:
            g.remove(r)
        self.rows = []
        me = os.getuid()
        for u in sorted(self.manager.list_users(), key=lambda u: u.get_uid()):
            name = u.get_real_name() or u.get_user_name()
            admin = u.get_account_type() == self.Act.UserAccountType.ADMINISTRATOR
            if u.get_uid() == me:
                self._me_rows(u, name, admin)
                continue
            r = Adw.ActionRow(title=name, subtitle=u.get_user_name() + (" · Administrator" if admin else ""))
            av = Adw.Avatar(size=40, text=name, show_initials=True)
            if u.get_icon_file() and os.path.exists(u.get_icon_file()):
                av.set_custom_image(Gdk.Texture.new_from_filename(u.get_icon_file()))
            r.add_prefix(av)
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Benutzer löschen")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda _b, u=u: self.delete_user(u))
            r.add_suffix(rm)
            self.others.add(r)
            self.rows.append((self.others, r))

    def _me_rows(self, u, name, admin):
        head = Adw.PreferencesRow(activatable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=18, margin_bottom=18)
        av = Adw.Avatar(size=96, text=name, show_initials=True)
        if u.get_icon_file() and os.path.exists(u.get_icon_file()):
            try:
                av.set_custom_image(Gdk.Texture.new_from_filename(u.get_icon_file()))
            except GLib.Error:
                pass
        btn = Gtk.Button(child=av, halign=Gtk.Align.CENTER, tooltip_text="Bild ändern")
        btn.add_css_class("flat")
        btn.add_css_class("circular")
        btn.connect("clicked", lambda *_: self.pick_avatar(u))
        box.append(btn)
        lbl = Gtk.Label(label=u.get_user_name() + (" · Administrator" if admin else ""))
        lbl.add_css_class("dim-label")
        box.append(lbl)
        head.set_child(box)
        self.me_group.add(head)
        self.rows.append((self.me_group, head))

        real = Adw.EntryRow(title="Vollständiger Name", show_apply_button=True)
        real.set_text(u.get_real_name() or "")
        real.connect("apply", lambda e: u.set_real_name(e.get_text()))
        self.me_group.add(real)
        self.rows.append((self.me_group, real))
        pw = Adw.ActionRow(title="Passwort ändern …", activatable=True)
        pw.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        pw.connect("activated", lambda *_: self.change_password(u))
        self.me_group.add(pw)
        self.rows.append((self.me_group, pw))

    def pick_avatar(self, u):
        dlg = Gtk.FileDialog(title="Benutzerbild wählen")

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f and f.get_path():
                u.set_icon_file(f.get_path())
                GLib.timeout_add(500, lambda: (self.populate(), False)[1])
        dlg.open(self.widget.get_root(), None, done)

    def change_password(self, u):
        dlg = Adw.AlertDialog(heading="Passwort ändern",
                              body="Das neue Passwort wird über AccountsService gesetzt. "
                                   "Eventuell fragt das System nach Ihrem aktuellen Passwort.")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        p1 = Gtk.PasswordEntry(placeholder_text="Neues Passwort", show_peek_icon=True)
        p2 = Gtk.PasswordEntry(placeholder_text="Wiederholen", show_peek_icon=True)
        box.append(p1)
        box.append(p2)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("ok", "Ändern")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r != "ok":
                return
            if not p1.get_text() or p1.get_text() != p2.get_text():
                toast(self.widget, "Passwörter stimmen nicht überein")
                return
            u.set_password(p1.get_text(), "")
            toast(self.widget, "Passwort geändert")
        dlg.connect("response", resp)
        dlg.present(self.widget.get_root())

    def add_user(self, *_):
        dlg = Adw.AlertDialog(heading="Benutzer hinzufügen")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        full = Gtk.Entry(placeholder_text="Vollständiger Name")
        user = Gtk.Entry(placeholder_text="Benutzername")
        admin = Gtk.CheckButton(label="Administrator")
        pw = Gtk.PasswordEntry(placeholder_text="Passwort", show_peek_icon=True)
        full.connect("changed", lambda e: user.set_text(
            "".join(c for c in e.get_text().lower().replace(" ", "") if c.isalnum())[:30]))
        for w in (full, user, pw, admin):
            box.append(w)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("ok", "Hinzufügen")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            if r != "ok" or not user.get_text():
                return
            kind = (self.Act.UserAccountType.ADMINISTRATOR if admin.get_active()
                    else self.Act.UserAccountType.STANDARD)
            try:
                nu = self.manager.create_user(user.get_text(), full.get_text(), kind)
                if pw.get_text():
                    nu.set_password(pw.get_text(), "")
                toast(self.widget, "Benutzer angelegt")
            except GLib.Error as e:
                toast(self.widget, f"Fehlgeschlagen: {e.message}")
        dlg.connect("response", resp)
        dlg.present(self.widget.get_root())

    def delete_user(self, u):
        dlg = Adw.AlertDialog(heading=f"{u.get_user_name()} löschen?",
                              body="Persönliche Dateien werden ebenfalls entfernt.")
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("del", "Löschen")
        dlg.set_response_appearance("del", Adw.ResponseAppearance.DESTRUCTIVE)

        def resp(_d, r):
            if r == "del":
                try:
                    self.manager.delete_user(u, True)
                except GLib.Error as e:
                    toast(self.widget, f"Fehlgeschlagen: {e.message}")
        dlg.connect("response", resp)
        dlg.present(self.widget.get_root())


# ======================================================================
PROVIDERS = [("google", "Google", "goa-account-google"), ("ms_graph", "Microsoft 365", "goa-account-msn"),
             ("owncloud", "Nextcloud", "goa-account-owncloud"), ("imap_smtp", "E-Mail (IMAP/SMTP)", "mail-send-symbolic"),
             ("webdav", "WebDAV / CalDAV", "network-server-symbolic"), ("exchange", "Exchange", "goa-account-exchange")]

SERVICES = [("mail", "E-Mail"), ("calendar", "Kalender"), ("contacts", "Kontakte"),
            ("files", "Dateien"), ("documents", "Dokumente"), ("photos", "Fotos")]


class AccountsPage:
    """GNOME Online Accounts integration (same backend as GNOME: goa-daemon)."""

    def __init__(self, cfg):
        self.widget = page("Online-Konten")
        self.list = group("Verbundene Konten",
                          "Konten werden mit GNOME Online Accounts verwaltet und stehen Apps wie "
                          "Kalender, Kontakte, Evolution oder Nautilus zur Verfügung.")
        self.widget.add(self.list)
        self.rows = []
        g = group("Konto hinzufügen")
        for pid, title, icon in PROVIDERS:
            r = Adw.ActionRow(title=title, activatable=True)
            r.add_prefix(Gtk.Image(icon_name=icon, pixel_size=32))
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            r.connect("activated", lambda _r, pid=pid: self.add_account(pid))
            g.add(r)
        self.widget.add(g)
        self.client = None
        try:
            gi.require_version("Goa", "1.0")
            from gi.repository import Goa
            self.Goa = Goa
            Goa.Client.new(None, self._ready)
        except (ValueError, ImportError):
            self.list.add(Adw.ActionRow(title="gnome-online-accounts ist nicht installiert"))

    def _ready(self, _src, res):
        try:
            self.client = self.Goa.Client.new_finish(res)
        except GLib.Error as e:
            self.list.add(Adw.ActionRow(title="goa-daemon nicht erreichbar", subtitle=e.message))
            return
        for sig in ("account-added", "account-removed", "account-changed"):
            self.client.connect(sig, lambda *_: self.populate())
        self.populate()

    def populate(self):
        for r in self.rows:
            self.list.remove(r)
        self.rows = []
        objs = self.client.get_accounts() if self.client else []
        if not objs:
            r = Adw.ActionRow(title="Noch keine Konten verbunden")
            self.list.add(r)
            self.rows.append(r)
        for obj in objs:
            acc = obj.get_account()
            exp = Adw.ExpanderRow(title=acc.props.provider_name, subtitle=acc.props.presentation_identity)
            try:
                gicon = Gio.Icon.new_for_string(acc.props.provider_icon)
                exp.add_prefix(Gtk.Image(gicon=gicon, pixel_size=32))
            except GLib.Error:
                pass
            if acc.props.attention_needed:
                exp.set_subtitle(exp.get_subtitle() + " · Anmeldung erforderlich")
            for key, title in SERVICES:
                getter = getattr(obj, f"get_{key}", None)
                if getter is None or getter() is None:
                    continue
                prop = f"{key}_disabled"
                sw = Adw.SwitchRow(title=title)
                sw.set_active(not acc.get_property(prop))
                sw.connect("notify::active", lambda r, _p, acc=acc, prop=prop: acc.set_property(prop, not r.get_active()))
                exp.add_row(sw)
            rm = Adw.ActionRow(title="Konto entfernen", activatable=True)
            rm.add_css_class("error")
            rm.connect("activated", lambda _r, acc=acc: acc.call_remove(None, None, None))
            exp.add_row(rm)
            self.list.add(exp)
            self.rows.append(exp)

    def add_account(self, provider):
        """Adding needs GOA's interactive dialog which lives in gnome-control-center."""
        if shutil.which("gnome-control-center"):
            env = dict(os.environ, XDG_CURRENT_DESKTOP="GNOME")
            subprocess.Popen(["gnome-control-center", "online-accounts", provider], env=env,
                             start_new_session=True)
        else:
            toast(self.widget, "Zum Hinzufügen wird gnome-control-center benötigt")


# ======================================================================
class AboutPage:
    def __init__(self, cfg):
        self.widget = page("Info")
        g = group()
        hero = Adw.PreferencesRow(activatable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=28, margin_bottom=28)
        logo = dotmatrix.DotLabel("NOTHING", pitch=7, align=0.5)
        logo.set_halign(Gtk.Align.CENTER)
        logo.accent_last = True
        r, gg, b = hex_to_rgb(cfg.get("accent"))
        logo.set_accent((r, gg, b, 1))
        box.append(logo)
        sub = Gtk.Label(label="DESKTOP · WAYLAND")
        sub.add_css_class("dim-label")
        sub.add_css_class("monospace")
        box.append(sub)
        hero.set_child(box)
        g.add(hero)
        self.widget.add(g)

        g = group("System")
        os_name = "Linux"
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        cpu = platform.processor() or ""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
        mem = ""
        try:
            with open("/proc/meminfo") as f:
                kb = int(f.readline().split()[1])
                mem = f"{kb / 1024 / 1024:.1f} GiB"
        except (OSError, ValueError, IndexError):
            pass
        disk = shutil.disk_usage("/")
        for title, value in (("Gerätename", socket.gethostname()), ("Betriebssystem", os_name),
                             ("Kernel", platform.release()), ("Prozessor", cpu), ("Arbeitsspeicher", mem),
                             ("Speicher", f"{disk.used / 1e9:.0f} von {disk.total / 1e9:.0f} GB belegt"),
                             ("Fenstersystem", "Wayland (nothing-wm) + XWayland")):
            row = Adw.ActionRow(title=title, subtitle=value, subtitle_selectable=True)
            row.add_css_class("property")
            g.add(row)
        self.widget.add(g)


# ======================================================================
class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app, cfg, start_page):
        super().__init__(application=app, title="Einstellungen", default_width=1000, default_height=720)
        self.toasts = Adw.ToastOverlay()
        split = Adw.NavigationSplitView(min_sidebar_width=240)
        side_tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        title = Gtk.Label(label="EINSTELLUNGEN")
        title.add_css_class("heading")
        title.add_css_class("monospace")
        hb.set_title_widget(title)
        side_tv.add_top_bar(hb)
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        side_tv.set_content(Gtk.ScrolledWindow(child=self.sidebar))
        split.set_sidebar(Adw.NavigationPage(title="Einstellungen", child=side_tv))

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.content_tv = Adw.ToolbarView()
        self.content_hb = Adw.HeaderBar()
        self.content_tv.add_top_bar(self.content_hb)
        self.content_tv.set_content(self.stack)
        self.content_page = Adw.NavigationPage(title="", child=self.content_tv)
        split.set_content(self.content_page)
        self.split = split

        builders = {"appearance": AppearancePage, "widgets": WidgetsPage, "dock": DockPage,
                    "workspaces": WorkspacesPage, "apps": DefaultAppsPage, "keyboard": KeyboardPage,
                    "users": UsersPage, "accounts": AccountsPage, "about": AboutPage}
        self.pages = {}
        self.cfg = cfg
        self.builders = builders
        for pid, name, icon in PAGES:
            row = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6)
            row.append(Gtk.Image(icon_name=icon))
            row.append(Gtk.Label(label=name, xalign=0))
            lbr = Gtk.ListBoxRow(child=row)
            lbr.pid = pid
            lbr.title = name
            self.sidebar.append(lbr)
        self.sidebar.connect("row-activated", lambda _l, r: self.show_page(r.pid, r.title))
        self.toasts.set_child(split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(split, "collapsed", True)
        self.add_breakpoint(bp)

        start = next((p for p in PAGES if p[0] == start_page), PAGES[0])
        idx = PAGES.index(start)
        self.sidebar.select_row(self.sidebar.get_row_at_index(idx))
        self.show_page(start[0], start[1])

    def show_page(self, pid, title):
        if pid not in self.pages:
            try:
                p = self.builders[pid](self.cfg)
            except Exception as e:  # keep the app usable if one page breaks
                p = type("Broken", (), {})()
                p.widget = Adw.StatusPage(title="Seite konnte nicht geladen werden", description=str(e),
                                          icon_name="dialog-error-symbolic")
            self.pages[pid] = p
            self.stack.add_named(p.widget, pid)
        self.stack.set_visible_child_name(pid)
        self.content_page.set_title(title)
        idx = next(i for i, p in enumerate(PAGES) if p[0] == pid)
        row = self.sidebar.get_row_at_index(idx)
        if self.sidebar.get_selected_row() is not row:
            self.sidebar.select_row(row)
        self.split.set_show_content(True)


class SettingsApp(Adw.Application):
    def __init__(self, start_page):
        super().__init__(application_id="eu.nothing_de.Settings",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.start_page = start_page
        self.win = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.cfg = get_config()
        self.theme = ThemeManager(self.cfg, sync_gsettings=False)

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        page_ = self.start_page
        if "--page" in args and args.index("--page") + 1 < len(args):
            page_ = args[args.index("--page") + 1]
        if self.win is None:
            self.win = SettingsWindow(self, self.cfg, page_)
        else:
            for pid, name, _i in PAGES:
                if pid == page_:
                    self.win.show_page(pid, name)
        self.win.present()
        return 0


def main():
    parser = argparse.ArgumentParser(prog="nothing-settings")
    parser.add_argument("--page", default="appearance", choices=[p[0] for p in PAGES])
    args, _rest = parser.parse_known_args()
    return SettingsApp(args.page).run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
