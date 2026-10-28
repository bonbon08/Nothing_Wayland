"""nothing-shell: bar, dock, desktop, launcher, control centre, notifications."""
import datetime
import os
import shutil
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import layer  # noqa: E402
from .apps import AppIndex, launch_app, spawn  # noqa: E402
from .bar import TopBar  # noqa: E402
from .config import get_config, terminal_command  # noqa: E402
from .control import ControlCenter  # noqa: E402
from .desktop import DesktopWindow  # noqa: E402
from .dock import Dock  # noqa: E402
from .ipc import WindowManager  # noqa: E402
from .launcher import Launcher  # noqa: E402
from .lockscreen import LockScreen  # noqa: E402
from .notifications import Notifications  # noqa: E402
from .theme import ThemeManager  # noqa: E402


class Shell:
    def __init__(self, app):
        self.app = app
        self.cfg = get_config()
        self.theme = ThemeManager(self.cfg)
        self.apps = AppIndex()
        self.wm = WindowManager()
        self.per_monitor = {}
        self.dock = None
        self.launcher = Launcher(self)
        self.control = ControlCenter(self)
        self.notifications = Notifications(self)
        self.lockscreen = LockScreen(self)

        self.wm.connect("action", lambda _w, name: self.run_action(name))
        self.wm.connect("connected", lambda *_: self.push_wm_config())
        self.cfg.connect("changed", lambda *_: self.push_wm_config())
        if self.wm.available:
            self.push_wm_config()

        monitors = Gdk.Display.get_default().get_monitors()
        monitors.connect("items-changed", lambda *_: self.sync_monitors())
        self.sync_monitors()
        self.autostart()

    # ---------------------------------------------------------- monitors
    def sync_monitors(self):
        monitors = Gdk.Display.get_default().get_monitors()
        current = [monitors.get_item(i) for i in range(monitors.get_n_items())]
        for mon in list(self.per_monitor):
            if mon not in current:
                for win in self.per_monitor.pop(mon):
                    win.destroy()
        for i, mon in enumerate(current):
            if mon in self.per_monitor:
                continue
            primary = i == 0
            wins = [DesktopWindow(self, mon, primary), TopBar(self, mon)]
            self.per_monitor[mon] = wins
            for w in wins:
                w.present()
        if self.dock is None or self.dock.get_root() is None:
            if current:
                self.dock = Dock(self, current[0])
                self.dock.present()
        if not layer.supported():
            print("nothing-shell: layer-shell not available — showing preview windows")

    def bar_net(self):
        for wins in self.per_monitor.values():
            return wins[1].net
        return None

    # -------------------------------------------------------- compositor
    def push_wm_config(self):
        kb = self.cfg.get("keyboard") or {}
        self.wm.config("workspaces", int(self.cfg.get("workspaces") or 4))
        self.wm.config("accent", self.cfg.get("accent"))
        self.wm.config("dark", 0 if self.cfg.get("theme") == "light" else 1)
        if kb.get("layout"):
            self.wm.config("kb_layout", kb.get("layout"))
        self.wm.config("kb_variant", kb.get("variant") or "")
        self.wm.config("kb_options", kb.get("options") or "")

    # ----------------------------------------------------------- actions
    def run_action(self, name):
        if name == "launcher":
            self.control.close_overlay()
            self.launcher.toggle()
        elif name == "control":
            self.launcher.close_overlay()
            self.control.toggle()
        elif name == "terminal":
            cmd = terminal_command(self.cfg)
            if cmd:
                spawn(cmd)
            else:
                self.notify("Kein Terminal gefunden", "In den Einstellungen festlegen.")
        elif name == "files":
            cmd = self.cfg.get("files")
            if cmd:
                spawn(cmd)
            else:
                app = Gio.AppInfo.get_default_for_type("inode/directory", False)
                if app:
                    launch_app(app, [Gio.File.new_for_path(os.path.expanduser("~")).get_uri()])
        elif name == "settings":
            self.spawn_settings()
        elif name == "lock":
            self.lockscreen.lock()
        elif name == "screenshot":
            self.screenshot()

    def spawn_settings(self, page=None):
        argv = ["nothing-settings"] + (["--page", page] if page else [])
        if not shutil.which("nothing-settings"):
            here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            argv[0] = os.path.join(here, "bin", "nothing-settings")
        spawn(argv)

    def screenshot(self):
        if not shutil.which("grim"):
            self.notify("Bildschirmfoto", "Bitte „grim“ (und optional „slurp“) installieren.")
            return
        pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~")
        folder = os.path.join(pics, "Bildschirmfotos")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, datetime.datetime.now().strftime("Bildschirmfoto_%Y-%m-%d_%H-%M-%S.png"))
        cmd = ["grim", path]
        if shutil.which("wl-copy"):
            cmd = ["sh", "-c", f'grim "{path}" && wl-copy < "{path}"']
        spawn(cmd)
        GLib.timeout_add(700, lambda: (self.notify("Bildschirmfoto gespeichert", path), False)[1])

    def notify(self, summary, body=""):
        self.notifications.notify(summary, body)

    # --------------------------------------------------------- autostart
    def autostart(self):
        """Run XDG autostart entries once per session."""
        flag = os.path.join(GLib.get_user_runtime_dir(), f"nothing-autostart-{os.environ.get('WAYLAND_DISPLAY', '')}")
        if os.path.exists(flag) or not self.wm.available or os.environ.get("NOTHING_NO_AUTOSTART"):
            return
        open(flag, "w").close()
        seen = set()
        dirs = [os.path.join(GLib.get_user_config_dir(), "autostart")] + \
               [os.path.join(d, "autostart") for d in GLib.get_system_config_dirs()]
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if not name.endswith(".desktop") or name in seen:
                    continue
                seen.add(name)
                try:
                    info = Gio.DesktopAppInfo.new_from_filename(os.path.join(d, name))
                except TypeError:
                    info = None
                if info is None or info.get_is_hidden():
                    continue
                if info.has_key("Hidden") and info.get_boolean("Hidden"):
                    continue
                if not info.get_show_in("Nothing"):
                    continue
                launch_app(info)


class ShellApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="eu.nothing_de.Shell",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.shell = None

    def do_activate(self):
        if self.shell is None:
            self.hold()
            self.shell = Shell(self)


def main():
    app = ShellApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
