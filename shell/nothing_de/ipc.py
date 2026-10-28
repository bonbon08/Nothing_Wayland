"""Client for the nothing-wm IPC socket (line based, JSON events)."""
import json
import os
import socket

from gi.repository import GLib, GObject


class WindowManager(GObject.Object):
    __gsignals__ = {
        "state": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "action": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "connected": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.path = os.environ.get("NOTHING_WM_SOCK")
        self.sock = None
        self.buf = b""
        self.state = {"workspace": 1, "workspaces": 1, "focused": 0, "windows": []}
        self._watch = None
        if self.path:
            self._connect()
        else:
            print("nothing-de: NOTHING_WM_SOCK not set — running without nothing-wm")

    @property
    def available(self):
        return self.sock is not None

    def _connect(self):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self.path)
        except OSError:
            GLib.timeout_add_seconds(1, self._retry)
            return
        self.sock = s
        self.buf = b""
        self._watch = GLib.io_add_watch(
            s.fileno(), GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self._on_io)
        self.send("subscribe")
        self.emit("connected")

    def _retry(self):
        self._connect()
        return False

    def _on_io(self, _fd, cond):
        data = b""
        if cond & GLib.IOCondition.IN:
            try:
                data = self.sock.recv(1 << 16)
            except OSError:
                data = b""
        if not data:
            self.sock.close()
            self.sock = None
            self._watch = None
            GLib.timeout_add_seconds(1, self._retry)
            return False
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue
            ev = msg.get("event")
            if ev == "state":
                self.state = msg
                self.emit("state", msg)
            elif ev == "action":
                self.emit("action", msg.get("name", ""))
        return True

    def send(self, *parts):
        if not self.sock:
            return
        line = " ".join(str(p) for p in parts) + "\n"
        try:
            self.sock.sendall(line.encode())
        except OSError:
            pass

    # convenience
    def focus(self, wid): self.send("focus", wid)
    def toggle(self, wid): self.send("toggle", wid)
    def close(self, wid): self.send("close", wid)
    def minimize(self, wid): self.send("minimize", wid)
    def maximize(self, wid): self.send("maximize", wid)
    def workspace(self, n): self.send("ws", n)
    def move_to(self, wid, n): self.send("move", wid, n)
    def config(self, key, value): self.send("config", key, value)
    def exit(self): self.send("exit")
