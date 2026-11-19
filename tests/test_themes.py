"""Themes, Theme-Codes, Start-Animation, Handschrift, Hintergrund-Karussell und Audio-Ausgaben."""
import random

import cairo
import pytest

from nothing_de import handwriting, media, splash, styles, system, theme, wallswitch


def test_presets_are_valid_and_recognised():
    for key, _name, _desc, values in styles.PRESETS:
        assert styles.clean(values) == values, key
        assert set(values) == set(styles.THEME_KEYS)
        assert styles.matching_preset(values) == key
    own = dict(styles.preset("classic"), accent="#123456")
    assert styles.matching_preset(own) is None


def test_code_round_trip():
    values = styles.preset("horizon")
    code = styles.encode(values)
    assert code.startswith(styles.CODE_PREFIX)
    assert styles.decode(code) == values
    assert styles.decode("  " + code + "\n") == values


@pytest.mark.parametrize("code", ["", "hallo", "NOTHING1:", "NOTHING1:!!!", "NOTHING1:e30"])
def test_bad_codes_are_rejected(code):
    assert styles.decode(code) is None


def test_clean_drops_unknown_keys_and_bad_values():
    dirty = {"accent": "rot", "theme": "dark", "style.radius": 99, "terminal": "rm -rf ~",
             "style.glass": 0.3}
    assert styles.clean(dirty) == {"theme": "dark", "style.glass": 0.3}
    assert styles.clean("kein dict") == {}


def test_surprise_is_a_valid_theme():
    for seed in range(20):
        values = styles.surprise(random.Random(seed))
        assert styles.clean(values) == values


class _Cfg:
    def __init__(self):
        self.data = {}
        self.emitted = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value, notify=True):
        self.data[key] = value

    def save(self):
        pass

    def emit(self, _sig):
        self.emitted += 1


def test_apply_writes_all_keys_once():
    cfg = _Cfg()
    cfg.data["accent_auto"] = True
    styles.apply(cfg, styles.preset("paper"))
    assert cfg.emitted == 1
    assert cfg.data["accent_auto"] is False
    assert styles.matching_preset(styles.current(cfg)) == "paper"


def test_scale_radii_keeps_pills_round():
    css = "a { border-radius: 20px; } b { border-radius: 999px; } c { border-radius: 9px; }"
    out = theme.scale_radii(css, 0.5)
    assert "border-radius: 10px" in out and "border-radius: 999px" in out
    assert "border-radius: 4.5px" in out
    assert theme.scale_radii(css, 1.0) == css


def test_handwriting_draws_and_reports_the_pen():
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 60)
    cr = cairo.Context(surf)
    assert handwriting.draw(cr, 0, 0, 120, 60, 0.0, (1, 1, 1, 1)) is None
    tip = handwriting.draw(cr, 0, 0, 120, 60, 0.5, (1, 1, 1, 1))
    assert tip is not None and 0 <= tip[0] <= 120 and 0 <= tip[1] <= 60
    assert handwriting.LENGTH > 0
    assert handwriting.ease(0) == 0 and handwriting.ease(1) == 1


def test_splash_frames_render_and_end_transparent():
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 200)
    for t in (0.0, 0.8, 1.5, 2.2, splash.DURATION - 0.3):
        splash.frame(cairo.Context(surf), 320, 200, t)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 32, 20)
    splash.frame(cairo.Context(surf), 32, 20, splash.DURATION + 0.1)
    surf.flush()
    assert not any(surf.get_data())


def test_card_layout_is_symmetric_and_fades_out():
    x0, a0, s0, o0 = wallswitch.card_layout(0, 500)
    assert (x0, a0, s0, o0) == (0, 0, 1.0, 1.0)
    for d in (0.5, 1, 2, 3):
        xl, al, sl, ol = wallswitch.card_layout(-d, 500)
        xr, ar, sr, orr = wallswitch.card_layout(d, 500)
        assert xl == -xr and al == -ar and sl == sr and ol == orr
    assert wallswitch.card_layout(1, 500)[0] < wallswitch.card_layout(2, 500)[0]
    assert wallswitch.card_layout(6, 500)[3] == 0


def test_display_names():
    assert wallswitch.display_name("/a/dots-dark.svg") == "dots dark"
    assert wallswitch.display_name("live:black-hole") == "Ereignishorizont"


def test_parse_sinks_skips_the_equalizer():
    text = ('[{"name":"alsa_output.pci","description":"Lautsprecher"},'
            '{"name":"nothing_eq","description":"Nothing Equalizer"},'
            '{"name":"bluez_output.AA","description":"Kopfhörer"}]')
    sinks = system.parse_sinks(text, "bluez_output.AA")
    assert sinks == [("alsa_output.pci", "Lautsprecher", False),
                     ("bluez_output.AA", "Kopfhörer", True)]
    assert system.parse_sinks("kaputt") == []


def test_loop_cycles():
    assert media.next_loop("None") == "Playlist"
    assert media.next_loop("Playlist") == "Track"
    assert media.next_loop("Track") == "None"
