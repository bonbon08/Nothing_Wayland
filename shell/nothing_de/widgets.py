"""Desktop widgets in Nothing OS style."""
import datetime
import glob
import json
import math
import os
import threading
import urllib.parse
import urllib.request

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import dotmatrix
from .theme import hex_to_rgb

SIZES = {"small": (172, 172), "wide": (360, 172), "large": (360, 360)}

WEEKDAYS = ["MONTAG", "DIENSTAG", "MITTWOCH", "DONNERSTAG", "FREITAG", "SAMSTAG", "SONNTAG"]
MONTHS = ["JANUAR", "FEBRUAR", "MÄRZ", "APRIL", "MAI", "JUNI", "JULI", "AUGUST",
          "SEPTEMBER", "OKTOBER", "NOVEMBER", "DEZEMBER"]


def caps(text, cls="n-widget-title"):
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.add_css_class(cls)
    return lbl


def accent_rgba(cfg):
    r, g, b = hex_to_rgb(cfg.get("accent"))
    return (r, g, b, 1.0)


class DesktopWidget(Gtk.Box):
    TYPE = ""
    NAME = ""
    SIZE = "small"
    REFRESH = 0  # seconds, 0 = none

    def __init__(self, shell, spec):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.shell = shell
        self.cfg = shell.cfg
        self.spec = spec
        self.add_css_class("n-card")
        self.add_css_class("n-root")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        w, h = SIZES[self.SIZE]
        self.set_size_request(w, h)
        self._timer = None
        self._cfg_handler = self.cfg.connect("changed", lambda *_: self.on_config())
        self.build()
        self.refresh()
        if self.REFRESH:
            self._timer = GLib.timeout_add_seconds(self.REFRESH, self._tick)

    def _tick(self):
        self.refresh()
        return True

    def build(self):
        pass

    def refresh(self):
        pass

    def on_config(self):
        self.refresh()

    def teardown(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        if self._cfg_handler:
            self.cfg.disconnect(self._cfg_handler)
            self._cfg_handler = None


class ClockWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "clock", "Uhr (Dot-Matrix)", "wide", 1

    def build(self):
        self.set_margin_top(0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(22)
        box.set_margin_end(22)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_vexpand(True)
        head = Gtk.Box()
        self.day = caps("")
        self.day.set_hexpand(True)
        dot = Gtk.DrawingArea(content_width=10, content_height=10)
        dot.set_draw_func(self._draw_dot)
        head.append(self.day)
        head.append(dot)
        self.time = dotmatrix.DotLabel("00:00", pitch=10)
        self.time.set_halign(Gtk.Align.START)
        self.time.set_vexpand(True)
        self.time.set_valign(Gtk.Align.CENTER)
        self.date = caps("")
        box.append(head)
        box.append(self.time)
        box.append(self.date)
        self.append(box)

    def _draw_dot(self, _a, cr, w, h):
        cr.set_source_rgba(*accent_rgba(self.cfg))
        cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
        cr.fill()

    def refresh(self):
        now = datetime.datetime.now()
        h24 = self.cfg.get("bar.clock_24h", True)
        hour = now.hour if h24 else (now.hour % 12 or 12)
        self.time.set_text(f"{hour:02d}:{now.minute:02d}")
        self.day.set_label(WEEKDAYS[now.weekday()])
        self.date.set_label(f"{now.day:02d} {MONTHS[now.month - 1]} {now.year}")


class AnalogClockWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "analog", "Analoguhr", "small", 1

    def build(self):
        self.area = Gtk.DrawingArea()
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)

    def refresh(self):
        self.area.queue_draw()

    def _draw(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 18
        now = datetime.datetime.now()
        # hour markers as dots
        for i in range(60):
            a = i / 60 * 2 * math.pi
            big = i % 5 == 0
            cr.set_source_rgba(fg[0], fg[1], fg[2], 0.9 if big else 0.18)
            cr.arc(cx + math.sin(a) * r, cy - math.cos(a) * r, 2.2 if big else 1.2, 0, 2 * math.pi)
            cr.fill()
        cr.set_line_cap(1)  # round
        ha = ((now.hour % 12) + now.minute / 60) / 12 * 2 * math.pi
        ma = (now.minute + now.second / 60) / 60 * 2 * math.pi
        sa = now.second / 60 * 2 * math.pi
        cr.set_source_rgba(*fg)
        cr.set_line_width(7)
        cr.move_to(cx, cy)
        cr.line_to(cx + math.sin(ha) * r * 0.5, cy - math.cos(ha) * r * 0.5)
        cr.stroke()
        cr.set_line_width(4)
        cr.move_to(cx, cy)
        cr.line_to(cx + math.sin(ma) * r * 0.78, cy - math.cos(ma) * r * 0.78)
        cr.stroke()
        cr.set_source_rgba(*acc)
        cr.arc(cx + math.sin(sa) * (r - 10), cy - math.cos(sa) * (r - 10), 4, 0, 2 * math.pi)
        cr.fill()
        cr.arc(cx, cy, 4.5, 0, 2 * math.pi)
        cr.fill()


WMO = {
    0: ("Klar", "weather-clear"), 1: ("Überwiegend klar", "weather-few-clouds"),
    2: ("Teilweise bewölkt", "weather-few-clouds"), 3: ("Bedeckt", "weather-overcast"),
    45: ("Nebel", "weather-fog"), 48: ("Raureif-Nebel", "weather-fog"),
    51: ("Nieselregen", "weather-showers-scattered"), 53: ("Nieselregen", "weather-showers-scattered"),
    55: ("Starker Niesel", "weather-showers"), 56: ("Gefrierender Niesel", "weather-freezing-rain"),
    57: ("Gefrierender Niesel", "weather-freezing-rain"), 61: ("Leichter Regen", "weather-showers-scattered"),
    63: ("Regen", "weather-showers"), 65: ("Starkregen", "weather-showers"),
    66: ("Eisregen", "weather-freezing-rain"), 67: ("Eisregen", "weather-freezing-rain"),
    71: ("Leichter Schnee", "weather-snow"), 73: ("Schnee", "weather-snow"),
    75: ("Starker Schnee", "weather-snow"), 77: ("Schneegriesel", "weather-snow"),
    80: ("Schauer", "weather-showers-scattered"), 81: ("Schauer", "weather-showers"),
    82: ("Starke Schauer", "weather-showers"), 85: ("Schneeschauer", "weather-snow"),
    86: ("Schneeschauer", "weather-snow"), 95: ("Gewitter", "weather-storm"),
    96: ("Gewitter, Hagel", "weather-storm"), 99: ("Gewitter, Hagel", "weather-storm"),
}


def fetch_json(url, callback):
    """GET JSON in a worker thread, deliver result (or None) on the main loop."""
    def work():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nothing-de/0.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except (OSError, ValueError):
            data = None
        GLib.idle_add(callback, data)
    threading.Thread(target=work, daemon=True).start()


class WeatherWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "weather", "Wetter", "small", 900

    def build(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        box.set_vexpand(True)
        head = Gtk.Box(spacing=6)
        self.city = caps("")
        self.city.set_hexpand(True)
        self.city.set_ellipsize(Pango.EllipsizeMode.END)
        self.icon = Gtk.Image(pixel_size=22)
        head.append(self.city)
        head.append(self.icon)
        self.temp = dotmatrix.DotLabel("--°", pitch=8)
        self.temp.set_halign(Gtk.Align.START)
        self.temp.set_vexpand(True)
        self.temp.set_valign(Gtk.Align.CENTER)
        self.cond = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.range = caps("")
        box.append(head)
        box.append(self.temp)
        box.append(self.cond)
        box.append(self.range)
        self.append(box)
        self._loc = None

    def on_config(self):
        loc = (self.cfg.get("weather.lat"), self.cfg.get("weather.lon"))
        if loc != self._loc:
            self.refresh()

    def refresh(self):
        lat, lon = self.cfg.get("weather.lat"), self.cfg.get("weather.lon")
        self._loc = (lat, lon)
        self.city.set_label((self.cfg.get("weather.city") or "").upper())
        if lat is None or lon is None:
            self.cond.set_label("Ort in Einstellungen festlegen")
            return
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "current": "temperature_2m,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1})
        fetch_json("https://api.open-meteo.com/v1/forecast?" + q, self._on_data)

    def _on_data(self, data):
        if not data or "current" not in data:
            self.cond.set_label("Offline")
            return False
        cur = data["current"]
        code = int(cur.get("weather_code", 0))
        text, icon = WMO.get(code, ("—", "weather-severe-alert"))
        if not cur.get("is_day", 1) and icon in ("weather-clear", "weather-few-clouds"):
            icon += "-night"
        self.temp.set_text(f"{round(cur.get('temperature_2m', 0))}°")
        self.cond.set_label(text)
        self.icon.set_from_icon_name(icon + "-symbolic")
        d = data.get("daily", {})
        try:
            self.range.set_label(f"H {round(d['temperature_2m_max'][0])}°  T {round(d['temperature_2m_min'][0])}°")
        except (KeyError, IndexError, TypeError):
            self.range.set_label("")
        return False


def read_battery():
    bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not bats:
        return None, None
    try:
        with open(os.path.join(bats[0], "capacity")) as f:
            cap = int(f.read().strip())
        with open(os.path.join(bats[0], "status")) as f:
            status = f.read().strip()
    except (OSError, ValueError):
        return None, None
    return cap, status


class BatteryWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "battery", "Akku", "small", 20

    def build(self):
        self.area = Gtk.DrawingArea()
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        self.append(self.area)
        self.cap, self.status = None, None

    def refresh(self):
        self.cap, self.status = read_battery()
        self.area.queue_draw()

    def _draw(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        cx, cy = w / 2, h / 2 + 4
        r = min(w, h) / 2 - 28
        # dotted ring, lit up to the charge level
        n = 40
        level = (self.cap or 0) / 100 if self.cap is not None else 1
        charging = self.status in ("Charging", "Full")
        for i in range(n):
            a = i / n * 2 * math.pi
            on = i / n < level
            col = (acc if (charging or (self.cap or 100) <= 20) else fg) if on else (fg[0], fg[1], fg[2], 0.15)
            cr.set_source_rgba(*col)
            cr.arc(cx + math.sin(a) * r, cy - math.cos(a) * r, 3, 0, 2 * math.pi)
            cr.fill()
        text = f"{self.cap}" if self.cap is not None else "AC"
        pitch = 6
        tw = dotmatrix.columns(text) * pitch
        dotmatrix.draw(cr, text, cx - tw / 2, cy - 3.5 * pitch, pitch, fg)
        label = "LÄDT" if self.status == "Charging" else ("AKKU" if self.cap is not None else "NETZ")
        cr.set_source_rgba(fg[0], fg[1], fg[2], 0.55)
        cr.select_font_face("monospace")
        cr.set_font_size(10)
        cr.move_to(18, 28)
        cr.show_text(label)


class SystemWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "system", "System", "small", 2

    def build(self):
        self.prev = None
        self.cpu = 0.0
        self.mem = 0.0
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        box.append(caps("SYSTEM"))
        self.area = Gtk.DrawingArea()
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        box.append(self.area)
        self.append(box)

    def refresh(self):
        try:
            with open("/proc/stat") as f:
                vals = [int(v) for v in f.readline().split()[1:]]
            idle, total = vals[3] + vals[4], sum(vals)
            if self.prev:
                dt, di = total - self.prev[1], idle - self.prev[0]
                self.cpu = 0 if dt <= 0 else (1 - di / dt)
            self.prev = (idle, total)
            mi = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mi[k] = int(v.split()[0])
            self.mem = 1 - mi.get("MemAvailable", 0) / max(1, mi.get("MemTotal", 1))
        except (OSError, ValueError, IndexError):
            pass
        self.area.queue_draw()

    def _draw(self, area, cr, w, h):
        fg = dotmatrix.rgba_tuple(area.get_color())
        acc = accent_rgba(self.cfg)
        rows = [("CPU", self.cpu), ("RAM", self.mem)]
        cols = 12
        pitch = (w - 4) / cols
        y = 4
        for name, val in rows:
            cr.set_source_rgba(fg[0], fg[1], fg[2], 0.55)
            cr.select_font_face("monospace")
            cr.set_font_size(10)
            cr.move_to(0, y + 10)
            cr.show_text(f"{name}  {round(val * 100)}%")
            y += 18
            lit = round(val * cols)
            for i in range(cols):
                on = i < lit
                col = (acc if val > 0.85 else fg) if on else (fg[0], fg[1], fg[2], 0.15)
                cr.set_source_rgba(*col)
                for j in range(2):
                    cr.arc(i * pitch + pitch / 2 + 2, y + j * pitch * 0.9 + pitch / 2,
                           pitch * 0.36, 0, 2 * math.pi)
                    cr.fill()
            y += pitch * 2 + 10


class CalendarWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "calendar", "Kalender", "wide", 60

    def build(self):
        outer = Gtk.Box(spacing=18)
        for m in ("start", "end", "top", "bottom"):
            getattr(outer, f"set_margin_{m}")(18)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.wd = caps("")
        self.big = dotmatrix.DotLabel("00", pitch=9)
        self.big.set_halign(Gtk.Align.START)
        self.big.set_vexpand(True)
        self.big.set_valign(Gtk.Align.CENTER)
        self.mon = caps("")
        left.append(self.wd)
        left.append(self.big)
        left.append(self.mon)
        self.grid = Gtk.Grid(column_spacing=1, row_spacing=0)
        self.grid.set_hexpand(True)
        self.grid.set_halign(Gtk.Align.END)
        self.grid.set_valign(Gtk.Align.CENTER)
        outer.append(left)
        outer.append(self.grid)
        self.append(outer)
        self._day = None

    def refresh(self):
        today = datetime.date.today()
        if today == self._day:
            return
        self._day = today
        self.wd.set_label(WEEKDAYS[today.weekday()])
        self.big.set_text(f"{today.day:02d}")
        self.mon.set_label(MONTHS[today.month - 1])
        while (child := self.grid.get_first_child()) is not None:
            self.grid.remove(child)
        for i, d in enumerate("MDMDFSS"):
            lbl = Gtk.Label(label=d)
            lbl.add_css_class("n-cal-day")
            lbl.add_css_class("n-cal-head")
            self.grid.attach(lbl, i, 0, 1, 1)
        first = today.replace(day=1)
        start = first - datetime.timedelta(days=first.weekday())
        for i in range(35 if (first.weekday() + 31) <= 35 else 42):
            day = start + datetime.timedelta(days=i)
            lbl = Gtk.Label(label=str(day.day))
            lbl.add_css_class("n-cal-day")
            if day == today:
                lbl.add_css_class("today")
            elif day.month != today.month:
                lbl.add_css_class("other")
            self.grid.attach(lbl, i % 7, 1 + i // 7, 1, 1)


class NotesWidget(DesktopWidget):
    TYPE, NAME, SIZE = "notes", "Notizen", "large"

    def build(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        head = Gtk.Box()
        t = caps("NOTIZEN")
        t.set_hexpand(True)
        head.append(t)
        box.append(head)
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.add_css_class("n-notes")
        self.view.get_buffer().set_text(self.cfg.get("notes") or "")
        self.view.get_buffer().connect("changed", self._changed)
        scroll = Gtk.ScrolledWindow(child=self.view, vexpand=True)
        box.append(scroll)
        self.append(box)
        self._save_id = None

    def _changed(self, buf):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(800, self._save)

    def _save(self):
        self._save_id = None
        buf = self.view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.cfg.set("notes", text, notify=False)
        return False

    def on_config(self):
        pass


class MediaWidget(DesktopWidget):
    TYPE, NAME, SIZE, REFRESH = "media", "Medien", "wide", 2

    def build(self):
        self.proxy = None
        self.player_name = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m in ("start", "end", "top", "bottom"):
            getattr(box, f"set_margin_{m}")(18)
        self.src = caps("MEDIEN")
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("n-big")
        self.title.set_vexpand(True)
        self.title.set_valign(Gtk.Align.CENTER)
        self.artist = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.artist.add_css_class("n-muted")
        ctl = Gtk.Box(spacing=8)
        ctl.set_halign(Gtk.Align.END)
        for icon, method in (("media-skip-backward-symbolic", "Previous"),
                             ("media-playback-start-symbolic", "PlayPause"),
                             ("media-skip-forward-symbolic", "Next")):
            b = Gtk.Button(icon_name=icon)
            b.add_css_class("n-round")
            b.connect("clicked", lambda _b, m=method: self._call(m))
            ctl.append(b)
            if method == "PlayPause":
                self.play_btn = b
        bottom = Gtk.Box()
        bottom.append(self.artist)
        self.artist.set_hexpand(True)
        bottom.append(ctl)
        box.append(self.src)
        box.append(self.title)
        box.append(bottom)
        self.append(box)

    def _call(self, method):
        if self.proxy:
            self.proxy.call(method, None, Gio.DBusCallFlags.NONE, -1, None, None)

    def refresh(self):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        try:
            names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                  "org.freedesktop.DBus", "ListNames", None, None,
                                  Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
        except GLib.Error:
            names = []
        players = sorted(n for n in names if n.startswith("org.mpris.MediaPlayer2."))
        if not players:
            self.proxy = None
            self.player_name = None
            self.title.set_label("Keine Wiedergabe")
            self.artist.set_label("")
            self.src.set_label("MEDIEN")
            return
        if self.player_name not in players:
            self.player_name = players[0]
            self.proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None, self.player_name,
                "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", None)
        meta = self.proxy.get_cached_property("Metadata")
        meta = meta.unpack() if meta else {}
        status = self.proxy.get_cached_property("PlaybackStatus")
        status = status.unpack() if status else ""
        self.title.set_label(meta.get("xesam:title") or "Unbekannt")
        artists = meta.get("xesam:artist") or []
        self.artist.set_label(", ".join(artists) if isinstance(artists, list) else str(artists))
        self.src.set_label(self.player_name.split(".")[3].upper())
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if status == "Playing"
                                    else "media-playback-start-symbolic")


class PhotoWidget(DesktopWidget):
    TYPE, NAME, SIZE = "photo", "Foto", "large"

    def build(self):
        self.pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, vexpand=True, hexpand=True)
        self.hint = Gtk.Label(label="Foto in den Einstellungen\nunter Widgets wählen",
                              justify=Gtk.Justification.CENTER, vexpand=True)
        self.hint.add_css_class("n-muted")
        self.append(self.pic)
        self.append(self.hint)
        self._path = None

    def refresh(self):
        path = self.cfg.get("photo") or ""
        if path == self._path:
            return
        self._path = path
        ok = bool(path) and os.path.exists(path)
        self.pic.set_visible(ok)
        self.hint.set_visible(not ok)
        if ok:
            self.pic.set_filename(path)


WIDGET_TYPES = {cls.TYPE: cls for cls in (
    ClockWidget, AnalogClockWidget, WeatherWidget, BatteryWidget, SystemWidget,
    CalendarWidget, NotesWidget, MediaWidget, PhotoWidget)}
