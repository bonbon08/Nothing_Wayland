"""End-to-End: nothing-wm headless starten, per IPC steuern, die Shell darin laufen lassen.

Läuft ohne Bildschirm (wlroots-Headless mit Pixman) und ohne echte Sitzung. Der Compositor-Build
kommt aus meson im Testverzeichnis; mit NOTHING_WM_BIN lässt sich ein bestehendes Binary nehmen.
"""
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import time

import pytest

from conftest import ROOT

pytestmark = pytest.mark.integration

WM_ENV = {
    "WLR_BACKENDS": "headless",
    "WLR_RENDERER": "pixman",
    "WLR_HEADLESS_OUTPUTS": "1",
    "GSK_RENDERER": "cairo",
    "NOTHING_NO_GSETTINGS": "1",
    "NOTHING_NO_AUTOSTART": "1",
}


def shell_pids(runtime):
    """PIDs der Shell, die in diesem Test-Runtime-Verzeichnis läuft.

    spawn() im Compositor macht einen Double-Fork: die Shell ist kein Kind mehr. Erkannt wird sie an
    XDG_RUNTIME_DIR in ihrer Umgebung. So trifft der Test nie eine echte Sitzung auf demselben Rechner.
    """
    marker = f"XDG_RUNTIME_DIR={runtime}".encode()
    found = []
    for cmd_path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmd_path, "rb") as f:
                cmd = f.read()
            if b"nothing_de.shell" not in cmd:
                continue
            with open(os.path.dirname(cmd_path) + "/environ", "rb") as f:
                env = f.read().split(b"\0")
        except OSError:  # Prozess ist inzwischen beendet
            continue
        if marker in env:
            found.append(int(cmd_path.split("/")[2]))
    return found


def run_checked(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, f"{' '.join(cmd)} schlug fehl:\n{result.stdout}\n{result.stderr}"
    return result


@pytest.fixture(scope="session")
def wm_binary(tmp_path_factory):
    given = os.environ.get("NOTHING_WM_BIN")
    if given:
        if not os.path.isfile(given):
            pytest.skip(f"NOTHING_WM_BIN zeigt auf nichts: {given}")
        return given
    if not (shutil.which("meson") and shutil.which("ninja")):
        pytest.skip("meson/ninja fehlen, Compositor kann nicht gebaut werden")
    build = tmp_path_factory.mktemp("wm-build")
    run_checked(["meson", "setup", str(build), os.path.join(ROOT, "compositor")])
    run_checked(["ninja", "-C", str(build)])
    return str(build / "nothing-wm")


class Session:
    """Eine laufende nothing-wm-Instanz mit eigenem Runtime- und Config-Verzeichnis."""

    def __init__(self, wm_bin, startup, workdir, runtime=None):
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime or workdir / "rt"
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        self.log_path = workdir / "wm.log"
        env = dict(os.environ, **WM_ENV)
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        env["XDG_CONFIG_HOME"] = str(workdir / "cfg")
        cmd = [wm_bin, "-s", startup]
        if shutil.which("dbus-run-session"):  # eigener Session-Bus: keine Benachrichtigungen aus der echten Sitzung
            cmd = ["dbus-run-session", "--"] + cmd
        self._log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, env=env, stdout=self._log, stderr=subprocess.STDOUT,
                                     start_new_session=True)

    def socket_path(self, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            socks = glob.glob(str(self.runtime / "nothing-wm.*.sock"))
            if socks:
                return socks[0]
            if self.proc.poll() is not None:
                break
            time.sleep(0.2)
        raise AssertionError(f"kein IPC-Socket. Log:\n{self.log()}")

    def ipc(self, *commands):
        """Befehle senden und jede Antwortzeile als JSON zurückgeben (eine Verbindung)."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(self.socket_path())
        for c in commands:
            s.sendall((c + "\n").encode())
        time.sleep(0.4)
        s.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
        s.close()
        return [json.loads(line) for line in data.decode().splitlines() if line.strip()]

    def state(self):
        return [m for m in self.ipc("state") if m.get("event") == "state"][-1]

    def log(self):
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def stop(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
        self._log.close()


@pytest.fixture
def start_session(wm_binary, tmp_path):
    sessions = []

    def start(startup="sleep 120", runtime=None):
        s = Session(wm_binary, startup, tmp_path / f"s{len(sessions)}", runtime)
        sessions.append(s)
        return s

    yield start
    for s in sessions:
        s.stop()


def test_compositor_answers_state_over_ipc(start_session):
    s = start_session()
    state = s.state()

    assert state["workspaces"] >= 1
    assert state["workspace"] == 1
    assert state["windows"] == []
    assert state["outputs"], "mindestens ein (virtueller) Bildschirm erwartet"
    assert state["outputs"][0]["enabled"] is True


def test_workspace_switch_is_reflected_in_state(start_session):
    s = start_session()
    s.ipc("ws 2")
    assert s.state()["workspace"] == 2


def test_config_command_changes_workspace_count(start_session):
    s = start_session()
    s.ipc("config workspaces 6")
    assert s.state()["workspaces"] == 6


def test_screen_command_switches_the_screen_off_and_on(start_session):
    s = start_session()
    assert s.state()["screen_off"] is False
    events = s.ipc("subscribe", "screen off")
    assert {"event": "action", "name": "screen_off"} in events
    assert s.state()["screen_off"] is True
    # the outputs stay in the layout while the screen is dark
    assert s.state()["outputs"][0]["enabled"] is True
    s.ipc("screen toggle")
    assert s.state()["screen_off"] is False


def test_blank_timeout_turns_the_screen_off_without_input(start_session):
    s = start_session()
    s.ipc("config blank_timeout 1")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not s.state()["screen_off"]:
        time.sleep(0.3)
    assert s.state()["screen_off"] is True
    s.ipc("config blank_timeout 0", "screen on")
    time.sleep(1.5)
    assert s.state()["screen_off"] is False


def test_output_transform_rotates_the_screen(start_session):
    s = start_session()
    out = s.state()["outputs"][0]
    assert out["transform"] == 0
    s.ipc(f"output {out['name']} transform 90")
    assert s.state()["outputs"][0]["transform"] == 90
    s.ipc(f"output {out['name']} transform 0")
    assert s.state()["outputs"][0]["transform"] == 0


def test_osk_command_without_input_method(start_session):
    s = start_session()
    assert s.state()["osk"] is False
    # no on-screen keyboard connected: the commands are accepted and change nothing
    assert not [m for m in s.ipc("osk hide", "osk show") if m.get("event") == "error"]
    assert s.state()["osk"] is False


def test_exit_command_ends_the_session(start_session):
    s = start_session()
    s.ipc("exit")
    assert s.proc.wait(timeout=15) == 0


def test_too_long_runtime_dir_is_reported_not_silently_truncated(wm_binary, tmp_path):
    # Der IPC-Pfad ist auf 108 Byte begrenzt. Dieser Pfad ist knapp darunter: der Wayland-Socket
    # passt noch hinein, der IPC-Socket nicht mehr. Früher wurde er still abgeschnitten.
    long_dir = tmp_path / ("n" * (90 - len(str(tmp_path)) - 1))
    long_dir.mkdir(mode=0o700)
    s = Session(wm_binary, "sleep 3", tmp_path / "long", runtime=long_dir)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and "IPC socket path too long" not in s.log():
            time.sleep(0.2)
        assert "IPC socket path too long" in s.log(), s.log()
        assert glob.glob(str(long_dir / "nothing-wm.*")) == []
    finally:
        s.stop()


def test_shell_runs_inside_the_compositor(start_session):
    shell = os.path.join(ROOT, "bin", "nothing-shell")
    s = start_session(startup=shell)
    s.socket_path()

    time.sleep(15)  # Start der Shell (GTK, Widgets, Dock) abwarten

    assert s.proc.poll() is None, f"Compositor ist beendet. Log:\n{s.log()}"
    assert shell_pids(s.runtime), f"Shell-Prozess läuft nicht. Log:\n{s.log()}"
    assert "Traceback" not in s.log(), s.log()
    assert "nothing-de:" not in s.log(), s.log()
    assert s.state()["workspaces"] >= 1  # Compositor antwortet weiterhin
