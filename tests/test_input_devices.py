"""Erkennung von Tastatur und Touchscreen aus /proc/bus/input/devices."""
import struct

from nothing_de import system



def word(value):
    return format(value, "x")


def block(name, handlers, key=0, abs_=0, prop=0):
    return (f'I: Bus=0003 Vendor=0001 Product=0001 Version=0001\n'
            f'N: Name="{name}"\nH: Handlers={handlers}\n'
            f'B: PROP={word(prop)}\nB: EV=1b\nB: KEY={word(key)}\nB: ABS={word(abs_)}\n')


LETTERS = sum(1 << k for k in system._LETTER_KEYS)
POWER_KEYS = (1 << 116) | (1 << 114) | (1 << 115)      # power, volume down/up
MT_X = 1 << 0x35


def devices(tmp_path, *blocks):
    path = tmp_path / "devices"
    path.write_text("\n".join(blocks))
    return system.input_devices(str(path))


def test_bitmap_with_several_words():
    # the low word comes last: "1 0" sets bit `word width`
    assert system._bits("1 0") == 1 << (struct.calcsize("l") * 8)


def test_pc_keyboard_is_found(tmp_path):
    devs = devices(tmp_path, block("AT Translated Set 2 keyboard", "sysrq kbd event0", key=LETTERS))
    assert system.has_hardware_keyboard(devs)
    assert not system.has_touchscreen(devs)


def test_phone_buttons_are_no_keyboard(tmp_path):
    devs = devices(tmp_path,
                   block("gpio-keys", "kbd event1", key=POWER_KEYS),
                   block("touchscreen", "event2", abs_=MT_X, prop=1))
    assert not system.has_hardware_keyboard(devs)
    assert system.has_touchscreen(devs)


def test_touchpad_is_no_touchscreen(tmp_path):
    # touchpads report multi-touch too, but not INPUT_PROP_DIRECT
    devs = devices(tmp_path, block("Touchpad", "mouse0 event3", abs_=MT_X, prop=1 << 2))
    assert not system.has_touchscreen(devs)


def test_missing_file_means_no_devices(tmp_path):
    assert system.input_devices(str(tmp_path / "nope")) == []
