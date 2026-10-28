"""Lock screen using ext-session-lock (via gtk4-layer-shell's Gtk4SessionLock).

The password is verified with the setuid helper `unix_chkpwd` from PAM's
pam_unix, so no extra Python modules are required."""
import datetime
import getpass
import os
import shutil
import subprocess
import threading

import gi
from gi.repository import Gdk, GLib, Gtk

from . import dotmatrix
from .widgets import MONTHS, WEEKDAYS

try:
    gi.require_version("Gtk4SessionLock", "1.0")
    from gi.repository import Gtk4SessionLock
except (ValueError, ImportError):
    Gtk4SessionLock = None


def check_password(user, password):
    helper = shutil.which("unix_chkpwd") or "/usr/bin/unix_chkpwd"
    if not os.path.exists(helper):
        return False
    try:
        p = subprocess.run([helper, user, "nullok"], input=password.encode() + b"\0",
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class LockScreen:
    def __init__(self, shell):
        self.shell = shell
        self.instance = None
        self.windows = []
        self.user = getpass.getuser()

    @property
    def available(self):
        return Gtk4SessionLock is not None and Gtk4SessionLock.is_supported()

    def lock(self):
        if self.instance is not None:
            return
        if not self.available:
            for cmd in ("swaylock", "gtklock", "hyprlock"):
                if shutil.which(cmd):
                    subprocess.Popen([cmd], start_new_session=True)
                    return
            self.shell.notify("Sperren nicht möglich", "Kein Session-Lock verfügbar.")
            return
        self.instance = Gtk4SessionLock.Instance.new()
        self.instance.connect("unlocked", lambda *_: self._cleanup())
        self.instance.connect("failed", lambda *_: self._cleanup())
        has_monitor_signal = True
        try:
            self.instance.connect("monitor", lambda _i, mon: self._window_for(mon))
        except TypeError:
            has_monitor_signal = False
        if not self.instance.lock():
            self._cleanup()
            return
        if not has_monitor_signal:
            monitors = Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                self._window_for(monitors.get_item(i))

    def _cleanup(self):
        for w in self.windows:
            w.destroy()
        self.windows = []
        self.instance = None

    def _window_for(self, monitor):
        win = Gtk.Window(application=self.shell.app)
        win.add_css_class("n-root")
        win.add_css_class("n-lock")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        now = datetime.datetime.now()
        day = Gtk.Label(label=f"{WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}")
        day.add_css_class("n-caps")
        clock = dotmatrix.DotLabel(now.strftime("%H:%M"), pitch=16, show_dim=True, align=0.5)
        clock.set_halign(Gtk.Align.CENTER)
        user = Gtk.Label(label=self.user.upper())
        user.add_css_class("n-caps")
        user.set_margin_top(40)
        entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Passwort")
        entry.set_halign(Gtk.Align.CENTER)
        status = Gtk.Label()
        status.add_css_class("n-accent-text")
        for w in (day, clock, user, entry, status):
            box.append(w)
        win.set_child(box)

        def tick():
            if win not in self.windows:
                return False
            clock.set_text(datetime.datetime.now().strftime("%H:%M"))
            return True
        GLib.timeout_add_seconds(5, tick)

        def submit(_e):
            pw = entry.get_text()
            entry.set_sensitive(False)
            status.set_label("…")

            def work():
                ok = check_password(self.user, pw)
                GLib.idle_add(done, ok)

            def done(ok):
                if ok and self.instance:
                    self.instance.unlock()
                    return False
                entry.set_sensitive(True)
                entry.set_text("")
                entry.add_css_class("error")
                status.set_label("Falsches Passwort")
                entry.grab_focus()
                return False
            threading.Thread(target=work, daemon=True).start()
        entry.connect("activate", submit)
        self.instance.assign_window_to_monitor(win, monitor)
        self.windows.append(win)
        win.present()
        entry.grab_focus()
