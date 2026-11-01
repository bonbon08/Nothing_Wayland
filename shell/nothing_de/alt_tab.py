"""Alt+Tab-Fensterwechsler mit Vorschau (App-Icon + Titel pro Fenster)."""
from gi.repository import GLib, Gtk, Pango

from . import layer
from .icons import icon_widget

SHOW_DELAY = 150   # a quick Alt+Tab switches without any flicker


class AltTab(layer.Overlay):
    """Zeigt die Fenster der aktuellen Arbeitsfläche und hebt das fokussierte hervor."""

    def __init__(self, shell):
        # no keyboard: the compositor handles the keys, and an exclusive layer
        # would keep the focus away from the window that is being selected
        super().__init__(shell.app, "nothing-alt-tab", keyboard="none")
        self.shell = shell
        self.cfg = shell.cfg
        self.panel.set_size_request(640, 380)
        self.panel.set_spacing(10)

        hint = Gtk.Label(label="Alt + Tab: Fenster wechseln · loslassen zum Übernehmen", xalign=0)
        hint.add_css_class("n-muted")
        self.panel.append(hint)

        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled.set_child(self.box)
        self.panel.append(scrolled)

        self._timer = None
        # the focus changes right after the key press, the state event tells
        shell.wm.connect("state", lambda *_: self.get_visible() and self._rebuild())

    def cycle(self):
        if not self.get_visible() and self._timer is None:
            self._timer = GLib.timeout_add(SHOW_DELAY, self._open)

    def _open(self):
        self._timer = None
        self._rebuild()
        self.open_overlay()
        return False

    def close_overlay(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        super().close_overlay()

    def _rebuild(self):
        st = self.shell.wm.state
        while (c := self.box.get_first_child()) is not None:
            self.box.remove(c)
        for w in st.get("windows", []):
            if w.get("taskbar", True) and w.get("ws") == st.get("workspace"):
                self._row(w, st.get("focused"))

    def _row(self, w, focused):
        wid = w["id"]
        app = self.shell.apps.lookup(w.get("app_id"))
        row = Gtk.Button()
        row.add_css_class("n-alt-tab-row")
        if wid == focused:
            row.add_css_class("selected")
        row.connect("clicked", lambda _b, i=wid: self._pick(i))

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.append(icon_widget(app, 40, self.cfg))

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_hexpand(True)
        title = Gtk.Label(label=w.get("title") or "Fenster", xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        app_name = Gtk.Label(
            label=(app.get_display_name() if app else (w.get("app_id") or ""))[:44], xalign=0)
        app_name.add_css_class("n-muted")
        app_name.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.append(title)
        vbox.append(app_name)
        box.append(vbox)
        row.set_child(box)
        self.box.append(row)

    def _pick(self, wid):
        self.close_overlay()
        self.shell.wm.focus(wid)
