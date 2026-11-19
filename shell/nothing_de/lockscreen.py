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
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from . import dotmatrix, livewall, system
from .phone_extras import power_menu_box
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


KEY_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm", "!@#$%&*?-_.,/"]


def _on_screen_keyboard(entry, compact=False):
    """Keys that type into the password entry; ⌫ deletes, ↵ submits. Rows take the width
    of the screen, like a phone keyboard. `compact`: lower keys for a flat (landscape) screen."""
    board = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6 if compact else 8)
    board.set_margin_top(6 if compact else 18)
    if compact:
        board.add_css_class("n-keyboard-compact")
    board.set_margin_start(6)
    board.set_margin_end(6)

    def press(label, action):
        key = Gtk.Button(label=label)
        key.add_css_class("n-key")
        key.set_focusable(False)
        key.connect("clicked", lambda *_: action())
        return key

    def typed(ch):
        return lambda: entry.set_text(entry.get_text() + ch)

    widest = len(KEY_ROWS[0])
    for row in KEY_ROWS:
        # shorter rows are indented by half a key per missing key, as on a real keyboard
        line = Gtk.Box(spacing=5, homogeneous=True, halign=Gtk.Align.FILL)
        pad = max(0, widest - len(row)) * 0.5
        line.set_margin_start(int(pad * 46))
        line.set_margin_end(int(pad * 46))
        for ch in row:
            line.append(press(ch, typed(ch)))
        board.append(line)
    bottom = Gtk.Box(spacing=5)
    back = press("⌫", lambda: entry.set_text(entry.get_text()[:-1]))
    back.set_size_request(80, -1)
    bottom.append(back)
    space = press("␣", typed(" "))
    space.set_hexpand(True)
    bottom.append(space)
    enter = press("↵", lambda: entry.emit("activate"))
    enter.set_size_request(80, -1)
    enter.add_css_class("n-key-accent")
    bottom.append(enter)
    board.append(bottom)
    return board


def avatar_path(user):
    """The user's picture: AccountsService's icon or ~/.face, like GDM shows it."""
    for path in (os.path.join("/var/lib/AccountsService/icons", user),
                 os.path.expanduser("~/.face"), os.path.expanduser("~/.face.icon")):
        try:
            if os.path.isfile(path) and os.access(path, os.R_OK) and os.path.getsize(path) > 0:
                return path
        except OSError:
            continue
    return None


def _avatar_texture(path, size):
    """The picture cut to a centred square of size×size pixels (×2 for HiDPI)."""
    px = size * 2
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error:
        return None
    w, h = pb.get_width(), pb.get_height()
    side = min(w, h)
    pb = pb.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side)
    pb = pb.scale_simple(px, px, GdkPixbuf.InterpType.BILINEAR)
    return Gdk.Texture.new_for_pixbuf(pb)


def user_avatar(user, size=84):
    """A round picture of the user; without one, the initial on the accent colour."""
    frame = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    frame.add_css_class("n-avatar")
    frame.set_size_request(size, size)
    frame.set_overflow(Gtk.Overflow.HIDDEN)
    path = avatar_path(user)
    texture = _avatar_texture(path, size) if path else None
    if texture is not None:
        # scaled down beforehand: a Gtk.Picture asks for its picture's full size, a large
        # ~/.face would blow the circle up to fill the lock screen
        pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                          hexpand=True, vexpand=True)
        pic.set_paintable(texture)
        frame.append(pic)
    else:
        frame.add_css_class("n-avatar-initial")
        label = Gtk.Label(label=(user[:1] or "?").upper(), hexpand=True)
        frame.append(label)
    return frame


class Logind:
    """The login session in logind: LockedHint follows our lock screen (the fingerprint
    service of the phone port only scans while it is set), and logind's Unlock (e.g.
    `loginctl unlock-session` after a fingerprint match) and Lock signals are followed."""

    def __init__(self, on_lock, on_unlock):
        self.bus = self.path = None
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
            res = self.bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                                     "org.freedesktop.login1.Manager", "GetSessionByPID",
                                     GLib.Variant("(u)", (os.getpid(),)),
                                     GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 2000)
            self.path = res.unpack()[0]
        except GLib.Error:
            return
        for signal, cb in (("Lock", on_lock), ("Unlock", on_unlock)):
            self.bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Session",
                                      signal, self.path, None, Gio.DBusSignalFlags.NONE,
                                      lambda *_a, cb=cb: cb())

    def set_locked_hint(self, locked):
        if not self.path:
            return
        self.bus.call("org.freedesktop.login1", self.path, "org.freedesktop.login1.Session",
                      "SetLockedHint", GLib.Variant("(b)", (locked,)), None,
                      Gio.DBusCallFlags.NONE, -1, None, None)


class LockScreen:
    def __init__(self, shell):
        self.shell = shell
        self.instance = None
        self.windows = []
        self.user = getpass.getuser()
        self.logind = Logind(self.lock, self.unlock)

    def show_power_menu(self):
        """Long press on the power key while locked: the menu shows on the lock screen."""
        for win in self.windows:
            if getattr(win, "n_power", None) is not None:
                continue
            scrim = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.FILL,
                            halign=Gtk.Align.FILL)
            scrim.add_css_class("n-scrim")
            scrim.add_css_class("dim")
            menu = power_menu_box(lambda w=win: self._close_power_menu(w))
            menu.set_valign(Gtk.Align.CENTER)
            menu.set_vexpand(True)
            menu.set_margin_start(24)
            menu.set_margin_end(24)
            scrim.append(menu)
            win.n_overlay.add_overlay(scrim)
            win.n_power = scrim

    def _close_power_menu(self, win):
        if getattr(win, "n_power", None) is not None:
            win.n_overlay.remove_overlay(win.n_power)
            win.n_power = None

    def unlock(self):
        """Unlock without a password (logind's Unlock, after a fingerprint match)."""
        if self.instance is not None:
            self.instance.unlock()

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
        self.logind.set_locked_hint(True)
        if not has_monitor_signal:
            monitors = Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                self._window_for(monitors.get_item(i))

    def _cleanup(self):
        for w in self.windows:
            w.destroy()
        self.windows = []
        self.instance = None
        self.logind.set_locked_hint(False)

    def _background(self):
        """The wallpaper behind the lock screen, dimmed so the clock stays readable;
        plain background colour if switched off or there is no picture."""
        cfg = self.shell.cfg
        key = "phone.wallpaper" if self.shell.phone else "wallpaper"
        path = cfg.get(key) or "" if cfg.get("lock.wallpaper", True) else ""
        # a picture, a video or an animated scene (livewall)
        pic = livewall.wallpaper_widget(path, fps=int(cfg.get("wallpaper_fps") or 20))
        if pic is None:
            return Gtk.Box(hexpand=True, vexpand=True)
        stack = Gtk.Overlay()
        stack.set_child(pic)
        scrim = Gtk.Box(hexpand=True, vexpand=True)
        scrim.add_css_class("n-lock-scrim")
        stack.add_overlay(scrim)
        return stack

    def _window_for(self, monitor):
        win = Gtk.Window(application=self.shell.app)
        win.add_css_class("n-root")
        win.add_css_class("n-lock")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        now = datetime.datetime.now()
        day = Gtk.Label(label=f"{WEEKDAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}")
        day.add_css_class("n-caps")
        user = Gtk.Label(label=self.user.upper())
        user.add_css_class("n-caps")
        user.set_margin_top(40)
        # the phone types on screen; the phone layout on a computer has a real keyboard
        osk = bool(self.shell.phone) and (system.has_touchscreen()
                                          or not system.has_hardware_keyboard())
        geo = monitor.get_geometry() if monitor is not None else None
        short = bool(geo and geo.height < 720)
        # a low screen with the on-screen keyboard: smaller clock and no picture, the keys
        # need the room
        clock = dotmatrix.DotLabel(now.strftime("%H:%M"), pitch=9 if osk and short else 16,
                                   show_dim=True, align=0.5)
        clock.set_halign(Gtk.Align.CENTER)
        avatar = None
        if self.shell.cfg.get("lock.avatar", True) and not (osk and short):
            avatar = user_avatar(self.user)
            avatar.set_margin_top(40)
            user.set_margin_top(0)
        entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Passwort")
        entry.set_halign(Gtk.Align.CENTER)
        # GTK's simple input method instead of the compositor's (text-input): the lock
        # screen brings its own keys, and a Wayland input context left behind by the
        # destroyed entry would pop up the on-screen keyboard on the shell's next window
        entry.get_delegate().set_property("im-module", "gtk-im-context-simple")
        status = Gtk.Label()
        status.add_css_class("n-accent-text")
        for w in (day, clock, avatar, user, entry, status):
            if w is not None:
                box.append(w)
        if osk:
            # no hardware keyboard on the phone: type the password on screen
            box.set_halign(Gtk.Align.FILL)
            box.set_valign(Gtk.Align.END)
            box.set_margin_bottom(12 if short else 28)
            entry.set_size_request(300, -1)
            if short:
                # everything has to fit above the keys on a flat screen
                box.set_spacing(6)
                user.set_margin_top(0)
            box.append(_on_screen_keyboard(entry, compact=short))
        overlay = Gtk.Overlay(child=self._background())
        overlay.add_overlay(box)
        win.n_overlay = overlay
        win.n_power = None
        win.n_entry = entry
        win.n_status = status
        win.set_child(overlay)

        def tick():
            if win not in self.windows:
                return False
            clock.set_text(datetime.datetime.now().strftime("%H:%M"))
            return True
        GLib.timeout_add_seconds(5, tick)

        def mirror(_e):
            # one lock window per monitor: what is typed shows on every screen, whichever
            # of them has the keyboard
            text = entry.get_text()
            for other in self.windows:
                if other is not win and other.n_entry.get_text() != text:
                    other.n_entry.set_text(text)
        entry.connect("changed", mirror)

        def set_all(sensitive, label, error=False):
            for other in self.windows:
                other.n_entry.set_sensitive(sensitive)
                other.n_status.set_label(label)
                if error:
                    other.n_entry.add_css_class("error")
                    other.n_entry.set_text("")

        def submit(_e):
            pw = entry.get_text()
            set_all(False, "…")

            def work():
                ok = check_password(self.user, pw)
                GLib.idle_add(done, ok)

            def done(ok):
                if ok and self.instance:
                    self.instance.unlock()
                    return False
                set_all(True, "Falsches Passwort", error=True)
                entry.grab_focus()
                return False
            threading.Thread(target=work, daemon=True).start()
        entry.connect("activate", submit)
        self.instance.assign_window_to_monitor(win, monitor)
        if self.windows:
            entry.set_text(self.windows[0].n_entry.get_text())
        self.windows.append(win)
        win.present()
        entry.grab_focus()
