"""What is playing: one shared view of the MPRIS players for the media widgets, the
equalizer card, the cassette and the island.

`get_media()` returns the shared `Media` object; it polls the session bus once a second
while anyone listens (`listen(cb)`), and in between the position runs on
with the clock, so progress bars move smoothly without asking the player all the time.
"""
import threading
import time
import urllib.parse
import urllib.request

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

PLAYER_PREFIX = "org.mpris.MediaPlayer2."


def player_label(bus_name):
    """"org.mpris.MediaPlayer2.spotify" -> "Spotify"; instance suffixes are dropped."""
    short = bus_name.removeprefix(PLAYER_PREFIX)
    short = short.split(".")[0]
    return short[:1].upper() + short[1:]


def fmt_time(us):
    """Microseconds -> "m:ss" (or "h:mm:ss")."""
    s = max(0, int((us or 0) // 1_000_000))
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _load_art(url, size):
    """Cover art (file:// or http(s)://) as a square texture; None if it cannot be read."""
    try:
        if url.startswith("file://"):
            path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
        elif url.startswith(("http://", "https://")):
            req = urllib.request.Request(url, headers={"User-Agent": "nothing-de/0.1"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read(8 << 20)
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pb = loader.get_pixbuf()
        else:
            return None
    except (GLib.Error, OSError, ValueError):
        return None
    if pb is None:
        return None
    w, h = pb.get_width(), pb.get_height()
    side = min(w, h)
    pb = pb.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side)
    pb = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    return Gdk.Texture.new_for_pixbuf(pb)


class Media(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "art": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.bus = None
        self.proxy = None
        self.name = None            # bus name of the player
        self.title = ""
        self.artist = ""
        self.album = ""
        self.art_url = ""
        self.art = None             # Gdk.Texture of the cover
        self.track_id = None
        self.length = 0             # µs
        self._position = 0          # µs, at _pos_time
        self._pos_time = time.monotonic()
        self.status = ""            # Playing | Paused | Stopped | ""
        self._users = 0
        self._timer = None
        self._art_wanted = None

    # -------------------------------------------------------------- users
    def listen(self, cb):
        """`cb(media)` on every change; returns an id for `release`. Polls while anyone
        listens."""
        self._users += 1
        if self._timer is None:
            self._timer = GLib.timeout_add(1000, self._tick)
            GLib.idle_add(lambda: (self.poll(), False)[1])
        return self.connect("changed", cb)

    def release(self, handler_id):
        """Stop listening; polling stops with the last listener."""
        self.disconnect(handler_id)
        self._users = max(0, self._users - 1)
        if not self._users and self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.poll()
        return True

    # ------------------------------------------------------------- state
    @property
    def available(self):
        return self.proxy is not None

    @property
    def playing(self):
        return self.status == "Playing"

    @property
    def position(self):
        """Current position in µs, extrapolated since the last poll."""
        pos = self._position
        if self.playing:
            pos += (time.monotonic() - self._pos_time) * 1_000_000
        return min(pos, self.length) if self.length else pos

    @property
    def progress(self):
        return max(0.0, min(1.0, self.position / self.length)) if self.length else 0.0

    @property
    def player(self):
        return player_label(self.name) if self.name else ""

    def _players(self):
        if self.bus is None:
            try:
                self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            except GLib.Error:
                return []
        try:
            names = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                       "org.freedesktop.DBus", "ListNames", None, None,
                                       Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
        except GLib.Error:
            return []
        return sorted(n for n in names if n.startswith(PLAYER_PREFIX))

    def poll(self):
        players = self._players()
        if not players:
            if self.proxy is not None or self.title:
                self.proxy = self.name = None
                self.title = self.artist = self.album = self.art_url = ""
                self.art = None
                self.status = ""
                self.length = self._position = 0
                self.emit("art")
                self.emit("changed")
            return
        # a playing player wins over a paused one
        if self.name not in players or not self.playing:
            for name in players:
                st = self._status_of(name)
                if st == "Playing":
                    self._use(name)
                    break
            else:
                if self.name not in players:
                    self._use(players[0])
        if self.proxy is None:
            return
        self.proxy.call("org.freedesktop.DBus.Properties.GetAll",
                        GLib.Variant("(s)", ("org.mpris.MediaPlayer2.Player",)),
                        Gio.DBusCallFlags.NONE, 800, None, self._on_props, self.name)

    def _status_of(self, name):
        try:
            res = self.bus.call_sync(name, "/org/mpris/MediaPlayer2",
                                     "org.freedesktop.DBus.Properties", "Get",
                                     GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player",
                                                           "PlaybackStatus")),
                                     None, Gio.DBusCallFlags.NONE, 300, None)
            return res.unpack()[0]
        except GLib.Error:
            return ""

    def _use(self, name):
        if name == self.name and self.proxy is not None:
            return
        self.name = name
        try:
            self.proxy = Gio.DBusProxy.new_sync(
                self.bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None, name,
                "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", None)
        except GLib.Error:
            self.proxy = None

    def _on_props(self, proxy, res, name):
        if name != self.name:
            return
        try:
            props = proxy.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        meta = props.get("Metadata") or {}
        artists = meta.get("xesam:artist") or []
        self.title = meta.get("xesam:title") or ""
        self.artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
        self.album = meta.get("xesam:album") or ""
        self.track_id = meta.get("mpris:trackid")
        self.length = int(meta.get("mpris:length") or 0)
        self.status = props.get("PlaybackStatus") or ""
        pos = props.get("Position")
        if pos is not None:
            self._position = int(pos)
            self._pos_time = time.monotonic()
        url = meta.get("mpris:artUrl") or ""
        if url != self.art_url:
            self.art_url = url
            self.art = None
            self.emit("art")
            if url:
                self._fetch_art(url)
        self.emit("changed")

    def _fetch_art(self, url):
        self._art_wanted = url

        def work():
            tex = _load_art(url, 256)
            GLib.idle_add(done, tex)

        def done(tex):
            if self._art_wanted == url:
                self.art = tex
                self.emit("art")
            return False
        threading.Thread(target=work, daemon=True).start()

    # ----------------------------------------------------------- control
    def call(self, method):
        if self.proxy is None:
            return
        self.proxy.call(method, None, Gio.DBusCallFlags.NONE, -1, None, None)
        if method == "PlayPause":
            # show the new state right away; the next poll confirms it
            self._position = self.position
            self._pos_time = time.monotonic()
            self.status = "Paused" if self.playing else "Playing"
            self.emit("changed")
        GLib.timeout_add(250, lambda: (self.poll(), False)[1])

    def seek(self, fraction):
        if self.proxy is None or not self.length or not self.track_id:
            return
        pos = int(max(0.0, min(1.0, fraction)) * self.length)
        self.proxy.call("SetPosition", GLib.Variant("(ox)", (self.track_id, pos)),
                        Gio.DBusCallFlags.NONE, -1, None, None)
        self._position = pos
        self._pos_time = time.monotonic()
        self.emit("changed")


_media = None


def get_media():
    global _media
    if _media is None:
        _media = Media()
    return _media


def art_initial(title):
    """A letter for the cover placeholder."""
    title = (title or "").strip()
    return title[:1].upper() if title else "♪"

