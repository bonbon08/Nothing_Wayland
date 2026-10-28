"""Minimal org.freedesktop.Notifications server with Nothing-style toasts."""
from gi.repository import Gio, GLib, Gtk, Pango

from . import layer

XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" name="app_name" direction="in"/>
      <arg type="u" name="replaces_id" direction="in"/>
      <arg type="s" name="app_icon" direction="in"/>
      <arg type="s" name="summary" direction="in"/>
      <arg type="s" name="body" direction="in"/>
      <arg type="as" name="actions" direction="in"/>
      <arg type="a{sv}" name="hints" direction="in"/>
      <arg type="i" name="expire_timeout" direction="in"/>
      <arg type="u" name="id" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" name="id" direction="in"/></method>
    <method name="GetCapabilities"><arg type="as" name="caps" direction="out"/></method>
    <method name="GetServerInformation">
      <arg type="s" name="name" direction="out"/><arg type="s" name="vendor" direction="out"/>
      <arg type="s" name="version" direction="out"/><arg type="s" name="spec" direction="out"/>
    </method>
    <signal name="NotificationClosed"><arg type="u" name="id"/><arg type="u" name="reason"/></signal>
    <signal name="ActionInvoked"><arg type="u" name="id"/><arg type="s" name="action_key"/></signal>
  </interface>
</node>
"""


class Notifications:
    def __init__(self, shell):
        self.shell = shell
        self.next_id = 1
        self.toasts = {}
        self.conn = None
        self.win = Gtk.ApplicationWindow(application=shell.app)
        self.win.add_css_class("n-root")
        layer.setup(self.win, layer="overlay", anchors=("top", "right"),
                    margins={"top": 44, "right": 12}, namespace="nothing-notifications")
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.box.set_size_request(360, -1)
        self.win.set_child(self.box)
        self.info = Gio.DBusNodeInfo.new_for_xml(XML)
        Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                         Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                         self._on_bus, None, lambda *_: print("nothing-de: notification name taken"))

    def _on_bus(self, conn, _name):
        self.conn = conn
        conn.register_object("/org/freedesktop/Notifications", self.info.interfaces[0],
                             self._on_call, None, None)

    def _on_call(self, _conn, _sender, _path, _iface, method, params, inv):
        if method == "GetCapabilities":
            inv.return_value(GLib.Variant("(as)", (["body", "actions", "icon-static"],)))
        elif method == "GetServerInformation":
            inv.return_value(GLib.Variant("(ssss)", ("nothing-de", "Nothing DE", "0.1", "1.2")))
        elif method == "CloseNotification":
            self.close(params.unpack()[0], 3)
            inv.return_value(None)
        elif method == "Notify":
            app, rid, icon, summary, body, actions, hints, timeout = params.unpack()
            nid = rid if rid and rid in self.toasts else self.next_id
            if nid == self.next_id:
                self.next_id += 1
            inv.return_value(GLib.Variant("(u)", (nid,)))
            urgency = hints.get("urgency", 1)
            if self.shell.cfg.get("dnd") and urgency < 2:
                return
            self.show(nid, app, icon, summary, body, actions,
                      timeout if timeout > 0 else (0 if urgency == 2 else 6000))
        else:
            inv.return_value(None)

    def show(self, nid, app, icon, summary, body, actions, timeout):
        if nid in self.toasts:
            self.close(nid, None)
        toast = Gtk.Box(spacing=12)
        toast.add_css_class("n-toast")
        img = Gtk.Image(pixel_size=32, valign=Gtk.Align.START)
        if icon and icon.startswith("/"):
            img.set_from_file(icon)
        elif icon:
            img.set_from_icon_name(icon)
        else:
            app_info = self.shell.apps.lookup(app)
            img.set_from_gicon(app_info.get_icon() if app_info and app_info.get_icon()
                               else Gio.ThemedIcon.new("dialog-information-symbolic"))
        toast.append(img)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        head = Gtk.Label(label=(app or "").upper(), xalign=0)
        head.add_css_class("n-caps")
        title = Gtk.Label(label=summary, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR)
        title.add_css_class("n-toast-title")
        col.append(head)
        col.append(title)
        if body:
            text = Gtk.Label(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, lines=4,
                             ellipsize=Pango.EllipsizeMode.END)
            try:
                Pango.parse_markup(body, -1, "\x00")
                text.set_markup(body)
            except (GLib.Error, TypeError, ValueError):
                text.set_text(body)
            col.append(text)
        if actions:
            row = Gtk.Box(spacing=6)
            for key, label in zip(actions[::2], actions[1::2]):
                if key == "default":
                    continue
                b = Gtk.Button(label=label)
                b.add_css_class("n-tile")
                b.connect("clicked", lambda _b, k=key: self._invoke(nid, k))
                row.append(b)
            col.append(row)
        toast.append(col)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._invoke(nid, "default") if "default" in actions
                      else self.close(nid, 2))
        toast.add_controller(click)
        self.box.prepend(toast)
        self.toasts[nid] = toast
        self.win.present()
        if timeout:
            GLib.timeout_add(timeout, lambda: (self.close(nid, 1), False)[1])

    def _invoke(self, nid, key):
        if self.conn:
            self.conn.emit_signal(None, "/org/freedesktop/Notifications",
                                  "org.freedesktop.Notifications", "ActionInvoked",
                                  GLib.Variant("(us)", (nid, key)))
        self.close(nid, 2)

    def close(self, nid, reason):
        toast = self.toasts.pop(nid, None)
        if toast is None:
            return
        self.box.remove(toast)
        if reason is not None and self.conn:
            self.conn.emit_signal(None, "/org/freedesktop/Notifications",
                                  "org.freedesktop.Notifications", "NotificationClosed",
                                  GLib.Variant("(uu)", (nid, reason)))
        if not self.toasts:
            self.win.set_visible(False)

    def notify(self, summary, body="", icon="dialog-information-symbolic"):
        self.show(self.next_id, "Nothing", icon, summary, body, [], 5000)
        self.next_id += 1
