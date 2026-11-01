"""Prüft, dass alle Dateien syntaktisch in Ordnung sind und das Paket vollständig importiert."""
import glob
import importlib
import os
import py_compile
import shutil
import subprocess

import pytest

from conftest import ROOT

PY_FILES = sorted(glob.glob(os.path.join(ROOT, "shell", "nothing_de", "*.py")))
SHELL_SCRIPTS = [
    "bin/nothing-session", "bin/nothing-session-start", "bin/nothing-settings",
    "bin/nothing-shell", "install.sh", "tools/vm-test.sh",
]
# Session-Dateien werden ausgenommen: desktop-file-validate meldet „DesktopNames“, ein in
# Session-Dateien übliches Feld (GNOME, Plasma), als unbekannt.
DESKTOP_FILES = sorted(p for p in glob.glob(os.path.join(ROOT, "data", "**", "*.desktop"), recursive=True)
                       if os.sep + "sessions" + os.sep not in p)


def module_names():
    return [os.path.splitext(os.path.basename(p))[0] for p in PY_FILES]


@pytest.mark.parametrize("path", PY_FILES, ids=os.path.basename)
def test_python_file_compiles(path, tmp_path):
    py_compile.compile(path, cfile=str(tmp_path / "out.pyc"), doraise=True)


@pytest.mark.parametrize("name", module_names())
def test_module_imports(name):
    importlib.import_module(f"nothing_de.{name}")


def test_nothing_msg_compiles(tmp_path):
    py_compile.compile(os.path.join(ROOT, "bin", "nothing-msg"),
                       cfile=str(tmp_path / "msg.pyc"), doraise=True)


@pytest.mark.parametrize("script", SHELL_SCRIPTS)
def test_shell_script_has_valid_syntax(script):
    result = subprocess.run(["sh", "-n", os.path.join(ROOT, script)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("desktop-file-validate"), reason="desktop-file-validate fehlt")
@pytest.mark.parametrize("path", DESKTOP_FILES, ids=os.path.basename)
def test_desktop_entry_is_valid(path):
    result = subprocess.run(["desktop-file-validate", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_script_in_bin_is_covered():
    bin_files = {f"bin/{os.path.basename(p)}" for p in glob.glob(os.path.join(ROOT, "bin", "*"))}
    covered = set(SHELL_SCRIPTS) | {"bin/nothing-msg"}
    assert bin_files <= covered, bin_files - covered
