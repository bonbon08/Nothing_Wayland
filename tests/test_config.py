import copy
import json
import os

import pytest

from nothing_de import config
from nothing_de.theme import PALETTES


def test_deep_merge_merges_nested_dicts_without_mutating_inputs():
    base = {"a": 1, "dock": {"icon_size": 48, "pinned": ["x"]}}
    over = {"dock": {"icon_size": 64}, "b": 2}
    base_copy = copy.deepcopy(base)

    merged = config.deep_merge(base, over)

    assert merged == {"a": 1, "dock": {"icon_size": 64, "pinned": ["x"]}, "b": 2}
    assert base == base_copy
    assert over == {"dock": {"icon_size": 64}, "b": 2}


def test_deep_merge_replaces_lists_instead_of_merging_them():
    merged = config.deep_merge({"pinned": ["a", "b"]}, {"pinned": ["c"]})
    assert merged["pinned"] == ["c"]


def test_deep_merge_accepts_missing_override():
    assert config.deep_merge(config.DEFAULTS, None) == config.DEFAULTS


def test_defaults_are_consistent():
    for _name, hex_color in config.ACCENTS:
        assert hex_color.startswith("#") and len(hex_color) == 7, hex_color
    assert config.DEFAULTS["accent"] in [c for _n, c in config.ACCENTS]
    assert config.DEFAULTS["theme"] in PALETTES
    assert config.DEFAULTS["icons"] in ("nothing", "original")
    assert config.DEFAULTS["wallpaper_fit"] in ("cover", "contain", "fill")
    assert config.DEFAULTS["keyboard"]["layout"]  # Standard-Layout darf nie leer sein


def test_bundled_wallpapers_exist():
    assert os.path.isfile(config.DEFAULTS["wallpaper"])
    assert os.path.isdir(config.WALLPAPER_DIR)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Config-Datei in einem Temp-Verzeichnis, damit nichts im echten Profil landet."""
    cfg_dir = tmp_path / "nothing-de"
    monkeypatch.setattr(config, "CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(config, "CONFIG_PATH", str(cfg_dir / "config.json"))
    return cfg_dir / "config.json"


def test_new_config_writes_defaults_to_disk(isolated_config):
    cfg = config.Config()
    assert isolated_config.exists()
    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["accent"] == cfg.get("accent")


def test_set_and_get_nested_value_roundtrip(isolated_config):
    cfg = config.Config()
    cfg.set("dock.icon_size", 56)
    cfg.set("outputs.DP-1", {"scale": 1.5})

    reloaded = config.Config()
    assert reloaded.get("dock.icon_size") == 56
    assert reloaded.get("outputs.DP-1") == {"scale": 1.5}
    assert reloaded.get("dock.launcher") == "left"  # nicht gesetzte Werte bleiben


def test_get_returns_default_for_unknown_path(isolated_config):
    cfg = config.Config()
    assert cfg.get("does.not.exist", "fallback") == "fallback"
    assert cfg.get("accent.too.deep") is None  # Skalar, kein Dict


def test_set_emits_changed_only_when_value_differs(isolated_config):
    cfg = config.Config()
    calls = []
    cfg.connect("changed", lambda *_: calls.append(1))

    cfg.set("dnd", True)
    cfg.set("dnd", True)  # gleicher Wert: kein Signal, kein Schreiben
    cfg.set("dnd", False)

    assert len(calls) == 2


def test_set_without_notify_is_silent(isolated_config):
    cfg = config.Config()
    calls = []
    cfg.connect("changed", lambda *_: calls.append(1))
    cfg.set("notes", "hallo", notify=False)
    assert calls == []
    assert cfg.get("notes") == "hallo"


def test_unreadable_file_falls_back_to_defaults(isolated_config, capsys):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text("{ kaputt", encoding="utf-8")

    cfg = config.Config()

    assert cfg.get("accent") == config.DEFAULTS["accent"]
    assert "config unreadable" in capsys.readouterr().out


def test_partial_file_keeps_defaults_for_missing_keys(isolated_config):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({"accent": "#2F6BFF"}), encoding="utf-8")

    cfg = config.Config()

    assert cfg.get("accent") == "#2F6BFF"
    assert cfg.get("dock.icon_size") == 48


def test_first_available_picks_first_installed_command():
    assert config.first_available("nothing-does-not-exist-xyz", "sh") == "sh"
    assert config.first_available("nothing-does-not-exist-xyz") is None
    assert config.first_available("", None) is None


def test_terminal_command_prefers_configured_terminal(isolated_config):
    cfg = config.Config()
    cfg.set("terminal", "sh -c true", notify=False)
    assert config.terminal_command(cfg) == "sh -c true"
