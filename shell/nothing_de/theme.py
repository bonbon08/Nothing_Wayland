"""Nothing OS inspired styling, generated from the user's config."""
from gi.repository import Gdk, Gio, Gtk

PALETTES = {
    "dark": {
        "bg": "#000000", "surface": "#111111", "card": "#1B1B1D",
        "card_hi": "#26262A", "border": "#2C2C30", "fg": "#FFFFFF",
        "muted": "#8E8E93", "dim": "#3A3A3E", "glass": "rgba(16,16,18,0.82)",
        "scrim": "rgba(0,0,0,0.45)",
    },
    "light": {
        "bg": "#F2F2F2", "surface": "#FFFFFF", "card": "#FFFFFF",
        "card_hi": "#ECECEC", "border": "#E2E2E2", "fg": "#000000",
        "muted": "#6E6E73", "dim": "#D4D4D8", "glass": "rgba(250,250,250,0.86)",
        "scrim": "rgba(0,0,0,0.25)",
    },
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) < 6:
        return (0.84, 0.10, 0.13)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def on_color(h):
    """Readable text colour on top of the given background."""
    r, g, b = hex_to_rgb(h)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if lum > 0.6 else "#FFFFFF"


def palette(cfg):
    p = dict(PALETTES.get(cfg.get("theme"), PALETTES["dark"]))
    p["accent"] = cfg.get("accent") or "#D71921"
    p["on_accent"] = on_color(p["accent"])
    return p


def build_css(cfg):
    p = palette(cfg)
    return f"""
@define-color n_bg {p['bg']};
@define-color n_surface {p['surface']};
@define-color n_card {p['card']};
@define-color n_card_hi {p['card_hi']};
@define-color n_border {p['border']};
@define-color n_fg {p['fg']};
@define-color n_muted {p['muted']};
@define-color n_dim {p['dim']};
@define-color n_accent {p['accent']};
@define-color n_on_accent {p['on_accent']};
@define-color accent_bg_color {p['accent']};
@define-color accent_color {p['accent']};
@define-color accent_fg_color {p['on_accent']};

:root {{ --accent-bg-color: {p['accent']}; --accent-color: {p['accent']}; --accent-fg-color: {p['on_accent']}; }}
window.n-layer, window.n-layer > * {{ background: transparent; }}
.n-root {{ color: @n_fg; font-family: "NType 82", "Adwaita Sans", "Inter", sans-serif; }}
.n-mono, .n-caps {{ font-family: "Space Mono", "Adwaita Mono", "JetBrains Mono", monospace; }}
.n-caps {{ font-size: 10.5px; letter-spacing: 1.6px; color: @n_muted; }}
.n-muted {{ color: @n_muted; }}
.n-accent-text {{ color: @n_accent; }}

/* ---------- top bar ---------- */
.n-bar {{
  background: {p['glass']};
  border-bottom: 1px solid @n_border;
  min-height: 32px; padding: 0 10px;
}}
.n-bar button {{
  background: transparent; border: none; box-shadow: none;
  border-radius: 999px; padding: 2px 10px; min-height: 24px; color: @n_fg;
}}
.n-bar button:hover {{ background: alpha(@n_fg, 0.08); }}
.n-bar .n-appname {{ font-weight: 700; }}
.n-bar .n-clock {{ font-family: "Space Mono", "Adwaita Mono", monospace; font-size: 12.5px; }}
.n-ws-dot {{ min-width: 7px; min-height: 7px; border-radius: 99px; margin: 0 3px;
  background: @n_dim; padding: 0; }}
.n-ws-dot.occupied {{ background: @n_muted; }}
.n-ws-dot.active {{ background: @n_accent; min-width: 18px; }}
button.n-ws {{ padding: 4px 4px; min-height: 0; min-width: 0; }}

/* ---------- dock ---------- */
.n-dock {{
  background: {p['glass']};
  border: 1px solid @n_border; border-radius: 26px; padding: 8px 10px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.35);
}}
.n-dock button.n-dock-item {{
  background: transparent; border: none; box-shadow: none; padding: 4px;
  border-radius: 16px; transition: all 160ms ease;
}}
.n-dock button.n-dock-item:hover {{ background: alpha(@n_fg, 0.08); transform: translateY(-4px); }}
.n-dock .n-run-dot {{ min-width: 4px; min-height: 4px; border-radius: 99px; background: transparent; }}
.n-dock .n-run-dot.running {{ background: @n_fg; }}
.n-dock .n-run-dot.focused {{ background: @n_accent; min-width: 12px; }}
.n-dock-slot.drop-before {{ box-shadow: -5px 0 0 -2px @n_accent; }}
.n-dock-slot.drop-after {{ box-shadow: 5px 0 0 -2px @n_accent; }}
.n-icon {{ background: @n_card_hi; color: @n_fg; border-radius: 999px;
  box-shadow: inset 0 0 0 1px alpha(@n_fg, 0.06); }}
.n-dock-sep {{ min-width: 1px; background: @n_border; margin: 8px 6px; }}

/* ---------- cards / widgets ---------- */
.n-card {{
  background: @n_card; border-radius: 28px; color: @n_fg;
  border: 1px solid alpha(@n_border, 0.6);
}}
.n-card.editing {{ border: 1px dashed @n_accent; }}
.n-widget-title {{ font-family: "Space Mono", "Adwaita Mono", monospace; font-size: 10.5px;
  letter-spacing: 1.6px; color: @n_muted; }}
.n-big {{ font-size: 30px; font-weight: 300; }}
.n-cal-day {{ font-family: "Space Mono", "Adwaita Mono", monospace; font-size: 11px;
  min-width: 24px; min-height: 17px; border-radius: 99px; font-size: 10px; }}
.n-cal-day.today {{ background: @n_accent; color: @n_on_accent; }}
.n-cal-day.other {{ color: @n_dim; }}
.n-cal-head {{ color: @n_muted; font-size: 10px; }}
button.n-remove {{ background: @n_accent; color: @n_on_accent; border-radius: 99px;
  min-width: 22px; min-height: 22px; padding: 0; }}
textview.n-notes, textview.n-notes text {{ background: transparent; color: @n_fg; }}

/* ---------- panels (launcher, control centre, menus) ---------- */
.n-scrim {{ background: transparent; }}
.n-scrim.dim {{ background: {p['scrim']}; }}
.n-panel {{
  background: @n_surface; color: @n_fg; border-radius: 30px;
  border: 1px solid @n_border; box-shadow: 0 18px 50px rgba(0,0,0,0.45);
  padding: 18px;
}}
.n-search {{
  background: @n_card; border-radius: 999px; min-height: 44px; padding: 0 16px;
  border: 1px solid @n_border; font-size: 16px; color: @n_fg;
}}
.n-search:focus-within {{ border-color: @n_accent; outline: none; box-shadow: none; }}
.n-root *:focus-visible {{ outline-color: alpha(@n_accent, 0.6); }}
scale.n-slider:focus-visible, scale.n-slider *:focus-visible {{ outline: none; }}
scale.n-slider trough {{ outline: none; }}
.n-app-tile {{ background: transparent; border: none; box-shadow: none; border-radius: 20px; padding: 10px 4px; }}
.n-app-tile:hover, flowboxchild:selected .n-app-tile {{ background: @n_card_hi; }}
flowboxchild {{ background: transparent; padding: 0; border-radius: 20px; }}
flowboxchild:selected {{ background: transparent; }}
.n-app-tile label {{ font-size: 11.5px; }}

.n-tile {{
  background: @n_card; border-radius: 22px; padding: 14px; border: none; box-shadow: none;
  color: @n_fg; min-height: 64px;
}}
.n-tile:hover {{ background: @n_card_hi; }}
.n-tile.on {{ background: @n_accent; color: @n_on_accent; }}
.n-tile.on .n-caps {{ color: alpha(@n_on_accent, 0.75); }}
.n-round {{ border-radius: 999px; min-width: 44px; min-height: 44px; padding: 0;
  background: @n_card; border: none; box-shadow: none; color: @n_fg; }}
.n-round:hover {{ background: @n_card_hi; }}
.n-swatch {{ min-width: 26px; min-height: 26px; border-radius: 99px; padding: 0;
  border: 2px solid transparent; box-shadow: none; }}
.n-swatch.selected {{ border-color: @n_fg; }}
scale.n-slider trough {{ min-height: 30px; border-radius: 99px; background: @n_card;
  border: none; box-shadow: none; outline: none; }}
scale.n-slider highlight {{ border-radius: 99px; background: @n_fg; border: none;
  box-shadow: none; outline: none; }}
scale.n-slider slider {{ min-width: 0; min-height: 0; background: transparent; box-shadow: none; border: none; margin: 0; }}

/* ---------- notifications ---------- */
.n-toast {{ background: @n_surface; color: @n_fg; border-radius: 24px; padding: 14px 16px;
  border: 1px solid @n_border; box-shadow: 0 10px 30px rgba(0,0,0,0.4); }}
.n-toast .n-toast-title {{ font-weight: 700; }}

/* ---------- lock screen ---------- */
.n-lock {{ background: @n_bg; color: @n_fg; }}
.n-lock entry {{ background: @n_card; border-radius: 999px; min-height: 46px; min-width: 280px;
  padding: 0 18px; border: 1px solid @n_border; color: @n_fg; }}
.n-lock entry:focus-within {{ border-color: alpha(@n_fg, 0.35); outline: none; box-shadow: none; }}
.n-lock entry.error {{ border-color: @n_accent; }}

popover.n-menu > contents {{ background: @n_surface; color: @n_fg; border-radius: 18px;
  border: 1px solid @n_border; padding: 6px; }}
popover.n-menu modelbutton {{ border-radius: 12px; padding: 6px 12px; }}
popover.n-menu modelbutton:hover {{ background: @n_card_hi; }}
"""


class ThemeManager:
    """Keeps a CssProvider in sync with the config and mirrors light/dark +
    accent into the GNOME interface settings so GTK/libadwaita apps follow."""

    def __init__(self, cfg, sync_gsettings=True):
        import os
        self.cfg = cfg
        self.sync_gsettings = sync_gsettings and not os.environ.get("NOTHING_NO_GSETTINGS")
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER)
        cfg.connect("changed", lambda *_: self.apply())
        self.apply()

    def apply(self):
        self.provider.load_from_string(build_css(self.cfg))
        dark = self.cfg.get("theme") != "light"
        settings = Gtk.Settings.get_default()
        if settings and settings.find_property("gtk-interface-color-scheme"):
            settings.set_property("gtk-interface-color-scheme", 2 if dark else 3)
        elif settings:
            settings.set_property("gtk-application-prefer-dark-theme", dark)
        try:
            import gi
            gi.require_version("Adw", "1")
            from gi.repository import Adw
            if Adw.is_initialized():
                Adw.StyleManager.get_default().set_color_scheme(
                    Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
        except (ImportError, ValueError, TypeError):
            pass
        if self.sync_gsettings:
            sync_gnome_settings(self.cfg)


GNOME_ACCENTS = {
    "blue": "#3584E4", "teal": "#2190A4", "green": "#3A944A", "yellow": "#C88800",
    "orange": "#ED5B00", "red": "#E62D42", "pink": "#D56199", "purple": "#9141AC",
    "slate": "#6F8396",
}


def nearest_gnome_accent(hex_color):
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.18:
        return "slate"
    best, dist = "red", 9
    for name, hx in GNOME_ACCENTS.items():
        if name == "slate":
            continue
        h2, _, _ = colorsys.rgb_to_hls(*hex_to_rgb(hx))
        d = min(abs(h - h2), 1 - abs(h - h2))
        if d < dist:
            best, dist = name, d
    return best


def sync_gnome_settings(cfg):
    try:
        schema_src = Gio.SettingsSchemaSource.get_default()
        if not schema_src or not schema_src.lookup("org.gnome.desktop.interface", True):
            return
        s = Gio.Settings.new("org.gnome.desktop.interface")
        dark = cfg.get("theme") != "light"
        want = "prefer-dark" if dark else "default"
        if s.get_string("color-scheme") != want:
            s.set_string("color-scheme", want)
        schema = schema_src.lookup("org.gnome.desktop.interface", True)
        if schema.has_key("accent-color"):
            acc = nearest_gnome_accent(cfg.get("accent"))
            if s.get_string("accent-color") != acc:
                s.set_string("accent-color", acc)
    except Exception as e:  # never let theming break the shell
        print("nothing-de: gsettings sync failed:", e)
