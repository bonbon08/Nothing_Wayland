"""System-wide 10-band equalizer through PipeWire's filter-chain.

When switched on (config "eq.enabled"), a small `pipewire -c <conf>` process provides the
sink "Nothing Equalizer" whose biquad filters feed the real output; it becomes the default
output, so every app is equalized. Changing a band sets the filter's gain live with
`pw-cli set-param`, without interrupting the sound. Switching off restores the previous
output and ends the process. Without PipeWire nothing happens (the card says so).
"""
import ctypes
import json
import os
import shutil
import signal
import subprocess
import tempfile

from gi.repository import GLib

FREQS = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
LABELS = ["31", "63", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
MAX_DB = 12.0
SINK_NAME = "nothing_eq"

PRESETS = [
    ("flat", "Flat", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    ("bass", "Bass", [7, 6, 4.5, 2.5, 0.5, 0, 0, 0, 0, 0]),
    ("treble", "Treble", [0, 0, 0, 0, 0, 1, 2.5, 4.5, 6, 7]),
    ("vocal", "Vocal", [-2, -2, -1, 1, 3, 4, 3.5, 2, 0, -1]),
    ("pop", "Pop", [-1, 1, 3, 4, 3, 0, -1, -1, 1, 2]),
    ("rock", "Rock", [5, 4, 2.5, 0, -1.5, -1, 1, 2.5, 3.5, 4.5]),
    ("jazz", "Jazz", [3, 2, 1, 2, -1.5, -1.5, 0, 1, 2, 3]),
    ("classic", "Classic", [4.5, 3.5, 2.5, 1.5, -1, -1, 0, 2, 3, 4]),
]


def preset_gains(key):
    for k, _name, gains in PRESETS:
        if k == key:
            return list(gains)
    return [0.0] * len(FREQS)


def matching_preset(gains):
    """The key of the preset these gains are, or "custom"."""
    for k, _name, g in PRESETS:
        if all(abs(a - b) < 0.05 for a, b in zip(g, gains)):
            return k
    return "custom"


def clamp_gains(gains):
    out = []
    for i in range(len(FREQS)):
        try:
            v = float(gains[i])
        except (IndexError, TypeError, ValueError):
            v = 0.0
        out.append(max(-MAX_DB, min(MAX_DB, v)))
    return out


def filter_chain_conf(gains, target=None):
    """A standalone PipeWire config with one filter-chain module: low shelf, eight
    peaking bands, high shelf."""
    nodes, links = [], []
    for i, (f, g) in enumerate(zip(FREQS, clamp_gains(gains))):
        label = "bq_lowshelf" if i == 0 else "bq_highshelf" if i == len(FREQS) - 1 else "bq_peaking"
        nodes.append(f'{{ type = builtin name = eq{i} label = {label} '
                     f'control = {{ "Freq" = {float(f)} "Q" = 1.0 "Gain" = {g:.2f} }} }}')
        if i:
            links.append(f'{{ output = "eq{i - 1}:Out" input = "eq{i}:In" }}')
    target_line = f'target.object = "{target}"' if target else ""
    return f"""context.properties = {{ log.level = 0 }}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.* = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "Nothing Equalizer"
            media.name = "Nothing Equalizer"
            filter.graph = {{
                nodes = [
                    {chr(10).join("                    " + n for n in nodes).lstrip()}
                ]
                links = [
                    {chr(10).join("                    " + n for n in links).lstrip()}
                ]
            }}
            audio.channels = 2
            audio.position = [ FL FR ]
            capture.props = {{
                node.name = "{SINK_NAME}"
                media.class = Audio/Sink
            }}
            playback.props = {{
                node.name = "{SINK_NAME}.output"
                node.passive = true
                {target_line}
            }}
        }}
    }}
]
"""


def params_pod(gains):
    """The Props pod for `pw-cli set-param`: every band's gain."""
    parts = " ".join(f'"eq{i}:Gain" {g:.2f}' for i, g in enumerate(clamp_gains(gains)))
    return f"{{ params = [ {parts} ] }}"


def _die_with_parent():
    """The filter process ends with the shell (PR_SET_PDEATHSIG), no orphaned sink."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


class Equalizer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.conf = None
        self.previous_sink = None
        self.node_id = None
        self.gains = clamp_gains(cfg.get("eq.gains") or [])
        self.enabled = False
        self.error = ""
        cfg.connect("changed", lambda *_: self.sync())
        self.sync()

    @property
    def available(self):
        return bool(shutil.which("pipewire") and shutil.which("pw-cli") and shutil.which("pactl"))

    def sync(self):
        want = bool(self.cfg.get("eq.enabled"))
        gains = clamp_gains(self.cfg.get("eq.gains") or [])
        if want and not self.enabled:
            self.start(gains)
        elif not want and self.enabled:
            self.stop()
        elif want and gains != self.gains:
            self.set_gains(gains)

    # ------------------------------------------------------------ process
    def _default_sink(self):
        try:
            out = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out and out != SINK_NAME:
            return out
        # the equalizer is the default already (left over): the first real output
        try:
            sinks = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True,
                                   text=True, timeout=3).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in sinks:
            parts = line.split("\t")
            if len(parts) > 1 and not parts[1].startswith(SINK_NAME):
                return parts[1]
        return None

    def start(self, gains):
        self.gains = gains
        if not self.available:
            self.error = "PipeWire (pipewire, pw-cli, pactl) fehlt"
            return
        self.previous_sink = self._default_sink()
        fd, self.conf = tempfile.mkstemp(prefix="nothing-eq-", suffix=".conf")
        with os.fdopen(fd, "w") as f:
            f.write(filter_chain_conf(gains, self.previous_sink))
        try:
            self.proc = subprocess.Popen(["pipewire", "-c", self.conf],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, preexec_fn=_die_with_parent)
        except OSError as e:
            self.error = str(e)
            return
        self.enabled = True
        self.error = ""
        self.node_id = None
        # the sink shows up after a moment; then it becomes the default output
        self._tries = 0
        GLib.timeout_add(150, self._wait_for_sink)

    def _wait_for_sink(self):
        if not self.enabled:
            return False
        self._tries += 1
        nid = self._find_node()
        if nid is not None:
            self.node_id = nid
            subprocess.Popen(["pactl", "set-default-sink", SINK_NAME],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return False
        if self._tries > 40 or (self.proc and self.proc.poll() is not None):
            self.error = "Equalizer-Sink ließ sich nicht anlegen"
            self.stop()
            return False
        return True

    def _find_node(self):
        try:
            out = subprocess.run(["pw-dump", "Node"], capture_output=True, text=True,
                                 timeout=3).stdout
            nodes = json.loads(out or "[]")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        for n in nodes:
            props = (n.get("info") or {}).get("props") or {}
            if props.get("node.name") == SINK_NAME:
                return n.get("id")
        return None

    def set_gains(self, gains):
        self.gains = clamp_gains(gains)
        if not self.enabled:
            return
        if self.node_id is None:
            self.node_id = self._find_node()
        if self.node_id is None:
            return
        subprocess.Popen(["pw-cli", "set-param", str(self.node_id), "Props",
                          params_pod(self.gains)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def set_output(self, name):
        """Play through another device: the equalizer starts over in front of it.
        False if it is off (then the caller switches the default output itself)."""
        if not self.enabled:
            return False
        gains = self.gains
        self.stop()
        subprocess.run(["pactl", "set-default-sink", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.start(gains)
        return True

    def stop(self):
        self.enabled = False
        if self.previous_sink:
            subprocess.run(["pactl", "set-default-sink", self.previous_sink],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.conf:
            try:
                os.unlink(self.conf)
            except OSError:
                pass
            self.conf = None
        self.node_id = None


_eq = None


def get_equalizer(cfg):
    global _eq
    if _eq is None:
        _eq = Equalizer(cfg)
    return _eq
