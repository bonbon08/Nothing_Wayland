"""Wallpaper switcher: the wallpapers as cards in a 3D row, the chosen one in front.

Super + Shift + W (or "Hintergrund wechseln" in the desktop menu). Arrow keys, the mouse
wheel or a click on a side card turn the row, Enter or a click on the front card takes it,
Tab switches between "Bilder", "Fotos" and "Live", Escape closes.
"""
import math
import os

import gi

gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

from . import layer, livewall, thumbs  # noqa: E402
from .config import WALLPAPER_DIR  # noqa: E402

PICTURE_EXT = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".jxl")
VISIBLE = 4.6        # cards further away than this from the front are not drawn
MAX_PER_TAB = 120


def _pictures_in(dirs):
    paths = []
    for d in dirs:
        if d and os.path.isdir(d):
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(PICTURE_EXT) and not n.startswith("."):
                    paths.append(os.path.join(d, n))
    return list(dict.fromkeys(paths))


def wallpaper_paths():
    """The wallpapers that come with Nothing and the system, and the user's own folder."""
    return _pictures_in([WALLPAPER_DIR, "/usr/share/backgrounds", "/usr/share/backgrounds/gnome",
                         os.path.join(GLib.get_user_data_dir(), "backgrounds")])


def photo_paths():
    """Pictures from the user's picture folder (not the screenshots)."""
    pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    dirs = [pics, os.path.expanduser("~/Bilder"), os.path.expanduser("~/Pictures")]
    if pics:
        dirs.append(os.path.join(pics, "Wallpapers"))
        dirs.append(os.path.join(pics, "Hintergründe"))
    return _pictures_in(list(dict.fromkeys(d for d in dirs if d)))


def display_name(path):
    if livewall.is_live(path):
        scene = livewall.SCENES.get(path[len(livewall.LIVE_PREFIX):])
        return scene.NAME if scene else path
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("-", " ").replace("_", " ")


def card_layout(d, card_w, gap=26):
    """Where the card `d` places away from the front one sits (d may be fractional while
    the row turns): (x offset of its centre, rotation about the vertical axis in degrees,
    scale, opacity). The front card faces the viewer; the others turn inwards and pile up."""
    a = abs(d)
    sgn = 1 if d > 0 else -1 if d < 0 else 0
    first = card_w * 0.5 + card_w * 0.22 + gap         # centre of the direct neighbour
    step = card_w * 0.17                                # then each further card
    x = a * first if a <= 1 else first + (a - 1) * step
    angle = -sgn * min(a, 1.0) * 58.0
    scale = 1.0 - min(a, 1.0) * 0.14
    opacity = max(0.0, min(1.0, VISIBLE - a))
    return sgn * x, angle, scale, opacity


class WallpaperSwitcher(layer.Overlay):
    def __init__(self, shell):
        super().__init__(shell.app, "nothing-wallpapers", dim=True)
        self.shell = shell
        self.cfg = shell.cfg
        self.panel.add_css_class("n-wall-panel")
        self.scrim.add_css_class("n-wall-scrim")
        self.panel.set_halign(Gtk.Align.FILL)
        self.tab = "pictures"
        self.items = []
        self.cards = []
        self.pos = 0.0
        self.target = 0
        self._tick_id = None
        self._order_for = None

        head = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        title = Gtk.Label(label="● HINTERGRUND")
        title.add_css_class("n-caps")
        head.append(title)
        self.tab_btns = {}
        for key, label in (("pictures", "Bilder"), ("photos", "Fotos"), ("live", "Live")):
            b = Gtk.Button(label=label)
            b.add_css_class("n-wall-tab")
            b.connect("clicked", lambda _b, k=key: self.show_tab(k))
            head.append(b)
            self.tab_btns[key] = b
        self.counter = Gtk.Label()
        self.counter.add_css_class("n-caps")
        head.append(self.counter)
        self.panel.append(head)

        self.stage = Gtk.Fixed(hexpand=True, overflow=Gtk.Overflow.HIDDEN)
        self.stage.set_margin_top(18)
        self.panel.append(self.stage)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES |
                                               Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect("scroll", self._on_scroll)
        self.stage.add_controller(scroll)

        self.name = Gtk.Label()
        self.name.add_css_class("n-wall-name")
        self.name.set_margin_top(14)
        self.panel.append(self.name)
        hint = Gtk.Label(label="← →  wählen   ·   Enter  übernehmen   ·   Tab  Kategorie   ·   Esc")
        hint.add_css_class("n-caps")
        hint.set_margin_top(6)
        self.panel.append(hint)

        keys = Gtk.EventControllerKey()
        # before GTK's own focus keys (Tab, arrows)
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_keys)
        self.add_controller(keys)

    # ------------------------------------------------------------ content
    @property
    def key(self):
        return "phone.wallpaper" if self.shell.phone else "wallpaper"

    def _items_for(self, tab):
        if tab == "live":
            return [livewall.LIVE_PREFIX + k for k in livewall.SCENES]
        if tab == "photos":
            return photo_paths()[:MAX_PER_TAB]
        return wallpaper_paths()[:MAX_PER_TAB]

    def open_overlay(self):
        current = self.cfg.get(self.key) or ""
        tab = "live" if livewall.is_live(current) else \
            "photos" if current in photo_paths() else "pictures"
        self._size_stage()
        self.show_tab(tab, select=current)
        super().open_overlay()

    def _size_stage(self):
        monitors = Gdk.Display.get_default().get_monitors()
        geo = monitors.get_item(0).get_geometry() if monitors.get_n_items() else None
        w = geo.width if geo else 1280
        self.stage_w = int(w * 0.96)
        self.card_w = int(min(w * 0.4, 760))
        self.card_h = int(self.card_w * 9 / 16)
        self.stage_h = int(self.card_h * 1.12)
        self.stage.set_size_request(self.stage_w, self.stage_h)

    def show_tab(self, tab, select=None):
        self.tab = tab
        for k, b in self.tab_btns.items():
            if k == tab:
                b.add_css_class("on")
            else:
                b.remove_css_class("on")
        for c in self.cards:
            self.stage.remove(c)
        self.cards = []
        self.items = self._items_for(tab)
        for i, path in enumerate(self.items):
            self.cards.append(self._card(i, path))
        idx = self.items.index(select) if select in self.items else 0
        self.target = idx
        self.pos = float(idx)
        self._order_for = None
        self._layout()
        self._label()

    def _card(self, i, path):
        frame = Gtk.Overlay()
        frame.add_css_class("n-wall-card")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_size_request(self.card_w, self.card_h)
        frame.n_loaded = False
        frame.n_path = path
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        pic.set_size_request(self.card_w, self.card_h)
        frame.set_child(pic)
        frame.n_pic = pic
        tag = Gtk.Label(label=display_name(path).upper(), halign=Gtk.Align.START,
                        valign=Gtk.Align.END, margin_start=14, margin_bottom=12)
        tag.add_css_class("n-wall-tag")
        frame.add_overlay(tag)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a, i=i: self._clicked(i))
        frame.add_controller(click)
        self.stage.put(frame, 0, 0)
        return frame

    def _load(self, frame):
        frame.n_loaded = True
        path = frame.n_path
        if livewall.is_live(path):
            key = path[len(livewall.LIVE_PREFIX):]
            frame.n_pic.set_paintable(livewall.thumbnail(key, self.card_w, self.card_h))
        else:
            thumbs.load_async(path, self.card_w, self.card_h, frame.n_pic.set_paintable)

    # ------------------------------------------------------------- layout
    def _layout(self):
        cx, cy = self.stage_w / 2, self.stage_h / 2
        for i, frame in enumerate(self.cards):
            d = i - self.pos
            x, angle, scale, opacity = card_layout(d, self.card_w)
            if opacity <= 0:
                frame.set_visible(False)
                continue
            frame.set_visible(True)
            if not frame.n_loaded:
                self._load(frame)
            frame.set_opacity(opacity)
            # a turned card, faked in 2D (every GSK renderer, also cairo, draws it): narrower
            # by the cosine of the angle and sheared so its far edge looks smaller
            rad = math.radians(angle)
            t = Gsk.Transform().translate(Graphene.Point().init(cx + x, cy))
            t = t.scale(scale * max(0.2, math.cos(rad)), scale)
            t = t.skew(0, -math.degrees(math.atan(math.sin(rad) * 0.16)))
            t = t.translate(Graphene.Point().init(-self.card_w / 2, -self.card_h / 2))
            self.stage.set_child_transform(frame, t)
            if round(d) == 0:
                frame.add_css_class("front")
            else:
                frame.remove_css_class("front")
        # the front card on top: far cards first in the widget order
        front = round(self.pos)
        if front != self._order_for:
            self._order_for = front
            order = sorted(enumerate(self.cards), key=lambda e: -abs(e[0] - front))
            for _i, frame in order:
                frame.insert_before(self.stage, None)

    def _label(self):
        n = len(self.items)
        if not n:
            self.counter.set_label("00 / 00")
            self.name.set_label("Keine Bilder gefunden" if self.tab != "photos"
                                else "Keine Bilder im Bilder-Ordner")
            return
        self.counter.set_label(f"{self.target + 1:02d} / {n:02d}")
        current = self.cfg.get(self.key) or ""
        mark = "  ·  AKTUELL" if self.items[self.target] == current else ""
        self.name.set_label(display_name(self.items[self.target]) + mark)

    def _go(self, index):
        if not self.items:
            return
        self.target = max(0, min(len(self.items) - 1, index))
        self._label()
        if self._tick_id is None:
            self._tick_id = self.stage.add_tick_callback(self._tick)

    def _tick(self, _w, _clock):
        diff = self.target - self.pos
        if abs(diff) < 0.004:
            self.pos = float(self.target)
            self._layout()
            self._tick_id = None
            return False
        self.pos += diff * 0.2
        self._layout()
        return True

    # -------------------------------------------------------------- input
    def _clicked(self, i):
        if i == self.target:
            self.apply()
        else:
            self._go(i)

    def _on_scroll(self, _c, dx, dy):
        step = dy if abs(dy) >= abs(dx) else dx
        if step:
            self._go(self.target + (1 if step > 0 else -1))
        return True

    def _on_keys(self, _c, keyval, _code, state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_a, Gdk.KEY_h):
            self._go(self.target - 1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_d, Gdk.KEY_l):
            self._go(self.target + 1)
        elif keyval == Gdk.KEY_Home:
            self._go(0)
        elif keyval == Gdk.KEY_End:
            self._go(len(self.items) - 1)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.apply()
        elif keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            tabs = list(self.tab_btns)
            back = keyval == Gdk.KEY_ISO_Left_Tab or state & Gdk.ModifierType.SHIFT_MASK
            self.show_tab(tabs[(tabs.index(self.tab) + (-1 if back else 1)) % len(tabs)])
        else:
            return False
        return True

    def apply(self):
        if not self.items:
            return
        self.cfg.set(self.key, self.items[self.target])
        self.close_overlay()

    def close_overlay(self):
        super().close_overlay()
        # free the thumbnails and scenes until next time
        for c in self.cards:
            self.stage.remove(c)
        self.cards = []
