"""App launcher / search (Super+Space)."""
import ast
import operator

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import layer
from .apps import app_icon, launch_app

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def calc(expr):
    """Tiny safe calculator for the search field."""
    expr = expr.replace(",", ".").replace("×", "*").replace("÷", "/").replace("^", "**")
    if not any(c.isdigit() for c in expr) or not any(c in "+-*/%" for c in expr):
        return None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100:
                raise ValueError
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError
    try:
        val = ev(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if isinstance(val, float):
        val = round(val, 10)
        if val.is_integer():
            val = int(val)
    return str(val).replace(".", ",")


class Launcher(layer.Overlay):
    def __init__(self, shell):
        super().__init__(shell.app, "nothing-launcher", dim=True,
                         valign=Gtk.Align.START, margin_top=120)
        self.shell = shell
        self.panel.set_size_request(720, -1)
        self.panel.set_spacing(14)

        self.entry = Gtk.SearchEntry(placeholder_text="Apps suchen oder rechnen …")
        self.entry.add_css_class("n-search")
        self.entry.connect("search-changed", lambda *_: self.populate())
        self.entry.connect("activate", lambda *_: self.activate_first())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._entry_key)
        self.entry.add_controller(keys)
        self.panel.append(self.entry)

        self.calc = Gtk.Label(xalign=0)
        self.calc.add_css_class("n-big")
        self.calc.set_selectable(True)
        self.calc.set_margin_start(10)
        self.panel.append(self.calc)

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE,
                                max_children_per_line=6, min_children_per_line=6,
                                homogeneous=True, row_spacing=4, column_spacing=4,
                                activate_on_single_click=True, valign=Gtk.Align.START)
        self.flow.connect("child-activated", self._activated)
        scroll = Gtk.ScrolledWindow(child=self.flow, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_min_content_height(420)
        scroll.set_max_content_height(420)
        self.panel.append(scroll)
        shell.apps.listeners.append(lambda: self.get_visible() and self.populate())
        # build the tiles ahead of time so the first Super+Space is instant
        GLib.idle_add(lambda: (self.populate(), False)[1])

    def open_overlay(self):
        # leave the dock uncovered: it stays usable and accepts dropped apps
        dock = self.shell.dock
        if dock is not None and dock.get_visible():
            layer.set_margin(self, "bottom", dock.get_height() + 10)
        self.entry.set_text("")
        self.populate()
        super().open_overlay()
        self.entry.grab_focus()

    def populate(self):
        q = self.entry.get_text()
        res = calc(q)
        self.calc.set_visible(res is not None)
        if res is not None:
            self.calc.set_label(f"= {res}")
        while (c := self.flow.get_first_child()) is not None:
            self.flow.remove(c)
        for app in self.shell.apps.search(q)[:120]:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            tile.add_css_class("n-app-tile")
            img = Gtk.Image(gicon=app_icon(app), pixel_size=52)
            tile.append(img)
            lbl = Gtk.Label(label=app.get_display_name(), ellipsize=Pango.EllipsizeMode.END,
                            max_width_chars=12, justify=Gtk.Justification.CENTER)
            tile.append(lbl)
            tile.set_tooltip_text(app.get_description() or app.get_display_name())
            self._decorate_tile(tile, img, app)
            child = Gtk.FlowBoxChild(child=tile)
            child.app = app
            self.flow.append(child)
        first = self.flow.get_child_at_index(0)
        if first:
            self.flow.select_child(first)

    def _decorate_tile(self, tile, img, app):
        """Right-click menu and drag-to-dock for an app tile."""
        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY)
        drag.set_content(Gdk.ContentProvider.new_for_value(app.get_id()))
        drag.connect("drag-begin", self._drag_begin, img)
        drag.connect("drag-end", self._drag_end)
        tile.add_controller(drag)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *_: self._tile_menu(tile, app))
        tile.add_controller(right)

    def _drag_begin(self, source, _drag, img):
        source.set_icon(Gtk.WidgetPaintable.new(img), 26, 26)

    def _drag_end(self, _source, _drag, _delete):
        self.close_overlay()

    def _tile_menu(self, tile, app):
        dock = self.shell.dock
        pinned = dock is not None and dock.is_pinned(app)
        group = Gio.SimpleActionGroup()
        for name, cb in (("open", lambda: (launch_app(app), self.close_overlay())),
                         ("pin", lambda: dock and dock.toggle_pin(app))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(a)
        tile.insert_action_group("tile", group)
        menu = Gio.Menu()
        menu.append("Öffnen", "tile.open")
        menu.append("Aus dem Dock entfernen" if pinned else "Im Dock behalten", "tile.pin")
        pop = Gtk.PopoverMenu.new_from_model(menu)
        pop.add_css_class("n-menu")
        pop.set_parent(tile)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.popup()

    def _entry_key(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            sel = self.flow.get_selected_children()
            if sel:
                sel[0].grab_focus()
            return True
        return False

    def activate_first(self):
        sel = self.flow.get_selected_children()
        if sel:
            self._activated(self.flow, sel[0])

    def _activated(self, _flow, child):
        launch_app(child.app)
        self.close_overlay()
