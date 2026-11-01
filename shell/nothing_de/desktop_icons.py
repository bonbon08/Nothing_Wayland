"""Desktop-Icons: installierte Apps als startbare Symbole auf dem Hintergrund.

Einstellung „desktop.icons“. Die Fläche liegt auf dem ersten Bildschirm rechts
neben den Widgets und lässt sich scrollen, falls nicht alle Apps hineinpassen.
"""
from gi.repository import Gtk, Pango

from .apps import launch_app
from .icons import icon_widget
from .widget_sdk import SIZES

ICON_SIZE = 56
MARGIN = 24
TOP = 48           # below the bar
BOTTOM = 110       # above the dock


class DesktopIcons:
    def __init__(self, desktop):
        self.desktop = desktop
        self.cfg = desktop.cfg
        self.area = None
        self._geometry = None
        desktop.shell.apps.listeners.append(self.reload_apps)
        desktop.connect("destroy", lambda *_: desktop.shell.apps.listeners.remove(self.reload_apps))
        self.cfg.connect("changed", lambda *_: self.sync())
        self.sync()

    def _wanted_geometry(self):
        """Area right of the widgets: (x, y, width, height)."""
        d = self.desktop
        mon = d.monitor.get_geometry()
        right = max((spec.get("x", 0) + SIZES[type(w).SIZE][0] for w, spec in d.items), default=0)
        x = right + MARGIN
        return x, TOP, max(mon.width - x - MARGIN, ICON_SIZE * 3), max(mon.height - TOP - BOTTOM, ICON_SIZE * 3)

    def sync(self):
        wanted = bool(self.cfg.get("desktop.icons")) and self.desktop.primary \
            and self.desktop.monitor is not None
        if not wanted:
            if self.area is not None:
                self.desktop.fixed.remove(self.area)
                self.area = self._geometry = None
            return
        geometry = self._wanted_geometry()
        if self.area is None:
            self.area = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            self.area.set_child(self._build())
            self.desktop.fixed.put(self.area, geometry[0], geometry[1])
        elif geometry != self._geometry:
            self.desktop.fixed.move(self.area, geometry[0], geometry[1])
        self.area.set_size_request(geometry[2], geometry[3])
        self._geometry = geometry

    def reload_apps(self):
        if self.area is not None:
            self.area.set_child(self._build())

    def _build(self):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           activate_on_single_click=True, valign=Gtk.Align.START,
                           halign=Gtk.Align.END, max_children_per_line=12,
                           row_spacing=4, column_spacing=4)
        flow.connect("child-activated", lambda _f, child: launch_app(child.app))
        for app in self.desktop.shell.apps.apps:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            tile.add_css_class("n-app-tile")
            tile.set_tooltip_text(app.get_description() or app.get_display_name())
            tile.append(icon_widget(app, ICON_SIZE, self.cfg))
            tile.append(Gtk.Label(label=app.get_display_name(), ellipsize=Pango.EllipsizeMode.END,
                                  max_width_chars=10, justify=Gtk.Justification.CENTER))
            child = Gtk.FlowBoxChild(child=tile)
            child.app = app
            flow.append(child)
        return flow
