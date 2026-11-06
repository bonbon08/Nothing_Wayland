"""Telefon-Oberfläche: Startbildschirm mit App-Raster, Statusleiste oben, Home-Leiste unten.

Aktiv bei hochkantem Bildschirm (Einstellung „form“ oder Umgebung NOTHING_FORM=phone). Der Compositor
bleibt derselbe. Fenster bekommen nur den Platz zwischen Statusleiste und Home-Leiste, weil beide
eine Exklusivzone melden. Der Startbildschirm liegt im Hintergrund-Layer, hinter den Fenstern.
"""
import datetime

from gi.repository import GLib, Gtk, Pango

from . import layer, system
from .apps import launch_app
from .bar import MONTHS_SHORT, WEEKDAYS_SHORT
from .icons import icon_widget
from .widgets import read_battery

COLUMNS = 4


def _window_for(shell, app):
    """Erstes offenes Fenster, das zu dieser App gehört (auch minimierte)."""
    for win in shell.wm.state.get("windows", []):
        if shell.apps.lookup(win.get("app_id")) is app:
            return win
    return None


class PhoneHome(Gtk.ApplicationWindow):
    """Startbildschirm: Datum, Uhrzeit und ein Raster aller Apps."""

    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        layer.setup(self, layer="background", anchors=("top", "bottom", "left", "right"),
                    exclusive=-1, keyboard="none", namespace="nothing-home", monitor=monitor)
        if not layer.supported():
            self.set_default_size(400, 800)
        self.add_css_class("n-root")
        self.add_css_class("n-phone-home")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.set_margin_top(84)            # unter der Statusleiste
        root.set_margin_bottom(44)         # über der Home-Leiste
        root.set_margin_start(20)
        root.set_margin_end(20)

        self.date = Gtk.Label(xalign=0)
        self.date.add_css_class("n-caps")
        root.append(self.date)
        self.clock = Gtk.Label(xalign=0)
        self.clock.add_css_class("n-phone-clock")
        root.append(self.clock)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                                max_children_per_line=COLUMNS, min_children_per_line=COLUMNS,
                                homogeneous=True, row_spacing=6, column_spacing=4,
                                activate_on_single_click=True, valign=Gtk.Align.START)
        self.flow.connect("child-activated", self._activated)
        scroll = Gtk.ScrolledWindow(child=self.flow, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    vexpand=True)
        root.append(scroll)
        self.set_child(root)

        shell.apps.listeners.append(self.populate)
        GLib.timeout_add_seconds(1, self._tick)
        self._tick()
        GLib.idle_add(lambda: (self.populate(), False)[1])

    def _tick(self):
        now = datetime.datetime.now()
        self.clock.set_label(now.strftime("%H:%M"))
        self.date.set_label(f"{WEEKDAYS_SHORT[now.weekday()]} {now.day}. {MONTHS_SHORT[now.month - 1]}")
        return True

    def populate(self):
        while (c := self.flow.get_first_child()) is not None:
            self.flow.remove(c)
        for app in self.shell.apps.search("")[:200]:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            tile.add_css_class("n-app-tile")
            tile.append(icon_widget(app, 52, self.shell.cfg))
            tile.append(Gtk.Label(label=app.get_display_name(), ellipsize=Pango.EllipsizeMode.END,
                                  max_width_chars=9, justify=Gtk.Justification.CENTER))
            # lights up while the finger is on it (touch has no hover)
            press = Gtk.GestureClick()
            press.connect("pressed", lambda *_, t=tile: t.add_css_class("pressed"))
            press.connect("released", lambda *_, t=tile: t.remove_css_class("pressed"))
            press.connect("cancel", lambda *_, t=tile: t.remove_css_class("pressed"))
            tile.add_controller(press)
            child = Gtk.FlowBoxChild(child=tile)
            child.app = app
            self.flow.append(child)

    def _activated(self, _flow, child):
        app = child.app
        win = _window_for(self.shell, app)
        if win is not None:
            # focus also brings a minimised window back
            self.shell.wm.focus(win["id"])
        else:
            launch_app(app)


class PhoneStatus(Gtk.ApplicationWindow):
    """Statusleiste oben: Uhrzeit links, Netz und Akku rechts. Tippen öffnet das Kontrollzentrum."""

    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        layer.setup(self, layer="top", anchors=("top", "left", "right"),
                    exclusive="auto", namespace="nothing-status", monitor=monitor)
        self.add_css_class("n-root")

        row = Gtk.CenterBox()
        row.add_css_class("n-phone-status")
        row.set_margin_start(20)
        row.set_margin_end(20)
        row.set_margin_top(6)
        row.set_margin_bottom(4)
        self.clock = Gtk.Label()
        self.clock.add_css_class("n-clock")
        row.set_start_widget(self.clock)

        right = Gtk.Box(spacing=8)
        self.net_icon = Gtk.Image(icon_name="network-offline-symbolic")
        self.bat_icon = Gtk.Image(icon_name="battery-full-symbolic")
        self.bat_label = Gtk.Label()
        self.bat_label.add_css_class("n-clock")
        for w in (self.net_icon, self.bat_icon, self.bat_label):
            right.append(w)
        row.set_end_widget(right)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: shell.run_action("control"))
        row.add_controller(click)
        self.set_child(row)

        self.net = system.Network(self._update_net)
        GLib.timeout_add_seconds(1, self._tick)
        self._tick()
        GLib.timeout_add_seconds(5, self._slow_tick)
        self._slow_tick()

    def _tick(self):
        self.clock.set_label(datetime.datetime.now().strftime("%H:%M"))
        return True

    def _slow_tick(self):
        cap, status = read_battery()
        self.bat_icon.set_visible(cap is not None)
        self.bat_label.set_visible(cap is not None)
        if cap is not None:
            lvl = min(100, (cap + 5) // 10 * 10)
            charging = "-charging" if status in ("Charging", "Full") else ""
            self.bat_icon.set_from_icon_name(f"battery-level-{lvl}{charging}-symbolic")
            self.bat_label.set_label(f"{cap}%")
        self._update_net()
        return True

    def _update_net(self):
        icon, label = self.net.status()
        self.net_icon.set_from_icon_name(icon)
        self.net_icon.set_tooltip_text(label)


SWIPE_HOME = 60       # px upwards on the home bar: home screen
SWIPE_OVERVIEW = 220  # px upwards on the home bar: app overview


class PhoneNav(Gtk.ApplicationWindow):
    """Home-Leiste unten. Tippen zeigt den Startbildschirm (Fenster minimieren),
    nach oben wischen öffnet die Übersicht mit den offenen Apps."""

    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        layer.setup(self, layer="top", anchors=("bottom", "left", "right"),
                    exclusive="auto", namespace="nothing-nav", monitor=monitor)
        self.add_css_class("n-root")

        btn = Gtk.Button()
        btn.add_css_class("n-home-hit")
        btn.set_tooltip_text("Startbildschirm")
        pill = Gtk.Box()
        pill.add_css_class("n-home-pill")
        pill.set_halign(Gtk.Align.CENTER)
        pill.set_valign(Gtk.Align.CENTER)
        btn.set_child(pill)
        btn.connect("clicked", lambda *_: shell.wm.show_desktop())
        self.set_child(btn)
        self.set_size_request(-1, 40)
        # on the window, in the capture phase: the button would otherwise take the touch
        drag = Gtk.GestureDrag()
        drag.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

    def _on_drag_end(self, _gesture, _dx, dy):
        if dy <= -SWIPE_OVERVIEW:
            self.shell.run_action("overview")
        elif dy <= -SWIPE_HOME:
            self.shell.wm.show_desktop()
