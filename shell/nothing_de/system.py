"""System integration helpers: audio, brightness, network, bluetooth, power."""
import glob
import os
import re
import shutil
import struct

from gi.repository import Gio, GLib


def shell_app_id(display=None):
    """One shell per compositor, not per D-Bus session: a nothing-wm started for testing
    inside the running desktop shares its session bus, and with a single name its shell
    would only hand over to the running one and quit, leaving the test screen black."""
    display = os.environ.get("WAYLAND_DISPLAY", "") if display is None else display
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", os.path.basename(display))
    if not suffix or suffix == "wayland_0":
        return "eu.nothing_de.Shell"
    return "eu.nothing_de.Shell." + ("d" + suffix if suffix[0].isdigit() else suffix)


def bus_owner_flags():
    """Flags for the shell's well-known names (notifications, tray watcher): the desktop's
    shell takes them over, a test shell in a nested nothing-wm leaves them to it (it would
    take them away and they would be gone once the test ends)."""
    flags = Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT
    if shell_app_id() == "eu.nothing_de.Shell":
        flags |= Gio.BusNameOwnerFlags.REPLACE
    return flags


# ------------------------------------------------------------ input devices
# KEY_Q..KEY_P, KEY_A..KEY_L, KEY_Z..KEY_M and the space bar: a device with all of them is a
# real keyboard (the power and volume keys of a phone are "keyboards" too, without letters)
_LETTER_KEYS = list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51)) + [57]
_ABS_MT_POSITION_X = 0x35
_INPUT_PROP_DIRECT = 0


def _bits(words):
    """A bitmap from /proc/bus/input/devices ("B: KEY=..."): hex words, the most
    significant first, each as wide as a C long."""
    width = struct.calcsize("l") * 8
    value = 0
    for word in words.split():
        value = (value << width) | int(word, 16)
    return value


def input_devices(path="/proc/bus/input/devices"):
    """The kernel's input devices as dicts: name, handlers and the bitmaps KEY, ABS, PROP."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    devices = []
    for block in text.split("\n\n"):
        dev = {"name": "", "handlers": "", "KEY": 0, "ABS": 0, "PROP": 0}
        for line in block.splitlines():
            if line.startswith("N: Name="):
                dev["name"] = line[8:].strip().strip('"')
            elif line.startswith("H: Handlers="):
                dev["handlers"] = line[12:]
            elif line.startswith("B: "):
                key, _, val = line[3:].partition("=")
                if key in ("KEY", "ABS", "PROP"):
                    try:
                        dev[key] = _bits(val)
                    except ValueError:
                        pass
        if dev["name"] or dev["handlers"]:
            devices.append(dev)
    return devices


def has_hardware_keyboard(devices=None):
    """A keyboard with letters is plugged in (USB, Bluetooth, laptop keyboard)."""
    for dev in input_devices() if devices is None else devices:
        if "kbd" in dev["handlers"] and all(dev["KEY"] >> k & 1 for k in _LETTER_KEYS):
            return True
    return False


def has_touchscreen(devices=None):
    """A touchscreen (multi-touch, drawn directly on the screen: not a touchpad)."""
    for dev in input_devices() if devices is None else devices:
        if dev["ABS"] >> _ABS_MT_POSITION_X & 1 and dev["PROP"] >> _INPUT_PROP_DIRECT & 1:
            return True
    return False


def run_async(argv, callback=None):
    """Run a command without blocking; callback(stdout or None)."""
    if not shutil.which(argv[0]):
        if callback:
            callback(None)
        return
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE |
                                  Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error:
        if callback:
            callback(None)
        return

    def done(p, res):
        try:
            _ok, out, _err = p.communicate_utf8_finish(res)
        except GLib.Error:
            out = None
        if callback:
            callback(out)
    proc.communicate_utf8_async(None, None, done)


# ------------------------------------------------------------------ audio
def get_volume(callback):
    """callback(volume 0..1.5, muted) — uses PipeWire's wpctl, falls back to pactl."""
    def parse_wp(out):
        if out:
            m = re.search(r"Volume:\s*([\d.]+)", out)
            if m:
                callback(float(m.group(1)), "MUTED" in out)
                return
        run_async(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], parse_pa)

    def parse_pa(out):
        m = re.search(r"(\d+)%", out or "")
        callback(int(m.group(1)) / 100 if m else None, False)
    run_async(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], parse_wp)


def set_volume(value):
    value = max(0.0, min(1.0, value))
    if shutil.which("wpctl"):
        run_async(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value:.2f}"])
    else:
        run_async(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(value * 100)}%"])


def toggle_mute():
    if shutil.which("wpctl"):
        run_async(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    else:
        run_async(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])


def volume_icon(vol, muted):
    if vol is None:
        return "audio-volume-muted-symbolic"
    if muted or vol <= 0.001:
        return "audio-volume-muted-symbolic"
    if vol < 0.34:
        return "audio-volume-low-symbolic"
    if vol < 0.67:
        return "audio-volume-medium-symbolic"
    return "audio-volume-high-symbolic"


# ------------------------------------------------------------- brightness
def _backlight():
    devs = sorted(glob.glob("/sys/class/backlight/*"))
    if devs:
        return devs[0]
    # phones often drive the panel through an LED class device
    devs = sorted(glob.glob("/sys/class/leds/*backlight*"))
    return devs[0] if devs else None


def get_brightness():
    dev = _backlight()
    if not dev:
        return None
    try:
        with open(os.path.join(dev, "brightness")) as f:
            cur = int(f.read())
        with open(os.path.join(dev, "max_brightness")) as f:
            mx = int(f.read())
        return cur / mx if mx else None
    except (OSError, ValueError):
        return None


def set_brightness(value):
    """Uses logind's SetBrightness so no root/udev rules are needed."""
    dev = _backlight()
    if not dev:
        return
    try:
        with open(os.path.join(dev, "max_brightness")) as f:
            mx = int(f.read())
    except (OSError, ValueError):
        return
    level = max(1, int(mx * max(0.01, min(1.0, value))))
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        bus.call("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                 "org.freedesktop.login1.Session", "SetBrightness",
                 GLib.Variant("(ssu)", (os.path.basename(os.path.dirname(dev)),
                                        os.path.basename(dev), level)),
                 None, Gio.DBusCallFlags.NONE, -1, None, None)
    except GLib.Error:
        if shutil.which("brightnessctl"):
            run_async(["brightnessctl", "set", str(level)])


# ------------------------------------------------------------------ torch
def _torch():
    """The flash LED used as torch (phones: an LED class device *:torch or *:flash)."""
    devs = sorted(glob.glob("/sys/class/leds/*:torch")) or sorted(glob.glob("/sys/class/leds/*:flash"))
    return devs[0] if devs else None


def get_torch():
    """True/False, or None without a torch LED."""
    dev = _torch()
    if not dev:
        return None
    try:
        with open(os.path.join(dev, "brightness")) as f:
            return int(f.read()) > 0
    except (OSError, ValueError):
        return None


def set_torch(on):
    """Like set_brightness through logind (the leds subsystem), full torch brightness."""
    dev = _torch()
    if not dev:
        return
    try:
        with open(os.path.join(dev, "max_brightness")) as f:
            level = int(f.read()) if on else 0
    except (OSError, ValueError):
        return
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        bus.call("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                 "org.freedesktop.login1.Session", "SetBrightness",
                 GLib.Variant("(ssu)", ("leds", os.path.basename(dev), level)),
                 None, Gio.DBusCallFlags.NONE, -1, None, None)
    except GLib.Error:
        if shutil.which("brightnessctl"):
            run_async(["brightnessctl", "-d", os.path.basename(dev), "set", str(level)])


# ---------------------------------------------------------------- network
class Network:
    def __init__(self, on_change):
        self.client = None
        self.on_change = on_change
        try:
            import gi
            gi.require_version("NM", "1.0")
            from gi.repository import NM
            self.NM = NM
            NM.Client.new_async(None, self._ready)
        except (ImportError, ValueError):
            pass

    def _ready(self, _src, res):
        try:
            self.client = self.NM.Client.new_finish(res)
        except GLib.Error:
            return
        for prop in ("primary-connection", "wireless-enabled", "connectivity"):
            self.client.connect(f"notify::{prop}", lambda *_: self.on_change())
        self.on_change()

    def wifi_enabled(self):
        return bool(self.client and self.client.wireless_get_enabled())

    def set_wifi(self, on):
        run_async(["nmcli", "radio", "wifi", "on" if on else "off"],
                  lambda _o: GLib.timeout_add(600, lambda: (self.on_change(), False)[1]))

    def status(self):
        """(icon_name, label)"""
        if not self.client:
            return "network-offline-symbolic", "Netzwerk"
        ac = self.client.get_primary_connection()
        if not ac:
            return ("network-wireless-offline-symbolic" if self.wifi_enabled()
                    else "network-offline-symbolic"), "Nicht verbunden"
        ctype = ac.get_connection_type() or ""
        name = ac.get_id() or ""
        if "wireless" in ctype:
            strength = 0
            for dev in ac.get_devices() or []:
                if isinstance(dev, self.NM.DeviceWifi) and dev.get_active_access_point():
                    strength = dev.get_active_access_point().get_strength()
            lvl = ("excellent" if strength > 75 else "good" if strength > 50
                   else "ok" if strength > 25 else "weak")
            return f"network-wireless-signal-{lvl}-symbolic", name
        if "vpn" in ctype or "wireguard" in ctype:
            return "network-vpn-symbolic", name
        return "network-wired-symbolic", name


# -------------------------------------------------------------- bluetooth
def get_bluetooth(callback):
    def parse(out):
        if out is None or "No default controller" in (out or ""):
            callback(None)
        else:
            callback("Powered: yes" in out)
    run_async(["bluetoothctl", "show"], parse)


def get_bluetooth_devices(callback):
    """callback(list of (address, name, connected)) — paired & discovered devices."""
    def parse(out):
        devices = []
        for line in (out or "").splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0] == "Device":
                devices.append((parts[1], parts[2]))
        return devices

    def got_all(out):
        def got_connected(connected_out):
            connected = {addr for addr, _name in parse(connected_out)}
            callback([(addr, name, addr in connected) for addr, name in parse(out)])
        run_async(["bluetoothctl", "devices", "Connected"], got_connected)
    run_async(["bluetoothctl", "devices"], got_all)


def bluetooth_device_info(address, callback):
    """callback(dict with Connected, Paired, Trusted, Name, Icon)."""
    def parse(out):
        info = {}
        if out:
            for line in out.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
        callback(info)
    run_async(["bluetoothctl", "info", address], parse)


def bluetooth_connect(address, done=None):
    run_async(["bluetoothctl", "connect", address],
              lambda _o: (done and done()))


def bluetooth_disconnect(address, done=None):
    run_async(["bluetoothctl", "disconnect", address],
              lambda _o: (done and done()))


def set_bluetooth(on, done=None):
    run_async(["bluetoothctl", "power", "on" if on else "off"], lambda _o: done and done())


# ------------------------------------------------------------------ power
def logind_call(method, *args):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        sig = "(" + "b" * len(args) + ")"
        bus.call("org.freedesktop.login1", "/org/freedesktop/login1",
                 "org.freedesktop.login1.Manager", method,
                 GLib.Variant(sig, args) if args else None, None,
                 Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, -1, None, None)
    except GLib.Error as e:
        print("nothing-de: logind", method, "failed:", e.message)


def suspend():
    logind_call("Suspend", True)


def reboot():
    logind_call("Reboot", True)


def poweroff():
    logind_call("PowerOff", True)
