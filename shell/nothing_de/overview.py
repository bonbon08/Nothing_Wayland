"""Overview (GNOME-like): rauszoomen und alle Fenster als Kacheln sehen.

Wird über die linke obere Ecke oder Super + W geöffnet. Ein Klick
auf eine Kachel fokussiert das Fenster und schließt den Overview wieder.
"""
from gi.repository import Gtk, Pango

from . import layer
from .icons import icon_widget


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

    def open_overlay(self):
        windows = [w for w in self.shell.wm.state.get("windows", [])
                   if w.get("taskbar", True)]
        while (c := self.flow.get_first_child()) is not None:
            self.flow.remove(c)
        for w in windows:
            self._tile(w)
        self.empty.set_visible(not windows)
        super().open_overlay()

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

        btn = Gtk.Button(child=tile)
        btn.add_css_class("flat")
        btn.connect("clicked", lambda _b, i=wid: self._pick(i))
        self.flow.append(btn)

    def _pick(self, wid):
        self.close_overlay()
        self.shell.wm.focus(wid)
