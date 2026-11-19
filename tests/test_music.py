"""Equalizer, Medien-Hilfen, Live-Hintergründe, Akzent aus dem Bild und Dot-Bitmaps."""
import cairo
from nothing_de import dotmatrix, equalizer, livewall, media, theme


def test_presets_have_ten_bands_and_are_recognised():
    for key, _name, gains in equalizer.PRESETS:
        assert len(gains) == len(equalizer.FREQS)
        assert equalizer.matching_preset(gains) == key
    assert equalizer.matching_preset([1, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == "custom"
    assert equalizer.preset_gains("gibt-es-nicht") == [0.0] * 10


def test_gains_are_clamped_and_padded():
    g = equalizer.clamp_gains([99, -99, "x"])
    assert g[0] == equalizer.MAX_DB and g[1] == -equalizer.MAX_DB
    assert g[2:] == [0.0] * 8


def test_filter_chain_conf_chains_all_bands():
    conf = equalizer.filter_chain_conf([3] * 10, target="alsa_output.test")
    assert conf.count("type = builtin") == 10
    assert "bq_lowshelf" in conf and "bq_highshelf" in conf
    assert conf.count('output = "eq') == 9
    assert 'node.name = "nothing_eq"' in conf
    assert 'target.object = "alsa_output.test"' in conf
    assert '"Freq" = 16000.0' in conf


def test_params_pod_sets_every_gain():
    pod = equalizer.params_pod([1.5] * 10)
    assert pod.startswith("{ params = [") and pod.count(":Gain") == 10
    assert '"eq9:Gain" 1.50' in pod


def test_media_helpers():
    assert media.fmt_time(0) == "0:00"
    assert media.fmt_time(65_000_000) == "1:05"
    assert media.fmt_time(3_725_000_000) == "1:02:05"
    assert media.player_label("org.mpris.MediaPlayer2.spotify") == "Spotify"
    assert media.player_label("org.mpris.MediaPlayer2.firefox.instance_1_23") == "Firefox"
    assert media.art_initial("toxic") == "T"
    assert media.art_initial("") == "♪"


def test_bitmap_matches_columns():
    rows = dotmatrix.bitmap("12")
    assert len(rows) == dotmatrix.ROWS
    assert len(rows[0]) == dotmatrix.columns("12")
    assert any(any(r) for r in rows)


def test_live_paths():
    assert livewall.is_live("live:snow-forest")
    assert not livewall.is_live("/a/b.png")
    assert livewall.is_video("/x/clip.MP4") and not livewall.is_video("/x/a.jpg")
    assert livewall.scene_for("live:gibt-es-nicht") is None
    assert isinstance(livewall.scene_for("live:ember"), livewall.Ember)


def test_every_scene_draws_frames():
    for key, cls in livewall.SCENES.items():
        scene = cls()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 160, 90)
        cr = cairo.Context(surf)
        for t in (0.0, 1.5, 30.0):
            scene.draw(cr, 160, 90, t)
        assert theme.on_color(scene.ACCENT) in ("#000000", "#FFFFFF"), key
        tex = livewall.thumbnail(key, 64, 36)
        assert tex.get_width() == 64 and tex.get_height() == 36


def test_accent_from_pixels():
    red = [(220, 30, 30)] * 50 + [(10, 10, 10)] * 50
    hx = theme.accent_from_pixels(red)
    r, g, b = theme.hex_to_rgb(hx)
    assert r > 0.7 and g < 0.3 and b < 0.3
    assert theme.accent_from_pixels([(128, 128, 128)] * 100) is None


def test_shell_app_id_per_compositor():
    from gi.repository import Gio
    from nothing_de import system
    # the desktop's own shell keeps its name, a nested test compositor gets one of its own
    assert system.shell_app_id("wayland-0") == "eu.nothing_de.Shell"
    assert system.shell_app_id("") == "eu.nothing_de.Shell"
    for display in ("wayland-1", "/run/user/1000/wayland-2", "1x"):
        app_id = system.shell_app_id(display)
        assert app_id != "eu.nothing_de.Shell" and Gio.Application.id_is_valid(app_id)
