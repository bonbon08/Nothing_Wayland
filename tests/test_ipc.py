"""Der IPC-Client gegen einen echten Unix-Socket, ohne Compositor.

Der Test spielt den nothing-wm-Server: er nimmt die Verbindung an, liest den
Befehl „subscribe“ und schickt Ereignisse zurück.
"""
import json
import os
import socket
import time

import pytest
from gi.repository import GLib

from nothing_de import ipc


def pump(predicate, timeout=3.0):
    """GLib-Hauptschleife laufen lassen, bis predicate() wahr ist."""
    deadline = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < deadline:
        if predicate():
            return True
        ctx.iteration(False)
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def server(tmp_path, monkeypatch):
    # Kurzer Pfad: sun_path ist auf 108 Byte begrenzt
    sock_path = os.path.join(tmp_path, "wm.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    srv.settimeout(3)
    monkeypatch.setenv("NOTHING_WM_SOCK", sock_path)
    yield srv
    srv.close()


def read_line(conn):
    buf = b""
    while b"\n" not in buf:
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf += chunk
    return buf.split(b"\n", 1)[0]


def test_connects_and_subscribes_on_creation(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    assert read_line(conn) == b"subscribe"
    assert wm.available
    conn.close()


def test_state_and_action_events_are_emitted(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    read_line(conn)

    states, actions, connected = [], [], []
    wm.connect("state", lambda _w, st: states.append(st))
    wm.connect("action", lambda _w, name: actions.append(name))
    wm.connect("connected", lambda _w: connected.append(True))

    state = {"event": "state", "workspace": 2, "workspaces": 4, "focused": 7,
             "windows": [{"id": 7, "app_id": "firefox", "ws": 2, "taskbar": True}]}
    conn.sendall(json.dumps(state).encode() + b"\n")
    conn.sendall(b'{"event":"action","name":"launcher"}\n')

    assert pump(lambda: states and actions)
    assert wm.state["workspace"] == 2
    assert wm.state["windows"][0]["app_id"] == "firefox"
    assert actions == ["launcher"]
    assert connected == []  # 'connected' kommt nur beim Aufbau, nicht bei Events
    conn.close()


def test_lines_split_across_packets_are_joined(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    read_line(conn)

    payload = json.dumps({"event": "state", "workspace": 3}).encode() + b"\n"
    conn.sendall(payload[:10])
    time.sleep(0.05)
    conn.sendall(payload[10:])

    assert pump(lambda: wm.state.get("workspace") == 3)
    conn.close()


def test_broken_json_is_ignored_and_stream_continues(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    read_line(conn)

    conn.sendall(b"das ist kein json\n\n")
    conn.sendall(b'{"event":"state","workspace":4}\n')

    assert pump(lambda: wm.state.get("workspace") == 4)
    conn.close()


def test_commands_are_sent_as_text_lines(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    reader = conn.makefile("rb")  # puffert: mehrere Zeilen in einem Paket bleiben erhalten
    assert reader.readline() == b"subscribe\n"

    wm.focus(3)
    wm.workspace(2)
    wm.move_to(3, 4)
    wm.config("accent", "#2F6BFF")

    received = [reader.readline().decode().strip() for _ in range(4)]
    assert received == ["focus 3", "ws 2", "move 3 4", "config accent #2F6BFF"]
    reader.close()
    conn.close()


def test_send_without_connection_is_a_noop(monkeypatch):
    monkeypatch.delenv("NOTHING_WM_SOCK", raising=False)
    wm = ipc.WindowManager()
    assert not wm.available
    wm.focus(1)  # darf nicht werfen
    wm.exit()


def test_reconnects_after_server_goes_away(server):
    wm = ipc.WindowManager()
    conn, _ = server.accept()
    read_line(conn)
    conn.close()  # Compositor beendet sich

    assert pump(lambda: not wm.available)

    # Der Retry-Timer des Clients läuft nur, wenn die Schleife läuft: deshalb
    # nicht-blockierend annehmen und dabei weiter pumpen.
    server.setblocking(False)
    new_conn = []

    def reconnected():
        try:
            new_conn.append(server.accept()[0])
        except BlockingIOError:
            return False
        return True

    assert pump(reconnected, timeout=5)
    new_conn[0].setblocking(True)
    assert read_line(new_conn[0]) == b"subscribe"
    assert pump(lambda: wm.available)
    new_conn[0].close()


def test_failed_connect_does_not_leak_a_file_descriptor(tmp_path, monkeypatch):
    # Der Compositor läuft noch nicht: jeder Wiederholversuch darf keinen Socket offen lassen
    monkeypatch.setenv("NOTHING_WM_SOCK", str(tmp_path / "fehlt.sock"))
    wm = ipc.WindowManager()
    before = len(os.listdir("/proc/self/fd"))

    for _ in range(20):
        wm._connect()

    assert not wm.available
    assert len(os.listdir("/proc/self/fd")) == before
