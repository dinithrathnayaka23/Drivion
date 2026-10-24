from drivion.app import EXIT_CONFIG_ERROR, EXIT_OK, main
from drivion.config import paths


def test_check_config_with_defaults(tmp_path, capsys):
    code = main(["--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env"),
                 "--check-config"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Configuration OK" in out
    assert "LLM key configured      : False" in out
    assert (paths.log_dir() / "drivion.log").exists()


def test_invalid_config_exits_with_error_and_no_ui(tmp_path, capsys):
    bad = tmp_path / "settings.toml"
    bad.write_text("[face]\nsimilarity_threshold = 7\n", encoding="utf-8")
    code = main(["--config", str(bad), "--check-config"])
    assert code == EXIT_CONFIG_ERROR
    assert "face.similarity_threshold" in capsys.readouterr().err


def test_check_config_does_not_print_secret(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("DRIVION_LLM_API_KEY=very-private-key-123\n", encoding="utf-8")
    main(["--config", str(tmp_path / "none.toml"), "--env-file", str(env), "--check-config"])
    out = capsys.readouterr().out
    assert "very-private-key-123" not in out
    assert "LLM key configured      : True" in out


def test_data_dir_respects_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVION_DATA_DIR", str(tmp_path / "x"))
    assert paths.data_dir() == tmp_path / "x"
