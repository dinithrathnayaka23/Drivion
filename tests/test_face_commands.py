"""The face commands: --delete-face and --test-face."""

import sys

import pytest

import face_fakes as ff
from drivion.vision.templates import FaceTemplates, TemplateStore

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")



@windows_only
def test_delete_face_command(tmp_path, capsys):
    from drivion import app
    from drivion.config import paths

    store = TemplateStore(paths.face_dir())
    store.save(FaceTemplates(ff.owner_templates(), "m"))
    assert app.main(["--config", str(tmp_path / "none.toml"), "--delete-face", "--yes"]) == app.EXIT_OK
    assert not store.exists()
    assert "deleted" in capsys.readouterr().out


def test_delete_face_asks_first(tmp_path, monkeypatch, capsys):
    from drivion import app
    from drivion.config import paths

    paths.face_dir().mkdir(parents=True)
    (paths.face_dir() / "templates.bin").write_bytes(b"x")
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert app.main(["--config", str(tmp_path / "none.toml"), "--delete-face"]) == app.EXIT_ERROR
    assert (paths.face_dir() / "templates.bin").exists()


def test_test_face_needs_an_enrollment(tmp_path, capsys):
    from drivion import app

    assert app.main(["--config", str(tmp_path / "none.toml"), "--test-face"]) == app.EXIT_ERROR
    assert "--enroll-face" in capsys.readouterr().err
