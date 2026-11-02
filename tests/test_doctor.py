"""drivion --doctor."""

import os
from unittest.mock import patch

from drivion.config import AppConfig, load_secrets
from drivion.core.autostart import Autostart
from drivion.doctor import SELF_TESTS, Status, _start_at_login, print_report, run_checks, run_self_test
from drivion.vision.templates import TemplateStore


def report(tmp_path, config=None, secrets=None):
    secrets = secrets or load_secrets(tmp_path / ".env")
    checks = run_checks(config or AppConfig(), secrets, hardware=False,
                        store=TemplateStore(tmp_path / "face"), models=tmp_path / "models")
    return {c.name: c for c in checks}


def test_doctor_on_a_fresh_install_lists_each_fix(tmp_path):
    checks = report(tmp_path)
    assert checks["Wake word"].status is Status.FAIL and "--download-models" in checks["Wake word"].fix
    assert "--download-models" in checks["Speech recognition"].fix
    assert "--enroll-face" in checks["Face enrollment"].fix
    assert checks["AI providers"].status is Status.WARN
    assert checks["Liveness check"].status is Status.OK


def test_doctor_warns_when_liveness_is_off(tmp_path):
    config = AppConfig.model_validate({"face": {"liveness_mode": "none"}})
    assert report(tmp_path, config)["Liveness check"].status is Status.WARN


def test_doctor_reports_damaged_templates(tmp_path):
    (tmp_path / "face").mkdir()
    (tmp_path / "face" / "templates.bin").write_bytes(b"garbage")
    check = report(tmp_path)["Face enrollment"]
    assert check.status is Status.FAIL and "--enroll-face" in check.fix


def test_doctor_never_shows_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DRIVION_GROQ_API_KEY=very-private-key-123\n", encoding="utf-8")
    lines = []
    print_report(list(report(tmp_path, secrets=load_secrets(env)).values()), lines.append)
    text = "\n".join(lines)
    assert "very-private-key-123" not in text and "keys set: groq" in text


def test_doctor_exit_status(tmp_path, capsys):
    from drivion import app

    assert app.main(["--config", str(tmp_path / "none.toml"), "--doctor"]) == app.EXIT_ERROR
    assert "problem(s) to fix" in capsys.readouterr().out


def test_start_at_login_check(tmp_path):
    autostart = Autostart()
    assert _start_at_login(autostart).detail == "off"
    autostart.enable()
    assert _start_at_login(autostart).detail == "on"
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, os.environ["DRIVION_AUTOSTART_KEY"], 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Drivion", 0, winreg.REG_SZ, '"C:\\old\\DrivionApp.exe"')
    check = _start_at_login(autostart)
    assert check.status is Status.WARN and "--autostart on" in check.fix
    autostart.disable()


def test_self_test_reports_every_failure_and_carries_on(tmp_path):
    def broken(config, models):
        raise RuntimeError("no such library")

    tests = {"One": broken, "Two": lambda config, models: "fine"}
    with patch.dict(SELF_TESTS, tests, clear=True):
        checks = run_self_test(AppConfig(), tmp_path)
    assert [(c.name, c.status) for c in checks] == [("One", Status.FAIL), ("Two", Status.OK)]
    assert "no such library" in checks[0].detail


def test_self_test_without_models_fails_cleanly(tmp_path):
    checks = {c.name: c.status for c in run_self_test(AppConfig(), tmp_path / "empty")}
    assert checks["Wake word engine"] is Status.FAIL
    assert checks["Speech recognition"] is Status.FAIL
    assert checks["Face engine"] is Status.FAIL
