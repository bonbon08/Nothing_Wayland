"""Control centre: quick toggles, sliders, accent picker, power buttons."""
from gi.repository import GLib, Gtk, Pango

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


SWIPE_CLOSE = 60   # px upwards that close the control centre on the phone


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
        # phone only: turn the screen with the phone
        self.rotate = Tile("object-rotate-right-symbolic", "Drehen",
                           lambda on: self.cfg.set("phone.auto_rotate", on))
        grid.attach(self.rotate, 0, 2, 1, 1)
        self.panel.append(grid)

        # Bluetooth-Geräte (Quick Connect)
        self.bt_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.bt_group.add_css_class("n-panel-section")
        bt_title = Gtk.Label(label="Bluetooth-Geräte", xalign=0)
        bt_title.add_css_class("n-caps")
        bt_title.set_margin_top(4)
        self.bt_group.append(bt_title)
        self.bt_sub = Gtk.Label(label="Gekoppelte / entdeckte Geräte", xalign=0)
        self.bt_sub.add_css_class("n-muted")
        self.bt_sub.set_margin_bottom(4)
        self.bt_group.append(self.bt_sub)
        self.bt_devices = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.bt_devices.add_css_class("boxed-list")
        self.bt_group.append(self.bt_devices)
        self.bt_empty = Gtk.Label(label="Keine Geräte gefunden")
        self.bt_empty.add_css_class("n-muted")
        self.bt_empty.set_margin_top(6)
        self.bt_group.append(self.bt_empty)
        self.panel.append(self.bt_group)
        self.bt_group.set_visible(False)

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
        swipe = Gtk.GestureDrag()
        swipe.connect("drag-end", self._on_swipe_end)
        self.add_controller(swipe)

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
        # phone: no standby entry (the power key turns the screen off instead)
        if self.shell.phone:
            choices = [("Abbrechen", None), ("Neu starten", system.reboot),
                       ("Ausschalten", system.poweroff)]
            message = "Telefon ausschalten?"
        else:
            choices = [("Abbrechen", None), ("Bereitschaft", system.suspend),
                       ("Neu starten", system.reboot), ("Ausschalten", system.poweroff)]
            message = "Computer ausschalten?"
        dlg = Gtk.AlertDialog(message=message, buttons=[c[0] for c in choices],
                              cancel_button=0, default_button=len(choices) - 1)

        def done(d, res):
            try:
                idx = d.choose_finish(res)
            except GLib.Error:
                return
            action = choices[idx][1] if 0 <= idx < len(choices) else None
            if action:
                action()
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
            self.bt_group.set_visible(bool(state))
            if state:
                self._refresh_bt_devices()
        system.get_bluetooth(got)
        return False

    def _refresh_bt_devices(self):
        def got(devices):
            while (c := self.bt_devices.get_first_child()) is not None:
                self.bt_devices.remove(c)
            if not devices:
                self.bt_empty.set_visible(True)
                return
            self.bt_empty.set_visible(False)
            for addr, name, connected in devices:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.set_hexpand(True)
                lbl = Gtk.Label(label=name or addr, xalign=0)
                lbl.set_hexpand(True)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                btn = Gtk.Button(label="Trennen" if connected else "Verbinden")
                btn.add_css_class("flat")
                btn.set_valign(Gtk.Align.CENTER)
                action = self._disconnect_bt if connected else self._connect_bt
                btn.connect("clicked", lambda _b, a=addr, act=action: act(a))
                row.append(lbl)
                row.append(btn)
                self.bt_devices.append(row)
        system.get_bluetooth_devices(got)

    def _connect_bt(self, address):
        def done():
            GLib.timeout_add(800, self._refresh_bt_devices)
        system.bluetooth_connect(address, done)

    def _disconnect_bt(self, address):
        def done():
            GLib.timeout_add(800, self._refresh_bt_devices)
        system.bluetooth_disconnect(address, done)

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
        rot = self.shell.rotation
        self.rotate.set_visible(bool(self.shell.phone and rot and rot.available))
        self.rotate.set_state(self.cfg.get("phone.auto_rotate", True),
                              None if self.cfg.get("phone.auto_rotate", True) else "GESPERRT")
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
        # phone: pulled down from the status bar over the whole width; swiping up closes it
        narrow = bool(self.shell.phone)
        self.panel.set_size_request(-1 if narrow else 360, -1)
        self.panel.set_halign(Gtk.Align.FILL if narrow else Gtk.Align.END)
        self.panel.set_margin_top(8 if narrow else 42)
        self.panel.set_margin_start(8 if narrow else 0)
        self.panel.set_margin_end(8 if narrow else 10)
        self.refresh()
        super().open_overlay()

    def _on_swipe_end(self, _g, dx, dy):
        if self.shell.phone and dy < -SWIPE_CLOSE and abs(dy) > abs(dx):
            self.close_overlay()
