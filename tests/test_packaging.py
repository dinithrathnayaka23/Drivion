"""The packaged build's paths, and start at login."""

import subprocess
import sys
from pathlib import Path

import pytest

from drivion import app
from drivion.config import paths
from drivion.core.autostart import Autostart


def test_source_runs_keep_user_files_in_the_project(tmp_path):
    assert paths.user_files_dir(frozen=False) == paths.PROJECT_ROOT


def test_packaged_builds_keep_user_files_in_the_data_folder():
    assert paths.user_files_dir(frozen=True) == paths.data_dir()


def test_packaged_build_relaunches_the_program_without_a_console(monkeypatch):
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Drivion\drivion.exe")
    assert paths.launch_command("--enroll-face") == [str(Path(r"C:\Program Files\Drivion\DrivionApp.exe")),
                                                     "--enroll-face"]


def test_source_run_relaunches_with_python_without_a_console(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert paths.launch_command() == [str(tmp_path / "pythonw.exe"), "-m", "drivion"]


def test_autostart_starts_off_and_can_be_turned_on_and_off():
    autostart = Autostart()
    assert not autostart.is_enabled()
    autostart.enable()
    assert autostart.is_enabled() and autostart.is_current()
    autostart.disable()
    autostart.disable()  # turning it off twice is fine
    assert not autostart.is_enabled()


def test_autostart_command_survives_spaces_in_the_path(monkeypatch):
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Drivion\drivion.exe")
    assert Autostart.command() == r'"C:\Program Files\Drivion\DrivionApp.exe"'


def test_autostart_never_uses_the_real_key_in_tests():
    assert "CurrentVersion" not in Autostart()._key_path


@pytest.mark.parametrize("choice, expected", [("status", "off"), ("on", "on"), ("off", "off")])
def test_autostart_option(choice, expected, tmp_path, capsys):
    code = app.main(["--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env"),
                     "--autostart", choice])
    assert code == app.EXIT_OK
    assert capsys.readouterr().out.strip().endswith(f"Start at login: {expected}")


def test_config_errors_are_shown_when_there_is_no_console(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr("ctypes.windll.user32.MessageBoxW", lambda _, text, *rest: shown.append(text))
    bad = tmp_path / "settings.toml"
    bad.write_text("[face]\nsimilarity_threshold = 7\n", encoding="utf-8")
    assert app.main(["--config", str(bad), "--check-config"]) == app.EXIT_CONFIG_ERROR
    assert "face.similarity_threshold" in shown[0]


def test_build_recipe_bundles_no_user_files():
    recipe = (paths.PROJECT_ROOT / "packaging" / "drivion.spec").read_text(encoding="utf-8")
    code = "\n".join(line for line in recipe.splitlines() if not line.startswith("#"))
    assert ".env" not in code and "settings" not in code and "models" not in code
