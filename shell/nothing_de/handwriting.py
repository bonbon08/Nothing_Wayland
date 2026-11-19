"""A handwritten "hallo", written stroke by stroke (the island's greeting).

One continuous pen line of cubic Bézier segments in a box of WIDTH × HEIGHT; `draw`
shows the first `fraction` of its length, so it looks as if it were being written.
"""
import math

WIDTH, HEIGHT = 114.0, 52.0

# (start, control 1, control 2, end); each segment starts where the last one ended
STROKE = [
    # h: lead-in, the loop of the ascender, stem, hump
    ((2, 46), (10, 40), (24, 14), (22, 6)),
    ((22, 6), (19, 0), (12, 4), (13, 20)),
    ((13, 20), (13, 32), (12, 42), (11, 48)),
    ((11, 48), (14, 36), (20, 28), (26, 30)),
    ((26, 30), (32, 32), (29, 44), (31, 47)),
    # a: over to its top, round, up and down the stem
    ((31, 47), (36, 50), (44, 30), (52, 32)),
    ((52, 32), (44, 28), (36, 36), (38, 43)),
    ((38, 43), (40, 50), (50, 48), (52, 38)),
    ((52, 38), (53, 34), (53, 32), (53, 31)),
    ((53, 31), (52, 38), (52, 44), (56, 47)),
    # l
    ((56, 47), (62, 44), (72, 16), (68, 6)),
    ((68, 6), (66, 0), (60, 4), (61, 16)),
    ((61, 16), (62, 30), (60, 44), (66, 47)),
    # l
    ((66, 47), (72, 44), (86, 16), (82, 6)),
    ((82, 6), (80, 0), (74, 4), (75, 16)),
    ((75, 16), (76, 30), (74, 44), (80, 47)),
    # o and a little flourish
    ((80, 47), (84, 48), (88, 40), (94, 32)),
    ((94, 32), (88, 33), (87, 46), (95, 48)),
    ((95, 48), (103, 49), (104, 34), (97, 32)),
    ((97, 32), (100, 34), (106, 33), (112, 30)),
]


def _bezier(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def polyline(steps=24):
    """The stroke as points, with the running length at each: [(x, y, length)]."""
    pts = [(STROKE[0][0][0], STROKE[0][0][1], 0.0)]
    for seg in STROKE:
        for i in range(1, steps + 1):
            x, y = _bezier(*seg, i / steps)
            px, py, length = pts[-1]
            pts.append((x, y, length + math.hypot(x - px, y - py)))
    return pts


_POINTS = polyline()
LENGTH = _POINTS[-1][2]


def ease(t):
    """Slow start and end, like a pen."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def draw(cr, x, y, w, h, fraction, rgba, line_width=None):
    """Draw the first `fraction` (0..1) of the word into the box x, y, w, h (aspect kept);
    returns the pen position (for a glowing tip) or None."""
    s = min(w / WIDTH, h / HEIGHT)
    ox = x + (w - WIDTH * s) / 2
    oy = y + (h - HEIGHT * s) / 2
    upto = LENGTH * max(0.0, min(1.0, fraction))
    if upto <= 0:
        return None
    cr.save()
    cr.set_source_rgba(*rgba)
    cr.set_line_width(line_width or max(1.2, 2.6 * s))
    cr.set_line_cap(1)    # round
    cr.set_line_join(1)
    px, py, _ = _POINTS[0]
    cr.move_to(ox + px * s, oy + py * s)
    tip = None
    for (ax, ay, al), (bx, by, bl) in zip(_POINTS, _POINTS[1:]):
        if bl <= upto:
            cr.line_to(ox + bx * s, oy + by * s)
            tip = (ox + bx * s, oy + by * s)
            continue
        k = (upto - al) / max(1e-6, bl - al)
        tip = (ox + (ax + (bx - ax) * k) * s, oy + (ay + (by - ay) * k) * s)
        cr.line_to(*tip)
        break
    cr.stroke()
    cr.restore()
    return tip
