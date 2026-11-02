"""The packaged build's paths."""

import subprocess
import sys
from pathlib import Path

from drivion import app
from drivion.config import paths


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


def test_config_errors_are_shown_when_there_is_no_console(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr("ctypes.windll.user32.MessageBoxW", lambda _, text, *rest: shown.append(text))
    bad = tmp_path / "settings.toml"
    bad.write_text("[face]\nsimilarity_threshold = 7\n", encoding="utf-8")
    assert app.main(["--config", str(bad), "--check-config"]) == app.EXIT_CONFIG_ERROR
    assert "face.similarity_threshold" in shown[0]
