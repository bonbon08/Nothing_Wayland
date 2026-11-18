"""Audio-Visualizer: Umrechnung der Spektren ohne Soundserver."""
import cairo

from nothing_de import audio, widget_sdk
from nothing_de import widgets  # noqa: F401  (registriert die Widgets)


def test_parse_magnitudes_reads_gstreamer_message():
    text = "spectrum, endtime=(guint64)1, magnitude=(float){ -80, -12.5, -3 };"
    assert audio.parse_magnitudes(text) == [-80.0, -12.5, -3.0]


def test_parse_magnitudes_without_values():
    assert audio.parse_magnitudes("spectrum, endtime=(guint64)1;") == []


def test_log_groups_cover_the_range_in_order():
    groups = audio.log_groups(256, 48)
    assert len(groups) == 48
    assert all(a < b for a, b in groups)
    assert all(groups[i][1] <= groups[i + 1][0] + 1 for i in range(len(groups) - 1))
    assert groups[-1][1] == 256


def test_db_levels_are_normalised():
    levels = audio.db_levels([-70.0] * 128 + [0.0] * 128, 16)
    assert len(levels) == 16
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert levels[0] == 0.0 and levels[-1] == 1.0


def test_db_levels_without_data_is_silence():
    assert audio.db_levels([], 8) == [0.0] * 8


def test_resample_keeps_peaks():
    assert audio.resample([0, 1, 0, 0], 2) == [1, 0]
    assert len(audio.resample([0.5] * 3, 10)) == 10
    assert audio.resample([], 3) == [0.0, 0.0, 0.0]


def test_smooth_rises_faster_than_it_falls():
    up = audio.smooth([0.0], [1.0])[0]
    down = audio.smooth([1.0], [0.0])[0]
    assert up > 1.0 - down


def test_parse_cava_line():
    assert audio.parse_cava_line("0;500;1000;\n") == [0.0, 0.5, 1.0]


def test_draw_levels_all_styles():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 80)
    cr = cairo.Context(surface)
    for style in ("wave", "bars", "dots"):
        audio.draw_levels(cr, [0.2, 0.8, 0.5], 0, 0, 200, 80, style, (1, 0, 0, 1),
                          dim=(1, 1, 1, 0.5))
        audio.draw_levels(cr, [], 0, 0, 200, 80, style, (1, 0, 0, 1))


def test_new_widgets_are_registered():
    for key in ("visualizer", "clock-ring", "clock-stacked", "media-round"):
        assert key in widget_sdk.WIDGET_TYPES, key


def test_interpolate_hits_the_ends():
    out = audio.interpolate([0.0, 1.0], 5)
    assert out == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert audio.interpolate([], 2) == [0.0, 0.0]
