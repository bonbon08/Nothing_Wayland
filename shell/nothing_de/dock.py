"""The dock: pinned apps + running windows, grouped by application."""
import math

from gi.repository import Gdk, Gio, GLib, Gtk

from . import layer
from .apps import app_icon, launch_app
from .theme import hex_to_rgb


class DockItem(Gtk.Box):
    def __init__(self, dock, key, app, size):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.dock = dock
        self.key = key
        self.app = app
        self.windows = []
        self._cycle = 0
        self.btn = Gtk.Button()
        self.btn.add_css_class("n-dock-item")
        self.img = Gtk.Image(gicon=app_icon(app), pixel_size=size)
        self.btn.set_child(self.img)
        name = app.get_display_name() if app else key
        self.btn.set_tooltip_text(name)
        self.btn.connect("clicked", self._clicked)
        self.dot = Gtk.Box()
        self.dot.add_css_class("n-run-dot")
        self.dot.set_halign(Gtk.Align.CENTER)
        self.append(self.btn)
        self.append(self.dot)

        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *_: self._menu())
        self.btn.add_controller(right)
        middle = Gtk.GestureClick(button=Gdk.BUTTON_MIDDLE)
        middle.connect("pressed", lambda *_: launch_app(self.app))
        self.btn.add_controller(middle)

    def set_windows(self, windows, focused):
        self.windows = windows
        self.dot.remove_css_class("running")
        self.dot.remove_css_class("focused")
        if any(w["id"] == focused for w in windows):
            self.dot.add_css_class("focused")
        elif windows:
            self.dot.add_css_class("running")

    def _clicked(self, _b):
        wm = self.dock.shell.wm
        if not self.windows:
            if launch_app(self.app):
                self.dot.add_css_class("running")
            return
        focused = wm.state.get("focused")
        if len(self.windows) == 1:
            wm.toggle(self.windows[0]["id"])
            return
        ids = [w["id"] for w in self.windows]
        if focused in ids:
            self._cycle = (ids.index(focused) + 1) % len(ids)
        else:
            self._cycle = 0
        wm.focus(ids[self._cycle])

    def _menu(self):
        wm = self.dock.shell.wm
        group = Gio.SimpleActionGroup()
        menu = Gio.Menu()

        def act(name, cb, param=None):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
            a.connect("activate", cb)
            group.add_action(a)

        if self.windows:
            sec = Gio.Menu()
            for w in self.windows:
                title = (w.get("title") or "Fenster")[:48]
                if w.get("ws", 1) != wm.state.get("workspace"):
                    title += f"  ·  {w.get('ws')}"
                sec.append(title, f"dock.focus({w['id']})")
            menu.append_section(None, sec)
            act("focus", lambda _a, p: wm.focus(p.get_int32()), "i")
        sec = Gio.Menu()
        if self.app:
            sec.append("Neues Fenster", "dock.new")
            act("new", lambda *_: launch_app(self.app))
            pinned = self.dock.is_pinned(self.app)
            sec.append("Aus dem Dock entfernen" if pinned else "Im Dock behalten", "dock.pin")
            act("pin", lambda *_: self.dock.toggle_pin(self.app))
        menu.append_section(None, sec)
        if self.windows:
            sec = Gio.Menu()
            sec.append("Alle Fenster schließen" if len(self.windows) > 1 else "Beenden", "dock.quit")
            act("quit", lambda *_: [wm.close(w["id"]) for w in self.windows])
            menu.append_section(None, sec)
        self.insert_action_group("dock", group)
        pop = Gtk.PopoverMenu.new_from_model(menu)
        pop.add_css_class("n-menu")
        pop.set_parent(self.btn)
        pop.set_position(Gtk.PositionType.TOP)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()


class Dock(Gtk.ApplicationWindow):
    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        self.cfg = shell.cfg
        layer.setup(self, layer="top", anchors=("bottom",), margins={"bottom": 10},
                    exclusive="auto", namespace="nothing-dock", monitor=monitor)
        self.add_css_class("n-root")
        self.box = Gtk.Box(spacing=4)
        self.box.add_css_class("n-dock")
        self.set_child(self.box)
        self.items = {}
        self._layout_key = None
        shell.wm.connect("state", lambda *_: self.refresh())
        self.cfg.connect("changed", lambda *_: self.refresh())
        shell.apps.listeners.append(self.refresh)
        self.refresh()

    def is_pinned(self, app):
        return app.get_id() in (self.cfg.get("dock.pinned") or [])

    def toggle_pin(self, app):
        pinned = list(self.cfg.get("dock.pinned") or [])
        if app.get_id() in pinned:
            pinned.remove(app.get_id())
        else:
            pinned.append(app.get_id())
        self.cfg.set("dock.pinned", pinned)

    def _launcher_button(self, size):
        btn = Gtk.Button()
        btn.add_css_class("n-dock-item")
        btn.set_tooltip_text("Apps")
        art = Gtk.DrawingArea(content_width=size, content_height=size)

        def draw(area, cr, w, h):
            fg = area.get_color()
            acc = hex_to_rgb(self.cfg.get("accent"))
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
            r = w * 0.26
            cr.new_sub_path()
            cr.arc(w - r, r, r, -math.pi / 2, 0)
            cr.arc(w - r, h - r, r, 0, math.pi / 2)
            cr.arc(r, h - r, r, math.pi / 2, math.pi)
            cr.arc(r, r, r, math.pi, 1.5 * math.pi)
            cr.close_path()
            cr.fill()
            p = w / 5
            for i in range(3):
                for j in range(3):
                    if i == 1 and j == 1:
                        cr.set_source_rgba(acc[0], acc[1], acc[2], 1)
                    else:
                        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
                    cr.arc(p * (1.5 + i), p * (1.5 + j), p * 0.28, 0, 2 * math.pi)
                    cr.fill()
        art.set_draw_func(draw)
        btn.set_child(art)
        btn.connect("clicked", lambda *_: self.shell.run_action("launcher"))
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        wrap.append(btn)
        spacer = Gtk.Box()
        spacer.add_css_class("n-run-dot")
        wrap.append(spacer)
        return wrap

    def refresh(self):
        st = self.shell.wm.state
        size = int(self.cfg.get("dock.icon_size") or 48)
        pinned_ids = self.cfg.get("dock.pinned") or []
        groups = {}    # key -> (app, [windows])
        order = []
        for did in pinned_ids:
            app = self.shell.apps.get(did)
            if app is None:
                continue
            key = app.get_id()
            groups[key] = (app, [])
            order.append(key)
        running_order = []
        for w in st.get("windows", []):
            app = self.shell.apps.lookup(w.get("app_id"))
            key = app.get_id() if app else "win:" + (w.get("app_id") or str(w["id"]))
            if key not in groups:
                groups[key] = (app, [])
                running_order.append(key)
            groups[key][1].append(w)

        layout_key = (size, tuple(order), tuple(running_order),
                      self.cfg.get("accent"))
        if layout_key != self._layout_key:
            self._layout_key = layout_key
            while (c := self.box.get_first_child()) is not None:
                self.box.remove(c)
            self.items = {}
            self.box.append(self._launcher_button(size))
            sep = Gtk.Box()
            sep.add_css_class("n-dock-sep")
            self.box.append(sep)
            for key in order:
                self._add(key, groups[key][0], size)
            if running_order:
                sep2 = Gtk.Box()
                sep2.add_css_class("n-dock-sep")
                self.box.append(sep2)
            for key in running_order:
                self._add(key, groups[key][0], size)
        focused = st.get("focused")
        for key, item in self.items.items():
            item.set_windows(groups.get(key, (None, []))[1], focused)

    def _add(self, key, app, size):
        item = DockItem(self, key, app, size)
        self.items[key] = item
        self.box.append(item)
