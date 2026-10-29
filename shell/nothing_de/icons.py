"""Nothing-style app icons: a monochrome glyph on a round plate.

Apps rarely ship such icons, so the glyph is derived from the normal icon:
a symbolic variant is used as is; for a coloured icon on a plate (a squircle
or circle in one colour, e.g. Discord or Signal) the motif is cut out of the
plate by its colour difference; any other icon becomes a white silhouette
whose shading keeps the inner detail. The glyph is painted in the CSS colour
of the widget, so it follows light/dark mode and needs no recolouring.
"""
import cairo
import numpy as np

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .apps import app_icon

RENDER = 128            # px the source icon is rasterised at
_cache = {}             # source path -> (A8 surface, plate?) or None


def _source(gicon, symbolic=True):
    """Path of the best file for gicon, preferring its -symbolic variant."""
    if isinstance(gicon, Gio.FileIcon):
        return gicon.get_file().get_path(), False
    if not isinstance(gicon, Gio.ThemedIcon):
        return None, False
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    names = [n for n in gicon.get_names() if not n.endswith("-symbolic")]
    candidates = [(n + "-symbolic", True) for n in names] if symbolic else []
    candidates += [(n, False) for n in names]
    for name, is_symbolic in candidates:
        if not theme.has_icon(name):
            continue
        found = theme.lookup_icon(name, None, RENDER, 1, Gtk.TextDirection.NONE, 0)
        f = found.get_file() if found else None
        if f and f.get_path():
            return f.get_path(), is_symbolic
    return None, False


def _load(path, symbolic):
    if not (symbolic and path.endswith(".svg")):
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, RENDER, RENDER, True)
    # Firefox-style symbolic SVGs paint with context-fill, unknown to librsvg
    with open(path, encoding="utf-8", errors="replace") as f:
        svg = f.read()
    for word, value in (("context-fill-opacity", "1"), ("context-stroke-opacity", "1"),
                        ("context-fill", "#000"), ("context-stroke", "#000")):
        svg = svg.replace(word, value)
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.set_size(RENDER, RENDER)
    loader.write(svg.encode())
    loader.close()
    return loader.get_pixbuf()


def _pixels(path, symbolic):
    pb = _load(path, symbolic)
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, stride = pb.get_width(), pb.get_height(), pb.get_rowstride()
    raw = np.frombuffer(pb.get_pixels(), np.uint8)
    raw = np.pad(raw, (0, h * stride - raw.size))    # last row may be short
    return raw.reshape(h, stride)[:, :w * 4].reshape(h, w, 4).astype(np.float32) / 255


def _erode(mask, steps):
    for _ in range(steps):
        m = mask.copy()
        m[1:] &= mask[:-1]
        m[:-1] &= mask[1:]
        m[:, 1:] &= mask[:, :-1]
        m[:, :-1] &= mask[:, 1:]
        mask = m
    return mask


def _plate_colours(rgb, solid):
    """Candidates for the plate colour: the outline ring, then the most common colour."""
    ring = solid & ~_erode(solid, RENDER // 24)
    if ring.any():
        yield np.median(rgb[ring], axis=0), ring
    q = np.round(rgb[solid] * 7).astype(np.int32) @ np.array([64, 8, 1])
    counts = np.bincount(q, minlength=512)
    if counts.max() >= 0.25 * solid.sum():
        yield rgb[solid][q == counts.argmax()].mean(axis=0), None


def _plate_glyph(rgb, a):
    """Motif of an icon drawn on a one-coloured plate, or None.

    The plate colour is preferably taken from a ring along the icon's outline,
    where the motif rarely reaches; a soft gradient stays below the threshold.
    """
    solid = a > 0.5
    if solid.mean() < 0.35:
        return None
    for plate, ring in _plate_colours(rgb, solid):
        dist = np.linalg.norm(rgb - plate, axis=2) / np.sqrt(3)
        if ring is not None and np.median(dist[ring]) > 0.08:
            continue
        if (dist[solid] < 0.2).mean() < 0.3:
            continue
        glyph = np.clip((dist - 0.10) / 0.16, 0, 1) * np.clip((a - 0.75) / 0.2, 0, 1)
        if 0.015 < glyph.sum() / solid.sum() < 0.6:
            return glyph
    return None


def _glyph(path, symbolic):
    px = _pixels(path, symbolic)
    rgb, a = px[..., :3], px[..., 3]
    glyph = None if symbolic else _plate_glyph(rgb, a)
    plate = glyph is not None
    if glyph is None and symbolic:
        glyph = a
    if glyph is None:
        lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        solid = a > 0.5
        lo, hi = np.percentile(lum[solid], (5, 95)) if solid.any() else (0, 1)
        shade = np.clip((lum - lo) / max(hi - lo, 0.05), 0, 1)
        glyph = a * (0.38 + 0.62 * shade)
    ys, xs = np.nonzero(glyph > 0.08)
    if not len(xs):
        return None
    glyph = glyph[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = glyph.shape
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_A8, w)
    buf = np.zeros((h, stride), np.uint8)
    buf[:, :w] = np.round(glyph * 255)
    data = bytearray(buf.tobytes())
    surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_A8, w, h, stride)
    return surf, plate or symbolic


def glyph_for(gicon):
    for prefer_symbolic in (True, False):
        path, symbolic = _source(gicon, prefer_symbolic)
        if path is None:
            return None
        key = (path, symbolic)
        if key not in _cache:
            try:
                _cache[key] = _glyph(path, symbolic)
            except (GLib.Error, ValueError, OSError) as e:
                print("nothing-de: icon", path, e)
                _cache[key] = None
        if _cache[key] is not None or not symbolic:
            return _cache[key]
    return None


class NothingIcon(Gtk.DrawingArea):
    """Round plate with the app's glyph, drawn in the widget's CSS colour."""

    def __init__(self, app, size):
        super().__init__(content_width=size, content_height=size,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.add_css_class("n-icon")
        self.gicon = app_icon(app)
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, w, h):
        g = glyph_for(self.gicon)
        if g is None:
            g = glyph_for(Gio.ThemedIcon.new("application-x-executable"))
        if g is None:
            return
        surf, tight = g
        box = min(w, h) * (0.5 if tight else 0.58)
        s = box / max(surf.get_width(), surf.get_height())
        fg = self.get_color()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
        cr.translate((w - surf.get_width() * s) / 2, (h - surf.get_height() * s) / 2)
        cr.scale(s, s)
        pat = cairo.SurfacePattern(surf)
        pat.set_filter(cairo.FILTER_GOOD)
        cr.mask(pat)


def icon_widget(app, size, cfg):
    """App icon in the style chosen in the settings."""
    if cfg.get("icons") == "original":
        return Gtk.Image(gicon=app_icon(app), pixel_size=size)
    return NothingIcon(app, size)
