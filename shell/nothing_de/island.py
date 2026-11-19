"""The island: a black pill under the top bar that shows what is playing.

Small it shows the cover, the title and a few bars dancing to the music; under the
pointer (and for a moment when the track changes) it grows into a card with two tabs:
"Musik" (cover, controls, progress, shuffle, volume, repeat) and "Geräte" (the audio
output to play through). It is hidden while nothing plays (config "island.enabled").
At the start of a session it writes a handwritten "hallo" (greet, after the splash).
"""
import datetime
import math

from gi.repository import GLib, Gtk, Pango

from . import audio, handwriting, layer, system
from .apps import spawn
from .media import fmt_time, get_media
from .theme import hex_to_rgb
from .widgets_audio import _cover, set_cover

AUTO_OPEN_MS = 3500
GREET_WRITE = 1.9      # s to write the word
GREET_MS = 5200        # the greeting stays this long
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _btn(icon, cb, css="n-island-btn"):
    b = Gtk.Button(icon_name=icon)
    b.add_css_class(css)
    b.connect("clicked", lambda *_: cb())
    return b


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
        self._greeting = False
        self._greet_t0 = 0
        self._updating = False

        pill = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pill.add_css_class("n-island")
        self.pill = pill

        # ---- the small pill: what plays, or the greeting
        self.head = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                              transition_duration=250, vhomogeneous=False, hhomogeneous=False)
        small = Gtk.Box(spacing=10)
        self.small_cover = _cover(24)
        small.append(self.small_cover)
        self.small_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                     max_width_chars=26, hexpand=True)
        small.append(self.small_title)
        self.bars = Gtk.DrawingArea(content_width=26, content_height=16, valign=Gtk.Align.CENTER)
        self.bars.set_draw_func(self._draw_bars)
        small.append(self.bars)
        self.head.add_named(small, "music")

        greet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        greet.set_margin_start(10)
        greet.set_margin_end(4)
        self.hand = Gtk.DrawingArea(content_width=150, content_height=44,
                                    halign=Gtk.Align.CENTER)
        self.hand.set_draw_func(self._draw_hand)
        greet.append(self.hand)
        self.greet_sub = Gtk.Label(label="Willkommen bei Nothing")
        self.greet_sub.add_css_class("n-island-sub")
        greet.append(self.greet_sub)
        self.head.add_named(greet, "greet")
        pill.append(self.head)

        # ---- the open card
        big = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        big.set_margin_top(8)
        tabs = Gtk.Box(spacing=14)
        self.tab_btns = {}
        for key, label in (("music", "Musik"), ("devices", "Geräte")):
            b = Gtk.Button(label=label)
            b.add_css_class("n-island-tab")
            b.connect("clicked", lambda _b, k=key: self._show_tab(k))
            tabs.append(b)
            self.tab_btns[key] = b
        tabs.append(Gtk.Box(hexpand=True))
        tabs.append(_btn("view-app-grid-symbolic", self._open_visualizer, "n-island-small"))
        big.append(tabs)

        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=180, vhomogeneous=False)
        self.pages.add_named(self._music_page(), "music")
        self.devices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.pages.add_named(self.devices, "devices")
        big.append(self.pages)

        foot = Gtk.Box(spacing=8)
        self.date = Gtk.Label(xalign=0, hexpand=True)
        self.date.add_css_class("n-island-foot")
        foot.append(self.date)
        dots = Gtk.Label(label="• • •")
        dots.add_css_class("n-island-foot")
        foot.append(dots)
        self.player_lbl = Gtk.Label(xalign=1, hexpand=True)
        self.player_lbl.add_css_class("n-island-foot")
        foot.append(self.player_lbl)
        big.append(foot)
        self._show_tab("music")

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

    def _music_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        row = Gtk.Box(spacing=14)
        self.cover = _cover(72)
        self.cover.add_css_class("n-island-art")
        row.append(self.cover)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True,
                        valign=Gtk.Align.CENTER)
        self.source = Gtk.Label(xalign=0)
        self.source.add_css_class("n-island-foot")
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        self.title.add_css_class("n-strong")
        self.artist = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        self.artist.add_css_class("n-island-muted")
        for w in (self.source, self.title, self.artist):
            right.append(w)
        ctl = Gtk.Box(spacing=10, margin_top=6)
        ctl.append(_btn("media-skip-backward-symbolic", lambda: self.media.call("Previous")))
        self.play_btn = _btn("media-playback-start-symbolic",
                             lambda: self.media.call("PlayPause"), "n-island-play")
        ctl.append(self.play_btn)
        ctl.append(_btn("media-skip-forward-symbolic", lambda: self.media.call("Next")))
        right.append(ctl)
        row.append(right)
        page.append(row)

        prog = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.progress = Gtk.DrawingArea(content_height=10, hexpand=True)
        self.progress.set_draw_func(self._draw_progress)
        seek = Gtk.GestureClick()
        seek.connect("released", lambda _g, _n, x, _y:
                     self.media.seek(x / max(1, self.progress.get_width())))
        self.progress.add_controller(seek)
        prog.append(self.progress)
        times = Gtk.Box()
        self.pos = Gtk.Label(xalign=0, hexpand=True)
        self.pos.add_css_class("n-island-foot")
        self.len = Gtk.Label(xalign=1)
        self.len.add_css_class("n-island-foot")
        times.append(self.pos)
        times.append(self.len)
        prog.append(times)
        page.append(prog)

        vol = Gtk.Box(spacing=6)
        self.shuffle_btn = _btn("media-playlist-shuffle-symbolic", self.media.toggle_shuffle,
                                "n-island-small")
        self.shuffle_btn.set_tooltip_text("Zufällige Wiedergabe")
        vol.append(self.shuffle_btn)
        self.vol_icon = _btn("audio-volume-high-symbolic", self._toggle_mute, "n-island-small")
        vol.append(self.vol_icon)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        self.volume.set_draw_value(False)
        self.volume.set_hexpand(True)
        self.volume.set_focusable(False)
        self.volume.add_css_class("n-island-volume")
        self.volume.connect("value-changed", lambda s: None if self._updating
                            else system.set_volume(s.get_value()))
        vol.append(self.volume)
        self.loop_btn = _btn("media-playlist-repeat-symbolic", self.media.cycle_loop,
                             "n-island-small")
        self.loop_btn.set_tooltip_text("Wiederholen")
        vol.append(self.loop_btn)
        page.append(vol)
        return page

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
        music = bool(self.cfg.get("island.enabled", True)) and m.available and bool(m.title)
        wanted = music or self._greeting
        if wanted != self.get_visible():
            self.set_visible(wanted)
        self._listen(music and m.playing)
        if not music:
            return
        self.small_title.set_label(m.title)
        self.title.set_label(m.title)
        self.artist.set_label(m.artist)
        self.source.set_label(m.player.upper())
        self.player_lbl.set_label(m.player)
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if m.playing
                                    else "media-playback-start-symbolic")
        self.len.set_label(fmt_time(m.length))
        self.shuffle_btn.set_sensitive(m.shuffle is not None)
        self._mark(self.shuffle_btn, bool(m.shuffle))
        self.loop_btn.set_sensitive(m.loop is not None)
        self._mark(self.loop_btn, m.loop in ("Track", "Playlist"))
        self.loop_btn.set_icon_name("media-playlist-repeat-song-symbolic" if m.loop == "Track"
                                    else "media-playlist-repeat-symbolic")
        self._tick()
        if m.title != self._title:
            first = self._title is None
            self._title = m.title
            if not first and m.playing and not self._greeting:
                # a new track: show it for a moment
                self._open(auto=True)

    @staticmethod
    def _mark(btn, on):
        if on:
            btn.add_css_class("on")
        else:
            btn.remove_css_class("on")

    def _tick(self):
        if self.get_visible():
            self.pos.set_label(fmt_time(self.media.position))
            self.progress.queue_draw()
            if not self.media.playing:
                self.bars.queue_draw()
        return True

    # ----------------------------------------------------------- greeting
    def greet(self):
        """Write "hallo" into the pill (after the splash at the start of a session)."""
        if not self.cfg.get("splash.greeting", True):
            return
        name = GLib.get_real_name() or ""
        first = name.split()[0] if name and name != "Unknown" else ""
        self.greet_sub.set_label(f"Willkommen, {first}" if first else "Willkommen bei Nothing")
        self._greeting = True
        self._greet_t0 = GLib.get_monotonic_time()
        self.head.set_visible_child_name("greet")
        self.pill.add_css_class("greet")
        self.update()
        self.hand.add_tick_callback(self._greet_tick)
        GLib.timeout_add(GREET_MS, self._end_greeting)

    def _greet_tick(self, _w, _clock):
        self.hand.queue_draw()
        return self._greeting and \
            (GLib.get_monotonic_time() - self._greet_t0) / 1e6 < GREET_WRITE + 0.5

    def _end_greeting(self):
        self._greeting = False
        self.pill.remove_css_class("greet")
        self.head.set_visible_child_name("music")
        self._shrink()
        self.update()
        return False

    def _draw_hand(self, _a, cr, w, h):
        t = (GLib.get_monotonic_time() - self._greet_t0) / 1e6
        frac = handwriting.ease(t / GREET_WRITE)
        tip = handwriting.draw(cr, 2, 2, w - 4, h - 4, frac, (1, 1, 1, 1))
        if tip and frac < 1:
            r, g, b, _ = self._accent()
            cr.set_source_rgba(r, g, b, 0.9)
            cr.arc(tip[0], tip[1], 2.6, 0, 2 * math.pi)
            cr.fill()

    # ------------------------------------------------------------ devices
    def _show_tab(self, key):
        self.pages.set_visible_child_name(key)
        for k, b in self.tab_btns.items():
            self._mark(b, k == key)
        if key == "devices":
            system.get_sinks(self._fill_devices)

    def _fill_devices(self, sinks):
        while (child := self.devices.get_first_child()) is not None:
            self.devices.remove(child)
        eq = getattr(self.shell, "equalizer", None)
        through_eq = eq.previous_sink if eq is not None and eq.enabled else None
        if not sinks:
            lbl = Gtk.Label(label="Keine Audio-Ausgabe gefunden", xalign=0)
            lbl.add_css_class("n-island-muted")
            self.devices.append(lbl)
            return
        for name, desc, default in sinks:
            active = name == through_eq if through_eq else default
            row = Gtk.Box(spacing=10)
            icon = "audio-headphones-symbolic" if "head" in (name + desc).lower() or \
                "bluez" in name else "audio-speakers-symbolic"
            row.append(Gtk.Image(icon_name=icon))
            lbl = Gtk.Label(label=desc, xalign=0, hexpand=True,
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=30)
            row.append(lbl)
            if active:
                row.append(Gtk.Image(icon_name="object-select-symbolic"))
            b = Gtk.Button(child=row)
            b.add_css_class("n-island-device")
            self._mark(b, active)
            b.connect("clicked", lambda _b, n=name: self._pick_device(n))
            self.devices.append(b)

    def _pick_device(self, name):
        eq = getattr(self.shell, "equalizer", None)
        refresh = lambda: system.get_sinks(self._fill_devices)  # noqa: E731
        if eq is not None and eq.set_output(name):
            GLib.timeout_add(600, lambda: (refresh(), False)[1])
        else:
            system.set_default_sink(name, refresh)

    # ------------------------------------------------------------- volume
    def _refresh_volume(self):
        def got(v, muted):
            self._updating = True
            self.volume.set_value(min(1.0, v or 0))
            self.vol_icon.set_icon_name(system.volume_icon(v, muted))
            self._updating = False
        system.get_volume(got)

    def _toggle_mute(self):
        system.toggle_mute()
        GLib.timeout_add(200, lambda: (self._refresh_volume(), False)[1])

    def _open_visualizer(self):
        spawn(["nothing-visualizer"])

    # ------------------------------------------------------------- open/close
    def _set_hover(self, on):
        self._hover = on
        if self._greeting:
            return
        if on:
            self._open()
        elif self._close_id is None:
            self._close_id = GLib.timeout_add(350, self._close)

    def _open(self, auto=False):
        if self._close_id is not None:
            GLib.source_remove(self._close_id)
            self._close_id = None
        now = datetime.datetime.now()
        self.date.set_label(f"{WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}")
        self._refresh_volume()
        if self.pages.get_visible_child_name() == "devices":
            system.get_sinks(self._fill_devices)
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
