"""Desktop entry index: maps window app_ids / X11 classes to .desktop apps."""
import os
import shlex
import subprocess

from gi.repository import Gdk, Gio, GLib


class AppIndex:
    def __init__(self):
        self.apps = []
        self.by_key = {}
        self._monitor = Gio.AppInfoMonitor.get()
        self._monitor.connect("changed", lambda *_: self.reload())
        self.listeners = []
        self.reload()

    def reload(self):
        self.apps = []
        self.by_key = {}
        for app in Gio.AppInfo.get_all():
            if not isinstance(app, Gio.DesktopAppInfo):
                continue
            aid = app.get_id() or ""
            keys = {aid.lower(), aid.lower().removesuffix(".desktop")}
            wm = app.get_startup_wm_class()
            if wm:
                keys.add(wm.lower())
            exe = app.get_executable()
            if exe:
                keys.add(os.path.basename(exe).lower())
            # reverse-DNS ids: org.gnome.Nautilus -> nautilus
            base = aid.removesuffix(".desktop")
            if "." in base:
                keys.add(base.rsplit(".", 1)[-1].lower())
            for k in keys:
                if k:
                    self.by_key.setdefault(k, app)
            if app.should_show():
                self.apps.append(app)
        self.apps.sort(key=lambda a: (a.get_display_name() or "").lower())
        for cb in self.listeners:
            cb()

    def get(self, desktop_id):
        try:
            return Gio.DesktopAppInfo.new(desktop_id)
        except TypeError:
            return None

    def lookup(self, app_id):
        if not app_id:
            return None
        key = app_id.lower()
        for k in (key, key.removesuffix(".desktop"), key.rsplit(".", 1)[-1],
                  key.replace(" ", "-")):
            if k in self.by_key:
                return self.by_key[k]
        app = self.get(app_id + ".desktop")
        if app:
            return app
        results = Gio.DesktopAppInfo.search(app_id)
        if results and results[0]:
            return self.get(results[0][0])
        return None

    def search(self, query):
        q = query.lower().strip()
        if not q:
            return list(self.apps)
        scored = []
        for app in self.apps:
            name = (app.get_display_name() or "").lower()
            kw = " ".join(app.get_keywords() or []).lower()
            gen = (app.get_generic_name() or "").lower()
            if name.startswith(q):
                s = 0
            elif q in name:
                s = 1
            elif q in gen or q in kw:
                s = 2
            elif q in (app.get_description() or "").lower():
                s = 3
            else:
                continue
            scored.append((s, name, app))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [t[2] for t in scored]


def launch_app(app, uris=None):
    if app is None:
        return False
    ctx = Gdk.Display.get_default().get_app_launch_context()
    try:
        return app.launch_uris(uris or [], ctx)
    except GLib.Error as e:
        print("nothing-de: launch failed:", e.message)
        return False


def spawn(cmd):
    """Run a shell-ish command line detached from the shell."""
    if not cmd:
        return
    try:
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        subprocess.Popen(argv, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        print("nothing-de: cannot run", cmd, e)


def app_icon(app):
    """App icon, falling back to a generic one if the theme lacks it."""
    fallback = Gio.ThemedIcon.new("application-x-executable")
    icon = app.get_icon() if app is not None else None
    if icon is None:
        return fallback
    if isinstance(icon, Gio.ThemedIcon):
        from gi.repository import Gtk
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        names = [n for n in icon.get_names() if theme.has_icon(n)]
        if not names:
            return fallback
        # GTK 4 cannot render XPM icons (e.g. xterm), they would stay blank
        found = theme.lookup_icon(names[0], None, 48, 1, Gtk.TextDirection.NONE, 0)
        f = found.get_file() if found else None
        if f and (f.get_path() or "").endswith(".xpm"):
            return fallback
    elif isinstance(icon, Gio.FileIcon) and not icon.get_file().query_exists(None):
        return fallback
    return icon
