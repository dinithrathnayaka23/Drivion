import os
import subprocess
import sys
import time

import pytest

from drivion.app import EXIT_ALREADY_RUNNING, EXIT_CONFIG_ERROR, EXIT_OK, main
from drivion.config import paths
from drivion.core.single_instance import SingleInstanceLock, instance_id

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")


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


@windows_only
def test_second_launch_exits_when_already_running(qapp, tmp_path, capsys):
    with SingleInstanceLock(instance_id()) as held:
        assert held.acquired
        code = main(["--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env")])
    assert code == EXIT_ALREADY_RUNNING
    assert "already running" in capsys.readouterr().out


def _wait_for_log(log_file, text, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_file.exists() and text in log_file.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(0.1)
    return False


@windows_only
def test_two_real_processes_only_one_runs(tmp_path):
    """Integration: launch Drivion twice as separate processes."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    cmd = [sys.executable, "-m", "drivion",
           "--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env")]
    log_file = paths.log_dir() / "drivion.log"

    first = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        assert _wait_for_log(log_file, "Drivion running"), "first instance never started"

        second = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        assert second.returncode == EXIT_ALREADY_RUNNING
        assert "asked it to open" in second.stdout

        assert _wait_for_log(log_file, "Activation requested by another Drivion launch")
        assert first.poll() is None  # the first instance is unaffected
    finally:
        first.kill()
        first.wait(10)
        first.stdout.close()
