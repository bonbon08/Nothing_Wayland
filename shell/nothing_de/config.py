"""Shared configuration of the Nothing desktop (shell + settings app).

Stored as JSON in ~/.config/nothing-de/config.json. Both processes watch the
file, so a change made in the settings app is applied live by the shell.
"""
import copy
import json
import os
import shutil

from gi.repository import Gio, GLib, GObject

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "nothing-de")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def _find_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("NOTHING_DE_DATA", ""),
        os.path.join(here, "..", "..", "data"),          # source checkout
        os.path.join(here, "..", "data"),                # installed share dir
        "/usr/local/share/nothing-de/data",
        "/usr/share/nothing-de/data",
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "wallpapers")):
            return os.path.realpath(c)
    return os.path.realpath(candidates[1])


DATA_DIR = _find_data_dir()
WALLPAPER_DIR = os.path.join(DATA_DIR, "wallpapers")

ACCENTS = [
    ("Nothing Rot", "#D71921"),
    ("Orange", "#FF6A13"),
    ("Gelb", "#F5C400"),
    ("Grün", "#30C76A"),
    ("Türkis", "#00B3A4"),
    ("Blau", "#2F6BFF"),
    ("Lila", "#8C5CFF"),
    ("Pink", "#FF4F9A"),
    ("Grau", "#8A8A8A"),
]

DEFAULTS = {
    "theme": "dark",                 # dark | light
    "accent": "#D71921",
    "wallpaper": os.path.join(WALLPAPER_DIR, "dots-dark.svg"),
    "wallpaper_fit": "cover",        # cover | contain | fill
    "background_color": "#000000",
    "workspaces": 4,
    "terminal": "",
    "files": "",
    "keyboard": {"layout": "de", "variant": "", "options": ""},
    "bar": {"clock_24h": True, "show_seconds": False, "show_date": True,
            "show_workspaces": True},
    "icons": "nothing",              # nothing (monochrome) | original
    "dock": {
        "icon_size": 48,
        "launcher": "left",          # left | right: position of the apps button
        "pinned": [
            "org.gnome.Nautilus.desktop",
            "firefox.desktop",
            "org.gnome.Console.desktop",
            "org.gnome.TextEditor.desktop",
            "nothing-settings.desktop",
        ],
    },
    "weather": {"city": "Berlin", "lat": 52.52, "lon": 13.41},
    "widgets": [
        {"type": "clock", "x": 48, "y": 72},
        {"type": "weather", "x": 48, "y": 268},
        {"type": "battery", "x": 236, "y": 268},
        {"type": "calendar", "x": 48, "y": 456},
    ],
    "notes": "",
    "photo": "",
    "dnd": False,
}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if not os.path.exists(CONFIG_PATH):
            self.save()
        self._monitor = Gio.File.new_for_path(CONFIG_PATH).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._monitor.set_rate_limit(250)
        self._monitor.connect("changed", self._on_file_changed)

    def load(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                self.data = deep_merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            self.data = copy.deepcopy(DEFAULTS)
        except (OSError, ValueError) as e:
            print("nothing-de: config unreadable, using defaults:", e)

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)

    def _on_file_changed(self, _mon, _file, _other, event):
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                         Gio.FileMonitorEvent.CREATED,
                         Gio.FileMonitorEvent.RENAMED,
                         Gio.FileMonitorEvent.MOVED_IN):
            return
        old = self.data
        self.load()
        if old != self.data:
            self.emit("changed")

    def get(self, path, default=None):
        node = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path, value, notify=True):
        parts = path.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if node.get(parts[-1]) == value:
            return
        node[parts[-1]] = value
        self.save()
        if notify:
            self.emit("changed")


_config = None


def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config


def first_available(*commands):
    for c in commands:
        if c and shutil.which(c.split()[0]):
            return c
    return None


def terminal_command(cfg):
    return first_available(cfg.get("terminal"), "kgx", "gnome-terminal", "ptyxis",
                           "foot", "kitty", "alacritty", "konsole", "xterm")
