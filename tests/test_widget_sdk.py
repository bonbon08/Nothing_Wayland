import textwrap

import pytest

from nothing_de import config, widget_sdk
from nothing_de import widgets  # noqa: F401  (Import registriert die Standard-Widgets)


@pytest.fixture
def registry_snapshot():
    """Registrierung nach dem Test zurücksetzen, damit Tests sich nicht beeinflussen."""
    saved = dict(widget_sdk.WIDGET_TYPES)
    yield
    widget_sdk.WIDGET_TYPES.clear()
    widget_sdk.WIDGET_TYPES.update(saved)


def test_builtin_widgets_are_registered():
    for spec in config.DEFAULTS["widgets"]:
        assert spec["type"] in widget_sdk.WIDGET_TYPES, spec["type"]


def test_every_registered_widget_has_a_known_size():
    for key, cls in widget_sdk.WIDGET_TYPES.items():
        assert cls.TYPE == key
        assert cls.SIZE in widget_sdk.SIZES, (key, cls.SIZE)
        assert cls.NAME, f"{key} braucht einen Anzeigenamen"


def test_register_widget_requires_a_type():
    class Nameless:
        TYPE = ""

    with pytest.raises(TypeError):
        widget_sdk.register_widget(Nameless)


def test_register_widget_adds_to_registry(registry_snapshot):
    class Hello:
        TYPE = "test-hello"
        NAME = "Hallo"

    assert widget_sdk.register_widget(Hello) is Hello
    assert widget_sdk.WIDGET_TYPES["test-hello"] is Hello


def test_user_widget_example_from_docs_loads(tmp_path, registry_snapshot):
    (tmp_path / "hello.py").write_text(textwrap.dedent('''\
        from nothing_widget_sdk import DesktopWidget, register_widget

        @register_widget
        class HelloWidget(DesktopWidget):
            TYPE = "test-user-hello"
            NAME = "Hallo"
            SIZE = "small"
            REFRESH = 5
        '''), encoding="utf-8")

    widget_sdk.load_user_widgets(str(tmp_path))

    cls = widget_sdk.WIDGET_TYPES["test-user-hello"]
    assert cls.NAME == "Hallo"
    assert issubclass(cls, widget_sdk.DesktopWidget)


def test_broken_user_widget_does_not_stop_the_others(tmp_path, registry_snapshot, capsys):
    (tmp_path / "a_kaputt.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    (tmp_path / "b_gut.py").write_text(textwrap.dedent('''\
        from nothing_widget_sdk import DesktopWidget, register_widget

        @register_widget
        class Gut(DesktopWidget):
            TYPE = "test-gut"
            NAME = "Gut"
        '''), encoding="utf-8")

    widget_sdk.load_user_widgets(str(tmp_path))

    assert "test-gut" in widget_sdk.WIDGET_TYPES
    out = capsys.readouterr().out
    assert "cannot load widget" in out and "a_kaputt.py" in out


def test_missing_user_widget_folder_is_fine(tmp_path, registry_snapshot):
    before = set(widget_sdk.WIDGET_TYPES)
    widget_sdk.load_user_widgets(str(tmp_path / "gibt-es-nicht"))
    assert set(widget_sdk.WIDGET_TYPES) == before
