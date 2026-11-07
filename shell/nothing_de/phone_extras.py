"""Telefon-Zusätze: Lautstärke-/Helligkeitsanzeige, Ausschalt-Menü und automatisches Drehen.

- OSD: der Compositor meldet `osd_volume`/`osd_brightness` nach einer Lautstärke- oder
  Helligkeitstaste, die Anzeige zeigt kurz den neuen Wert.
- Ausschalt-Menü: langes Drücken der Ein-/Aus-Taste (`power_menu`). Auf dem Sperrbildschirm
  zeigt es der Sperrbildschirm selbst (power_menu_box), sonst ein eigenes Overlay.
- Drehen: der Lagesensor (net.hadess.SensorProxy, iio-sensor-proxy oder kompatibel) liefert die
  Ausrichtung, der Compositor dreht den eingebauten Bildschirm samt Touch. Gesperrt bleibt das
  Telefon hochkant.
"""
from gi.repository import Gio, GLib, Gtk

from . import layer, system

OSD_MS = 1500

# AccelerometerOrientation -> rotation of the screen (wl_output, degrees counter-clockwise)
ORIENTATION_DEGREES = {"normal": 0, "left-up": 90, "bottom-up": 180, "right-up": 270}


class Osd(Gtk.ApplicationWindow):
    """Kleine Pille oben in der Mitte: Symbol und Balken, verschwindet nach kurzer Zeit."""

    def __init__(self, shell):
        super().__init__(application=shell.app)
        self.add_css_class("n-root")
        layer.setup(self, layer="overlay", anchors=("top",), margins={"top": 48},
                    exclusive=-1, keyboard="none", namespace="nothing-osd")
        box = Gtk.Box(spacing=14)
        box.add_css_class("n-osd")
        self.icon = Gtk.Image(pixel_size=20)
        self.bar = Gtk.LevelBar(min_value=0, max_value=1, hexpand=True)
        self.bar.add_css_class("n-osd-bar")
        self.bar.set_size_request(180, -1)
        self.bar.set_valign(Gtk.Align.CENTER)
        box.append(self.icon)
        box.append(self.bar)
        self.set_child(box)
        self._hide = 0

    def show_level(self, icon, value):
        self.icon.set_from_icon_name(icon)
        self.bar.set_value(max(0.0, min(1.0, value)))
        self.present()
        if self._hide:
            GLib.source_remove(self._hide)
        self._hide = GLib.timeout_add(OSD_MS, self._timeout)

    def _timeout(self):
        self._hide = 0
        self.set_visible(False)
        return False

    def volume(self):
        # the compositor has only just started wpctl
        def got(v, muted):
            self.show_level(system.volume_icon(v, muted), 0 if muted else (v or 0))
        GLib.timeout_add(150, lambda: (system.get_volume(got), False)[1])

    def brightness(self):
        def show():
            b = system.get_brightness()
            if b is not None:
                self.show_level("display-brightness-symbolic", b)
            return False
        GLib.timeout_add(150, show)


def power_menu_box(on_close, lock=None):
    """Große Knöpfe zum Ausschalten, Neustarten (und Sperren); on_close() schließt das Menü."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.add_css_class("n-power-menu")
    entries = [("system-shutdown-symbolic", "Ausschalten", system.poweroff),
               ("system-reboot-symbolic", "Neu starten", system.reboot)]
    if lock:
        entries.append(("system-lock-screen-symbolic", "Sperren", lock))
    for icon, label, action in entries:
        b = Gtk.Button()
        b.add_css_class("n-power-item")
        row = Gtk.Box(spacing=16)
        row.append(Gtk.Image(icon_name=icon, pixel_size=22))
        row.append(Gtk.Label(label=label, xalign=0))
        b.set_child(row)
        b.connect("clicked", lambda _b, a=action: (on_close(), a()))
        box.append(b)
    cancel = Gtk.Button(label="Abbrechen")
    cancel.add_css_class("n-pill-button")
    cancel.set_halign(Gtk.Align.CENTER)
    cancel.set_margin_top(6)
    cancel.connect("clicked", lambda *_: on_close())
    box.append(cancel)
    return box


class PowerMenu(layer.Overlay):
    def __init__(self, shell):
        super().__init__(shell.app, "nothing-power", dim=True)
        self.shell = shell
        self.panel.remove_css_class("n-panel")   # the menu box brings its own card
        self.panel.set_halign(Gtk.Align.FILL)
        self.panel.set_valign(Gtk.Align.CENTER)
        self.panel.set_margin_start(24)
        self.panel.set_margin_end(24)
        self.panel.append(power_menu_box(self.close_overlay,
                                         lock=lambda: shell.run_action("lock")))


class Rotation:
    """Automatisches Drehen über den Lagesensor. `rotated` sagt, ob der Bildschirm gerade
    quer oder kopfüber steht (die Shell bleibt dann in der Telefon-Ansicht)."""

    def __init__(self, shell):
        self.shell = shell
        self.orientation = "normal"
        self.applied = 0
        self.proxy = None
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
                                  "net.hadess.SensorProxy", "/net/hadess/SensorProxy",
                                  "net.hadess.SensorProxy", None, self._ready)

    @property
    def rotated(self):
        return self.applied != 0

    @property
    def available(self):
        return self.proxy is not None and self.proxy.get_name_owner() is not None

    def _ready(self, _src, res):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error:
            return
        self.proxy.connect("g-properties-changed", lambda *_: self._read())
        self.proxy.call("ClaimAccelerometer", None, Gio.DBusCallFlags.NONE, -1, None,
                        lambda p, r: self._claimed(p, r))

    def _claimed(self, proxy, res):
        try:
            proxy.call_finish(res)
        except GLib.Error:
            self.proxy = None
            return
        self._read()

    def _read(self):
        v = self.proxy.get_cached_property("AccelerometerOrientation")
        if v is not None:
            self.orientation = v.unpack()
        self.apply()

    def apply(self):
        """Bring the screen in line with sensor, setting and lock state."""
        deg = ORIENTATION_DEGREES.get(self.orientation)
        if deg is None:          # "undefined": lying flat, keep what we have
            deg = self.applied
        if not self.shell.cfg.get("phone.auto_rotate", True) or self.shell.wm.state.get("locked"):
            deg = 0
        outputs = self.shell.wm.state.get("outputs", [])
        if not outputs:
            return
        if deg != self.applied or outputs[0].get("transform", 0) != deg:
            self.applied = deg
            self.shell.wm.send("output", outputs[0]["name"], "transform", deg)
