"""Live wallpapers: animated scenes drawn with cairo, and video files as wallpaper.

A wallpaper value "live:<key>" in the config picks a scene from SCENES; a path to a video
(mp4, webm, mkv, mov) plays muted in a loop. Every scene draws its still parts once into
a cached surface and only the moving parts per frame, at "wallpaper_fps" frames a second.
"""
import math
import os
import random

import cairo
from gi.repository import Gdk, GLib, Gtk

LIVE_PREFIX = "live:"
VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ogv")


def is_live(path):
    return bool(path) and path.startswith(LIVE_PREFIX)


def is_video(path):
    return bool(path) and path.lower().endswith(VIDEO_EXT)


def _grad(stops, x0, y0, x1, y1):
    g = cairo.LinearGradient(x0, y0, x1, y1)
    for off, (r, gg, b, *a) in stops:
        g.add_color_stop_rgba(off, r, gg, b, a[0] if a else 1.0)
    return g


def _hex(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


class Scene:
    KEY = NAME = DESCRIPTION = ""
    ACCENT = "#D71921"     # the matching accent colour ("Farbe aus dem Hintergrund")

    def __init__(self):
        self._bg = None
        self._size = None
        self.rng = random.Random(7)

    def draw(self, cr, w, h, t):
        if self._size != (w, h):
            self._size = (w, h)
            self._bg = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, w), max(1, h))
            bcr = cairo.Context(self._bg)
            self.rng = random.Random(7)
            self.setup(w, h)
            self.paint_static(bcr, w, h)
        cr.set_source_surface(self._bg, 0, 0)
        cr.paint()
        self.paint_dynamic(cr, w, h, t)

    def setup(self, w, h):
        pass

    def paint_static(self, cr, w, h):
        pass

    def paint_dynamic(self, cr, w, h, t):
        pass


# ------------------------------------------------------------------ snow forest
class SnowForest(Scene):
    KEY, NAME, DESCRIPTION, ACCENT = ("snow-forest", "Schneewald",
                                      "Nebel zwischen Tannen, es schneit", "#7FA6B8")

    def setup(self, w, h):
        rng = self.rng
        # three depths of flakes: far ones small and slow
        self.flakes = []
        for _ in range(int(220 * max(1, w * h / (1920 * 1080)) ** 0.5)):
            depth = rng.choice((0.35, 0.6, 1.0))
            self.flakes.append((rng.random() * w, rng.random() * h, depth, rng.random() * 6.28))

    def _tree(self, cr, x, base, height, width):
        tiers = 6
        for k in range(tiers):
            top = base - height * (k + 1) / tiers - height * 0.12
            half = width * (1 - k / tiers) * 0.5
            y = base - height * k / tiers
            cr.move_to(x - half, y)
            cr.line_to(x, top)
            cr.line_to(x + half, y)
            cr.close_path()
        cr.rectangle(x - width * 0.04, base - height * 0.05, width * 0.08, height * 0.08)
        cr.fill()

    def paint_static(self, cr, w, h):
        cr.set_source(_grad([(0, _hex("#C9D1D6")), (0.55, _hex("#9AA6AD")), (1, _hex("#6E7A80"))],
                            0, 0, 0, h))
        cr.paint()
        rng = self.rng
        layers = [("#B4BEC4", 0.52, 0.22, 26), ("#8E9AA1", 0.62, 0.3, 20),
                  ("#5F6B71", 0.76, 0.42, 15), ("#2E3639", 0.95, 0.62, 10)]
        for color, horizon, scale, count in layers:
            cr.set_source_rgba(*_hex(color))
            for _ in range(count):
                x = rng.random() * w
                th = h * scale * rng.uniform(0.7, 1.15)
                self._tree(cr, x, h * horizon + rng.uniform(-0.02, 0.04) * h, th, th * 0.42)
            # fog between the rows
            cr.set_source(_grad([(0, (0.85, 0.88, 0.9, 0.0)), (0.8, (0.85, 0.88, 0.9, 0.35)),
                                 (1, (0.85, 0.88, 0.9, 0.0))],
                                0, h * (horizon - 0.25), 0, h * (horizon + 0.06)))
            cr.rectangle(0, 0, w, h * (horizon + 0.06))
            cr.fill()
            cr.set_source_rgba(*_hex(color))
        # snow on the ground
        cr.set_source(_grad([(0, _hex("#D8DEE1")), (1, _hex("#AEB8BD"))], 0, h * 0.92, 0, h))
        cr.rectangle(0, h * 0.93, w, h * 0.07)
        cr.fill()

    def paint_dynamic(self, cr, w, h, t):
        # drifting fog banks (filled only where they are: painting the whole screen with a
        # gradient costs several times more)
        for k in range(2):
            fx = (t * (12 + k * 7) + k * w * 0.5) % (w * 1.6) - w * 0.3
            fy = h * (0.62 + k * 0.12)
            rad = w * 0.4
            cr.save()
            cr.translate(fx, fy)
            cr.scale(1, 0.25)
            g = cairo.RadialGradient(0, 0, 0, 0, 0, rad)
            g.add_color_stop_rgba(0, 0.9, 0.92, 0.94, 0.25)
            g.add_color_stop_rgba(1, 0.9, 0.92, 0.94, 0.0)
            cr.set_source(g)
            cr.arc(0, 0, rad, 0, 2 * math.pi)
            cr.fill()
            cr.restore()
        cr.set_source_rgba(1, 1, 1, 0.9)
        for x0, y0, depth, ph in self.flakes:
            y = (y0 + t * 60 * depth) % (h + 10) - 5
            x = (x0 + math.sin(t * 0.8 * depth + ph) * 18 * depth + t * 8 * depth) % w
            cr.arc(x, y, 0.9 + 1.9 * depth, 0, 2 * math.pi)
            cr.fill()


# -------------------------------------------------------------------- blue hour
class BlueHour(Scene):
    KEY, NAME, DESCRIPTION, ACCENT = ("blue-hour", "Blaue Stunde",
                                      "Dämmerung über dem Wasser", "#4F7BD9")

    def setup(self, w, h):
        rng = self.rng
        self.stars = [(rng.random() * w, rng.random() * h * 0.45, rng.random() * 6.28,
                       rng.uniform(0.4, 1.2)) for _ in range(90)]
        self.clouds = [(rng.random(), rng.uniform(0.08, 0.4), rng.uniform(0.12, 0.26),
                        rng.uniform(4, 10)) for _ in range(4)]
        self.glints = [(rng.random() * w, rng.uniform(0.66, 1.0) * h, rng.random() * 6.28,
                        rng.uniform(8, 40)) for _ in range(140)]

    def paint_static(self, cr, w, h):
        hz = h * 0.64
        cr.set_source(_grad([(0, _hex("#0E1A33")), (0.55, _hex("#2B4A7E")),
                             (0.9, _hex("#6F8FBF")), (1, _hex("#B7A6B8"))], 0, 0, 0, hz))
        cr.rectangle(0, 0, w, hz)
        cr.fill()
        cr.set_source(_grad([(0, _hex("#5B76A3")), (0.25, _hex("#2F4870")), (1, _hex("#0D1830"))],
                            0, hz, 0, h))
        cr.rectangle(0, hz, w, h - hz)
        cr.fill()
        # the far shore
        rng = self.rng
        cr.set_source_rgba(*_hex("#0B1426"))
        cr.move_to(0, hz)
        x = 0
        while x < w:
            cr.line_to(x, hz - rng.uniform(2, 14) - (18 if rng.random() < 0.15 else 0))
            x += rng.uniform(6, 22)
        cr.line_to(w, hz)
        cr.close_path()
        cr.fill()
        # glow on the horizon
        g = cairo.RadialGradient(w * 0.7, hz, 0, w * 0.7, hz, w * 0.5)
        g.add_color_stop_rgba(0, 1, 0.8, 0.75, 0.25)
        g.add_color_stop_rgba(1, 1, 0.8, 0.75, 0)
        cr.set_source(g)
        cr.paint()

    def paint_dynamic(self, cr, w, h, t):
        hz = h * 0.64
        for x, y, ph, size in self.stars:
            a = 0.25 + 0.55 * (0.5 + 0.5 * math.sin(t * 1.3 + ph)) * (1 - y / (h * 0.5))
            cr.set_source_rgba(1, 1, 1, max(0, a))
            cr.arc(x, y, size, 0, 2 * math.pi)
            cr.fill()
        for fx, fy, fw, speed in self.clouds:
            cx = ((fx * w + t * speed) % (w * 1.5)) - w * 0.25
            cy = fy * hz
            cr.save()
            cr.translate(cx, cy)
            cr.scale(1, 0.22)
            g = cairo.RadialGradient(0, 0, 0, 0, 0, fw * w)
            g.add_color_stop_rgba(0, 0.75, 0.8, 0.95, 0.16)
            g.add_color_stop_rgba(1, 0.75, 0.8, 0.95, 0)
            cr.set_source(g)
            cr.arc(0, 0, fw * w, 0, 2 * math.pi)
            cr.fill()
            cr.restore()
        cr.set_line_width(1.2)
        for x, y, ph, length in self.glints:
            a = max(0.0, math.sin(t * 1.7 + ph)) * 0.35 * (y - hz) / (h - hz + 1)
            if a < 0.02:
                continue
            dx = math.sin(t * 0.5 + ph) * 6
            cr.set_source_rgba(0.85, 0.9, 1, a)
            cr.move_to(x + dx, y)
            cr.line_to(x + dx + length, y)
            cr.stroke()


# ------------------------------------------------------------------ black hole
class BlackHole(Scene):
    KEY, NAME, DESCRIPTION, ACCENT = ("black-hole", "Ereignishorizont",
                                      "Eine glühende Scheibe um ein schwarzes Loch", "#FF8A3D")

    def setup(self, w, h):
        rng = self.rng
        self.R = min(w, h) * 0.12
        self.parts = []
        for _ in range(420):
            r = self.R * rng.uniform(1.35, 3.6)
            self.parts.append((r, rng.random() * 6.28, rng.uniform(0.6, 1.6)))

    def paint_static(self, cr, w, h):
        cr.set_source_rgb(0.01, 0.01, 0.02)
        cr.paint()
        rng = self.rng
        for _ in range(int(w * h / 3500)):
            a = rng.random() ** 3
            cr.set_source_rgba(1, 1, 1, 0.15 + 0.75 * a)
            cr.arc(rng.random() * w, rng.random() * h, 0.4 + a * 1.2, 0, 2 * math.pi)
            cr.fill()
        cx, cy = w / 2, h / 2
        g = cairo.RadialGradient(cx, cy, self.R, cx, cy, self.R * 5)
        g.add_color_stop_rgba(0, 1, 0.55, 0.2, 0.25)
        g.add_color_stop_rgba(1, 1, 0.55, 0.2, 0)
        cr.set_source(g)
        cr.paint()
        self._disk(cr, cx, cy)

    TILT = 0.2

    def _rings(self, cr, cx, cy, t, front):
        """The disk as glowing rings, brighter on the left where the gas comes towards
        us; `front` draws the half in front of the hole."""
        n = 26
        for i in range(n):
            u = i / (n - 1)
            r = self.R * (1.4 + 2.3 * u)
            heat = 1 - u
            alpha = (0.07 + 0.3 * heat ** 1.5) * (0.9 + 0.1 * math.sin(t * 3 + i))
            g = cairo.LinearGradient(cx - r, 0, cx + r, 0)
            g.add_color_stop_rgba(0, 1, 0.6 + 0.35 * heat, 0.3 + 0.5 * heat, min(1, alpha * 1.6))
            g.add_color_stop_rgba(1, 1, 0.45 + 0.3 * heat, 0.2 + 0.3 * heat, alpha * 0.45)
            cr.set_source(g)
            cr.save()
            cr.translate(cx, cy)
            cr.scale(1, self.TILT)
            if front:
                cr.arc(0, 0, r, 0, math.pi)
            else:
                cr.arc(0, 0, r, math.pi, 2 * math.pi)
            cr.restore()
            cr.set_line_width(self.R * 0.11)
            cr.stroke()

    def _sparks(self, cr, cx, cy, t, front):
        for r, a0, size in self.parts:
            a = a0 + t * 1.6 * (self.R / r) ** 1.5
            s = math.sin(a)
            if (s > 0) != front:
                continue
            x, y = math.cos(a) * r, s * r * self.TILT
            if not front and x * x + y * y < self.R * self.R:
                continue
            heat = min(1.0, (self.R * 3.6 - r) / (self.R * 2.2))
            boost = 0.55 + 0.45 * (-math.cos(a))
            cr.set_source_rgba(1, 0.6 + 0.4 * heat, 0.3 + 0.6 * heat ** 2, 0.15 + 0.45 * boost * heat)
            cr.arc(cx + x, cy + y, size * (0.6 + heat), 0, 2 * math.pi)
            cr.fill()

    def _disk(self, cr, cx, cy):
        """Rings, the bent light and the hole: still, so drawn once into the cache."""
        cr.set_operator(cairo.OPERATOR_ADD)
        self._rings(cr, cx, cy, 0, front=False)
        # the far side of the disk, bent by gravity over the top and under the hole
        for top, alpha in ((True, 0.5), (False, 0.22)):
            for i in range(8):
                rr = self.R * (1.06 + 0.06 * i)
                cr.set_source_rgba(1, 0.75 - 0.03 * i, 0.45 - 0.03 * i, alpha * (1 - i / 8))
                cr.set_line_width(self.R * 0.07)
                if top:
                    cr.arc(cx, cy, rr, math.pi * 1.02, math.pi * 1.98)
                else:
                    cr.arc(cx, cy, rr * 0.92, math.pi * 0.08, math.pi * 0.92)
                cr.stroke()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgb(0, 0, 0)
        cr.arc(cx, cy, self.R, 0, 2 * math.pi)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_ADD)
        cr.set_line_width(1.5)
        cr.set_source_rgba(1, 0.85, 0.6, 0.7)
        cr.arc(cx, cy, self.R * 1.02, 0, 2 * math.pi)
        cr.stroke()
        self._rings(cr, cx, cy, 0, front=True)
        cr.set_operator(cairo.OPERATOR_OVER)

    def paint_dynamic(self, cr, w, h, t):
        # only the sparks circle; the ones behind the hole stay hidden
        cr.set_operator(cairo.OPERATOR_ADD)
        self._sparks(cr, w / 2, h / 2, t, front=False)
        self._sparks(cr, w / 2, h / 2, t, front=True)
        cr.set_operator(cairo.OPERATOR_OVER)


# ------------------------------------------------------------------------ ember
class Ember(Scene):
    KEY, NAME, DESCRIPTION, ACCENT = ("ember", "Glut",
                                      "Glühende Fäden, langsam wie Seide", "#E0413A")

    def setup(self, w, h):
        rng = self.rng
        self.lines = [(rng.uniform(0.25, 0.75), rng.uniform(0.6, 1.6), rng.random() * 6.28,
                       rng.uniform(0.05, 0.16), rng.uniform(0.15, 0.4)) for _ in range(22)]
        self.dust = [(rng.random() * w, rng.random() * h, rng.random() * 6.28) for _ in range(120)]

    def paint_static(self, cr, w, h):
        g = cairo.RadialGradient(w * 0.55, h * 0.55, 0, w * 0.55, h * 0.55, max(w, h) * 0.8)
        g.add_color_stop_rgb(0, 0.09, 0.02, 0.03)
        g.add_color_stop_rgb(1, 0.01, 0.0, 0.01)
        cr.set_source(g)
        cr.paint()

    def paint_dynamic(self, cr, w, h, t):
        cr.set_operator(cairo.OPERATOR_ADD)
        cr.set_line_width(1.6)
        for base, freq, ph, amp, speed in self.lines:
            cr.set_source_rgba(0.95, 0.35 + amp, 0.3, 0.24 + amp * 1.5)
            n = 48
            for i in range(n + 1):
                x = w * i / n
                u = i / n
                y = h * (base + amp * math.sin(u * 6.28 * freq + t * speed + ph)
                         + 0.04 * math.sin(u * 13 + t * speed * 1.7 + ph * 2))
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
        for x, y, ph in self.dust:
            yy = (y - t * 9) % h
            a = 0.2 + 0.3 * (0.5 + 0.5 * math.sin(t + ph))
            cr.set_source_rgba(1, 0.75, 0.4, a)
            cr.arc(x + math.sin(t * 0.3 + ph) * 12, yy, 1.1, 0, 2 * math.pi)
            cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)


SCENES = {cls.KEY: cls for cls in (SnowForest, BlueHour, BlackHole, Ember)}


def scene_for(path):
    if not is_live(path):
        return None
    cls = SCENES.get(path[len(LIVE_PREFIX):])
    return cls() if cls else None


def thumbnail(key, w=280, h=160, t=4.0):
    """A still frame of a scene as texture (the settings' wallpaper grid)."""
    cls = SCENES.get(key)
    if cls is None:
        return None
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cls().draw(cairo.Context(surf), w, h, t)
    surf.flush()
    data = GLib.Bytes.new(bytes(surf.get_data()))
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data,
                                 surf.get_stride())


class LiveWallpaper(Gtk.DrawingArea):
    """Plays a scene while it is on screen, at `fps` frames a second."""

    def __init__(self, scene, fps=24):
        super().__init__(hexpand=True, vexpand=True, can_target=False)
        self.scene = scene
        self.fps = max(1, int(fps))
        self.t0 = GLib.get_monotonic_time()
        self._last = 0
        self.set_draw_func(self._draw)
        self.add_tick_callback(self._tick)

    def _tick(self, _w, clock):
        now = clock.get_frame_time()
        if now - self._last >= 1_000_000 / self.fps:
            self._last = now
            self.queue_draw()
        return True

    def _draw(self, _a, cr, w, h):
        t = (GLib.get_monotonic_time() - self.t0) / 1e6
        self.scene.draw(cr, w, h, t)


def video_paintable(path):
    """A muted, looping video as paintable for a Gtk.Picture."""
    if not os.path.exists(path):
        return None
    media = Gtk.MediaFile.new_for_filename(path)
    media.set_loop(True)
    media.set_muted(True)
    media.play()
    return media


def wallpaper_widget(path, fps=24, fit=Gtk.ContentFit.COVER):
    """A widget showing any wallpaper value: a scene, a video or a picture; None if there
    is nothing to show."""
    if is_live(path):
        scene = scene_for(path)
        return LiveWallpaper(scene, fps) if scene else None
    if not path or not os.path.exists(path):
        return None
    pic = Gtk.Picture(content_fit=fit, can_shrink=True, hexpand=True, vexpand=True)
    if is_video(path):
        pic.set_paintable(video_paintable(path))
    else:
        pic.set_filename(path)
    return pic
