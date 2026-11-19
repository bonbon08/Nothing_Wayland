"""Themes: ready-made looks, a random one, and a short code to share a look.

A theme is a handful of config values (THEME_KEYS): light or dark, accent colour,
wallpaper, the shape of the cards (style.*) and the music widgets' look. Applying a
theme writes them into the config, the shell and the settings app follow live.
"""
import base64
import colorsys
import json
import os
import random

from .config import DEFAULTS, WALLPAPER_DIR

CODE_PREFIX = "NOTHING1:"

# key -> check(value) -> bool
THEME_KEYS = {
    "theme": lambda v: v in ("dark", "light"),
    "accent": lambda v: isinstance(v, str) and len(v) == 7 and v.startswith("#") and
    all(c in "0123456789abcdefABCDEF" for c in v[1:]),
    "wallpaper": lambda v: isinstance(v, str) and len(v) < 1024,
    "style.radius": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 1.6,
    "style.glass": lambda v: isinstance(v, (int, float)) and 0.0 <= v <= 0.8,
    "style.font": lambda v: v in ("sans", "mono"),
    "desktop.visualizer": lambda v: v in ("off", "wave", "bars", "dots"),
    "dotvis.mode": lambda v: v in ("face", "pulse", "ripple", "torus", "clock", "ticker"),
}


def _wp(name):
    return os.path.join(WALLPAPER_DIR, name)


# (key, name, description, values)
PRESETS = [
    ("classic", "Nothing", "Schwarz, Rot und Punkte",
     {"theme": "dark", "accent": "#D71921", "wallpaper": _wp("dots-dark.svg"),
      "style.radius": 1.0, "style.glass": 0.0, "style.font": "sans",
      "desktop.visualizer": "off", "dotvis.mode": "face"}),
    ("horizon", "Horizont", "Ereignishorizont, warmes Orange, Welle",
     {"theme": "dark", "accent": "#FF8A3D", "wallpaper": "live:black-hole",
      "style.radius": 1.0, "style.glass": 0.35, "style.font": "sans",
      "desktop.visualizer": "wave", "dotvis.mode": "torus"}),
    ("frost", "Frost", "Verschneiter Wald, Eisblau, Glas",
     {"theme": "dark", "accent": "#8CC8FF", "wallpaper": "live:snow-forest",
      "style.radius": 1.2, "style.glass": 0.45, "style.font": "sans",
      "desktop.visualizer": "dots", "dotvis.mode": "ripple"}),
    ("paper", "Papier", "Hell, Monospace, kantig",
     {"theme": "light", "accent": "#D71921", "wallpaper": _wp("dots-light.svg"),
      "style.radius": 0.45, "style.glass": 0.0, "style.font": "mono",
      "desktop.visualizer": "off", "dotvis.mode": "clock"}),
    ("phosphor", "Phosphor", "Grün auf Schwarz wie ein alter Monitor",
     {"theme": "dark", "accent": "#30C76A", "wallpaper": _wp("glyph-dark.svg"),
      "style.radius": 0.3, "style.glass": 0.0, "style.font": "mono",
      "desktop.visualizer": "bars", "dotvis.mode": "ticker"}),
    ("ember", "Glut", "Glimmende Funken, Orange, weich",
     {"theme": "dark", "accent": "#FF6A13", "wallpaper": "live:ember",
      "style.radius": 1.4, "style.glass": 0.25, "style.font": "sans",
      "desktop.visualizer": "wave", "dotvis.mode": "pulse"}),
    ("dusk", "Blaue Stunde", "Dämmerung, Lila, Glas",
     {"theme": "dark", "accent": "#8C5CFF", "wallpaper": "live:blue-hour",
      "style.radius": 1.1, "style.glass": 0.4, "style.font": "sans",
      "desktop.visualizer": "dots", "dotvis.mode": "face"}),
]


def _default(key):
    node = DEFAULTS
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def current(cfg):
    """The theme values in the config right now."""
    return {k: cfg.get(k, _default(k)) for k in THEME_KEYS}


def matching_preset(values):
    """Key of the preset these values are (None if they are the user's own mix)."""
    for key, _name, _desc, preset in PRESETS:
        if all(_same(values.get(k), v) for k, v in preset.items()):
            return key
    return None


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.01
    if isinstance(a, str) and isinstance(b, str) and a.startswith("#"):
        return a.lower() == b.lower()
    return a == b


def preset(key):
    return next((p[3] for p in PRESETS if p[0] == key), None)


def apply(cfg, values):
    """Write the theme into the config (one change signal at the end). A picked theme ends
    "Farbe aus dem Hintergrund", it brings its own colour."""
    values = clean(values)
    if not values:
        return
    cfg.set("accent_auto", False, notify=False)
    for k, v in values.items():
        cfg.set(k, v, notify=False)
    cfg.save()
    cfg.emit("changed")


def clean(values):
    """Only known keys with sensible values (from a pasted code, never trusted)."""
    if not isinstance(values, dict):
        return {}
    return {k: v for k, v in values.items() if k in THEME_KEYS and THEME_KEYS[k](v)}


def encode(values):
    """A short text to share the look, e.g. in a chat."""
    raw = json.dumps(clean(values), separators=(",", ":"), sort_keys=True).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(code):
    """The theme in a code; None if it is not one."""
    code = (code or "").strip()
    if not code.startswith(CODE_PREFIX):
        return None
    body = code[len(CODE_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError):
        return None
    values = clean(data)
    return values or None


def surprise(rng=None, wallpapers=None):
    """A random but matching look: a vivid accent, one of the wallpapers and a shape."""
    rng = rng or random.Random()
    h = rng.random()
    s = rng.uniform(0.55, 0.9)
    v = rng.uniform(0.8, 0.98)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    accent = "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))
    light = rng.random() < 0.2
    walls = list(wallpapers or [])
    if not walls:
        walls = [p[3]["wallpaper"] for p in PRESETS if p[3]["theme"] == ("light" if light else "dark")]
    return {
        "theme": "light" if light else "dark",
        "accent": accent,
        "wallpaper": rng.choice(walls),
        "style.radius": round(rng.choice([0.3, 0.6, 1.0, 1.2, 1.4]), 2),
        "style.glass": round(rng.choice([0.0, 0.0, 0.25, 0.4]), 2),
        "style.font": rng.choice(["sans", "sans", "mono"]),
        "desktop.visualizer": rng.choice(["off", "wave", "bars", "dots"]),
        "dotvis.mode": rng.choice(["face", "pulse", "ripple", "torus", "clock", "ticker"]),
    }
