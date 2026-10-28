"""Control centre: quick toggles, sliders, accent picker, power buttons."""
from gi.repository import GLib, Gtk

from . import layer, system
from .config import ACCENTS


class Tile(Gtk.Button):
    def __init__(self, icon, title, on_toggle):
        super().__init__()
        self.add_css_class("n-tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.icon = Gtk.Image(icon_name=icon, pixel_size=20, halign=Gtk.Align.START)
        self.title = Gtk.Label(label=title, xalign=0)
        self.title.set_css_classes(["n-tile-title"])
        self.sub = Gtk.Label(xalign=0)
        self.sub.add_css_class("n-caps")
        box.append(self.icon)
        box.append(self.title)
        box.append(self.sub)
        self.set_child(box)
        self.state = False
        self.connect("clicked", lambda *_: on_toggle(not self.state))

    def set_state(self, on, sub=None):
        self.state = bool(on)
        if on:
            self.add_css_class("on")
        else:
            self.remove_css_class("on")
        self.sub.set_label(sub if sub is not None else ("AN" if on else "AUS"))


class ControlCenter(layer.Overlay):
    def __init__(self, shell):
        super().__init__(shell.app, "nothing-control", halign=Gtk.Align.END,
                         valign=Gtk.Align.START, margin_top=42, margin_end=10)
        self.shell = shell
        self.cfg = shell.cfg
        self.panel.set_size_request(360, -1)
        self.panel.set_spacing(14)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.wifi = Tile("network-wireless-symbolic", "WLAN", self._set_wifi)
        self.bt = Tile("bluetooth-active-symbolic", "Bluetooth", self._set_bt)
        self.dark = Tile("weather-clear-night-symbolic", "Dunkel",
                         lambda on: self.cfg.set("theme", "dark" if on else "light"))
        self.dnd = Tile("notifications-disabled-symbolic", "Nicht stören",
                        lambda on: (self.cfg.set("dnd", on), self.refresh()))
        grid.attach(self.wifi, 0, 0, 1, 1)
        grid.attach(self.bt, 1, 0, 1, 1)
        grid.attach(self.dark, 0, 1, 1, 1)
        grid.attach(self.dnd, 1, 1, 1, 1)
        self.panel.append(grid)

        self.vol = self._slider("audio-volume-high-symbolic", system.set_volume,
                                lambda: system.toggle_mute())
        self.panel.append(self.vol[0])
        self.bright = self._slider("display-brightness-symbolic", system.set_brightness)
        self.panel.append(self.bright[0])

        acc_box = Gtk.Box(spacing=8)
        acc_box.set_halign(Gtk.Align.CENTER)
        self.swatches = []
        for name, hx in ACCENTS:
            b = Gtk.Button()
            b.add_css_class("n-swatch")
            b.set_tooltip_text(name)
            prov = Gtk.CssProvider()
            prov.load_from_string(f"button {{ background: {hx}; }}")
            b.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            b.connect("clicked", lambda _b, hx=hx: self.cfg.set("accent", hx))
            b.hex = hx
            self.swatches.append(b)
            acc_box.append(b)
        self.panel.append(acc_box)

        row = Gtk.Box(spacing=10, homogeneous=True)
        for icon, tip, cb in (
            ("emblem-system-symbolic", "Einstellungen", lambda: shell.spawn_settings()),
            ("camera-photo-symbolic", "Bildschirmfoto", lambda: shell.run_action("screenshot")),
            ("system-lock-screen-symbolic", "Sperren", lambda: shell.run_action("lock")),
            ("system-shutdown-symbolic", "Ausschalten", self._power_menu),
        ):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.add_css_class("n-round")
            b.connect("clicked", lambda _b, cb=cb: (self.close_overlay(), cb()))
            row.append(b)
        self.panel.append(row)
        self.cfg.connect("changed", lambda *_: self.get_visible() and self.refresh())
        self._updating = False

    def _slider(self, icon, setter, icon_click=None):
        box = Gtk.Box(spacing=10)
        btn = Gtk.Button(icon_name=icon)
        btn.add_css_class("n-round")
        if icon_click:
            btn.connect("clicked", lambda *_: (icon_click(), GLib.timeout_add(200, self._refresh_volume)))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.add_css_class("n-slider")
        scale.set_focusable(False)  # no focus ring inside the panel
        scale.connect("value-changed", lambda s: None if self._updating else setter(s.get_value()))
        box.append(btn)
        box.append(scale)
        return box, scale, btn

    def _power_menu(self):
        dlg = Gtk.AlertDialog(message="Computer ausschalten?",
                              buttons=["Abbrechen", "Bereitschaft", "Neu starten", "Ausschalten"],
                              cancel_button=0, default_button=3)

        def done(d, res):
            try:
                idx = d.choose_finish(res)
            except GLib.Error:
                return
            {1: system.suspend, 2: system.reboot, 3: system.poweroff}.get(idx, lambda: None)()
        dlg.choose(None, None, done)

    def _set_wifi(self, on):
        self.shell.bar_net().set_wifi(on)
        self.wifi.set_state(on)

    def _set_bt(self, on):
        system.set_bluetooth(on, lambda: GLib.timeout_add(500, self._refresh_bt))
        self.bt.set_state(on)

    def _refresh_bt(self):
        def got(state):
            self.bt.set_sensitive(state is not None)
            self.bt.set_state(bool(state), "N/V" if state is None else None)
        system.get_bluetooth(got)
        return False

    def _refresh_volume(self):
        def got(v, muted):
            self._updating = True
            self.vol[1].set_value(min(1.0, v or 0))
            self.vol[2].set_icon_name(system.volume_icon(v, muted))
            self._updating = False
        system.get_volume(got)
        return False

    def refresh(self):
        net = self.shell.bar_net()
        icon, label = net.status()
        on = net.wifi_enabled()
        sub = label.upper()[:16] if on and "wireless-signal" in icon else ("AN" if on else "AUS")
        self.wifi.set_state(on, sub)
        self.dark.set_state(self.cfg.get("theme") != "light")
        self.dnd.set_state(self.cfg.get("dnd"))
        self._refresh_bt()
        self._refresh_volume()
        b = system.get_brightness()
        self.bright[0].set_visible(b is not None)
        if b is not None:
            self._updating = True
            self.bright[1].set_value(b)
            self._updating = False
        for s in self.swatches:
            if s.hex.lower() == (self.cfg.get("accent") or "").lower():
                s.add_css_class("selected")
            else:
                s.remove_css_class("selected")

    def open_overlay(self):
        self.refresh()
        super().open_overlay()
