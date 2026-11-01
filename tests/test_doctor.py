"""drivion --doctor."""

from drivion.config import AppConfig, load_secrets
from drivion.doctor import Status, print_report, run_checks
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
