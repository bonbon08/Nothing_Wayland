import pytest

from nothing_de import config, theme


@pytest.mark.parametrize("value, expected", [
    ("#FF0000", (1.0, 0.0, 0.0)),
    ("00FF00", (0.0, 1.0, 0.0)),        # ohne '#' geht auch
])
def test_hex_to_rgb(value, expected):
    assert theme.hex_to_rgb(value) == pytest.approx(expected)


def test_hex_to_rgb_falls_back_to_nothing_red_for_broken_input():
    assert theme.hex_to_rgb("") == (0.84, 0.10, 0.13)
    assert theme.hex_to_rgb("#FFF") == (0.84, 0.10, 0.13)


@pytest.mark.parametrize("background, text", [
    ("#F5C400", "#000000"),   # Gelb: dunkle Schrift
    ("#FFFFFF", "#000000"),
    ("#000000", "#FFFFFF"),   # Schwarz: helle Schrift
    ("#2F6BFF", "#FFFFFF"),
])
def test_on_color_is_readable(background, text):
    assert theme.on_color(background) == text


class _Cfg:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_palette_follows_theme_and_accent():
    light = theme.palette(_Cfg({"theme": "light", "accent": "#F5C400"}))
    assert light["bg"] == theme.PALETTES["light"]["bg"]
    assert light["accent"] == "#F5C400"
    assert light["on_accent"] == "#000000"


def test_palette_unknown_theme_uses_dark_and_missing_accent_uses_default():
    p = theme.palette(_Cfg({"theme": "neon"}))
    assert p["bg"] == theme.PALETTES["dark"]["bg"]
    assert p["accent"] == "#D71921"


def test_every_palette_has_the_same_keys():
    assert theme.PALETTES["dark"].keys() == theme.PALETTES["light"].keys()


def test_build_css_is_fully_formatted_for_every_theme_and_accent():
    for name, accent in config.ACCENTS:
        for mode in ("dark", "light"):
            css = theme.build_css(_Cfg({"theme": mode, "accent": accent}))
            assert accent in css, name
            assert "{p[" not in css, "unaufgelöster Platzhalter"
            assert "{{" not in css and "}}" not in css, "unescapte Klammern"
            assert css.count("{") == css.count("}"), "unbalancierte CSS-Klammern"


@pytest.mark.parametrize("accent, gnome", [
    ("#2F6BFF", "blue"),
    ("#D71921", "red"),
    ("#30C76A", "green"),
    ("#8A8A8A", "slate"),   # wenig Sättigung -> slate
])
def test_nearest_gnome_accent(accent, gnome):
    assert theme.nearest_gnome_accent(accent) == gnome


def test_every_configured_accent_maps_to_a_gnome_accent():
    for _name, accent in config.ACCENTS:
        assert theme.nearest_gnome_accent(accent) in set(theme.GNOME_ACCENTS) | {"slate"}
