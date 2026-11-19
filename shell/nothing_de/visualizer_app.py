"""nothing-visualizer: the music as full-screen scenes.

Six scenes in a list on the left, the picked one fills the window; it follows the live
spectrum of whatever plays (audio.py). Space pauses, F or F11 switches to full screen,
↑/↓ change the scene.
"""
import math
import random
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
import cairo  # noqa: E402
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import audio  # noqa: E402
from .config import get_config  # noqa: E402
from .theme import ThemeManager, hex_to_rgb  # noqa: E402


def _band(levels, a, b):
    if not levels:
        return 0.0
    n = len(levels)
    part = levels[int(a * n):max(int(a * n) + 1, int(b * n))]
    return sum(part) / len(part)


class Scene:
    KEY = NAME = SUBTITLE = ""

    def __init__(self):
        self.rng = random.Random(3)

    def draw(self, cr, w, h, t, lv, accent):
        pass


class Horizon(Scene):
    KEY, NAME, SUBTITLE = "horizon", "Horizon", "Die Sonne geht im Takt auf."

    def draw(self, cr, w, h, t, lv, acc):
        hz = h * 0.62
        sky = cairo.LinearGradient(0, 0, 0, hz)
        sky.add_color_stop_rgb(0, 0.02, 0.02, 0.05)
        sky.add_color_stop_rgb(1, acc[0] * 0.35, acc[1] * 0.2, acc[2] * 0.3)
        cr.set_source(sky)
        cr.rectangle(0, 0, w, hz)
        cr.fill()
        bass = _band(lv, 0, 0.12)
        r = h * (0.2 + bass * 0.08)
        # the sun, cut by stripes towards the horizon
        cr.save()
        cr.rectangle(0, 0, w, hz)
        cr.clip()
        sun = cairo.LinearGradient(0, hz - r, 0, hz)
        sun.add_color_stop_rgb(0, 1, 0.85, 0.5)
        sun.add_color_stop_rgb(1, *acc[:3])
        cr.set_source(sun)
        cr.arc(w / 2, hz, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(0.02, 0.02, 0.05)
        for k in range(7):
            y = hz - r * 0.08 - k * r * 0.11
            cr.rectangle(0, y, w, 2 + (7 - k) * 0.9)
            cr.fill()
        cr.restore()
        # the spectrum as mountains on the horizon, mirrored
        half = audio.interpolate(lv or [0.0] * 8, 40)
        vals = list(reversed(half)) + half
        cr.set_source_rgb(0.01, 0.01, 0.02)
        cr.move_to(0, hz)
        for i, v in enumerate(vals):
            cr.line_to(w * i / (len(vals) - 1), hz - v * h * 0.22 - 4)
        cr.line_to(w, hz)
        cr.close_path()
        cr.fill()
        # the floor grid comes towards us
        cr.set_source_rgb(0.01, 0.01, 0.02)
        cr.rectangle(0, hz, w, h - hz)
        cr.fill()
        cr.set_source_rgba(acc[0], acc[1], acc[2], 0.55)
        cr.set_line_width(1.2)
        speed = 0.35 + _band(lv, 0, 1) * 1.2
        for k in range(14):
            z = ((k + t * speed) % 14) / 14
            y = hz + (h - hz) * z ** 2.2
            cr.move_to(0, y)
            cr.line_to(w, y)
            cr.stroke()
        for k in range(-12, 13):
            cr.move_to(w / 2 + k * w * 0.012, hz)
            cr.line_to(w / 2 + k * w * 0.16, h)
            cr.stroke()


class Nebula(Scene):
    KEY, NAME, SUBTITLE = "nebula", "Nebula", "Farbwolken, die mit der Musik atmen."

    def __init__(self):
        super().__init__()
        self.p = [[self.rng.random(), self.rng.random(), self.rng.random()] for _ in range(420)]

    def draw(self, cr, w, h, t, lv, acc):
        cr.set_source_rgb(0.01, 0.0, 0.03)
        cr.paint()
        mid = _band(lv, 0.1, 0.6)
        bass = _band(lv, 0, 0.12)
        cr.set_operator(cairo.OPERATOR_ADD)
        for p in self.p:
            x, y, hue = p
            a = math.sin(x * 6 + t * 0.2) + math.cos(y * 5 - t * 0.15)
            p[0] = (x + math.cos(a) * 0.0012 * (1 + mid * 3)) % 1
            p[1] = (y + math.sin(a) * 0.0012 * (1 + mid * 3)) % 1
            size = (10 + 30 * hue) * (1 + bass * 1.2)
            if hue < 0.5:
                col = (acc[0], acc[1], acc[2])
            else:
                col = (0.35, 0.45, 1.0)
            g = cairo.RadialGradient(p[0] * w, p[1] * h, 0, p[0] * w, p[1] * h, size)
            g.add_color_stop_rgba(0, *col, 0.12 + 0.25 * mid)
            g.add_color_stop_rgba(1, *col, 0)
            cr.set_source(g)
            cr.arc(p[0] * w, p[1] * h, size, 0, 2 * math.pi)
            cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)


class Orbit(Scene):
    KEY, NAME, SUBTITLE = "orbit", "Orbit", "Jedes Frequenzband zieht seine Bahn."

    def __init__(self):
        super().__init__()
        self.angles = [self.rng.random() * 6.28 for _ in range(12)]

    def draw(self, cr, w, h, t, lv, acc):
        cr.set_source_rgb(0.0, 0.0, 0.0)
        cr.paint()
        vals = audio.resample(lv or [0.0] * 12, 12)
        cx, cy = w / 2, h / 2
        base = min(w, h) * 0.06
        step = min(w, h) * 0.034
        for i, v in enumerate(vals):
            r = base + step * (i + 1)
            self.angles[i] += (0.004 + v * 0.05) * (1 if i % 2 else -1)
            cr.set_source_rgba(1, 1, 1, 0.08)
            cr.set_line_width(1)
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            cr.stroke()
            a = self.angles[i]
            trail = 0.2 + v * 2.2
            cr.set_line_width(2.2)
            cr.set_source_rgba(1, 1, 1, 0.35 + v * 0.5)
            cr.set_line_cap(1)
            lo, hi = (a - trail, a) if i % 2 else (a, a + trail)
            cr.arc(cx, cy, r, lo, hi)
            cr.stroke()
            cr.set_source_rgba(*acc[:3], 1)
            cr.arc(cx + math.cos(a) * r, cy + math.sin(a) * r, 3.5 + v * 6, 0, 2 * math.pi)
            cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.arc(cx, cy, base * (0.5 + _band(lv, 0, 0.1) * 0.6), 0, 2 * math.pi)
        cr.fill()


class Phosphor(Scene):
    KEY, NAME, SUBTITLE = "phosphor", "Phosphor", "Ein Oszilloskop, das grün nachleuchtet."

    def __init__(self):
        super().__init__()
        self.trails = []

    def draw(self, cr, w, h, t, lv, acc):
        cr.set_source_rgb(0.0, 0.02, 0.01)
        cr.paint()
        cr.set_source_rgba(0.2, 1, 0.5, 0.06)
        for gx in range(1, 10):
            cr.rectangle(w * gx / 10, 0, 1, h)
        for gy in range(1, 8):
            cr.rectangle(0, h * gy / 8, w, 1)
        cr.fill()
        vals = audio.resample(lv or [0.0] * 8, 8)
        pts = []
        s = min(w, h) * 0.36
        for i in range(260):
            u = i / 259 * 2 * math.pi
            x = sum(v * math.sin(u * (k + 1) + t * (0.6 + k * 0.13)) for k, v in enumerate(vals[:4]))
            y = sum(v * math.cos(u * (k + 2) - t * (0.4 + k * 0.17)) for k, v in enumerate(vals[4:]))
            x = math.sin(u * 3 + t) * 0.3 + x
            y = math.cos(u * 2 + t * 0.7) * 0.3 + y
            pts.append((w / 2 + math.tanh(x) * s, h / 2 + math.tanh(y) * s))
        self.trails.append(pts)
        self.trails = self.trails[-10:]
        cr.set_line_join(1)
        for k, tr in enumerate(self.trails):
            age = (k + 1) / len(self.trails)
            for width, alpha in ((6, 0.06), (1.6, 0.8)):
                cr.set_line_width(width)
                cr.set_source_rgba(0.3, 1, 0.55, alpha * age ** 2)
                cr.move_to(*tr[0])
                for pt in tr[1:]:
                    cr.line_to(*pt)
                cr.close_path()
                cr.stroke()


class Contour(Scene):
    KEY, NAME, SUBTITLE = "contour", "Contour", "Das Spektrum als Gebirge aus Linien."

    def __init__(self):
        super().__init__()
        self.history = []

    def draw(self, cr, w, h, t, lv, acc):
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        self.history.append(audio.interpolate(lv or [0.0] * 8, 64))
        self.history = self.history[-36:]
        rows = len(self.history)
        top, bottom = h * 0.2, h * 0.9
        x0, x1 = w * 0.2, w * 0.8
        for k, vals in enumerate(self.history):
            y = top + (bottom - top) * k / 35
            pts = []
            for i, v in enumerate(vals):
                u = i / (len(vals) - 1)
                # the middle rises highest, the edges stay calm
                env = math.sin(u * math.pi) ** 1.5
                pts.append((x0 + (x1 - x0) * u, y - v * h * 0.18 * env))
            cr.move_to(*pts[0])
            for pt in pts[1:]:
                cr.line_to(*pt)
            cr.line_to(x1, y + 4)
            cr.line_to(x0, y + 4)
            cr.close_path()
            cr.set_source_rgb(0, 0, 0)
            cr.fill_preserve()
            newest = k == rows - 1
            cr.set_source_rgba(*(acc[:3] if newest else (1, 1, 1)), 0.35 + 0.65 * k / max(1, rows - 1))
            cr.set_line_width(1.6 if newest else 1.1)
            cr.stroke()


class Ember(Scene):
    KEY, NAME, SUBTITLE = "ember", "Ember", "Goldener Staub in Zeitlupe."

    def __init__(self):
        super().__init__()
        rng = self.rng
        self.lines = [(rng.uniform(0.3, 0.7), rng.uniform(0.6, 1.6), rng.random() * 6.28,
                       rng.uniform(0.04, 0.14), rng.uniform(0.15, 0.45)) for _ in range(26)]
        self.dust = [[rng.random(), rng.random(), rng.random() * 6.28] for _ in range(160)]

    def draw(self, cr, w, h, t, lv, acc):
        cr.set_source_rgb(0.015, 0.0, 0.01)
        cr.paint()
        energy = _band(lv, 0, 1)
        cr.set_operator(cairo.OPERATOR_ADD)
        cr.set_line_width(1.5)
        for i, (base, freq, ph, amp, speed) in enumerate(self.lines):
            v = audio.resample(lv or [0.0], len(self.lines))[i] if lv else 0
            a = amp * (1 + v * 2.5)
            cr.set_source_rgba(0.95, 0.3 + a, 0.35, 0.16 + a * 1.6)
            for j in range(57):
                u = j / 56
                y = h * (base + a * math.sin(u * 6.28 * freq + t * speed + ph)
                         + 0.03 * math.sin(u * 13 + t * speed * 1.7 + ph * 2))
                if j == 0:
                    cr.move_to(0, y)
                else:
                    cr.line_to(w * u, y)
            cr.stroke()
        for p in self.dust:
            p[1] = (p[1] - 0.0008 * (1 + energy * 4)) % 1
            alpha = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(t * 1.3 + p[2]))
            cr.set_source_rgba(1, 0.78, 0.4, alpha)
            cr.arc(p[0] * w + math.sin(t * 0.3 + p[2]) * 14, p[1] * h, 1.3, 0, 2 * math.pi)
            cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)


SCENES = [Horizon, Nebula, Orbit, Phosphor, Contour, Ember]


class VisualizerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Visualizer")
        self.set_default_size(1180, 700)
        self.cfg = get_config()
        self.scenes = [cls() for cls in SCENES]
        self.index = 0
        self.paused = False
        self.levels = []
        self.t = 0.0
        self._last = None
        self.spectrum = audio.get_spectrum()
        self._sub = self.spectrum.subscribe(self._on_levels)
        self.connect("close-request", self._on_close)

        split = Adw.OverlaySplitView(sidebar_width_fraction=0.2, min_sidebar_width=210)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.add_css_class("n-vis-side")
        head = Adw.HeaderBar(show_title=False)
        head.add_css_class("flat")
        side.append(head)
        title = Gtk.Label(label="SZENEN", xalign=0)
        title.add_css_class("n-caps")
        title.set_margin_start(16)
        title.set_margin_bottom(8)
        side.append(title)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        for i, sc in enumerate(self.scenes):
            row = Gtk.Box(spacing=12)
            row.set_margin_top(6)
            row.set_margin_bottom(6)
            dot = Gtk.DrawingArea(content_width=26, content_height=26)
            dot.set_draw_func(self._draw_icon, i)
            row.append(dot)
            name = Gtk.Label(label=sc.NAME, xalign=0, hexpand=True)
            row.append(name)
            num = Gtk.Label(label=f"{i + 1:02d}")
            num.add_css_class("n-caps")
            row.append(num)
            self.list.append(row)
        self.list.connect("row-selected", self._on_row)
        side.append(self.list)
        split.set_sidebar(side)

        main = Gtk.Overlay()
        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self._draw)
        main.set_child(self.area)
        hud = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      halign=Gtk.Align.START, valign=Gtk.Align.START)
        hud.set_margin_start(40)
        hud.set_margin_top(56)
        hud.set_can_target(False)
        brand = Gtk.Label(label="NOTHING VISUALIZER", xalign=0)
        brand.add_css_class("n-caps")
        self.name = Gtk.Label(xalign=0)
        self.name.add_css_class("n-vis-title")
        self.sub = Gtk.Label(xalign=0)
        self.sub.add_css_class("n-vis-sub")
        for wdg in (brand, self.name, self.sub):
            hud.append(wdg)
        main.add_overlay(hud)
        top = Adw.HeaderBar(show_title=False)
        top.add_css_class("flat")
        top.add_css_class("n-vis-head")
        top.set_valign(Gtk.Align.START)
        self.pause_btn = Gtk.Button(icon_name="media-playback-pause-symbolic", tooltip_text="Pause (Leertaste)")
        self.pause_btn.connect("clicked", lambda *_: self.toggle_pause())
        full = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Vollbild (F)")
        full.connect("clicked", lambda *_: self.toggle_fullscreen())
        top.pack_end(full)
        top.pack_end(self.pause_btn)
        main.add_overlay(top)
        self.status = Gtk.Label(xalign=0, halign=Gtk.Align.START, valign=Gtk.Align.END)
        self.status.add_css_class("n-caps")
        self.status.set_margin_start(40)
        self.status.set_margin_bottom(28)
        main.add_overlay(self.status)
        split.set_content(main)
        self.split = split
        self.set_content(split)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.area.add_tick_callback(self._tick)
        self.list.select_row(self.list.get_row_at_index(0))
        GLib.timeout_add_seconds(1, self._update_status)
        self._update_status()

    def _on_close(self, *_):
        self.spectrum.unsubscribe(self._sub)
        return False

    def _update_status(self):
        if self.spectrum.backend:
            self.status.set_label(f"● LIVE · {self.spectrum.backend.upper()}")
        else:
            self.status.set_label("KEIN AUDIO-ABGRIFF · gst-plugins-good oder cava installieren")
        return True

    @property
    def accent(self):
        r, g, b = hex_to_rgb(self.cfg.get("accent"))
        return (r, g, b, 1.0)

    def _on_levels(self, levels):
        self.levels = levels

    def _on_row(self, _l, row):
        if row is None:
            return
        self.index = row.get_index()
        sc = self.scenes[self.index]
        self.name.set_label(sc.NAME)
        self.sub.set_label(sc.SUBTITLE)

    def _tick(self, _w, clock):
        now = clock.get_frame_time() / 1e6
        if self._last is not None and not self.paused:
            self.t += min(0.1, now - self._last)
        self._last = now
        if not self.paused:
            self.area.queue_draw()
        return True

    def _draw(self, _a, cr, w, h):
        self.scenes[self.index].draw(cr, w, h, self.t, self.levels, self.accent)

    def _draw_icon(self, area, cr, w, h, i):
        fg = area.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.85)
        cr.set_line_width(1.4)
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 2
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        acc = self.accent
        cr.set_source_rgba(*acc)
        # a little emblem per scene
        if i == 0:
            cr.arc(cx, cy + 3, r * 0.5, math.pi, 2 * math.pi)
            cr.fill()
        elif i == 1:
            for dx, dy in ((-3, -2), (3, 1), (0, 4)):
                cr.arc(cx + dx, cy + dy, 2.4, 0, 2 * math.pi)
                cr.fill()
        elif i == 2:
            cr.arc(cx + r * 0.55, cy - r * 0.2, 2.6, 0, 2 * math.pi)
            cr.fill()
        elif i == 3:
            cr.move_to(cx - r * 0.6, cy)
            for k in range(1, 13):
                cr.line_to(cx - r * 0.6 + k * r * 0.1, cy + math.sin(k) * r * 0.4)
            cr.stroke()
        elif i == 4:
            for k in range(3):
                cr.move_to(cx - r * 0.6, cy - 4 + k * 4)
                cr.line_to(cx + r * 0.6, cy - 4 + k * 4)
                cr.stroke()
        else:
            cr.move_to(cx - r * 0.7, cy + 3)
            cr.curve_to(cx - 2, cy - 8, cx + 2, cy + 8, cx + r * 0.7, cy - 3)
            cr.stroke()

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.set_icon_name("media-playback-start-symbolic" if self.paused
                                     else "media-playback-pause-symbolic")

    def toggle_fullscreen(self):
        if self.is_fullscreen():
            self.unfullscreen()
            self.split.set_show_sidebar(True)
        else:
            self.fullscreen()
            self.split.set_show_sidebar(False)

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_space:
            self.toggle_pause()
        elif keyval in (Gdk.KEY_f, Gdk.KEY_F11) or keyval == Gdk.KEY_Escape and self.is_fullscreen():
            self.toggle_fullscreen()
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            i = (self.index + (1 if keyval == Gdk.KEY_Down else -1)) % len(self.scenes)
            self.list.select_row(self.list.get_row_at_index(i))
        else:
            return False
        return True


class VisualizerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="eu.nothing_de.Visualizer")

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            ThemeManager(get_config(), sync_gsettings=False)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            win = VisualizerWindow(self)
        win.present()


def main():
    return VisualizerApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
