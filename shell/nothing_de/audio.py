"""Live audio spectrum for the visualizer (widget and band above the dock).

What is playing is read from the monitor of the default output, so any app counts.
Two ways, whichever is installed:

* GStreamer (`gst-plugins-good`: pulsesrc + spectrum), works with PulseAudio and
  PipeWire's pulse server;
* `cava` with raw ASCII output.

Without either the levels stay at zero and the visualizers show a flat line.
One analysis runs for all listeners and stops when the last one leaves.
"""
import math
import os
import re
import shutil
import subprocess
import tempfile

from gi.repository import Gio, GLib

BANDS = 48            # number of levels handed to the listeners
_RAW_BANDS = 256      # linear bands GStreamer computes, grouped logarithmically
_FLOOR_DB = -70.0
_FPS = 30

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except (ValueError, ImportError):
    Gst = None

_MAG_RE = re.compile(r"magnitude=\(float\)\{([^}]*)\}")


def parse_magnitudes(text):
    """The dB values of a GStreamer spectrum message, from its string form (PyGObject
    cannot unpack the GstValueList directly)."""
    m = _MAG_RE.search(text)
    if not m:
        return []
    out = []
    for part in m.group(1).split(","):
        part = part.strip()
        if part:
            try:
                out.append(float(part))
            except ValueError:
                out.append(_FLOOR_DB)
    return out


def log_groups(n_in, n_out, low=1):
    """Index ranges that group `n_in` linear frequency bands into `n_out` bands of
    equal width on a logarithmic scale (bass gets as much room as treble, like the ear)."""
    edges = []
    top = math.log(n_in)
    base = math.log(max(1, low))
    for i in range(n_out + 1):
        edges.append(int(round(math.exp(base + (top - base) * i / n_out))))
    groups = []
    prev = low
    for i in range(n_out):
        a = max(prev, edges[i])
        b = max(a + 1, edges[i + 1])
        b = min(b, n_in)
        a = min(a, n_in - 1)
        groups.append((a, b))
        prev = b
    return groups


def db_levels(magnitudes, n_out=BANDS, floor=_FLOOR_DB):
    """dB values of linear bands -> `n_out` levels 0..1 on a log frequency scale."""
    if not magnitudes:
        return [0.0] * n_out
    out = []
    for a, b in log_groups(len(magnitudes), n_out):
        chunk = magnitudes[a:b] or [floor]
        v = max(chunk)
        out.append(min(1.0, max(0.0, (v - floor) / -floor)))
    return out


def resample(levels, n):
    """`levels` stretched or squeezed to `n` values (for widgets with fewer columns)."""
    if n <= 0:
        return []
    if not levels:
        return [0.0] * n
    m = len(levels)
    if m == n:
        return list(levels)
    out = []
    for i in range(n):
        a = int(i * m / n)
        b = max(a + 1, int((i + 1) * m / n))
        out.append(max(levels[a:b]))
    return out


def interpolate(levels, n):
    """`levels` linearly interpolated to `n` values (smooth curves instead of steps)."""
    if n <= 0:
        return []
    if not levels:
        return [0.0] * n
    if len(levels) == 1 or n == 1:
        return [levels[0]] * n
    out = []
    m = len(levels) - 1
    for i in range(n):
        pos = i * m / (n - 1)
        a = int(pos)
        b = min(a + 1, m)
        f = pos - a
        out.append(levels[a] * (1 - f) + levels[b] * f)
    return out


def smooth(previous, new, attack=0.6, decay=0.18):
    """Rise fast, fall slowly, so the bars do not flicker."""
    if len(previous) != len(new):
        return list(new)
    return [p + (v - p) * (attack if v > p else decay) for p, v in zip(previous, new)]


def parse_cava_line(line, max_range=1000):
    vals = []
    for part in line.strip().strip(";").split(";"):
        if part:
            try:
                vals.append(min(1.0, int(part) / max_range))
            except ValueError:
                vals.append(0.0)
    return vals


CAVA_CONFIG = f"""[general]
bars = {BANDS}
framerate = {_FPS}
[input]
method = pulse
source = auto
[output]
method = raw
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
[smoothing]
noise_reduction = 60
"""


class AudioSpectrum:
    """Shared analysis. `subscribe(cb)` gets `cb(levels)` about 30 times a second."""

    def __init__(self):
        self.listeners = {}
        self._next = 1
        self.levels = [0.0] * BANDS
        self.backend = None          # "gstreamer" | "cava" | None
        self._pipeline = None
        self._proc = None
        self._stream = None
        self._cancel = None
        self._cava_cfg = None
        self._silence = None

    # ------------------------------------------------------------ listeners
    def subscribe(self, callback):
        sid = self._next
        self._next += 1
        self.listeners[sid] = callback
        if len(self.listeners) == 1:
            self._start()
        return sid

    def unsubscribe(self, sid):
        self.listeners.pop(sid, None)
        if not self.listeners:
            self._stop()

    @property
    def available(self):
        return bool(self._gst_ok() or shutil.which("cava"))

    def _emit(self, levels):
        self.levels = smooth(self.levels, levels)
        for cb in list(self.listeners.values()):
            try:
                cb(self.levels)
            except Exception as e:     # one broken listener must not stop the others
                print("nothing-de: visualizer listener:", e)

    # ------------------------------------------------------------- backends
    @staticmethod
    def _gst_ok():
        if Gst is None:
            return False
        if not Gst.is_initialized():
            Gst.init(None)
        return all(Gst.ElementFactory.find(n) for n in ("pulsesrc", "spectrum", "audioconvert"))

    def _start(self):
        if os.environ.get("NOTHING_NO_AUDIO"):
            return
        if self._gst_ok() and self._start_gst():
            self.backend = "gstreamer"
        elif shutil.which("cava") and self._start_cava():
            self.backend = "cava"
        else:
            self.backend = None

    def _start_gst(self):
        desc = (f"pulsesrc device=@DEFAULT_MONITOR@ ! audioconvert ! audio/x-raw,channels=1 ! "
                f"spectrum bands={_RAW_BANDS} threshold={int(_FLOOR_DB)} "
                f"interval={int(1e9 / _FPS)} post-messages=true message-magnitude=true "
                f"! fakesink sync=false")
        try:
            pipe = Gst.parse_launch(desc)
        except GLib.Error as e:
            print("nothing-de: visualizer:", e.message)
            return False
        bus = pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::element", self._on_gst_message)
        bus.connect("message::error", self._on_gst_error)
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            pipe.set_state(Gst.State.NULL)
            return False
        self._pipeline = pipe
        return True

    def _on_gst_message(self, _bus, msg):
        st = msg.get_structure()
        if st is None or st.get_name() != "spectrum":
            return
        self._emit(db_levels(parse_magnitudes(st.to_string())))

    def _on_gst_error(self, _bus, msg):
        err, _dbg = msg.parse_error()
        print("nothing-de: visualizer:", err.message)
        self._stop_gst()
        # fall back to cava if GStreamer cannot reach the sound server
        if self.listeners and shutil.which("cava") and self._start_cava():
            self.backend = "cava"
        else:
            self.backend = None

    def _start_cava(self):
        fd, path = tempfile.mkstemp(prefix="nothing-cava-", suffix=".conf")
        with os.fdopen(fd, "w") as f:
            f.write(CAVA_CONFIG)
        self._cava_cfg = path
        try:
            self._proc = subprocess.Popen(["cava", "-p", path], stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            self._proc = None
            return False
        self._stream = Gio.DataInputStream.new(
            Gio.UnixInputStream.new(self._proc.stdout.fileno(), False))
        self._cancel = Gio.Cancellable()
        self._read_cava()
        return True

    def _read_cava(self):
        self._stream.read_line_async(GLib.PRIORITY_DEFAULT, self._cancel, self._on_cava_line)

    def _on_cava_line(self, stream, res):
        try:
            line, _n = stream.read_line_finish_utf8(res)
        except GLib.Error:
            return
        if line is None:          # cava ended
            self._stop_cava()
            return
        vals = parse_cava_line(line)
        if vals:
            self._emit(resample(vals, BANDS))
        if self._stream is stream:
            self._read_cava()

    def _stop_gst(self):
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline.get_bus().remove_signal_watch()
            self._pipeline = None

    def _stop_cava(self):
        if self._cancel is not None:
            self._cancel.cancel()
            self._cancel = None
        self._stream = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._cava_cfg:
            try:
                os.unlink(self._cava_cfg)
            except OSError:
                pass
            self._cava_cfg = None

    def _stop(self):
        self._stop_gst()
        self._stop_cava()
        self.backend = None
        self.levels = [0.0] * BANDS


_spectrum = None


def get_spectrum():
    global _spectrum
    if _spectrum is None:
        _spectrum = AudioSpectrum()
    return _spectrum


# ---------------------------------------------------------------- drawing
def draw_levels(cr, levels, x, y, w, h, style, color, dim=None, pitch=10, off_dots=True):
    """Draw `levels` (0..1) into the box (x, y, w, h), growing upwards from its bottom.

    style: "wave" (filled curve, mirrored for a calm look), "bars" (rounded bars) or
    "dots" (Nothing-style dot matrix; the top dot of each column in `color`, the column
    in `dim`; with `off_dots` the unlit dots faintly too)."""
    if style == "dots":
        cols = max(1, int(w // pitch))
        rows = max(1, int(h // pitch))
        vals = resample(levels, cols)
        r = pitch * 0.36
        x0 = x + (w - cols * pitch) / 2
        for c, v in enumerate(vals):
            lit = int(round(v * rows))
            cx = x0 + c * pitch + pitch / 2
            for row in range(rows):
                cy = y + h - row * pitch - pitch / 2
                if row < lit:
                    cr.set_source_rgba(*(color if row == lit - 1 else (dim or color)))
                elif dim is not None and off_dots:
                    cr.set_source_rgba(dim[0], dim[1], dim[2], dim[3] * 0.25)
                else:
                    continue
                cr.arc(cx, cy, r, 0, 2 * math.pi)
                cr.fill()
        return
    if style == "bars":
        n = max(1, int(w // pitch))
        vals = resample(levels, n)
        bw = pitch * 0.6
        x0 = x + (w - n * pitch) / 2
        cr.set_source_rgba(*color)
        for i, v in enumerate(vals):
            bh = max(bw, v * h)
            bx = x0 + i * pitch + (pitch - bw) / 2
            by = y + h - bh
            rad = bw / 2
            cr.new_sub_path()
            cr.arc(bx + rad, by + rad, rad, math.pi, 0)
            cr.arc(bx + rad, y + h - rad, rad, 0, math.pi)
            cr.close_path()
            cr.fill()
        return
    # wave: mirrored, the bass rises at both edges and the treble meets in the middle
    half = interpolate(levels, 32)
    vals = half + list(reversed(half))
    n = len(vals)
    pts = [(x + w * i / (n - 1), y + h - max(0.02, v) * h) for i, v in enumerate(vals)]
    cr.move_to(x, y + h)
    cr.line_to(*pts[0])
    for i in range(1, n):
        (px, py), (qx, qy) = pts[i - 1], pts[i]
        mx = (px + qx) / 2
        cr.curve_to(mx, py, mx, qy, qx, qy)
    cr.line_to(x + w, y + h)
    cr.close_path()
    cr.set_source_rgba(*color)
    cr.fill()
