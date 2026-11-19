"""The island: a black pill under the top bar that shows what is playing.

Small it shows the cover, the title and a few bars dancing to the music; under the
pointer (and for a moment when the track changes) it grows into a card with the progress
and the controls. It is hidden while nothing plays (config "island.enabled").
"""
import math

from gi.repository import GLib, Gtk, Pango

from . import audio, layer
from .media import fmt_time, get_media
from .theme import hex_to_rgb
from .widgets_audio import _cover, set_cover

AUTO_OPEN_MS = 3500


class Island(Gtk.ApplicationWindow):
    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        self.cfg = shell.cfg
        # exclusive zone 0: placed below the bar's zone instead of over it
        layer.setup(self, layer="top", anchors=("top",), margins={"top": 6},
                    exclusive=0, namespace="nothing-island", monitor=monitor)
        self.add_css_class("n-root")
        self.media = get_media()
        self.levels = []
        self._sub = None
        self._close_id = None
        self._hover = False
        self._title = None

        pill = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pill.add_css_class("n-island")
        self.pill = pill

        small = Gtk.Box(spacing=10)
        self.small_cover = _cover(24)
        small.append(self.small_cover)
        self.small_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                     max_width_chars=26, hexpand=True)
        small.append(self.small_title)
        self.bars = Gtk.DrawingArea(content_width=26, content_height=16, valign=Gtk.Align.CENTER)
        self.bars.set_draw_func(self._draw_bars)
        small.append(self.bars)
        pill.append(small)

        big = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        big.set_margin_top(12)
        row = Gtk.Box(spacing=12)
        self.cover = _cover(54)
        row.append(self.cover)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True,
                       valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        self.title.add_css_class("n-strong")
        self.artist = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        self.artist.add_css_class("n-island-muted")
        self.source = Gtk.Label(xalign=0)
        self.source.add_css_class("n-caps")
        for w in (self.source, self.title, self.artist):
            info.append(w)
        row.append(info)
        big.append(row)
        prog = Gtk.Box(spacing=8)
        self.pos = Gtk.Label()
        self.pos.add_css_class("n-caps")
        self.len = Gtk.Label()
        self.len.add_css_class("n-caps")
        self.progress = Gtk.DrawingArea(content_height=10, hexpand=True, valign=Gtk.Align.CENTER)
        self.progress.set_draw_func(self._draw_progress)
        seek = Gtk.GestureClick()
        seek.connect("released", lambda _g, _n, x, _y:
                     self.media.seek(x / max(1, self.progress.get_width())))
        self.progress.add_controller(seek)
        prog.append(self.pos)
        prog.append(self.progress)
        prog.append(self.len)
        big.append(prog)
        ctl = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER)
        for icon, method in (("media-skip-backward-symbolic", "Previous"),
                             ("media-playback-start-symbolic", "PlayPause"),
                             ("media-skip-forward-symbolic", "Next")):
            b = Gtk.Button(icon_name=icon)
            b.add_css_class("n-island-btn")
            b.connect("clicked", lambda _b, m=method: self.media.call(m))
            ctl.append(b)
            if method == "PlayPause":
                self.play_btn = b
        big.append(ctl)
        self.revealer = Gtk.Revealer(child=big, reveal_child=False,
                                     transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=220)
        pill.append(self.revealer)
        # a window keeps its size when the content shrinks: back to the small pill once
        # the card has folded up
        self.revealer.connect("notify::child-revealed", lambda r, _p:
                              r.get_child_revealed() or self._shrink())
        self.set_child(pill)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_hover(True))
        motion.connect("leave", lambda *_: self._set_hover(False))
        pill.add_controller(motion)

        self._media_id = self.media.listen(lambda *_: self.update())
        self._art_id = self.media.connect("art", lambda *_: self._art())
        self._cfg_id = self.cfg.connect("changed", lambda *_: self.update())
        self._timer = GLib.timeout_add(500, self._tick)
        self.connect("destroy", lambda *_: self._shutdown())
        self._art()
        self.update()

    # ------------------------------------------------------------------ state
    def _shutdown(self):
        if self._media_id:
            self.media.release(self._media_id)
            self.media.disconnect(self._art_id)
            self.cfg.disconnect(self._cfg_id)
            self._media_id = None
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        self._listen(False)

    def _listen(self, on):
        spectrum = audio.get_spectrum()
        if on and self._sub is None:
            self._sub = spectrum.subscribe(self._on_levels)
        elif not on and self._sub is not None:
            spectrum.unsubscribe(self._sub)
            self._sub = None
            self.levels = []

    def _on_levels(self, levels):
        self.levels = levels
        self.bars.queue_draw()

    def _art(self):
        set_cover(self.small_cover, self.media)
        set_cover(self.cover, self.media)

    def update(self):
        m = self.media
        wanted = bool(self.cfg.get("island.enabled", True)) and m.available and bool(m.title)
        if wanted != self.get_visible():
            self.set_visible(wanted)
        self._listen(wanted and m.playing)
        if not wanted:
            return
        self.small_title.set_label(m.title)
        self.title.set_label(m.title)
        self.artist.set_label(m.artist)
        self.source.set_label(m.player.upper())
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if m.playing
                                    else "media-playback-start-symbolic")
        self.len.set_label(fmt_time(m.length))
        self._tick()
        if m.title != self._title:
            first = self._title is None
            self._title = m.title
            if not first and m.playing:
                # a new track: show it for a moment
                self._open(auto=True)

    def _tick(self):
        if self.get_visible():
            self.pos.set_label(fmt_time(self.media.position))
            self.progress.queue_draw()
            if not self.media.playing:
                self.bars.queue_draw()
        return True

    # ------------------------------------------------------------- open/close
    def _set_hover(self, on):
        self._hover = on
        if on:
            self._open()
        elif self._close_id is None:
            self._close_id = GLib.timeout_add(350, self._close)

    def _open(self, auto=False):
        if self._close_id is not None:
            GLib.source_remove(self._close_id)
            self._close_id = None
        self.pill.add_css_class("open")
        self.revealer.set_reveal_child(True)
        if auto:
            self._close_id = GLib.timeout_add(AUTO_OPEN_MS, self._close)

    def _shrink(self):
        self.set_default_size(1, 1)
        # the pill's width eases back by CSS transition, follow it for a moment
        for ms in (120, 240):
            GLib.timeout_add(ms, lambda: (self.set_default_size(1, 1), False)[1])

    def _close(self):
        self._close_id = None
        if self._hover:
            return False
        self.revealer.set_reveal_child(False)
        self.pill.remove_css_class("open")
        return False

    # ---------------------------------------------------------------- drawing
    def _accent(self):
        r, g, b = hex_to_rgb(self.cfg.get("accent"))
        return (r, g, b, 1.0)

    def _draw_bars(self, _a, cr, w, h):
        n = 4
        vals = audio.resample(self.levels, n) if self.levels else [0.12] * n
        bw = 3.4
        gap = (w - n * bw) / (n - 1)
        cr.set_source_rgba(*self._accent())
        for i, v in enumerate(vals):
            bh = max(bw, min(1.0, v * 1.4) * h)
            x = i * (bw + gap)
            y = (h - bh) / 2
            cr.new_sub_path()
            cr.arc(x + bw / 2, y + bw / 2, bw / 2, math.pi, 0)
            cr.arc(x + bw / 2, y + bh - bw / 2, bw / 2, 0, math.pi)
            cr.close_path()
            cr.fill()

    def _draw_progress(self, _a, cr, w, h):
        y = h / 2
        cr.set_line_cap(1)
        cr.set_line_width(3)
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.move_to(2, y)
        cr.line_to(w - 2, y)
        cr.stroke()
        x = 2 + (w - 4) * self.media.progress
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.move_to(2, y)
        cr.line_to(x, y)
        cr.stroke()
        cr.set_source_rgba(*self._accent())
        cr.arc(x, y, 4, 0, 2 * math.pi)
        cr.fill()
