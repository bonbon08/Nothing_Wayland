"""Thin wrapper around gtk4-layer-shell with a plain-window fallback, so the
shell can also be previewed inside compositors without layer-shell."""
import gi

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LS
except (ValueError, ImportError):
    LS = None

from gi.repository import Gtk

TOP, BOTTOM, LEFT, RIGHT = "top", "bottom", "left", "right"


def supported():
    return LS is not None and LS.is_supported()


def setup(win, *, layer="top", anchors=(), margins=None, exclusive=None,
          keyboard="none", namespace="nothing", monitor=None):
    win.add_css_class("n-layer")
    if not supported():
        win.set_decorated(False)
        return False
    LS.init_for_window(win)
    LS.set_namespace(win, namespace)
    LS.set_layer(win, {
        "background": LS.Layer.BACKGROUND, "bottom": LS.Layer.BOTTOM,
        "top": LS.Layer.TOP, "overlay": LS.Layer.OVERLAY}[layer])
    edges = {TOP: LS.Edge.TOP, BOTTOM: LS.Edge.BOTTOM,
             LEFT: LS.Edge.LEFT, RIGHT: LS.Edge.RIGHT}
    for name, edge in edges.items():
        LS.set_anchor(win, edge, name in anchors)
    for name, value in (margins or {}).items():
        LS.set_margin(win, edges[name], value)
    if exclusive == "auto":
        LS.auto_exclusive_zone_enable(win)
    elif exclusive is not None:
        LS.set_exclusive_zone(win, exclusive)
    LS.set_keyboard_mode(win, {
        "none": LS.KeyboardMode.NONE, "exclusive": LS.KeyboardMode.EXCLUSIVE,
        "on_demand": LS.KeyboardMode.ON_DEMAND}[keyboard])
    if monitor is not None:
        LS.set_monitor(win, monitor)
    return True


def set_keyboard(win, keyboard):
    if supported() and LS.is_layer_window(win):
        LS.set_keyboard_mode(win, {
            "none": LS.KeyboardMode.NONE, "exclusive": LS.KeyboardMode.EXCLUSIVE,
            "on_demand": LS.KeyboardMode.ON_DEMAND}[keyboard])


def set_exclusive(win, value):
    if supported() and LS.is_layer_window(win):
        LS.set_exclusive_zone(win, value)


def set_margin(win, edge, value):
    if supported() and LS.is_layer_window(win):
        LS.set_margin(win, {TOP: LS.Edge.TOP, BOTTOM: LS.Edge.BOTTOM,
                            LEFT: LS.Edge.LEFT, RIGHT: LS.Edge.RIGHT}[edge], value)


class Overlay(Gtk.ApplicationWindow):
    """Full screen transparent overlay that hosts a floating panel and closes
    when clicking outside it or pressing Escape (launcher, control centre)."""

    def __init__(self, app, namespace, dim=False, halign=Gtk.Align.CENTER,
                 valign=Gtk.Align.CENTER, margin_top=0, margin_end=0):
        super().__init__(application=app)
        self.add_css_class("n-root")
        setup(self, layer="overlay", anchors=(TOP, BOTTOM, LEFT, RIGHT),
              exclusive=-1, keyboard="exclusive", namespace=namespace)
        if not supported():
            self.set_default_size(900, 640)
        self.scrim = Gtk.Box()
        self.scrim.add_css_class("n-scrim")
        if dim:
            self.scrim.add_css_class("dim")
        self.scrim.set_hexpand(True)
        self.scrim.set_vexpand(True)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.panel.add_css_class("n-panel")
        self.panel.set_halign(halign)
        self.panel.set_valign(valign)
        self.panel.set_margin_top(margin_top)
        self.panel.set_margin_end(margin_end)
        self.panel.set_hexpand(True)
        self.panel.set_vexpand(True)
        self.scrim.append(self.panel)
        self.set_child(self.scrim)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_scrim_click)
        self.scrim.add_controller(click)
        keys = Gtk.EventControllerKey()
        # capture phase: entries (e.g. GtkSearchEntry) would swallow Escape
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_scrim_click(self, gesture, _n, x, y):
        picked = self.scrim.pick(x, y, Gtk.PickFlags.DEFAULT)
        w = picked
        while w is not None:
            if w is self.panel:
                return
            w = w.get_parent()
        self.close_overlay()

    def _on_key(self, _ctl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            self.close_overlay()
            return True
        return False

    def toggle(self):
        if self.get_visible():
            self.close_overlay()
        else:
            self.open_overlay()

    def open_overlay(self):
        self.present()

    def close_overlay(self):
        self.set_visible(False)
