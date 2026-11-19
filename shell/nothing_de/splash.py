"""Start of a session: the dot logo assembles itself, then the desktop fades in.

Scattered, blurred dots fly together into a dot-matrix "N", a dotted ring draws itself
around it, the red dot pops in and "NOTHING" appears below. Then the black screen fades
out and the island writes its greeting (island.greet). Once per session, config
"splash.enabled"; NOTHING_SPLASH=1 shows it on every start of the shell (testing).
"""
import math
import random

from gi.repository import GLib, Gtk

from . import dotmatrix, layer
from .theme import hex_to_rgb

DURATION = 3.4      # s until the fade-out is over
FADE = 0.6          # s of the fade-out at the end
GLYPH = "N"


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _back_out(t):
    """Overshoot a little and settle (the red dot popping in)."""
    t = max(0.0, min(1.0, t))
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def dots(seed=7):
    """The logo's dots: [(column, row, start x, start y, delay)] with start positions as
    fractions of the screen, scattered around."""
    rng = random.Random(seed)
    rows = dotmatrix.bitmap(GLYPH)
    out = []
    for r, line in enumerate(rows):
        for c, on in enumerate(line):
            if on:
                ang = rng.uniform(0, 2 * math.pi)
                dist = rng.uniform(0.18, 0.55)
                out.append((c, r, 0.5 + math.cos(ang) * dist, 0.5 + math.sin(ang) * dist * 0.8,
                            rng.uniform(0.0, 0.35)))
    return out


_DOTS = dots()


def frame(cr, w, h, t, accent="#D71921"):
    """One frame of the animation at `t` seconds (also used by the tests)."""
    fade = 1.0 - max(0.0, min(1.0, (t - (DURATION - FADE)) / FADE))
    cr.set_source_rgba(0, 0, 0, fade)
    cr.paint()
    if fade <= 0:
        return
    cols = len(dotmatrix.bitmap(GLYPH)[0])
    pitch = max(8.0, min(w, h) * 0.045)
    gw, gh = cols * pitch, dotmatrix.ROWS * pitch
    cx, cy = w / 2, h / 2 - pitch
    x0, y0 = cx - gw / 2, cy - gh / 2

    # the dotted ring, drawn clockwise from the top
    ring = max(gw, gh) * 0.8
    k = _ease_out((t - 0.25) / 1.1)
    n = 72
    for i in range(int(n * k)):
        a = -math.pi / 2 + 2 * math.pi * i / n
        cr.set_source_rgba(1, 1, 1, 0.55 * fade)
        cr.arc(cx + math.cos(a) * ring, cy + math.sin(a) * ring, pitch * 0.09, 0, 2 * math.pi)
        cr.fill()

    # the glyph's dots fly in, blurred and big at first
    for c, r, sx, sy, delay in _DOTS:
        p = _ease_out((t - delay) / 1.15)
        tx, ty = x0 + c * pitch + pitch / 2, y0 + r * pitch + pitch / 2
        x = sx * w + (tx - sx * w) * p
        y = sy * h + (ty - sy * h) * p
        rad = pitch * 0.4 * (1.0 + (1 - p) * 0.9)
        blur = 1 - p
        if blur > 0.05:
            cr.set_source_rgba(1, 1, 1, 0.18 * blur * fade)
            cr.arc(x, y, rad * 1.8, 0, 2 * math.pi)
            cr.fill()
        cr.set_source_rgba(1, 1, 1, (0.35 + 0.65 * p) * fade)
        cr.arc(x, y, rad, 0, 2 * math.pi)
        cr.fill()

    # the red dot, with a soft glow
    p = _back_out((t - 1.35) / 0.45) if t > 1.35 else 0.0
    if p > 0:
        r, g, b = hex_to_rgb(accent)
        dx, dy = x0 + gw + pitch * 1.35, y0 + gh - pitch * 0.5
        glow = pitch * 1.6 * p
        cr.set_source_rgba(r, g, b, 0.22 * fade)
        cr.arc(dx, dy, glow, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(r, g, b, fade)
        cr.arc(dx, dy, pitch * 0.55 * p, 0, 2 * math.pi)
        cr.fill()

    # the word below
    a = _ease_out((t - 1.7) / 0.6) * fade
    if a > 0:
        word = "NOTHING"
        wp = pitch * 0.32
        ww = dotmatrix.columns(word) * wp
        dotmatrix.draw(cr, word, cx - ww / 2, cy + ring + pitch * 1.4, wp, (1, 1, 1, 0.85 * a))


class Splash(Gtk.ApplicationWindow):
    """The animation over one screen; calls `on_done` once it has faded out."""

    def __init__(self, shell, monitor, on_done=None):
        super().__init__(application=shell.app)
        self.shell = shell
        self.on_done = on_done
        layer.setup(self, layer="overlay", anchors=("top", "bottom", "left", "right"),
                    exclusive=-1, namespace="nothing-splash", monitor=monitor)
        self.add_css_class("n-root")
        area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        area.set_draw_func(self._draw)
        self.set_child(area)
        # a click skips it
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self.finish())
        area.add_controller(click)
        self.area = area
        self.t0 = None
        self._done = False
        area.add_tick_callback(self._tick)
        # never stay on screen, even without frame clock ticks (e.g. no output)
        GLib.timeout_add(int(DURATION * 1000) + 1500, lambda: (self.finish(), False)[1])

    def _tick(self, _w, clock):
        now = clock.get_frame_time() / 1e6
        if self.t0 is None:
            self.t0 = now
        self.area.queue_draw()
        if now - self.t0 >= DURATION:
            self.finish()
            return False
        return True

    def _draw(self, _a, cr, w, h):
        t = 0.0 if self.t0 is None else GLib.get_monotonic_time() / 1e6 - self.t0
        frame(cr, w, h, t, self.shell.cfg.get("accent") or "#D71921")

    def finish(self):
        if self._done:
            return
        self._done = True
        self.destroy()
        if self.on_done:
            self.on_done()
