"""System integration helpers: audio, brightness, network, bluetooth, power."""
import glob
import os
import re
import shutil

from gi.repository import Gio, GLib


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
                 GLib.Variant("(ssu)", ("backlight", os.path.basename(dev), level)),
                 None, Gio.DBusCallFlags.NONE, -1, None, None)
    except GLib.Error:
        if shutil.which("brightnessctl"):
            run_async(["brightnessctl", "set", str(level)])


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
