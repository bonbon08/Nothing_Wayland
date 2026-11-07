"""Overview (GNOME-like): rauszoomen und alle Fenster als Kacheln sehen.

Wird über die linke obere Ecke oder Super + W geöffnet, auf dem Telefon mit einem langen Wisch
von der Home-Leiste nach oben. Ein Klick auf eine Kachel fokussiert das Fenster und schließt
den Overview wieder. Das × auf einer Kachel schließt das Fenster.

Auf dem Telefon ist die Übersicht eine Liste der offenen Apps über die ganze Breite: Tippen
wechselt zur App, zur Seite wischen oder × schließt sie, „Alle schließen“ schließt alle.
"""
from gi.repository import GLib, Gtk, Pango

from . import layer
from .icons import icon_widget

SWIPE_CLOSE = 110   # px sideways that close an app on the phone


class Overview(layer.Overlay):
    """Kacheln aller Fenster, mit ihrer Arbeitsfläche."""

    def __init__(self, shell):
        super().__init__(shell.app, "nothing-overview", dim=True)
        self.shell = shell
        self.cfg = shell.cfg
        self.panel.set_size_request(800, 480)

        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.empty = Gtk.Label(label="Keine offenen Fenster", vexpand=True)
        self.empty.add_css_class("n-muted")
        self.panel.append(self.empty)

        self.flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=4, min_children_per_line=2,
            homogeneous=True, row_spacing=16, column_spacing=16,
            valign=Gtk.Align.START)
        scrolled.set_child(self.flow)
        self.panel.append(scrolled)

        # phone only: closes every app
        self.close_all = Gtk.Button(label="Alle schließen", halign=Gtk.Align.CENTER)
        self.close_all.add_css_class("n-pill-button")
        self.close_all.set_margin_top(12)
        self.close_all.connect("clicked", lambda *_: self._close_all())
        self.panel.append(self.close_all)

    def open_overlay(self):
        self._populate()
        super().open_overlay()

    def _populate(self):
        # phone: the panel fills the screen between the bars, one card per row
        narrow = bool(self.shell.phone)
        self.panel.set_size_request(-1 if narrow else 800, -1 if narrow else 480)
        for side in ("start", "end", "top", "bottom"):
            getattr(self.panel, f"set_margin_{side}")(12 if narrow else 0)
        self.panel.set_halign(Gtk.Align.FILL if narrow else Gtk.Align.CENTER)
        self.panel.set_valign(Gtk.Align.FILL if narrow else Gtk.Align.CENTER)
        self.flow.set_min_children_per_line(1 if narrow else 2)
        self.flow.set_max_children_per_line(1 if narrow else 4)
        self.flow.set_row_spacing(10 if narrow else 16)
        self.empty.set_label("Keine offenen Apps" if narrow else "Keine offenen Fenster")

        windows = [w for w in self.shell.wm.state.get("windows", [])
                   if w.get("taskbar", True)]
        while (c := self.flow.get_first_child()) is not None:
            self.flow.remove(c)
        for w in windows:
            if narrow:
                self._phone_card(w)
            else:
                self._tile(w)
        self.empty.set_visible(not windows)
        self.close_all.set_visible(narrow and len(windows) > 1)

    def _phone_card(self, w):
        """A row per app: icon, title and name; tap switches, a sideways swipe closes."""
        wid = w["id"]
        app = self.shell.apps.lookup(w.get("app_id"))
        card = Gtk.Box(spacing=14)
        card.add_css_class("n-overview-tile")
        card.append(icon_widget(app, 52, self.cfg))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True,
                       valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=app.get_display_name() if app else (w.get("app_id") or "App"),
                         xalign=0, ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("n-overview-title")
        text.append(name)
        title = Gtk.Label(label=w.get("title") or "", xalign=0,
                          ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("n-muted")
        text.append(title)
        card.append(text)
        close = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
        close.add_css_class("n-round")
        close.connect("clicked", lambda _b: self._close(wid))
        card.append(close)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._pick(wid))
        card.add_controller(click)

        drag = Gtk.GestureDrag()

        def update(gesture, dx, dy):
            if abs(dx) > 10 and abs(dx) > abs(dy):
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                card.set_margin_start(max(0, int(dx)))
                card.set_margin_end(max(0, int(-dx)))
                card.set_opacity(max(0.2, 1 - abs(dx) / 300))

        def end(_g, dx, _dy):
            if abs(dx) > SWIPE_CLOSE:
                card.set_sensitive(False)
                self._close(wid)
            else:
                card.set_margin_start(0)
                card.set_margin_end(0)
                card.set_opacity(1)
        drag.connect("drag-update", update)
        drag.connect("drag-end", end)
        card.add_controller(drag)
        self.flow.append(card)

    def _close_all(self):
        for w in self.shell.wm.state.get("windows", []):
            if w.get("taskbar", True):
                self.shell.wm.close(w["id"])
        GLib.timeout_add(350, self._refresh)

    def _tile(self, w):
        wid = w["id"]
        app = self.shell.apps.lookup(w.get("app_id"))

        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tile.add_css_class("n-overview-tile")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.append(icon_widget(app, 48, self.cfg))
        title = Gtk.Label(label=w.get("title") or "Fenster", xalign=0)
        title.add_css_class("n-overview-title")
        title.set_hexpand(True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        header.append(title)
        close = Gtk.Button(icon_name="window-close-symbolic")
        close.add_css_class("flat")
        close.set_valign(Gtk.Align.START)
        close.set_tooltip_text("Schließen")
        close.connect("clicked", lambda _b, i=wid: self._close(i))
        header.append(close)
        tile.append(header)

        app_name = Gtk.Label(
            label=(app.get_display_name() if app else (w.get("app_id") or ""))[:40],
            xalign=0)
        app_name.add_css_class("n-muted")
        app_name.set_ellipsize(Pango.EllipsizeMode.END)
        tile.append(app_name)

        ws_lbl = Gtk.Label(label=f"Arbeitsfläche {w.get('ws', 1)}", xalign=0)
        ws_lbl.add_css_class("n-dim-label")
        tile.append(ws_lbl)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._pick(wid))
        tile.add_controller(click)
        self.flow.append(tile)

    def _pick(self, wid):
        self.close_overlay()
        self.shell.wm.focus(wid)

    def _close(self, wid):
        self.shell.wm.close(wid)
        # the compositor reports the window gone a moment later
        GLib.timeout_add(350, self._refresh)

    def _refresh(self):
        if self.get_visible():
            self._populate()
            # the last app is gone: back to the home screen
            if self.shell.phone and not any(w.get("taskbar", True) for w in
                                            self.shell.wm.state.get("windows", [])):
                self.close_overlay()
        return False
