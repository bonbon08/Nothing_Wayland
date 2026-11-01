"""StatusNotifierItem (SNI) / System-Tray für die obere Leiste.

Apps wie Steam oder Discord melden ihr Symbol beim
``org.kde.StatusNotifierWatcher`` an. Diesen Dienst stellt die Shell selbst
bereit und zeigt jedes Item als Knopf in der Leiste: Linksklick ruft
``Activate`` auf, Rechtsklick öffnet das Menü der App (DBusMenu).
"""
from gi.repository import Gdk, Gio, GLib, GObject, Gtk

SN_WATCHER_NAME = "org.kde.StatusNotifierWatcher"
SN_WATCHER_PATH = "/StatusNotifierWatcher"
SN_ITEM = "org.kde.StatusNotifierItem"
SN_ITEM_PATH = "/StatusNotifierItem"
DBUS_PROPS = "org.freedesktop.DBus.Properties"
DBUS_MENU = "com.canonical.dbusmenu"

WATCHER_INTROSPECTION = """
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem">
      <arg type="s" name="service" direction="in"/>
    </method>
    <method name="RegisterStatusNotifierHost">
      <arg type="s" name="service" direction="in"/>
    </method>
    <property type="as" name="RegisteredStatusNotifierItems" access="read"/>
    <property type="b" name="IsStatusNotifierHostRegistered" access="read"/>
    <property type="i" name="ProtocolVersion" access="read"/>
    <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
    <signal name="StatusNotifierHostRegistered"/>
  </interface>
</node>
"""


class StatusNotifierWatcher(GObject.Object):
    """Nimmt die Anmeldungen der Apps entgegen und führt die Liste der Items."""

    __gsignals__ = {
        "items-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.conn = None
        self.items = {}            # "bus_name/path" -> StatusNotifierItem
        self._info = Gio.DBusNodeInfo.new_for_xml(WATCHER_INTROSPECTION)

    def start(self):
        Gio.bus_own_name(Gio.BusType.SESSION, SN_WATCHER_NAME,
                         Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                         self._on_bus, None,
                         lambda *_: print("nothing-de: tray watcher name taken"))

    def _on_bus(self, conn, _name):
        self.conn = conn
        conn.register_object(SN_WATCHER_PATH, self._info.interfaces[0],
                             self._on_call, self._on_get_property, None)
        self._emit("StatusNotifierHostRegistered", None)

    def _emit(self, signal, params):
        self.conn.emit_signal(None, SN_WATCHER_PATH, SN_WATCHER_NAME, signal, params)

    def _on_call(self, _conn, sender, _path, _iface, method, params, inv):
        if method == "RegisterStatusNotifierItem":
            service = params.unpack()[0]
            # Ayatana indicators send their object path, others their bus name
            if service.startswith("/"):
                self._add_item(sender, service)
            else:
                self._add_item(service, SN_ITEM_PATH)
        inv.return_value(None)

    def _on_get_property(self, _conn, _sender, _path, _iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", list(self.items))
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        return GLib.Variant("i", 0)

    def _add_item(self, bus_name, path):
        key = bus_name + path
        if key in self.items:
            return
        self.items[key] = StatusNotifierItem(self, key, bus_name, path)
        self._emit("StatusNotifierItemRegistered", GLib.Variant("(s)", (key,)))

    def remove_item(self, key):
        if self.items.pop(key, None) is not None:
            self._emit("StatusNotifierItemUnregistered", GLib.Variant("(s)", (key,)))
            self.emit("items-changed")


class StatusNotifierItem:
    """Ein einzelnes Tray-Item; `props` sind die Eigenschaften aus D-Bus."""

    def __init__(self, watcher, key, bus_name, path):
        self.watcher = watcher
        self.conn = watcher.conn
        self.key = key
        self.bus_name = bus_name
        self.path = path
        self.props = {}
        self.known = False
        self._watch = Gio.bus_watch_name_on_connection(
            self.conn, bus_name, Gio.BusNameWatcherFlags.NONE, None, self._vanished)
        # NewIcon, NewTitle, NewStatus, ... carry no values: read everything again
        self._signal = self.conn.signal_subscribe(
            bus_name, SN_ITEM, None, path, None, Gio.DBusSignalFlags.NONE,
            lambda *_: self.fetch())
        self.fetch()

    def _vanished(self, _conn, _name):
        Gio.bus_unwatch_name(self._watch)
        self.conn.signal_unsubscribe(self._signal)
        self.watcher.remove_item(self.key)

    def call(self, iface, path, method, params, callback=None):
        def done(conn, res):
            try:
                reply = conn.call_finish(res)
            except GLib.Error:
                reply = None
            if callback:
                callback(reply)
        self.conn.call(self.bus_name, path, iface, method, params, None,
                       Gio.DBusCallFlags.NONE, -1, None, done)

    def fetch(self):
        def got(reply):
            if reply is None:
                # no StatusNotifierItem behind this name
                if not self.known:
                    self._vanished(None, None)
                return
            self.known = True
            self.props = reply.unpack()[0]
            self.watcher.emit("items-changed")
        self.call(DBUS_PROPS, self.path, "GetAll", GLib.Variant("(s)", (SN_ITEM,)), got)

    @property
    def title(self):
        tip = self.props.get("ToolTip")
        return self.props.get("Title") or (tip[2] if tip else "") or \
            self.props.get("Id") or self.bus_name

    def activate(self, on_error):
        if self.props.get("ItemIsMenu"):
            on_error()
            return
        self.call(SN_ITEM, self.path, "Activate", GLib.Variant("(ii)", (0, 0)),
                  lambda reply: reply is None and on_error())

    def context_menu(self):
        self.call(SN_ITEM, self.path, "ContextMenu", GLib.Variant("(ii)", (0, 0)))

    def menu_layout(self, callback):
        """callback(menu node, or None): a node is (id, properties, children)."""
        path = self.props.get("Menu")
        if not path:
            callback(None)
            return
        self.call(DBUS_MENU, path, "AboutToShow", GLib.Variant("(i)", (0,)))
        self.call(DBUS_MENU, path, "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                  lambda reply: callback(reply.unpack()[1] if reply else None))

    def menu_clicked(self, item_id):
        self.call(DBUS_MENU, self.props["Menu"], "Event",
                  GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("i", 0), 0)))


class Tray(Gtk.Box):
    """Rechts in der oberen Leiste: ein Icon pro registriertem Tray-Item."""

    def __init__(self, shell):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.add_css_class("n-tray")
        self.set_valign(Gtk.Align.CENTER)
        self.watcher = shell.tray_watcher
        handler = self.watcher.connect("items-changed", lambda *_: self.rebuild())
        self.connect("destroy", lambda *_: self.watcher.disconnect(handler))
        self.rebuild()

    def rebuild(self):
        while (c := self.get_first_child()) is not None:
            self.remove(c)
        for item in self.watcher.items.values():
            if item.known:
                self.append(self._button(item))

    def _button(self, item):
        btn = Gtk.Button(child=self._icon(item))
        btn.add_css_class("n-tray-btn")
        btn.set_tooltip_text(item.title)
        btn.connect("clicked", lambda *_: item.activate(lambda: self._menu(btn, item)))
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", lambda *_: self._menu(btn, item))
        btn.add_controller(right)
        return btn

    def _icon(self, item):
        img = Gtk.Image(pixel_size=18)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        path = item.props.get("IconThemePath")
        if path and path not in theme.get_search_path():
            theme.add_search_path(path)
        name = item.props.get("IconName") or ""
        pixmaps = item.props.get("IconPixmap")
        if name.startswith("/"):
            img.set_from_file(name)
        elif name and theme.has_icon(name):
            img.set_from_icon_name(name)
        elif pixmaps:
            w, h, data = max(pixmaps, key=lambda p: p[0])
            img.set_from_paintable(Gdk.MemoryTexture.new(
                w, h, Gdk.MemoryFormat.A8R8G8B8, GLib.Bytes.new(bytes(data)), w * 4))
        else:
            img.set_from_icon_name("application-x-executable-symbolic")
        return img

    def _menu(self, btn, item):
        def got(layout):
            if layout is None or not layout[2]:
                item.context_menu()
                return
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            pop = Gtk.Popover(child=box)
            pop.add_css_class("n-menu")
            self._fill_menu(box, layout[2], item, pop, 0)
            pop.set_parent(btn)
            pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
            pop.popup()
        item.menu_layout(got)

    def _fill_menu(self, box, children, item, pop, depth):
        for node in children:
            item_id, props, sub = node
            if not props.get("visible", True):
                continue
            if props.get("type") == "separator":
                box.append(Gtk.Separator())
                continue
            label = (props.get("label") or "").replace("_", "")
            if props.get("toggle-state") == 1:
                label = "✓ " + label
            row = Gtk.Button()
            row.add_css_class("flat")
            text = Gtk.Label(label=label, xalign=0)
            text.set_margin_start(depth * 14)
            row.set_child(text)
            row.set_sensitive(props.get("enabled", True) and not sub)
            row.connect("clicked", lambda _b, i=item_id: (pop.popdown(), item.menu_clicked(i)))
            box.append(row)
            self._fill_menu(box, sub, item, pop, depth + 1)
