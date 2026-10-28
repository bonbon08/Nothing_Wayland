"""Desktop background: wallpaper plus freely placeable widgets."""
import copy
import json
import os

from gi.repository import Gdk, Gio, GLib, Gtk

from . import layer
from .apps import spawn
from .widgets import SIZES, WIDGET_TYPES

GRID = 8


class DesktopWindow(Gtk.ApplicationWindow):
    def __init__(self, shell, monitor, primary):
        super().__init__(application=shell.app)
        self.shell = shell
        self.cfg = shell.cfg
        self.primary = primary
        self.editing = False
        self.items = []        # (widget, spec)
        self._rendered = None
        self._wallpaper = None
        layer.setup(self, layer="background", anchors=("top", "bottom", "left", "right"),
                    exclusive=-1, keyboard="on_demand", namespace="nothing-desktop",
                    monitor=monitor)
        if not layer.supported():
            self.set_default_size(1280, 800)
        self.add_css_class("n-root")

        self.bg = Gtk.Box()
        self.bg_provider = Gtk.CssProvider()
        self.bg.get_style_context().add_provider(self.bg_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.bg.add_css_class("n-desktop-bg")
        self.picture = Gtk.Picture(hexpand=True, vexpand=True, can_shrink=True)
        self.bg.append(self.picture)
        overlay = Gtk.Overlay(child=self.bg)
        self.fixed = Gtk.Fixed()
        overlay.add_overlay(self.fixed)

        self.done_btn = Gtk.Button(label="Fertig")
        self.done_btn.add_css_class("n-tile")
        self.done_btn.add_css_class("on")
        self.done_btn.set_halign(Gtk.Align.CENTER)
        self.done_btn.set_valign(Gtk.Align.END)
        self.done_btn.set_margin_bottom(110)
        self.done_btn.set_visible(False)
        self.done_btn.connect("clicked", lambda *_: self.set_editing(False))
        overlay.add_overlay(self.done_btn)
        self.set_child(overlay)

        self._build_menu()
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._on_right_click)
        self.fixed.add_controller(click)

        self.cfg.connect("changed", lambda *_: self.reload())
        self.reload()

    # ---------------------------------------------------------------- menu
    def _build_menu(self):
        group = Gio.SimpleActionGroup()

        def add(name, cb, param=None):
            a = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
            a.connect("activate", cb)
            group.add_action(a)

        add("wallpaper", lambda *_: spawn(["nothing-settings", "--page", "appearance"]))
        add("widgets", lambda *_: self.set_editing(True))
        add("add", lambda _a, p: self.add_widget(p.get_string()), "s")
        add("settings", lambda *_: spawn(["nothing-settings"]))
        add("terminal", lambda *_: self.shell.run_action("terminal"))
        self.insert_action_group("desk", group)

        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append("Hintergrund ändern …", "desk.wallpaper")
        sec.append("Widgets bearbeiten", "desk.widgets")
        sub = Gio.Menu()
        for t, cls in WIDGET_TYPES.items():
            sub.append(cls.NAME, f"desk.add::{t}")
        sec.append_submenu("Widget hinzufügen", sub)
        menu.append_section(None, sec)
        sec2 = Gio.Menu()
        sec2.append("Terminal öffnen", "desk.terminal")
        sec2.append("Einstellungen", "desk.settings")
        menu.append_section(None, sec2)
        self.menu = Gtk.PopoverMenu.new_from_model(menu)
        self.menu.add_css_class("n-menu")
        self.menu.set_has_arrow(False)
        self.menu.set_parent(self.fixed)

    def _on_right_click(self, _g, _n, x, y):
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self.menu.set_pointing_to(rect)
        self.menu.popup()

    # ---------------------------------------------------------- wallpaper
    def _apply_wallpaper(self):
        path = self.cfg.get("wallpaper") or ""
        fit = self.cfg.get("wallpaper_fit") or "cover"
        color = self.cfg.get("background_color") or "#000000"
        key = (path, fit, color)
        if key == self._wallpaper:
            return
        self._wallpaper = key
        self.bg_provider.load_from_string(f".n-desktop-bg {{ background: {color}; }}")
        self.picture.set_content_fit({
            "cover": Gtk.ContentFit.COVER, "contain": Gtk.ContentFit.CONTAIN,
            "fill": Gtk.ContentFit.FILL}.get(fit, Gtk.ContentFit.COVER))
        if path and os.path.exists(path):
            self.picture.set_filename(path)
        else:
            self.picture.set_paintable(None)

    # ------------------------------------------------------------ widgets
    def reload(self):
        self._apply_wallpaper()
        if not self.primary:
            return
        specs = self.cfg.get("widgets") or []
        key = json.dumps(specs, sort_keys=True)
        if key == self._rendered:
            return
        self._rendered = key
        for w, _spec in self.items:
            w.teardown()
            self.fixed.remove(w.get_parent())
        self.items = []
        for spec in specs:
            cls = WIDGET_TYPES.get(spec.get("type"))
            if cls:
                self._add_item(cls, copy.deepcopy(spec))

    def _add_item(self, cls, spec):
        w = cls(self.shell, spec)
        holder = Gtk.Overlay(child=w)
        rm = Gtk.Button(icon_name="window-close-symbolic")
        rm.add_css_class("n-remove")
        rm.set_halign(Gtk.Align.START)
        rm.set_valign(Gtk.Align.START)
        rm.set_visible(self.editing)
        rm.connect("clicked", lambda *_: self.remove_widget(w))
        holder.add_overlay(rm)
        holder._remove_btn = rm
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin, holder)
        drag.connect("drag-update", self._drag_update, holder)
        drag.connect("drag-end", self._drag_end, holder, w)
        holder.add_controller(drag)
        self.fixed.put(holder, spec.get("x", 40), spec.get("y", 60))
        if self.editing:
            w.add_css_class("editing")
        self.items.append((w, spec))

    def _drag_begin(self, gesture, _x, _y, holder):
        if not self.editing:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        holder._start = self.fixed.get_child_position(holder)

    def _drag_update(self, _g, dx, dy, holder):
        if not self.editing or not hasattr(holder, "_start"):
            return
        x = max(0, round((holder._start[0] + dx) / GRID) * GRID)
        y = max(0, round((holder._start[1] + dy) / GRID) * GRID)
        self.fixed.move(holder, x, y)

    def _drag_end(self, _g, _dx, _dy, holder, w):
        if not self.editing:
            return
        x, y = self.fixed.get_child_position(holder)
        w.spec["x"], w.spec["y"] = int(x), int(y)
        self._store()

    def _store(self):
        specs = [spec for _w, spec in self.items]
        self._rendered = json.dumps(specs, sort_keys=True)
        self.cfg.set("widgets", copy.deepcopy(specs))

    def set_editing(self, on):
        self.editing = on
        self.done_btn.set_visible(on)
        for w, _spec in self.items:
            w.get_parent()._remove_btn.set_visible(on)
            if on:
                w.add_css_class("editing")
            else:
                w.remove_css_class("editing")

    def _free_spot(self, cls):
        w, h = SIZES[cls.SIZE]
        width = max(self.get_width(), 800)
        height = max(self.get_height(), 600)
        taken = []
        for item, spec in self.items:
            iw, ih = SIZES[type(item).SIZE]
            taken.append((spec.get("x", 0), spec.get("y", 0), iw, ih))
        for x in range(48, width - w, 24):
            for y in range(72, height - h - 100, 24):
                if all(x + w + 16 <= tx or tx + tw + 16 <= x or y + h + 16 <= ty or ty + th + 16 <= y
                       for tx, ty, tw, th in taken):
                    return x, y
        return 48, 72

    def add_widget(self, wtype):
        cls = WIDGET_TYPES.get(wtype)
        if not cls:
            return
        x, y = self._free_spot(cls)
        self._add_item(cls, {"type": wtype, "x": x, "y": y})
        self._store()

    def remove_widget(self, widget):
        for i, (w, _spec) in enumerate(self.items):
            if w is widget:
                w.teardown()
                self.fixed.remove(w.get_parent())
                del self.items[i]
                break
        self._store()
