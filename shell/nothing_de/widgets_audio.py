"""Music widgets: the equalizer card, the round dot visualizer and the cassette deck.

All three follow what is playing (media.py) and the live spectrum (audio.py); the
equalizer's bands act on the whole system through PipeWire (equalizer.py).
"""
import datetime
import math
import random
import time

import numpy as np
from gi.repository import Gtk, Pango

from . import audio, dotmatrix
from .equalizer import (
    LABELS,
    MAX_DB,
    PRESETS,
    get_equalizer,
    matching_preset,
    preset_gains,
)
from .media import art_initial, fmt_time, get_media
from .widget_sdk import DesktopWidget, register_widget
from .widgets import accent_rgba, caps


def _band(levels, a, b):
    """Mean level of the spectrum bands a..b (fractions of the range)."""
    if not levels:
        return 0.0
    n = len(levels)
    part = levels[int(a * n):max(int(a * n) + 1, int(b * n))]
    return sum(part) / len(part)


class Beat:
    """A simple beat detector on the bass: fires when the bass jumps above its average."""

    def __init__(self):
        self.avg = 0.0
        self.last = 0.0

    def __call__(self, bass):
        now = time.monotonic()
        hit = bass > 0.22 and bass > self.avg * 1.3 and now - self.last > 0.24
        self.avg += (bass - self.avg) * 0.08
        if hit:
            self.last = now
        return hit


def _rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _cover(size):
    """A round cover-art slot: picture, or the title's first letter without one."""
    frame = Gtk.Overlay()
    frame.add_css_class("n-cover")
    frame.set_size_request(size, size)
    frame.set_overflow(Gtk.Overflow.HIDDEN)
    frame.set_valign(Gtk.Align.CENTER)
    # no hexpand/vexpand in here: it would spread to the rows around the cover
    letter = Gtk.Label(label="♪", halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    frame.set_child(letter)
    pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
    frame.add_overlay(pic)
    frame.n_pic, frame.n_letter = pic, letter
    return frame


def set_cover(frame, media):
    frame.n_pic.set_paintable(media.art)
    frame.n_pic.set_visible(media.art is not None)
    frame.n_letter.set_label(art_initial(media.title))


# ====================================================================== equalizer
@register_widget
class EqualizerWidget(DesktopWidget):
    """What is playing with its controls, above a 10-band equalizer for the whole
    system (PipeWire) with presets."""
    TYPE, NAME, SIZE = "equalizer", "Equalizer", "tall"

    def build(self):
        self.eq = get_equalizer(self.cfg)
        self.media = get_media()
        self.gains = list(self.eq.gains)
        self._drag_col = None
        self._apply_id = self._save_id = None
        self._syncing = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, vexpand=True)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)

        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image(icon_name="audio-x-generic-symbolic"))
        self.player = caps("MEDIEN")
        self.player.set_hexpand(True)
        head.append(self.player)
        box.append(head)

        now = Gtk.Box(spacing=12)
        self.cover = _cover(52)
        now.append(self.cover)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True,
                       valign=Gtk.Align.CENTER)
        # few characters as natural width: on the desktop's Gtk.Fixed a widget gets its
        # natural size, a long title would stretch the card
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        self.title.add_css_class("n-strong")
        self.artist = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        self.artist.add_css_class("n-muted")
        info.append(self.title)
        info.append(self.artist)
        now.append(info)
        ctl = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        for icon, method in (("media-skip-backward-symbolic", "Previous"),
                             ("media-playback-start-symbolic", "PlayPause"),
                             ("media-skip-forward-symbolic", "Next")):
            b = Gtk.Button(icon_name=icon)
            b.add_css_class("flat" if method != "PlayPause" else "n-round")
            b.connect("clicked", lambda _b, m=method: self.media.call(m))
            ctl.append(b)
            if method == "PlayPause":
                self.play_btn = b
        now.append(ctl)
        box.append(now)

        prog = Gtk.Box(spacing=8)
        self.pos = caps("0:00")
        self.len = caps("0:00")
        self.bar = Gtk.DrawingArea(content_height=12, hexpand=True, valign=Gtk.Align.CENTER)
        self.bar.set_draw_func(self._draw_progress)
        seek = Gtk.GestureClick()
        seek.connect("released", lambda _g, _n, x, _y:
                     self.media.seek(x / max(1, self.bar.get_width())))
        self.bar.add_controller(seek)
        prog.append(self.pos)
        prog.append(self.bar)
        prog.append(self.len)
        box.append(prog)

        eqhead = Gtk.Box(spacing=8)
        t = caps("EQUALIZER")
        t.set_hexpand(True)
        eqhead.append(t)
        self.preset_lbl = caps("")
        eqhead.append(self.preset_lbl)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._on_switch)
        eqhead.append(self.switch)
        box.append(eqhead)

        self.sliders = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.sliders.set_draw_func(self._draw_sliders)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._slide_begin)
        drag.connect("drag-update", self._slide_update)
        drag.connect("drag-end", lambda *_: self._slide_end())
        self.sliders.add_controller(drag)
        reset = Gtk.GestureClick()
        reset.connect("pressed", self._on_double_click)
        self.sliders.add_controller(reset)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.sliders.add_controller(scroll)
        self._pointer_x = 0
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, _y: setattr(self, "_pointer_x", x))
        self.sliders.add_controller(motion)
        box.append(self.sliders)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
        self.preset_btns = {}
        for i, (key, name, _g) in enumerate(PRESETS):
            b = Gtk.Button(label=name)
            b.add_css_class("n-eq-preset")
            b.connect("clicked", lambda _b, k=key: self.set_preset(k))
            grid.attach(b, i % 4, i // 4, 1, 1)
            self.preset_btns[key] = b
        box.append(grid)
        self.append(box)

        self._media_id = self.media.listen(lambda *_: self.refresh())
        self._art_id = self.media.connect("art", lambda *_: set_cover(self.cover, self.media))
        set_cover(self.cover, self.media)
        self.timeout_add(500, self._tick)

    # ----------------------------------------------------------------- media
    def _tick(self):
        if self.media.playing:
            self.pos.set_label(fmt_time(self.media.position))
            self.bar.queue_draw()
        return True

    def refresh(self):
        m = getattr(self, "media", None)
        if m is None:
            return
        if m.available:
            self.title.set_label(m.title or "Unbekannt")
            self.artist.set_label(m.artist)
            self.player.set_label(m.player.upper())
        else:
            self.title.set_label("Keine Wiedergabe")
            self.artist.set_label("")
            self.player.set_label("MEDIEN")
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if m.playing
                                    else "media-playback-start-symbolic")
        self.pos.set_label(fmt_time(m.position))
        self.len.set_label(fmt_time(m.length))
        self.bar.queue_draw()
        self._sync_eq()

    def on_config(self):
        self.refresh()

    def _sync_eq(self):
        self._syncing = True
        self.switch.set_active(bool(self.cfg.get("eq.enabled")))
        self._syncing = False
        if self._drag_col is None and self._save_id is None:
            self.gains = list(self.eq.gains if self.eq.enabled else
                              (self.cfg.get("eq.gains") or self.gains))
            self.gains = (self.gains + [0.0] * 10)[:10]
        self._update_presets()
        if self.eq.error:
            self.preset_lbl.set_label("FEHLER")
            self.set_tooltip_text(self.eq.error)
        self.sliders.queue_draw()

    def _update_presets(self):
        cur = matching_preset(self.gains)
        for key, b in self.preset_btns.items():
            if key == cur:
                b.add_css_class("on")
            else:
                b.remove_css_class("on")
        name = next((n for k, n, _g in PRESETS if k == cur), "Eigene")
        self.preset_lbl.set_label(name.upper())

    def _draw_progress(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        y = h / 2
        cr.set_line_cap(1)
        cr.set_line_width(3)
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.15)
        cr.move_to(2, y)
        cr.line_to(w - 2, y)
        cr.stroke()
        x = 2 + (w - 4) * self.media.progress
        cr.set_source_rgba(*fg)
        cr.move_to(2, y)
        cr.line_to(x, y)
        cr.stroke()
        cr.set_source_rgba(*acc)
        cr.arc(x, y, 4.5, 0, 2 * math.pi)
        cr.fill()

    # ------------------------------------------------------------- equalizer
    def _on_switch(self, sw, _p):
        if not self._syncing:
            self.cfg.set("eq.enabled", sw.get_active())

    def set_preset(self, key):
        self.gains = preset_gains(key)
        self._changed(save_now=True)

    def _changed(self, save_now=False):
        self._update_presets()
        self.sliders.queue_draw()
        if self._apply_id is None:
            # live, but not more often than every 80 ms (pw-cli per change)
            def apply():
                self._apply_id = None
                self.eq.set_gains(self.gains)
                return False
            self._apply_id = self.timeout_add(80, apply)
        if self._save_id is not None:
            self.remove_timeout(self._save_id)

        def save():
            self._save_id = None
            self.cfg.set("eq.gains", [round(g, 1) for g in self.gains])
            return False
        self._save_id = self.timeout_add(50 if save_now else 600, save)

    def _geom(self):
        w, h = self.sliders.get_width(), self.sliders.get_height()
        top, bottom = 10, h - 22
        return w / len(self.gains), top, bottom

    def _value_at(self, y):
        _cw, top, bottom = self._geom()
        frac = (y - top) / max(1, bottom - top)
        v = MAX_DB - frac * 2 * MAX_DB
        v = max(-MAX_DB, min(MAX_DB, v))
        return round(v * 2) / 2

    def _slide_begin(self, _g, x, y):
        cw, _t, _b = self._geom()
        self._drag_col = max(0, min(len(self.gains) - 1, int(x / cw)))
        self._drag_start = (x, y)
        self.gains[self._drag_col] = self._value_at(y)
        self._changed()

    def _slide_update(self, _g, dx, dy):
        if self._drag_col is None:
            return
        x, y = self._drag_start[0] + dx, self._drag_start[1] + dy
        cw, _t, _b = self._geom()
        # sweeping across draws a curve over several bands
        col = max(0, min(len(self.gains) - 1, int(x / cw)))
        self._drag_col = col
        self.gains[col] = self._value_at(y)
        self._changed()

    def _slide_end(self):
        self._drag_col = None

    def _on_double_click(self, _g, n, x, _y):
        if n == 2:
            cw, _t, _b = self._geom()
            col = max(0, min(len(self.gains) - 1, int(x / cw)))
            self.gains[col] = 0.0
            self._changed()

    def _on_scroll(self, _c, _dx, dy):
        cw, _t, _b = self._geom()
        col = max(0, min(len(self.gains) - 1, int(self._pointer_x / cw)))
        self.gains[col] = max(-MAX_DB, min(MAX_DB, self.gains[col] - dy * 0.5))
        self._changed()
        return True

    def _draw_sliders(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        on = bool(self.cfg.get("eq.enabled"))
        cw, top, bottom = self._geom()
        mid = (top + bottom) / 2
        cr.set_line_cap(1)
        # 0 dB line
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.08)
        cr.set_line_width(1)
        cr.move_to(0, mid)
        cr.line_to(w, mid)
        cr.stroke()
        cr.select_font_face("monospace")
        cr.set_font_size(9.5)
        fill = acc if on else (fg[0], fg[1], fg[2], 0.45)
        for i, g in enumerate(self.gains):
            x = cw * i + cw / 2
            cr.set_line_width(5)
            cr.set_source_rgba(fg[0], fg[1], fg[2], 0.12)
            cr.move_to(x, top)
            cr.line_to(x, bottom)
            cr.stroke()
            y = mid - g / MAX_DB * (bottom - top) / 2
            cr.set_source_rgba(*fill)
            cr.move_to(x, mid)
            cr.line_to(x, y + 0.01)
            cr.stroke()
            cr.set_source_rgba(*fg)
            cr.arc(x, y, 7, 0, 2 * math.pi)
            cr.fill()
            if i == self._drag_col:
                cr.set_source_rgba(*acc)
                cr.arc(x, y, 3, 0, 2 * math.pi)
                cr.fill()
            label = LABELS[i]
            ext = cr.text_extents(label)
            cr.set_source_rgba(fg[0], fg[1], fg[2], 0.5)
            cr.move_to(x - ext.width / 2 - ext.x_bearing, h - 4)
            cr.show_text(label)

    def teardown(self):
        if getattr(self, "_media_id", None):
            self.media.release(self._media_id)
            self.media.disconnect(self._art_id)
            self._media_id = None
        super().teardown()


# =============================================================== dot visualizer
MODES = ["face", "pulse", "ripple", "torus", "clock", "ticker"]


@register_widget
class DotVisualizerWidget(DesktopWidget):
    """A round dot matrix that lives with the music: a face that looks at the pointer and
    sings along, pulsing rings, ripples on the beat, a turning torus, the time and the
    title as a ticker. Click or scroll switches the mode."""
    TYPE, NAME, SIZE = "dot-visualizer", "Dot-Visualizer", "large"
    N = 25

    def build(self):
        self.add_css_class("n-circle")
        self.area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)
        n = self.N
        c = (np.arange(n) - (n - 1) / 2) / ((n - 1) / 2)
        self.X, self.Y = np.meshgrid(c, c)
        self.R = np.sqrt(self.X ** 2 + self.Y ** 2)
        self.inside = self.R <= 1.0
        self.levels = []
        self.bass = self.mid = self.high = 0.0
        self.beat = Beat()
        self.ripples = []
        self.look = [0.0, 0.0]
        self.look_target = [0.0, 0.0]
        self.pointer = None
        self.blink_at = time.monotonic() + 3
        self.t0 = time.monotonic()
        self.mode_shown = 0.0
        self._last_frame = 0.0
        self._torus_pts = self._torus_points()
        self.media = get_media()
        self._media_id = self.media.listen(lambda *_: None)
        self.spectrum = audio.get_spectrum()
        self._sub = self.spectrum.subscribe(self._on_levels)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._next_mode(1))
        self.add_controller(click)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", lambda _c, _dx, dy: (self._next_mode(1 if dy > 0 else -1), True)[1])
        self.add_controller(scroll)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_: setattr(self, "pointer", None))
        self.add_controller(motion)
        self.set_tooltip_text("Klick/Scrollen: Modus wechseln")
        self.area.add_tick_callback(self._frame)

    @property
    def mode(self):
        m = self.cfg.get("dotvis.mode") or "face"
        return m if m in MODES else "face"

    def _next_mode(self, step):
        i = (MODES.index(self.mode) + step) % len(MODES)
        self.cfg.set("dotvis.mode", MODES[i])
        self.mode_shown = time.monotonic()
        self.area.queue_draw()

    def _on_motion(self, _c, x, y):
        w, h = self.area.get_width(), self.area.get_height()
        px, py = (x - w / 2) / (w / 2), (y - h / 2) / (h / 2)
        last = self.pointer
        self.pointer = (px, py)
        if self.mode == "ripple" and (last is None or math.dist(last, self.pointer) > 0.25):
            self.ripples.append([px, py, time.monotonic(), 0.6])

    def _on_levels(self, levels):
        self.levels = levels
        self.bass = _band(levels, 0, 0.12)
        self.mid = _band(levels, 0.12, 0.55)
        self.high = _band(levels, 0.55, 1)
        if self.beat(self.bass) and self.mode == "ripple":
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(0, 0.5)
            self.ripples.append([math.cos(a) * r, math.sin(a) * r, time.monotonic(), 1.0])

    def _frame(self, _w, _clock):
        now = time.monotonic()
        if now - self._last_frame >= 1 / 30:
            self._last_frame = now
            self.area.queue_draw()
        return True

    # ------------------------------------------------------------------ modes
    def _face(self, t):
        X, Y = self.X, self.Y
        if self.pointer is not None:
            self.look_target = [max(-1, min(1, self.pointer[0])), max(-1, min(1, self.pointer[1]))]
        else:
            # wander a little on its own
            self.look_target = [math.sin(t * 0.4) * 0.6, math.sin(t * 0.27) * 0.3]
        for i in (0, 1):
            self.look[i] += (self.look_target[i] - self.look[i]) * 0.15
        lx, ly = self.look[0] * 0.1, self.look[1] * 0.08
        now = time.monotonic()
        if now > self.blink_at + 0.16:
            self.blink_at = now + random.uniform(2.5, 6)
        blink = 0.12 if self.blink_at <= now <= self.blink_at + 0.16 else 1.0
        b = np.zeros_like(X)
        acc = np.zeros_like(X, dtype=bool)
        eh = 0.36 * blink
        for cx in (-0.36, 0.36):
            ex, ey = cx + lx, -0.1 + ly
            dx = (X - ex) / 0.17
            dy = (Y - ey) / eh
            # a dome: round top, flat bottom with a notch in the middle
            dome = (dx ** 2 + np.minimum(dy, 0) ** 2 <= 1.0) & (dy <= 0.9) & (np.abs(dx) <= 1)
            notch = (np.abs(dx) < 0.3) & (dy > 0.45)
            b[dome & ~notch] = 1.0
        for cx in (-0.42, 0.42):
            cheek = (np.abs(X - cx - lx * 0.5) < 0.1) & (np.abs(Y - 0.3) < 0.05)
            b[cheek] = 1.0
            acc |= cheek
        # the mouth opens with the bass
        open_ = 0.04 + min(0.18, self.bass * 0.3)
        mouth = (np.abs(X - lx * 0.5) < 0.1 + self.mid * 0.08) & (np.abs(Y - 0.5) < open_)
        b[mouth] = 0.85
        return b, acc

    def _pulse(self, t):
        b = np.zeros_like(self.R)
        speed = 0.35 + self.bass * 0.8
        for k in range(3):
            rad = ((t * speed + k / 3) % 1.0) * 1.15
            b += np.exp(-((self.R - rad) / (0.05 + self.bass * 0.05)) ** 2) * (1 - rad / 1.25)
        core = np.exp(-(self.R / (0.12 + self.bass * 0.35)) ** 2)
        b = np.maximum(b, core)
        acc = core > 0.6
        return np.clip(b, 0, 1), acc

    def _ripple(self, t):
        now = time.monotonic()
        if not self.ripples or now - self.ripples[-1][2] > 1.6:
            a = random.uniform(0, 2 * math.pi)
            self.ripples.append([math.cos(a) * 0.3, math.sin(a) * 0.3, now, 0.7])
        self.ripples = [r for r in self.ripples if now - r[2] < 2.2][-8:]
        b = np.zeros_like(self.R)
        acc = np.zeros_like(self.R, dtype=bool)
        for i, (cx, cy, t0, strength) in enumerate(self.ripples):
            age = now - t0
            d = np.sqrt((self.X - cx) ** 2 + (self.Y - cy) ** 2)
            ring = np.exp(-((d - age * 0.9) / 0.08) ** 2) * strength * (1 - age / 2.2)
            b += ring
            if i == len(self.ripples) - 1:
                acc |= ring > 0.5
        return np.clip(b, 0, 1), acc

    @staticmethod
    def _torus_points():
        u, v = np.meshgrid(np.linspace(0, 2 * np.pi, 48, endpoint=False),
                           np.linspace(0, 2 * np.pi, 16, endpoint=False))
        R, r = 0.62, 0.28
        x = (R + r * np.cos(v)) * np.cos(u)
        y = (R + r * np.cos(v)) * np.sin(u)
        z = r * np.sin(v)
        return np.stack([x.ravel(), y.ravel(), z.ravel()])

    def _torus(self, t):
        a, c = t * (0.5 + self.mid), t * 0.33
        ca, sa, cc, sc = math.cos(a), math.sin(a), math.cos(c), math.sin(c)
        rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
        rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
        p = rz @ rx @ self._torus_pts
        scale = 0.95 + self.bass * 0.25
        n = self.N
        gx = np.clip(((p[0] * scale + 1) / 2 * (n - 1)).round().astype(int), 0, n - 1)
        gy = np.clip(((p[1] * scale + 1) / 2 * (n - 1)).round().astype(int), 0, n - 1)
        depth = (p[2] + 0.9) / 1.8
        b = np.zeros((n, n))
        np.maximum.at(b, (gy, gx), 0.25 + depth * 0.75)
        return b, b > 0.95

    def _text_grid(self, rows_list):
        """Bitmaps (lists of rows) stacked and centred on the grid."""
        n = self.N
        b = np.zeros((n, n))
        total = sum(len(r) for r in rows_list) + 2 * (len(rows_list) - 1)
        y = (n - total) // 2
        for rows in rows_list:
            w = len(rows[0])
            x = (n - w) // 2
            for r, line in enumerate(rows):
                for col, on in enumerate(line):
                    if on and 0 <= y + r < n and 0 <= x + col < n:
                        b[y + r, x + col] = 1.0
            y += len(rows) + 2
        return b

    def _clock(self, t):
        now = datetime.datetime.now()
        h24 = self.cfg.get("bar.clock_24h", True)
        hour = now.hour if h24 else (now.hour % 12 or 12)
        b = self._text_grid([dotmatrix.bitmap(f"{hour:02d}"), dotmatrix.bitmap(f"{now.minute:02d}")])
        acc = np.zeros_like(b, dtype=bool)
        # the seconds run around the edge
        a = (now.second + now.microsecond / 1e6) / 60 * 2 * math.pi
        ang = np.arctan2(self.X, -self.Y) % (2 * math.pi)
        edge = (self.R > 0.86) & (self.R <= 1.0)
        trail = edge & (ang <= a)
        b[trail] = np.maximum(b[trail], 0.35)
        head = edge & (np.abs(ang - a) < 0.2)
        b[head] = 1.0
        acc |= head
        return b, acc

    def _ticker(self, t):
        m = self.media
        text = f"{m.title} · {m.artist}" if m.title else datetime.datetime.now().strftime("%H:%M")
        text = text.upper() + "   "
        rows = dotmatrix.bitmap(text)
        w = len(rows[0])
        n = self.N
        b = np.zeros((n, n))
        off = int(t * 9) % (w + n) - n
        y0 = 6
        for r, line in enumerate(rows):
            for c in range(n):
                k = c + off
                if 0 <= k < w and line[k]:
                    b[y0 + r, c] = 1.0
        # the spectrum underneath
        lv = audio.resample(self.levels, n) if self.levels else [0.0] * n
        acc = np.zeros_like(b, dtype=bool)
        for c, v in enumerate(lv):
            hgt = int(round(v * 9))
            for r in range(hgt):
                row = n - 3 - r
                b[row, c] = max(b[row, c], 0.55 if r < hgt - 1 else 1.0)
                if r == hgt - 1:
                    acc[row, c] = True
        return b, acc

    def _draw(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc_c = accent_rgba(self.cfg)
        t = time.monotonic() - self.t0
        mode = self.mode
        b, acc = getattr(self, "_" + mode)(t)
        n = self.N
        d = min(w, h) - 20
        pitch = d / n
        x0, y0 = (w - d) / 2, (h - d) / 2
        rmax = pitch * 0.42
        for row in range(n):
            for col in range(n):
                if not self.inside[row, col]:
                    continue
                v = float(b[row, col])
                cx, cy = x0 + col * pitch + pitch / 2, y0 + row * pitch + pitch / 2
                if v < 0.18:
                    cr.set_source_rgba(fg[0], fg[1], fg[2], 0.08)
                    cr.arc(cx, cy, rmax * 0.55, 0, 2 * math.pi)
                elif acc[row, col]:
                    cr.set_source_rgba(*acc_c)
                    cr.arc(cx, cy, rmax, 0, 2 * math.pi)
                else:
                    cr.set_source_rgba(fg[0], fg[1], fg[2], 0.25 + 0.75 * v)
                    cr.arc(cx, cy, rmax * (0.6 + 0.4 * v), 0, 2 * math.pi)
                cr.fill()
        # the mode's name for a moment after switching
        if time.monotonic() - self.mode_shown < 1.5:
            cr.select_font_face("monospace")
            cr.set_font_size(11)
            label = mode.upper()
            ext = cr.text_extents(label)
            _rounded(cr, w / 2 - ext.width / 2 - 10, h - 46, ext.width + 20, 22, 11)
            cr.set_source_rgba(0, 0, 0, 0.7)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.move_to(w / 2 - ext.width / 2 - ext.x_bearing, h - 31)
            cr.show_text(label)

    def teardown(self):
        if self._sub:
            self.spectrum.unsubscribe(self._sub)
            self._sub = None
        if self._media_id:
            self.media.release(self._media_id)
            self._media_id = None
        super().teardown()


# ===================================================================== cassette
@register_widget
class CassetteWidget(DesktopWidget):
    """A cassette deck: the reels turn while music plays and the tape winds over with the
    track's progress; next to it an oscilloscope and LOW / MID / HIGH meters.
    Click: play/pause, scroll: next/previous track."""
    TYPE, NAME, SIZE = "cassette", "Kassette", "deck"

    def build(self):
        self.area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)
        self.media = get_media()
        self._media_id = self.media.listen(lambda *_: self.area.queue_draw())
        self.spectrum = audio.get_spectrum()
        self._sub = self.spectrum.subscribe(self._on_levels)
        self.levels = []
        self.angle = [0.0, 0.0]
        self.phase = 0.0
        self._last = time.monotonic()
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.media.call("PlayPause"))
        self.add_controller(click)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", lambda _c, _dx, dy: (self.media.call("Next" if dy > 0 else "Previous"), True)[1])
        self.add_controller(scroll)
        self.set_tooltip_text("Klick: Wiedergabe/Pause · Scrollen: Titel wechseln")
        self.area.add_tick_callback(self._frame)

    def _on_levels(self, levels):
        self.levels = levels

    def _frame(self, _w, _clock):
        now = time.monotonic()
        dt = now - self._last
        if dt < 1 / 30:
            return True
        self._last = now
        if self.media.playing or self.levels and max(self.levels) > 0.02:
            if self.media.playing:
                p = self.media.progress
                # the fuller reel turns slower, as on a real deck
                for i, pack in enumerate((1 - p, p)):
                    self.angle[i] += dt * 4.2 / (0.55 + pack)
            self.phase += dt * 6
            self.area.queue_draw()
        return True

    def _reel(self, cr, cx, cy, pack, angle, fg, acc):
        rmin, rmax = 14, 36
        r = rmin + (rmax - rmin) * pack
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.08)
        cr.arc(cx, cy, rmax + 3, 0, 2 * math.pi)
        cr.fill()
        # the wound tape
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.32)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.12)
        cr.set_line_width(1)
        for k in range(1, 4):
            cr.arc(cx, cy, rmin + (r - rmin) * k / 4, 0, 2 * math.pi)
            cr.stroke()
        # hub with spokes
        cr.set_source_rgba(0.06, 0.06, 0.07, 1)
        cr.arc(cx, cy, rmin - 1, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(*fg)
        cr.set_line_width(2.4)
        cr.arc(cx, cy, rmin - 1, 0, 2 * math.pi)
        cr.stroke()
        cr.set_line_cap(1)
        for k in range(6):
            a = angle + k * math.pi / 3
            cr.move_to(cx + math.cos(a) * 4, cy + math.sin(a) * 4)
            cr.line_to(cx + math.cos(a) * (rmin - 4), cy + math.sin(a) * (rmin - 4))
            cr.stroke()
        cr.set_source_rgba(*acc)
        cr.arc(cx, cy, 2.2, 0, 2 * math.pi)
        cr.fill()

    def _text(self, cr, x, y, text, size, color, bold=False):
        cr.select_font_face("monospace", 0, 1 if bold else 0)
        cr.set_font_size(size)
        cr.set_source_rgba(*color)
        cr.move_to(x, y)
        cr.show_text(text)

    def _fit(self, cr, text, width):
        while text and cr.text_extents(text).width > width:
            text = text[:-2] + "…" if len(text) > 2 else ""
        return text

    def _draw(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        muted = (fg[0], fg[1], fg[2], 0.5)
        m = self.media
        pad = 14
        lw = 216
        # ------------------------------------------------ the cassette
        _rounded(cr, pad, pad, lw, h - 2 * pad, 14)
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.05)
        cr.fill_preserve()
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.14)
        cr.set_line_width(1)
        cr.stroke()
        self._text(cr, pad + 12, pad + 24, "A", 18, fg, bold=True)
        cr.select_font_face("monospace", 0, 1)
        cr.set_font_size(11)
        title = self._fit(cr, (m.title or "KEINE KASSETTE").upper(), lw - 50)
        self._text(cr, pad + 34, pad + 18, title, 11, fg, bold=True)
        cr.set_font_size(9)
        artist = self._fit(cr, (m.artist or m.player or "—").upper(), lw - 110)
        self._text(cr, pad + 34, pad + 31, artist, 9, muted)
        self._text(cr, pad + lw - 66, pad + 31, "C-90 CHROME", 8, muted)
        p = m.progress
        cy = pad + 82
        lx, rx = pad + 56, pad + lw - 56
        self._reel(cr, lx, cy, 1 - p, self.angle[0], fg, acc)
        self._reel(cr, rx, cy, p, self.angle[1], fg, acc)
        # tape running along the bottom between the reels
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.35)
        cr.set_line_width(1.2)
        cr.move_to(lx - 10, cy + 40)
        cr.line_to(rx + 10, cy + 40)
        cr.stroke()
        _rounded(cr, pad + lw / 2 - 18, cy + 34, 36, 12, 4)
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.2)
        cr.fill()
        # counter and state
        by = h - pad - 12
        counter = fmt_time(m.position).rjust(5, "0")[-5:]
        dotmatrix.draw(cr, counter, pad + 12, by - 16, 2.6, fg)
        state = "PLAY ›" if m.playing else ("PAUSE" if m.available else "STOP")
        self._text(cr, pad + 22 + dotmatrix.columns(counter) * 2.6, by - 3, state, 10, fg, bold=True)
        blink = m.playing and int(time.monotonic() * 2) % 2 == 0
        self._text(cr, pad + lw - 44, by - 2, "REC", 9, muted)
        cr.set_source_rgba(*(acc if blink or not m.playing else (acc[0], acc[1], acc[2], 0.35)))
        cr.arc(pad + lw - 14, by - 5.5, 4, 0, 2 * math.pi)
        cr.fill()

        # ------------------------------------------------ oscilloscope
        sx = pad + lw + 12
        sw = w - sx - pad
        sh = 104
        _rounded(cr, sx, pad, sw, sh, 10)
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.05)
        cr.fill_preserve()
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.14)
        cr.stroke()
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.12)
        for gx in range(1, 6):
            for gy in range(1, 4):
                cr.arc(sx + sw * gx / 6, pad + sh * gy / 4, 0.9, 0, 2 * math.pi)
                cr.fill()
        lv = audio.resample(self.levels, 12) if self.levels else [0.0] * 12
        mid = pad + sh / 2 - 6
        amp = sh * 0.36
        pts = []
        for i in range(90):
            x = i / 89
            y = 0.0
            for k, v in enumerate(lv):
                y += v * math.sin(x * (k + 1) * 4.5 + self.phase * (1 + k * 0.35) + k)
            y = math.tanh(y * 0.8)
            # fade towards both ends like a scope trace
            env = math.sin(x * math.pi) ** 0.6
            pts.append((sx + 8 + (sw - 16) * x, mid - y * amp * env))
        cr.set_line_join(1)
        for width, alpha in ((5, 0.12), (1.8, 0.95)):
            cr.set_line_width(width)
            cr.set_source_rgba(fg[0], fg[1], fg[2], alpha)
            cr.move_to(*pts[0])
            for pt in pts[1:]:
                cr.line_to(*pt)
            cr.stroke()
        self._text(cr, sx + 8, pad + sh - 8, "CH1 2V/DIV · TB 5MS", 7.5, muted)
        bpm = "LIVE" if self.spectrum.backend else "—"
        self._text(cr, sx + sw - 34, pad + sh - 8, bpm, 7.5, muted)

        # ------------------------------------------------ meters
        bands = (("LOW", _band(self.levels, 0, 0.15)), ("MID", _band(self.levels, 0.15, 0.6)),
                 ("HIGH", _band(self.levels, 0.6, 1)))
        my = pad + sh + 20
        step = (h - pad - my) / 3
        for i, (name, v) in enumerate(bands):
            y = my + i * step + step / 2
            self._text(cr, sx + 2, y + 3, name, 8.5, muted)
            lit = int(round(min(1.0, v * 1.8) * 8))
            for k in range(8):
                on = k < lit
                cr.set_source_rgba(*((acc if k == lit - 1 else fg) if on else
                                     (fg[0], fg[1], fg[2], 0.14)))
                cr.arc(sx + 48 + k * ((sw - 56) / 8), y, 3, 0, 2 * math.pi)
                cr.fill()

    def teardown(self):
        if self._sub:
            self.spectrum.unsubscribe(self._sub)
            self._sub = None
        if self._media_id:
            self.media.release(self._media_id)
            self._media_id = None
        super().teardown()
