"""Top bar (macOS-like menu bar, Nothing styling)."""
import datetime
import math

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import layer, system
from .theme import hex_to_rgb
from .widgets import read_battery

WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


class TopBar(Gtk.ApplicationWindow):
    def __init__(self, shell, monitor):
        super().__init__(application=shell.app)
        self.shell = shell
        self.cfg = shell.cfg
        self.wm = shell.wm
        layer.setup(self, layer="top", anchors=("top", "left", "right"),
                    exclusive="auto", namespace="nothing-bar", monitor=monitor)
        self.add_css_class("n-root")

        bar = Gtk.CenterBox()
        bar.add_css_class("n-bar")
        self.set_child(bar)

        # ---------------------------------------------------- left side
        left = Gtk.Box(spacing=2)
        self.logo = Gtk.MenuButton()
        logo_art = Gtk.DrawingArea(content_width=16, content_height=16)
        logo_art.set_draw_func(self._draw_logo)
        self.logo.set_child(logo_art)
        self.logo.set_menu_model(self._system_menu())
        self.logo.set_tooltip_text("System")
        self.logo.get_popover().add_css_class("n-menu")
        self.logo_art = logo_art
        left.append(self.logo)

        self.app_btn = Gtk.MenuButton()
        self.app_label = Gtk.Label(label="Schreibtisch")
        self.app_label.add_css_class("n-appname")
        self.app_btn.set_child(self.app_label)
        self.app_btn.set_menu_model(self._window_menu())
        self.app_btn.get_popover().add_css_class("n-menu")
        left.append(self.app_btn)

        self.title_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=60)
        self.title_label.add_css_class("n-muted")
        self.title_label.set_margin_start(6)
        left.append(self.title_label)
        bar.set_start_widget(left)

        # --------------------------------------------------- centre: workspaces
        self.ws_box = Gtk.Box(spacing=0)
        self.ws_box.set_valign(Gtk.Align.CENTER)
        bar.set_center_widget(self.ws_box)

        # ----------------------------------------------------- right side
        right = Gtk.Box(spacing=2)
        status = Gtk.Button()
        sbox = Gtk.Box(spacing=10)
        self.net_icon = Gtk.Image(icon_name="network-offline-symbolic")
        self.vol_icon = Gtk.Image(icon_name="audio-volume-high-symbolic")
        self.bat_icon = Gtk.Image(icon_name="battery-full-symbolic")
        self.bat_label = Gtk.Label()
        self.bat_label.add_css_class("n-clock")
        for w in (self.net_icon, self.vol_icon, self.bat_icon, self.bat_label):
            sbox.append(w)
        status.set_child(sbox)
        status.set_tooltip_text("Kontrollzentrum")
        status.connect("clicked", lambda *_: shell.run_action("control"))
        right.append(status)

        self.clock_btn = Gtk.MenuButton()
        self.clock = Gtk.Label()
        self.clock.add_css_class("n-clock")
        self.clock_btn.set_child(self.clock)
        cal_pop = Gtk.Popover()
        cal_pop.add_css_class("n-menu")
        cal = Gtk.Calendar()
        cal_pop.set_child(cal)
        cal_pop.connect("show", lambda *_: cal.select_day(GLib.DateTime.new_now_local()))
        self.clock_btn.set_popover(cal_pop)
        right.append(self.clock_btn)
        bar.set_end_widget(right)

        self.net = system.Network(self._update_net)
        self.wm.connect("state", lambda _w, st: self.update_state(st))
        self.cfg.connect("changed", lambda *_: (self.update_state(self.wm.state), self.logo_art.queue_draw()))
        self.update_state(self.wm.state)
        self._tick()
        GLib.timeout_add_seconds(1, self._tick)
        self._slow_tick()
        GLib.timeout_add_seconds(5, self._slow_tick)

    # ------------------------------------------------------------ drawing
    def _draw_logo(self, area, cr, w, h):
        fg = area.get_color()
        acc = hex_to_rgb(self.cfg.get("accent"))
        # 3x3 dot grid with the accent in the corner — a nod to Nothing's glyphs
        p = w / 3
        for i in range(3):
            for j in range(3):
                if i == 2 and j == 0:
                    cr.set_source_rgba(acc[0], acc[1], acc[2], 1)
                else:
                    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
                cr.arc(i * p + p / 2, j * p + p / 2, p * 0.33, 0, 2 * math.pi)
                cr.fill()

    # -------------------------------------------------------------- menus
    def _system_menu(self):
        group = Gio.SimpleActionGroup()
        acts = {
            "about": lambda: self.shell.spawn_settings("about"),
            "settings": lambda: self.shell.spawn_settings(),
            "lock": lambda: self.shell.run_action("lock"),
            "suspend": system.suspend,
            "reboot": system.reboot,
            "poweroff": system.poweroff,
            "logout": self.wm.exit,
            "launcher": lambda: self.shell.run_action("launcher"),
        }
        for name, cb in acts.items():
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(a)
        self.insert_action_group("sys", group)
        m = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("Über diesen Computer", "sys.about")
        s1.append("Systemeinstellungen …", "sys.settings")
        s1.append("Apps", "sys.launcher")
        m.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append("Bildschirm sperren", "sys.lock")
        s2.append("Bereitschaft", "sys.suspend")
        s2.append("Neu starten …", "sys.reboot")
        s2.append("Ausschalten …", "sys.poweroff")
        m.append_section(None, s2)
        s3 = Gio.Menu()
        s3.append("Abmelden", "sys.logout")
        m.append_section(None, s3)
        return m

    def _window_menu(self):
        group = Gio.SimpleActionGroup()

        def focused():
            return self.wm.state.get("focused") or 0

        for name, cb in {
            "minimize": lambda: self.wm.minimize(focused()),
            "maximize": lambda: self.wm.maximize(focused()),
            "fullscreen": lambda: self.wm.send("fullscreen", focused()),
            "close": lambda: self.wm.close(focused()),
            "newwin": self._new_window,
        }.items():
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, cb=cb: cb())
            group.add_action(a)
        mv = Gio.SimpleAction.new("moveto", GLib.VariantType.new("i"))
        mv.connect("activate", lambda _a, p: self.wm.move_to(focused(), p.get_int32()))
        group.add_action(mv)
        self.insert_action_group("win", group)
        self._ws_submenu = Gio.Menu()
        m = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("Neues Fenster", "win.newwin")
        m.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append("Minimieren", "win.minimize")
        s2.append("Maximieren", "win.maximize")
        s2.append("Vollbild", "win.fullscreen")
        s2.append_submenu("Verschieben nach", self._ws_submenu)
        m.append_section(None, s2)
        s3 = Gio.Menu()
        s3.append("Schließen", "win.close")
        m.append_section(None, s3)
        return m

    def _new_window(self):
        win = self._focused_window()
        if win:
            app = self.shell.apps.lookup(win.get("app_id"))
            from .apps import launch_app
            launch_app(app)

    def _focused_window(self):
        fid = self.wm.state.get("focused")
        for w in self.wm.state.get("windows", []):
            if w["id"] == fid:
                return w
        return None

    # ------------------------------------------------------------- state
    def update_state(self, st):
        win = self._focused_window()
        if win:
            app = self.shell.apps.lookup(win.get("app_id"))
            name = app.get_display_name() if app else (win.get("app_id") or "Fenster")
            self.app_label.set_label(name)
            title = win.get("title") or ""
            self.title_label.set_label("" if title == name else title)
        else:
            self.app_label.set_label("Schreibtisch")
            self.title_label.set_label("")

        n = st.get("workspaces", 1)
        cur = st.get("workspace", 1)
        occupied = {w.get("ws") for w in st.get("windows", [])}
        while (c := self.ws_box.get_first_child()) is not None:
            self.ws_box.remove(c)
        self.ws_box.set_visible(self.cfg.get("bar.show_workspaces", True) and n > 1)
        for i in range(1, n + 1):
            b = Gtk.Button()
            b.add_css_class("n-ws")
            dot = Gtk.Box()
            dot.add_css_class("n-ws-dot")
            if i == cur:
                dot.add_css_class("active")
            elif i in occupied:
                dot.add_css_class("occupied")
            b.set_child(dot)
            b.set_tooltip_text(f"Arbeitsfläche {i}")
            b.connect("clicked", lambda _b, i=i: self.wm.workspace(i))
            self.ws_box.append(b)
        if self._ws_submenu.get_n_items() != n:
            self._ws_submenu.remove_all()
            for i in range(1, n + 1):
                self._ws_submenu.append(f"Arbeitsfläche {i}", f"win.moveto({i})")

    def _tick(self):
        now = datetime.datetime.now()
        h24 = self.cfg.get("bar.clock_24h", True)
        secs = self.cfg.get("bar.show_seconds", False)
        if h24:
            t = now.strftime("%H:%M:%S" if secs else "%H:%M")
        else:
            t = now.strftime("%I:%M:%S %p" if secs else "%I:%M %p").lstrip("0")
        if self.cfg.get("bar.show_date", True):
            t = f"{WEEKDAYS_SHORT[now.weekday()]} {now.day}. {MONTHS_SHORT[now.month - 1]}  {t}"
        self.clock.set_label(t)
        return True

    def _slow_tick(self):
        cap, status = read_battery()
        self.bat_icon.set_visible(cap is not None)
        self.bat_label.set_visible(cap is not None)
        if cap is not None:
            lvl = min(100, (cap + 5) // 10 * 10)
            charging = "-charging" if status in ("Charging", "Full") else ""
            self.bat_icon.set_from_icon_name(f"battery-level-{lvl}{charging}-symbolic")
            self.bat_label.set_label(f"{cap}%")
        system.get_volume(lambda v, m: self.vol_icon.set_from_icon_name(system.volume_icon(v, m)))
        self._update_net()
        return True

    def _update_net(self):
        icon, label = self.net.status()
        self.net_icon.set_from_icon_name(icon)
        self.net_icon.set_tooltip_text(label)
