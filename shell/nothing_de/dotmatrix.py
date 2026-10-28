"""Dot-matrix typography in the spirit of Nothing's Ndot face, drawn with
cairo so no special font has to be installed."""
import math

from gi.repository import Gtk

_G = {
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "111 010 010 010 010 010 111",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 10001 01010 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    ":": "0 1 1 0 1 1 0",
    ".": "0 0 0 0 0 0 1",
    ",": "00 00 00 00 00 01 10",
    "!": "1 1 1 1 1 0 1",
    "?": "01110 10001 00001 00010 00100 00000 00100",
    "-": "000 000 000 111 000 000 000",
    "+": "00000 00100 00100 11111 00100 00100 00000",
    "/": "00001 00010 00010 00100 01000 01000 10000",
    "%": "11000 11001 00010 00100 01000 10011 00011",
    "°": "111 101 111 000 000 000 000",
    " ": "000 000 000 000 000 000 000",
}
GLYPHS = {k: v.split() for k, v in _G.items()}
_FALLBACK = {"Ä": "A", "Ö": "O", "Ü": "U", "ß": "S", "É": "E", "È": "E"}
ROWS = 7


def _glyph(ch):
    ch = ch.upper()
    ch = _FALLBACK.get(ch, ch)
    return GLYPHS.get(ch, GLYPHS["?"])


def columns(text):
    """Total number of dot columns, including 1 column spacing between glyphs."""
    if not text:
        return 0
    return sum(len(_glyph(c)[0]) for c in text) + len(text) - 1


def draw(cr, text, x, y, pitch, color, dim=None, dot_ratio=0.78):
    """Draw text with its top-left at (x, y). `pitch` is the grid size of one
    dot cell. If `dim` is given, unlit dots of each glyph cell are drawn too."""
    r = pitch * dot_ratio / 2
    cx = x
    for i, ch in enumerate(text):
        g = _glyph(ch)
        w = len(g[0])
        for row in range(ROWS):
            line = g[row]
            for col in range(w):
                on = line[col] == "1"
                if not on and dim is None:
                    continue
                cr.set_source_rgba(*(color if on else dim))
                cr.arc(cx + col * pitch + pitch / 2, y + row * pitch + pitch / 2,
                       r, 0, 2 * math.pi)
                cr.fill()
        cx += (w + 1) * pitch


def rgba_tuple(rgba):
    return (rgba.red, rgba.green, rgba.blue, rgba.alpha)


class DotLabel(Gtk.DrawingArea):
    """A label rendered in dot-matrix. Uses the widget's CSS colour."""

    def __init__(self, text="", pitch=6, accent_last=False, show_dim=False, align=0.0):
        super().__init__()
        self.text = text
        self.pitch = pitch
        self.accent_last = accent_last
        self.show_dim = show_dim
        self.align = align
        self.accent = None
        self.set_draw_func(self._draw)
        self._update_size()

    def _update_size(self):
        self.set_content_width(max(1, int(columns(self.text) * self.pitch)))
        self.set_content_height(int(ROWS * self.pitch))

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self._update_size()
            self.queue_draw()

    def set_pitch(self, pitch):
        self.pitch = pitch
        self._update_size()
        self.queue_draw()

    def set_accent(self, rgba_tuple_):
        self.accent = rgba_tuple_
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        fg = rgba_tuple(self.get_color())
        dim = (fg[0], fg[1], fg[2], 0.07) if self.show_dim else None
        tw = columns(self.text) * self.pitch
        x = (width - tw) * self.align
        if self.accent_last and self.accent and len(self.text) > 1:
            draw(cr, self.text[:-1], x, 0, self.pitch, fg, dim)
            off = (columns(self.text[:-1]) + 1) * self.pitch
            draw(cr, self.text[-1], x + off, 0, self.pitch, self.accent, dim)
        else:
            draw(cr, self.text, x, 0, self.pitch, fg, dim)
