"""Einstellungsseiten für Verbindungen: WLAN, LAN, Bluetooth und Mobilfunk.

- WLAN und LAN über NetworkManager (libnm): ein-/ausschalten, Netze suchen, verbinden (mit
  Passwortabfrage), gespeicherte Netze vergessen, Adressen anzeigen.
- Bluetooth über BlueZ (D-Bus): Adapter an/aus, gekoppelte Geräte verbinden/trennen/entfernen,
  neue Geräte suchen und koppeln. Ein eigener Pairing-Agent fragt Bestätigung oder PIN ab.
- Mobilfunk über ModemManager (D-Bus) und NetworkManager: SIM-PIN, Netz, Signal, mobile Daten,
  APN, Roaming und erlaubte Netztypen.
Alles läuft asynchron, die Seiten bauen sich bei Änderungen neu auf.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("NM", "1.0")
    from gi.repository import NM  # noqa: E402
except (ValueError, ImportError):   # libnm not installed: the pages say so
    NM = None


def _group(title=None, description=None):
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(title)
    if description:
        g.set_description(description)
    return g


class Rebuildable:
    """A group whose rows are replaced as a whole (lists of networks or devices)."""

    def __init__(self, title=None, description=None):
        self.group = _group(title, description)
        self.rows = []

    def set_rows(self, rows):
        for r in self.rows:
            self.group.remove(r)
        self.rows = list(rows)
        for r in self.rows:
            self.group.add(r)


def _toast(widget, text):
    w = widget.get_root()
    if w is not None and hasattr(w, "toasts"):
        w.toasts.add_toast(Adw.Toast(title=text, timeout=3))


def _status_page(title, description, icon):
    p = Adw.PreferencesPage()
    g = _group()
    g.add(Adw.StatusPage(title=title, description=description, icon_name=icon))
    p.add(g)
    return p


def _signal_icon(strength):
    for limit, name in ((80, "excellent"), (55, "good"), (30, "ok"), (5, "weak")):
        if strength >= limit:
            return f"network-wireless-signal-{name}-symbolic"
    return "network-wireless-signal-none-symbolic"


def _ip4(device):
    cfg = device.get_ip4_config() if device else None
    addrs = cfg.get_addresses() if cfg else []
    return ", ".join(f"{a.get_address()}/{a.get_prefix()}" for a in addrs)


_nm_client = None


def nm_client(callback):
    """Shared NM.Client, created once (async); callback(client or None)."""
    global _nm_client
    if NM is None:
        callback(None)
        return
    if _nm_client is not None:
        callback(_nm_client)
        return

    def done(_src, res):
        global _nm_client
        try:
            _nm_client = NM.Client.new_finish(res)
        except GLib.Error:
            _nm_client = None
        callback(_nm_client)
    NM.Client.new_async(None, done)


# ======================================================================
class WifiPage:
    def __init__(self, cfg):
        self.widget = Adw.PreferencesPage(title="WLAN")
        self.client = None
        self.device = None
        self._pending = 0

        g = _group()
        self.enabled = Adw.SwitchRow(title="WLAN")
        self.enabled.connect("notify::active", self._on_switch)
        g.add(self.enabled)
        self.widget.add(g)

        self.current = Rebuildable("Verbunden")
        self.widget.add(self.current.group)
        self.networks = Rebuildable("Netzwerke")
        scan = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Suchen")
        scan.add_css_class("flat")
        scan.connect("clicked", lambda *_: self.scan())
        self.networks.group.set_header_suffix(scan)
        self.widget.add(self.networks.group)
        self.saved = Rebuildable("Gespeicherte Netzwerke")
        self.widget.add(self.saved.group)
        nm_client(self._ready)

    def _ready(self, client):
        self.client = client
        if client is None:
            self.enabled.set_sensitive(False)
            self.networks.set_rows([Adw.ActionRow(title="NetworkManager nicht erreichbar")])
            return
        client.connect("notify::wireless-enabled", lambda *_: self.refresh())
        client.connect("device-added", lambda *_: self._find_device())
        client.connect("device-removed", lambda *_: self._find_device())
        client.connect("connection-added", lambda *_: self.refresh())
        client.connect("connection-removed", lambda *_: self.refresh())
        self._find_device()
        self.scan()
        # keep the list fresh while the page exists
        GLib.timeout_add_seconds(15, lambda: (self.widget.get_mapped() and self.scan(), True)[1])

    def _find_device(self):
        self.device = next((d for d in self.client.get_devices()
                            if d.get_device_type() == NM.DeviceType.WIFI), None)
        if self.device is not None:
            for sig in ("access-point-added", "access-point-removed", "state-changed",
                        "notify::active-access-point"):
                self.device.connect(sig, lambda *_: self.refresh())
        self.refresh()

    def _on_switch(self, row, _p):
        if self.client is None or row.get_active() == self.client.wireless_get_enabled():
            return
        self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                      GLib.Variant("b", row.get_active()), -1, None, None)

    def scan(self):
        if self.device is not None and self.client.wireless_get_enabled():
            self.device.request_scan_async(None, lambda d, r: self._scan_done(d, r))

    def _scan_done(self, dev, res):
        try:
            dev.request_scan_finish(res)
        except GLib.Error:
            pass   # "scanning not allowed" right after a scan: the old list stays
        self.refresh()

    def refresh(self):
        # many signals at once (a scan adds dozens of access points): rebuild once
        if not self._pending:
            self._pending = GLib.timeout_add(250, self._rebuild)

    def _rebuild(self):
        self._pending = 0
        on = self.client.wireless_get_enabled()
        self.enabled.set_active(on)
        if self.device is None:
            self.current.group.set_visible(False)
            self.networks.set_rows([Adw.ActionRow(title="Kein WLAN-Gerät")])
            self.saved.group.set_visible(False)
            return False
        active = self.device.get_active_access_point()
        active_ssid = _ssid(active)

        rows = []
        if active is not None and self.device.get_state() == NM.DeviceState.ACTIVATED:
            r = Adw.ActionRow(title=active_ssid, subtitle=f"Verbunden · {_ip4(self.device)}")
            r.add_prefix(Gtk.Image(icon_name=_signal_icon(active.get_strength())))
            off = Gtk.Button(label="Trennen", valign=Gtk.Align.CENTER)
            off.connect("clicked", lambda *_: self.device.disconnect_async(None, None))
            r.add_suffix(off)
            rows.append(r)
        elif self.device.get_state() in (NM.DeviceState.PREPARE, NM.DeviceState.CONFIG,
                                         NM.DeviceState.NEED_AUTH, NM.DeviceState.IP_CONFIG):
            rows.append(Adw.ActionRow(title="Verbinde …"))
        self.current.set_rows(rows)
        self.current.group.set_visible(bool(rows))

        # strongest access point per network name
        best = {}
        for ap in self.device.get_access_points():
            ssid = _ssid(ap)
            if ssid and ssid != active_ssid and (ssid not in best or
                                                 ap.get_strength() > best[ssid].get_strength()):
                best[ssid] = ap
        saved = self._saved_wifi()
        rows = []
        # by signal level (as the icon shows it), then name: a rescan doesn't shuffle the list
        # under the finger
        for ap in sorted(best.values(), key=lambda a: (-(a.get_strength() // 25),
                                                       _ssid(a).lower())):
            ssid = _ssid(ap)
            secure = bool(ap.get_wpa_flags() or ap.get_rsn_flags() or
                          ap.get_flags() & getattr(NM, "80211ApFlags").PRIVACY)
            r = Adw.ActionRow(title=ssid, activatable=True,
                              subtitle="Gespeichert" if ssid in saved else None)
            r.add_prefix(Gtk.Image(icon_name=_signal_icon(ap.get_strength())))
            if secure:
                r.add_suffix(Gtk.Image(icon_name="channel-secure-symbolic"))
            r.connect("activated", lambda _r, ap=ap, s=secure: self.connect_ap(ap, s))
            rows.append(r)
        if not on:
            rows = [Adw.ActionRow(title="WLAN ist aus")]
        elif not rows:
            rows = [Adw.ActionRow(title="Suche …")]
        self.networks.set_rows(rows)

        rows = []
        for ssid, conn in sorted(saved.items()):
            r = Adw.ActionRow(title=ssid)
            forget = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Vergessen")
            forget.add_css_class("flat")
            forget.connect("clicked", lambda _b, c=conn: c.delete_async(None, None))
            r.add_suffix(forget)
            rows.append(r)
        self.saved.set_rows(rows)
        self.saved.group.set_visible(bool(rows))
        return False

    def _saved_wifi(self):
        out = {}
        for c in self.client.get_connections():
            w = c.get_setting_wireless()
            if w is not None and w.get_ssid() is not None:
                out[NM.utils_ssid_to_utf8(w.get_ssid().get_data())] = c
        return out

    def connect_ap(self, ap, secure):
        ssid = _ssid(ap)
        saved = self._saved_wifi().get(ssid)
        if saved is not None:
            self.client.activate_connection_async(saved, self.device, ap.get_path(), None,
                                                  lambda c, r: self._activated(c, r, ssid))
            return
        if not secure:
            self._add(ap, None)
            return
        dlg = Adw.AlertDialog(heading=f"„{ssid}“", body="Passwort des WLANs")
        entry = Adw.PasswordEntryRow(title="Passwort")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.append(entry)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("ok", "Verbinden")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        entry.connect("entry-activated", lambda *_: (dlg.close(), self._add(ap, entry.get_text())))
        dlg.connect("response", lambda _d, r: r == "ok" and self._add(ap, entry.get_text()))
        dlg.present(self.widget)

    def _add(self, ap, password):
        conn = NM.SimpleConnection.new()
        if password:
            sec = NM.SettingWirelessSecurity.new()
            sec.set_property("key-mgmt", "sae" if _wpa3_only(ap) else "wpa-psk")
            sec.set_property("psk", password)
            conn.add_setting(sec)
        ssid = _ssid(ap)
        self.client.add_and_activate_connection_async(
            conn, self.device, ap.get_path(), None,
            lambda c, r: self._activated(c, r, ssid, added=True))

    def _activated(self, client, res, ssid, added=False):
        try:
            if added:
                client.add_and_activate_connection_finish(res)
            else:
                client.activate_connection_finish(res)
        except GLib.Error as e:
            _toast(self.widget, f"„{ssid}“: {e.message}")
        self.refresh()


def _ssid(ap):
    if ap is None or ap.get_ssid() is None:
        return None
    return NM.utils_ssid_to_utf8(ap.get_ssid().get_data())


def _wpa3_only(ap):
    flags = ap.get_rsn_flags()
    sae = getattr(NM, "80211ApSecurityFlags").KEY_MGMT_SAE
    psk = getattr(NM, "80211ApSecurityFlags").KEY_MGMT_PSK
    return bool(flags & sae) and not flags & psk


# ======================================================================
class WiredPage:
    """LAN: Kabelnetzwerke (Ethernet, auch USB-C-Adapter und USB-Netz zum PC)."""

    def __init__(self, cfg):
        self.widget = Adw.PreferencesPage(title="LAN")
        self.client = None
        self.list = Rebuildable("Kabelnetzwerk",
                                "Netzwerkkabel über einen USB-C-Adapter, oder das USB-Netz zum PC.")
        self.widget.add(self.list.group)
        self._pending = 0
        nm_client(self._ready)

    def _ready(self, client):
        self.client = client
        if client is None:
            self.list.set_rows([Adw.ActionRow(title="NetworkManager nicht erreichbar")])
            return
        for sig in ("device-added", "device-removed", "active-connection-added",
                    "active-connection-removed"):
            client.connect(sig, lambda *_: self.refresh())
        for d in client.get_devices():
            d.connect("state-changed", lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        if not self._pending:
            self._pending = GLib.timeout_add(250, self._rebuild)

    def _rebuild(self):
        self._pending = 0
        rows = []
        for d in self.client.get_devices():
            if d.get_device_type() != NM.DeviceType.ETHERNET:
                continue
            state = d.get_state()
            if state == NM.DeviceState.UNMANAGED:
                sub = "Nicht von NetworkManager verwaltet"
                ip = _ip_of(d.get_iface())
                if ip:
                    sub += f" · {ip}"
            elif state == NM.DeviceState.UNAVAILABLE:
                sub = "Kein Kabel"
            elif state == NM.DeviceState.ACTIVATED:
                speed = d.get_speed() if hasattr(d, "get_speed") else 0
                sub = "Verbunden · " + _ip4(d) + (f" · {speed} Mbit/s" if speed else "")
            elif state == NM.DeviceState.DISCONNECTED:
                sub = "Getrennt"
            else:
                sub = "Verbinde …"
            iface = d.get_iface()
            if iface.startswith("usb") and state == NM.DeviceState.UNMANAGED:
                # the phone's USB gadget network (SSH from the PC), set up outside NetworkManager
                title, sub = f"USB-Netz zum PC ({iface})", _ip_of(iface) or "Kein Kabel"
            else:
                title = iface
            r = Adw.ActionRow(title=title, subtitle=sub)
            r.add_prefix(Gtk.Image(icon_name="network-wired-symbolic"))
            if state in (NM.DeviceState.ACTIVATED, NM.DeviceState.DISCONNECTED):
                sw = Gtk.Switch(active=state == NM.DeviceState.ACTIVATED, valign=Gtk.Align.CENTER)
                sw.connect("notify::active", lambda s, _p, d=d: self._toggle(d, s.get_active()))
                r.add_suffix(sw)
            rows.append(r)
        if not rows:
            rows = [Adw.ActionRow(title="Kein Kabelanschluss",
                                  subtitle="USB-C-Netzwerkadapter anschließen")]
        self.list.set_rows(rows)
        return False

    def _toggle(self, device, on):
        if on:
            self.client.activate_connection_async(None, device, None, None, None)
        else:
            device.disconnect_async(None, None)


def _ip_of(iface):
    """IPv4 of an interface NetworkManager doesn't manage (e.g. the USB link to the PC)."""
    try:
        import subprocess
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", iface], capture_output=True,
                             text=True, timeout=2).stdout.split()
        return out[3] if len(out) > 3 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ======================================================================
BLUEZ = "org.bluez"
AGENT_PATH = "/eu/nothing_de/settings/agent"
AGENT_XML = """<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>"""


class BluetoothPage:
    def __init__(self, cfg):
        self.widget = Adw.PreferencesPage(title="Bluetooth")
        self.bus = None
        self.manager = None
        self.adapter = None
        self.discovering = False
        self._pending = 0
        self._dialog = None

        g = _group()
        self.power = Adw.SwitchRow(title="Bluetooth")
        self.power.connect("notify::active", self._on_power)
        g.add(self.power)
        self.widget.add(g)
        self.paired = Rebuildable("Meine Geräte")
        self.widget.add(self.paired.group)
        self.found = Rebuildable("Andere Geräte", "Gerät in den Kopplungsmodus versetzen, dann antippen.")
        self.search = Gtk.Button(label="Suchen", valign=Gtk.Align.CENTER)
        self.search.connect("clicked", lambda *_: self.toggle_discovery())
        self.found.group.set_header_suffix(self.search)
        self.widget.add(self.found.group)
        self.widget.connect("unmap", lambda *_: self.discovering and self.toggle_discovery())

        Gio.DBusObjectManagerClient.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, BLUEZ, "/",
            None, None, None, self._ready)

    def _ready(self, _src, res):
        try:
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_finish(res)
        except GLib.Error:
            self.manager = None
        if self.manager is None or self.manager.get_name_owner() is None:
            self.power.set_sensitive(False)
            self.paired.set_rows([Adw.ActionRow(title="Bluetooth-Dienst nicht erreichbar")])
            self.found.group.set_visible(False)
            return
        self.bus = self.manager.get_connection()
        self.manager.connect("object-added", lambda *_: self.refresh())
        self.manager.connect("object-removed", lambda *_: self.refresh())
        self.manager.connect("interface-proxy-properties-changed", lambda *_: self.refresh())
        self._register_agent()
        self.refresh()

    # ---------------------------------------------------------- agent
    def _register_agent(self):
        """Pairing agent: confirms codes and asks for PINs through dialogs."""
        info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        try:
            self.bus.register_object(AGENT_PATH, info.interfaces[0], self._agent_call)
        except GLib.Error:
            return   # already registered by this process
        self.bus.call(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                      GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), None,
                      Gio.DBusCallFlags.NONE, -1, None,
                      lambda b, r: self._agent_registered(b, r))

    def _agent_registered(self, bus, res):
        try:
            bus.call_finish(res)
            bus.call(BLUEZ, "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                     GLib.Variant("(o)", (AGENT_PATH,)), None, Gio.DBusCallFlags.NONE, -1,
                     None, None)
        except GLib.Error:
            pass

    def _agent_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        name = self._name(args[0]) if args else ""
        reject = lambda: invocation.return_dbus_error("org.bluez.Error.Rejected", "abgelehnt")  # noqa: E731
        if method in ("Release", "Cancel"):
            if self._dialog is not None:
                self._dialog.close()
            invocation.return_value(None)
        elif method in ("AuthorizeService", "RequestAuthorization"):
            invocation.return_value(None)
        elif method == "RequestConfirmation":
            self._ask(name, f"Zeigt das Gerät den Code {args[1]:06d}?", None,
                      lambda ok, _t: invocation.return_value(None) if ok else reject())
        elif method in ("DisplayPasskey", "DisplayPinCode"):
            code = f"{args[1]:06d}" if method == "DisplayPasskey" else args[1]
            self._ask(name, f"Auf dem Gerät eingeben: {code}", None, lambda *_: None, info=True)
            invocation.return_value(None)
        elif method == "RequestPinCode":
            self._ask(name, "PIN des Geräts (oft 0000 oder 1234)", "PIN",
                      lambda ok, t: invocation.return_value(GLib.Variant("(s)", (t,)))
                      if ok and t else reject())
        elif method == "RequestPasskey":
            self._ask(name, "Code des Geräts", "Code",
                      lambda ok, t: invocation.return_value(GLib.Variant("(u)", (int(t),)))
                      if ok and t.isdigit() else reject())
        else:
            reject()

    def _ask(self, heading, body, entry_title, done, info=False):
        dlg = Adw.AlertDialog(heading=heading or "Koppeln", body=body)
        entry = None
        if entry_title:
            entry = Adw.EntryRow(title=entry_title)
            box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            box.add_css_class("boxed-list")
            box.append(entry)
            dlg.set_extra_child(box)
        if info:
            dlg.add_response("ok", "OK")
        else:
            dlg.add_response("cancel", "Abbrechen")
            dlg.add_response("ok", "Koppeln")
            dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        self._dialog = dlg

        def resp(_d, r):
            self._dialog = None
            done(r == "ok", entry.get_text().strip() if entry else "")
        dlg.connect("response", resp)
        dlg.present(self.widget)

    # ---------------------------------------------------------- state
    def _objects(self, iface):
        out = []
        for obj in self.manager.get_objects():
            p = obj.get_interface(iface)
            if p is not None:
                out.append(p)
        return out

    def _prop(self, proxy, name, default=None):
        v = proxy.get_cached_property(name)
        return v.unpack() if v is not None else default

    def _name(self, path):
        obj = self.manager.get_object(path) if self.manager else None
        dev = obj.get_interface("org.bluez.Device1") if obj else None
        return self._prop(dev, "Alias", "") if dev else ""

    def refresh(self):
        if not self._pending:
            self._pending = GLib.timeout_add(300, self._rebuild)

    def _rebuild(self):
        self._pending = 0
        adapters = self._objects("org.bluez.Adapter1")
        self.adapter = adapters[0] if adapters else None
        if self.adapter is None:
            self.power.set_sensitive(False)
            self.paired.set_rows([Adw.ActionRow(title="Kein Bluetooth-Adapter")])
            self.found.group.set_visible(False)
            return False
        powered = bool(self._prop(self.adapter, "Powered", False))
        self.power.set_sensitive(True)
        self.power.set_active(powered)
        self.discovering = bool(self._prop(self.adapter, "Discovering", False))
        self.search.set_label("Stopp" if self.discovering else "Suchen")
        self.search.set_sensitive(powered)

        paired, found = [], []
        for dev in self._objects("org.bluez.Device1"):
            name = self._prop(dev, "Alias") or self._prop(dev, "Address")
            icon = (self._prop(dev, "Icon") or "bluetooth") + "-symbolic"
            r = Adw.ActionRow(title=name)
            r.add_prefix(Gtk.Image(icon_name=icon))
            if self._prop(dev, "Paired", False):
                connected = self._prop(dev, "Connected", False)
                r.set_subtitle("Verbunden" if connected else "Nicht verbunden")
                b = Gtk.Button(label="Trennen" if connected else "Verbinden",
                               valign=Gtk.Align.CENTER, sensitive=powered)
                b.connect("clicked", lambda _b, d=dev, c=connected:
                          self._call(d, "Disconnect" if c else "Connect"))
                r.add_suffix(b)
                rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Entfernen")
                rm.add_css_class("flat")
                rm.connect("clicked", lambda _b, d=dev: self._remove(d))
                r.add_suffix(rm)
                paired.append(r)
            elif self._prop(dev, "Name") and powered:
                r.set_activatable(True)
                rssi = self._prop(dev, "RSSI")
                if rssi is not None:
                    r.set_subtitle(f"Signal {rssi} dBm")
                r.connect("activated", lambda _r, d=dev: self._pair(d))
                found.append(r)
        if not powered:
            paired = [Adw.ActionRow(title="Bluetooth ist aus")] if not paired else paired
        self.paired.set_rows(paired or [Adw.ActionRow(title="Noch keine Geräte gekoppelt")])
        self.found.group.set_visible(powered)
        self.found.set_rows(found or [Adw.ActionRow(
            title="Suche …" if self.discovering else "„Suchen“ zeigt Geräte in der Nähe")])
        return False

    # ---------------------------------------------------------- actions
    def _on_power(self, row, _p):
        if self.adapter is None or row.get_active() == bool(self._prop(self.adapter, "Powered")):
            return
        self._set(self.adapter, "org.bluez.Adapter1", "Powered", GLib.Variant("b", row.get_active()))

    def _set(self, proxy, iface, name, value):
        self.bus.call(BLUEZ, proxy.get_object_path(), "org.freedesktop.DBus.Properties", "Set",
                      GLib.Variant("(ssv)", (iface, name, value)), None,
                      Gio.DBusCallFlags.NONE, -1, None, None)

    def _call(self, proxy, method, args=None, done=None):
        def finish(p, res):
            try:
                p.call_finish(res)
                ok = True
            except GLib.Error as e:
                ok = False
                if "AlreadyExists" not in e.message:
                    _toast(self.widget, f"Bluetooth: {e.message.split(':')[-1].strip()}")
            if done:
                done(ok)
            self.refresh()
        proxy.call(method, args, Gio.DBusCallFlags.NONE, 60000, None, finish)

    def toggle_discovery(self):
        if self.adapter is None:
            return
        self._call(self.adapter, "StopDiscovery" if self.discovering else "StartDiscovery")

    def _pair(self, dev):
        if self.discovering:
            self.toggle_discovery()
        _toast(self.widget, f"Kopple mit {self._prop(dev, 'Alias')} …")

        def paired(ok):
            if ok:
                self._set(dev, "org.bluez.Device1", "Trusted", GLib.Variant("b", True))
                self._call(dev, "Connect")
        self._call(dev, "Pair", done=paired)

    def _remove(self, dev):
        self._call(self.adapter, "RemoveDevice", GLib.Variant("(o)", (dev.get_object_path(),)))


# ======================================================================
MM = "org.freedesktop.ModemManager1"
MODE_2G, MODE_3G, MODE_4G, MODE_5G = 2, 4, 8, 16
NET_MODES = [("Automatisch (5G/4G/3G/2G)", MODE_2G | MODE_3G | MODE_4G | MODE_5G),
             ("4G/3G/2G (kein 5G)", MODE_2G | MODE_3G | MODE_4G),
             ("Nur 3G/2G", MODE_2G | MODE_3G),
             ("Nur 2G", MODE_2G)]
ACCESS_TECH = [(1 << 15, "5G"), (1 << 14, "LTE"), (0x3E0 | (1 << 10) | (1 << 11) | (1 << 12), "3G"),
               (0x1E, "2G")]
MODEM_STATES = {-1: "Fehler", 0: "Unbekannt", 1: "Initialisiere", 2: "Gesperrt", 3: "Aus",
                4: "Schaltet aus", 5: "Schaltet ein", 6: "Bereit", 7: "Sucht Netz",
                8: "Im Netz", 9: "Trennt", 10: "Verbinde", 11: "Verbunden"}


class MobilePage:
    def __init__(self, cfg):
        self.widget = Adw.PreferencesPage(title="Mobilfunk")
        self.manager = None
        self.client = None
        self._pending = 0
        self._busy = False

        self.sim = Rebuildable("SIM-Karte")
        self.widget.add(self.sim.group)

        g = _group("Mobile Daten")
        self.data = Adw.SwitchRow(title="Mobile Daten")
        self.data.connect("notify::active", self._on_data)
        g.add(self.data)
        self.roaming = Adw.SwitchRow(title="Roaming", subtitle="Daten auch in fremden Netzen")
        self.roaming.connect("notify::active", self._on_roaming)
        g.add(self.roaming)
        self.apn = Adw.EntryRow(title="APN (leer = vom Netz)", show_apply_button=True)
        self.apn.connect("apply", self._on_apn)
        g.add(self.apn)
        self.widget.add(g)
        self.data_group = g

        g = _group("Netz")
        self.mode = Adw.ComboRow(title="Netztypen", model=Gtk.StringList.new([m[0] for m in NET_MODES]))
        self.mode.connect("notify::selected", self._on_mode)
        g.add(self.mode)
        self.widget.add(g)
        self.net_group = g

        self.info = Rebuildable("Gerät")
        self.widget.add(self.info.group)

        Gio.DBusObjectManagerClient.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, MM,
            "/org/freedesktop/ModemManager1", None, None, None, self._ready)
        nm_client(self._nm_ready)

    def _ready(self, _src, res):
        try:
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_finish(res)
        except GLib.Error:
            self.manager = None
        if self.manager is not None:
            self.manager.connect("object-added", lambda *_: self.refresh())
            self.manager.connect("object-removed", lambda *_: self.refresh())
            self.manager.connect("interface-proxy-properties-changed", lambda *_: self.refresh())
        self.refresh()

    def _nm_ready(self, client):
        self.client = client
        if client is not None:
            for sig in ("active-connection-added", "active-connection-removed",
                        "connection-added", "connection-removed"):
                client.connect(sig, lambda *_: self.refresh())
        self.refresh()

    def _modem(self):
        if self.manager is None or self.manager.get_name_owner() is None:
            return None, None
        for obj in self.manager.get_objects():
            modem = obj.get_interface(MM + ".Modem")
            if modem is not None:
                return modem, obj.get_interface(MM + ".Modem.Modem3gpp")
        return None, None

    def _sim_proxy(self, modem, done):
        path = _p(modem, "Sim")
        if not path or path == "/":
            done(None)
            return
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, MM, path,
                                  MM + ".Sim", None,
                                  lambda _s, r: done(Gio.DBusProxy.new_for_bus_finish(r)))

    def _gsm(self):
        """NetworkManager's mobile data connection (the first of type gsm) and its active state."""
        if self.client is None:
            return None, None
        conn = next((c for c in self.client.get_connections()
                     if c.get_connection_type() == "gsm"), None)
        active = next((a for a in self.client.get_active_connections()
                       if conn is not None and a.get_uuid() == conn.get_uuid()), None)
        return conn, active

    def refresh(self):
        if not self._pending:
            self._pending = GLib.timeout_add(300, self._rebuild)

    def _rebuild(self):
        self._pending = 0
        modem, gpp = self._modem()
        if modem is None:
            self.sim.set_rows([Adw.ActionRow(title="Kein Modem gefunden",
                                             subtitle="ModemManager läuft nicht oder sieht kein Modem")])
            for g in (self.data_group, self.net_group, self.info.group):
                g.set_visible(False)
            return False
        for g in (self.data_group, self.net_group, self.info.group):
            g.set_visible(True)
        self._busy = True
        state = _p(modem, "State", 0)
        unlock = _p(modem, "UnlockRequired", 0)
        retries = dict(_p(modem, "UnlockRetries", []) or [])
        rows = []
        if unlock == 2:      # MM_MODEM_LOCK_SIM_PIN
            r = Adw.ActionRow(title="SIM gesperrt",
                              subtitle=f"PIN eingeben · noch {retries.get(2, '?')} Versuche")
            r.add_prefix(Gtk.Image(icon_name="dialog-password-symbolic"))
            b = Gtk.Button(label="Entsperren", valign=Gtk.Align.CENTER)
            b.add_css_class("suggested-action")
            b.connect("clicked", lambda *_: self._ask_pin(modem, retries.get(2)))
            r.add_suffix(b)
            rows.append(r)
        elif unlock == 4:    # SIM_PUK
            rows.append(Adw.ActionRow(title="SIM durch PUK gesperrt",
                                      subtitle="Zu oft falsche PIN. PUK z. B. mit mmcli eingeben."))
        elif _p(modem, "Sim", "/") in ("/", None):
            rows.append(Adw.ActionRow(title="Keine SIM-Karte"))
        else:
            op = _p(gpp, "OperatorName", "") if gpp else ""
            sig = (_p(modem, "SignalQuality", (0, False)) or (0, False))[0]
            tech = _tech(_p(modem, "AccessTechnologies", 0))
            r = Adw.ActionRow(title=op or MODEM_STATES.get(state, "?"),
                              subtitle=" · ".join(x for x in (tech, f"Signal {sig} %",
                                                             MODEM_STATES.get(state, "")) if x))
            r.add_prefix(Gtk.Image(icon_name=_cell_icon(sig)))
            rows.append(r)
            numbers = _p(modem, "OwnNumbers", []) or []
            if numbers:
                rows.append(Adw.ActionRow(title="Rufnummer", subtitle=", ".join(numbers)))
        self.sim.set_rows(rows)

        conn, active = self._gsm()
        usable = conn is not None and unlock in (0, 1)
        self.data.set_sensitive(usable)
        self.data.set_active(active is not None)
        self.data.set_subtitle("Verbunden" if active is not None and
                               active.get_state() == NM.ActiveConnectionState.ACTIVATED else
                               ("Kein Mobilfunkprofil in NetworkManager" if conn is None else ""))
        gsm = conn.get_setting_gsm() if conn else None
        self.roaming.set_sensitive(gsm is not None)
        self.apn.set_sensitive(gsm is not None)
        if gsm is not None:
            self.roaming.set_active(not gsm.get_home_only())
            if not self.apn.has_focus():
                self.apn.set_text(gsm.get_apn() or "")

        cur = _p(modem, "CurrentModes", (0, 0)) or (0, 0)
        supported = [m[0] for m in (_p(modem, "SupportedModes", []) or [])]
        for i, (_label, mask) in enumerate(NET_MODES):
            if cur[0] == mask:
                self.mode.set_selected(i)
        self.mode.set_sensitive(len(supported) > 1)

        info = []
        for title, value in (("IMEI", _p(gpp, "Imei", "") if gpp else ""),
                             ("Hersteller / Modell", f"{_p(modem, 'Manufacturer', '')} "
                                                     f"{_p(modem, 'Model', '')}".strip()),
                             ("Firmware", _p(modem, "Revision", ""))):
            if value:
                row = Adw.ActionRow(title=title, subtitle=value, subtitle_selectable=True)
                row.add_css_class("property")
                info.append(row)
        self.info.set_rows(info)
        self._busy = False
        return False

    # ---------------------------------------------------------- actions
    def _ask_pin(self, modem, left):
        dlg = Adw.AlertDialog(heading="SIM-PIN", body=f"Noch {left} Versuche." if left else None)
        entry = Adw.PasswordEntryRow(title="PIN")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        box.append(entry)
        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Abbrechen")
        dlg.add_response("ok", "Entsperren")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            pin = entry.get_text().strip()
            if r != "ok" or not pin.isdigit():
                return

            def got_sim(sim):
                if sim is None:
                    return

                def done(p, res):
                    try:
                        p.call_finish(res)
                        _toast(self.widget, "SIM entsperrt")
                    except GLib.Error as e:
                        _toast(self.widget, "Falsche PIN" if "Incorrect" in e.message or
                               "IncorrectPassword" in e.message else e.message)
                    self.refresh()
                sim.call("SendPin", GLib.Variant("(s)", (pin,)), Gio.DBusCallFlags.NONE,
                         30000, None, done)
            self._sim_proxy(modem, got_sim)
        dlg.connect("response", resp)
        dlg.present(self.widget)

    def _on_data(self, row, _p):
        if self._busy or self.client is None:
            return
        conn, active = self._gsm()
        if conn is None:
            return
        if row.get_active() and active is None:
            self.client.activate_connection_async(
                conn, None, None, None,
                lambda c, r: self._nm_done(lambda: c.activate_connection_finish(r)))
        elif not row.get_active() and active is not None:
            self.client.deactivate_connection_async(
                active, None, lambda c, r: self._nm_done(lambda: c.deactivate_connection_finish(r)))

    def _nm_done(self, finish):
        try:
            finish()
        except GLib.Error as e:
            _toast(self.widget, f"Mobile Daten: {e.message}")
        self.refresh()

    def _change_gsm(self, fn):
        conn, _a = self._gsm()
        gsm = conn.get_setting_gsm() if conn else None
        if gsm is None:
            return
        fn(gsm)
        conn.commit_changes_async(True, None, lambda c, r: self._committed(c, r))

    def _committed(self, conn, res):
        try:
            conn.commit_changes_finish(res)
            _toast(self.widget, "Gespeichert, gilt ab der nächsten Verbindung")
        except GLib.Error as e:
            _toast(self.widget, e.message)
        self.refresh()

    def _on_roaming(self, row, _p):
        if not self._busy:
            self._change_gsm(lambda g: g.set_property("home-only", not row.get_active()))

    def _on_apn(self, row):
        self._change_gsm(lambda g: g.set_property("apn", row.get_text().strip() or None))

    def _on_mode(self, row, _p):
        if self._busy:
            return
        modem, _g = self._modem()
        if modem is None:
            return
        mask = NET_MODES[row.get_selected()][1]

        def done(p, res):
            try:
                p.call_finish(res)
            except GLib.Error as e:
                _toast(self.widget, f"Netztypen: {e.message.split(':')[-1].strip()}")
            self.refresh()
        modem.call("SetCurrentModes", GLib.Variant("((uu))", ((mask, 0),)),
                   Gio.DBusCallFlags.NONE, 30000, None, done)


def _p(proxy, name, default=None):
    if proxy is None:
        return default
    v = proxy.get_cached_property(name)
    return v.unpack() if v is not None else default


def _tech(mask):
    for bits, name in ACCESS_TECH:
        if mask & bits:
            return name
    return ""


def _cell_icon(quality):
    for limit, name in ((75, "excellent"), (50, "good"), (25, "ok"), (5, "weak")):
        if quality >= limit:
            return f"network-cellular-signal-{name}-symbolic"
    return "network-cellular-signal-none-symbolic"
